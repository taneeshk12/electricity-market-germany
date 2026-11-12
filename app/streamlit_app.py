"""Streamlit front end for the electricity analytics agent.

    make app      # http://localhost:8501

The app is a thin client: all data access goes through the agent -> MCP tools ->
SQL validator -> read-only PostgreSQL role.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analytics_agent import config  # noqa: E402
from analytics_agent.agent import AgentResult, AnalyticsAgent  # noqa: E402
from analytics_agent.llm import GroqLLM  # noqa: E402
from analytics_agent.tools.execute_query import get_available_date_range  # noqa: E402

EXAMPLES = [
    "What was the average electricity price in 2024?",
    "Which month had the highest electricity generation?",
    "Compare solar and wind generation between 2023 and 2025.",
    "What percentage of hours had negative prices in each year?",
    "What was the relationship between residual load and electricity prices?",
    "Show the five days with the highest average price.",
    "Compare weekday and weekend electricity prices.",
    "What was the gas price in 2024?",  # not in the data -> the agent should abstain
]

st.set_page_config(page_title="German electricity market – ask the data", page_icon="⚡", layout="wide")


@st.cache_resource
def get_agent() -> AnalyticsAgent:
    return AnalyticsAgent(GroqLLM(config.get_llm_config()))


@st.cache_data(ttl=3600)
def coverage() -> dict:
    return get_available_date_range()


def pick_chart(df: pd.DataFrame) -> None:
    """Draw a simple chart when the result shape suggests one; otherwise show nothing."""
    if len(df) < 2 or len(df.columns) < 2:
        return
    numeric = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
    if not numeric:
        return
    first = df.columns[0]
    time_like = any(k in first.lower() for k in ("date", "month", "time", "hour", "year", "day"))
    y = [c for c in numeric if c != first][:3]
    if not y:
        return
    data = df.set_index(first)[y]
    if time_like and len(df) > 3:
        st.line_chart(data)
    elif len(df) <= 40:
        st.bar_chart(data)


def show_result(r: AgentResult) -> None:
    if r.status == "abstained":
        st.warning(f"**Not answerable from this dataset.** {r.answer}")
    elif r.status == "failed":
        st.error(f"**The question could not be answered.** {r.error}")
    else:
        st.success(r.answer)

    if r.rows:
        df = pd.DataFrame(r.rows, columns=r.columns)
        pick_chart(df)
        st.dataframe(df, width="stretch", hide_index=True)
        if r.truncated:
            st.info(f"Showing the first {r.row_count} rows; the result was truncated.")
        elif r.limit_applied and r.row_count >= config.get_db_config().max_rows:
            st.info("A row limit was applied to this query.")

    if r.sql:
        with st.expander("Generated SQL (validated, executed read-only)", expanded=r.status != "answered"):
            st.code(r.sql, language="sql")
    if r.assumptions:
        st.caption(f"Assumptions: {r.assumptions}")

    cols = st.columns(4)
    cols[0].metric("Total time", f"{r.timings_ms.get('total', 0) / 1000:.1f} s")
    cols[1].metric(
        "LLM time", f"{(r.timings_ms.get('llm_generate', 0) + r.timings_ms.get('llm_explain', 0)) / 1000:.1f} s"
    )
    cols[2].metric("Query time", f"{r.timings_ms.get('execute', 0):.0f} ms")
    cols[3].metric("Tokens", f"{r.prompt_tokens + r.completion_tokens:,}")
    if len(r.attempts) > 1:
        with st.expander(f"{len(r.attempts)} attempts (self-repair)"):
            st.json(r.attempts)


# --- Layout --------------------------------------------------------------------------------

st.title("⚡ Ask the German electricity market")
st.write(
    "Natural-language questions over hourly SMARD data (market area DE-LU): day-ahead prices, grid load and "
    "generation by source. A Groq LLM writes SQL against the dbt marts. The SQL is checked by a validator and "
    "run by a **read-only** database role, and it is always shown below the answer."
)

with st.sidebar:
    st.header("Example questions")
    for q in EXAMPLES:
        if st.button(q, width="stretch"):
            st.session_state["question"] = q
    st.divider()
    st.header("Data coverage")
    try:
        cov = coverage()
        st.write(f"**{cov['first_local_date']} → {cov['last_local_date']}** (local dates)")
        st.write(f"{cov['hours']:,} hours · source: SMARD.de, Bundesnetzagentur (CC BY 4.0)")
    except Exception as exc:  # database not reachable / role not created
        st.error(f"Database unavailable: {exc}")
    st.divider()
    st.header("Limitations")
    st.caption(
        "No fuel/CO₂ prices, cross-border flows or forecasts. Renewable share is a share of net generation. "
        "Correlation is not causation. LLM-generated SQL can be wrong: check the SQL."
    )

question = st.text_input(
    "Your question",
    key="question",
    max_chars=config.MAX_QUESTION_CHARS,
    placeholder="e.g. Which month had the most negative-price hours?",
)
if st.button("Ask", type="primary") and question:
    try:
        agent = get_agent()
    except config.ConfigError as exc:
        st.error(f"Configuration error: {exc}")
        st.stop()
    with st.spinner("Generating SQL, validating and querying…"):
        st.session_state["result"] = agent.answer(question)

if "result" in st.session_state:
    show_result(st.session_state["result"])
