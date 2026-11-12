"""Smoke test of the Streamlit page with Streamlit's AppTest harness (no browser, no LLM)."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[3] / "app" / "streamlit_app.py")


def test_page_renders_and_reports_missing_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert "Ask the German electricity market" in at.title[0].value
    assert len(at.sidebar.button) >= 7  # example questions

    at.sidebar.button[0].click().run()  # fills the question box
    assert at.text_input[0].value == "What was the average electricity price in 2024?"
    ask = next(b for b in at.button if b.label == "Ask")
    ask.click().run()
    assert any("GROQ_API_KEY" in e.value for e in at.error)


def test_chart_columns_skip_counts_and_mismatched_scales() -> None:
    import sys

    import pandas as pd

    sys.path.insert(0, str(Path(APP).parent))
    from streamlit_app import chart_columns

    df = pd.DataFrame(
        [["Autumn", 6555, 250, 0.0381, 91.86], ["Winter", 6504, 128, 0.0197, 99.31]],
        columns=["season", "total_hours", "negative_price_hours", "negative_price_share", "avg_price_eur_mwh"],
    )
    # Regression (seen in the app): total_hours dominated the chart; the share is on another scale.
    assert chart_columns(df) == ["negative_price_hours", "avg_price_eur_mwh"]
    assert chart_columns(df[["season", "avg_price_eur_mwh"]]) == ["avg_price_eur_mwh"]
    assert chart_columns(df.head(1)) == []
