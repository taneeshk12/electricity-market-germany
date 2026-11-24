"""Risk workbook reference maths: VaR, volatility, backtest and the buyer scenario."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from risk_workbook import metrics as m


def test_price_changes_and_buyer_pnl() -> None:
    prices = pd.Series([50.0, 60.0, -5.0, 0.0])
    changes = m.price_changes(prices)
    assert math.isnan(changes.iloc[0])
    assert changes.iloc[1:].tolist() == [10.0, -65.0, 5.0]
    # A buyer loses when the price rises.
    assert m.buyer_pnl(changes).iloc[1:].tolist() == [-10.0, 65.0, -5.0]


def test_rolling_vol_is_sample_std_of_trailing_window() -> None:
    changes = pd.Series([np.nan, 1.0, 3.0, 2.0, 8.0])
    vol = m.rolling_vol(changes, window=3)
    assert vol.iloc[:3].isna().all()
    assert vol.iloc[3] == pytest.approx(np.std([1.0, 3.0, 2.0], ddof=1))
    assert vol.iloc[4] == pytest.approx(np.std([3.0, 2.0, 8.0], ddof=1))


def test_historical_var_matches_percentile_inc() -> None:
    pnl = pd.Series(np.arange(1.0, 101.0))
    # Excel PERCENTILE.INC(1..100, 0.05) = 1 + 0.05 * 99 = 5.95
    assert m.historical_var(pnl, 0.95) == pytest.approx(-5.95)
    assert m.historical_var(-pnl, 0.99) == pytest.approx(100 - 0.01 * 99)


def test_parametric_var_uses_mean_and_sample_std() -> None:
    pnl = pd.Series([-3.0, -1.0, 0.0, 2.0, 7.0])
    z = -2.3263478740408408  # NORM.S.INV(0.01)
    assert m.parametric_var(pnl, 0.99) == pytest.approx(-(pnl.mean() + z * pnl.std(ddof=1)))


def test_rolling_var_has_no_lookahead() -> None:
    rng = np.random.default_rng(0)
    pnl = pd.Series(rng.normal(size=60))
    pnl.iloc[0] = np.nan
    base = m.rolling_var(pnl, window=20, confidence=0.95, method="historical")
    # The first day with a full window of 20 P&L values before it is index 21.
    assert base.iloc[:21].isna().all()
    assert base.iloc[21] == pytest.approx(m.historical_var(pnl.iloc[1:21], 0.95))

    shocked = pnl.copy()
    shocked.iloc[40] = 1_000.0  # changing today's P&L must not change today's VaR
    assert m.rolling_var(shocked, 20, 0.95, "historical").iloc[40] == pytest.approx(base.iloc[40])


def test_backtest_counts_losses_beyond_var() -> None:
    pnl = pd.Series([np.nan, -5.0, -1.0, -3.0, 2.0])
    var = pd.Series([np.nan, np.nan, 2.0, 2.0, 2.0])
    bt = m.backtest(pnl, var, confidence=0.9)
    assert (bt.observations, bt.breaches) == (3, 1)  # only -3 < -2; day 1 has no VaR
    assert bt.expected == pytest.approx(0.3)


def test_kupiec_is_zero_when_breach_rate_matches() -> None:
    assert m.kupiec_lr(10, 1000, 0.01) == pytest.approx(0.0, abs=1e-12)
    assert m.chi2_sf_1df(0.0) == pytest.approx(1.0)
    assert m.chi2_sf_1df(3.841458820694124) == pytest.approx(0.05)


def test_kupiec_handles_zero_breaches() -> None:
    # No breaches: LR = -2 T ln(1 - p).
    assert m.kupiec_lr(0, 250, 0.01) == pytest.approx(-2 * 250 * math.log(0.99))


def test_buyer_scenario_margin() -> None:
    sc = m.BuyerScenario(
        forecast_mwh=1000, actual_mwh=1200, tariff=110, hedge_ratio=0.6, forward_price=80, spot_base=90, price_shock=0.5
    )
    assert sc.spot == pytest.approx(135)
    # Revenue 1200*110 - hedge 600*80 - open 600*135
    assert sc.margin == pytest.approx(132_000 - 48_000 - 81_000)


def test_buyer_scenario_shortfall_sells_surplus_hedge_at_spot() -> None:
    sc = m.BuyerScenario(1000, 400, 110, 0.6, 80, 90, 1.0)
    # 200 MWh of hedge are not needed and are sold at the shocked spot of 180: a gain.
    assert sc.cost == pytest.approx(600 * 80 - 200 * 180)
