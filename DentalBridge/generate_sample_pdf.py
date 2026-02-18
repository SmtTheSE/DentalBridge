from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

def create_sample_pdf(filename):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, height - 50, "Dr. Smith's Dental Clinic")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 70, "123 Smile Way, Tooth City")
    c.drawString(50, height - 90, "Patient: John Doe")
    c.drawString(50, height - 110, "Date: Jan 28, 2026")
    
    c.line(50, height - 120, width - 50, height - 120)
    
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, height - 140, "Treatment Plan Details:")
    
    c.setFont("Helvetica", 10)
    y = height - 160
    
    items = [
        "D0150 - Comprehensive Oral Evaluation - $150.00",
        "D0210 - Intraoral - Complete Series of Radiographic Images - $200.00",
        "D1110 - Prophylaxis - Adult - $120.00",
        "D2740 - Crown - Porcelain/Ceramic Substrate - $1,200.00",
        "D3330 - Endodontic Therapy, Molar (excluding final restoration) - $1,100.00"
    ]
    
    for item in items:
        c.drawString(50, y, item)
        y -= 20
        
    c.line(50, y - 10, width - 50, y - 10)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y - 30, "Total Estimated Price: $2,770.00")
    
    c.save()
    print(f"Created {filename}")

if __name__ == "__main__":
    create_sample_pdf("sample_dental_quote.pdf")
