
from typing import List, Dict
from pathlib import Path
import fitz
import os


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
        for b in page.get_text("blocks"):
            x0, y0, x1, y1, text, block_no, block_type = b
            text = text.strip()
            if not text:
                continue
            blocks.append({"page": page_no, "bbox": [x0, y0, x1, y1], "text": text})
    return blocks
