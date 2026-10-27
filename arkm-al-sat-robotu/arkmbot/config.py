"""Ayar dosyasi (ayarlar.json) okuma.

Tum ayarlarin varsayilan degerleri burada tanimlidir; ayarlar.json yalnizca
degistirilmek istenen alanlari icerebilir. Bilinmeyen bir anahtar hata verir,
boylece yazim hatasi sessizce yok sayilmaz.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


@dataclass
class Settings:
    # Piyasa
    sembol: str = "ARKMUSDT"
    btc_sembol: str = "BTCUSDT"
    api_adresi: str = "https://api.binance.com"
    # Yalnizca herkese acik piyasa verisi icin (bolge kisitlamasi olan yerlerde de calisir)
    veri_adresi: str = "https://data-api.binance.vision"
    testnet_adresi: str = "https://testnet.binance.vision"
    # ARKM Binance spot islem baslangici: 18 Temmuz 2023
    baslangic_tarihi: str = "2023-07-18"

    # Maliyetler (Binance spot VIP0 standart komisyon %0,1; BNB ile odemede %0,075)
    ucret_orani: float = 0.001
    kayma_orani: float = 0.0005

    # Sermaye ve risk
    baslangic_sermaye: float = 1000.0      # backtest icin sanal sermaye (USDT)
    sermaye_limiti_usdt: float = 100.0     # canli/paper modda robotun kullanabilecegi azami USDT
    maks_pozisyon_orani: float = 0.95      # sermayenin tek islemde kullanilabilecek azami orani
    islem_risk_orani: float | None = None  # None ise arastirma (Monte Carlo) belirler
    varsayilan_risk_orani: float = 0.005   # yeterli veri yoksa kullanilan temkinli risk
    hedef_dusus_p95: float = 0.20          # Monte Carlo %95 dusus hedefi
    gunluk_zarar_limiti: float = 0.05      # gunluk %5 kayipta yeni islem acilmaz
    maks_dusus_limiti: float = 0.25        # zirveden %25 dususte robot yeni islem acmayi durdurur
    zarar_sonrasi_bekleme_bar: int = 3     # zarar kes sonrasi bekleme (bar)
    min_islem_tutari: float = 5.0          # Binance NOTIONAL filtresine yakin alt sinir (USDT)
    maks_spread_orani: float = 0.003       # alis-satis farki %0,3'u asarsa piyasa emri verilmez

    # Token kilit acilimi gibi riskli tarihler (YYYY-MM-DD). Bu tarihlerin
    # oncesinde ve sonrasinda 'kilit_acilim_bekleme_saat' boyunca yeni islem acilmaz.
    kilit_acilim_tarihleri: list[str] = field(default_factory=list)
    kilit_acilim_bekleme_saat: int = 48

    # Arastirma (walk-forward)
    egitim_gun: int = 240
    test_gun: int = 60
    min_islem_sayisi: int = 8
    min_skor: float = 1.0
    zaman_dilimleri: list[str] = field(default_factory=lambda: ["1h", "4h"])
    paralel_islem: int = 0                 # 0 = islemci sayisi kadar
    # Canli robot, parametreler 'test_gun' gunden eskiyse (ve pozisyon yoksa) arastirmayi
    # yeniler; boylece canli davranis walk-forward testindeki yeniden secim sikligiyla aynidir.

    # Canli dongu
    kontrol_saniye: int = 15
    stop_limit_tamponu: float = 0.01       # STOP_LOSS_LIMIT icin limit fiyat tamponu

    # Dosya yollari (calisma klasorune gore)
    veri_klasoru: str = "veri"
    rapor_klasoru: str = "rapor"
    kayit_klasoru: str = "kayitlar"
    parametre_dosyasi: str = "parametreler.json"
    durum_dosyasi: str = "durum.json"

    @property
    def base_dir(self) -> Path:
        return Path(getattr(self, "_base_dir", "."))

    def path(self, name: str) -> Path:
        p = Path(getattr(self, name))
        return p if p.is_absolute() else self.base_dir / p

    def to_dict(self) -> dict:
        return asdict(self)


def load_settings(path: str | Path | None = None) -> Settings:
    settings = Settings()
    base = Path(".")
    if path is not None:
        path = Path(path)
        base = path.parent
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            known = {f.name for f in fields(Settings)}
            unknown = [k for k in data if k not in known and not k.startswith("_")]
            if unknown:
                raise ValueError(f"Bilinmeyen ayar anahtari: {', '.join(unknown)}")
            for k, v in data.items():
                if not k.startswith("_"):
                    setattr(settings, k, v)
    object.__setattr__(settings, "_base_dir", str(base))
    _validate(settings)
    return settings


def _validate(s: Settings) -> None:
    checks = [
        (0 <= s.ucret_orani < 0.01, "ucret_orani 0 ile 0.01 arasinda olmali"),
        (0 <= s.kayma_orani < 0.05, "kayma_orani 0 ile 0.05 arasinda olmali"),
        (0 < s.maks_pozisyon_orani <= 1, "maks_pozisyon_orani 0 ile 1 arasinda olmali"),
        (s.islem_risk_orani is None or 0 < s.islem_risk_orani <= 0.05,
         "islem_risk_orani 0 ile 0.05 arasinda olmali"),
        (0 < s.gunluk_zarar_limiti < 1, "gunluk_zarar_limiti 0 ile 1 arasinda olmali"),
        (0 < s.maks_dusus_limiti < 1, "maks_dusus_limiti 0 ile 1 arasinda olmali"),
        (s.egitim_gun > 0 and s.test_gun > 0, "egitim_gun ve test_gun pozitif olmali"),
        (all(tf in ("1h", "4h") for tf in s.zaman_dilimleri), "zaman_dilimleri yalnizca 1h/4h"),
        (s.sermaye_limiti_usdt > 0, "sermaye_limiti_usdt pozitif olmali"),
    ]
    for ok, msg in checks:
        if not ok:
            raise ValueError(msg)
