from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from arkmbot.binance_client import (BinanceClient, BinanceError, SymbolRules, fill_summary,
                                    floor_to_step, fmt_decimal, sign)

# Binance exchangeInfo yapisinda ORNEK degerler (gercek ARKMUSDT filtreleri degildir).
EXCHANGE_INFO = {
    "symbol": "ARKMUSDT", "baseAsset": "ARKM", "quoteAsset": "USDT", "quoteAssetPrecision": 8,
    "orderTypes": ["LIMIT", "LIMIT_MAKER", "MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT"],
    "filters": [
        {"filterType": "PRICE_FILTER", "minPrice": "0.00010000", "maxPrice": "1000.00000000", "tickSize": "0.00010000"},
        {"filterType": "LOT_SIZE", "minQty": "0.10000000", "maxQty": "9222449.00000000", "stepSize": "0.10000000"},
        {"filterType": "MARKET_LOT_SIZE", "minQty": "0.00000000", "maxQty": "100000.00000000", "stepSize": "0.00000000"},
        {"filterType": "NOTIONAL", "minNotional": "5.00000000", "applyMinToMarket": True,
         "maxNotional": "9000000.00000000", "applyMaxToMarket": False, "avgPriceMins": 5},
    ],
}


def test_signature_matches_binance_documentation_example():
    secret = "NhqPtmdSJYdKjVHjA7PZj4Mge3R5YNiP1e3UZjInClVN65XAbvqqM6A7H5fATj0j"
    query = ("symbol=LTCBTC&side=BUY&type=LIMIT&timeInForce=GTC&quantity=1&price=0.1"
             "&recvWindow=5000&timestamp=1499827319559")
    assert sign(secret, query) == "c8db56825ae71d6d79447849e617115f4a920fa2acdcab2b053c4b2838bd6b71"


@pytest.mark.parametrize("value,step,expected", [
    (12.3456, "0.1", "12.3"), (0.19, "0.1", "0.1"), (5, "1", "5"), (7.99999, "0.0001", "7.9999"),
    (0.12345678, "0.00000001", "0.12345678"), (25, "10", "20"),
])
def test_floor_to_step(value, step, expected):
    assert fmt_decimal(floor_to_step(value, step)) == expected


def test_symbol_rules_parsing_and_rounding():
    r = SymbolRules.from_exchange_info(EXCHANGE_INFO)
    assert r.step_size == Decimal("0.1")
    assert r.market_step_size == Decimal("0.1")       # MARKET_LOT_SIZE adimi 0 -> LOT_SIZE
    assert r.min_notional == Decimal("5")
    assert fmt_decimal(r.round_qty(123.456)) == "123.4"
    assert fmt_decimal(r.round_qty(200000, market=True)) == "100000"   # MARKET maxQty siniri
    assert fmt_decimal(r.round_price(0.123456)) == "0.1234"
    # 40 ARKM x 0.12 = 4.8 USDT < 5 -> gecersiz; 42 x 0.12 = 5.04 -> gecerli
    assert not r.qty_ok(Decimal("40"), 0.12, market=True)
    assert r.qty_ok(Decimal("42"), 0.12, market=True)
    assert not r.qty_ok(Decimal("0.05"), 1000)          # minQty altinda


def test_fill_summary_buy_fee_in_base():
    order = {"side": "BUY", "executedQty": "100.0", "cummulativeQuoteQty": "12.5",
             "fills": [{"price": "0.125", "qty": "100.0", "commission": "0.1", "commissionAsset": "ARKM"}]}
    qty, avg, fee_q = fill_summary(order, "ARKM", "USDT")
    assert qty == pytest.approx(99.9)
    assert avg == pytest.approx(0.125)
    assert fee_q == pytest.approx(0.1 * 0.125)


def test_fill_summary_sell_fee_in_quote():
    order = {"side": "SELL", "executedQty": "50", "cummulativeQuoteQty": "6.0",
             "fills": [{"price": "0.12", "qty": "50", "commission": "0.006", "commissionAsset": "USDT"}]}
    qty, avg, fee_q = fill_summary(order, "ARKM", "USDT")
    assert qty == 50 and avg == pytest.approx(0.12) and fee_q == pytest.approx(0.006)


class FakeResp:
    def __init__(self, status, body, headers=None):
        self.status_code, self._body, self.headers, self.text = status, body, headers or {}, str(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, timeout=None):
        self.calls.append((method, url, headers))
        return self.responses.pop(0)


def test_signed_request_contains_valid_signature():
    sess = FakeSession([FakeResp(200, {"orderId": 1})])
    c = BinanceClient("https://x.test", api_key="k", api_secret="s", session=sess)
    c.order_stop_loss("ARKMUSDT", "10", "0.1", None, "cid")
    method, url, headers = sess.calls[0]
    assert method == "POST" and headers["X-MBX-APIKEY"] == "k"
    query = urlparse(url).query
    body, sig = query.rsplit("&signature=", 1)
    assert sign("s", body) == sig
    q = parse_qs(body)
    assert q["type"] == ["STOP_LOSS"] and q["stopPrice"] == ["0.1"] and "price" not in q


def test_stop_limit_has_price_and_tif():
    sess = FakeSession([FakeResp(200, {"orderId": 1})])
    c = BinanceClient("https://x.test", api_key="k", api_secret="s", session=sess)
    c.order_stop_loss("ARKMUSDT", "10", "0.1", "0.099", "cid")
    q = parse_qs(urlparse(sess.calls[0][1]).query)
    assert q["type"] == ["STOP_LOSS_LIMIT"] and q["price"] == ["0.099"] and q["timeInForce"] == ["GTC"]


def test_post_5xx_is_not_retried_but_get_is(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    sess = FakeSession([FakeResp(503, {"code": -1, "msg": "busy"})])
    c = BinanceClient("https://x.test", api_key="k", api_secret="s", session=sess)
    with pytest.raises(BinanceError):
        c.order_market_sell("ARKMUSDT", "1")
    assert len(sess.calls) == 1
    sess2 = FakeSession([FakeResp(503, {"code": -1, "msg": "busy"}), FakeResp(200, {"serverTime": 5})])
    c2 = BinanceClient("https://x.test", session=sess2)
    assert c2.server_time_ms() == 5
    assert len(sess2.calls) == 2


def test_unsigned_without_keys_raises_for_signed():
    c = BinanceClient("https://x.test", session=FakeSession([]))
    with pytest.raises(BinanceError):
        c.account()
