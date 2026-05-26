
import pytesseract
from PIL import Image
import fitz
from pathlib import Path
from typing import Optional
import os
import shutil


# Allow override via environment variable (bytes). Defaults to 50 MB.
try:
    MAX_PDF_BYTES = int(os.environ.get("MAX_PDF_BYTES", 50 * 1024 * 1024))
except Exception:
    MAX_PDF_BYTES = 50 * 1024 * 1024


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


def _configure_tesseract() -> bool:
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
    if isinstance(current_cmd, str) and _set_tesseract(Path(current_cmd)):
        return True

    which_cmd = shutil.which("tesseract")
    if which_cmd and _set_tesseract(Path(which_cmd)):
        return True

    for candidate in candidates:
        if _set_tesseract(candidate):
            return True

    return False


def ocr_pdf_if_needed(pdf_path: str) -> Optional[str]:
    """Run OCR on all pages and return concatenated text. Requires Tesseract installed.

    If pages are digital (contain text), this function will still run OCR but caller may choose otherwise.
    """
    if not _configure_tesseract():
        return None
    cmd = Path(getattr(pytesseract.pytesseract, "tesseract_cmd", "tesseract"))
    if cmd.exists():
        tessdata = cmd.parent / "tessdata"
        if tessdata.exists():
            os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
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
