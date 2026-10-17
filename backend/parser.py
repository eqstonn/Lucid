"""Syllabus text -> structured GradingCategory list via Claude (schema-enforced)."""

from __future__ import annotations

from typing import Optional

import anthropic

from schemas import GradingCategory, ParseSyllabusResponse

MODEL = "claude-opus-5-5"
MAX_TOKENS = 16000

SYSTEM_PROMPT = """\
You extract the grading scheme from a university course syllabus.

Return every graded component grouped into categories (e.g. Quizzes, Assignments, \
Midterm, Final Exam, Participation/Wooclap).

Rules:
- Category `weight` is the percent of the FINAL COURSE GRADE (0-100). Categories \
should normally sum to 100; report what the syllabus states and do not rescale.
- Item `weight` is the item's share of the FINAL COURSE GRADE in percent (e.g. one \
of four equal quizzes in a 20% category has weight 5). If the syllabus does not \
state per-item weights, leave `weight` null; do not guess.
- Only list items the syllabus names or clearly implies (e.g. "4 quizzes" -> \
"Quiz 1".."Quiz 4"). A category with no identifiable items has an empty `items` list.
- `score` and `max_score` are always null: a syllabus has no student results.
- If the syllabus gives best-of / drop-lowest rules, keep the plain listing and \
ignore the rule; do not invent weights for it.
- Never invent components that are not in the text.
"""


class ParseError(Exception):
    """Raised when the model response cannot be turned into grading categories."""


def parse_syllabus_text(
    text: str,
    client: Optional[anthropic.Anthropic] = None,
) -> list[GradingCategory]:
    """Send normalized syllabus text to Claude and return validated grading categories.

    Args:
        text: Output of ``extractor.extract_text_from_pdf``.
        client: Optional preconfigured client (credentials resolve from the environment
            when omitted). Injectable for testing.

    Raises:
        ParseError: empty input, refusal, truncation, or output failing the schema.
    """
    if not text.strip():
        raise ParseError("Syllabus text is empty")

    api = client or anthropic.Anthropic()
    try:
        response = api.messages.parse(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": f"<syllabus>\n{text}\n</syllabus>\n\nExtract the grading scheme.",
                }
            ],
            output_format=ParseSyllabusResponse,
        )
    except anthropic.APIStatusError as exc:
        raise ParseError(f"Claude API error ({exc.status_code}): {exc.message}") from exc
    except anthropic.APIConnectionError as exc:
        raise ParseError("Could not reach the Claude API") from exc

    if response.stop_reason == "refusal":
        raise ParseError("Claude declined to process this document")
    if response.stop_reason == "max_tokens":
        raise ParseError("Response was truncated before the grading scheme was complete")
    parsed: Optional[ParseSyllabusResponse] = response.parsed_output
    if parsed is None:
        raise ParseError("Claude returned no structured output")
    return parsed.categories


if __name__ == "__main__":
    from types import SimpleNamespace

    canned = ParseSyllabusResponse(
        categories=[GradingCategory(name="Final Exam", weight=100.0)]
    )

    class _Messages:
        def parse(self, **kwargs: object) -> SimpleNamespace:
            assert kwargs["output_format"] is ParseSyllabusResponse
            return SimpleNamespace(stop_reason="end_turn", parsed_output=canned)

    fake = SimpleNamespace(messages=_Messages())
    result = parse_syllabus_text("Final Exam 100%", client=fake)  # type: ignore[arg-type]
    assert result == canned.categories
    try:
        parse_syllabus_text("   ", client=fake)  # type: ignore[arg-type]
    except ParseError:
        pass
    else:
        raise AssertionError("expected ParseError on empty text")
    print("parser.py: all assertions passed")
