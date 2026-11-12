"""Result-equivalence and aggregate metrics for the text-to-SQL evaluation.

Two results are *equivalent* if they contain the same rows, regardless of column names,
column order, row order and extra predicted columns:

* every expected column must map to a distinct predicted column with the same values,
  compared row-aligned (rows are sorted on the mapped columns before comparing);
* numbers match if they are close (relative 1e-6) or if the predicted value equals the
  expected value rounded to the predicted number of decimals (the model may round);
* a column may be uniformly scaled by 100, 1e3 or 1e6 (or the inverse): %, GWh, TWh, GW
  (the comparison, including the rounding rule, happens in the prediction's units);
* strings/dates/booleans compare case-insensitively as text;
* the row count must match exactly.
The headline metric uses rel_tol=1e-6 (strict); a lenient score with rel_tol=1e-3 is reported
as a sensitivity check (it accepts e.g. a mean of daily means instead of the hourly mean).
`label_columns` lists expected columns that identify groups and may be written differently
(bucket 0 vs '0-20%'); they are not compared, but all other columns and the row count are.
"""

from __future__ import annotations

import math
from decimal import Decimal
from itertools import permutations
from statistics import median
from typing import Any

SCALES = (1.0, 100.0, 0.01, 1e3, 1e-3, 1e6, 1e-6)
MAX_DECIMALS_FOR_ROUNDING = 6


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int | float | Decimal):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v)
        except ValueError:
            return None
    return None


def _decimals(x: float) -> int:
    text = repr(x)
    if "e" in text or "E" in text:
        return MAX_DECIMALS_FOR_ROUNDING
    return len(text.split(".")[1].rstrip("0")) if "." in text else 0


def numbers_match(pred: float, expected: float, rel_tol: float = 1e-6) -> bool:
    if math.isclose(pred, expected, rel_tol=rel_tol, abs_tol=1e-9):
        return True
    d = _decimals(pred)
    # Accept model rounding to >= 1 decimal, or to integers when the value is large.
    if d >= 1 or abs(expected) >= 100:
        return math.isclose(pred, round(expected, d), rel_tol=1e-9, abs_tol=10 ** -(d + 3))
    return False


def _text(v: Any) -> str:
    return str(v).strip().lower()


def _is_numeric_column(values: list[Any]) -> bool:
    non_null = [v for v in values if v is not None]
    return bool(non_null) and all(_num(v) is not None and not isinstance(v, str) for v in non_null)


def _column_matches(pred: list[Any], expected: list[Any], numeric: bool, rel_tol: float) -> float | None:
    """Return the scale under which `pred` equals `expected` as a multiset, else None."""
    if len(pred) != len(expected):
        return None
    if not numeric:
        return 1.0 if sorted(map(_text, pred)) == sorted(map(_text, expected)) else None
    p = [_num(v) for v in pred]
    if any(v is None for v in p) and not all(v is None for v in expected):
        if sum(v is None for v in p) != sum(v is None for v in expected):
            return None
    ps = sorted(v for v in p if v is not None)
    es = sorted(_num(v) for v in expected if v is not None)
    for scale in SCALES:  # predicted ≈ expected * scale; compare in the prediction's own units
        if len(ps) == len(es) and all(numbers_match(a, b * scale, rel_tol) for a, b in zip(ps, es, strict=True)):
            return scale
    return None


def results_equivalent(
    pred_cols: list[str],
    pred_rows: list[list[Any]],
    exp_cols: list[str],
    exp_rows: list[list[Any]],
    label_columns: list[int] | None = None,
    rel_tol: float = 1e-6,
) -> bool:
    if len(pred_rows) != len(exp_rows):
        return False
    if not exp_rows:
        return True
    n_exp, n_pred = len(exp_cols), len(pred_cols)
    exp_c = [[r[i] for r in exp_rows] for i in range(n_exp)]
    pred_c = [[r[i] for r in pred_rows] for i in range(n_pred)]
    numeric = [_is_numeric_column(c) for c in exp_c]
    skip = set(label_columns or [])
    required = [i for i in range(n_exp) if i not in skip]
    if len(required) > n_pred:
        return False

    # Candidate predicted columns for each required expected column (multiset match).
    candidates = {
        i: [(j, s) for j in range(n_pred) if (s := _column_matches(pred_c[j], exp_c[i], numeric[i], rel_tol))]
        for i in required
    }
    if any(not c for c in candidates.values()):
        return False

    # Try assignments (tiny search: results have few columns) and verify row alignment.
    for combo in _assignments(required, candidates):
        if len({j for j, _ in combo.values()}) != len(combo):
            continue
        if _rows_align(pred_rows, exp_rows, combo, numeric, rel_tol):
            return True
    return False


def _assignments(required: list[int], candidates: dict[int, list[tuple[int, float]]]):
    def rec(k: int, acc: dict[int, tuple[int, float]]):
        if k == len(required):
            yield dict(acc)
            return
        i = required[k]
        for cand in candidates[i]:
            acc[i] = cand
            yield from rec(k + 1, acc)
            del acc[i]

    yield from rec(0, {})


def _rows_align(pred_rows, exp_rows, combo, numeric, rel_tol) -> bool:
    def key_exp(r):
        return tuple(_text(r[i]) if not numeric[i] else (_num(r[i]) or 0.0) for i in combo)

    def key_pred(r):
        return tuple(_text(r[j]) if not numeric[i] else ((_num(r[j]) or 0.0) / s) for i, (j, s) in combo.items())

    # Sort both on the mapped values; ties are handled by trying column-priority permutations.
    for order in permutations(range(len(combo))) if len(combo) <= 4 else [tuple(range(len(combo)))]:
        e = sorted(exp_rows, key=lambda r: tuple(key_exp(r)[k] for k in order))
        p = sorted(pred_rows, key=lambda r: tuple(key_pred(r)[k] for k in order))
        if all(_row_eq(pr, er, combo, numeric, rel_tol) for pr, er in zip(p, e, strict=True)):
            return True
    return False


def _row_eq(pr, er, combo, numeric, rel_tol) -> bool:
    for i, (j, s) in combo.items():
        if numeric[i]:
            a, b = _num(pr[j]), _num(er[i])
            if (a is None) != (b is None):
                return False
            if a is not None and not numbers_match(a, b * s, rel_tol):
                return False
        elif _text(pr[j]) != _text(er[i]):
            return False
    return True


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(values: list[float]) -> dict[str, float | None]:
    return {"median": median(values) if values else None, "p95": percentile(values, 0.95)}
