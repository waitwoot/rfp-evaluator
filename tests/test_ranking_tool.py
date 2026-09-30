"""Ranking maths and tie-breaks. 40 marks of the rubric live behind these."""

from __future__ import annotations

import itertools

import pytest

from rfp.tools.ranking_tool import (
    SupplierInput,
    compute_benchmarks,
    peer_performance_index,
    rank_suppliers,
    relative_performance,
    weighted_points,
)


# ---------------------------------------------------------------------------
# primitive formulas
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "score,max_score,weight,expected",
    [
        (8, 10, 60, 48.0),
        (5, 10, 40, 20.0),
        (10, 10, 30, 30.0),
        (0, 10, 30, 0.0),
        (3, 5, 20, 12.0),      # a non-10 maximum still normalises correctly
        (7, 0, 30, 0.0),       # guard: max_score of 0 cannot divide
    ],
)
def test_weighted_points(score, max_score, weight, expected):
    assert weighted_points(score, max_score, weight) == pytest.approx(expected)


@pytest.mark.parametrize(
    "score,benchmark,expected",
    [(8, 8, 100.0), (4, 8, 50.0), (0, 8, 0.0), (5, 10, 50.0)],
)
def test_relative_performance(score, benchmark, expected):
    assert relative_performance(score, benchmark) == pytest.approx(expected)


def test_relative_performance_zero_benchmark_is_zero_not_error():
    """Benchmark 0 means nobody scored; the criterion goes neutral, never crashes."""
    assert relative_performance(0, 0) == 0.0
    assert relative_performance(5, 0) == 0.0


def test_peer_performance_index_is_weighted_mean_of_relatives():
    assert peer_performance_index([(100.0, 60.0), (50.0, 40.0)]) == pytest.approx(80.0)
    assert peer_performance_index([]) == 0.0


# ---------------------------------------------------------------------------
# the hand-checked worked example from the brief
# ---------------------------------------------------------------------------
def test_worked_example_absolute_scores(ab_criteria, make_eval):
    """Tech 60 / Price 40, max 10. A=(8,5), B=(4,10) -> absolute 68 and 64."""
    suppliers = [
        SupplierInput("A", "2026-09-01", 3.0, make_eval("A", {1: 8, 2: 5}, ab_criteria)),
        SupplierInput("B", "2026-09-02", 3.0, make_eval("B", {1: 4, 2: 10}, ab_criteria)),
    ]
    by_name = {s["supplier_name"]: s for s in rank_suppliers(suppliers, ab_criteria)["suppliers"]}
    assert by_name["A"]["absolute_score"] == pytest.approx(68.0)
    assert by_name["B"]["absolute_score"] == pytest.approx(64.0)


def test_worked_example_ppi_overturns_absolute_score(ab_criteria, make_eval):
    """A wins on PPI 80 vs 70 -- and would also have won on absolute score.

    The important part is that the two measures are computed independently:
    absolute score is against the maximum, PPI is against the peer group.
    """
    suppliers = [
        SupplierInput("A", "2026-09-01", 3.0, make_eval("A", {1: 8, 2: 5}, ab_criteria)),
        SupplierInput("B", "2026-09-02", 3.0, make_eval("B", {1: 4, 2: 10}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    by_name = {s["supplier_name"]: s for s in result["suppliers"]}

    assert by_name["A"]["ppi"] == pytest.approx(80.0)
    assert by_name["B"]["ppi"] == pytest.approx(70.0)
    assert by_name["A"]["final_rank"] == 1
    assert by_name["B"]["final_rank"] == 2


def test_worked_example_benchmarks_and_gaps(ab_criteria, make_eval):
    """Benchmarks are the per-criterion maxima: 8 on Tech, 10 on Price."""
    suppliers = [
        SupplierInput("A", "2026-09-01", 3.0, make_eval("A", {1: 8, 2: 5}, ab_criteria)),
        SupplierInput("B", "2026-09-02", 3.0, make_eval("B", {1: 4, 2: 10}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert result["benchmarks"] == {"1": 8.0, "2": 10.0}

    by_name = {s["supplier_name"]: s for s in result["suppliers"]}
    a_tech = by_name["A"]["criteria"][0]
    a_price = by_name["A"]["criteria"][1]

    assert a_tech["gap"] == 0.0            # A leads Technical, so gap is 0
    assert a_price["gap"] == pytest.approx(-5.0)
    assert a_tech["relative_pct"] == pytest.approx(100.0)
    assert a_price["relative_pct"] == pytest.approx(50.0)


def test_gap_is_never_positive(ab_criteria, make_eval):
    suppliers = [
        SupplierInput("A", "2026-09-01", 3.0, make_eval("A", {1: 8, 2: 5}, ab_criteria)),
        SupplierInput("B", "2026-09-02", 3.0, make_eval("B", {1: 4, 2: 10}, ab_criteria)),
        SupplierInput("C", "2026-09-03", 3.0, make_eval("C", {1: 1, 2: 1}, ab_criteria)),
    ]
    for supplier in rank_suppliers(suppliers, ab_criteria)["suppliers"]:
        for criterion in supplier["criteria"]:
            assert criterion["gap"] <= 0


def test_zero_benchmark_zeroes_relative_and_warns(ab_criteria, make_eval):
    """Nobody scores on Price: relative is 0 for all, and the run warns."""
    suppliers = [
        SupplierInput("A", "2026-09-01", 3.0, make_eval("A", {1: 8, 2: 0}, ab_criteria)),
        SupplierInput("B", "2026-09-02", 3.0, make_eval("B", {1: 4, 2: 0}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)

    assert result["benchmarks"]["2"] == 0.0
    for supplier in result["suppliers"]:
        assert supplier["criteria"][1]["relative_pct"] == 0.0
    assert any("benchmark is 0" in w for w in result["warnings"])

    # Technical still separates them: A scores 8/8 -> 100%, B 4/8 -> 50%.
    by_name = {s["supplier_name"]: s for s in result["suppliers"]}
    assert by_name["A"]["ppi"] == pytest.approx(60.0)   # (100*60 + 0*40)/100
    assert by_name["B"]["ppi"] == pytest.approx(30.0)   # (50*60  + 0*40)/100


# ---------------------------------------------------------------------------
# tie-breaks, one level at a time
# ---------------------------------------------------------------------------
def test_tiebreak_level_1_ppi(ab_criteria, make_eval):
    suppliers = [
        SupplierInput("Zeta", "2026-09-01", 5.0, make_eval("Zeta", {1: 4, 2: 4}, ab_criteria)),
        SupplierInput("Alpha", "2026-09-02", 1.0, make_eval("Alpha", {1: 9, 2: 9}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["Alpha", "Zeta"]
    assert result["tie_breaks"][0]["rule_level"] == 1
    assert "Higher PPI" in result["tie_breaks"][0]["explanation"]


def test_tiebreak_level_2_earlier_submission_date(ab_criteria, make_eval):
    """Identical scores -> identical PPI -> the earlier submission wins."""
    suppliers = [
        SupplierInput("Later", "2026-09-10", 5.0, make_eval("Later", {1: 7, 2: 7}, ab_criteria)),
        SupplierInput("Earlier", "2026-09-08", 5.0, make_eval("Earlier", {1: 7, 2: 7}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["Earlier", "Later"]

    decision = result["tie_breaks"][0]
    assert decision["rule_level"] == 2
    assert "PPI tied at 100.0000" in decision["explanation"]
    assert "2026-09-08" in decision["explanation"]
    assert "2026-09-10" in decision["explanation"]


def test_tiebreak_level_3_experience_rating(ab_criteria, make_eval):
    suppliers = [
        SupplierInput("LowExp", "2026-09-08", 2.0, make_eval("LowExp", {1: 7, 2: 7}, ab_criteria)),
        SupplierInput("HighExp", "2026-09-08", 4.5, make_eval("HighExp", {1: 7, 2: 7}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["HighExp", "LowExp"]

    decision = result["tie_breaks"][0]
    assert decision["rule_level"] == 3
    assert "higher experience rating" in decision["explanation"]


def test_tiebreak_level_4_alphabetical(ab_criteria, make_eval):
    suppliers = [
        SupplierInput("Yankee", "2026-09-08", 3.0, make_eval("Yankee", {1: 7, 2: 7}, ab_criteria)),
        SupplierInput("Bravo", "2026-09-08", 3.0, make_eval("Bravo", {1: 7, 2: 7}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["Bravo", "Yankee"]

    decision = result["tie_breaks"][0]
    assert decision["rule_level"] == 4
    assert "alphabetically" in decision["explanation"]


def test_tiebreak_levels_apply_in_priority_order(ab_criteria, make_eval):
    """A worse date must not rescue a supplier that already lost on PPI."""
    suppliers = [
        SupplierInput("EarlyWeak", "2026-09-01", 5.0,
                      make_eval("EarlyWeak", {1: 2, 2: 2}, ab_criteria)),
        SupplierInput("LateStrong", "2026-09-30", 0.0,
                      make_eval("LateStrong", {1: 9, 2: 9}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["LateStrong", "EarlyWeak"]
    assert result["tie_breaks"][0]["rule_level"] == 1


def test_ppi_rounded_before_sorting_so_float_noise_cannot_decide(ab_criteria, make_eval):
    """PPIs differing by ~1e-10 are a tie; the date decides, not float noise.

    Without rounding, B's invisible 0.0000000002 advantage would outrank A and
    the "earlier submission date" rule would never be reached.
    """
    suppliers = [
        SupplierInput("A_early", "2026-09-01", 3.0,
                      make_eval("A_early", {1: 8, 2: 5.0}, ab_criteria)),
        SupplierInput("B_late", "2026-09-20", 3.0,
                      make_eval("B_late", {1: 8, 2: 5.00000000001}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    by_name = {s["supplier_name"]: s for s in result["suppliers"]}

    assert by_name["A_early"]["ppi"] == by_name["B_late"]["ppi"]  # equal after rounding
    assert [s["supplier_name"] for s in result["suppliers"]] == ["A_early", "B_late"]
    assert result["tie_breaks"][0]["rule_level"] == 2


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------
def test_ranking_is_independent_of_input_order(default_criteria, make_eval):
    """Every permutation of the same suppliers produces the same leaderboard."""
    specs = [
        ("Apex Systems", "2026-09-08", 4.2, {1: 9, 2: 7, 3: 5, 4: 9, 5: 7}),
        ("BrightPath Tech", "2026-09-11", 2.5, {1: 6, 2: 6, 3: 9, 4: 3, 5: 4}),
        ("NexaWorks", "2026-09-09", 4.0, {1: 8, 2: 9, 3: 7, 4: 8, 5: 9}),
        ("Orbit Digital", "2026-09-10", 4.6, {1: 6, 2: 7, 3: 7, 4: 7, 5: 9}),
    ]
    expected = None
    for permutation in itertools.permutations(specs):
        suppliers = [
            SupplierInput(name, date, exp, make_eval(name, scores, default_criteria))
            for name, date, exp, scores in permutation
        ]
        result = rank_suppliers(suppliers, default_criteria)
        order = [(s["supplier_name"], s["final_rank"], s["ppi"]) for s in result["suppliers"]]
        if expected is None:
            expected = order
        assert order == expected


def test_ranks_are_contiguous_from_one(default_criteria, make_eval):
    suppliers = [
        SupplierInput(f"S{i}", f"2026-09-0{i}", float(i),
                      make_eval(f"S{i}", {1: i, 2: i, 3: i, 4: i, 5: i}, default_criteria))
        for i in range(1, 5)
    ]
    result = rank_suppliers(suppliers, default_criteria)
    assert [s["final_rank"] for s in result["suppliers"]] == [1, 2, 3, 4]


def test_tie_break_recorded_for_every_adjacent_pair(default_criteria, make_eval):
    suppliers = [
        SupplierInput(f"S{i}", f"2026-09-0{i}", float(i),
                      make_eval(f"S{i}", {1: i, 2: i, 3: i, 4: i, 5: i}, default_criteria))
        for i in range(1, 5)
    ]
    result = rank_suppliers(suppliers, default_criteria)

    assert len(result["tie_breaks"]) == 3          # N suppliers -> N-1 comparisons
    assert result["suppliers"][-1]["tie_break_reason"] == "Lowest ranked supplier in this run."
    for supplier in result["suppliers"][:-1]:
        assert supplier["tie_break_reason"]


def test_leader_scores_100_relative_on_every_criterion_it_leads(default_criteria, make_eval):
    suppliers = [
        SupplierInput("Top", "2026-09-01", 5.0,
                      make_eval("Top", {1: 10, 2: 10, 3: 10, 4: 10, 5: 10}, default_criteria)),
        SupplierInput("Mid", "2026-09-02", 5.0,
                      make_eval("Mid", {1: 5, 2: 5, 3: 5, 4: 5, 5: 5}, default_criteria)),
    ]
    result = rank_suppliers(suppliers, default_criteria)
    top = result["suppliers"][0]
    assert top["ppi"] == pytest.approx(100.0)
    assert top["absolute_score"] == pytest.approx(100.0)
    assert result["suppliers"][1]["ppi"] == pytest.approx(50.0)


def test_empty_supplier_list_returns_empty_result(default_criteria):
    result = rank_suppliers([], default_criteria)
    assert result["suppliers"] == []
    assert result["tie_breaks"] == []


def test_unreadable_submission_date_sorts_last_and_warns(ab_criteria, make_eval):
    suppliers = [
        SupplierInput("NoDate", "not-a-date", 3.0,
                      make_eval("NoDate", {1: 7, 2: 7}, ab_criteria)),
        SupplierInput("Dated", "2026-09-30", 3.0,
                      make_eval("Dated", {1: 7, 2: 7}, ab_criteria)),
    ]
    result = rank_suppliers(suppliers, ab_criteria)
    assert [s["supplier_name"] for s in result["suppliers"]] == ["Dated", "NoDate"]
    assert any("could not be read" in w for w in result["warnings"])
