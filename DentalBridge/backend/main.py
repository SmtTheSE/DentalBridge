import logging
import os
import io
import json
import sys
from typing import List, Optional

# Configure logging immediately at module level
logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)

logger.info("Starting DentalBridge backend...")

# Core imports
from fastapi import FastAPI, HTTPException, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import google.generativeai as genai

logger.info("Core imports OK")

# PDF imports
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont

logger.info("ReportLab imports OK")

# PDF text extraction
import pdfplumber
from PIL import Image

logger.info("pdfplumber and PIL imports OK")

# Optional: HEIC support
try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    HEIC_AVAILABLE = True
    logger.info("HEIC support: Available")
except ImportError:
    HEIC_AVAILABLE = False
    logger.warning("HEIC support: Not available (pillow-heif not installed)")

# Optional: Myanmar font converter
try:
    import mmfont.converter
    MMFONT_AVAILABLE = True
    logger.info("mmfont: Available")
except ImportError:
    MMFONT_AVAILABLE = False
    logger.warning("mmfont: Not available")

load_dotenv()

# Font setup
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FONTS_DIR = os.path.join(BASE_DIR, "fonts")
ZAWGYI_FONT_PATH = os.path.join(FONTS_DIR, "Zawgyi-One.ttf")

ZAWGYI_AVAILABLE = False
try:
    if os.path.exists(ZAWGYI_FONT_PATH):
        pdfmetrics.registerFont(TTFont('Zawgyi-One', ZAWGYI_FONT_PATH))
        registerFontFamily('Zawgyi-One', normal='Zawgyi-One', bold='Zawgyi-One', italic='Zawgyi-One', boldItalic='Zawgyi-One')
        ZAWGYI_AVAILABLE = True
        logger.info(f"Zawgyi font registered from {ZAWGYI_FONT_PATH}")
    else:
        logger.warning(f"Zawgyi font not found at {ZAWGYI_FONT_PATH}")
except Exception as e:
    logger.error(f"Font registration error: {e}")

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

logger.info("FastAPI app created")

# --- Pydantic Models ---
class DentalItemPydantic(BaseModel):
    code: str = Field(..., description="The dental procedure code")
    technical_name: str = Field(..., description="Technical name")
    friendly_name: str = Field(..., description="Patient-friendly name")
    explanation: str = Field(..., description="Simple explanation")
    urgency: str = Field(..., description="Urgency: High, Medium, Low")
    price: Optional[float] = Field(None, description="Cost")
    urgency_hook: Optional[str] = Field(None, description="Persuasive text")

class PlanContext(BaseModel):
    items: List[DentalItemPydantic]
    patient_name: str = "Unknown Patient"

# --- System Prompt ---
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
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
        if len(text.strip()) < 50:
            logger.warning("Text extraction yielded little data. PDF might be scanned.")
    except Exception as e:
        logger.error(f"Error extracting PDF: {e}")
    return text

async def call_llm(content_parts: list) -> List[DentalItemPydantic]:
    api_key = os.getenv("GEMINI_API_KEY")
    
    if not api_key:
        logger.warning("GEMINI_API_KEY not found. Returning Mock Data.")
        return [DentalItemPydantic(
            code="D2740",
            technical_name="Crown - Porcelain/Ceramic",
            friendly_name="Tooth Armor / Custom Cap",
            explanation="Your tooth is cracked. This cap holds it together.",
            urgency="High",
            price=1200.0,
            urgency_hook="High Risk: A split tooth cannot be fixed."
        )]

    genai.configure(api_key=api_key)
    errors = []

    async def try_generate(model_name: str, use_json_mode: bool):
        logger.info(f"Attempting LLM with model: {model_name}")
        try:
            model = genai.GenerativeModel(model_name)
            config = {"response_mime_type": "application/json"} if use_json_mode else {}
            full_prompt = [SYSTEM_PROMPT] + content_parts
            response = await model.generate_content_async(full_prompt, generation_config=config)
            return response.text
        except Exception as e:
            logger.warning(f"Model {model_name} failed: {e}")
            errors.append(f"{model_name}: {str(e)}")
            return None

    content = await try_generate("gemini-2.0-flash", True)
    if not content:
        content = await try_generate("gemini-1.5-flash-latest", True)
    if not content:
        content = await try_generate("gemini-1.5-pro-latest", True)
        
    if not content:
        logger.error(f"All Gemini models failed. Errors: {errors}")
        raise HTTPException(status_code=500, detail=f"AI Analysis Failed: {'; '.join(errors)}")

    try:
        clean_content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_content)
        
        items_data = []
        if isinstance(data, dict) and "items" in data:
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
        logger.error(f"JSON Parse Error: {e}\nContent: {content}")
        return []

# --- Routes ---
@app.get("/")
def read_root():
    return {"message": "DentalBridge Provider", "status": "ok"}

@app.get("/debug")
def debug_env():
    return {
        "status": "alive",
        "heic_available": HEIC_AVAILABLE,
        "mmfont_available": MMFONT_AVAILABLE,
        "zawgyi_available": ZAWGYI_AVAILABLE,
        "base_dir": BASE_DIR,
        "fonts_dir": FONTS_DIR,
        "fonts_dir_exists": os.path.exists(FONTS_DIR),
        "is_vercel": is_vercel,
        "gemini_key_set": bool(os.getenv("GEMINI_API_KEY")),
    }

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
                logger.warning("No text extracted from PDF.")
            content_parts.append(f"Here is the dental plan text:\n\n{text}")
            
        elif filename.endswith((".jpg", ".jpeg", ".png", ".webp")) or file.content_type.startswith("image/"):
            mime_type = file.content_type if file.content_type else "image/jpeg"
            content_parts.append({'mime_type': mime_type, 'data': content})
            
        elif filename.endswith(".heic"):
            if HEIC_AVAILABLE:
                try:
                    image = Image.open(io.BytesIO(content))
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='JPEG')
                    content_parts.append({'mime_type': 'image/jpeg', 'data': img_byte_arr.getvalue()})
                except Exception as img_err:
                    logger.error(f"HEIC processing: {img_err}")
                    return []
            else:
                logger.warning("HEIC file uploaded but pillow-heif not available.")
                return []
        
        if not content_parts:
            return []

        return await call_llm(content_parts)
        
    except Exception as e:
        logger.error(f"Error in analyze_file: {str(e)}", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": f"Internal Server Error: {str(e)}"})

# --- PDF Generation ---
@app.post("/generate-pdf")
async def generate_pdf(request: PlanContext):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    
    styles = getSampleStyleSheet()
    normal_style = styles["Normal"]
    
    elements.append(Paragraph("Dental Treatment Plan Analysis", styles["Heading1"]))
    elements.append(Spacer(1, 12))
    elements.append(Paragraph(f"<b>Patient Name:</b> {request.patient_name}", normal_style))
    from datetime import datetime
    elements.append(Paragraph(f"<b>Date:</b> {datetime.utcnow().strftime('%Y-%m-%d')}", normal_style))
    elements.append(Spacer(1, 24))
    
    # Use Zawgyi if available, else fallback to Helvetica
    font_name = 'Zawgyi-One' if ZAWGYI_AVAILABLE else 'Helvetica'
    content_style = ParagraphStyle('ContentStyle', parent=normal_style, fontName=font_name, fontSize=10, leading=14)
    
    def to_zawgyi(text):
        if not text:
            return ""
        if MMFONT_AVAILABLE and ZAWGYI_AVAILABLE:
            try:
                return mmfont.converter.uni512zg1(text)
            except Exception:
                pass
        return text

    data = [["Treatment", "Analysis", "Price", "Urgency"]]
    total_price = 0.0
    
    for item in request.items:
        price = item.price or 0.0
        if price:
            total_price += price
        friendly = Paragraph(f"<b>{to_zawgyi(item.friendly_name)}</b><br/><font size=8 color='gray'>{item.technical_name} ({item.code})</font>", content_style)
        explanation = Paragraph(f"{to_zawgyi(item.explanation)}", content_style)
        data.append([friendly, explanation, f"{price:,.0f} MMK" if price else "N/A", item.urgency])

    table = Table(data, colWidths=[2*inch, 3*inch, 1.2*inch, 1*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#2563eb")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
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
    
    safe_name = "".join([c for c in request.patient_name if c.isalpha() or c.isdigit() or c == ' ']).strip().replace(' ', '_') or "Patient"
    filename = f"DentalPlan_{safe_name}.pdf"
    
    return Response(
        content=buffer.getvalue(),
        headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        media_type="application/pdf"
    )
