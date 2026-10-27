"""Arastirma hattinin uctan uca calismasi (YAPAY veriyle; performans iddiasi degildir)."""
import json

import numpy as np
import pandas as pd
import pytest

from arkmbot.config import load_settings
from arkmbot.data import resample
from arkmbot.research import (make_folds, monte_carlo_risk, run_research, score_trades,
                              select_params)
from arkmbot.strategy import Params, build_grid, neighbors

from .conftest import synthetic_1h


def test_resample_4h_aligned_and_complete():
    df = synthetic_1h(4 * 10 + 2, seed=3)          # 42 saat -> 10 tam 4h mum
    out = resample(df, "4h")
    assert len(out) == 10
    assert all(t.hour % 4 == 0 for t in out.index)
    first = df.iloc[:4]
    assert out["open"].iloc[0] == first["open"].iloc[0]
    assert out["high"].iloc[0] == first["high"].max()
    assert out["low"].iloc[0] == first["low"].min()
    assert out["close"].iloc[0] == first["close"].iloc[-1]
    assert out["volume"].iloc[0] == pytest.approx(first["volume"].sum())


def test_grid_and_neighbors_are_consistent():
    grid = build_grid(["1h", "4h"])
    assert len(grid) == len({p.key() for p in grid})          # tekrar yok
    nb = neighbors(grid)
    for i, js in enumerate(nb):
        for j in js:
            assert i in nb[j]                                   # simetrik
            a, b = grid[i].to_dict(), grid[j].to_dict()
            assert a["module"] == b["module"] and a["timeframe"] == b["timeframe"]


def test_score_requires_positive_edge():
    assert score_trades(np.array([1.0, -1.0] * 5), 8) is None        # ortalama 0
    assert score_trades(np.array([2.0, -1.0] * 2), 8) is None        # az islem
    s = score_trades(np.array([2.0, -1.0] * 5), 8)
    r = np.array([2.0, -1.0] * 5)
    assert s == pytest.approx(r.mean() / r.std(ddof=1) * np.sqrt(10))


def test_select_params_prefers_plateau():
    # 3x3 kafes: sl_atr x trail_atr. (0,0) tek basina en yuksek SQN'e sahip ama komsulari kotu;
    # (2,2), (2,1), (1,2) birbirine komsu ve iyi -> plato (2,2) secilmeli.
    sls, trails = (1.5, 2.0, 3.0), (2.0, 3.0, 4.0)
    grid = [Params(sl_atr=s, tp_atr=0.0, tp_fraction=0.0, trail_atr=tr) for s in sls for tr in trails]
    pos = {(a, b): a * 3 + b for a in range(3) for b in range(3)}
    nb = neighbors(grid)
    t = np.arange(10, dtype=np.int64)
    good = np.array([2.0, -1.0] * 5)        # SQN = 1,0
    spike = np.array([5.0, -1.0] * 5)       # SQN = 2,0
    bad = np.array([-1.0] * 10)             # uygun degil
    rs = [bad] * 9
    rs[pos[(0, 0)]] = spike
    for k in [(2, 2), (2, 1), (1, 2)]:
        rs[pos[k]] = good
    best, smooth, _ = select_params(grid, nb, [t] * 9, [t + 1] * 9, rs, 0, 100, 8, 0.0)
    assert best == pos[(2, 2)]
    assert smooth == pytest.approx(1.0)
    # (0,0)'in duzeltilmis puani: (2 - 1 - 1) / 3 = 0
    best_none, _, _ = select_params(grid, nb, [t] * 9, [t + 1] * 9, rs, 0, 100, 8, 1.5)
    assert best_none is None                # esik asilmazsa islem yok
    # Pencere sonundan sonra kapanan islemler sayilmaz -> islem sayisi yetersiz, secim yok
    late_exit = [t + 1000] * 9
    best_late, _, _ = select_params(grid, nb, [t] * 9, late_exit, rs, 0, 100, 8, 0.0)
    assert best_late is None


def test_monte_carlo_risk_monotone():
    r = np.array([2.0, -1.0, -1.0, 1.5, -1.0, 3.0, -1.0, 0.5] * 5)
    chosen, table = monte_carlo_risk(r, 0.20, n_sims=2000)
    dds = [m["dusus_p95"] for m in table]
    assert all(b >= a - 1e-9 for a, b in zip(dds, dds[1:]))
    assert chosen is None or next(m for m in table if m["risk"] == chosen)["dusus_p95"] <= 0.20


def test_make_folds_cover_period_without_overlap():
    first = pd.Timestamp("2023-07-18", tz="UTC")
    last = pd.Timestamp("2026-10-27", tz="UTC")
    folds = make_folds(first, last, 240, 60)
    assert folds[0].train_end - folds[0].train_start == pd.Timedelta(days=240)
    for a, b in zip(folds, folds[1:]):
        assert b.train_end == a.test_end                       # test pencereleri bitisik
    assert folds[-1].test_end == last


def test_run_research_end_to_end(tmp_path):
    n = 24 * 420
    veri = tmp_path / "veri"
    veri.mkdir()
    synthetic_1h(n, seed=11).to_csv(veri / "ARKMUSDT_1h.csv", index=False)
    synthetic_1h(n, seed=12, price=30000, vol=0.006).to_csv(veri / "BTCUSDT_1h.csv", index=False)
    (tmp_path / "ayarlar.json").write_text(json.dumps({
        "zaman_dilimleri": ["4h"], "egitim_gun": 150, "test_gun": 60, "min_islem_sayisi": 5,
        "min_skor": 0.0}), encoding="utf-8")
    s = load_settings(tmp_path / "ayarlar.json")
    res = run_research(s, workers=1)
    assert (tmp_path / "parametreler.json").exists()
    assert (tmp_path / "rapor" / "arastirma_raporu.md").exists()
    saved = json.loads((tmp_path / "parametreler.json").read_text(encoding="utf-8"))
    assert saved["islem_acik"] == res["islem_acik"]
    assert 0 < saved["risk_orani"] <= 0.02
    curve = pd.read_csv(tmp_path / "rapor" / "oos_sermaye_egrisi.csv", index_col=0)
    assert curve["sermaye"].iloc[0] == pytest.approx(s.baslangic_sermaye)
    assert np.isfinite(curve["sermaye"]).all()
    # birlesik egri sonu = baslangic x katlanmis test pencere getirileri
    assert res["oos"]["toplam_getiri"] == pytest.approx(curve["sermaye"].iloc[-1] / curve["sermaye"].iloc[0] - 1)
