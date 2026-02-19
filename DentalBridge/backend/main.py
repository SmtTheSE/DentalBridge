from fastapi import FastAPI, HTTPException, UploadFile, File, Response, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import List, Optional
import os
import io
import json
import logging
import pdfplumber
from PIL import Image
import pillow_heif
# Register HEIC opener
pillow_heif.register_heif_opener()

from dotenv import load_dotenv
import google.generativeai as genai

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
import mmfont.converter

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Resolve absolute path for fonts
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
ZAWGYI_FONT_PATH = os.path.join(FONTS_DIR, "Zawgyi-One.ttf")

# Create fonts directory if not exists
if not os.path.exists(FONTS_DIR):
    os.makedirs(FONTS_DIR)
    
# Register Zawgyi Font
try:
    if os.path.exists(ZAWGYI_FONT_PATH):
        pdfmetrics.registerFont(TTFont('Zawgyi-One', ZAWGYI_FONT_PATH))
        registerFontFamily('Zawgyi-One', normal='Zawgyi-One', bold='Zawgyi-One', italic='Zawgyi-One', boldItalic='Zawgyi-One')
        logger.info(f"Zawgyi Font Registered Successfully from {ZAWGYI_FONT_PATH}")
    else:
        logger.warning(f"Zawgyi font not found at {ZAWGYI_FONT_PATH}. Using default font.")
except Exception as e:
    logger.error(f"Failed to register Zawgyi font: {e}")

load_dotenv()

# Determine if running on Vercel
is_vercel = os.environ.get('VERCEL') == '1'
root_path = "/api" if is_vercel else ""

app = FastAPI(title="DentalBridge API (Stateless)", root_path=root_path)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Pydantic Models for API
class DentalItemPydantic(BaseModel):
    code: str = Field(..., description="The dental procedure code")
    technical_name: str = Field(..., description="Technical name")
    friendly_name: str = Field(..., description="Patient-friendly name")
    explanation: str = Field(..., description="Simple explanation")
    urgency: str = Field(..., description="Urgency: High, Medium, Low")
    price: Optional[float] = Field(None, description="Cost")
    urgency_hook: Optional[str] = Field(None, description="Persuasive text")

# Context for PDF (Stateless)
class PlanContext(BaseModel):
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
        # Only plain text extraction for Vercel (No OCR)
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        
        if len(text.strip()) < 50:
            logger.warning("Text extraction yielded little data. PDF might be scanned (OCR required).")
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
    return text

async def call_llm(content_parts: list) -> List[DentalItemPydantic]:
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
    
    errors = []

    async def try_generate(model_name: str, use_json_mode: bool):
        logger.info(f"Attempting LLM with model: {model_name}, json_mode: {use_json_mode}")
        try:
            model = genai.GenerativeModel(model_name)
            config = {"response_mime_type": "application/json"} if use_json_mode else {}
            
            # System Prompt is always the first part
            full_prompt = [SYSTEM_PROMPT] + content_parts
            
            response = await model.generate_content_async(
                full_prompt,
                generation_config=config
            )
            return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            errors.append(f"{model_name}: {str(e)}")
            return None

    # Strategy 1: Gemini 2.0 Flash (Newest, Fast, Vision)
    content = await try_generate("gemini-2.0-flash", True)
    
    # Strategy 2: Gemini Flash Latest (Reliable Vision Fallback)
    if not content:
        content = await try_generate("gemini-flash-latest", True)
        
    # Strategy 3: Gemini 1.5 Pro (Powerful Fallback)
    if not content:
        content = await try_generate("gemini-1.5-pro-latest", True)
        
    if not content:
        logger.error(f"All Gemini models failed. Errors: {errors}")
        raise HTTPException(status_code=500, detail=f"AI Analysis Failed. Models failed: {'; '.join(errors)}")

    try:
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
            if "price" in item and isinstance(item["price"], str):
                try:
                    price_str = item["price"].replace("$", "").replace(",", "").strip()
                    item["price"] = float(price_str) if price_str else 0.0
                except ValueError:
                    item["price"] = 0.0 
            
            cleaned_items.append(DentalItemPydantic(**item))
            
        return cleaned_items

    except Exception as e:
        logger.error(f"JSON Parse Error: {e} \nContent: {content}")
        return []

@app.post("/analyze", response_model=List[DentalItemPydantic])
async def analyze_file(file: UploadFile = File(...)):
    try:
        content = await file.read()
        logger.info(f"Received file: {file.filename}, size: {len(content)} bytes")
        
        content_parts = []
        filename = file.filename.lower()
        
        if filename.endswith(".pdf") or file.content_type == "application/pdf":
            text = extract_text_from_pdf(content)
            if not text.strip():
                logger.warning("No text extracted from PDF. This might be a scan.")
            content_parts.append(f"Here is the dental plan text:\n\n{text}")
            
        elif filename.endswith((".jpg", ".jpeg", ".png", ".heic", ".webp")) or file.content_type.startswith("image/"):
            try:
                if filename.endswith(".heic"):
                    image = Image.open(io.BytesIO(content))
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='JPEG')
                    blob = {'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()}
                    content_parts.append(blob)
                else:
                    mime_type = file.content_type if file.content_type else "image/jpeg"
                    blob = {'mime_type': mime_type, 'data': content}
                    content_parts.append(blob)
            except Exception as img_err:
                logger.error(f"Image processing failed: {img_err}")
                return []
        
        if not content_parts:
             return []

        result = await call_llm(content_parts)
        return result
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal Server Error: {str(e)}"}
        )

@app.get("/")
def read_root():
    return {"message": "DentalBridge Provider"}

@app.get("/debug")
def debug_env():
    import pkg_resources
    installed_packages = [f"{p.project_name}=={p.version}" for p in pkg_resources.working_set]
    
    return {
        "cwd": os.getcwd(),
        "files_in_cwd": os.listdir("."),
        "fonts_dir_exists": os.path.exists(FONTS_DIR),
        "fonts_dir_contents": os.listdir(FONTS_DIR) if os.path.exists(FONTS_DIR) else [],
        "base_dir": BASE_DIR,
        "zawgyi_path": ZAWGYI_FONT_PATH,
        "installed_packages": installed_packages,
        "env_vars": [k for k in os.environ.keys()]
    }

# --- Stateless PDF Generation ---
def build_pdf_buffer(plan_context: PlanContext) -> io.BytesIO:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = styles["Heading1"]
    normal_style = styles["Normal"]
    
    elements.append(Paragraph("Dental Treatment Plan Analysis", title_style))
    elements.append(Spacer(1, 12))
    
    elements.append(Paragraph(f"<b>Patient Name:</b> {plan_context.patient_name}", normal_style))
    from datetime import datetime
    elements.append(Paragraph(f"<b>Date:</b> {datetime.utcnow().strftime('%Y-%m-%d')}", normal_style))
    elements.append(Spacer(1, 24))
    
    # Determine if Zawgyi is available
    font_name = 'Zawgyi-One' if 'Zawgyi-One' in pdfmetrics.getRegisteredFontNames() else 'Helvetica'
    zawgyi_style = ParagraphStyle('ZawgyiStyle', parent=normal_style, fontName=font_name, fontSize=10, leading=14)
    
    def to_zawgyi(text):
        if not text: return ""
        # If we don't have the font, don't convert to weird encoding
        if font_name != 'Zawgyi-One': return text 
        try:
            return mmfont.converter.uni512zg1(text)
        except:
            return text

    data = [["Treatment", "My Analysis (Friendly)", "Price", "Urgency"]]
    total_price = 0.0
    
    for item in plan_context.items:
        price = item.price
        price_display = f"{price:,.0f} MMK" if price else "N/A"
        if price:
            total_price += price
            
        friendly_zg = to_zawgyi(item.friendly_name)
        explanation_zg = to_zawgyi(item.explanation)
        urgency_hook_zg = to_zawgyi(item.urgency_hook or '')

        technical = Paragraph(f"<b>{friendly_zg}</b><br/><font size=8 color='gray'>{item.technical_name} ({item.code})</font>", zawgyi_style)
        explanation = Paragraph(f"{explanation_zg}<br/><br/><i>{urgency_hook_zg}</i>", zawgyi_style)
        
        data.append([technical, explanation, price_display, item.urgency])

    table = Table(data, colWidths=[2*inch, 3*inch, 1.2*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (1, -1), 'Zawgyi-One'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('allowWidows', (0, 0), (-1, -1), 1),
        ('allowOrphans', (0, 0), (-1, -1), 1),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    
    elements.append(table)
    elements.append(Spacer(1, 24))
    elements.append(Paragraph(f"<b>Total Estimated:</b> {total_price:,.0f} MMK", styles["Heading3"]))
    
    doc.build(elements)
    buffer.seek(0)
    return buffer

@app.post("/generate-pdf")
async def generate_pdf(request: PlanContext):
    pdf_buffer = build_pdf_buffer(request)
    
    # Sanitize filename
    safe_name = "".join([c for c in request.patient_name if c.isalpha() or c.isdigit() or c==' ']).strip().replace(' ', '_')
    if not safe_name: safe_name = "Patient"
    filename = f"DentalPlan_{safe_name}.pdf"
    
    headers = {'Content-Disposition': f'attachment; filename="{filename}"'}
    return Response(content=pdf_buffer.getvalue(), headers=headers, media_type="application/pdf")
