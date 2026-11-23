import pytest

from parley.script import (Turn, decode_text_file, looks_like_dialogue, parse_script, split_pauses,
                           split_text, strip_pauses)


def test_dialogue_with_continuation_lines():
    turns = parse_script("Barista: Hi there!\nWhat can I get you?\n\nCustomer: A latte, please.")
    assert turns == [Turn("Barista", "Hi there! What can I get you?"), Turn("Customer", "A latte, please.")]


def test_url_line_is_not_a_speaker():
    turns = parse_script("Guide: Visit\nhttps://example.com today")
    assert turns == [Turn("Guide", "Visit https://example.com today")]


@pytest.mark.parametrize("text", ["", "   ", "no label first", "Guide:"])
def test_invalid_scripts(text):
    with pytest.raises(ValueError):
        parse_script(text)


def test_speaker_limit():
    text = "\n".join(f"P{i}: hi" for i in range(31))
    with pytest.raises(ValueError):
        parse_script(text)


def test_looks_like_dialogue():
    assert looks_like_dialogue("A: hi\nB: hello")
    assert not looks_like_dialogue("Just a paragraph of text.\nAnother line.")


def test_split_text_prefers_sentence_end():
    text = ("This is a sentence. " * 60).strip()
    chunks = split_text(text, limit=100)
    assert all(len(c) <= 100 for c in chunks)
    assert all(c.endswith(".") for c in chunks)
    assert " ".join(chunks) == text


def test_split_text_without_spaces():
    assert split_text("x" * 250, limit=100) == ["x" * 100, "x" * 100, "x" * 50]


def test_pause_tags():
    assert split_pauses("Wait [pause] go [pause 2s] now [PAUSE 250ms]") == ["Wait", 1000, "go", 2000, "now", 250]
    assert split_pauses("[pause 99s]") == [10_000]
    assert strip_pauses("Wait [pause 2s] go") == "Wait go"


def test_decode_text_file():
    assert decode_text_file("Merhaba".encode("utf-16")) == "Merhaba"
    assert decode_text_file(b"\xef\xbb\xbfhello") == "hello"
    assert decode_text_file("caf\xe9".encode("cp1252")) == "caf\xe9"
