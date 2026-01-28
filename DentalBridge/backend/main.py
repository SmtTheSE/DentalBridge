from fastapi import FastAPI, HTTPException, UploadFile, File, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import io
import json
import logging
import pdfplumber
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
from sqlalchemy.orm import Session
from database import engine, SessionLocal, Base, TreatmentPlan, PlanItem
from dotenv import load_dotenv
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Create tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="DentalBridge API")

@app.on_event("startup")
async def startup_event():
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        genai.configure(api_key=api_key)
        try:
            logger.info("Listing available Gemini Models:")
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    logger.info(f"- {m.name}")
        except Exception as e:
            logger.error(f"Failed to list models: {e}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic Models for API
class DentalItemPydantic(BaseModel):
    code: str = Field(..., description="The dental procedure code")
    technical_name: str = Field(..., description="Technical name")
    friendly_name: str = Field(..., description="Patient-friendly name")
    explanation: str = Field(..., description="Simple explanation")
    urgency: str = Field(..., description="Urgency: High, Medium, Low")
    price: Optional[float] = Field(None, description="Cost")
    urgency_hook: Optional[str] = Field(None, description="Persuasive text")

class SavePlanRequest(BaseModel):
    items: List[DentalItemPydantic]
    patient_name: str = "Unknown Patient"

# System Prompt
SYSTEM_PROMPT = """
ROLE: You are a compassionate, top-tier Dental Treatment Coordinator serving patients in Myanmar.

TASK: Analyze the raw dental line items.

CONVERSION RULES:
1. Simplify: "Prophylaxis" -> "Professional Cleaning".
2. Visualize: "Composite - 2 Surfaces" -> "Tooth-Colored Filling (repairing the decay)".
3. Urgency: If the code relates to infection (Root Canal) or structural failure (Crown), mark urgency as "High".
4. Tone: Helpful, not salesy. Focus on "saving the tooth."
5. Language: 
   - Keep 'technical_name' in English (standard medical practice).
   - Translate 'friendly_name', 'explanation', and 'urgency_hook' into natural, warm, and professional Burmese (Myanmar Language).
   - Ensure the Burmese translation is encouraging and easy to understand for laypeople.

OUTPUT: Return a purely JSON list of objects matching the Schema. Key names: code, technical_name, friendly_name, explanation, urgency, price, urgency_hook.
"""

def extract_text_from_pdf(file_bytes: bytes) -> str:
    text = ""
    try:
        # 1. Try text extraction
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        
        # 2. OCR Fallback if text is sparse
        if len(text.strip()) < 50:
            logger.info("Text extraction yielded little data. Attempting OCR...")
            try:
                images = convert_from_bytes(file_bytes)
                for img in images:
                    text += pytesseract.image_to_string(img) + "\n"
            except Exception as ocr_error:
                logger.error(f"OCR Error (pytesseract/pdf2image): {ocr_error}")
                # Fallback to keep existing text if partial
                
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
    return text

def extract_text_from_image(file_bytes: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(file_bytes))
        text = pytesseract.image_to_string(image)
        return text
    except Exception as e:
        logger.error(f"Error extracting text from image: {e}")
        return ""

async def call_llm(text: str) -> List[DentalItemPydantic]:
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not found. Returning Mock Data.")
        return [
            DentalItemPydantic(
                code="D2740",
                technical_name="Crown - Porcelain/Ceramic",
                friendly_name="Tooth Armor / Custom Cap",
                explanation="Your tooth is cracked. This cap holds it together.",
                urgency="High",
                price=1200.0,
                urgency_hook="High Risk: A split tooth cannot be fixed."
            )
        ]

    genai.configure(api_key=api_key)
    
    async def try_generate(model_name: str, use_json_mode: bool):
        logger.info(f"Attempting LLM with model: {model_name}, json_mode: {use_json_mode}")
        try:
            model = genai.GenerativeModel(model_name)
            config = {"response_mime_type": "application/json"} if use_json_mode else {}
            
            full_prompt = f"{SYSTEM_PROMPT}\n\nHere is the dental plan text:\n\n{text}"
            
            response = await model.generate_content_async(
                full_prompt,
                generation_config=config
            )
            return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            return None

    # Strategy 1: Gemini 2.0 Flash (Newest, Fast)
    content = await try_generate("gemini-2.0-flash", True)
    
    # Strategy 2: Gemini Flash Latest (Stable Alias)
    if not content:
        content = await try_generate("gemini-flash-latest", True)

    # Strategy 3: Gemini 1.5 Flash (Fallback if 2.0 fails/unavailable)
    if not content:
        content = await try_generate("gemini-1.5-flash", True)
        
    if not content:
        logger.error("All Gemini models failed.")
        return []

    try:
        # Clean up code blocks if legacy model adds them
        clean_content = content.replace("```json", "").replace("```", "")
        data = json.loads(clean_content)
        
        items_data = []
        if isinstance(data, dict):
            if "items" in data:
                items_data = data["items"]
        elif isinstance(data, list):
            items_data = data
            
        cleaned_items = []
        for item in items_data:
            # Fix Price: Remove $ and , and convert to float
            if "price" in item and isinstance(item["price"], str):
                try:
                    price_str = item["price"].replace("$", "").replace(",", "").strip()
                    item["price"] = float(price_str) if price_str else 0.0
                except ValueError:
                    item["price"] = 0.0 # Fallback
            
            cleaned_items.append(DentalItemPydantic(**item))
            
        return cleaned_items

    except Exception as e:
        logger.error(f"JSON Parse Error: {e} \nContent: {content}")
        return []

@app.post("/save-plan")
async def save_plan(items: List[DentalItemPydantic], db: Session = Depends(get_db)):
    # Create Plan
    db_plan = TreatmentPlan(patient_name="Unknown Patient")
    db.add(db_plan)
    db.flush() # get ID

    # Create Items
    for item in items:
        db_item = PlanItem(
            plan_id=db_plan.id,
            code=item.code,
            technical_name=item.technical_name,
            friendly_name=item.friendly_name,
            explanation=item.explanation,
            urgency=item.urgency,
            price=item.price,
            urgency_hook=item.urgency_hook
        )
        db.add(db_item)
    
    db.commit()
    return {"plan_id": db_plan.id, "url": f"/p/{db_plan.id}"}

@app.get("/plan/{plan_id}", response_model=List[DentalItemPydantic])
async def get_plan(plan_id: str, db: Session = Depends(get_db)):
    plan = db.query(TreatmentPlan).filter(TreatmentPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    
    # Convert DB items to Pydantic
    return [
        DentalItemPydantic(
            code=i.code,
            technical_name=i.technical_name,
            friendly_name=i.friendly_name,
            explanation=i.explanation,
            urgency=i.urgency,
            price=i.price,
            urgency_hook=i.urgency_hook
        ) for i in plan.items
    ]

@app.post("/analyze", response_model=List[DentalItemPydantic])
async def analyze_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        logger.info(f"Received file: {file.filename}, size: {len(content)} bytes")
        
        text = ""
        filename = file.filename.lower()
        if filename.endswith(".pdf") or file.content_type == "application/pdf":
            text = extract_text_from_pdf(content)
        elif filename.endswith((".jpg", ".jpeg", ".png", ".heic")) or file.content_type.startswith("image/"):
            text = extract_text_from_image(content)
        
        logger.info(f"Extracted text length: {len(text)}")
        
        if not text.strip():
            text = "No text found."
            logger.warning("No text extracted from PDF.")
            
        result = await call_llm(text)
        return result
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {str(e)}"}
        )

@app.get("/")
def read_root():
    return {"message": "DentalBridge API is running"}
