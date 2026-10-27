"""Komut satiri.

    python -m arkmbot indir                      # tum ARKM ve BTC gecmisini indir / guncelle
    python -m arkmbot arastir                    # walk-forward arastirma, parametreler.json + rapor
    python -m arkmbot backtest                   # secilen parametrelerle tum gecmis (ornek ici) test
    python -m arkmbot calistir                   # paper (sanal) islem
    python -m arkmbot calistir --canli --onayliyorum   # gercek emirlerle islem
    python -m arkmbot durum                      # durum ozeti
    python -m arkmbot devam                      # durdurulan robotu yeniden ac
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from .binance_client import BinanceClient
from .config import load_settings

log = logging.getLogger("arkmbot")


def setup_logging(log_dir: Path, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for h in (logging.StreamHandler(sys.stdout), logging.FileHandler(log_dir / "bot.log", encoding="utf-8")):
        h.setFormatter(fmt)
        root.addHandler(h)


def load_dotenv(path: Path) -> None:
    """KEY=VALUE satirlarini ortam degiskenine yukler (mevcut degiskenleri ezmez)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_indir(s) -> None:
    from .data import update_cache
    client = BinanceClient(s.api_adresi, market_data_url=s.veri_adresi)
    for sym in (s.sembol, s.btc_sembol):
        df, n = update_cache(client, s.path("veri_klasoru"), sym, s.baslangic_tarihi)
        log.info("%s: %d yeni mum, toplam %d (%s - %s)", sym, n, len(df),
                 _ts(df["open_time"].iloc[0]), _ts(df["open_time"].iloc[-1]))


def _ts(ms) -> str:
    import pandas as pd
    return str(pd.Timestamp(int(ms), unit="ms", tz="UTC"))


def cmd_arastir(s, workers: int | None) -> None:
    from .research import run_research
    res = run_research(s, workers=workers)
    o = res["oos"]
    print(f"\nOrnek disi: getiri {o['toplam_getiri']:.2%}, maks dusus {o['maks_dusus']:.2%}, "
          f"islem {o['islem']}, PF {o['kar_faktoru']:.2f}, al-tut {o['al_tut_getiri']:.2%}")
    print(f"Canli karar: islem {'ACIK' if res['islem_acik'] else 'KAPALI'}, risk {res['risk_orani']:.2%}")
    for r in res["kapali_nedeni"]:
        print(" -", r)
    print(f"Rapor: {s.path('rapor_klasoru') / 'arastirma_raporu.md'}")


def cmd_backtest(s) -> None:
    import pandas as pd

    from .backtest import equity_stats, run_backtest, trade_stats
    from .research import blackout_mask, build_libraries, research_config
    from .strategy import Params, signals
    plan = json.loads(s.path("parametre_dosyasi").read_text(encoding="utf-8"))
    if not plan.get("params"):
        print("parametreler.json icinde parametre yok (arastirma uygun set bulamadi).")
        return
    p = Params.from_dict(plan["params"])
    _, libs, _ = build_libraries(s)
    lib = libs[p.timeframe]
    entry, exit_, atr = signals(lib, p)
    allowed = blackout_mask(lib.bars.index, s.kilit_acilim_tarihleri, s.kilit_acilim_bekleme_saat)
    cfg = research_config(s, plan["risk_orani"])
    res = run_backtest(lib.bars, entry, exit_, atr, p, cfg, entry_allowed=allowed)
    st = {**equity_stats(res.equity, res.index, p.timeframe), **trade_stats(res.trades)}
    print("UYARI: Bu test parametrelerin secildigi veriyi de icerir (ornek ici); gercekci "
          "beklenti icin rapordaki walk-forward sonucuna bakin.\n")
    for k, v in st.items():
        print(f"{k:>16}: {v:.4f}" if isinstance(v, float) else f"{k:>16}: {v}")
    out = s.path("rapor_klasoru") / "backtest_islemler.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([t.__dict__ for t in res.trades]).to_csv(out, index=False)
    print(f"\nIslem listesi: {out}")


def cmd_calistir(s, live: bool, confirmed: bool, testnet: bool) -> None:
    from .bot import Bot
    from .broker import LiveBroker, PaperBroker
    data_client = BinanceClient(s.api_adresi, market_data_url=s.veri_adresi)
    if live:
        if not confirmed:
            sys.exit("Canli mod gercek para kullanir. Onayliyorsaniz --onayliyorum ekleyin.")
        key, secret = os.environ.get("BINANCE_API_KEY"), os.environ.get("BINANCE_API_SECRET")
        if not key or not secret:
            sys.exit("BINANCE_API_KEY ve BINANCE_API_SECRET tanimli degil (.env dosyasina yazin).")
        base = s.testnet_adresi if testnet else s.api_adresi
        trade_client = BinanceClient(base, api_key=key, api_secret=secret,
                                     market_data_url=base if testnet else s.veri_adresi)
        broker = LiveBroker(trade_client, s.sembol, s.ucret_orani, s.stop_limit_tamponu)
        mode = "testnet" if testnet else "canli"
    else:
        rules = data_client.symbol_rules(s.sembol)
        mode = "paper"
        bot_state_path = s.path("durum_dosyasi")
        store = {}
        if bot_state_path.exists():
            store = json.loads(bot_state_path.read_text(encoding="utf-8")).get("paper", {})
        broker = PaperBroker(data_client, s.sembol, rules, s.ucret_orani, s.kayma_orani, store,
                             s.sermaye_limiti_usdt)
    bot = Bot(s, data_client, broker, mode)
    if mode == "paper":
        bot.state["paper"] = broker.store
    bot.run()


def cmd_durum(s) -> None:
    p = s.path("durum_dosyasi")
    if not p.exists():
        print("Durum dosyasi yok; robot henuz calistirilmamis.")
        return
    st = json.loads(p.read_text(encoding="utf-8"))
    print(json.dumps({k: v for k, v in st.items() if k != "paper"}, indent=2, ensure_ascii=False))


def cmd_devam(s) -> None:
    p = s.path("durum_dosyasi")
    st = json.loads(p.read_text(encoding="utf-8"))
    st["halted"] = False
    st["halt_reason"] = ""
    # Dusus olcumu yeniden baslasin
    st["peak_equity"] = st["cash"]
    p.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Robot durdurma kaydi temizlendi.")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="arkmbot", description="ARKM/USDT Binance spot al-sat robotu")
    ap.add_argument("--ayar", default="ayarlar.json", help="ayar dosyasi (varsayilan: ayarlar.json)")
    ap.add_argument("-v", "--ayrintili", action="store_true")
    sub = ap.add_subparsers(dest="komut", required=True)
    sub.add_parser("indir")
    a = sub.add_parser("arastir")
    a.add_argument("--islemci", type=int, default=None, help="paralel islem sayisi")
    sub.add_parser("backtest")
    c = sub.add_parser("calistir")
    c.add_argument("--canli", action="store_true", help="gercek emir gonder")
    c.add_argument("--onayliyorum", action="store_true", help="canli mod onayi")
    c.add_argument("--testnet", action="store_true", help="Binance spot testnet kullan")
    sub.add_parser("durum")
    sub.add_parser("devam")
    args = ap.parse_args(argv)

    s = load_settings(args.ayar)
    load_dotenv(s.base_dir / ".env")
    setup_logging(s.path("kayit_klasoru"), args.ayrintili)
    if args.komut == "indir":
        cmd_indir(s)
    elif args.komut == "arastir":
        cmd_arastir(s, args.islemci)
    elif args.komut == "backtest":
        cmd_backtest(s)
    elif args.komut == "calistir":
        cmd_calistir(s, args.canli or args.testnet, args.onayliyorum or args.testnet, args.testnet)
    elif args.komut == "durum":
        cmd_durum(s)
    elif args.komut == "devam":
        cmd_devam(s)


if __name__ == "__main__":
    main()
