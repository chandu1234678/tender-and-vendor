
from typing import List, Dict
from pathlib import Path
import fitz
import os

from PIL import Image
import pytesseract


# Allow override via environment variable (bytes). Defaults to 50 MB.
try:
    MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", 50 * 1024 * 1024))
except Exception:
    MAX_PDF_BYTES = 50 * 1024 * 1024


def parse_pdf_blocks(pdf_path: str) -> List[Dict]:
    """Extract layout-aware text blocks from a PDF using PyMuPDF.

    Returns a list of dicts: {"page": int, "bbox": [x0,y0,x1,y1], "text": str}
    """
    p = Path(pdf_path)
    if not p.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")
    size = p.stat().st_size
    if size > MAX_PDF_BYTES:
        raise ValueError(f"PDF too large ({size} bytes) — exceeds {MAX_PDF_BYTES} byte limit")

    doc = fitz.open(pdf_path)
    blocks: List[Dict] = []
    for page_no, page in enumerate(doc, start=1):
        page_blocks = []
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = b
            text = text.strip()
            if not text:
                continue
            page_blocks.append({"page": page_no, "bbox": [x0, y0, x1, y1], "text": text})

        if not page_blocks:
            # OCR fallback for scanned pages
            try:
                pix = page.get_pixmap(dpi=200)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                ocr_text = pytesseract.image_to_string(img).strip()
                if ocr_text:
                    page_blocks.append({
                        "page": page_no,
                        "bbox": [0, 0, pix.width, pix.height],
                        "text": ocr_text,
                    })
            except Exception:
                pass

        blocks.extend(page_blocks)
    blocks.sort(key=lambda block: (block["page"], block["bbox"][1], block["bbox"][0]))
    return blocks
