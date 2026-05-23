from pathlib import Path

import fitz

from src.ingest.ocr import ocr_pdf_if_needed
from src.ingest.pdf_parser import parse_pdf_blocks


def _build_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 500), "BOTTOM BLOCK")
    page.insert_text((50, 50), "TOP BLOCK")
    doc.save(str(path))
    doc.close()


def test_parse_pdf_blocks_sorts_top_to_bottom(tmp_path):
    pdf_path = tmp_path / "sample.pdf"
    _build_pdf(pdf_path)

    blocks = parse_pdf_blocks(str(pdf_path))

    texts = [block["text"] for block in blocks]
    assert texts[0] == "TOP BLOCK"
    assert texts[1] == "BOTTOM BLOCK"
    assert blocks[0]["page"] == 1


def test_ocr_pdf_if_needed_returns_text_when_tesseract_is_mocked(tmp_path, monkeypatch):
    pdf_path = tmp_path / "ocr.pdf"
    _build_pdf(pdf_path)

    monkeypatch.setattr("pytesseract.image_to_string", lambda image: "OCR TEXT")

    text = ocr_pdf_if_needed(str(pdf_path))

    assert text == "OCR TEXT"
