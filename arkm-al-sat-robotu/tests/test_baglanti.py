"""'baglanti' komutunun emir vermeden yaptigi kontroller (sahte Binance yanitlariyla)."""
from urllib.parse import urlparse

import pytest

from arkmbot.__main__ import check_connection
from arkmbot.binance_client import BinanceClient
from arkmbot.config import Settings

from .test_binance_client import EXCHANGE_INFO, FakeResp


class RoutedSession:
    def __init__(self, routes):
        self.routes = routes
        self.methods = []

    def request(self, method, url, headers=None, timeout=None):
        self.methods.append(method)
        return FakeResp(200, self.routes[urlparse(url).path])


def routes(withdrawals=False, usdt="150", trading=True):
    return {
        "/api/v3/time": {"serverTime": 0},
        "/api/v3/account": {"canTrade": True, "balances": [
            {"asset": "USDT", "free": usdt, "locked": "0"}, {"asset": "ARKM", "free": "0", "locked": "0"}]},
        "/sapi/v1/account/apiRestrictions": {"ipRestrict": True, "enableReading": True,
                                             "enableSpotAndMarginTrading": trading,
                                             "enableWithdrawals": withdrawals},
        "/api/v3/exchangeInfo": {"symbols": [EXCHANGE_INFO]},
    }


def run(**kw):
    sess = RoutedSession(routes(**kw))
    client = BinanceClient("https://x.test", api_key="k", api_secret="s", session=sess)
    info, problems = check_connection(client, Settings(), testnet=False)
    assert set(sess.methods) == {"GET"}          # hicbir emir gonderilmez
    return info, problems


def test_ready_connection_has_no_problems():
    info, problems = run()
    assert problems == []
    assert any("USDT: 150.00" in line for line in info)
    assert any("STOP_LOSS" in line for line in info)


def test_withdrawal_permission_is_flagged():
    _, problems = run(withdrawals=True)
    assert any("PARA CEKME" in p for p in problems)


def test_missing_trading_permission_and_low_balance():
    _, problems = run(trading=False, usdt="3")
    assert any("Spot & Margin Trading" in p for p in problems)
    assert any("yeterli USDT yok" in p for p in problems)


def test_balance_below_capital_limit_is_note_not_problem():
    info, problems = run(usdt="40")
    assert problems == []
    assert any("en fazla 40.00 USDT" in line for line in info)
