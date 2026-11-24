"""Reference implementation of every risk number in the workbook.

The workbook computes these numbers with live Excel formulas. This module is the
independent check: tests pin its maths, and `verify.py` recalculates the workbook in
LibreOffice and compares the two. The definitions must stay identical to the formulas
in `build_workbook.py`.

Conventions
-----------
* Risk factor: the daily change of the base price in EUR/MWh (P_t - P_t-1). Log or percentage
  returns are undefined here because German prices go to zero and below.
* Position: a buyer that must purchase `volume` MWh per day at spot, so a rise in price is a loss.
  P&L per MWh is -change.
* VaR is reported as a positive loss: VaR_a = -quantile(P&L, 1 - a). Quantiles use linear
  interpolation, which equals Excel's PERCENTILE.INC.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np
import pandas as pd


def price_changes(base_price: pd.Series) -> pd.Series:
    """Daily change in EUR/MWh; the first day has none."""
    return base_price.diff()


def buyer_pnl(changes: pd.Series) -> pd.Series:
    """P&L per MWh for a spot buyer: a price rise costs money."""
    return -changes


def rolling_vol(changes: pd.Series, window: int = 30) -> pd.Series:
    """Sample standard deviation (Excel STDEV.S) of the last `window` changes, today included."""
    return changes.rolling(window, min_periods=window).std(ddof=1)


def historical_var(pnl: pd.Series, confidence: float) -> float:
    """Historical-simulation VaR as a positive loss."""
    return -float(np.percentile(pnl.dropna(), (1 - confidence) * 100, method="linear"))


def parametric_var(pnl: pd.Series, confidence: float) -> float:
    """Variance-covariance (normal) VaR as a positive loss, mean included."""
    x = pnl.dropna()
    return -(float(x.mean()) + NormalDist().inv_cdf(1 - confidence) * float(x.std(ddof=1)))


def rolling_var(pnl: pd.Series, window: int, confidence: float, method: str) -> pd.Series:
    """Out-of-sample VaR for day t, estimated only from the `window` P&L values before t."""
    fn = historical_var if method == "historical" else parametric_var
    out = pd.Series(np.nan, index=pnl.index)
    values = pnl.to_numpy()
    for i in range(len(values)):
        past = values[max(0, i - window) : i]
        if len(past) == window and not np.isnan(past).any():
            out.iloc[i] = fn(pd.Series(past), confidence)
    return out


@dataclass(frozen=True)
class Backtest:
    observations: int
    breaches: int
    expected: float
    breach_rate: float
    kupiec_lr: float
    kupiec_p_value: float


def backtest(pnl: pd.Series, var: pd.Series, confidence: float) -> Backtest:
    """Count days whose loss exceeded the VaR set the day before, plus Kupiec's POF test."""
    mask = var.notna() & pnl.notna()
    t = int(mask.sum())
    x = int((pnl[mask] < -var[mask]).sum())
    lr = kupiec_lr(x, t, 1 - confidence)
    return Backtest(t, x, t * (1 - confidence), x / t, lr, chi2_sf_1df(lr))


def chi2_sf_1df(x: float) -> float:
    """Upper tail of the chi-squared distribution with 1 df (Excel CHISQ.DIST.RT(x, 1))."""
    return math.erfc(math.sqrt(max(x, 0.0) / 2))


def kupiec_lr(breaches: int, observations: int, p: float) -> float:
    """Likelihood ratio of Kupiec's proportion-of-failures test (chi-squared, 1 df)."""
    x, t = breaches, observations
    phat = x / t
    log_null = (t - x) * math.log(1 - p) + x * math.log(p)
    log_alt = (t - x) * math.log(1 - phat) if x < t else 0.0
    log_alt += x * math.log(phat) if x > 0 else 0.0
    return -2 * (log_null - log_alt)


@dataclass(frozen=True)
class BuyerScenario:
    """A hypothetical supplier: buys power, resells at a fixed tariff, partly hedged forward."""

    forecast_mwh: float
    actual_mwh: float
    tariff: float  # fixed price charged to customers, EUR/MWh
    hedge_ratio: float  # share of the forecast bought forward
    forward_price: float  # EUR/MWh
    spot_base: float  # EUR/MWh before the shock
    price_shock: float  # relative shock applied to spot, e.g. 0.5 = +50 %

    @property
    def spot(self) -> float:
        return self.spot_base * (1 + self.price_shock)

    @property
    def hedged_mwh(self) -> float:
        return self.forecast_mwh * self.hedge_ratio

    @property
    def cost(self) -> float:
        # Volume above the hedge is bought at spot; a shortfall below it is sold back at spot.
        return self.hedged_mwh * self.forward_price + (self.actual_mwh - self.hedged_mwh) * self.spot

    @property
    def revenue(self) -> float:
        return self.actual_mwh * self.tariff

    @property
    def margin(self) -> float:
        return self.revenue - self.cost
