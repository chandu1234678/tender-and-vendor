
from typing import List, Dict, Optional
from pathlib import Path
import fitz
import os
import logging
import shutil

from PIL import Image
import pytesseract


# Allow override via environment variable (bytes). Defaults to 200 MB.
try:
    MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", 200 * 1024 * 1024))
except Exception:
    MAX_PDF_BYTES = 200 * 1024 * 1024


def _tessdata_dir(cmd_path: Path) -> Optional[Path]:
    if not cmd_path.exists():
        return None
    tessdata = cmd_path.parent / "tessdata"
    if (tessdata / "eng.traineddata").exists():
        return tessdata
    return None


def _set_tesseract(cmd_path: Path) -> bool:
    tessdata = _tessdata_dir(cmd_path)
    if not tessdata:
        return False
    pytesseract.pytesseract.tesseract_cmd = str(cmd_path)
    os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
    return True


def _tesseract_available() -> bool:
    candidates: list[Path] = []
    env_cmd = os.environ.get("TESSERACT_CMD")
    if env_cmd:
        candidates.append(Path(env_cmd))
    local_app = os.environ.get("LOCALAPPDATA")
    if local_app:
        candidates.append(Path(local_app) / "Programs" / "Tesseract-OCR" / "tesseract.exe")
    candidates.extend([
        Path(r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe"),
        Path(r"C:\\Program Files (x86)\\Tesseract-OCR\\tesseract.exe"),
        Path(r"C:\\Program Files\\PDF24\\tesseract\\tesseract.exe"),
    ])

    current_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract")
    if isinstance(current_cmd, str):
        current_path = Path(current_cmd)
        if _set_tesseract(current_path):
            return True

    which_cmd = shutil.which("tesseract")
    if which_cmd and _set_tesseract(Path(which_cmd)):
        return True

    for candidate in candidates:
        if _set_tesseract(candidate):
            return True

    return False


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
    ocr_available = _tesseract_available()
    ocr_skip_logged = False
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
            if not ocr_available:
                if not ocr_skip_logged:
                    logging.warning("OCR skipped for %s: tesseract is not installed or not in PATH", pdf_path)
                    ocr_skip_logged = True
                continue
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
            except Exception as exc:
                logging.warning("OCR failed on page %s of %s: %s", page_no, pdf_path, exc)

        blocks.extend(page_blocks)
    blocks.sort(key=lambda block: (block["page"], block["bbox"][1], block["bbox"][0]))
    return blocks
