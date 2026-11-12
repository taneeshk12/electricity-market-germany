"""The approved part of the warehouse the agent may see and query.

Only the dbt marts are exposed – no raw facts, no `public` schema, no system catalogs.
Descriptions are curated here (business meaning, units, caveats); the column lists were
taken from information_schema and are re-checked against the live database by
`verify_against_database` (tests + `make agent-check`).
"""

from __future__ import annotations

from dataclasses import dataclass

APPROVED_SCHEMA = "marts"


@dataclass(frozen=True)
class Column:
    name: str
    type: str
    description: str


@dataclass(frozen=True)
class Table:
    name: str
    grain: str
    description: str
    columns: tuple[Column, ...]

    @property
    def qualified_name(self) -> str:
        return f"{APPROVED_SCHEMA}.{self.name}"


_CAL = (
    Column("local_date", "date", "Local (Europe/Berlin) calendar date"),
    Column("year", "smallint", "Local calendar year (2023–2025)"),
    Column("month", "smallint", "Local month 1–12"),
    Column("year_month", "char(7)", "'YYYY-MM' of the local month"),
)

TABLES: tuple[Table, ...] = (
    Table(
        "fct_market_hourly",
        "one row per UTC hour (26,304 rows)",
        "Hourly day-ahead price, grid load, generation by category and calendar attributes, market area DE-LU.",
        (
            Column("timestamp_utc", "timestamptz", "Start of the hour in UTC (unique)"),
            Column(
                "timestamp_local",
                "timestamp",
                "Start of the hour, German local time (02:00 repeats on the autumn DST day)",
            ),
            Column("utc_offset_h", "smallint", "1 = CET (winter), 2 = CEST (summer)"),
            *_CAL,
            Column("quarter", "smallint", "Local quarter 1–4"),
            Column("month_name", "varchar", "English month name, e.g. 'January'"),
            Column("iso_weekday", "smallint", "1 = Monday … 7 = Sunday"),
            Column("weekday_name", "varchar", "English weekday name, e.g. 'Monday'"),
            Column("is_weekend", "boolean", "Saturday or Sunday"),
            Column("is_public_holiday", "boolean", "German nationwide public holiday (regional holidays not included)"),
            Column("season", "varchar", "Meteorological season: Winter (Dec–Feb), Spring, Summer, Autumn"),
            Column("hour_of_day", "smallint", "Local hour 0–23"),
            Column("day_period", "varchar", "Night (22–5), Morning (6–10), Midday (11–15), Evening (16–21)"),
            Column("is_peak", "boolean", "Mon–Fri 08:00–20:00 local (EEX peak definition)"),
            Column(
                "price_eur_mwh",
                "numeric",
                "Day-ahead price in EUR/MWh (DE-LU); hourly mean of quarter-hour prices since 2025-10-01",
            ),
            Column("is_negative_price", "boolean", "price_eur_mwh < 0"),
            Column("consumption_mwh", "numeric", "Grid load in the hour, MWh (= average MW)"),
            Column("total_gen_mwh", "numeric", "Total net generation of all sources in the hour, MWh"),
            Column("renewable_mwh", "numeric", "Generation from wind, solar, biomass, hydro, other renewables, MWh"),
            Column("variable_renewable_mwh", "numeric", "Wind + solar generation, MWh"),
            Column("solar_mwh", "numeric", "Solar PV generation, MWh"),
            Column("wind_mwh", "numeric", "Wind onshore + offshore generation, MWh"),
            Column("fossil_mwh", "numeric", "Lignite, hard coal, natural gas, other conventional, MWh"),
            Column("renewable_share", "numeric", "renewable_mwh / total_gen_mwh for this single hour (0–1)"),
            Column("residual_load_mwh", "numeric", "consumption_mwh minus wind and solar generation, MWh"),
        ),
    ),
    Table(
        "fct_generation_hourly",
        "one row per UTC hour and generation source (298,792 rows)",
        "Net generation per source. Hours without a value are absent (nuclear ends 2023-04-15).",
        (
            Column("timestamp_utc", "timestamptz", "Start of the hour in UTC"),
            Column("timestamp_local", "timestamp", "Start of the hour, German local time"),
            *_CAL,
            Column("hour_of_day", "smallint", "Local hour 0–23"),
            Column(
                "source_name",
                "varchar",
                "wind_onshore, wind_offshore, solar, biomass, hydro, other_renewable, "
                "lignite, hard_coal, natural_gas, other_conventional, nuclear, pumped_storage",
            ),
            Column("source_label", "varchar", "Display name, e.g. 'Solar (PV)'"),
            Column("category", "varchar", "renewable | fossil | nuclear | other (other = pumped storage)"),
            Column("is_variable_renewable", "boolean", "Wind or solar"),
            Column("generation_mwh", "numeric", "Net generation in the hour, MWh"),
        ),
    ),
    Table(
        "mart_market_daily",
        "one row per local date (1,096 rows)",
        "Daily aggregates. Days have 23 or 25 hours on DST switch days.",
        (
            *_CAL,
            Column("weekday_name", "varchar", "English weekday name"),
            Column("is_weekend", "boolean", "Saturday or Sunday"),
            Column("is_public_holiday", "boolean", "German nationwide public holiday"),
            Column("season", "varchar", "Winter, Spring, Summer, Autumn"),
            Column("hours", "bigint", "Hours in the day (23/24/25)"),
            Column("avg_price_eur_mwh", "numeric", "Mean hourly day-ahead price, EUR/MWh (unweighted)"),
            Column("min_price_eur_mwh", "numeric", "Lowest hourly price, EUR/MWh"),
            Column("max_price_eur_mwh", "numeric", "Highest hourly price, EUR/MWh"),
            Column("negative_price_hours", "bigint", "Hours with a negative price"),
            Column("consumption_mwh", "numeric", "Total grid load of the day, MWh"),
            Column("peak_hourly_load_mwh", "numeric", "Highest hourly grid load of the day, MWh (= MW)"),
            Column("total_gen_mwh", "numeric", "Total net generation, MWh"),
            Column("renewable_mwh", "numeric", "Renewable generation, MWh"),
            Column("renewable_share", "numeric", "Energy-weighted renewable share of net generation (0–1)"),
            Column("avg_residual_load_mwh", "numeric", "Mean hourly residual load, MWh"),
        ),
    ),
    Table(
        "mart_market_monthly",
        "one row per local month (36 rows)",
        "Monthly aggregates incl. price volatility and peak/off-peak prices.",
        (
            Column("year_month", "char(7)", "'YYYY-MM'"),
            Column("year", "smallint", "Year"),
            Column("month", "smallint", "Month 1–12"),
            Column("hours", "bigint", "Hours in the month"),
            Column("avg_price_eur_mwh", "numeric", "Mean hourly day-ahead price, EUR/MWh (unweighted)"),
            Column(
                "price_stddev_eur_mwh", "numeric", "Sample standard deviation of hourly prices (volatility), EUR/MWh"
            ),
            Column("min_price_eur_mwh", "numeric", "Lowest hourly price"),
            Column("max_price_eur_mwh", "numeric", "Highest hourly price"),
            Column("avg_peak_price_eur_mwh", "numeric", "Mean price in peak hours (Mon–Fri 08–20)"),
            Column("avg_offpeak_price_eur_mwh", "numeric", "Mean price in all other hours"),
            Column("negative_price_hours", "bigint", "Hours with a negative price"),
            Column("negative_price_hour_share", "numeric", "negative_price_hours / hours (0–1)"),
            Column("consumption_mwh", "numeric", "Total grid load, MWh"),
            Column("peak_hourly_load_mwh", "numeric", "Highest hourly grid load, MWh (= MW)"),
            Column("total_gen_mwh", "numeric", "Total net generation, MWh"),
            Column("renewable_mwh", "numeric", "Renewable generation, MWh"),
            Column("solar_mwh", "numeric", "Solar generation, MWh"),
            Column("wind_mwh", "numeric", "Wind generation, MWh"),
            Column("fossil_mwh", "numeric", "Fossil generation, MWh"),
            Column("renewable_share", "numeric", "Energy-weighted renewable share of net generation (0–1)"),
            Column("avg_residual_load_mwh", "numeric", "Mean hourly residual load, MWh"),
        ),
    ),
)

APPROVED_TABLES: frozenset[str] = frozenset(t.name for t in TABLES)

DATA_NOTES: tuple[str, ...] = (
    "Data: SMARD.de (Bundesnetzagentur, CC BY 4.0), market area DE-LU, hourly, local dates 2023-01-01 to 2025-12-31.",
    "Renewable share is a share of net generation (SMARD convention), not of gross consumption.",
    "Over periods, compute shares energy-weighted: SUM(renewable_mwh) / SUM(total_gen_mwh); never average hourly shares.",
    "Not in the data: fuel/gas/CO2 prices, cross-border flows, imports/exports, intraday prices, regional data, forecasts.",
)


def get_table(name: str) -> Table:
    for t in TABLES:
        if t.name == name:
            return t
    raise KeyError(name)


def as_dict() -> dict:
    """JSON-serialisable schema description (returned by the MCP tool)."""
    return {
        "schema": APPROVED_SCHEMA,
        "tables": [
            {
                "name": t.qualified_name,
                "grain": t.grain,
                "description": t.description,
                "columns": [{"name": c.name, "type": c.type, "description": c.description} for c in t.columns],
            }
            for t in TABLES
        ],
        "notes": list(DATA_NOTES),
    }


def as_prompt_text() -> str:
    """Compact schema description for the LLM prompt."""
    lines = []
    for t in TABLES:
        lines.append(f"TABLE {t.qualified_name}  -- {t.grain}. {t.description}")
        lines += [f"  {c.name} {c.type}  -- {c.description}" for c in t.columns]
    lines.append("NOTES:")
    lines += [f"- {n}" for n in DATA_NOTES]
    return "\n".join(lines)


def verify_against_database(columns_by_table: dict[str, set[str]]) -> list[str]:
    """Compare the curated context with information_schema; returns a list of problems."""
    problems = []
    for t in TABLES:
        actual = columns_by_table.get(t.name)
        if actual is None:
            problems.append(f"table {t.qualified_name} missing in database")
            continue
        missing = {c.name for c in t.columns} - actual
        if missing:
            problems.append(f"{t.qualified_name}: documented columns not in database: {sorted(missing)}")
    return problems
