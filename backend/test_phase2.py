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


BUCKET_LINES = [
    "COMP 1805 Assessment Overview - bucket-based grading",
    "Quizzes (10 x 5.5%) - available 55%, bucket capacity 50%",
    "Tutorial Workshops (11 x 1.5%) - available 16.5%, bucket capacity 15%",
    "Lecture Engagement - 12 opportunities, 1% each (12% available, capped at 10%)",
    "Video Engagement - 11 weekly video groups, 0.5% per week (capped at 5%)",
    "Final Exam - 20%",
]

BUCKET_CANNED = ParseSyllabusResponse(
    categories=[
        GradingCategory(
            name="Quizzes", weight=50, item_weight=5.5, items=[{"name": f"Quiz {i}"} for i in range(1, 11)]
        ),
        GradingCategory(
            name="Lecture Engagement",
            weight=10,
            item_weight=1,
            items=[{"name": f"Lecture Engagement {i}"} for i in range(1, 13)],
        ),
        GradingCategory(
            name="Video Engagement", weight=5, item_weight=0.5, items=[{"name": f"Video {i}"} for i in range(1, 12)]
        ),
        GradingCategory(name="Final Exam", weight=20, items=[{"name": "Final Exam"}]),
    ]
)


def test_item_weight_round_trips_through_schema_and_parser() -> None:
    assert GradingCategory(name="X", weight=10).item_weight is None
    with pytest.raises(Exception):
        GradingCategory(name="X", weight=10, item_weight=120)

    client = fake_client(None, text=BUCKET_CANNED.model_dump_json())
    cats = parse_syllabus_text("\n".join(BUCKET_LINES), client=client)  # type: ignore[arg-type]
    assert cats == BUCKET_CANNED.categories
    quizzes = cats[0]
    assert quizzes.item_weight == 5.5 and quizzes.weight == 50 and len(quizzes.items) == 10
    assert [len(c.items) for c in cats] == [10, 12, 11, 1]
    # Model-facing JSON schema exposes the new field.
    assert "item_weight" in client.captured["config"].response_json_schema["$defs"]["GradingCategory"]["properties"]  # type: ignore[attr-defined]


def test_prompt_asks_for_item_weight_and_buried_item_counts() -> None:
    client = fake_client(BUCKET_CANNED)
    parse_syllabus_text("\n".join(BUCKET_LINES), client=client)  # type: ignore[arg-type]
    prompt = client.captured["config"].system_instruction  # type: ignore[attr-defined]
    assert "item_weight" in prompt
    assert "aggressive" in prompt and "capacity" in prompt.lower()


@pytest.mark.skipif(not os.environ.get("GEMINI_API_KEY"), reason="live test needs GEMINI_API_KEY in backend/.env")
def test_live_gemini_extracts_bucket_items() -> None:
    categories = parse_syllabus_text(extract_text_from_pdf(make_pdf(BUCKET_LINES)))
    by_name = {c.name.lower(): c for c in categories}
    lecture = next(c for n, c in by_name.items() if "lecture" in n)
    video = next(c for n, c in by_name.items() if "video" in n)
    quizzes = next(c for n, c in by_name.items() if "quiz" in n)
    assert (len(lecture.items), lecture.item_weight, lecture.weight) == (12, 1, 10)
    assert (len(video.items), video.item_weight, video.weight) == (11, 0.5, 5)
    assert (len(quizzes.items), quizzes.item_weight, quizzes.weight) == (10, 5.5, 50)


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
