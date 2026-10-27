"""Mum (kline) verisinin indirilmesi, onbellege yazilmasi ve zaman dilimi donusumu.

Arastirma ve canli robot ayni 1 saatlik veri dosyasini kullanir; 4 saatlik
mumlar bu dosyadan uretilir. Boylece backtest ile canli karar ayni veriye dayanir.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from .binance_client import INTERVAL_MS, BinanceClient

log = logging.getLogger(__name__)

COLUMNS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
           "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "ignore"]
KEEP = ["open_time", "open", "high", "low", "close", "volume", "quote_volume", "trades", "taker_buy_base"]


def _to_frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)[KEEP]
    df["open_time"] = df["open_time"].astype("int64")
    for c in KEEP[1:]:
        df[c] = df[c].astype(float)
    return df


def download_klines(client: BinanceClient, symbol: str, interval: str, start_ms: int,
                    end_ms: int | None = None, pause: float = 0.2) -> pd.DataFrame:
    """startTime ile sayfalayarak tum mumlari indirir; kapanmamis son mumu atar."""
    step = INTERVAL_MS[interval]
    now_ms = client.server_time_ms()
    end_ms = min(end_ms or now_ms, now_ms)
    frames, cursor = [], start_ms
    while cursor < end_ms:
        rows = client.klines(symbol, interval, start_ms=cursor, end_ms=end_ms, limit=1000)
        if not rows:
            break
        frames.append(_to_frame(rows))
        last_open = int(rows[-1][0])
        cursor = last_open + step
        if len(rows) < 1000:
            break
        time.sleep(pause)
    if not frames:
        return pd.DataFrame(columns=KEEP)
    df = pd.concat(frames, ignore_index=True).drop_duplicates("open_time")
    # Yalnizca kapanmis mumlar (kapanis zamani = acilis + aralik - 1 ms)
    df = df[df["open_time"] + step - 1 < now_ms]
    return df.sort_values("open_time").reset_index(drop=True)


def cache_path(folder: Path, symbol: str, interval: str) -> Path:
    return folder / f"{symbol}_{interval}.csv"


def load_cache(folder: Path, symbol: str, interval: str = "1h") -> pd.DataFrame:
    p = cache_path(folder, symbol, interval)
    if not p.exists():
        raise FileNotFoundError(f"{p} bulunamadi. Once 'python -m arkmbot indir' calistirin.")
    df = pd.read_csv(p)
    df["open_time"] = df["open_time"].astype("int64")
    return df


def update_cache(client: BinanceClient, folder: Path, symbol: str, start_date: str,
                 interval: str = "1h") -> tuple[pd.DataFrame, int]:
    """Onbellegi gunceller. (tum veri, yeni eklenen mum sayisi) dondurur."""
    folder.mkdir(parents=True, exist_ok=True)
    p = cache_path(folder, symbol, interval)
    if p.exists():
        old = load_cache(folder, symbol, interval)
        start_ms = int(old["open_time"].iloc[-1]) + INTERVAL_MS[interval] if len(old) else None
    else:
        old = pd.DataFrame(columns=KEEP)
        start_ms = None
    if start_ms is None:
        start_ms = int(pd.Timestamp(start_date, tz="UTC").timestamp() * 1000)
    new = download_klines(client, symbol, interval, start_ms)
    if len(new) == 0:
        return old, 0
    df = pd.concat([old, new], ignore_index=True) if len(old) else new
    df = df.drop_duplicates("open_time").sort_values("open_time").reset_index(drop=True)
    df.to_csv(p, index=False)
    return df, len(new)


def to_indexed(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.index = pd.to_datetime(out["open_time"], unit="ms", utc=True)
    out.index.name = "time"
    return out


def resample(df_1h: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """1 saatlik mumlardan hedef zaman dilimini uretir (Binance gibi UTC 00:00 hizali).

    Bir 4 saatlik mum, suresi tamamen gecmisse tamamlanmis sayilir; eksik saat
    (borsa bakimi) olsa bile kapanmis kabul edilir. Henuz suresi dolmamis son grup atilir.
    """
    d = to_indexed(df_1h)
    if timeframe == "1h":
        return d.drop(columns=["open_time"])
    rule = {"4h": "4h"}[timeframe]
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
           "quote_volume": "sum", "trades": "sum", "taker_buy_base": "sum"}
    out = d.drop(columns=["open_time"]).resample(rule, label="left", closed="left", origin="epoch").agg(agg)
    out = out.dropna(subset=["open", "close"])
    last_1h_close = d.index[-1] + pd.Timedelta(hours=1)
    complete = out.index + pd.Timedelta(rule) <= last_1h_close
    return out[complete]


def market_profile(df_1h: pd.DataFrame) -> dict:
    """Tum gecmisten tanimlayici istatistikler (rapor icin)."""
    d = to_indexed(df_1h)
    daily = d["close"].resample("1D").last().dropna()
    r_d = np.log(daily).diff().dropna()
    r_h = np.log(d["close"]).diff().dropna()
    peak = d["close"].cummax()
    dd = d["close"] / peak - 1
    hour_ret = r_h.groupby(r_h.index.hour).mean() * 100
    dow_ret = r_d.groupby(r_d.index.dayofweek).mean() * 100
    day_hl = d[["high", "low", "close"]].resample("1D").agg({"high": "max", "low": "min", "close": "last"}).dropna()
    day_range = (day_hl["high"] - day_hl["low"]) / day_hl["close"]
    ath_idx = d["high"].idxmax()
    atl_idx = d["low"].idxmin()
    return {
        "baslangic": str(d.index[0]), "bitis": str(d.index[-1]),
        "mum_sayisi_1h": int(len(d)),
        "ilk_acilis": float(d["open"].iloc[0]), "son_kapanis": float(d["close"].iloc[-1]),
        "zirve": float(d["high"].max()), "zirve_zamani": str(ath_idx),
        "dip": float(d["low"].min()), "dip_zamani": str(atl_idx),
        "al_tut_getiri": float(d["close"].iloc[-1] / d["open"].iloc[0] - 1),
        "maks_dusus_kapanis": float(dd.min()),
        "yillik_oynaklik": float(r_d.std(ddof=1) * np.sqrt(365)),
        "gunluk_ort_getiri_yuzde": float(r_d.mean() * 100),
        "en_iyi_gun_yuzde": float((np.exp(r_d.max()) - 1) * 100),
        "en_kotu_gun_yuzde": float((np.exp(r_d.min()) - 1) * 100),
        "ortalama_gunluk_aralik_yuzde": float(day_range.mean() * 100),
        "saat_bazli_ort_getiri_yuzde": {int(k): float(v) for k, v in hour_ret.items()},
        "gun_bazli_ort_getiri_yuzde": {int(k): float(v) for k, v in dow_ret.items()},
    }
