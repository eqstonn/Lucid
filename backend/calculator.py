"""Pure grade math for Lucid. No I/O and no API routing; depends only on schemas.py."""

from __future__ import annotations

from schemas import CourseStanding, GradeItem, GradingCategory

_EPS = 1e-9


def resolve_item_weights(category: GradingCategory) -> list[float]:
    """Return each item's weight (% of course), aligned with ``category.items``.

    Items with an explicit weight keep it. Otherwise, if the category has an
    ``item_weight`` (bucket grading) each such item is worth exactly that, even
    when the total exceeds the category weight. Failing both, unweighted items
    split the category's remaining weight equally (never negative).
    """
    if category.item_weight is not None:
        return [i.weight if i.weight is not None else category.item_weight for i in category.items]
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
        cat_evaluated = 0.0
        cat_earned = 0.0
        for item, weight in zip(category.items, resolve_item_weights(category)):
            if item.is_evaluated:
                cat_evaluated += weight
                cat_earned += item_points_earned(item, weight)
        # Bucket cap: a category never contributes (or counts as evaluated) beyond its weight.
        evaluated_weight += min(cat_evaluated, category.weight)
        points_earned += min(cat_earned, category.weight)

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

    # Bucket grading (COMP 1805): 10 quizzes x 5.5% = 55% available, capped at 50%.
    def quizzes(scores: list[float]) -> GradingCategory:
        return GradingCategory(
            name="Quizzes",
            weight=50,
            item_weight=5.5,
            items=[GradeItem(name=f"Quiz {n + 1}", score=s, max_score=10) for n, s in enumerate(scores)]
            + [GradeItem(name=f"Quiz {n + 1}") for n in range(len(scores), 10)],
        )

    assert resolve_item_weights(quizzes([])) == [5.5] * 10
    # 4 perfect quizzes: 22 / 22, below the cap.
    b = calculate_standing([quizzes([10, 10, 10, 10])])
    assert b.points_earned == 22.0 and b.evaluated_weight == 22.0, b
    assert b.projected_grade == 100.0 and b.progress_label == "22 / 22", b
    # Half marks on 4 quizzes: 11 earned of 22 evaluated.
    h = calculate_standing([quizzes([5, 5, 5, 5])])
    assert h.points_earned == 11.0 and h.projected_grade == 50.0, h
    # All 10 perfect: 55% raw, capped to 50 / 50.
    full = calculate_standing([quizzes([10] * 10)])
    assert full.points_earned == 50.0 and full.evaluated_weight == 50.0, full
    assert full.projected_grade == 100.0 and full.guaranteed_floor == 50.0, full
    # Cap applies to earned: 9 perfect + 1 zero = 49.5 raw, under the cap.
    nine = calculate_standing([quizzes([10] * 9 + [0])])
    assert nine.points_earned == 49.5 and nine.evaluated_weight == 50.0, nine
    # An explicit item weight still overrides item_weight.
    ov = GradingCategory(
        name="C", weight=50, item_weight=5.5, items=[GradeItem(name="Big", weight=20, score=1, max_score=1)]
    )
    assert resolve_item_weights(ov) == [20.0]

    print("All calculator checks passed.")
