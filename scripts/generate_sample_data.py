from pathlib import Path
import pandas as pd
import fitz

ROOT = Path(__file__).resolve().parents[1]
INCOMING = ROOT / "data" / "incoming"
INCOMING.mkdir(parents=True, exist_ok=True)

# create master spec excel
master = INCOMING / "master_spec.xlsx"
df = pd.DataFrame([
    {"Spec_ID": "SPEC-01", "Parameter_Name": "Max Operating Temp", "company_Requirement": "Must withstand at least 600°C continuously."},
    {"Spec_ID": "SPEC-02", "Parameter_Name": "Hydrostatic Pressure", "company_Requirement": "Shell must withstand 60 bar total pressure."},
])
df.to_excel(master, index=False)

# create a sample vendor PDF
pdf_path = INCOMING / "vendor_01.pdf"
doc = fitz.open()
page = doc.new_page()
text = "Operating temperature stable up to 610C. Hydrostatic shell pressure rated at 65 bar. Delivery timeline guaranteed within 10 weeks."
rect = fitz.Rect(50, 50, 560, 800)
page.insert_textbox(rect, text, fontsize=11)
doc.save(str(pdf_path))
print(f"Created sample master spec at: {master}")
print(f"Created sample vendor pdf at: {pdf_path}")
