"""Data quality checks on the processed hourly data.

Writes docs/data_quality_report.md and raises if a *critical* check fails
(duplicates, broken hourly grid, aggregation not matching SMARD's own hourly
values). Non-critical findings (missing values, outliers) are reported only –
we never fix data silently.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd

from src import config
from src.reporting import df_to_markdown
from src.transform import GENERATION_FILE, METADATA_FILE, PRICE_LOAD_FILE, REFERENCE_FILE

logger = logging.getLogger(__name__)

REPORT_FILE = config.DOCS_DIR / "data_quality_report.md"
# Harmonised SDAC day-ahead clearing price limits (EUR/MWh).
PRICE_FLOOR, PRICE_CAP = -500.0, 4000.0
IQR_FACTOR = 3.0
# Tolerances for comparing our aggregation with SMARD's hourly series (rounding noise).
TOL_VOLUME_MWH, TOL_PRICE_EUR = 0.1, 0.01


@dataclass
class Report:
    """Collects markdown sections plus critical issues."""

    sections: list[str] = field(default_factory=list)
    critical: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def add(self, title: str, body: str) -> None:
        self.sections.append(f"## {title}\n\n{body}\n")


def check_row_counts(gen: pd.DataFrame, pl: pd.DataFrame, rep: Report) -> None:
    """Expected vs. actual hours per local year, and table sizes."""
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
    if not (table["expected_hours"] == table["price_load_rows"]).all():
        rep.critical.append("Hourly grid does not have the expected number of hours per year")
    rep.add("1. Row counts", df_to_markdown(table) + f"\n\n{n_sources} generation sources in long format.")


def check_dst(pl: pd.DataFrame, rep: Report) -> None:
    """Every local day must have 24 hours, except DST switch days (23 / 25)."""
    per_day = pl.groupby(pl["timestamp_local"].dt.date).size()
    odd = per_day[per_day != 24].rename("hours").rename_axis("local_date").to_frame()
    expected_odd = all(d.month in (3, 10) and d.weekday() == 6 for d in odd.index)  # last Sundays
    if not expected_odd:
        rep.critical.append("Local days with != 24 hours that are not DST switch days")
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
        if series != "nuclear" and row.sum() > 0:
            rep.warnings.append(f"{series}: {row.sum()} missing hours")
    rep.add("3. Missing hours per year", body)


def check_duplicates(gen: pd.DataFrame, pl: pd.DataFrame, meta: list[dict], rep: Report) -> None:
    """Duplicate keys after transform, plus duplicates seen in the raw chunks."""
    d_gen = int(gen.duplicated(["timestamp_utc", "source"]).sum())
    d_pl = int(pl.duplicated("timestamp_utc").sum())
    raw = pd.DataFrame(meta).set_index("name")[["duplicate_timestamps", "conflicting_duplicates", "non_numeric_values"]]
    if d_gen or d_pl or raw["conflicting_duplicates"].sum():
        rep.critical.append("Duplicate keys found")
    rep.add("4. Duplicates",
            f"- generation (timestamp_utc, source): **{d_gen}**\n- price_load (timestamp_utc): **{d_pl}**\n\n"
            "Raw quarter-hour chunks (non-numeric values like '-' are coerced to NaN and counted):\n\n" + df_to_markdown(raw))


def check_negative_generation(gen: pd.DataFrame, rep: Report) -> None:
    """Generation values should never be negative."""
    neg = gen[gen["generation_mwh"] < 0]
    if neg.empty:
        body = "No negative generation values."
    else:
        body = df_to_markdown(neg.groupby("source")["generation_mwh"].agg(["count", "min"]))
        rep.warnings.append(f"{len(neg)} negative generation values")
    rep.add("5. Negative generation", body)


def check_prices(pl: pd.DataFrame, rep: Report) -> None:
    """Price limits, IQR outliers, extremes and negative-price counts."""
    p = pl.dropna(subset=["price_eur_mwh"])
    price = p["price_eur_mwh"]
    out_of_limits = int(((price < PRICE_FLOOR) | (price > PRICE_CAP)).sum())
    q1, q3 = price.quantile([0.25, 0.75])
    lo, hi = q1 - IQR_FACTOR * (q3 - q1), q3 + IQR_FACTOR * (q3 - q1)
    iqr_out = p[(price < lo) | (price > hi)]
    if out_of_limits:
        rep.critical.append(f"{out_of_limits} prices outside the harmonised limits")

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
    if table["mismatches"].sum():
        rep.critical.append("Hourly aggregation differs from SMARD hourly values beyond tolerance")
    rep.add("7. Reconciliation with SMARD hourly series",
            f"Our hourly values (aggregated from quarter-hours) vs. SMARD's own hourly series. "
            f"Tolerance: {TOL_VOLUME_MWH} MWh for volumes, {TOL_PRICE_EUR} EUR/MWh for prices.\n\n" + df_to_markdown(table))


def check_resolution(meta: list[dict], rep: Report) -> None:
    """Document detected raw resolution and the effective price resolution."""
    df = pd.DataFrame(meta).set_index("name")[
        ["step_minutes", "raw_points", "null_quarters", "incomplete_hours", "effective_15min_from"]]
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
    table = pd.DataFrame({"generation_twh": g, "grid_load_twh": load, "generation_to_load": g / load}).rename_axis("year")
    rep.add("9. Plausibility: generation vs. grid load",
            "Totals in TWh. A ratio below 1 is plausible since Germany has been a net importer since 2023; "
            "the gap also includes storage and measurement differences.\n\n" + df_to_markdown(table))


def run() -> Report:
    """Run all checks and write the markdown report."""
    gen = pd.read_parquet(GENERATION_FILE)
    pl = pd.read_parquet(PRICE_LOAD_FILE)
    ref = pd.read_parquet(REFERENCE_FILE)
    meta = json.loads(METADATA_FILE.read_text())
    manifest = json.loads((config.RAW_DIR / "smard" / "manifest.json").read_text())

    rep = Report()
    rep.add("0. Source format and time handling",
            "Data comes from SMARD's chart-data JSON API, not the CSV download portal. Values are plain "
            "JSON numbers (no German '1.234,5' format or ';' separators) and missing values are `null` "
            "(counted below; '-' or other strings would be coerced to NaN and counted as non-numeric). "
            "Timestamps are epoch milliseconds (UTC), so DST is unambiguous: the pipeline keys on UTC and "
            "derives Europe/Berlin local time plus UTC offset for reporting.")
    check_row_counts(gen, pl, rep)
    check_dst(pl, rep)
    check_missing(gen, pl, rep)
    check_duplicates(gen, pl, meta, rep)
    check_negative_generation(gen, rep)
    check_prices(pl, rep)
    check_reconciliation(gen, pl, ref, rep)
    check_resolution(meta, rep)
    check_balance(gen, pl, rep)

    status = "❌ FAILED" if rep.critical else ("⚠️ PASSED with warnings" if rep.warnings else "✅ PASSED")
    summary = "\n".join([f"- **Critical:** {c}" for c in rep.critical] + [f"- Warning: {w}" for w in rep.warnings]) or "- No issues."
    header = (
        "# Data quality report\n\n"
        f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC · "
        f"Source: {manifest['source']} · region {manifest['region']} · "
        f"retrieved {manifest['retrieved_at_utc']} · period {manifest['period'][0]} – {manifest['period'][1]}\n\n"
        f"**Status: {status}**\n\n{summary}\n"
    )
    config.DOCS_DIR.mkdir(exist_ok=True)
    REPORT_FILE.write_text(header + "\n" + "\n".join(rep.sections))
    logger.info("Quality report written to %s – %s", REPORT_FILE, status)
    return rep


def main() -> None:
    """CLI entry point; exits non-zero on critical issues so the pipeline stops."""
    rep = run()
    if rep.critical:
        raise SystemExit("Critical data quality issues: " + "; ".join(rep.critical))


if __name__ == "__main__":
    config.setup_logging()
    main()
