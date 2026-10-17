"""Phase 2 tests: PDF bytes -> normalized text -> GradingCategory models (Gemini).

Run from backend/:  .venv\\Scripts\\python -m pytest test_phase2.py -v
The live test needs GEMINI_API_KEY in backend/.env and is skipped without it.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Optional

import pymupdf as fitz
import pytest
from dotenv import load_dotenv

from extractor import ExtractionError, extract_text_from_pdf
from parser import ParseError, parse_syllabus_text
from schemas import GradingCategory, ParseSyllabusResponse

load_dotenv(Path(__file__).with_name(".env"))

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


def fake_client(
    parsed: Optional[ParseSyllabusResponse], finish_reason: str = "STOP", text: Optional[str] = None
) -> SimpleNamespace:
    captured: dict[str, object] = {}

    def generate_content(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(
            parsed=parsed, text=text, candidates=[SimpleNamespace(finish_reason=finish_reason)]
        )

    return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content), captured=captured)


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


def test_pdf_to_models_end_to_end_with_fake_gemini() -> None:
    text = extract_text_from_pdf(make_pdf(SYLLABUS_LINES))
    client = fake_client(CANNED)
    categories = parse_syllabus_text(text, client=client)  # type: ignore[arg-type]

    assert all(isinstance(c, GradingCategory) for c in categories)
    assert sum(c.weight for c in categories) == 100
    assert "Final Exam - 30%" in client.captured["contents"]  # type: ignore[operator]
    assert client.captured["config"].response_json_schema == ParseSyllabusResponse.model_json_schema()  # type: ignore[attr-defined]


def test_falls_back_to_validating_raw_json_text() -> None:
    client = fake_client(None, text=CANNED.model_dump_json())
    assert parse_syllabus_text("Final Exam 30%", client=client) == CANNED.categories  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("parsed", "finish", "text"),
    [(None, "STOP", None), (None, "STOP", "{not json"), (CANNED, "FinishReason.MAX_TOKENS", None)],
)
def test_parse_failures_raise_parse_error(
    parsed: Optional[ParseSyllabusResponse], finish: str, text: Optional[str]
) -> None:
    with pytest.raises(ParseError):
        parse_syllabus_text("Final Exam 100%", client=fake_client(parsed, finish, text))  # type: ignore[arg-type]


def test_schema_contract_rejects_bad_model_output() -> None:
    with pytest.raises(Exception):
        GradingCategory(name="X", weight=120)
    with pytest.raises(Exception):
        GradingCategory.model_validate({"name": "X", "weight": 10, "items": [{"name": "Q", "score": 3}]})


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="live test needs GEMINI_API_KEY in backend/.env")
def test_live_gemini_parses_sample_syllabus() -> None:
    categories = parse_syllabus_text(extract_text_from_pdf(make_pdf(SYLLABUS_LINES)))

    assert all(isinstance(c, GradingCategory) for c in categories)
    assert sum(c.weight for c in categories) == pytest.approx(100)
    names = " ".join(c.name.lower() for c in categories)
    for expected in ("quiz", "assignment", "midterm", "final"):
        assert expected in names
    assert all(i.score is None and i.max_score is None for c in categories for i in c.items)
    quizzes = next(c for c in categories if "quiz" in c.name.lower())
    assert quizzes.weight == pytest.approx(20)
    assert len(quizzes.items) == 4
