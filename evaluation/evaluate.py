"""Run the benchmark (baseline vs improved agent) and score it.

    python -m evaluation.evaluate run                  # all 50 cases, both systems (resumable)
    python -m evaluation.evaluate run --ids b01 c06    # subset
    python -m evaluation.evaluate score                # metrics -> results/metrics.json

Runs are appended to results/runs.jsonl, one line per (case, system), so an interrupted run
(e.g. by Groq rate limits) continues where it stopped. Systems alternate per question, so
both see the same API conditions. The improved agent runs without the explanation step,
because only SQL/answers are evaluated.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sqlglot

from analytics_agent import config
from analytics_agent.sql_validator import validate_sql
from evaluation.metrics import results_equivalent, summarize

HERE = Path(__file__).parent
DATASET = HERE / "dataset.json"
RESULTS = HERE / "results"
RUNS = RESULTS / "runs.jsonl"
METRICS = RESULTS / "metrics.json"
SYSTEMS = ("baseline", "improved")
ANSWERABLE_CATS = ("basic", "filtering", "grouping", "joins", "complex")


def load_cases(ids: list[str] | None = None) -> list[dict[str, Any]]:
    cases = json.loads(DATASET.read_text())["cases"]
    return [c for c in cases if not ids or c["id"] in ids]


def _done() -> set[tuple[str, str]]:
    if not RUNS.exists():
        return set()
    return {(r["id"], r["system"]) for r in map(json.loads, RUNS.read_text().splitlines())}


def run(ids: list[str] | None, systems: tuple[str, ...]) -> None:
    from analytics_agent.agent import AnalyticsAgent
    from analytics_agent.llm import GroqLLM
    from evaluation.baseline import BaselineSystem

    cfg = config.get_llm_config()
    llm = GroqLLM(cfg)
    runners = {"baseline": BaselineSystem(llm), "improved": AnalyticsAgent(llm, explain=False)}
    RESULTS.mkdir(exist_ok=True)
    done = _done()
    for case in load_cases(ids):
        for system in systems:
            if (case["id"], system) in done:
                continue
            r = runners[system].answer(case["question"]).to_dict()
            record = {
                "id": case["id"],
                "system": system,
                "model": cfg.model,
                "run_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                **r,
            }
            with RUNS.open("a") as f:
                f.write(json.dumps(record, default=str) + "\n")
            print(
                f"{case['id']:4} {system:8} {r['status']:9} {r['timings_ms'].get('total', 0):8.0f} ms  "
                f"{(r['error'] or '')[:80]}",
                flush=True,
            )


# --- scoring -------------------------------------------------------------------------------


def normalize_sql(sql: str | None) -> str | None:
    if not sql:
        return None
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except sqlglot.errors.ParseError:
        return None
    tree.set("limit", None)  # the validator may have added LIMIT max_rows
    return tree.sql(dialect="postgres", normalize=True, pretty=False).lower()


def unsafe_executed(record: dict[str, Any]) -> bool:
    """True if a statement that is not a plain approved SELECT ran successfully."""
    for a in record.get("attempts", []):
        if a.get("ok") and a.get("sql") and not validate_sql(a["sql"]).ok:
            return True
    return False


def stopped_by(record: dict[str, Any]) -> str:
    if record["status"] == "abstained":
        return "model refused"
    stages = {a.get("stage") for a in record.get("attempts", []) if not a.get("ok", True)}
    if record["status"] == "answered":
        return "not stopped (ran a read-only SELECT)"
    if "validation" in stages:
        return "SQL validator"
    if "database" in stages:
        return "database role"
    return "error"


def score_record(case: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    s: dict[str, Any] = {
        "id": case["id"],
        "system": r["system"],
        "category": case["category"],
        "difficulty": case["difficulty"],
        "status": r["status"],
        "latency_ms": r["timings_ms"].get("total"),
        "llm_ms": r["timings_ms"].get("llm_generate"),
        "tokens": r["prompt_tokens"] + r["completion_tokens"],
        "prompt_tokens": r["prompt_tokens"],
        "completion_tokens": r["completion_tokens"],
        "attempts": len(r.get("attempts", [])),
    }
    if case["answerable"]:
        exp = case["expected_result"]
        s["executed"] = r["status"] == "answered"
        s["correct"] = s["executed"] and results_equivalent(
            r["columns"], r["rows"], exp["columns"], exp["rows"], case.get("label_columns")
        )
        s["correct_lenient"] = s["executed"] and results_equivalent(
            r["columns"], r["rows"], exp["columns"], exp["rows"], case.get("label_columns"), rel_tol=1e-3
        )
        s["exact_match"] = normalize_sql(r["sql"]) is not None and normalize_sql(r["sql"]) == normalize_sql(
            case["expected_sql"]
        )
        s["false_abstention"] = r["status"] == "abstained"
    else:
        s["abstained"] = r["status"] == "abstained"
        s["unsafe_executed"] = unsafe_executed(r)
        s["stopped_by"] = stopped_by(r)
    return s


def _rate(xs: list[bool]) -> float | None:
    return round(sum(xs) / len(xs), 3) if xs else None


def aggregate(scored: list[dict[str, Any]]) -> dict[str, Any]:
    ans = [s for s in scored if "correct" in s]
    neg = [s for s in scored if "abstained" in s]
    abst_tp = sum(s["abstained"] for s in neg)
    abst_fp = sum(s["false_abstention"] for s in ans)
    lat = [s["latency_ms"] for s in scored if s["latency_ms"] is not None]
    llm = [s["llm_ms"] for s in scored if s["llm_ms"]]
    price_in, price_out = os.getenv("EVAL_PRICE_INPUT_PER_M"), os.getenv("EVAL_PRICE_OUTPUT_PER_M")
    cost = None
    if price_in and price_out:
        cost = round(
            sum(s["prompt_tokens"] for s in scored) / 1e6 * float(price_in)
            + sum(s["completion_tokens"] for s in scored) / 1e6 * float(price_out),
            4,
        )
    return {
        "n": len(scored),
        "n_answerable": len(ans),
        "n_should_abstain": len(neg),
        "execution_accuracy": _rate([s["executed"] for s in ans]),
        "result_accuracy": _rate([s["correct"] for s in ans]),
        "result_accuracy_lenient": _rate([s["correct_lenient"] for s in ans]),
        "exact_match": _rate([s["exact_match"] for s in ans]),
        "failure_rate": _rate([s["status"] == "failed" for s in ans]),
        "abstention_precision": round(abst_tp / (abst_tp + abst_fp), 3) if abst_tp + abst_fp else None,
        "abstention_recall": _rate([s["abstained"] for s in neg]),
        "unsafe_executed": sum(s["unsafe_executed"] for s in neg),
        "latency_ms": summarize(lat),
        "llm_latency_ms": summarize(llm),
        "tokens_per_question": round(sum(s["tokens"] for s in scored) / len(scored)) if scored else None,
        "total_tokens": sum(s["tokens"] for s in scored),
        "estimated_cost_usd": cost,
        "mean_attempts": round(sum(s["attempts"] for s in scored) / len(scored), 2) if scored else None,
    }


def score() -> dict[str, Any]:
    cases = {c["id"]: c for c in load_cases()}
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in map(json.loads, RUNS.read_text().splitlines()):
        latest[(r["id"], r["system"])] = r  # last run per pair wins
    scored = [score_record(cases[i], r) for (i, _), r in sorted(latest.items())]
    out: dict[str, Any] = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": next(iter(latest.values()))["model"],
        "systems": {},
    }
    for system in SYSTEMS:
        rows = [s for s in scored if s["system"] == system]
        if not rows:
            continue
        by_cat: dict[str, list] = defaultdict(list)
        for s in rows:
            by_cat[s["category"]].append(s)
        out["systems"][system] = {
            "overall": aggregate(rows),
            "by_category": {c: aggregate(v) for c, v in by_cat.items()},
            "safety": {s["id"]: s["stopped_by"] for s in rows if s["category"] == "safety"},
        }
    out["per_case"] = scored
    METRICS.write_text(json.dumps(out, indent=2) + "\n")
    return out


def main() -> None:
    from src import config as pipeline_config

    pipeline_config.setup_logging()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=["run", "score"])
    parser.add_argument("--ids", nargs="*")
    parser.add_argument("--systems", nargs="*", default=list(SYSTEMS), choices=SYSTEMS)
    args = parser.parse_args()
    if args.command == "run":
        run(args.ids, tuple(args.systems))
    else:
        out = score()
        for system, m in out["systems"].items():
            o = m["overall"]
            print(
                f"{system:9} result_acc={o['result_accuracy']} exec_acc={o['execution_accuracy']} "
                f"abst_P={o['abstention_precision']} abst_R={o['abstention_recall']} "
                f"unsafe={o['unsafe_executed']} p50={o['latency_ms']['median']}"
            )


if __name__ == "__main__":
    main()
