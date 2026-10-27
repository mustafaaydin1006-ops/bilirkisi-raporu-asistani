"""Acik pozisyonun zarar kes / kar al / iz suren stop mantigi.

Backtest motoru ve canli robot ayni fonksiyonlari kullanir; boylece gecmiste
test edilen kural ile borsada uygulanan kural ayni kalir.

Zamanlama kurali (ileriye bakmayi onler):
* Sinyal t mumunun kapanisinda olusur, alim t+1 mumunun acilisinda yapilir.
* Ilk stop = dolum fiyati - sl_atr x ATR(t).
* Stop seviyesi her mum kapanisinda guncellenir ve bir sonraki mumdan itibaren gecerlidir.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from .strategy import Params


@dataclass
class PositionState:
    entry_time: str
    entry_price: float
    qty: float
    initial_qty: float
    stop: float
    initial_stop: float
    tp: float | None
    tp_done: bool
    highest: float
    bars_held: int
    cost: float          # alis icin odenen toplam quote (komisyon dahil)
    proceeds: float      # kismi satislardan alinan net quote
    fees: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PositionState":
        return cls(**d)

    @property
    def initial_risk(self) -> float:
        """1R: ilk stopta tum pozisyon kapansaydi olusacak zarar (komisyon haric)."""
        return self.initial_qty * (self.entry_price - self.initial_stop)


def initial_stop_price(fill_price: float, atr_signal: float, p: Params) -> float:
    return fill_price - p.sl_atr * atr_signal


def open_position(fill_price: float, qty: float, cost: float, fee: float, atr_signal: float,
                  p: Params, entry_time: str) -> PositionState:
    stop = initial_stop_price(fill_price, atr_signal, p)
    tp = fill_price + p.tp_atr * atr_signal if p.tp_fraction > 0 else None
    return PositionState(entry_time=entry_time, entry_price=fill_price, qty=qty, initial_qty=qty,
                         stop=stop, initial_stop=stop, tp=tp, tp_done=False, highest=fill_price,
                         bars_held=0, cost=cost, proceeds=0.0, fees=fee)


def breakeven_price(pos: PositionState, fee_rate: float) -> float:
    """Kalan miktar bu fiyattan satilirsa alis ve satis komisyonu karsilanir."""
    return pos.entry_price * (1 + fee_rate) / (1 - fee_rate)


def tp_sell_qty(pos: PositionState, p: Params) -> float:
    """Kar al seviyesinde satilacak miktar (kismi ya da tamami)."""
    if p.tp_fraction >= 1.0:
        return pos.qty
    return min(pos.qty, pos.initial_qty * p.tp_fraction)


def update_on_close(pos: PositionState, high: float, atr_now: float, exit_signal: bool,
                    p: Params, fee_rate: float) -> bool:
    """Mum kapanisinda stopu gunceller. Cikis istenirse True dondurur."""
    pos.bars_held += 1
    if high > pos.highest:
        pos.highest = high
    if atr_now == atr_now and atr_now > 0:   # NaN kontrolu
        trail = pos.highest - p.trail_atr * atr_now
        if trail > pos.stop:
            pos.stop = trail
    if pos.tp_done:
        be = breakeven_price(pos, fee_rate)
        if be > pos.stop:
            pos.stop = be
    if exit_signal:
        return True
    return p.max_hold > 0 and pos.bars_held >= p.max_hold
