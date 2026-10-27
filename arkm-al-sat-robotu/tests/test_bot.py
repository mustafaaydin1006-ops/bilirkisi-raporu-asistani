"""Robot dongusunun paper broker ile senaryo testi (sahte fiyat kaynagi)."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from arkmbot import bot as bot_mod
from arkmbot.binance_client import SymbolRules
from arkmbot.bot import Bot
from arkmbot.broker import PaperBroker
from arkmbot.config import load_settings

from .test_binance_client import EXCHANGE_INFO

FEE = 0.001


class FakeMarket:
    def __init__(self, bid, ask):
        self.bid, self.ask = bid, ask

    def book_ticker(self, symbol):
        return self.bid, self.ask


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make_frame(n, close, start):
    t0 = int(start.timestamp() * 1000)
    c = np.full(n, close)
    return pd.DataFrame({"open_time": t0 + np.arange(n, dtype=np.int64) * 3_600_000, "open": c,
                         "high": c * 1.001, "low": c * 0.999, "close": c, "volume": 1.0,
                         "quote_volume": 1.0, "trades": 1.0, "taker_buy_base": 0.5})


@pytest.fixture
def env(tmp_path, monkeypatch):
    (tmp_path / "ayarlar.json").write_text('{"sermaye_limiti_usdt": 100, "ucret_orani": 0.001, '
                                           '"kayma_orani": 0.0, "zarar_sonrasi_bekleme_bar": 0}')
    s = load_settings(tmp_path / "ayarlar.json")
    rules = SymbolRules.from_exchange_info(EXCHANGE_INFO)
    market = FakeMarket(0.1199, 0.12)
    store = {}
    broker = PaperBroker(market, "ARKMUSDT", rules, FEE, 0.0, store, 100.0)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    clock = Clock(start + timedelta(hours=300, minutes=1))
    plan = {"olusturma": clock.t.isoformat(), "islem_acik": True, "risk_orani": 0.01,
            "params": {"module": "trend", "timeframe": "1h", "sl_atr": 2.0, "tp_atr": 2.0,
                       "tp_fraction": 0.5, "trail_atr": 50.0, "btc_filter": False}}
    b = Bot(s, data_client=None, broker=broker, mode="paper", research_fn=lambda _s: plan, clock=clock)
    b.state["paper"] = store
    b.plan = plan
    from arkmbot.strategy import Params
    b.params = Params.from_dict(plan["params"])

    sig = {"entry": False, "exit": False, "atr": 0.002}

    def fake_signals(lib, p):
        n = len(lib.bars)
        e = np.zeros(n, bool)
        x = np.zeros(n, bool)
        e[-1], x[-1] = sig["entry"], sig["exit"]
        return e, x, np.full(n, sig["atr"])

    monkeypatch.setattr(bot_mod, "signals", fake_signals)
    return b, market, clock, store, sig, start


def hour(b, clock, start, h, close):
    clock.t = start + timedelta(hours=h + 1, minutes=1)
    frame = make_frame(h + 1, close, start)
    b.on_hour_closed(frame, frame)


def test_full_cycle_entry_tp_breakeven_stop(env):
    b, market, clock, store, sig, start = env
    sig["entry"] = True
    hour(b, clock, start, 299, 0.12)
    pos = b.pos
    assert pos is not None
    # risk 1 USDT / (0,12 - 0,116) = 250 ARKM -> 30,03 USDT (sermaye tavani 95 USDT)
    gross_qty = 250 * 0.12 * 1.001 / 0.12
    assert pos.initial_qty == pytest.approx(float(np.floor(gross_qty * (1 - FEE) * 10) / 10))
    assert pos.stop == pytest.approx(0.12 - 2 * 0.002)
    assert store["stop"]["status"] == "NEW"
    assert b.state["cash"] == pytest.approx(store["quote"])

    # Fiyat hedefe (0,124) ulasir -> yarisi satilir
    sig["entry"] = False
    market.bid, market.ask = 0.1241, 0.1242
    b.intrabar()
    pos = b.pos
    assert pos.tp_done
    assert pos.qty == pytest.approx(pos.initial_qty - float(np.floor(pos.initial_qty * 0.5 * 10) / 10))
    assert store["stop"]["qty"] == pytest.approx(pos.qty)

    # Mum kapanisi: stop basabasa cekilir ve borsadaki emir yenilenir
    hour(b, clock, start, 300, 0.1235)
    be = 0.12 * (1 + FEE) / (1 - FEE)
    assert b.pos.stop == pytest.approx(be)
    assert store["stop"]["stop"] == pytest.approx(float(np.floor(be * 1e4) / 1e4))

    # Fiyat duser -> stop dolar, pozisyon kapanir
    market.bid, market.ask = 0.1190, 0.1191
    b.intrabar()
    assert b.pos is None
    assert b.state["cash"] == pytest.approx(store["quote"])
    assert store["base"] == pytest.approx(0.0, abs=1e-9)
    trades = pd.read_csv(b.log_dir / "islemler.csv")
    assert len(trades) == 1 and trades["neden"].iloc[0] == "stop"


def test_entry_blocked_by_halt_and_spread(env):
    b, market, clock, store, sig, start = env
    sig["entry"] = True
    market.bid, market.ask = 0.110, 0.120          # %8,7 fark
    hour(b, clock, start, 299, 0.12)
    assert b.pos is None
    market.bid, market.ask = 0.1199, 0.12
    b.state["halted"] = True
    hour(b, clock, start, 300, 0.12)
    assert b.pos is None


def test_stale_signal_not_traded(env):
    b, market, clock, store, sig, start = env
    sig["entry"] = True
    frame = make_frame(300, 0.12, start)
    clock.t = start + timedelta(hours=300, minutes=40)   # kapanistan 40 dk sonra
    b.on_hour_closed(frame, frame)
    assert b.pos is None


def test_signal_exit_sells_everything(env):
    b, market, clock, store, sig, start = env
    sig["entry"] = True
    hour(b, clock, start, 299, 0.12)
    sig["entry"], sig["exit"] = False, True
    hour(b, clock, start, 300, 0.121)
    assert b.pos is None
    assert store["stop"]["status"] == "CANCELED"
    assert b.state["cash"] == pytest.approx(store["quote"])


def test_drawdown_halt(env):
    b, market, clock, store, sig, start = env
    b.state["peak_equity"] = 200.0       # sermaye 100 -> zirveden %50 asagida
    hour(b, clock, start, 299, 0.12)
    assert b.state["halted"]
