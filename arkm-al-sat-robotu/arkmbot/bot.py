"""Canli / paper islem dongusu.

Her kapanan mumda: veri guncellenir, sinyal hesaplanir, acik pozisyonun stopu
guncellenir ya da kosullar uygunsa yeni pozisyon acilir. Mumlar arasinda
kar al seviyesi ve borsadaki stop emrinin durumu yoklanir.

Robot yalnizca kendi aldigi ARKM miktarini yonetir; hesaptaki diger bakiyelere dokunmaz.
"""
from __future__ import annotations

import csv
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .binance_client import BinanceClient, BinanceError
from .broker import FINAL_STATUSES, Fill
from .config import Settings
from .data import resample, update_cache
from .research import run_research
from .strategy import FeatureLibrary, Params, signals
from .trade_manager import PositionState, open_position, tp_sell_qty, update_on_close

log = logging.getLogger(__name__)
HOUR_MS = 3_600_000
SIGNAL_MAX_AGE = timedelta(minutes=15)   # bundan eski kapanis sinyaliyle alim yapilmaz
_KEEP = object()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Bot:
    def __init__(self, settings: Settings, data_client: BinanceClient, broker, mode: str,
                 research_fn=run_research, clock=utcnow):
        self.s = settings
        self.data_client = data_client
        self.broker = broker
        self.mode = mode
        self.research_fn = research_fn
        self.clock = clock
        self.state_path = settings.path("durum_dosyasi")
        self.log_dir = settings.path("kayit_klasoru")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()
        self.plan: dict | None = None
        self.params: Params | None = None

    # ---- durum ----------------------------------------------------------
    def _load_state(self) -> dict:
        if self.state_path.exists():
            st = json.loads(self.state_path.read_text(encoding="utf-8"))
            if st.get("mod") != self.mode:
                raise RuntimeError(f"Durum dosyasi '{st.get('mod')}' moduna ait. Farkli mod icin "
                                   f"'durum_dosyasi' ayarini degistirin.")
            return st
        cap = float(self.s.sermaye_limiti_usdt)
        return {"mod": self.mode, "cash": cap, "start_capital": cap, "peak_equity": cap,
                "day": None, "day_start_equity": cap, "halted": False, "halt_reason": "",
                "cooldown_until": None, "position": None, "last_bar_time": None, "paper": {}}

    def save(self) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_path)

    @property
    def pos(self) -> PositionState | None:
        p = self.state.get("position")
        if not p:
            return None
        return PositionState.from_dict({k: v for k, v in p.items() if k in PositionState.__dataclass_fields__})

    def _set_pos(self, pos: PositionState | None, stop_id=_KEEP, stop_price=_KEEP) -> None:
        """Pozisyonu duruma yazar. stop_id/stop_price verilmezse mevcut deger korunur."""
        if pos is None:
            self.state["position"] = None
            return
        old = self.state.get("position") or {}
        d = pos.to_dict()
        d["stop_order_id"] = old.get("stop_order_id") if stop_id is _KEEP else stop_id
        d["stop_order_price"] = old.get("stop_order_price") if stop_price is _KEEP else stop_price
        if d["stop_order_id"] is None:
            d["stop_order_price"] = None
        self.state["position"] = d

    def _place_stop(self, pos: PositionState) -> str | None:
        sid = self.broker.place_stop(pos.qty, pos.stop)
        self._set_pos(pos, stop_id=sid, stop_price=pos.stop if sid else None)
        return sid

    @property
    def stop_id(self) -> str | None:
        return (self.state.get("position") or {}).get("stop_order_id")

    # ---- parametreler -----------------------------------------------------
    def load_plan(self, allow_research: bool = True) -> None:
        path = self.s.path("parametre_dosyasi")
        stale = True
        if path.exists():
            self.plan = json.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(self.plan["olusturma"])
            stale = self.clock() - created > timedelta(days=self.s.test_gun)
        if (self.plan is None or stale) and allow_research and self.pos is None:
            log.info("Parametreler yok veya eski; arastirma yeniden calistiriliyor...")
            self.plan = self.research_fn(self.s)
        if self.plan is None:
            raise RuntimeError("parametreler.json yok. Once 'python -m arkmbot arastir' calistirin.")
        self.params = Params.from_dict(self.plan["params"]) if self.plan.get("params") else None
        log.info("Plan: islem %s, risk %.4f, parametre %s", "ACIK" if self.plan["islem_acik"] else "KAPALI",
                 self.plan["risk_orani"], self.params)

    # ---- veri ----------------------------------------------------------------
    def refresh_data(self) -> tuple[pd.DataFrame, pd.DataFrame, int]:
        folder = self.s.path("veri_klasoru")
        arkm, n_new = update_cache(self.data_client, folder, self.s.sembol, self.s.baslangic_tarihi)
        btc, _ = update_cache(self.data_client, folder, self.s.btc_sembol, self.s.baslangic_tarihi)
        return arkm, btc, n_new

    # ---- ana dongu -----------------------------------------------------------
    def run(self) -> None:
        self.load_plan()
        self.reconcile()
        log.info("Robot basladi (%s modu).", self.mode)
        while True:
            try:
                self.step()
            except BinanceError as exc:
                log.error("Borsa hatasi: %s", exc)
            except Exception:  # dongu dusmesin; hata kaydedilir
                log.exception("Beklenmeyen hata")
            time.sleep(self.s.kontrol_saniye)

    def step(self) -> None:
        now_ms = int(self.clock().timestamp() * 1000)
        last_open = self.state.get("_last_1h_open")
        if last_open is None or now_ms >= last_open + 2 * HOUR_MS + 3000:
            arkm, btc, _ = self.refresh_data()
            newest = int(arkm["open_time"].iloc[-1])
            if newest != last_open:
                self.state["_last_1h_open"] = newest
                self.on_hour_closed(arkm, btc)
                return
        self.intrabar()

    # ---- mum kapanisi ----------------------------------------------------------
    def on_hour_closed(self, arkm: pd.DataFrame, btc: pd.DataFrame) -> None:
        self.broker.on_hourly_bar(float(arkm["low"].iloc[-1]))
        self.sync_stop()
        if self.params is None:
            self._bookkeeping(None)
            self._maybe_reresearch()
            self.save()
            return
        p = self.params
        bars = resample(arkm, p.timeframe)
        lib = FeatureLibrary(bars, resample(btc, p.timeframe))
        entry, exit_, atr = signals(lib, p)
        last_t = self.state.get("last_bar_time")
        if last_t is None:
            new_idx = [len(bars) - 1]
        else:
            new_idx = list(np.flatnonzero(bars.index > pd.Timestamp(last_t)))
        if not new_idx:
            self.save()
            return
        self.state["last_bar_time"] = str(bars.index[-1])
        bar_close = bars.index[-1] + pd.Timedelta(p.timeframe)

        pos = self.pos
        if pos is not None:
            entry_t = pd.Timestamp(pos.entry_time)
            exit_requested = False
            for i in new_idx:
                if bars.index[i] + pd.Timedelta(p.timeframe) <= entry_t:
                    continue   # pozisyon bu mum kapandiktan sonra acilmis
                exit_requested = update_on_close(pos, float(bars["high"].iloc[i]), float(atr[i]),
                                                 bool(exit_[i]), p, self.s.ucret_orani) or exit_requested
            self._set_pos(pos)
            if exit_requested:
                self.exit_position("sinyal")
            else:
                self.update_stop_order()

        bid, ask = self.broker.bid_ask()
        self._bookkeeping(bid)
        if self.pos is None and bool(entry[-1]):
            if self.clock() - bar_close.to_pydatetime() > SIGNAL_MAX_AGE:
                log.info("Alis sinyali bayat (mum %s kapandi); islem acilmadi.", bar_close)
            else:
                self.try_enter(float(atr[-1]), bid, ask)
        elif self.pos is None:
            self._maybe_reresearch()
        self.save()

    def _maybe_reresearch(self) -> None:
        created = datetime.fromisoformat(self.plan["olusturma"])
        if self.clock() - created > timedelta(days=self.s.test_gun):
            self.load_plan()

    # ---- risk muhasebesi -------------------------------------------------------
    def equity(self, bid: float | None) -> float:
        pos = self.pos
        value = pos.qty * bid if (pos is not None and bid) else 0.0
        return float(self.state["cash"]) + value

    def _bookkeeping(self, bid: float | None) -> None:
        eq = self.equity(bid)
        today = self.clock().date().isoformat()
        if self.state.get("day") != today:
            self.state["day"] = today
            self.state["day_start_equity"] = eq
        if eq > self.state["peak_equity"]:
            self.state["peak_equity"] = eq
        if not self.state["halted"] and eq <= self.state["peak_equity"] * (1 - self.s.maks_dusus_limiti):
            self.state["halted"] = True
            self.state["halt_reason"] = (f"Sermaye zirveden %{self.s.maks_dusus_limiti * 100:.0f} dustu "
                                         f"({eq:.2f} / {self.state['peak_equity']:.2f}). Yeni islem durduruldu.")
            log.error(self.state["halt_reason"])

    def entry_blockers(self, bid: float, ask: float) -> list[str]:
        reasons = []
        now = self.clock()
        if not self.plan or not self.plan.get("islem_acik"):
            reasons.append("arastirma islem izni vermedi")
        if self.state["halted"]:
            reasons.append("maksimum dusus siniri (robot durduruldu)")
        if self.equity(bid) <= self.state["day_start_equity"] * (1 - self.s.gunluk_zarar_limiti):
            reasons.append("gunluk zarar limiti")
        cd = self.state.get("cooldown_until")
        if cd and now < datetime.fromisoformat(cd):
            reasons.append("zarar sonrasi bekleme suresi")
        for d in self.s.kilit_acilim_tarihleri:
            t = datetime.fromisoformat(d).replace(tzinfo=timezone.utc)
            h = timedelta(hours=self.s.kilit_acilim_bekleme_saat)
            if t - h <= now < t + timedelta(days=1) + h:
                reasons.append(f"kilit acilimi yasak penceresi ({d})")
        mid = (bid + ask) / 2
        if mid <= 0 or (ask - bid) / mid > self.s.maks_spread_orani:
            reasons.append(f"alis-satis farki yuksek ({bid} / {ask})")
        return reasons

    # ---- islemler --------------------------------------------------------------
    def try_enter(self, atr_now: float, bid: float, ask: float) -> None:
        blockers = self.entry_blockers(bid, ask)
        if blockers:
            log.info("Alis sinyali var ama islem acilmadi: %s", "; ".join(blockers))
            return
        p = self.params
        stop_est = ask - p.sl_atr * atr_now
        if not (atr_now > 0 and stop_est > 0):
            return
        cash = float(self.state["cash"])
        risk_amt = cash * float(self.plan["risk_orani"])
        qty = risk_amt / (ask - stop_est)
        quote = min(qty * ask * (1 + self.s.ucret_orani), cash * self.s.maks_pozisyon_orani,
                    self.broker.free_quote() * 0.995)
        if quote < self.s.min_islem_tutari:
            log.warning("Islem tutari (%.2f) alt sinirin altinda; alim yapilmadi.", quote)
            return
        try:
            fill = self.broker.market_buy(quote)
        except Exception as exc:
            # Emir borsaya ulasmis olabilir; belirsiz durumda yeni islem acmak tehlikeli.
            self.state["halted"] = True
            self.state["halt_reason"] = (f"Alim emri sonucu belirsiz ({exc}). Binance hesabinizi kontrol "
                                         "edip 'python -m arkmbot devam' ile robotu acin.")
            log.critical(self.state["halt_reason"])
            self.save()
            return
        if fill.qty <= 0:
            log.error("Alim emri dolmadi.")
            return
        self.state["cash"] = cash - fill.quote
        pos = open_position(fill.price, fill.qty, fill.quote, fill.fee_quote, atr_now, p,
                            self.clock().isoformat())
        self._set_pos(pos, stop_id=None)
        log.info("ALIS: %.4f ARKM @ %.6f (%.2f USDT), stop %.6f, hedef %s",
                 fill.qty, fill.price, fill.quote, pos.stop, f"{pos.tp:.6f}" if pos.tp else "-")
        if self._place_stop(pos) is None:
            log.error("Koruyucu stop yerlestirilemedi; pozisyon guvenlik icin kapatiliyor.")
            self.save()
            self.exit_position("stop_yerlestirilemedi")
        self.save()

    def update_stop_order(self) -> None:
        """Stop seviyesi yukseldiyse borsadaki emri iptal edip yenisini koyar."""
        pos, sid = self.pos, self.stop_id
        if pos is None:
            return
        bid, _ = self.broker.bid_ask()
        if bid <= pos.stop:
            self.exit_position("stop")
            return
        old_price = (self.state.get("position") or {}).get("stop_order_price")
        tick = float(self.broker.rules.tick_size) or 0.0
        if sid is not None and old_price is not None and pos.stop - old_price < max(tick, 1e-12):
            return
        if sid is not None:
            info = self.broker.cancel_stop(sid)
            if info.status == "FILLED":
                self._close_from_stop(info)
                return
            self._set_pos(pos, stop_id=None)
            if info.executed_qty > 0:
                self._partial_stop_fill(info)
                self.exit_position("stop")
                return
        if self._place_stop(pos) is None:
            self.exit_position("stop_yerlestirilemedi")

    def sync_stop(self) -> None:
        """Borsadaki stop emri dolduysa pozisyonu kapatir."""
        pos, sid = self.pos, self.stop_id
        if pos is None or sid is None:
            return
        info = self.broker.stop_info(sid)
        if info.status == "FILLED":
            self._close_from_stop(info)
        elif info.status in FINAL_STATUSES:
            log.warning("Stop emri '%s' durumunda; yeniden yerlestiriliyor.", info.status)
            self._set_pos(pos, stop_id=None)
            if info.executed_qty > 0:
                self._partial_stop_fill(info)
            self.update_stop_order()

    def intrabar(self) -> None:
        pos = self.pos
        if pos is None:
            return
        self.sync_stop()
        pos = self.pos
        if pos is None:
            self.save()
            return
        bid, _ = self.broker.bid_ask()
        # STOP_LOSS_LIMIT tetiklenip dolmadiysa (fiyat limiti asagi gecti) piyasadan cik
        if bid < pos.stop * (1 - 2 * self.s.stop_limit_tamponu):
            log.warning("Fiyat stopun belirgin altinda (%.6f < %.6f); piyasa emriyle cikiliyor.", bid, pos.stop)
            self.exit_position("stop")
            self.save()
            return
        if pos.tp is not None and not pos.tp_done and bid >= pos.tp:
            self.take_profit()
            self.save()

    def take_profit(self) -> None:
        pos, p = self.pos, self.params
        q = tp_sell_qty(pos, p)
        remaining = pos.qty - q
        bid, _ = self.broker.bid_ask()
        if q >= pos.qty - 1e-12 or not self.broker.sellable(remaining, bid):
            self.exit_position("kar_al")
            return
        if self.stop_id:
            info = self.broker.cancel_stop(self.stop_id)
            if info.status == "FILLED":
                self._close_from_stop(info)
                return
            self._set_pos(pos, stop_id=None)
            if info.executed_qty > 0:
                self._partial_stop_fill(info)
                self.exit_position("stop")
                return
        fill = self.broker.market_sell(q)
        if fill is None:
            self.exit_position("kar_al")
            return
        self.state["cash"] = float(self.state["cash"]) + fill.quote
        pos.qty -= fill.qty
        pos.proceeds += fill.quote
        pos.fees += fill.fee_quote
        pos.tp_done = True
        log.info("KISMI KAR AL: %.4f ARKM @ %.6f, kalan %.4f", fill.qty, fill.price, pos.qty)
        if self._place_stop(pos) is None:
            self.exit_position("stop_yerlestirilemedi")

    def exit_position(self, reason: str) -> None:
        pos, sid = self.pos, self.stop_id
        if pos is None:
            return
        if sid is not None:
            info = self.broker.cancel_stop(sid)
            if info.status == "FILLED":
                self._close_from_stop(info)
                return
            self._set_pos(pos, stop_id=None)
            if info.executed_qty > 0:
                self._partial_stop_fill(info)
                pos = self.pos
        free_base = self.broker.base_balance()[0]
        qty = min(pos.qty, free_base)
        fill = self.broker.market_sell(qty) if qty > 0 else None
        if fill is None:
            log.error("Kalan %.6f ARKM satilamadi (alt sinir). Pozisyon kapali sayiliyor.", qty)
            fill = Fill(0.0, 0.0, 0.0, 0.0)
        self.state["cash"] = float(self.state["cash"]) + fill.quote
        pos.proceeds += fill.quote
        pos.fees += fill.fee_quote
        self._record_close(pos, fill.price, reason)

    def _partial_stop_fill(self, info) -> None:
        pos = self.pos
        net = info.quote * (1 - self.s.ucret_orani)
        self.state["cash"] = float(self.state["cash"]) + net
        pos.qty -= info.executed_qty
        pos.proceeds += net
        pos.fees += info.quote * self.s.ucret_orani
        self._set_pos(pos, stop_id=None)

    def _close_from_stop(self, info) -> None:
        pos = self.pos
        # GET /order komisyon icermez; komisyon ayardaki oranla tahmin edilir.
        net = info.quote * (1 - self.s.ucret_orani)
        self.state["cash"] = float(self.state["cash"]) + net
        pos.proceeds += net
        pos.fees += info.quote * self.s.ucret_orani
        avg = info.quote / info.executed_qty if info.executed_qty else pos.stop
        self._record_close(pos, avg, "stop")

    def _record_close(self, pos: PositionState, last_price: float, reason: str) -> None:
        pnl = pos.proceeds - pos.cost
        r_mult = pnl / pos.initial_risk if pos.initial_risk > 0 else 0.0
        now = self.clock()
        if pnl < 0:
            bars = self.s.zarar_sonrasi_bekleme_bar
            tf_hours = 4 if (self.params and self.params.timeframe == "4h") else 1
            self.state["cooldown_until"] = (now + timedelta(hours=bars * tf_hours)).isoformat()
        log.info("POZISYON KAPANDI (%s): net %.4f USDT, R=%.2f", reason, pnl, r_mult)
        path = self.log_dir / "islemler.csv"
        new = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(["mod", "giris_zamani", "cikis_zamani", "giris_fiyati", "son_cikis_fiyati",
                            "miktar", "maliyet", "gelir", "net_kar", "R", "neden"])
            w.writerow([self.mode, pos.entry_time, now.isoformat(), f"{pos.entry_price:.8f}",
                        f"{last_price:.8f}", f"{pos.initial_qty:.8f}", f"{pos.cost:.4f}",
                        f"{pos.proceeds:.4f}", f"{pnl:.4f}", f"{r_mult:.3f}", reason])
        self._set_pos(None)

    # ---- baslangic mutabakati ------------------------------------------------
    def reconcile(self) -> None:
        pos = self.pos
        if pos is None:
            return
        log.info("Kayitli acik pozisyon bulundu; borsa ile karsilastiriliyor.")
        sid = self.stop_id
        if sid is not None:
            info = self.broker.stop_info(sid)
            if info.status == "FILLED":
                self._close_from_stop(info)
                self.save()
                return
        free_base, locked = self.broker.base_balance()
        held = free_base + locked
        if held < pos.qty * 0.99:
            log.warning("Hesaptaki ARKM (%.4f) kayittan (%.4f) az; miktar guncelleniyor.", held, pos.qty)
            pos.qty = held
            self._set_pos(pos)
        if sid is None or self.broker.stop_info(sid).status in FINAL_STATUSES:
            self._set_pos(self.pos, stop_id=None)
            self.update_stop_order()
        self.save()
