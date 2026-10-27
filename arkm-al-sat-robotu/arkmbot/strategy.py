"""Strateji ailesi, parametre izgarasi ve sinyal uretimi.

Iki giris modulu vardir; arastirma hangisinin (veya hicbirinin) kullanilacagini
gecmis veriye gore secer:

* trend  : Donchian kirilimi + EMA trend filtresi + ADX guc filtresi
           (Turtle/CTA tipi trend takipcileri ve Freqtrade trend stratejilerinin ortak iskeleti)
* mr     : Bollinger alt bandi + RSI asiri satim + dusuk ADX (yatay piyasada ortalamaya donus)

Spot hesapta aciga satis olmadigindan robot yalnizca uzun (long) pozisyon acar;
dusen piyasada nakitte beklemek de bir karardir. BTC filtresi, altcoinlerin
BTC yonune bagimliligini hesaba katar (BTC kapanisi kendi EMA200'unun ustunde mi).

Cikis kurallari (zarar kes / kar al) her iki modulde ortaktir:
ATR tabanli ilk stop, istege bagli kismi/tam kar al, kar al sonrasi basabas
stop ve ATR tabanli iz suren (chandelier) stop.
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, fields, replace

import numpy as np
import pandas as pd

from . import indicators as ind

ATR_LEN = 14
RSI_LEN = 14
ADX_LEN = 14
BB_LEN = 20
BTC_EMA = 200


@dataclass(frozen=True)
class Params:
    module: str = "trend"          # "trend" | "mr"
    timeframe: str = "1h"          # "1h" | "4h"
    btc_filter: bool = True
    # trend
    donchian: int = 20
    ema_fast: int = 50
    ema_slow: int = 200
    adx_min: float = 0.0
    # ortalamaya donus
    rsi_max: float = 30.0
    bb_std: float = 2.0
    adx_max: float = 25.0
    # cikis (ATR katsayilari)
    sl_atr: float = 2.0
    tp_atr: float = 3.0
    tp_fraction: float = 0.5       # 0 = sabit kar al yok, 1 = tamamini sat
    trail_atr: float = 3.0
    max_hold: int = 0              # bar; 0 = sure siniri yok

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Params":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in names})

    def key(self) -> tuple:
        return tuple(asdict(self).values())


# ---- parametre izgarasi -------------------------------------------------
# Her eksen bilerek kucuk tutulmustur: cok genis izgara asiri uyum (overfitting)
# riskini artirir. Secim, komsu parametrelerin de iyi oldugu "plato" uzerinden yapilir.
TREND_AXES = {
    "donchian": [20, 55],
    "ema_pair": [(20, 100), (50, 200)],
    "adx_min": [0.0, 20.0],
}
MR_AXES = {
    "rsi_max": [25.0, 30.0],
    "bb_std": [2.0, 2.5],
    "adx_max": [20.0, 30.0],
}
EXIT_AXES = {
    "sl_atr": [1.5, 2.0, 3.0],
    "tp": [(0.0, 0.0), (2.0, 0.5), (4.0, 0.5), (2.0, 1.0), (4.0, 1.0)],   # (tp_atr, tp_fraction)
    "trail_atr": [2.0, 3.0, 4.0],
}
COMMON_AXES = {"btc_filter": [True, False]}


def build_grid(timeframes: list[str]) -> list[Params]:
    grid: list[Params] = []
    exit_combos = list(itertools.product(EXIT_AXES["sl_atr"], EXIT_AXES["tp"], EXIT_AXES["trail_atr"]))
    for tf, btc in itertools.product(timeframes, COMMON_AXES["btc_filter"]):
        for don, (ef, es), adx_min in itertools.product(*TREND_AXES.values()):
            for sl, (tp, frac), tr in exit_combos:
                grid.append(Params("trend", tf, btc, donchian=don, ema_fast=ef, ema_slow=es,
                                   adx_min=adx_min, sl_atr=sl, tp_atr=tp, tp_fraction=frac, trail_atr=tr))
        for rsi_max, bb_std, adx_max in itertools.product(*MR_AXES.values()):
            for sl, (tp, frac), tr in exit_combos:
                grid.append(Params("mr", tf, btc, rsi_max=rsi_max, bb_std=bb_std, adx_max=adx_max,
                                   sl_atr=sl, tp_atr=tp, tp_fraction=frac, trail_atr=tr))
    return grid


def _axis_values(p: Params) -> dict:
    """Komsuluk hesabi icin her parametrenin izgaradaki sira numarasi."""
    v = {"sl_atr": EXIT_AXES["sl_atr"].index(p.sl_atr),
         "tp": EXIT_AXES["tp"].index((p.tp_atr, p.tp_fraction)),
         "trail_atr": EXIT_AXES["trail_atr"].index(p.trail_atr)}
    if p.module == "trend":
        v.update(donchian=TREND_AXES["donchian"].index(p.donchian),
                 ema_pair=TREND_AXES["ema_pair"].index((p.ema_fast, p.ema_slow)),
                 adx_min=TREND_AXES["adx_min"].index(p.adx_min))
    else:
        v.update(rsi_max=MR_AXES["rsi_max"].index(p.rsi_max),
                 bb_std=MR_AXES["bb_std"].index(p.bb_std),
                 adx_max=MR_AXES["adx_max"].index(p.adx_max))
    return v


def neighbors(grid: list[Params]) -> list[list[int]]:
    """Ayni modul/zaman dilimi/BTC filtresinde tek bir eksende bir adim farkli olanlar."""
    groups: dict[tuple, list[int]] = {}
    coords = []
    for i, p in enumerate(grid):
        c = _axis_values(p)
        coords.append(c)
        groups.setdefault((p.module, p.timeframe, p.btc_filter), []).append(i)
    # "tp" ekseni sirasiz kategoridir; yine de tek adim komsuluk makul bir yaklasimdir.
    out: list[list[int]] = [[] for _ in grid]
    for idxs in groups.values():
        lookup = {tuple(sorted(coords[i].items())): i for i in idxs}
        for i in idxs:
            ci = coords[i]
            for k in ci:
                for d in (-1, 1):
                    cj = dict(ci)
                    cj[k] = ci[k] + d
                    j = lookup.get(tuple(sorted(cj.items())))
                    if j is not None:
                        out[i].append(j)
    return out


# ---- gosterge kutuphanesi -------------------------------------------------
class FeatureLibrary:
    """Bir zaman dilimi icin gostergeleri bir kez hesaplar ve onbellekte tutar."""

    def __init__(self, bars: pd.DataFrame, btc_bars: pd.DataFrame | None):
        self.bars = bars
        self.close = bars["close"]
        self.high = bars["high"]
        self.low = bars["low"]
        self._cache: dict[tuple, pd.Series] = {}
        if btc_bars is not None and len(btc_bars):
            btc_close = btc_bars["close"].reindex(bars.index).ffill()
            btc_ema = ind.ema(btc_bars["close"], BTC_EMA).reindex(bars.index).ffill()
            self.btc_ok = (btc_close > btc_ema).fillna(False)
        else:
            self.btc_ok = pd.Series(True, index=bars.index)

    def get(self, name: str, *args) -> pd.Series:
        key = (name, *args)
        if key not in self._cache:
            c, h, l = self.close, self.high, self.low
            if name == "ema":
                s = ind.ema(c, args[0])
            elif name == "don":
                s = ind.donchian_high(h, args[0])
            elif name == "atr":
                s = ind.atr(h, l, c, ATR_LEN)
            elif name == "adx":
                s = ind.adx(h, l, c, ADX_LEN)
            elif name == "rsi":
                s = ind.rsi(c, RSI_LEN)
            elif name == "bb_lower":
                s = ind.bollinger(c, BB_LEN, args[0])[0]
            elif name == "bb_mid":
                s = ind.bollinger(c, BB_LEN)[1]
            else:
                raise KeyError(name)
            self._cache[key] = s
        return self._cache[key]

    def bb_lower(self, k: float) -> pd.Series:
        return self.get("bb_lower", k)

    def bb_mid(self) -> pd.Series:
        return self.get("bb_mid")


def signals(lib: FeatureLibrary, p: Params) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(giris, cikis, atr) dizilerini dondurur. Sinyal mum kapanisinda olusur."""
    c = lib.close
    atr = lib.get("atr")
    if p.module == "trend":
        ef, es = lib.get("ema", p.ema_fast), lib.get("ema", p.ema_slow)
        don = lib.get("don", p.donchian)
        entry = (c > don) & (ef > es) & (c > es)
        if p.adx_min > 0:
            entry &= lib.get("adx") >= p.adx_min
        exit_ = ef < es
    elif p.module == "mr":
        entry = (c < lib.bb_lower(p.bb_std)) & (lib.get("rsi") < p.rsi_max) & (lib.get("adx") < p.adx_max)
        exit_ = c >= lib.bb_mid()
    else:
        raise ValueError(p.module)
    if p.btc_filter:
        entry &= lib.btc_ok
    entry &= atr.notna() & (atr > 0)
    return (entry.fillna(False).to_numpy(bool), exit_.fillna(False).to_numpy(bool),
            atr.to_numpy(float))


def with_overrides(p: Params, **kw) -> Params:
    return replace(p, **kw)
