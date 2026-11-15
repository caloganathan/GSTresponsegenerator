"""Tests for Google Lens-style OCR boxes/image support and clarifying questions."""

import io
import pytest

from backend import intake, ocr


def test_build_clarifying_questions_for_itc_and_ocr():
    fields = {
        "notice_type": "DRC-01",
        "section_invoked": "Section 74",
        "amount_disputed": 250000.0,
        "facts": "ITC mismatch between GSTR-2B and GSTR-3B for FY 2020-21.",
    }
    sources = {"amount_disputed": "notice-ocr"}
    snippets = {"amount_disputed": {"excerpt": "Total Tax Demand: Rs. 2,50,000"}}
    defects_list = [{"heading": "Excess ITC claimed u/s 16(2)(c)", "summary": "2B vs 3B"}]

    questions = intake.build_clarifying_questions(
        fields=fields,
        sources=sources,
        snippets=snippets,
        defects_list=defects_list,
        scanned=True,
    )
    ids = {q["id"] for q in questions}
    assert "confirm_ocr_amount" in ids
    assert "missing_gstin" in ids
    assert "missing_due_date" in ids
    assert "itc_root_cause" in ids
    assert "section74_intent" in ids
    assert "personal_hearing" in ids
    assert "additional_context" in ids


def test_boxes_from_result_normalizes_coordinates():
    raw = [
        ([[10, 20], [110, 20], [110, 40], [10, 40]], "GSTIN: 29ABCDE1234F1Z5", 0.96),
        ([[200, 100], [300, 100], [300, 120], [200, 120]], "2,50,000", 0.65),
    ]
    boxes = ocr._boxes_from_result(raw, width=1000, height=500)
    assert len(boxes) == 2
    assert boxes[0]["x"] == 0.01
    assert boxes[0]["y"] == 0.04
    assert boxes[0]["w"] == 0.1
    assert boxes[0]["h"] == 0.04
    assert boxes[0]["confidence"] == 0.96
    assert boxes[1]["confidence"] == 0.65


@pytest.mark.skipif(not ocr.available()[0], reason="OCR extra not installed")
def test_ocr_image_extracts_text_and_lens_page():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(img)
    draw.text((40, 60), "GSTIN: 29ABCDE1234F1Z5", fill="black")
    draw.text((40, 130), "FORM GST DRC-01", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")

    result = ocr.ocr_image(buf.getvalue())
    assert result["pages_read"] == 1
    assert len(result["lens_pages"]) == 1
    assert result["lens_pages"][0]["image"].startswith("data:image/jpeg;base64,")
    assert len(result["lens_pages"][0]["boxes"]) >= 1
