"""Pure grade math for Lucid. No I/O and no API routing; depends only on schemas.py."""

from __future__ import annotations

from schemas import CourseStanding, GradeItem, GradingCategory

_EPS = 1e-9


def resolve_item_weights(category: GradingCategory) -> list[float]:
    """Return each item's weight (% of course), aligned with ``category.items``.

    Items with an explicit weight keep it. Items without one split the
    category's remaining weight equally (never negative).
    """
    explicit = sum(i.weight for i in category.items if i.weight is not None)
    unweighted = [i for i in category.items if i.weight is None]
    share = max(category.weight - explicit, 0.0) / len(unweighted) if unweighted else 0.0
    return [i.weight if i.weight is not None else share for i in category.items]


def item_points_earned(item: GradeItem, weight: float) -> float:
    """Percent of the course earned from one item (0 if not yet evaluated)."""
    if item.score is None or item.max_score is None:
        return 0.0
    return weight * min(item.score, item.max_score) / item.max_score


def calculate_standing(categories: list[GradingCategory]) -> CourseStanding:
    """Compute points earned, evaluated weight, projected grade and floor."""
    points_earned = 0.0
    evaluated_weight = 0.0
    for category in categories:
        for item, weight in zip(category.items, resolve_item_weights(category)):
            if item.is_evaluated:
                evaluated_weight += weight
                points_earned += item_points_earned(item, weight)

    projected = (
        points_earned / evaluated_weight * 100.0 if evaluated_weight > _EPS else None
    )
    return CourseStanding(
        points_earned=round(points_earned, 4),
        evaluated_weight=round(evaluated_weight, 4),
        projected_grade=None if projected is None else round(projected, 4),
        guaranteed_floor=round(points_earned, 4),
        progress_label=f"{_fmt(points_earned)} / {_fmt(evaluated_weight)}",
    )


def _fmt(value: float) -> str:
    rounded = round(value, 2)
    return str(int(rounded)) if rounded == int(rounded) else f"{rounded:g}"


if __name__ == "__main__":
    # 15% of the course evaluated: Quiz 1 (5%, 4/5) + Midterm (10%, 80/100 -> 8%)
    # => earned 4 + 8 = 12 of 15 evaluated; projected 12/15 = 80%.
    cats = [
        GradingCategory(
            name="Quizzes",
            weight=20,
            items=[
                GradeItem(name="Quiz 1", weight=5, score=4, max_score=5),
                GradeItem(name="Quiz 2", weight=15),  # not yet graded
            ],
        ),
        GradingCategory(
            name="Midterm",
            weight=10,
            items=[GradeItem(name="Midterm", score=80, max_score=100)],  # weight inherited: 10
        ),
        GradingCategory(
            name="Final Exam",
            weight=70,
            items=[GradeItem(name="Final", weight=70)],
        ),
    ]
    s = calculate_standing(cats)
    assert s.points_earned == 12.0, s
    assert s.evaluated_weight == 15.0, s
    assert s.progress_label == "12 / 15", s
    assert abs(12 / 15 - 0.8) < _EPS
    assert s.projected_grade == 80.0, s
    assert s.guaranteed_floor == 12.0, s

    # Fill of the progress bar: 12 earned over 15 evaluated.
    assert abs(s.points_earned / s.evaluated_weight - 0.8) < _EPS

    # Nothing graded yet -> no projection, floor 0.
    empty = calculate_standing(
        [GradingCategory(name="Exam", weight=100, items=[GradeItem(name="Final")])]
    )
    assert empty.projected_grade is None and empty.guaranteed_floor == 0.0
    assert empty.progress_label == "0 / 0", empty

    # Equal split of unweighted items in a category (4 quizzes x 5% = 20%).
    q = GradingCategory(
        name="Quizzes",
        weight=20,
        items=[GradeItem(name=f"Q{n}", score=5, max_score=10) for n in range(4)],
    )
    assert resolve_item_weights(q) == [5.0] * 4
    qs = calculate_standing([q])
    assert qs.evaluated_weight == 20.0 and qs.points_earned == 10.0
    assert qs.projected_grade == 50.0

    print("All calculator checks passed.")
