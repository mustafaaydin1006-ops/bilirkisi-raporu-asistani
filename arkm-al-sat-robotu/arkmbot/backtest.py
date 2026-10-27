"""Mum mum ilerleyen (olay tabanli) backtest motoru ve performans olcutleri.

Varsayimlar (hepsi temkinli yondedir):
* Alim/satim emirleri sinyalden sonraki mumun acilisinda, kayma payi eklenerek dolar.
* Ayni mumda hem stop hem kar al seviyesine dokunulduysa once stop gerceklesti kabul edilir.
* Mum stopun altinda acilirsa (bosluk), dolum stop fiyatindan degil acilis fiyatindan olur.
* Her alim ve satimda komisyon (ucret_orani) dusulur.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .strategy import Params
from .trade_manager import PositionState, open_position, tp_sell_qty, update_on_close

BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365}


@dataclass
class BacktestConfig:
    initial_capital: float = 1000.0
    fee: float = 0.001
    slippage: float = 0.0005
    risk_per_trade: float = 0.01
    max_alloc: float = 0.95
    cooldown_bars: int = 3
    min_notional: float = 5.0
    max_drawdown_stop: float | None = None   # zirveden bu oranda dususte yeni islem acilmaz


@dataclass
class Trade:
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    entry_price: float
    exit_price: float      # agirlikli ortalama satis fiyati
    qty: float
    pnl: float
    ret: float             # pnl / maliyet
    r_multiple: float
    reason: str
    bars: int
    entry_idx: int
    exit_idx: int


@dataclass
class BacktestResult:
    trades: list[Trade]
    equity: np.ndarray
    index: pd.DatetimeIndex
    final_equity: float
    last_idx: int
    in_position: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))


def run_backtest(bars: pd.DataFrame, entry: np.ndarray, exit_sig: np.ndarray, atr: np.ndarray,
                 p: Params, cfg: BacktestConfig, start_idx: int = 0,
                 entry_allowed: np.ndarray | None = None,
                 stop_when_flat_after: int | None = None) -> BacktestResult:
    """bars uzerinde simulasyon.

    entry_allowed: True olan mumlarda yeni sinyal kabul edilir (walk-forward test penceresi,
    kilit acilim yasagi vb.). stop_when_flat_after: bu indeksten sonra pozisyon kapaninca durur.
    """
    o = bars["open"].to_numpy(float)
    h = bars["high"].to_numpy(float)
    l = bars["low"].to_numpy(float)
    c = bars["close"].to_numpy(float)
    idx = bars.index
    n = len(bars)
    fee, slip = cfg.fee, cfg.slippage

    allowed = entry & (entry_allowed if entry_allowed is not None else True)
    signal_idx = np.flatnonzero(allowed)

    equity = np.full(n, np.nan)
    in_pos = np.zeros(n, bool)
    cash = cfg.initial_capital
    peak = cash
    pos: PositionState | None = None
    pos_entry_idx = -1
    pending_entry = False
    pending_exit = False
    cooldown_until = -1
    halted = False
    trades: list[Trade] = []

    def close_trade(i: int, price: float, reason: str) -> None:
        nonlocal cash, pos
        proceeds = pos.qty * price * (1 - fee)
        cash += proceeds
        pos.proceeds += proceeds
        pos.fees += pos.qty * price * fee
        pnl = pos.proceeds - pos.cost
        sold_value = pos.proceeds / (1 - fee)
        avg_exit = sold_value / pos.initial_qty
        risk = pos.initial_risk
        trades.append(Trade(pd.Timestamp(pos.entry_time), idx[i], pos.entry_price, avg_exit,
                            pos.initial_qty, pnl, pnl / pos.cost, pnl / risk if risk > 0 else 0.0,
                            reason, pos.bars_held, pos_entry_idx, i))
        pos = None

    def partial_sell(price: float, qty: float) -> None:
        nonlocal cash
        proceeds = qty * price * (1 - fee)
        cash += proceeds
        pos.proceeds += proceeds
        pos.fees += qty * price * fee
        pos.qty -= qty
        pos.tp_done = True

    i = start_idx
    last_i = start_idx
    while i < n:
        # Pozisyon ve bekleyen emir yoksa bir sonraki sinyale atla (hiz icin)
        if pos is None and not pending_entry and not pending_exit:
            if stop_when_flat_after is not None and i > stop_when_flat_after:
                break
            k = np.searchsorted(signal_idx, max(i, cooldown_until + 1))
            limit = n if stop_when_flat_after is None else min(n, stop_when_flat_after + 1)
            nxt = signal_idx[k] if k < len(signal_idx) else n
            if halted or nxt >= limit:
                stop_at = limit if stop_when_flat_after is not None else n
                equity[i:stop_at] = cash
                last_i = stop_at - 1
                i = stop_at
                break
            equity[i:nxt] = cash
            i = nxt
            # nxt mumunun kapanisinda sinyal var -> bir sonraki mumda alim
            equity[i] = cash
            if i + 1 < n:
                pending_entry = True
            last_i = i
            i += 1
            continue

        # 1) Bekleyen emirler acilista
        if pending_exit:
            pending_exit = False
            if pos is not None:
                close_trade(i, o[i] * (1 - slip), "sinyal")
                if trades[-1].pnl < 0:
                    cooldown_until = i + cfg.cooldown_bars
        if pending_entry and pos is None:
            pending_entry = False
            a = atr[i - 1]
            fill = o[i] * (1 + slip)
            stop = fill - p.sl_atr * a
            if a > 0 and stop > 0:
                eq = cash
                qty = (eq * cfg.risk_per_trade) / (fill - stop)
                qty = min(qty, eq * cfg.max_alloc / (fill * (1 + fee)))
                if qty * fill >= cfg.min_notional:
                    cost = qty * fill * (1 + fee)
                    cash -= cost
                    pos = open_position(fill, qty, cost, qty * fill * fee, a, p, str(idx[i]))
                    pos_entry_idx = i

        # 2) Mum ici stop / kar al (temkinli sira)
        if pos is not None:
            if o[i] <= pos.stop:
                close_trade(i, o[i] * (1 - slip), "stop")
                if trades[-1].pnl < 0:
                    cooldown_until = i + cfg.cooldown_bars
            else:
                if pos.tp is not None and not pos.tp_done and o[i] >= pos.tp:
                    q = tp_sell_qty(pos, p)
                    if q >= pos.qty - 1e-12:
                        close_trade(i, o[i] * (1 - slip), "kar_al")
                    else:
                        partial_sell(o[i] * (1 - slip), q)
                if pos is not None and l[i] <= pos.stop:
                    close_trade(i, pos.stop * (1 - slip), "stop")
                    if trades[-1].pnl < 0:
                        cooldown_until = i + cfg.cooldown_bars
                elif pos is not None and pos.tp is not None and not pos.tp_done and h[i] >= pos.tp:
                    q = tp_sell_qty(pos, p)
                    if q >= pos.qty - 1e-12:
                        close_trade(i, pos.tp * (1 - slip), "kar_al")
                    else:
                        partial_sell(pos.tp * (1 - slip), q)

        # 3) Mum kapanisi
        if pos is not None:
            in_pos[i] = True
            if update_on_close(pos, h[i], atr[i], bool(exit_sig[i]), p, fee):
                if i + 1 < n:
                    pending_exit = True
        eq_now = cash + (pos.qty * c[i] if pos is not None else 0.0)
        equity[i] = eq_now
        peak = max(peak, eq_now)
        if cfg.max_drawdown_stop is not None and eq_now <= peak * (1 - cfg.max_drawdown_stop):
            halted = True

        if (pos is None and not pending_entry and not halted and allowed[i] and i > cooldown_until
                and i + 1 < n and not (stop_when_flat_after is not None and i > stop_when_flat_after)):
            pending_entry = True
        last_i = i
        i += 1
        if pos is None and not pending_entry and stop_when_flat_after is not None and i > stop_when_flat_after:
            break

    # Veri bittiginde acik pozisyon son kapanistan degerlenir (satilmis sayilir)
    if pos is not None:
        close_trade(last_i, c[last_i] * (1 - slip), "veri_sonu")
        equity[last_i] = cash
    final = cash
    return BacktestResult(trades, equity, idx, final, last_i, in_pos)


# ---- olcutler -------------------------------------------------------------
def max_drawdown(eq: np.ndarray) -> float:
    eq = eq[~np.isnan(eq)]
    if len(eq) == 0:
        return 0.0
    peak = np.maximum.accumulate(eq)
    return float((eq / peak - 1).min())


def sqn(r: np.ndarray) -> float:
    """Van Tharp System Quality Number: ort(R)/std(R) x karekok(min(n,100))."""
    n = len(r)
    if n < 2:
        return 0.0
    sd = r.std(ddof=1)
    if sd == 0:
        return 0.0
    return float(r.mean() / sd * math.sqrt(min(n, 100)))


def trade_stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"islem": 0, "kazanma_orani": 0.0, "kar_faktoru": 0.0, "ort_R": 0.0,
                "toplam_R": 0.0, "sqn": 0.0, "ort_getiri": 0.0, "ort_bar": 0.0}
    pnl = np.array([t.pnl for t in trades])
    r = np.array([t.r_multiple for t in trades])
    gains, losses = pnl[pnl > 0].sum(), -pnl[pnl < 0].sum()
    return {
        "islem": len(trades),
        "kazanma_orani": float((pnl > 0).mean()),
        "kar_faktoru": float(gains / losses) if losses > 0 else float("inf"),
        "ort_R": float(r.mean()),
        "toplam_R": float(r.sum()),
        "sqn": sqn(r),
        "ort_getiri": float(np.mean([t.ret for t in trades])),
        "ort_bar": float(np.mean([t.bars for t in trades])),
    }


def equity_stats(eq: np.ndarray, index: pd.DatetimeIndex, timeframe: str) -> dict:
    mask = ~np.isnan(eq)
    e = eq[mask]
    if len(e) < 2:
        return {"toplam_getiri": 0.0, "yillik_getiri": 0.0, "maks_dusus": 0.0, "sharpe": 0.0}
    rets = np.diff(e) / e[:-1]
    ix = index[mask]
    years = (ix[-1] - ix[0]).total_seconds() / (365 * 24 * 3600)
    total = e[-1] / e[0] - 1
    cagr = (e[-1] / e[0]) ** (1 / years) - 1 if years > 0 and e[-1] > 0 else 0.0
    sd = rets.std(ddof=1)
    sharpe = rets.mean() / sd * math.sqrt(BARS_PER_YEAR[timeframe]) if sd > 0 else 0.0
    return {"toplam_getiri": float(total), "yillik_getiri": float(cagr),
            "maks_dusus": max_drawdown(e), "sharpe": float(sharpe)}
