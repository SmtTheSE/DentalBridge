from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
import os

def create_pdf(filename, patient_name, date, items):
    c = canvas.Canvas(filename, pagesize=letter)
    width, height = letter
    
    # Header
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 50, "DentalBridge Clinic")
    c.setFont("Helvetica", 12)
    c.drawString(50, height - 70, "123 Smile Way, Yangon, Myanmar")
    c.drawString(50, height - 100, f"Patient: {patient_name}")
    c.drawString(50, height - 120, f"Date: {date}")
    
    c.line(50, height - 140, width - 50, height - 140)
    
    # Table Header
    y = height - 170
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, "Code")
    c.drawString(120, y, "Description")
    c.drawString(450, y, "Fee")
    y -= 20
    c.line(50, y + 10, width - 50, y + 10)
    
    # Items
    c.setFont("Helvetica", 10)
    total = 0
    for item in items:
        code, desc, fee = item
        c.drawString(50, y, code)
        c.drawString(120, y, desc)
        c.drawString(450, y, f"${fee:,.2f}")
        total += fee
        y -= 20
        
    y -= 10
    c.line(50, y, width - 50, y)
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(50, y, f"Total Estimated: ${total:,.2f}")
    
    c.save()
    print(f"Generated: {filename}")

def main():
    # Scenario 1: High Cost / Structural
    create_pdf(
        "test_implant.pdf", 
        "U Kyaw Kyaw", 
        "2026-02-01",
        [
            ("D6010", "Surgical Placement of Implant Body: Endosteal Implant", 2500.00),
            ("D6058", "Abutment supported porcelain/ceramic crown", 1500.00),
            ("D0360", "Cone Beam CT - Craniofacial Data Capture", 350.00)
        ]
    )

    # Scenario 2: High Urgency / Infection
    create_pdf(
        "test_root_canal.pdf", 
        "Daw Mya Mya", 
        "2026-02-02",
        [
            ("D0140", "Limited Oral Evaluation - Problem Focused", 80.00),
            ("D0220", "Intraoral - Periapical First Radiographic Image", 35.00),
            ("D3330", "Endodontic Therapy, Molar (Release of infection)", 1200.00),
            ("D2950", "Core Buildup, including any pins", 250.00)
        ]
    )

    # Scenario 3: Routine / Low Urgency
    create_pdf(
        "test_cleaning.pdf", 
        "Mg Aung Aung", 
        "2026-02-03",
        [
            ("D0120", "Periodic Oral Evaluation - Established Patient", 65.00),
            ("D1110", "Prophylaxis - Adult", 115.00),
            ("D1206", "Topical Application of Fluoride Varnish", 45.00)
        ]
    )
    
    # Scenario 4: Mixed / Ortho
    create_pdf(
        "test_braces.pdf", 
        "Ma Hla Hla", 
        "2026-02-04",
        [
            ("D8080", "Comprehensive Orthodontic Treatment of Adolescent Dentition", 4500.00),
            ("D8660", "Pre-orthodontic Treatment Examination to Monitor Growth", 150.00)
        ]
    )

if __name__ == "__main__":
    main()
