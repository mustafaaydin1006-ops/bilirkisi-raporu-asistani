import math

import numpy as np
import pandas as pd
import pytest

from arkmbot import indicators as ind


def ref_ema(x, n):
    a = 2 / (n + 1)
    out, prev = [], None
    for v in x:
        prev = v if prev is None else a * v + (1 - a) * prev
        out.append(prev)
    return np.array(out)


def ref_rsi(x, n):
    """Wilder RSI, bagimsiz dongu uygulamasi."""
    ag = al = None
    out = [math.nan]
    gains, losses = [], []
    for i in range(1, len(x)):
        d = x[i] - x[i - 1]
        g, l = max(d, 0.0), max(-d, 0.0)
        ag = g if ag is None else ag + (g - ag) / n
        al = l if al is None else al + (l - al) / n
        gains.append(g)
        if i < n:
            out.append(math.nan)
        else:
            out.append(100.0 if al == 0 else 100 - 100 / (1 + ag / al))
    return np.array(out)


def test_ema_matches_reference():
    x = np.random.default_rng(1).normal(100, 5, 300)
    got = ind.ema(pd.Series(x), 20).to_numpy()
    exp = ref_ema(x, 20)
    assert np.all(np.isnan(got[:19]))
    np.testing.assert_allclose(got[19:], exp[19:], rtol=1e-12)


def test_rsi_matches_reference():
    x = np.cumsum(np.random.default_rng(2).normal(0, 1, 400)) + 100
    got = ind.rsi(pd.Series(x), 14).to_numpy()
    exp = ref_rsi(x, 14)
    np.testing.assert_allclose(got[14:], exp[14:], rtol=1e-10)
    assert np.all((got[14:] >= 0) & (got[14:] <= 100))


def test_rsi_all_gains_is_100():
    x = pd.Series(np.arange(1, 50, dtype=float))
    assert ind.rsi(x, 14).iloc[-1] == 100.0


def test_atr_constant_range():
    # Her mum 2 birim aralikli ve bosluksuz -> TR = 2, ATR = 2
    n = 50
    close = pd.Series(np.full(n, 10.0))
    high, low = close + 1, close - 1
    a = ind.atr(high, low, close, 14)
    assert a.iloc[:13].isna().all()
    np.testing.assert_allclose(a.iloc[13:], 2.0)


def test_true_range_uses_previous_close():
    high = pd.Series([10.0, 12.0])
    low = pd.Series([9.0, 11.5])
    close = pd.Series([9.5, 11.8])
    tr = ind.true_range(high, low, close)
    # ikinci mum: max(12-11.5, |12-9.5|, |11.5-9.5|) = 2.5
    assert tr.iloc[1] == pytest.approx(2.5)


def test_bollinger_population_std():
    x = pd.Series([1.0, 2, 3, 4, 5])
    lower, mid, upper = ind.bollinger(x, 5, 2.0)
    sd = np.std([1, 2, 3, 4, 5])          # ddof=0 -> sqrt(2)
    assert mid.iloc[-1] == pytest.approx(3.0)
    assert upper.iloc[-1] == pytest.approx(3 + 2 * sd)
    assert lower.iloc[-1] == pytest.approx(3 - 2 * sd)


def test_donchian_excludes_current_bar():
    h = pd.Series([1.0, 3, 2, 5, 4])
    d = ind.donchian_high(h, 3)
    assert math.isnan(d.iloc[2])
    assert d.iloc[3] == 3.0     # 1,3,2 -> 3 (5 dahil degil)
    assert d.iloc[4] == 5.0


def test_adx_bounds_and_trend():
    n = 300
    up = pd.Series(np.linspace(1, 100, n))
    a = ind.adx(up + 0.5, up - 0.5, up, 14).dropna()
    assert (a >= 0).all() and (a <= 100).all()
    assert a.iloc[-1] > 50     # tek yonlu guclu trendde ADX yuksek olmali
