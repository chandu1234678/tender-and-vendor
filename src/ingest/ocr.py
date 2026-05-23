
import pytesseract
from PIL import Image
import fitz
from pathlib import Path
from typing import Optional
import os


# Allow override via environment variable (bytes). Defaults to 50 MB.
try:
    MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", 50 * 1024 * 1024))
except Exception:
    MAX_PDF_BYTES = 50 * 1024 * 1024


def ocr_pdf_if_needed(pdf_path: str) -> Optional[str]:
    """Run OCR on all pages and return concatenated text. Requires Tesseract installed.

    If pages are digital (contain text), this function will still run OCR but caller may choose otherwise.
    """
    p = Path(pdf_path)
    if not p.exists():
        return None
    if p.stat().st_size > MAX_PDF_BYTES:
        # avoid resource exhaustion on huge files
        return None

    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None

    texts = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img)
        texts.append(text)
    return "\n".join(texts)
