"""Syllabus text -> structured GradingCategory list via Gemini (schema-enforced)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import truststore
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import ValidationError

from schemas import GradingCategory, ParseSyllabusResponse

# Verify TLS against the OS trust store: networks that inspect TLS (corporate proxies,
# antivirus) install their root CA there, not in certifi's bundle.
truststore.inject_into_ssl()
load_dotenv(Path(__file__).with_name(".env"))

MODEL = "gemini-3.8-flash"

SYSTEM_PROMPT = """\
You extract the grading scheme from a university course syllabus.

Return every graded component grouped into categories (e.g. Quizzes, Assignments, \
Midterm, Final Exam, Participation/Wooclap).

Rules:
- Category `weight` is the percent of the FINAL COURSE GRADE (0-100) the category \
can contribute at most. Under bucket grading this is the bucket CAPACITY (e.g. \
"55% available, capped at 50%" -> weight 50), not the amount available. Report what \
the syllabus states and do not rescale; categories may sum to over 100 when extra \
buckets (bonus, revision recovery) are stated as "+N%".
- Category `item_weight` is the percent of the FINAL COURSE GRADE that EACH item is \
individually worth, when the syllabus states it (e.g. "10 x 5.5%" -> 5.5, "1.5% each" \
-> 1.5, "0.5% per week" -> 0.5). Items may add up to MORE than the category weight; \
that is expected, keep both numbers as stated. Leave `item_weight` null if no \
per-item value is given.
- Item `weight` is only for a single item whose own weight differs from its siblings. \
Leave it null when `item_weight` applies or when per-item weights are not stated; \
do not guess.
- Be aggressive about item counts. Search the whole text, including descriptions, \
tables and bullet points, for counts such as "11 weekly tutorials", "12 \
lecture-engagement opportunities", "11 weekly video groups", "weekly quiz, weeks \
2-11" (= 10), "N x P%". Create one item per counted unit with numbered names \
("Quiz 1".."Quiz 10", "Lecture Engagement 1".."Lecture Engagement 12", \
"Video 1".."Video 11"). Use the count of opportunities actually stated, not the \
number of weeks in the term. Never leave a category's `items` empty if a count is \
stated anywhere in the text.
- A single exam or similar one-off component gets one item named after it. Only \
leave `items` empty when no item or count can be identified.
- `score` and `max_score` are always null: a syllabus has no student results.
- Best-of / drop-lowest / capped-bucket rules are expressed through `weight` (cap) \
and `item_weight`; do not invent extra weights for them.
- Never invent components that are not in the text.
"""


class ParseError(Exception):
    """Raised when the model response cannot be turned into grading categories."""


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ParseError("GEMINI_API_KEY is not set (add it to backend/.env)")
    return genai.Client(api_key=api_key)


def parse_syllabus_text(
    text: str,
    client: Optional[genai.Client] = None,
) -> list[GradingCategory]:
    """Send normalized syllabus text to Gemini and return validated grading categories.

    Args:
        text: Output of ``extractor.extract_text_from_pdf``.
        client: Optional preconfigured client. Injectable for testing; by default one
            is built from ``GEMINI_API_KEY`` (loaded from ``backend/.env``).

    Raises:
        ParseError: empty input, missing key, API failure, blocked/truncated output,
            or output failing the schema.
    """
    if not text.strip():
        raise ParseError("Syllabus text is empty")

    api = client or _get_client()
    try:
        response = api.models.generate_content(
            model=MODEL,
            contents=f"<syllabus>\n{text}\n</syllabus>\n\nExtract the grading scheme.",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.0,
                response_mime_type="application/json",
                response_json_schema=ParseSyllabusResponse.model_json_schema(),
            ),
        )
    except genai_errors.APIError as exc:
        raise ParseError(f"Gemini API error ({exc.code}): {exc.message}") from exc

    candidates = response.candidates or []
    finish = str(candidates[0].finish_reason) if candidates and candidates[0].finish_reason else ""
    if "MAX_TOKENS" in finish:
        raise ParseError("Response was truncated before the grading scheme was complete")

    parsed = response.parsed
    if isinstance(parsed, ParseSyllabusResponse):
        return parsed.categories
    if response.text:
        try:
            return ParseSyllabusResponse.model_validate_json(response.text).categories
        except ValidationError as exc:
            raise ParseError(f"Model output failed schema validation: {exc}") from exc
    raise ParseError(f"Gemini returned no structured output (finish_reason={finish or 'unknown'})")


if __name__ == "__main__":
    from types import SimpleNamespace

    canned = ParseSyllabusResponse(
        categories=[GradingCategory(name="Final Exam", weight=100.0)]
    )

    def _fake(parsed: object, text: Optional[str] = None, finish: str = "STOP") -> genai.Client:
        def generate_content(**kwargs: object) -> SimpleNamespace:
            config = kwargs["config"]
            assert config.response_json_schema == ParseSyllabusResponse.model_json_schema()  # type: ignore[attr-defined]
            return SimpleNamespace(
                parsed=parsed, text=text, candidates=[SimpleNamespace(finish_reason=finish)]
            )

        return SimpleNamespace(models=SimpleNamespace(generate_content=generate_content))  # type: ignore[return-value]

    assert parse_syllabus_text("Final Exam 100%", client=_fake(canned)) == canned.categories
    assert parse_syllabus_text(
        "Final Exam 100%", client=_fake(None, text=canned.model_dump_json())
    ) == canned.categories
    for bad in (_fake(None), _fake(None, text="{not json"), _fake(canned, finish="FinishReason.MAX_TOKENS")):
        try:
            parse_syllabus_text("Final Exam 100%", client=bad)
        except ParseError:
            pass
        else:
            raise AssertionError("expected ParseError")
    try:
        parse_syllabus_text("   ", client=_fake(canned))
    except ParseError:
        pass
    else:
        raise AssertionError("expected ParseError on empty text")
    print("parser.py: all assertions passed")
