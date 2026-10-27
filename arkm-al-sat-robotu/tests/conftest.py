import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HOUR_MS = 3_600_000


def synthetic_1h(n: int, seed: int, start: str = "2023-07-18", price: float = 0.5,
                 vol: float = 0.012) -> pd.DataFrame:
    """Yalnizca kod dogrulamasi icin rejim degistiren yapay fiyat serisi (gercek ARKM verisi DEGILDIR)."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.normal(0, 0.0015, n // 300 + 1), 300)[:n]
    rets = regime + rng.normal(0, vol, n)
    close = price * np.exp(np.cumsum(rets))
    open_ = np.r_[price, close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, vol / 2, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, vol / 2, n)))
    t0 = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    vol_ = rng.uniform(1e5, 1e6, n)
    return pd.DataFrame({
        "open_time": t0 + np.arange(n, dtype=np.int64) * HOUR_MS,
        "open": open_, "high": high, "low": low, "close": close, "volume": vol_,
        "quote_volume": vol_ * close, "trades": rng.integers(100, 1000, n).astype(float),
        "taker_buy_base": vol_ / 2,
    })


@pytest.fixture
def synth():
    return synthetic_1h
