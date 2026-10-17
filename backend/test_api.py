"""API tests via TestClient. Gemini is stubbed; extractor and calculator run for real."""

from __future__ import annotations

from typing import Any

import pymupdf as fitz
import pytest
from fastapi.testclient import TestClient

import main
from parser import ParseError
from schemas import GradingCategory

client = TestClient(main.app)

CATEGORIES = [GradingCategory(name="Final Exam", weight=100, items=[{"name": "Final"}])]  # type: ignore[list-item]


def make_pdf(text: str = "Final Exam - 100%") -> bytes:
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    data = doc.tobytes()
    doc.close()
    return data


@pytest.fixture
def stub_parser(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake(text: str) -> list[GradingCategory]:
        seen.append(text)
        return CATEGORIES

    monkeypatch.setattr(main, "parse_syllabus_text", fake)
    return seen


# ---- /api/parse-syllabus ----------------------------------------------------


def test_parse_syllabus_multipart_upload(stub_parser: list[str]) -> None:
    r = client.post("/api/parse-syllabus", files={"file": ("s.pdf", make_pdf(), "application/pdf")})
    assert r.status_code == 200
    assert r.json() == {"categories": [CATEGORIES[0].model_dump()]}
    assert "Final Exam - 100%" in stub_parser[0]  # extractor output reached the parser


def test_parse_syllabus_raw_bytes(stub_parser: list[str]) -> None:
    r = client.post("/api/parse-syllabus", content=make_pdf(), headers={"content-type": "application/pdf"})
    assert r.status_code == 200
    assert r.json()["categories"][0]["name"] == "Final Exam"


def test_parse_syllabus_no_body_is_400() -> None:
    assert client.post("/api/parse-syllabus").status_code == 400


def test_parse_syllabus_empty_file_is_400() -> None:
    r = client.post("/api/parse-syllabus", files={"file": ("s.pdf", b"", "application/pdf")})
    assert r.status_code == 400


def test_parse_syllabus_non_pdf_is_422(stub_parser: list[str]) -> None:
    r = client.post("/api/parse-syllabus", files={"file": ("s.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 422
    assert "Could not read PDF" in r.json()["detail"]
    assert stub_parser == []  # never reached the model


def test_parse_syllabus_scanned_pdf_is_422(stub_parser: list[str]) -> None:
    blank = fitz.open()
    blank.new_page()
    r = client.post("/api/parse-syllabus", content=blank.tobytes(), headers={"content-type": "application/pdf"})
    assert r.status_code == 422


def test_parse_syllabus_parse_error_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(text: str) -> Any:
        raise ParseError("model refused")

    monkeypatch.setattr(main, "parse_syllabus_text", boom)
    r = client.post("/api/parse-syllabus", files={"file": ("s.pdf", make_pdf(), "application/pdf")})
    assert r.status_code == 422
    assert "model refused" in r.json()["detail"]


def test_parse_syllabus_oversize_is_413(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)
    r = client.post("/api/parse-syllabus", content=make_pdf(), headers={"content-type": "application/pdf"})
    assert r.status_code == 413


# ---- /api/calculate-standing ------------------------------------------------

STANDING_PAYLOAD = {
    "categories": [
        {
            "name": "Quizzes",
            "weight": 20,
            "items": [
                {"name": "Quiz 1", "weight": 5, "score": 4, "max_score": 5},
                {"name": "Quiz 2", "weight": 15},
            ],
        },
        {"name": "Midterm", "weight": 10, "items": [{"name": "Midterm", "score": 80, "max_score": 100}]},
        {"name": "Final Exam", "weight": 70, "items": [{"name": "Final", "weight": 70}]},
    ]
}


def test_calculate_standing_12_of_15() -> None:
    r = client.post("/api/calculate-standing", json=STANDING_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["progress_label"] == "12 / 15"
    assert body["points_earned"] == 12.0
    assert body["evaluated_weight"] == 15.0
    assert body["projected_grade"] == 80.0
    assert body["guaranteed_floor"] == 12.0


def _bucket_payload(scores: list[float]) -> dict[str, Any]:
    items = [{"name": f"Quiz {n + 1}", "score": s, "max_score": 10} for n, s in enumerate(scores)]
    items += [{"name": f"Quiz {n + 1}"} for n in range(len(scores), 10)]
    return {"categories": [{"name": "Quizzes", "weight": 50, "item_weight": 5.5, "items": items}]}


def test_calculate_standing_bucket_item_weight() -> None:
    body = client.post("/api/calculate-standing", json=_bucket_payload([10, 10, 5, 5])).json()
    assert body["points_earned"] == 16.5  # 5.5 + 5.5 + 2.75 + 2.75
    assert body["evaluated_weight"] == 22.0
    assert body["projected_grade"] == 75.0
    assert body["progress_label"] == "16.5 / 22"


def test_calculate_standing_bucket_is_capped_at_category_weight() -> None:
    body = client.post("/api/calculate-standing", json=_bucket_payload([10] * 10)).json()
    assert body["points_earned"] == 50.0  # 55% raw, capped at 50
    assert body["evaluated_weight"] == 50.0
    assert body["projected_grade"] == 100.0
    assert body["guaranteed_floor"] == 50.0


def test_calculate_standing_nothing_graded() -> None:
    payload = {"categories": [{"name": "Exam", "weight": 100, "items": [{"name": "Final"}]}]}
    body = client.post("/api/calculate-standing", json=payload).json()
    assert body["projected_grade"] is None and body["progress_label"] == "0 / 0"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"categories": "nope"},
        {"categories": [{"name": "X", "weight": 120}]},
        {"categories": [{"name": "X", "weight": 10, "items": [{"name": "Q", "score": 3}]}]},
        {"categories": [{"name": "X", "weight": 10, "surprise": 1}]},
        {"categories": [{"name": "X", "weight": 10, "item_weight": -1}]},
    ],
)
def test_calculate_standing_invalid_payload_is_422(payload: dict[str, Any]) -> None:
    assert client.post("/api/calculate-standing", json=payload).status_code == 422


# ---- CORS -------------------------------------------------------------------


def test_cors_allows_any_origin() -> None:
    r = client.options(
        "/api/calculate-standing",
        headers={"Origin": "chrome-extension://abc", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
