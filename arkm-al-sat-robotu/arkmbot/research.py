"""Otomatik arastirma: tum ARKM gecmisi uzerinde walk-forward optimizasyon.

Akis:
1. Izgaradaki her parametre kombinasyonu tum gecmiste bir kez simule edilir
   (gostergeler nedensel oldugu icin bu, ileriye bakma olusturmaz).
2. Gecmis, kayan egitim/test pencerelerine bolunur. Her egitim penceresinde
   kombinasyonlar SQN ile puanlanir; tek bir tepe yerine komsulari da iyi olan
   "plato" secilir. Esik asilmazsa o donemde islem yapilmaz.
3. Secilen parametreler yalnizca bir sonraki (gorulmemis) test penceresinde,
   tasinan sermaye ile islem yapar. Test pencerelerinin birlesimi, yontemin
   ornek disi (out-of-sample) performansidir.
4. Ornek disi islemlerin R dagilimindan Monte Carlo ile islem basina risk orani secilir.
5. Son egitim penceresinde secilen parametreler canli robot icin kaydedilir.
"""
from __future__ import annotations

import json
import logging
import math
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import (BacktestConfig, equity_stats, max_drawdown, run_backtest, trade_stats)
from .config import Settings
from .data import load_cache, market_profile, resample
from .strategy import FeatureLibrary, Params, build_grid, neighbors, signals

log = logging.getLogger(__name__)

WARMUP_DAYS = 40          # EMA200 (4h) icin yeterli isinma suresi
INELIGIBLE_SCORE = -1.0   # komsuluk ortalamasinda uygun olmayan kombinasyonun puani
RISK_CANDIDATES = [0.0025, 0.005, 0.0075, 0.01, 0.0125, 0.015, 0.02]

_W_LIBS: dict[str, FeatureLibrary] = {}
_W_CFG: BacktestConfig | None = None


# ---- yardimcilar --------------------------------------------------------
def blackout_mask(index: pd.DatetimeIndex, dates: list[str], hours: int) -> np.ndarray:
    """Kilit acilimi tarihlerinin +/- 'hours' cevresinde False olan maske."""
    allowed = np.ones(len(index), bool)
    for d in dates:
        t = pd.Timestamp(d, tz="UTC")
        lo, hi = t - pd.Timedelta(hours=hours), t + pd.Timedelta(hours=24 + hours)
        allowed &= ~((index >= lo) & (index < hi))
    return allowed


def build_libraries(settings: Settings) -> tuple[dict[str, pd.DataFrame], dict[str, FeatureLibrary], pd.DataFrame]:
    folder = settings.path("veri_klasoru")
    arkm = load_cache(folder, settings.sembol)
    btc = load_cache(folder, settings.btc_sembol)
    bars, libs = {}, {}
    for tf in settings.zaman_dilimleri:
        b = resample(arkm, tf)
        bb = resample(btc, tf)
        bars[tf] = b
        libs[tf] = FeatureLibrary(b, bb)
    return bars, libs, arkm


def _init_worker(libs: dict[str, FeatureLibrary], cfg: BacktestConfig) -> None:
    global _W_LIBS, _W_CFG
    _W_LIBS, _W_CFG = libs, cfg


def _run_combo(args: tuple[int, Params, list[str], int]) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """Tek kombinasyonu tum gecmiste calistirir; (giris zamani, cikis zamani, R) dondurur.
    Veri sonunda zorla kapatilan (tamamlanmamis) islem puanlamaya alinmaz."""
    i, p, blackout_dates, blackout_hours = args
    lib = _W_LIBS[p.timeframe]
    entry, exit_, atr = signals(lib, p)
    allowed = blackout_mask(lib.bars.index, blackout_dates, blackout_hours)
    res = run_backtest(lib.bars, entry, exit_, atr, p, _W_CFG, entry_allowed=allowed)
    done = [tr for tr in res.trades if tr.reason != "veri_sonu"]
    t_in = np.array([tr.entry_time.value for tr in done], dtype=np.int64)
    # cikis mumunun kapanis ani: islemin sonucu ancak bu anda bilinir
    step = pd.Timedelta(p.timeframe).value
    t_out = np.array([tr.exit_time.value + step for tr in done], dtype=np.int64)
    r = np.array([tr.r_multiple for tr in done], dtype=float)
    return i, t_in, t_out, r


def research_config(settings: Settings, risk: float = 0.01) -> BacktestConfig:
    return BacktestConfig(initial_capital=settings.baslangic_sermaye, fee=settings.ucret_orani,
                          slippage=settings.kayma_orani, risk_per_trade=risk,
                          max_alloc=settings.maks_pozisyon_orani,
                          cooldown_bars=settings.zarar_sonrasi_bekleme_bar,
                          min_notional=settings.min_islem_tutari)


def score_trades(r: np.ndarray, min_trades: int) -> float | None:
    """SQN puani; uygun degilse None. Uygunluk: yeterli islem, pozitif ortalama R, PF > 1."""
    if len(r) < min_trades:
        return None
    gains, losses = r[r > 0].sum(), -r[r < 0].sum()
    if r.mean() <= 0 or (losses > 0 and gains / losses <= 1.0):
        return None
    sd = r.std(ddof=1)
    if sd == 0:
        return None
    return float(r.mean() / sd * math.sqrt(min(len(r), 100)))


def select_params(grid: list[Params], nbrs: list[list[int]], times: list[np.ndarray],
                  exits: list[np.ndarray], rs: list[np.ndarray], start_ns: int, end_ns: int,
                  min_trades: int, min_score: float) -> tuple[int | None, float, list[tuple[int, float, float]]]:
    """Egitim penceresinde en saglam kombinasyonu secer.

    Yalnizca pencere icinde acilip pencere bitmeden sonucu belli olan islemler sayilir;
    boylece test donemi fiyatlari egitim puanina sizmaz.
    Donus: (secilen indeks veya None, duzeltilmis puan, ilk 10 [indeks, ham, duzeltilmis]).
    """
    raw: list[float | None] = []
    for t, x, r in zip(times, exits, rs):
        m = (t >= start_ns) & (x <= end_ns)
        raw.append(score_trades(r[m], min_trades))
    vals = np.array([INELIGIBLE_SCORE if s is None else s for s in raw])
    smooth = np.full(len(grid), -np.inf)
    for i, s in enumerate(raw):
        if s is None:
            continue
        group = [i] + nbrs[i]
        smooth[i] = float(vals[group].mean())
    order = np.argsort(-smooth)
    top = [(int(i), float(raw[i]), float(smooth[i])) for i in order[:10] if np.isfinite(smooth[i])]
    best = int(order[0]) if len(order) and np.isfinite(smooth[order[0]]) else None
    if best is None or smooth[best] < min_score:
        return None, (float(smooth[best]) if best is not None else float("nan")), top
    return best, float(smooth[best]), top


@dataclass
class Fold:
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    test_end: pd.Timestamp


def make_folds(first: pd.Timestamp, last: pd.Timestamp, train_days: int, test_days: int) -> list[Fold]:
    folds = []
    t0 = first + pd.Timedelta(days=WARMUP_DAYS)
    while True:
        tr_end = t0 + pd.Timedelta(days=train_days)
        if tr_end >= last:
            break
        te_end = min(tr_end + pd.Timedelta(days=test_days), last)
        folds.append(Fold(t0, tr_end, te_end))
        t0 = t0 + pd.Timedelta(days=test_days)
    return folds


def simulate_oos(folds: list[Fold], chosen: list[int | None], grid: list[Params],
                 libs: dict[str, FeatureLibrary], cfg: BacktestConfig, settings: Settings,
                 hourly_index: pd.DatetimeIndex) -> tuple[pd.Series, list, list[dict]]:
    """Secilen parametrelerle test pencerelerini sirayla, sermayeyi tasiyarak isletir."""
    equity = cfg.initial_capital
    flat_since = folds[0].train_end if folds else None
    curve_parts: list[pd.Series] = []
    all_trades = []
    fold_rows = []
    for f, ci in zip(folds, chosen):
        row = {"egitim": f"{f.train_start.date()} - {f.train_end.date()}",
               "test": f"{f.train_end.date()} - {f.test_end.date()}",
               "parametre": None, "islem": 0, "getiri": 0.0}
        if ci is None:
            fold_rows.append(row)
            continue
        p = grid[ci]
        lib = libs[p.timeframe]
        idx = lib.bars.index
        entry, exit_, atr = signals(lib, p)
        start_t = max(f.train_end, flat_since)
        allowed = (idx >= start_t) & (idx < f.test_end)
        allowed &= blackout_mask(idx, settings.kilit_acilim_tarihleri, settings.kilit_acilim_bekleme_saat)
        if not allowed.any():
            fold_rows.append(row)
            continue
        start_idx = int(np.searchsorted(idx, start_t))
        last_allowed = int(np.flatnonzero(idx < f.test_end)[-1])
        fcfg = BacktestConfig(**{**cfg.__dict__, "initial_capital": equity})
        res = run_backtest(lib.bars, entry, exit_, atr, p, fcfg, start_idx=start_idx,
                           entry_allowed=allowed, stop_when_flat_after=last_allowed)
        eq = pd.Series(res.equity, index=idx).dropna()
        curve_parts.append(eq)
        row.update(parametre=p.to_dict(), islem=len(res.trades), getiri=res.final_equity / equity - 1)
        fold_rows.append(row)
        equity = res.final_equity
        all_trades.extend(res.trades)
        if res.trades:
            last_exit = res.trades[-1].exit_time
            flat_since = max(flat_since, last_exit + pd.Timedelta(p.timeframe))
    if curve_parts:
        curve = pd.concat(curve_parts)
        curve = curve[~curve.index.duplicated(keep="last")].sort_index()
    else:
        curve = pd.Series(dtype=float)
    start = folds[0].train_end if folds else hourly_index[0]
    oos_index = hourly_index[hourly_index >= start]
    full = pd.Series(np.nan, index=oos_index)
    if len(curve):
        full = curve.reindex(oos_index.union(curve.index)).sort_index()
        full = full.reindex(oos_index)
    if len(full):
        if np.isnan(full.iloc[0]):
            full.iloc[0] = cfg.initial_capital
        full = full.ffill()
    return full, all_trades, fold_rows


def monte_carlo_risk(r: np.ndarray, target_dd: float, n_sims: int = 5000,
                     seed: int = 7) -> tuple[float | None, list[dict]]:
    """Ornek disi R degerlerini yeniden ornekleyerek (bootstrap) %95 dusus hedefini
    asmayan en buyuk islem basina risk oranini bulur. Islem getirisi = risk x R kabul edilir."""
    if len(r) == 0:
        return None, []
    rng = np.random.default_rng(seed)
    samples = rng.choice(r, size=(n_sims, len(r)), replace=True)
    table, chosen = [], None
    for risk in RISK_CANDIDATES:
        growth = np.clip(1 + risk * samples, 1e-9, None)
        eq = np.cumprod(growth, axis=1)
        eq = np.concatenate([np.ones((n_sims, 1)), eq], axis=1)
        dd = (eq / np.maximum.accumulate(eq, axis=1) - 1).min(axis=1)
        p95 = float(-np.percentile(dd, 5))
        med_ret = float(np.median(eq[:, -1]) - 1)
        table.append({"risk": risk, "dusus_p95": p95, "medyan_getiri": med_ret})
        if p95 <= target_dd:
            chosen = risk
    return chosen, table


# ---- ana akis ---------------------------------------------------------------
def run_research(settings: Settings, workers: int | None = None) -> dict:
    bars, libs, arkm_1h = build_libraries(settings)
    grid = build_grid(settings.zaman_dilimleri)
    nbrs = neighbors(grid)
    cfg = research_config(settings)
    log.info("Arastirma: %d kombinasyon, zaman dilimleri %s", len(grid), settings.zaman_dilimleri)

    n_workers = workers or settings.paralel_islem or os.cpu_count() or 1
    jobs = [(i, p, settings.kilit_acilim_tarihleri, settings.kilit_acilim_bekleme_saat)
            for i, p in enumerate(grid)]
    times: list[np.ndarray] = [np.zeros(0, np.int64)] * len(grid)
    exits: list[np.ndarray] = [np.zeros(0, np.int64)] * len(grid)
    rs: list[np.ndarray] = [np.zeros(0)] * len(grid)
    if n_workers > 1:
        with ProcessPoolExecutor(max_workers=n_workers, initializer=_init_worker,
                                 initargs=(libs, cfg)) as ex:
            for i, t, x, r in ex.map(_run_combo, jobs, chunksize=16):
                times[i], exits[i], rs[i] = t, x, r
    else:
        _init_worker(libs, cfg)
        for job in jobs:
            i, t, x, r = _run_combo(job)
            times[i], exits[i], rs[i] = t, x, r

    hourly_index = pd.to_datetime(arkm_1h["open_time"], unit="ms", utc=True)
    hourly_index = pd.DatetimeIndex(hourly_index)
    first, last = hourly_index[0], hourly_index[-1] + pd.Timedelta(hours=1)
    folds = make_folds(first, last, settings.egitim_gun, settings.test_gun)
    if not folds:
        raise RuntimeError("Walk-forward icin veri yetersiz (egitim_gun + isinma suresinden kisa).")

    chosen, fold_scores = [], []
    for f in folds:
        ci, sc, _ = select_params(grid, nbrs, times, exits, rs, f.train_start.value, f.train_end.value,
                                  settings.min_islem_sayisi, settings.min_skor)
        chosen.append(ci)
        fold_scores.append(sc)

    curve, oos_trades, fold_rows = simulate_oos(folds, chosen, grid, libs, cfg, settings, hourly_index)
    for row, sc in zip(fold_rows, fold_scores):
        row["egitim_skoru"] = sc
    oos_eq = curve.to_numpy(float)
    oos_stats = {**equity_stats(oos_eq, curve.index, "1h"), **trade_stats(oos_trades)}
    oos_start = folds[0].train_end
    closes = arkm_1h.set_index(hourly_index)["close"]
    opens = arkm_1h.set_index(hourly_index)["open"]
    bh_series = closes[closes.index >= oos_start]
    oos_stats["al_tut_getiri"] = float(bh_series.iloc[-1] / opens[opens.index >= oos_start].iloc[0] - 1)
    oos_stats["al_tut_maks_dusus"] = max_drawdown(bh_series.to_numpy(float))

    stress_cfg = BacktestConfig(**{**cfg.__dict__, "fee": cfg.fee * 2, "slippage": cfg.slippage * 2})
    s_curve, s_trades, _ = simulate_oos(folds, chosen, grid, libs, stress_cfg, settings, hourly_index)
    stress_stats = {**equity_stats(s_curve.to_numpy(float), s_curve.index, "1h"), **trade_stats(s_trades)}

    r_oos = np.array([t.r_multiple for t in oos_trades])
    mc_risk, mc_table = monte_carlo_risk(r_oos, settings.hedef_dusus_p95)
    enough = len(r_oos) >= 20
    if settings.islem_risk_orani:
        risk, risk_src = settings.islem_risk_orani, "ayar"
    elif not enough:
        risk, risk_src = settings.varsayilan_risk_orani, "varsayilan (ornek disi islem < 20)"
    elif mc_risk is None:
        # En kucuk aday bile dusus hedefini asiyor: en temkinli aday kullanilir
        risk, risk_src = RISK_CANDIDATES[0], "monte_carlo (hedef asildi, en dusuk aday)"
    else:
        risk, risk_src = mc_risk, "monte_carlo"

    # Canli icin son egitim penceresi
    final_start = last - pd.Timedelta(days=settings.egitim_gun)
    final_ci, final_score, final_top = select_params(grid, nbrs, times, exits, rs, final_start.value,
                                                     last.value, settings.min_islem_sayisi, settings.min_skor)
    oos_ok = (oos_stats["islem"] >= settings.min_islem_sayisi and oos_stats["toplam_R"] > 0
              and oos_stats["kar_faktoru"] > 1.0)
    trade_enabled = final_ci is not None and oos_ok
    reasons = []
    if final_ci is None:
        reasons.append("Son egitim penceresinde esigi gecen saglam bir parametre seti bulunamadi.")
    if not oos_ok:
        reasons.append("Walk-forward ornek disi sonuc pozitif degil (toplam R <= 0, PF <= 1 "
                       "veya islem sayisi yetersiz); yontemin gecmiste kalici bir ustunlugu gosterilemedi.")

    result = {
        "olusturma": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "veri_bitis": str(last),
        "sembol": settings.sembol,
        "islem_acik": bool(trade_enabled),
        "kapali_nedeni": reasons,
        "params": grid[final_ci].to_dict() if final_ci is not None else None,
        "egitim_skoru": final_score,
        "risk_orani": float(risk),
        "risk_kaynagi": risk_src,
        "oos": oos_stats,
        "stres": stress_stats,
    }
    report_dir = settings.path("rapor_klasoru")
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_outputs(settings, result, grid, times, rs, folds, fold_rows, final_top, mc_table,
                   market_profile(arkm_1h), curve, report_dir)
    settings.path("parametre_dosyasi").write_text(json.dumps(result, indent=2, ensure_ascii=False),
                                                  encoding="utf-8")
    return result


def _tr(x: float, d: int = 2) -> str:
    """Turkce sayi bicimi: binlik ayirici nokta, ondalik ayirici virgul."""
    return f"{x:,.{d}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(x: float) -> str:
    return "%" + _tr(x * 100)


def _write_outputs(settings, result, grid, times, rs, folds, fold_rows, final_top, mc_table,
                   profile, curve, report_dir: Path) -> None:
    rows = []
    for p, t, r in zip(grid, times, rs):
        st = trade_stats_from_r(r)
        rows.append({**p.to_dict(), **st})
    pd.DataFrame(rows).to_csv(report_dir / "izgara_tum_gecmis.csv", index=False)
    curve.to_csv(report_dir / "oos_sermaye_egrisi.csv", header=["sermaye"])
    (report_dir / "piyasa_profili.json").write_text(json.dumps(profile, indent=2, ensure_ascii=False),
                                                     encoding="utf-8")

    o, s = result["oos"], result["stres"]
    L = []
    L.append(f"# {settings.sembol} Arastirma Raporu\n")
    L.append(f"Olusturma: {result['olusturma']} | Veri sonu: {result['veri_bitis']}\n")
    L.append("## 1. Veri ve piyasa profili (tum gecmis)\n")
    L.append("| Olcut | Deger |\n|---|---|")
    L.append(f"| Donem | {profile['baslangic']} - {profile['bitis']} |")
    L.append(f"| 1 saatlik mum sayisi | {profile['mum_sayisi_1h']} |")
    L.append(f"| Ilk acilis / son kapanis (USDT) | {_tr(profile['ilk_acilis'], 4)} / {_tr(profile['son_kapanis'], 4)} |")
    L.append(f"| Zirve (USDT) | {_tr(profile['zirve'], 4)} ({profile['zirve_zamani']}) |")
    L.append(f"| Dip (USDT) | {_tr(profile['dip'], 4)} ({profile['dip_zamani']}) |")
    L.append(f"| Al-tut getirisi | {_pct(profile['al_tut_getiri'])} |")
    L.append(f"| En buyuk dusus (kapanis) | {_pct(profile['maks_dusus_kapanis'])} |")
    L.append(f"| Yillik oynaklik (gunluk log getiri) | {_pct(profile['yillik_oynaklik'])} |")
    L.append(f"| Ortalama gunluk fiyat araligi | %{_tr(profile['ortalama_gunluk_aralik_yuzde'])} |")
    L.append(f"| En iyi / en kotu gun | %{_tr(profile['en_iyi_gun_yuzde'])} / %{_tr(profile['en_kotu_gun_yuzde'])} |\n")
    L.append("## 2. Walk-forward pencereleri\n")
    L.append(f"Egitim {settings.egitim_gun} gun, test {settings.test_gun} gun, "
             f"{len(grid)} kombinasyon, secim olcutu: komsuluk ortalamali SQN >= {_tr(settings.min_skor)}.\n")
    L.append("| Egitim | Test | Secim | Egitim skoru | Test islem | Test getirisi |\n|---|---|---|---|---|---|")
    for row in fold_rows:
        prm = row["parametre"]
        desc = "islem yok" if prm is None else _describe(prm)
        sc = row.get("egitim_skoru")
        sc_s = "-" if sc is None or (isinstance(sc, float) and math.isnan(sc)) else _tr(sc)
        L.append(f"| {row['egitim']} | {row['test']} | {desc} | {sc_s} | {row['islem']} | {_pct(row['getiri'])} |")
    L.append("\n## 3. Ornek disi (out-of-sample) birlesik sonuc\n")
    L.append("| Olcut | Robot | Stres (2x maliyet) |\n|---|---|---|")
    for k, name in [("toplam_getiri", "Toplam getiri"), ("yillik_getiri", "Yillik getiri"),
                    ("maks_dusus", "En buyuk dusus")]:
        L.append(f"| {name} | {_pct(o[k])} | {_pct(s[k])} |")
    L.append(f"| Sharpe (yillik) | {_tr(o['sharpe'])} | {_tr(s['sharpe'])} |")
    L.append(f"| Islem sayisi | {o['islem']} | {s['islem']} |")
    L.append(f"| Kazanma orani | {_pct(o['kazanma_orani'])} | {_pct(s['kazanma_orani'])} |")
    L.append(f"| Kar faktoru | {_tr(o['kar_faktoru'])} | {_tr(s['kar_faktoru'])} |")
    L.append(f"| Ortalama R | {_tr(o['ort_R'], 3)} | {_tr(s['ort_R'], 3)} |")
    L.append(f"| SQN | {_tr(o['sqn'])} | {_tr(s['sqn'])} |")
    L.append(f"\nAyni donemde al-tut getirisi: {_pct(o['al_tut_getiri'])}, "
             f"al-tut en buyuk dusus: {_pct(o['al_tut_maks_dusus'])}.\n")
    L.append("## 4. Monte Carlo risk boyutlandirma\n")
    if mc_table:
        L.append(f"Hedef: %95 olasilikla dusus <= {_pct(settings.hedef_dusus_p95)}. "
                 "Islem getirisi = risk orani x R varsayilir.\n")
        L.append("| Islem basina risk | %95 dusus | Medyan getiri |\n|---|---|---|")
        for m in mc_table:
            L.append(f"| {_pct(m['risk'])} | {_pct(m['dusus_p95'])} | {_pct(m['medyan_getiri'])} |")
    else:
        L.append("Ornek disi islem olmadigi icin Monte Carlo yapilamadi.")
    L.append(f"\nSecilen risk orani: {_pct(result['risk_orani'])} (kaynak: {result['risk_kaynagi']}).\n")
    L.append("## 5. Canli robot icin karar\n")
    if result["islem_acik"]:
        L.append(f"Islem ACIK. Parametreler: {_describe(result['params'])}\n")
    else:
        L.append("Islem KAPALI. Robot nakitte bekler ve periyodik olarak arastirmayi yeniler.\n")
        for r in result["kapali_nedeni"]:
            L.append(f"- {r}")
    L.append("\n### Son egitim penceresinde ilk 10 kombinasyon\n")
    L.append("| # | Parametre | Ham SQN | Komsuluk ort. |\n|---|---|---|---|")
    for k, (i, raw, sm) in enumerate(final_top, 1):
        L.append(f"| {k} | {_describe(grid[i].to_dict())} | {_tr(raw)} | {_tr(sm)} |")
    L.append("\n## 6. Sinirlar\n")
    L.append("- Gecmis performans gelecegi garanti etmez. Walk-forward yalnizca secim yonteminin "
             "gorulmemis veride nasil davrandigini olcer.")
    L.append("- Backtest, mum ici fiyat sirasini bilmez; ayni mumda stop ve hedef varsa stop kabul edilir.")
    L.append("- Emir defteri derinligi ve buyuk emirlerin fiyat etkisi modellenmez; kayma payi sabit kabul edilir.")
    (report_dir / "arastirma_raporu.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def trade_stats_from_r(r: np.ndarray) -> dict:
    if len(r) == 0:
        return {"islem": 0, "ort_R": 0.0, "toplam_R": 0.0, "kazanma_orani": 0.0}
    return {"islem": int(len(r)), "ort_R": float(r.mean()), "toplam_R": float(r.sum()),
            "kazanma_orani": float((r > 0).mean())}


def _describe(p: dict) -> str:
    if p is None:
        return "-"
    if p["module"] == "trend":
        core = f"trend D{p['donchian']} EMA{p['ema_fast']}/{p['ema_slow']} ADX>={p['adx_min']:g}"
    else:
        core = f"mr RSI<{p['rsi_max']:g} BB{p['bb_std']:g} ADX<{p['adx_max']:g}"
    tp = "TP yok" if p["tp_fraction"] == 0 else f"TP {p['tp_atr']:g}ATR x{p['tp_fraction']:g}"
    btc = "BTC filtre" if p["btc_filter"] else "BTC filtresiz"
    return f"{p['timeframe']} {core}, SL {p['sl_atr']:g}ATR, {tp}, iz {p['trail_atr']:g}ATR, {btc}"
