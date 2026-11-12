"""Semantic layer: approved business metrics, defined on the dbt marts.

Only metrics the warehouse actually supports are listed. Every `example_sql` is executed
against the warehouse by `python -m analytics_agent.cli --verify-metrics`, which writes the
results to docs/metric_catalogue.md, and is checked by the SQL validator in the unit tests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Metric:
    name: str
    definition: str
    formula: str
    tables: tuple[str, ...]
    columns: tuple[str, ...]
    aggregation: str
    unit: str
    limitations: str
    example_question: str
    example_sql: str


METRICS: tuple[Metric, ...] = (
    Metric(
        "average_day_ahead_price",
        "Time-weighted average of the hourly day-ahead price (each hour counts once).",
        "AVG(price_eur_mwh)",
        ("marts.fct_market_hourly",),
        ("price_eur_mwh",),
        "mean over hours",
        "EUR/MWh",
        "Not volume-weighted (traded volumes are not in the data). Monthly/daily marts hold the same mean per period; "
        "averaging monthly averages is not equal to the yearly average.",
        "What was the average electricity price in 2024?",
        "SELECT year, round(avg(price_eur_mwh), 2) AS avg_price_eur_mwh FROM marts.fct_market_hourly "
        "GROUP BY year ORDER BY year",
    ),
    Metric(
        "renewable_share",
        "Share of net generation that comes from renewable sources (wind, solar, biomass, hydro, other renewables).",
        "SUM(renewable_mwh) / SUM(total_gen_mwh)",
        ("marts.fct_market_hourly", "marts.mart_market_monthly", "marts.mart_market_daily"),
        ("renewable_mwh", "total_gen_mwh"),
        "energy-weighted ratio of sums",
        "fraction 0–1 (×100 for %)",
        "Share of net generation (SMARD convention), not of gross consumption as in official German targets. "
        "Never average hourly or monthly shares. Pumped storage counts in the total but is not renewable.",
        "What was the renewable share per year?",
        "SELECT year, round(100 * sum(renewable_mwh) / sum(total_gen_mwh), 1) AS renewable_share_pct "
        "FROM marts.fct_market_hourly GROUP BY year ORDER BY year",
    ),
    Metric(
        "total_generation",
        "Total net electricity generation of all sources.",
        "SUM(total_gen_mwh)  (or SUM(generation_mwh) in fct_generation_hourly)",
        ("marts.fct_market_hourly", "marts.fct_generation_hourly", "marts.mart_market_monthly"),
        ("total_gen_mwh", "generation_mwh"),
        "sum",
        "MWh (÷ 1e6 for TWh)",
        "Net generation only; 20 source-hours are missing in 2023–2025 (slight understatement).",
        "Which month had the highest electricity generation?",
        "SELECT year_month, round(total_gen_mwh / 1e6, 2) AS total_gen_twh FROM marts.mart_market_monthly "
        "ORDER BY total_gen_mwh DESC LIMIT 1",
    ),
    Metric(
        "generation_by_source",
        "Net generation per source or category (renewable, fossil, nuclear, other).",
        "SUM(generation_mwh) GROUP BY source_name | category",
        ("marts.fct_generation_hourly",),
        ("generation_mwh", "source_name", "category"),
        "sum",
        "MWh",
        "Nuclear has no data after the shutdown on 2023-04-15. 'other' = pumped storage.",
        "How much solar and wind was generated in 2023 and 2024?",
        "SELECT year, source_name, round(sum(generation_mwh) / 1e6, 2) AS twh FROM marts.fct_generation_hourly "
        "WHERE source_name IN ('solar', 'wind_onshore', 'wind_offshore') AND year IN (2023, 2024) "
        "GROUP BY year, source_name ORDER BY year, source_name",
    ),
    Metric(
        "total_consumption",
        "Total grid load (Netzlast).",
        "SUM(consumption_mwh)",
        ("marts.fct_market_hourly", "marts.mart_market_monthly"),
        ("consumption_mwh",),
        "sum",
        "MWh (÷ 1e6 for TWh)",
        "Grid load, not total electricity consumption including self-generation.",
        "What was the total grid load per year?",
        "SELECT year, round(sum(consumption_mwh) / 1e6, 1) AS grid_load_twh FROM marts.fct_market_hourly "
        "GROUP BY year ORDER BY year",
    ),
    Metric(
        "residual_load",
        "Demand not covered by wind and solar: grid load minus wind and solar generation.",
        "consumption_mwh - variable_renewable_mwh; averaged: AVG(residual_load_mwh)",
        ("marts.fct_market_hourly",),
        ("residual_load_mwh",),
        "mean over hours",
        "MWh per hour (= average MW)",
        "Uses grid load, so imports/exports and storage are not netted out.",
        "What was the average residual load in negative-price hours vs other hours?",
        "SELECT is_negative_price, round(avg(residual_load_mwh) / 1000, 1) AS avg_residual_load_gw "
        "FROM marts.fct_market_hourly GROUP BY is_negative_price",
    ),
    Metric(
        "peak_demand",
        "Highest hourly grid load in a period.",
        "MAX(consumption_mwh)",
        ("marts.fct_market_hourly", "marts.mart_market_monthly"),
        ("consumption_mwh", "peak_hourly_load_mwh"),
        "max",
        "MWh in one hour (= average MW; ÷ 1000 for GW)",
        "Hourly average, so short intra-hour peaks are smoothed.",
        "What was the peak demand in each year?",
        "SELECT year, round(max(consumption_mwh) / 1000, 1) AS peak_load_gw FROM marts.fct_market_hourly "
        "GROUP BY year ORDER BY year",
    ),
    Metric(
        "negative_price_hours",
        "Number (and share) of hours with a negative day-ahead price.",
        "COUNT(*) FILTER (WHERE is_negative_price); share = that / COUNT(*)",
        ("marts.fct_market_hourly", "marts.mart_market_monthly", "marts.mart_market_daily"),
        ("is_negative_price", "negative_price_hours"),
        "count",
        "hours / fraction",
        "Since 2025-10-01 an hour is the mean of four quarter-hour prices, so a single negative quarter-hour does "
        "not make the hour negative (counts slightly conservative).",
        "What percentage of hours had negative prices in each year?",
        "SELECT year, count(*) FILTER (WHERE is_negative_price) AS negative_hours, "
        "round(100.0 * count(*) FILTER (WHERE is_negative_price) / count(*), 2) AS negative_pct "
        "FROM marts.fct_market_hourly GROUP BY year ORDER BY year",
    ),
    Metric(
        "price_volatility",
        "Sample standard deviation of hourly day-ahead prices within a period.",
        "STDDEV_SAMP(price_eur_mwh)",
        ("marts.mart_market_monthly", "marts.fct_market_hourly"),
        ("price_stddev_eur_mwh", "price_eur_mwh"),
        "standard deviation",
        "EUR/MWh",
        "Measures dispersion of hourly prices, not return volatility.",
        "Which month had the most volatile prices?",
        "SELECT year_month, round(price_stddev_eur_mwh, 2) AS price_stddev FROM marts.mart_market_monthly "
        "ORDER BY price_stddev_eur_mwh DESC LIMIT 3",
    ),
    Metric(
        "peak_offpeak_spread",
        "Average peak price (Mon–Fri 08–20 local) minus average off-peak price.",
        "AVG(price) FILTER (WHERE is_peak) - AVG(price) FILTER (WHERE NOT is_peak)",
        ("marts.fct_market_hourly",),
        ("price_eur_mwh", "is_peak"),
        "difference of means",
        "EUR/MWh",
        "Public holidays on weekdays count as peak (EEX definition).",
        "How did the peak/off-peak price spread develop?",
        "SELECT year, round(avg(price_eur_mwh) FILTER (WHERE is_peak) - avg(price_eur_mwh) FILTER (WHERE NOT is_peak), 2) "
        "AS spread_eur_mwh FROM marts.fct_market_hourly GROUP BY year ORDER BY year",
    ),
    Metric(
        "residual_load_price_correlation",
        "Pearson correlation between hourly residual load and price.",
        "CORR(residual_load_mwh, price_eur_mwh)",
        ("marts.fct_market_hourly",),
        ("residual_load_mwh", "price_eur_mwh"),
        "correlation",
        "r (−1 to 1)",
        "Association, not causation; fuel and CO2 prices are not in the data.",
        "What was the relationship between residual load and electricity prices?",
        "SELECT round(corr(residual_load_mwh, price_eur_mwh)::numeric, 3) AS r, "
        "round(regr_r2(price_eur_mwh, residual_load_mwh)::numeric, 3) AS r_squared FROM marts.fct_market_hourly",
    ),
)


def as_dict() -> list[dict]:
    return [asdict(m) for m in METRICS]


def as_prompt_text() -> str:
    return "\n".join(
        f"- {m.name}: {m.definition} Formula: {m.formula}. Unit: {m.unit}. Caveat: {m.limitations}" for m in METRICS
    )
