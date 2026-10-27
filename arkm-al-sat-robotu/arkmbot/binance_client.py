"""Binance Spot REST istemcisi (yalnizca robotun ihtiyac duydugu uc noktalar).

Imzali isteklerde HMAC-SHA256 kullanilir: imza, sorgu metninin (query string)
API gizli anahtariyla hesaplanan onaltilik ozetidir. Anahtar yalnizca bellekte
tutulur, hicbir dosyaya veya kayda yazilmaz.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass, field
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

import requests

log = logging.getLogger(__name__)

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000,
               "4h": 14_400_000, "1d": 86_400_000}


class BinanceError(Exception):
    def __init__(self, status: int, code: int | None, msg: str):
        super().__init__(f"HTTP {status} / kod {code}: {msg}")
        self.status = status
        self.code = code
        self.msg = msg


def sign(secret: str, query: str) -> str:
    return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()


def floor_to_step(value: float | str | Decimal, step: str | Decimal) -> Decimal:
    """Degeri adim buyuklugunun tam katina asagi yuvarlar (LOT_SIZE / PRICE_FILTER)."""
    v = Decimal(str(value))
    s = Decimal(str(step))
    if s <= 0:
        return v
    return (v / s).to_integral_value(rounding=ROUND_DOWN) * s


def fmt_decimal(d: Decimal) -> str:
    return format(d.normalize(), "f")


@dataclass
class SymbolRules:
    symbol: str
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    market_step_size: Decimal
    market_min_qty: Decimal
    market_max_qty: Decimal
    min_notional: Decimal
    min_notional_applies_to_market: bool
    quote_precision: int
    order_types: list[str] = field(default_factory=list)

    @classmethod
    def from_exchange_info(cls, info: dict) -> "SymbolRules":
        f = {flt["filterType"]: flt for flt in info.get("filters", [])}
        price = f.get("PRICE_FILTER", {})
        lot = f.get("LOT_SIZE", {})
        mlot = f.get("MARKET_LOT_SIZE", {})
        if "NOTIONAL" in f:
            min_notional = f["NOTIONAL"].get("minNotional", "0")
            applies = bool(f["NOTIONAL"].get("applyMinToMarket", True))
        elif "MIN_NOTIONAL" in f:
            min_notional = f["MIN_NOTIONAL"].get("minNotional", "0")
            applies = bool(f["MIN_NOTIONAL"].get("applyToMarket", True))
        else:
            min_notional, applies = "0", False
        step = Decimal(lot.get("stepSize", "0"))
        mstep = Decimal(mlot.get("stepSize", "0"))
        return cls(
            symbol=info["symbol"],
            base_asset=info["baseAsset"],
            quote_asset=info["quoteAsset"],
            tick_size=Decimal(price.get("tickSize", "0")),
            step_size=step,
            min_qty=Decimal(lot.get("minQty", "0")),
            max_qty=Decimal(lot.get("maxQty", "0")),
            # MARKET_LOT_SIZE adimi 0 donerse LOT_SIZE gecerlidir
            market_step_size=mstep if mstep > 0 else step,
            market_min_qty=Decimal(mlot.get("minQty", "0")),
            market_max_qty=Decimal(mlot.get("maxQty", "0")),
            min_notional=Decimal(str(min_notional)),
            min_notional_applies_to_market=applies,
            quote_precision=int(info.get("quoteAssetPrecision", info.get("quotePrecision", 8))),
            order_types=list(info.get("orderTypes", [])),
        )

    def round_qty(self, qty: float, market: bool = False) -> Decimal:
        q = floor_to_step(qty, self.market_step_size if market else self.step_size)
        max_q = self.market_max_qty if market else self.max_qty
        if max_q > 0 and q > max_q:
            q = floor_to_step(max_q, self.market_step_size if market else self.step_size)
        return q

    def round_price(self, price: float) -> Decimal:
        return floor_to_step(price, self.tick_size)

    def round_quote(self, amount: float) -> Decimal:
        return floor_to_step(amount, Decimal(1).scaleb(-self.quote_precision))

    def qty_ok(self, qty: Decimal, price: float, market: bool = False) -> bool:
        min_q = self.market_min_qty if market and self.market_min_qty > 0 else self.min_qty
        if qty <= 0 or qty < min_q:
            return False
        if market and not self.min_notional_applies_to_market:
            return True
        return qty * Decimal(str(price)) >= self.min_notional


class BinanceClient:
    def __init__(self, base_url: str = "https://api.binance.com", api_key: str | None = None,
                 api_secret: str | None = None, market_data_url: str | None = None,
                 timeout: float = 10.0, recv_window: int = 5000, max_retries: int = 4,
                 session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.market_data_url = (market_data_url or base_url).rstrip("/")
        self.api_key = api_key
        self._secret = api_secret
        self.timeout = timeout
        self.recv_window = recv_window
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.time_offset_ms = 0

    # ---- dusuk seviye -------------------------------------------------
    def _request(self, method: str, path: str, params: dict | None = None,
                 signed: bool = False, market_data: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        base = self.market_data_url if market_data else self.base_url
        headers = {}
        if signed:
            if not self.api_key or not self._secret:
                raise BinanceError(0, None, "API anahtari tanimli degil")
            headers["X-MBX-APIKEY"] = self.api_key
        delay = 1.0
        for attempt in range(self.max_retries + 1):
            query_params = dict(params)
            if signed:
                query_params["recvWindow"] = self.recv_window
                query_params["timestamp"] = int(time.time() * 1000) + self.time_offset_ms
            query = urlencode(query_params)
            if signed:
                query += "&signature=" + sign(self._secret, query)
            url = f"{base}{path}" + (f"?{query}" if query else "")
            try:
                resp = self.session.request(method, url, headers=headers, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise BinanceError(0, None, f"Ag hatasi: {exc}") from exc
                log.warning("Ag hatasi (%s), %.0f sn sonra tekrar denenecek", exc, delay)
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code == 200:
                return resp.json()
            code, msg = None, resp.text
            try:
                body = resp.json()
                code, msg = body.get("code"), body.get("msg", resp.text)
            except ValueError:
                pass
            # -1021: zaman damgasi recvWindow disinda -> saati esitle ve tekrar dene
            if code == -1021 and attempt < self.max_retries:
                self.sync_time()
                continue
            retryable = resp.status_code in (429, 418) or resp.status_code >= 500
            # Emir gonderiminde 5xx durumunda emir islenmis olabilir; tekrar gonderilmez.
            if retryable and attempt < self.max_retries and not (method == "POST" and resp.status_code >= 500):
                wait = float(resp.headers.get("Retry-After", delay))
                log.warning("Binance %s dondu, %.0f sn bekleniyor", resp.status_code, wait)
                time.sleep(wait)
                delay *= 2
                continue
            raise BinanceError(resp.status_code, code, msg)
        raise BinanceError(0, None, "Tekrar deneme siniri asildi")

    # ---- herkese acik ---------------------------------------------------
    def sync_time(self) -> None:
        server = self._request("GET", "/api/v3/time")["serverTime"]
        self.time_offset_ms = int(server - time.time() * 1000)

    def server_time_ms(self) -> int:
        return int(self._request("GET", "/api/v3/time", market_data=True)["serverTime"])

    def klines(self, symbol: str, interval: str, start_ms: int | None = None,
               end_ms: int | None = None, limit: int = 1000) -> list[list]:
        return self._request("GET", "/api/v3/klines", {
            "symbol": symbol, "interval": interval, "startTime": start_ms,
            "endTime": end_ms, "limit": limit}, market_data=True)

    def exchange_info(self, symbol: str) -> dict:
        data = self._request("GET", "/api/v3/exchangeInfo", {"symbol": symbol}, market_data=True)
        return data["symbols"][0]

    def symbol_rules(self, symbol: str) -> SymbolRules:
        return SymbolRules.from_exchange_info(self.exchange_info(symbol))

    def book_ticker(self, symbol: str) -> tuple[float, float]:
        d = self._request("GET", "/api/v3/ticker/bookTicker", {"symbol": symbol}, market_data=True)
        return float(d["bidPrice"]), float(d["askPrice"])

    # ---- imzali -----------------------------------------------------------
    def account(self) -> dict:
        return self._request("GET", "/api/v3/account", signed=True)

    def api_restrictions(self) -> dict:
        """API anahtarinin izinleri (enableReading, enableSpotAndMarginTrading,
        enableWithdrawals, ipRestrict ...). Testnet bu uc noktayi desteklemez."""
        return self._request("GET", "/sapi/v1/account/apiRestrictions", signed=True)

    def balances(self) -> dict[str, tuple[float, float]]:
        return {b["asset"]: (float(b["free"]), float(b["locked"]))
                for b in self.account().get("balances", [])}

    def order_market_buy_quote(self, symbol: str, quote_qty: str, client_id: str | None = None) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "BUY", "type": "MARKET", "quoteOrderQty": quote_qty,
            "newClientOrderId": client_id, "newOrderRespType": "FULL"}, signed=True)

    def order_market_sell(self, symbol: str, qty: str, client_id: str | None = None) -> dict:
        return self._request("POST", "/api/v3/order", {
            "symbol": symbol, "side": "SELL", "type": "MARKET", "quantity": qty,
            "newClientOrderId": client_id, "newOrderRespType": "FULL"}, signed=True)

    def order_stop_loss(self, symbol: str, qty: str, stop_price: str,
                        limit_price: str | None = None, client_id: str | None = None) -> dict:
        params = {"symbol": symbol, "side": "SELL", "quantity": qty, "stopPrice": stop_price,
                  "newClientOrderId": client_id}
        if limit_price is None:
            params["type"] = "STOP_LOSS"
        else:
            params.update(type="STOP_LOSS_LIMIT", price=limit_price, timeInForce="GTC")
        return self._request("POST", "/api/v3/order", params, signed=True)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self._request("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def cancel_order(self, symbol: str, order_id: int) -> dict:
        return self._request("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def open_orders(self, symbol: str) -> list[dict]:
        return self._request("GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True)


def fill_summary(order: dict, base_asset: str, quote_asset: str) -> tuple[float, float, float]:
    """FULL yanitindan (net baz miktar, ortalama fiyat, quote cinsinden komisyon) hesaplar.

    Alista komisyon baz varliktan (ARKM) kesilirse net miktar azalir; satista
    komisyon genellikle quote (USDT) cinsindendir. BNB ile odenen komisyon
    burada sifir sayilir, cunku USDT/ARKM bakiyesini etkilemez.
    """
    executed = float(order.get("executedQty", 0))
    quote = float(order.get("cummulativeQuoteQty", 0))
    avg = quote / executed if executed > 0 else 0.0
    base_fee = quote_fee = 0.0
    for f in order.get("fills", []):
        if f.get("commissionAsset") == base_asset:
            base_fee += float(f["commission"])
        elif f.get("commissionAsset") == quote_asset:
            quote_fee += float(f["commission"])
    side = order.get("side")
    net_qty = executed - base_fee if side == "BUY" else executed
    fee_in_quote = quote_fee + base_fee * avg
    return net_qty, avg, fee_in_quote
