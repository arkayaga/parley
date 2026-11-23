from pathlib import Path

import pytest

from parley import ocr


def test_clean_line():
    assert ocr.clean_line("• Barista :  Hi!How are you?") == "Barista: Hi! How are you?"


def test_merge_rows_joins_label_and_text_on_one_line():
    boxes = [(0.5, 0.10, 0.05, "Good morning!"), (0.05, 0.11, 0.05, "Barista:"), (0.05, 0.30, 0.05, "Customer: Hi.")]
    assert ocr.merge_rows(boxes) == ["Barista: Good morning!", "Customer: Hi."]


@pytest.mark.skipif(not ocr.available(), reason="no OS text recognition here")
def test_reads_fixture_image():
    data = (Path(__file__).parent / "fixtures" / "dialogue.png").read_bytes()
    result = ocr.read_image(data)
    assert result["dialogue"]
    assert result["text"].splitlines()[0].startswith("Barista: Good morning")
