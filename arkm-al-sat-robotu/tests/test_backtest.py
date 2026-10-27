"""Backtest motorunun elle hesaplanmis senaryolarla dogrulanmasi."""
import numpy as np
import pandas as pd
import pytest

from arkmbot.backtest import BacktestConfig, max_drawdown, run_backtest, sqn
from arkmbot.strategy import Params

FEE = 0.001


def bars(rows):
    idx = pd.date_range("2024-01-01", periods=len(rows), freq="1h", tz="UTC")
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"], index=idx)


def cfg(**kw):
    base = dict(initial_capital=1000.0, fee=FEE, slippage=0.0, risk_per_trade=0.01,
                max_alloc=0.95, cooldown_bars=0, min_notional=5.0)
    base.update(kw)
    return BacktestConfig(**base)


def run(rows, p, entry_at=(0,), exit_at=(), **kw):
    b = bars(rows)
    n = len(b)
    entry = np.zeros(n, bool)
    entry[list(entry_at)] = True
    ex = np.zeros(n, bool)
    if exit_at:
        ex[list(exit_at)] = True
    atr = np.full(n, 1.0)
    return run_backtest(b, entry, ex, atr, p, cfg(**kw))


NO_TRAIL = dict(trail_atr=1000.0, max_hold=0)


def test_stop_loss_exact_pnl():
    # Sinyal 0. mum kapanisi, alis 1. mum acilisi 100. Stop = 100 - 2x1 = 98.
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 101, 99, 100],
               [100, 100, 97, 97],
               [97, 97, 97, 97]], p)
    assert len(res.trades) == 1
    t = res.trades[0]
    # miktar = (1000 x 0,01) / (100 - 98) = 5; tavan 1000x0,95/(100x1,001)=9,49 -> 5
    assert t.qty == pytest.approx(5.0)
    cost = 5 * 100 * 1.001                 # 500,50
    proceeds = 5 * 98 * 0.999              # 489,51
    assert t.pnl == pytest.approx(proceeds - cost)          # -10,99
    assert t.pnl == pytest.approx(-10.99)
    assert t.r_multiple == pytest.approx(-10.99 / 10.0)     # 1R = 5 x 2 = 10
    assert t.entry_idx == 1 and t.exit_idx == 2 and t.reason == "stop"
    assert res.final_equity == pytest.approx(1000 - 10.99)


def test_partial_take_profit_then_breakeven_stop():
    # TP = 100 + 2 = 102, yarisi satilir; kalan icin stop basabas fiyatina cekilir.
    p = Params(sl_atr=2.0, tp_atr=2.0, tp_fraction=0.5, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 102.5, 99.5, 101],
               [101, 101, 100, 100],
               [100, 100, 100, 100]], p)
    t = res.trades[0]
    be = 100 * 1.001 / 0.999
    first = 2.5 * 102 * 0.999                # 254,745
    second = 2.5 * be * 0.999                # 250,25 (alis maliyetinin yarisi)
    assert second == pytest.approx(2.5 * 100 * 1.001)
    assert t.pnl == pytest.approx(first + second - 500.5)   # 4,495
    assert t.pnl == pytest.approx(4.495)
    assert t.reason == "stop"
    assert t.exit_price == pytest.approx((2.5 * 102 + 2.5 * be) / 5)


def test_full_take_profit():
    p = Params(sl_atr=2.0, tp_atr=3.0, tp_fraction=1.0, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 103.5, 99.5, 103],
               [103, 103, 103, 103]], p)
    t = res.trades[0]
    assert t.reason == "kar_al"
    assert t.pnl == pytest.approx(5 * 103 * 0.999 - 500.5)   # 514,485 - 500,5 = 13,985
    assert t.r_multiple == pytest.approx(13.985 / 10)


def test_gap_below_stop_fills_at_open():
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 100.5, 99, 99.5],
               [95, 96, 94, 95]], p)
    t = res.trades[0]
    assert t.exit_price == pytest.approx(95.0)
    assert t.pnl == pytest.approx(5 * 95 * 0.999 - 500.5)


def test_stop_has_priority_when_stop_and_tp_in_same_bar():
    p = Params(sl_atr=2.0, tp_atr=2.0, tp_fraction=1.0, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 103, 97, 100]], p)
    assert res.trades[0].reason == "stop"


def test_signal_exit_executes_next_open():
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    res = run([[100, 100, 100, 100],
               [100, 101, 99.5, 101],
               [101.5, 102, 101, 101.8],
               [101.8, 102, 101, 101]], p, exit_at=(2,))
    t = res.trades[0]
    assert t.reason == "sinyal" and t.exit_idx == 3
    assert t.exit_price == pytest.approx(101.8)


def test_trailing_stop_ratchets_up():
    # iz suren stop = en yuksek - 1,5 x ATR(1) ; 2. mum yuksegi 105 -> stop 103,5
    p = Params(sl_atr=2.0, tp_fraction=0.0, trail_atr=1.5, max_hold=0)
    res = run([[100, 100, 100, 100],
               [100, 101, 99.5, 100.5],
               [100.5, 105, 100.5, 104.5],
               [104.5, 104.6, 103, 103.2],
               [103, 103, 103, 103]], p)
    t = res.trades[0]
    assert t.reason == "stop"
    assert t.exit_price == pytest.approx(103.5)
    assert t.exit_idx == 3


def test_allocation_cap_limits_quantity():
    # Stop mesafesi cok dar: risk boyutu 10/0,1 = 100 adet olurdu; tavan 950/(100x1,001)=9,4905...
    b = bars([[100, 100, 100, 100], [100, 100.05, 99.95, 100], [100, 100, 100, 100]])
    entry = np.array([True, False, False])
    res = run_backtest(b, entry, np.zeros(3, bool), np.full(3, 0.05), Params(sl_atr=2.0, tp_fraction=0, **NO_TRAIL), cfg())
    assert res.trades[0].qty == pytest.approx(950 / (100 * 1.001))


def test_no_entry_on_last_bar_and_equity_complete():
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    b = bars([[100, 100, 100, 100]] * 5)
    entry = np.array([False, False, False, False, True])
    res = run_backtest(b, entry, np.zeros(5, bool), np.ones(5), p, cfg())
    assert res.trades == []
    assert not np.isnan(res.equity).any()
    assert res.final_equity == 1000.0


def test_cooldown_after_loss():
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    rows = [[100, 100, 100, 100], [100, 100, 97, 97]] + [[97, 97, 97, 97]] * 6
    b = bars(rows)
    entry = np.zeros(len(rows), bool)
    entry[[0, 2, 3, 4]] = True
    res = run_backtest(b, entry, np.zeros(len(rows), bool), np.ones(len(rows)), p, cfg(cooldown_bars=2))
    # zarar 1. mumda -> 2 ve 3. mum sinyalleri yok sayilir, 4. mum sinyali 5. mumda alis
    assert len(res.trades) == 2
    assert res.trades[1].entry_idx == 5


def test_stop_when_flat_after_and_entry_window():
    p = Params(sl_atr=2.0, tp_fraction=0.0, **NO_TRAIL)
    rows = [[100, 100, 100, 100]] * 10
    b = bars(rows)
    entry = np.ones(10, bool)
    allowed = np.zeros(10, bool)
    allowed[3] = True
    res = run_backtest(b, entry, np.zeros(10, bool), np.ones(10), p, cfg(), start_idx=2,
                       entry_allowed=allowed, stop_when_flat_after=4)
    assert len(res.trades) == 1 and res.trades[0].entry_idx == 4
    assert res.trades[0].reason == "veri_sonu"   # pozisyon veri sonuna kadar acik kaldi
    assert np.isnan(res.equity[:2]).all()


def test_metrics():
    assert max_drawdown(np.array([100, 120, 90, 130, 65.0])) == pytest.approx(-0.5)
    r = np.array([1.0, -1.0, 2.0, -0.5])
    assert sqn(r) == pytest.approx(r.mean() / r.std(ddof=1) * 2)
