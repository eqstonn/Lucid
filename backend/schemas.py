"""Pydantic v2 data contracts for Lucid (grade items, categories, API models)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GradeItem(BaseModel):
    """A single assessed piece of material (quiz, test, exam, assignment, ...).

    ``weight`` is the item's share of the FINAL COURSE GRADE, in percent
    (e.g. 5.0 means worth 5% of the course). If omitted, the owning category
    splits its leftover weight equally among its weightless items.
    An item is "evaluated" once both ``score`` and ``max_score`` are known.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: Optional[float] = Field(default=None, ge=0, le=100)
    score: Optional[float] = Field(default=None, ge=0)
    max_score: Optional[float] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def _score_requires_max(self) -> "GradeItem":
        if self.score is not None and self.max_score is None:
            raise ValueError("max_score is required when score is provided")
        return self

    @property
    def is_evaluated(self) -> bool:
        return self.score is not None and self.max_score is not None


class GradingCategory(BaseModel):
    """A group of grade items (e.g. "Quizzes") worth at most ``weight`` % of the course.

    ``weight`` is the category's cap. For bucket grading, ``item_weight`` is the
    % of the course each item is individually worth; the items may add up to more
    than ``weight`` (10 quizzes x 5.5% = 55% in a 50% bucket) but the category's
    contribution never exceeds ``weight``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    weight: float = Field(ge=0, le=100)
    item_weight: Optional[float] = Field(default=None, ge=0, le=100)
    items: list[GradeItem] = Field(default_factory=list)


class ParseSyllabusResponse(BaseModel):
    """Response for /api/parse-syllabus."""

    categories: list[GradingCategory]


class CalculateStandingRequest(BaseModel):
    """Request for /api/calculate-standing."""

    categories: list[GradingCategory]


class CourseStanding(BaseModel):
    """Computed standing for one course. All values are percentages of the course."""

    points_earned: float  # % of the course grade earned so far (the "12" in 12 / 15)
    evaluated_weight: float  # % of the course evaluated so far (the "15" in 12 / 15)
    projected_grade: Optional[float]  # points_earned / evaluated_weight * 100; None if nothing evaluated
    guaranteed_floor: float  # grade if every remaining item scored 0
    progress_label: str  # e.g. "12 / 15"
