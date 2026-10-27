"""Emir katmani: canli Binance ve sanal (paper) islem ayni arayuzu kullanir.

Canli modda koruyucu stop, borsada bekleyen bir STOP_LOSS (veya sembol izin
vermiyorsa STOP_LOSS_LIMIT) satis emri olarak durur. Boylece robot, internet
veya bilgisayar kapansa bile zarar kes seviyesi borsada gecerli kalir.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from .binance_client import BinanceClient, BinanceError, SymbolRules, fill_summary, fmt_decimal

log = logging.getLogger(__name__)

FINAL_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED", "EXPIRED_IN_MATCH"}


@dataclass
class Fill:
    qty: float        # alis: net alinan baz miktar; satis: satilan miktar
    price: float      # ortalama fiyat
    quote: float      # alis: odenen toplam quote; satis: alinan net quote
    fee_quote: float  # komisyonun quote karsiligi


@dataclass
class StopInfo:
    status: str
    executed_qty: float
    quote: float      # dolan kisim icin brut quote


def _cid(prefix: str) -> str:
    return f"arkm{prefix}{uuid.uuid4().hex[:16]}"


class LiveBroker:
    def __init__(self, client: BinanceClient, symbol: str, fee_rate: float, stop_limit_buffer: float):
        self.client = client
        self.symbol = symbol
        self.fee_rate = fee_rate
        self.buffer = stop_limit_buffer
        self.rules: SymbolRules = client.symbol_rules(symbol)
        self.stop_market = "STOP_LOSS" in self.rules.order_types
        client.sync_time()

    def bid_ask(self) -> tuple[float, float]:
        return self.client.book_ticker(self.symbol)

    def free_quote(self) -> float:
        return self.client.balances().get(self.rules.quote_asset, (0.0, 0.0))[0]

    def base_balance(self) -> tuple[float, float]:
        return self.client.balances().get(self.rules.base_asset, (0.0, 0.0))

    def market_buy(self, quote_amount: float) -> Fill:
        q = self.rules.round_quote(quote_amount)
        order = self.client.order_market_buy_quote(self.symbol, fmt_decimal(q), _cid("b"))
        qty, avg, fee_q = fill_summary(order, self.rules.base_asset, self.rules.quote_asset)
        spent = float(order.get("cummulativeQuoteQty", 0))
        quote_fee = sum(float(f["commission"]) for f in order.get("fills", [])
                        if f.get("commissionAsset") == self.rules.quote_asset)
        return Fill(qty, avg, spent + quote_fee, fee_q)

    def sellable(self, qty: float, price: float) -> bool:
        return self.rules.qty_ok(self.rules.round_qty(qty, market=True), price, market=True)

    def market_sell(self, qty: float) -> Fill | None:
        q = self.rules.round_qty(qty, market=True)
        bid, _ = self.bid_ask()
        if not self.rules.qty_ok(q, bid, market=True):
            log.warning("Satis miktari %s borsa alt sinirinin altinda; satilamadi.", q)
            return None
        order = self.client.order_market_sell(self.symbol, fmt_decimal(q), _cid("s"))
        executed, avg, fee_q = fill_summary(order, self.rules.base_asset, self.rules.quote_asset)
        gross = float(order.get("cummulativeQuoteQty", 0))
        quote_fee = sum(float(f["commission"]) for f in order.get("fills", [])
                        if f.get("commissionAsset") == self.rules.quote_asset)
        return Fill(executed, avg, gross - quote_fee, fee_q)

    def place_stop(self, qty: float, stop_price: float) -> str | None:
        q = self.rules.round_qty(qty)
        sp = self.rules.round_price(stop_price)
        if sp <= 0 or not self.rules.qty_ok(q, float(sp)):
            log.warning("Stop emri borsa filtrelerini karsilamiyor (miktar %s, fiyat %s).", q, sp)
            return None
        limit = None
        if not self.stop_market:
            limit = fmt_decimal(self.rules.round_price(float(sp) * (1 - self.buffer)))
        try:
            order = self.client.order_stop_loss(self.symbol, fmt_decimal(q), fmt_decimal(sp), limit, _cid("x"))
        except BinanceError as exc:
            log.error("Stop emri reddedildi: %s", exc)
            return None
        return str(order["orderId"])

    def stop_info(self, order_id: str) -> StopInfo:
        o = self.client.get_order(self.symbol, int(order_id))
        return StopInfo(o["status"], float(o.get("executedQty", 0)), float(o.get("cummulativeQuoteQty", 0)))

    def cancel_stop(self, order_id: str) -> StopInfo:
        try:
            o = self.client.cancel_order(self.symbol, int(order_id))
            return StopInfo(o["status"], float(o.get("executedQty", 0)), float(o.get("cummulativeQuoteQty", 0)))
        except BinanceError as exc:
            # -2011: emir bulunamadi / zaten kapanmis -> gercek durumu sorgula
            log.info("Stop iptal edilemedi (%s); durum sorgulaniyor.", exc)
            return self.stop_info(order_id)

    def on_hourly_bar(self, low: float) -> None:
        """Canli modda stop borsada calisir; bir sey yapmaya gerek yok."""


class PaperBroker:
    """Gercek fiyatlarla sanal islem. Bakiyeler durum dosyasinda saklanir."""

    def __init__(self, client: BinanceClient, symbol: str, rules: SymbolRules, fee_rate: float,
                 slippage: float, store: dict, starting_quote: float):
        self.client = client
        self.symbol = symbol
        self.rules = rules
        self.fee_rate = fee_rate
        self.slippage = slippage
        self.store = store
        store.setdefault("quote", starting_quote)
        store.setdefault("base", 0.0)
        store.setdefault("stop", None)
        store.setdefault("seq", 0)

    def bid_ask(self) -> tuple[float, float]:
        return self.client.book_ticker(self.symbol)

    def free_quote(self) -> float:
        return float(self.store["quote"])

    def base_balance(self) -> tuple[float, float]:
        stop = self.store["stop"]
        locked = stop["qty"] if stop and stop["status"] == "NEW" else 0.0
        return float(self.store["base"]) - locked, locked

    def market_buy(self, quote_amount: float) -> Fill:
        _, ask = self.bid_ask()
        price = ask * (1 + self.slippage)
        quote = min(float(quote_amount), self.store["quote"])
        gross_qty = quote / price
        qty = float(self.rules.round_qty(gross_qty * (1 - self.fee_rate), market=True))
        self.store["quote"] -= quote
        self.store["base"] += qty
        return Fill(qty, price, quote, gross_qty * self.fee_rate * price)

    def sellable(self, qty: float, price: float) -> bool:
        return self.rules.qty_ok(self.rules.round_qty(qty, market=True), price, market=True)

    def market_sell(self, qty: float) -> Fill | None:
        bid, _ = self.bid_ask()
        q = float(self.rules.round_qty(min(qty, self.base_balance()[0]), market=True))
        if not self.rules.qty_ok(self.rules.round_qty(q, market=True), bid, market=True):
            return None
        price = bid * (1 - self.slippage)
        gross = q * price
        self.store["base"] -= q
        self.store["quote"] += gross * (1 - self.fee_rate)
        return Fill(q, price, gross * (1 - self.fee_rate), gross * self.fee_rate)

    def place_stop(self, qty: float, stop_price: float) -> str | None:
        q = float(self.rules.round_qty(qty))
        sp = float(self.rules.round_price(stop_price))
        if sp <= 0 or not self.rules.qty_ok(self.rules.round_qty(q), sp):
            return None
        self.store["seq"] += 1
        oid = f"P{self.store['seq']}"
        self.store["stop"] = {"id": oid, "qty": q, "stop": sp, "status": "NEW", "quote": 0.0, "executed": 0.0}
        return oid

    def _trigger(self, price: float) -> None:
        s = self.store["stop"]
        fill = price * (1 - self.slippage)
        gross = s["qty"] * fill
        self.store["base"] -= s["qty"]
        self.store["quote"] += gross * (1 - self.fee_rate)
        s.update(status="FILLED", quote=gross, executed=s["qty"])

    def _check_price(self) -> None:
        s = self.store["stop"]
        if s and s["status"] == "NEW":
            bid, _ = self.bid_ask()
            if bid <= s["stop"]:
                self._trigger(min(bid, s["stop"]))

    def on_hourly_bar(self, low: float) -> None:
        """Yoklama arasinda kacan fitilleri yakalamak icin kapanan mumun dibine bakilir."""
        s = self.store["stop"]
        if s and s["status"] == "NEW" and low <= s["stop"]:
            self._trigger(s["stop"])

    def stop_info(self, order_id: str) -> StopInfo:
        self._check_price()
        s = self.store["stop"]
        if not s or s["id"] != order_id:
            return StopInfo("CANCELED", 0.0, 0.0)
        return StopInfo(s["status"], s["executed"], s["quote"])

    def cancel_stop(self, order_id: str) -> StopInfo:
        info = self.stop_info(order_id)
        s = self.store["stop"]
        if s and s["id"] == order_id and s["status"] == "NEW":
            s["status"] = "CANCELED"
            info = StopInfo("CANCELED", 0.0, 0.0)
        return info
