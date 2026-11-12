"""Data quality checks on the processed hourly data.

Writes docs/data_quality_report.md (human-readable) and docs/data_quality_report.json
(machine-readable: one record per check with expected/actual/status/timestamp) and
raises if a *critical* check fails (duplicates, broken hourly grid, aggregation not
matching SMARD's own hourly values). Non-critical findings (missing values, outliers)
are reported as warnings only – we never fix data silently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from src import config
from src.reporting import df_to_markdown
from src.transform import GENERATION_FILE, METADATA_FILE, PRICE_LOAD_FILE, REFERENCE_FILE

logger = logging.getLogger(__name__)

REPORT_FILE = config.DOCS_DIR / "data_quality_report.md"
REPORT_JSON = config.DOCS_DIR / "data_quality_report.json"
# Harmonised SDAC day-ahead clearing price limits (EUR/MWh).
PRICE_FLOOR, PRICE_CAP = -500.0, 4000.0
IQR_FACTOR = 3.0
# Tolerances for comparing our aggregation with SMARD's hourly series (rounding noise).
TOL_VOLUME_MWH, TOL_PRICE_EUR = 0.1, 0.01
# Plausible hourly grid load for DE-LU in MWh (= average GW). Observed 2023–2025: ~30–80 GW.
# Wide bounds: this catches unit errors (kWh / quarter-hour values) and zeros, not real extremes.
LOAD_MIN_MWH, LOAD_MAX_MWH = 15_000.0, 120_000.0

PASS, WARN, FAIL = "pass", "warn", "fail"


@dataclass
class CheckResult:
    """One machine-readable check outcome."""

    name: str
    description: str
    expected: str
    actual: str
    status: str  # pass | warn | fail
    severity: str  # critical (fails the pipeline) | warning (reported only)
    checked_at_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


@dataclass
class Report:
    """Collects markdown sections, structured check results and critical issues."""

    sections: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    results: list[CheckResult] = field(default_factory=list)

    def add(self, title: str, body: str) -> None:
        self.sections.append(f"## {title}\n\n{body}\n")

    def record(self, name: str, description: str, expected: Any, actual: Any, passed: bool,
               critical: bool = True, message: str | None = None) -> CheckResult:
        """Store a check result; failed critical checks stop the pipeline, failed warnings don't."""
        status = PASS if passed else (FAIL if critical else WARN)
        result = CheckResult(name, description, str(expected), str(actual), status,
                             "critical" if critical else "warning")
        self.results.append(result)
        if not passed:
            text = message or f"{name}: expected {expected}, got {actual}"
            (self.critical if critical else self.warnings).append(text)
            log = logger.error if critical else logger.warning
            log("Quality check %s %s: %s", name, status.upper(), text)
        return result

    @property
    def status(self) -> str:
        return "failed" if self.critical else ("passed_with_warnings" if self.warnings else "passed")


def check_row_counts(gen: pd.DataFrame, pl: pd.DataFrame, rep: Report) -> None:
    """Expected vs. actual hours per local year, and table sizes (record-count reconciliation)."""
    start, end = config.period_bounds_utc()
    grid = pd.date_range(start, end, freq="h", inclusive="left", tz="UTC")
    expected = grid.tz_convert(config.LOCAL_TZ).year.value_counts().sort_index()
    actual = pl.groupby(pl["timestamp_local"].dt.year).size()
    n_sources = gen["source"].nunique()
    table = pd.DataFrame({
        "expected_hours": expected,
        "price_load_rows": actual,
        "generation_rows": gen.groupby(gen["timestamp_local"].dt.year).size(),
        "expected_generation_rows": expected * n_sources,
    }).rename_axis("year")
    rep.record("price_load_row_count", "price/load has exactly one row per hour of the period",
               len(grid), len(pl), len(pl) == len(grid) and (table["expected_hours"] == table["price_load_rows"]).all(),
               message="Hourly grid does not have the expected number of hours per year")
    rep.record("generation_row_count", "generation has one row per hour and source (long format)",
               len(grid) * n_sources, len(gen), len(gen) == len(grid) * n_sources)
    rep.add("1. Row counts", df_to_markdown(table) + f"\n\n{n_sources} generation sources in long format.")


def check_null_keys(gen: pd.DataFrame, pl: pd.DataFrame, rep: Report) -> None:
    """Key columns must never be NULL (values may be; keys may not)."""
    nulls = {
        "generation.timestamp_utc": int(gen["timestamp_utc"].isna().sum()),
        "generation.timestamp_local": int(gen["timestamp_local"].isna().sum()),
        "generation.source": int(gen["source"].isna().sum()),
        "price_load.timestamp_utc": int(pl["timestamp_utc"].isna().sum()),
        "price_load.timestamp_local": int(pl["timestamp_local"].isna().sum()),
    }
    total = sum(nulls.values())
    rep.record("null_keys", "no NULLs in timestamp or source key columns", 0, total, total == 0)
    rep.add("1a. Null keys", "\n".join(f"- {k}: **{v}**" for k, v in nulls.items()))


def check_continuity(pl: pd.DataFrame, rep: Report) -> None:
    """The UTC timestamps must form a gap-free, strictly increasing hourly sequence."""
    ts = pl["timestamp_utc"].dropna()
    steps = ts.diff().dropna()
    one_hour = pd.Timedelta(hours=1)
    gaps = int((steps > one_hour).sum())
    non_increasing = int((steps <= pd.Timedelta(0)).sum())
    off_grid = int((ts != ts.dt.floor("h")).sum())
    rep.record("hourly_continuity", "consecutive UTC timestamps are exactly 1 hour apart",
               "0 gaps", f"{gaps} gaps", gaps == 0)
    rep.record("monotonic_timestamps", "UTC timestamps strictly increasing (no duplicates / disorder)",
               0, non_increasing, non_increasing == 0)
    rep.record("expected_frequency", "every timestamp lies on a full UTC hour (hourly frequency)",
               0, off_grid, off_grid == 0)
    rep.add("1b. Timestamp continuity and frequency",
            f"- gaps > 1 h: **{gaps}**\n- non-increasing steps: **{non_increasing}**\n"
            f"- timestamps not on a full hour: **{off_grid}**")


def check_dst(pl: pd.DataFrame, rep: Report) -> None:
    """Every local day must have 24 hours, except DST switch days (23 / 25)."""
    per_day = pl.groupby(pl["timestamp_local"].dt.date).size()
    odd = per_day[per_day != 24].rename("hours").rename_axis("local_date").to_frame()
    # Spring forward = last Sunday in March (23 h), fall back = last Sunday in October (25 h).
    expected_odd = all(
        d.weekday() == 6 and d.day > 24 and ((d.month == 3 and h == 23) or (d.month == 10 and h == 25))
        for d, h in odd["hours"].items()
    )
    rep.record("dst_days", "only DST switch days (last Sunday Mar = 23h, Oct = 25h) deviate from 24h",
               "all irregular days are DST days", f"{len(odd)} irregular days, all DST: {expected_odd}",
               expected_odd, message="Local days with != 24 hours that are not DST switch days")
    rep.add("2. Daylight saving time",
            "Local days with ≠ 24 hours (expected: last Sunday in March = 23h, October = 25h):\n\n"
            + df_to_markdown(odd) + f"\n\nAll irregular days are DST switch days: **{expected_odd}**.")


def check_missing(gen: pd.DataFrame, pl: pd.DataFrame, rep: Report) -> None:
    """Missing hours per year for every series."""
    year_g = gen["timestamp_local"].dt.year
    miss_gen = gen["generation_mwh"].isna().groupby([gen["source"], year_g]).sum().unstack(fill_value=0)
    year_p = pl["timestamp_local"].dt.year
    miss_pl = pl[["price_eur_mwh", "consumption_mwh"]].isna().groupby(year_p).sum().T
    table = pd.concat([miss_gen, miss_pl]).astype(int)
    table.columns = [str(c) for c in table.columns]
    table = table.rename_axis("series")

    body = df_to_markdown(table)
    nuc = gen[gen["source"] == "nuclear"].dropna(subset=["generation_mwh"])
    if not nuc.empty:
        last_pos = nuc.loc[nuc["generation_mwh"] > 0, "timestamp_local"].max()
        body += (f"\n\n**Nuclear:** last hour with generation > 0 is {last_pos} (local). "
                 "Germany shut down its last reactors on 2023-04-15; afterwards SMARD mostly reports "
                 "no value. These NaNs are expected and are *not* filled.")
    for series, row in table.iterrows():
        if series == "nuclear":
            continue  # expected after the shutdown, see above
        # Price and load drive every analysis -> missing values there are critical.
        critical = series in ("price_eur_mwh", "consumption_mwh")
        rep.record(f"missing_hours.{series}", f"hours without a value for {series}", 0, int(row.sum()),
                   row.sum() == 0, critical=critical, message=f"{series}: {row.sum()} missing hours")
    rep.add("3. Missing hours per year", body)


def check_duplicates(gen: pd.DataFrame, pl: pd.DataFrame, meta: list[dict], rep: Report) -> None:
    """Duplicate keys after transform, plus duplicates seen in the raw chunks."""
    d_gen = int(gen.duplicated(["timestamp_utc", "source"]).sum())
    d_pl = int(pl.duplicated("timestamp_utc").sum())
    raw = pd.DataFrame(meta).set_index("name")[["duplicate_timestamps", "conflicting_duplicates", "non_numeric_values"]]
    conflicting = int(raw["conflicting_duplicates"].sum())
    rep.record("duplicate_keys", "no duplicate (timestamp_utc, source) / timestamp_utc keys after transform",
               0, d_gen + d_pl, d_gen + d_pl == 0, message="Duplicate keys found")
    rep.record("conflicting_raw_duplicates", "raw chunks contain no timestamps with differing values",
               0, conflicting, conflicting == 0, message="Duplicate keys found")
    rep.add("4. Duplicates",
            f"- generation (timestamp_utc, source): **{d_gen}**\n- price_load (timestamp_utc): **{d_pl}**\n\n"
            "Raw quarter-hour chunks (non-numeric values like '-' are coerced to NaN and counted):\n\n"
            + df_to_markdown(raw))


def check_negative_generation(gen: pd.DataFrame, rep: Report) -> None:
    """Generation values should never be negative."""
    neg = gen[gen["generation_mwh"] < 0]
    if neg.empty:
        body = "No negative generation values."
    else:
        body = df_to_markdown(neg.groupby("source")["generation_mwh"].agg(["count", "min"]))
    rep.record("negative_generation", "generation_mwh >= 0", 0, len(neg), neg.empty, critical=False,
               message=f"{len(neg)} negative generation values")
    rep.add("5. Negative generation", body)


def check_load_range(pl: pd.DataFrame, rep: Report) -> None:
    """Grid load must lie in a physically plausible range (catches unit errors)."""
    load = pl["consumption_mwh"].dropna()
    outside = load[(load < LOAD_MIN_MWH) | (load > LOAD_MAX_MWH)]
    rep.record("load_range", f"hourly grid load within [{LOAD_MIN_MWH:,.0f}, {LOAD_MAX_MWH:,.0f}] MWh",
               0, len(outside), outside.empty, critical=False,
               message=f"{len(outside)} grid-load hours outside the plausible range")
    lo, hi = (load.min(), load.max()) if not load.empty else (float("nan"), float("nan"))
    rep.add("5a. Grid load range",
            f"Observed min / max hourly load: **{lo:,.0f} / {hi:,.0f} MWh**. "
            f"Hours outside [{LOAD_MIN_MWH:,.0f}, {LOAD_MAX_MWH:,.0f}]: **{len(outside)}**.")


def check_prices(pl: pd.DataFrame, rep: Report) -> None:
    """Price limits, IQR outliers, extremes and negative-price counts."""
    p = pl.dropna(subset=["price_eur_mwh"])
    price = p["price_eur_mwh"]
    out_of_limits = int(((price < PRICE_FLOOR) | (price > PRICE_CAP)).sum())
    q1, q3 = price.quantile([0.25, 0.75])
    lo, hi = q1 - IQR_FACTOR * (q3 - q1), q3 + IQR_FACTOR * (q3 - q1)
    iqr_out = p[(price < lo) | (price > hi)]
    rep.record("price_limits", f"day-ahead price within harmonised limits [{PRICE_FLOOR:.0f}, {PRICE_CAP:.0f}]",
               0, out_of_limits, out_of_limits == 0,
               message=f"{out_of_limits} prices outside the harmonised limits")

    stats = price.groupby(p["timestamp_local"].dt.year).agg(
        ["count", "mean", "median", "min", "max", lambda s: int((s < 0).sum())])
    stats.columns = ["hours", "mean", "median", "min", "max", "negative_hours"]
    cols = ["timestamp_local", "price_eur_mwh"]
    body = (
        df_to_markdown(stats.rename_axis("year"))
        + f"\n\n- Outside harmonised limits [{PRICE_FLOOR:.0f}, {PRICE_CAP:.0f}] EUR/MWh: **{out_of_limits}**"
        + f"\n- IQR outliers (outside [{lo:.2f}, {hi:.2f}], factor {IQR_FACTOR}): **{len(iqr_out)}** hours "
        "– kept, since price spikes and negative prices are real market outcomes and the focus of this analysis."
        + "\n\nFive highest hours:\n\n" + df_to_markdown(p.nlargest(5, "price_eur_mwh")[cols], index=False)
        + "\n\nFive lowest hours:\n\n" + df_to_markdown(p.nsmallest(5, "price_eur_mwh")[cols], index=False)
    )
    rep.add("6. Price plausibility and outliers", body)


def check_reconciliation(gen: pd.DataFrame, pl: pd.DataFrame, ref: pd.DataFrame, rep: Report) -> None:
    """Compare our quarter-hour -> hour aggregation with SMARD's own hourly series."""
    ours = pd.concat([
        gen.rename(columns={"source": "series", "generation_mwh": "value"})[["timestamp_utc", "series", "value"]],
        pl.melt(id_vars="timestamp_utc", value_vars=["price_eur_mwh", "consumption_mwh"],
                var_name="series", value_name="value")
          .replace({"series": {"price_eur_mwh": "day_ahead_price", "consumption_mwh": "grid_load"}}),
    ])
    m = ours.merge(ref, on=["timestamp_utc", "series"], how="outer", suffixes=("_ours", "_smard"))
    m["abs_diff"] = (m["value_ours"] - m["value_smard"]).abs()
    m["tol"] = TOL_VOLUME_MWH
    m.loc[m["series"] == "day_ahead_price", "tol"] = TOL_PRICE_EUR
    m["mismatch"] = m["abs_diff"] > m["tol"]
    m["only_one_side"] = m["value_ours"].isna() != m["value_smard"].isna()
    table = m.groupby("series").agg(
        compared_hours=("abs_diff", "count"), max_abs_diff=("abs_diff", "max"),
        mismatches=("mismatch", "sum"), value_on_one_side_only=("only_one_side", "sum"))
    mismatches = int(table["mismatches"].sum())
    rep.record("smard_reconciliation", "our hourly aggregation equals SMARD's hourly series within tolerance",
               0, f"{mismatches} mismatching hours", mismatches == 0,
               message="Hourly aggregation differs from SMARD hourly values beyond tolerance")
    rep.add("7. Reconciliation with SMARD hourly series",
            f"Our hourly values (aggregated from quarter-hours) vs. SMARD's own hourly series. "
            f"Tolerance: {TOL_VOLUME_MWH} MWh for volumes, {TOL_PRICE_EUR} EUR/MWh for prices.\n\n"
            + df_to_markdown(table))


def check_resolution(meta: list[dict], rep: Report) -> None:
    """Document detected raw resolution and the effective price resolution."""
    df = pd.DataFrame(meta).set_index("name")[
        ["step_minutes", "raw_points", "null_quarters", "incomplete_hours", "effective_15min_from"]]
    steps = sorted({s for s in df["step_minutes"].dropna()})
    rep.record("raw_resolution", "raw series are delivered in 15-minute steps", "[15.0]", steps,
               steps == [15.0], critical=False)
    rep.add("8. Resolution detection",
            "Raw data was downloaded in quarter-hour resolution. `step_minutes` is the most frequent "
            "gap between timestamps. For the price, `effective_15min_from` is the first local date on "
            "which the four quarter-hour prices of an hour differ, i.e. when the day-ahead market switched "
            "to 15-minute products. Before that, SMARD repeats the hourly price in each quarter.\n\n"
            "Aggregation: volumes are summed, prices averaged (unweighted). An hour is only "
            "built if all 4 quarters exist, otherwise it stays NaN.\n\n" + df_to_markdown(df.fillna("–")))


def check_balance(gen: pd.DataFrame, pl: pd.DataFrame, rep: Report) -> None:
    """Sanity check: yearly generation vs. grid load (difference ≈ net imports, storage, own use)."""
    g = gen.groupby(gen["timestamp_local"].dt.year)["generation_mwh"].sum() / 1e6
    load = pl.groupby(pl["timestamp_local"].dt.year)["consumption_mwh"].sum() / 1e6
    table = pd.DataFrame({"generation_twh": g, "grid_load_twh": load,
                          "generation_to_load": g / load}).rename_axis("year")
    rep.add("9. Plausibility: generation vs. grid load",
            "Totals in TWh. A ratio below 1 is plausible since Germany has been a net importer since 2023; "
            "the gap also includes storage and measurement differences.\n\n" + df_to_markdown(table))


def run_checks(gen: pd.DataFrame, pl: pd.DataFrame, ref: pd.DataFrame, meta: list[dict]) -> Report:
    """Run every check on in-memory frames (no file I/O, so it is unit-testable)."""
    rep = Report()
    rep.add("0. Source format and time handling",
            "Data comes from SMARD's chart-data JSON API, not the CSV download portal. Values are plain "
            "JSON numbers (no German '1.234,5' format or ';' separators) and missing values are `null` "
            "(counted below; '-' or other strings would be coerced to NaN and counted as non-numeric). "
            "Timestamps are epoch milliseconds (UTC), so DST is unambiguous: the pipeline keys on UTC and "
            "derives Europe/Berlin local time plus UTC offset for reporting.")
    check_row_counts(gen, pl, rep)
    check_null_keys(gen, pl, rep)
    check_continuity(pl, rep)
    check_dst(pl, rep)
    check_missing(gen, pl, rep)
    check_duplicates(gen, pl, meta, rep)
    check_negative_generation(gen, rep)
    check_load_range(pl, rep)
    check_prices(pl, rep)
    check_reconciliation(gen, pl, ref, rep)
    check_resolution(meta, rep)
    check_balance(gen, pl, rep)
    return rep


def results_table(results: list[CheckResult]) -> str:
    """Markdown summary table of all check results."""
    icon = {PASS: "✅ pass", WARN: "⚠️ warn", FAIL: "❌ fail"}
    rows = pd.DataFrame([
        {"check": r.name, "description": r.description, "expected": r.expected, "actual": r.actual,
         "severity": r.severity, "status": icon[r.status]}
        for r in results
    ])
    return df_to_markdown(rows, index=False)


def write_reports(rep: Report, manifest: dict[str, Any]) -> None:
    """Write the markdown and JSON reports to docs/."""
    generated = datetime.now(timezone.utc)
    status = {"failed": "❌ FAILED", "passed_with_warnings": "⚠️ PASSED with warnings",
              "passed": "✅ PASSED"}[rep.status]
    summary = "\n".join([f"- **Critical:** {c}" for c in rep.critical]
                        + [f"- Warning: {w}" for w in rep.warnings]) or "- No issues."
    header = (
        "# Data quality report\n\n"
        f"Generated: {generated:%Y-%m-%d %H:%M} UTC · "
        f"Source: {manifest['source']} · region {manifest['region']} · "
        f"retrieved {manifest['retrieved_at_utc']} · period {manifest['period'][0]} – {manifest['period'][1]}\n\n"
        f"**Status: {status}**\n\n{summary}\n\n"
        f"## Check summary\n\nMachine-readable version: [`data_quality_report.json`](data_quality_report.json).\n\n"
        f"{results_table(rep.results)}\n"
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(header + "\n" + "\n".join(rep.sections))
    REPORT_JSON.write_text(json.dumps({
        "generated_at_utc": generated.isoformat(timespec="seconds"),
        "status": rep.status,
        "source": {k: manifest.get(k) for k in ("source", "region", "retrieved_at_utc", "period")},
        "summary": {s: sum(r.status == s for r in rep.results) for s in (PASS, WARN, FAIL)},
        "checks": [asdict(r) for r in rep.results],
    }, indent=2) + "\n")


def run() -> Report:
    """Load the processed files, run all checks and write the reports."""
    gen = pd.read_parquet(GENERATION_FILE)
    pl = pd.read_parquet(PRICE_LOAD_FILE)
    ref = pd.read_parquet(REFERENCE_FILE)
    meta = json.loads(METADATA_FILE.read_text())
    manifest = json.loads((config.RAW_DIR / "smard" / "manifest.json").read_text())

    rep = run_checks(gen, pl, ref, meta)
    write_reports(rep, manifest)
    n = {s: sum(r.status == s for r in rep.results) for s in (PASS, WARN, FAIL)}
    logger.info("Quality report written to %s – %s (%d pass, %d warn, %d fail)",
                REPORT_FILE, rep.status, n[PASS], n[WARN], n[FAIL])
    return rep


def main() -> None:
    """CLI entry point; exits non-zero on critical issues so the pipeline stops."""
    rep = run()
    if rep.critical:
        raise SystemExit("Critical data quality issues: " + "; ".join(rep.critical))


if __name__ == "__main__":
    config.setup_logging()
    main()
