"""Phase 2 tests: PDF bytes -> normalized text -> GradingCategory models.

Run offline (fake Claude client):   python -m pytest backend/test_phase2.py -v
Also run the live Claude test:      set ANTHROPIC_API_KEY (or `ant auth login`) first.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pymupdf as fitz
import pytest

from extractor import ExtractionError, extract_text_from_pdf
from parser import ParseError, parse_syllabus_text
from schemas import GradingCategory, ParseSyllabusResponse

SYLLABUS_LINES = [
    "CS 1010 - Introduction to Programming",
    "Grading Scheme",
    "Quizzes (4 equal quizzes) - 20%",
    "Assignments (Assignment 1, Assignment 2) - 30%: 15% each",
    "Midterm Exam - 20%",
    "Final Exam - 30%",
]


def make_pdf(lines: list[str]) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72.0
    for line in lines:
        page.insert_text((72, y), line)
        y += 20
    data = doc.tobytes()
    doc.close()
    return data


def fake_client(parsed: ParseSyllabusResponse | None, stop_reason: str = "end_turn") -> SimpleNamespace:
    captured: dict[str, object] = {}

    def parse(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(stop_reason=stop_reason, parsed_output=parsed)

    return SimpleNamespace(messages=SimpleNamespace(parse=parse), captured=captured)


CANNED = ParseSyllabusResponse(
    categories=[
        GradingCategory(name="Quizzes", weight=20, items=[{"name": f"Quiz {i}", "weight": 5} for i in range(1, 5)]),
        GradingCategory(
            name="Assignments",
            weight=30,
            items=[{"name": "Assignment 1", "weight": 15}, {"name": "Assignment 2", "weight": 15}],
        ),
        GradingCategory(name="Midterm Exam", weight=20, items=[{"name": "Midterm Exam"}]),
        GradingCategory(name="Final Exam", weight=30, items=[{"name": "Final Exam"}]),
    ]
)


def test_extracts_text_from_in_memory_pdf() -> None:
    text = extract_text_from_pdf(make_pdf(SYLLABUS_LINES))
    for line in SYLLABUS_LINES:
        assert line in text


def test_rejects_non_pdf_and_textless_pdf() -> None:
    with pytest.raises(ExtractionError):
        extract_text_from_pdf(b"hello world")
    blank = fitz.open()
    blank.new_page()
    with pytest.raises(ExtractionError):
        extract_text_from_pdf(blank.tobytes())


def test_pdf_to_models_end_to_end_with_fake_claude() -> None:
    text = extract_text_from_pdf(make_pdf(SYLLABUS_LINES))
    client = fake_client(CANNED)
    categories = parse_syllabus_text(text, client=client)  # type: ignore[arg-type]

    assert all(isinstance(c, GradingCategory) for c in categories)
    assert sum(c.weight for c in categories) == 100
    assert "Final Exam - 30%" in client.captured["messages"][0]["content"]  # type: ignore[index]
    assert client.captured["output_format"] is ParseSyllabusResponse


@pytest.mark.parametrize(
    ("parsed", "stop_reason"),
    [(None, "end_turn"), (CANNED, "refusal"), (CANNED, "max_tokens")],
)
def test_parse_failures_raise_parse_error(parsed: ParseSyllabusResponse | None, stop_reason: str) -> None:
    with pytest.raises(ParseError):
        parse_syllabus_text("Final Exam 100%", client=fake_client(parsed, stop_reason))  # type: ignore[arg-type]


def test_schema_contract_rejects_bad_model_output() -> None:
    with pytest.raises(Exception):
        GradingCategory(name="X", weight=120)
    with pytest.raises(Exception):
        GradingCategory.model_validate({"name": "X", "weight": 10, "items": [{"name": "Q", "score": 3}]})


@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"), reason="live test needs ANTHROPIC_API_KEY"
)
def test_live_claude_parses_sample_syllabus() -> None:
    categories = parse_syllabus_text(extract_text_from_pdf(make_pdf(SYLLABUS_LINES)))
    by_name = {c.name.lower(): c for c in categories}
    assert sum(c.weight for c in categories) == 100
    assert any("final" in n for n in by_name)
    assert all(i.score is None for c in categories for i in c.items)
