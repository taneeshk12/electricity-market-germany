"""Render results/evaluation_report.md from metrics.json, safety_results.json and the
hand-written results/failure_analysis.md (root causes need human judgement)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.reporting import df_to_markdown

R = Path(__file__).parent / "results"
CATS = ["basic", "filtering", "grouping", "joins", "complex", "unanswerable", "safety"]


def pct(x) -> str:
    return "–" if x is None else f"{100 * x:.0f} %"


def ms(x) -> str:
    return "–" if x is None else f"{x / 1000:.1f} s"


def main() -> None:
    m = json.loads((R / "metrics.json").read_text())
    systems = m["systems"]
    rows = []
    for label, key, fmt in [
        ("Result accuracy (strict)", "result_accuracy", pct),
        ("Result accuracy (lenient, 0.1 % tolerance)", "result_accuracy_lenient", pct),
        ("Execution accuracy (SQL ran)", "execution_accuracy", pct),
        ("Exact SQL match", "exact_match", pct),
        ("Query failure rate", "failure_rate", pct),
        ("Abstention precision", "abstention_precision", pct),
        ("Abstention recall", "abstention_recall", pct),
        ("Unsafe statements executed", "unsafe_executed", str),
        ("Mean attempts per question", "mean_attempts", str),
        ("Tokens per question", "tokens_per_question", str),
    ]:
        rows.append({"metric": label, **{s: fmt(v["overall"][key]) for s, v in systems.items()}})
    for label, key in [
        ("Median latency, end-to-end", "latency_ms"),
        ("P95 latency, end-to-end", "latency_ms"),
        ("Median LLM call latency", "llm_latency_ms"),
        ("P95 LLM call latency", "llm_latency_ms"),
    ]:
        q = "median" if "Median" in label else "p95"
        rows.append({"metric": label, **{s: ms(v["overall"][key][q]) for s, v in systems.items()}})
    overall = df_to_markdown(pd.DataFrame(rows), index=False)

    cat_rows = []
    for c in CATS:
        row = {"category": c}
        for s, v in systems.items():
            b = v["by_category"].get(c)
            if not b:
                continue
            row[f"{s} n"] = b["n"]
            if c in ("unanswerable", "safety"):
                row[f"{s} correct"] = f"{pct(b['abstention_recall'])} refused"
            else:
                row[f"{s} correct"] = f"{pct(b['result_accuracy'])} (lenient {pct(b['result_accuracy_lenient'])})"
        cat_rows.append(row)
    by_cat = df_to_markdown(pd.DataFrame(cat_rows), index=False)

    per_case = pd.DataFrame(m["per_case"])
    piv = per_case.pivot(index="id", columns="system", values="status").reset_index()
    corr = per_case[per_case["correct"].notna()].pivot(index="id", columns="system", values="correct")
    piv = piv.merge(corr.add_suffix(" correct").reset_index(), on="id", how="left")
    per_case_md = df_to_markdown(piv.fillna("–"), index=False)

    safety = json.loads((R / "safety_results.json").read_text())
    sdf = pd.DataFrame(
        [
            {
                "attack": s["attack"],
                "baseline (role only)": s["baseline"].split(":")[0],
                "improved (validator + role)": s["improved"].split(":")[0],
            }
            for s in safety
        ]
    )
    n_exec = sum(s["baseline"].startswith("EXECUTED") for s in safety)
    safety_md = df_to_markdown(sdf, index=False)

    llm_safety = df_to_markdown(
        pd.DataFrame(
            [
                {"case": k, **{s: systems[s]["safety"].get(k, "–") for s in systems}}
                for k in systems["improved"]["safety"]
            ]
        ),
        index=False,
    )

    failures = (R / "failure_analysis.md").read_text() if (R / "failure_analysis.md").exists() else "_pending_"
    n_ans = systems["improved"]["overall"]["n_answerable"]
    n_neg = systems["improved"]["overall"]["n_should_abstain"]

    report = f"""# Evaluation report: baseline vs improved text-to-SQL agent

Generated from `evaluation/results/metrics.json` (scored {m["generated_at_utc"]}). Model: `{m["model"]}` on Groq,
temperature 0, the same model and token budget for both systems. Single run per question; LLM outputs are not
fully deterministic even at temperature 0, so small differences (±1 question) are within run-to-run noise.

## Setup

| | Baseline | Improved |
|---|---|---|
| Context | table and column names and types only | curated column descriptions, data notes, 11 metric definitions, available date range (via MCP tools) |
| Validation | none | SQLGlot allowlist validator |
| Repair | none | one retry with the validator or database error |
| Execution | read-only role | read-only role (through MCP `execute_readonly_query`) |
| Abstention | may return `sql: null` | explicit `answerable: false` with a reason |

**Dataset** ([`dataset.json`](../dataset.json)): 50 questions. {n_ans} are answerable (10 basic, 8 filtering,
8 grouping, 7 joins, 7 complex) and {n_neg} should be refused (5 unanswerable, 5 safety). Every expected result was
produced by executing hand-written SQL against the warehouse (`evaluation/build_dataset.py`), not typed by hand.
The questions were written before either system was run and were not changed afterwards.

**Scoring** ([`metrics.py`](../metrics.py)): results are compared as row sets. Column names, column and row order
and extra columns are ignored; model rounding is accepted, and so is unit scaling (%, GWh, TWh). The row count
must match. *Strict* uses a relative tolerance of 1e-6. *Lenient* (1e-3) is a sensitivity check that also accepts
near-identical aggregates (e.g. a mean of daily means). Exact SQL match is reported for completeness; it is
expected to be low, because different SQL can be equally correct.

**Scoring correction (disclosed).** During failure analysis I found a comparator bug: numeric group IDs (e.g.
renewable-share bucket 0–4) were compared as values, so a correct answer labelled `'0-20%'` failed. Label columns
are now declared per case (`label_columns` in the dataset: g02, g08, j06, c07), and **both systems were re-scored
from the same recorded runs**. No LLM call was repeated. Effect: baseline 62.5 → 65 % (g02), improved 92.5 → 95 % (c07).

**Latency caveat.** The improved prompt is about 3.8 times larger (3,140 vs 834 tokens per question). On Groq's
free tier (8,000 tokens/minute) it therefore hits rate limits far more often, and the end-to-end median of 6.6 s
is mostly waiting. Per call, the model is about as fast (median 0.8 vs 0.7 s). On a paid tier, the token cost,
not the latency, is the real price of the richer context.

## Overall results

{overall}

End-to-end latency includes waits caused by Groq free-tier rate limits (8,000 tokens/minute). LLM call latency
measures only the successful API call, which is the fairer speed comparison.

## By category

{by_cat}

## Safety

**Model-level** (the 5 safety prompts in the dataset): what stopped each request.

{llm_safety}

**Execution-level** (deterministic, no LLM: `evaluation/safety_tests.py`). 20 known attacks were sent directly
to each execution path.

{safety_md}

The read-only role alone blocked every write, DDL and file read. It still executed {n_exec} of 20 attacks: catalog
reads (`pg_roles`, `information_schema`, readable by every PostgreSQL role by design) and session-level setting
changes. None of these modifies data, but they leak metadata or loosen session limits. The validator blocked all 20
before they reached the database. Defence in depth is therefore justified: the role is the hard boundary, and the
validator closes the gaps that PostgreSQL privileges cannot.

## Failure analysis

{failures}

## Per-case outcomes

{per_case_md}

## Threats to validity

- 50 questions written by the project author; they cover the schema but are not an independent benchmark.
- One model, one run per question. Differences of 1–2 questions should not be over-interpreted.
- The improved system differs from the baseline in several ways at once (context, metrics, validation, repair).
  This evaluation does not isolate which part caused an improvement, and MCP itself is a transport, not a
  correctness feature.
- Expected SQL encodes one interpretation of each question. Where several are reasonable, the strict score may
  undercount; the lenient score and the manual failure analysis address part of this.
"""
    (R / "evaluation_report.md").write_text(report)
    print(f"wrote {R / 'evaluation_report.md'}")


if __name__ == "__main__":
    main()
