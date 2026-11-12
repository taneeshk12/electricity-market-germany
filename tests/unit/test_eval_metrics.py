"""The evaluation comparator: equivalent results pass, genuinely different results fail."""

from __future__ import annotations

import pytest

from evaluation.metrics import numbers_match, percentile, results_equivalent


@pytest.mark.parametrize(
    ("pred", "exp", "ok"),
    [
        (78.51, 78.51203324225865, True),  # rounded to 2 decimals
        (78.5, 78.51203324225865, True),  # rounded to 1 decimal
        (78.6, 78.51203324225865, False),
        (79, 78.51203324225865, False),  # integer rounding of a small value is not accepted
        (463, 463.07860775, True),  # large value rounded to integer
        (0.5768101173905452, 0.5768101173905452, True),
        (3.44, 3.4375, True),
        (3.45, 3.4375, False),
    ],
)
def test_numbers_match(pred, exp, ok) -> None:
    assert numbers_match(pred, exp) is ok


def test_column_names_order_and_extra_columns_do_not_matter() -> None:
    exp = (["year", "avg"], [[2023, 95.1755], [2024, 78.512]])
    pred = (["average_price", "yr", "n"], [[78.51, 2024, 8784], [95.18, 2023, 8760]])
    assert results_equivalent(*pred, *exp)


def test_unit_scaling_is_accepted() -> None:
    assert results_equivalent(["twh"], [[463.08]], ["mwh"], [[463078607.75]])  # MWh vs TWh
    assert results_equivalent(["pct"], [[57.68]], ["share"], [[0.5768101]])  # fraction vs %


def test_row_alignment_is_checked() -> None:
    exp = (["year", "p"], [[2023, 95.18], [2024, 78.51]])
    swapped = (["year", "p"], [[2023, 78.51], [2024, 95.18]])  # same multisets, wrong pairing
    assert not results_equivalent(*swapped, *exp)


def test_row_count_must_match() -> None:
    assert not results_equivalent(["p"], [[1.0], [2.0]], ["p"], [[1.0]])
    assert not results_equivalent(["p"], [], ["p"], [[1.0]])


def test_strings_dates_and_booleans() -> None:
    assert results_equivalent(["m"], [["2025-06"]], ["year_month"], [["2025-06"]])
    assert not results_equivalent(["m"], [["2025-05"]], ["year_month"], [["2025-06"]])
    assert results_equivalent(["d", "v"], [["2024-12-14", 184.31]], ["local_date", "r"], [["2024-12-14", 184.3092]])


def test_label_columns() -> None:
    exp = (["is_weekend", "share"], [[False, 0.0296], [True, 0.1034]])
    pred = (["day_type", "pct"], [["weekday", 2.96], ["weekend", 10.34]])
    assert not results_equivalent(*pred, *exp)
    assert results_equivalent(*pred, *exp, label_columns=[0])
    wrong = (["day_type", "pct"], [["weekday", 2.96], ["weekend", 11.0]])
    assert not results_equivalent(*wrong, *exp, label_columns=[0])


def test_missing_expected_column_fails() -> None:
    exp = (["source", "gwh"], [["solar", 1.0], ["wind", 2.0]])
    assert not results_equivalent(["gwh"], [[1.0], [2.0]], *exp)


def test_percentile() -> None:
    assert percentile([1, 2, 3, 4, 5], 0.5) == 3
    assert percentile([1, 2, 3, 4, 5], 0.95) == pytest.approx(4.8)
    assert percentile([], 0.5) is None


def test_lenient_tolerance() -> None:
    assert not results_equivalent(["p"], [[78.50806]], ["p"], [[78.51203]])
    assert results_equivalent(["p"], [[78.50806]], ["p"], [[78.51203]], rel_tol=1e-3)
    assert not results_equivalent(["p"], [[78.3]], ["p"], [[78.51203]], rel_tol=1e-3)


def test_numeric_label_column() -> None:
    # Regression (found in the benchmark): bucket ids 0..4 are labels, not values.
    exp = (["bucket", "p"], [[0.0, 190.5077], [1.0, 131.4849], [4.0, 9.5840]])
    pred = (["bucket", "p"], [["0-20%", 190.51], ["20-40%", 131.48], ["80-100%", 9.58]])
    assert not results_equivalent(*pred, *exp)
    assert results_equivalent(*pred, *exp, label_columns=[0])
