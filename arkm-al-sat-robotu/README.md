# ARKM Al-Sat Robotu (Binance Spot)

ARKM/USDT paritesinde Binance spot piyasasında **kendi kendine araştırma yapan, parametrelerini ve zarar kes / kar al seviyelerini ARKM'nin tüm geçmişinden kendisi belirleyen ve otomatik al-sat yapan** bir robot.

> **Risk uyarısı.** Kripto para işlemleri sermayenin tamamını kaybetme riski taşır. ARKM, zirvesinden %97'nin üzerinde değer kaybetmiş, oynaklığı çok yüksek bir varlıktır. Bu robot kar garantisi vermez; geçmiş performans geleceği göstermez. Robot, geçmişte üstünlüğü gösterilemeyen durumlarda **işlem açmamak** üzere tasarlanmıştır. Kullanmadan önce mutlaka paper (sanal) modda deneyin ve yalnızca kaybetmeyi göze alabileceğiniz bir tutarla başlayın.

> **Bu sürüm hakkında.** Robot hazırlanırken çalışma ortamından Binance'e ağ erişimi engelliydi. Bu nedenle **gerçek ARKM verisiyle backtest sonucu bu depoda yoktur**; uydurma bir performans rakamı verilmemiştir. Kod, elle hesaplanmış senaryolar ve yapay veriyle 50 testte doğrulanmıştır. Gerçek araştırma, `arastir` komutunu kendi bilgisayarınızda çalıştırdığınızda ARKM'nin tüm geçmişi indirilerek yapılır.

Tasarımın ayrıntılı gerekçesi, ARKM hakkındaki kaynaklı bilgiler ve sahadaki robotlardan alınan uygulamalar için: **[ARASTIRMA.md](ARASTIRMA.md)**

---

## Robot ne yapar?

```
 indir      ARKMUSDT + BTCUSDT 1 saatlik mumlar (18.07.2023'ten bugune)
   |
 arastir    2.880 parametre kombinasyonu x walk-forward (240 gun egitim / 60 gun test)
   |        -> plato secimi (SQN), stres testi, Monte Carlo risk orani
   |        -> parametreler.json + rapor/arastirma_raporu.md
   |
 calistir   her mum kapanisinda: sinyal -> risk kontrolleri -> piyasa emriyle alis
            -> Binance'te bekleyen STOP emri -> iz suren stop / kar al
            -> 60 gunde bir arastirmayi kendiliginden yeniler
```

| Özellik | Açıklama |
|---|---|
| İki strateji modülü | Trend takibi (Donchian kırılımı + EMA + ADX) ve ortalamaya dönüş (Bollinger + RSI + düşük ADX). Hangisinin kullanılacağını veya hiç işlem yapılmayacağını araştırma seçer. |
| BTC filtresi | BTC kendi EMA200'ünün altındaysa işlem açmama seçeneği; kullanılıp kullanılmayacağını araştırma seçer. |
| Zarar kes | ATR tabanlı ilk stop (1,5 / 2 / 3 × ATR), **Binance'te bekleyen gerçek stop emri** olarak yerleştirilir. İnternet kesilse de geçerlidir. |
| Kar al | Sabit hedef yok / 2 × ATR / 4 × ATR; kısmi (%50) veya tam satış. Kısmi satıştan sonra stop başabaşa çekilir. |
| İz süren stop | En yüksek fiyat − (2 / 3 / 4 × ATR); yalnızca yukarı hareket eder. |
| Risk boyutu | İşlem başına sermayenin %0,25–%2'si; Monte Carlo ile "%95 olasılıkla düşüş ≤ %20" hedefine göre seçilir. |
| Koruma katmanları | Günlük zarar limiti, zirveden maksimum düşüşte durma, zarar sonrası bekleme, alış-satış farkı kontrolü, bayat sinyal kontrolü, kilit açılımı tarih yasağı. |
| Kendi parasına dokunma | Robot yalnızca kendi aldığı ARKM miktarını yönetir ve en fazla `sermaye_limiti_usdt` kadar USDT kullanır. |

---

## Kurulum

Python 3.10 veya üstü gerekir.

```bash
cd arkm-al-sat-robotu
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q                # 50 test gecmeli
```

## Kullanım adımları

### 1. Veriyi indirin

```bash
python -m arkmbot indir
```

ARKM'nin işlem başladığı 18 Temmuz 2023'ten bugüne tüm 1 saatlik mumlar `veri/` klasörüne yazılır (yaklaşık 28.000 mum). Sonraki çalıştırmalarda yalnızca yeni mumlar eklenir.

### 2. Robotun araştırma yapmasını sağlayın

```bash
python -m arkmbot arastir
```

Çıktılar:

| Dosya | İçerik |
|---|---|
| `rapor/arastirma_raporu.md` | Piyasa profili, her walk-forward penceresinde seçilen parametreler, örnek dışı sonuç, al-tut karşılaştırması, stres testi, Monte Carlo tablosu, canlı karar |
| `parametreler.json` | Canlı robotun kullanacağı parametreler ve risk oranı; `islem_acik` alanı |
| `rapor/izgara_tum_gecmis.csv` | 2.880 kombinasyonun tüm geçmişteki sonuçları |
| `rapor/oos_sermaye_egrisi.csv` | Örnek dışı sermaye eğrisi |
| `rapor/piyasa_profili.json` | Saat ve gün bazında ortalama getiri dahil istatistikler |

**Raporu mutlaka okuyun.** `islem_acik: false` çıkarsa robot, ARKM geçmişinde bu yöntemle kalıcı bir üstünlük bulamamıştır ve para riske etmez.

### 3. (İsteğe bağlı) Seçilen parametrelerle tüm geçmiş backtest

```bash
python -m arkmbot backtest
```

Bu test parametrelerin seçildiği veriyi de içerir (örnek içi). Gerçekçi beklenti için rapordaki walk-forward sonucunu esas alın.

### 4. Paper (sanal) modda çalıştırın — en az 2–4 hafta önerilir

```bash
python -m arkmbot calistir
```

Gerçek Binance fiyatlarıyla, sanal bakiyeyle işlem yapar. API anahtarı gerekmez. İşlemler `kayitlar/islemler.csv`, günlük `kayitlar/bot.log` dosyasına yazılır.

### 5. (İsteğe bağlı) Binance Spot Testnet

```bash
python -m arkmbot calistir --testnet
```

testnet.binance.vision için ayrı API anahtarı gerekir. Testnet fiyatları gerçek piyasadan farklıdır; bu mod yalnızca emir akışını denemek içindir.

### 6. Binance hesabınıza bağlama

**a) API anahtarı oluşturun** (binance.com, web sitesi)
1. Profil simgesi → **Hesap** → **API Yönetimi** → **API Oluştur**.
2. Anahtar türü olarak **Sistem tarafından oluşturulan (System generated)** seçeneğini seçin. Robot bu türün kullandığı HMAC imzasını kullanır.
3. Bir ad verin (ör. `arkm-robot`) ve güvenlik doğrulamasını (2FA) tamamlayın.
4. Ekranda görünen **API Key** ve **Secret Key** değerlerini hemen kopyalayın. Gizli anahtar yalnızca bir kez gösterilir.
5. **Kısıtlamaları düzenle** bölümünde:
   - ✅ Enable Reading (okuma)
   - ✅ Enable Spot & Margin Trading (spot işlem)
   - ❌ **Enable Withdrawals (para çekme): asla açmayın**
   - ✅ **Restrict access to trusted IPs only**: robotu çalıştıracağınız bilgisayarın veya sunucunun IP adresini yazın.

**b) Anahtarları robota verin**

```bash
cp .env.example .env               # Windows: copy .env.example .env
```

`.env` dosyasını bir metin düzenleyiciyle açıp anahtarları yazın (tırnak ve boşluk olmadan):

```
BINANCE_API_KEY=buraya_api_key
BINANCE_API_SECRET=buraya_secret_key
```

`.env` dosyasını kimseyle paylaşmayın; `.gitignore` içinde olduğu için GitHub'a gönderilmez.

**c) Spot cüzdana USDT koyun.** Robot yalnızca **Spot** cüzdandaki USDT'yi kullanır. USDT'niz Fonlama (Funding) cüzdanındaysa Binance'te **Cüzdan → Transfer** ile Spot'a aktarın. Robotun kullanacağı azami tutarı `ayarlar.json` içindeki `sermaye_limiti_usdt` belirler (varsayılan 100).

**d) Bağlantıyı test edin.** Bu komut hiçbir emir göndermez:

```bash
python -m arkmbot baglanti
```

Komut sunucu saati farkını, hesabın işlem iznini ve anahtarın izinlerini kontrol eder. Para çekme izni açıksa **TEHLİKE** uyarısı verir. Ayrıca IP kısıtlamasını, Spot USDT bakiyesini ve ARKMUSDT için en küçük işlem tutarını gösterir. "Bağlantı hazır" yazmadan canlı moda geçmeyin.

**e) Canlı modu başlatın**

```bash
python -m arkmbot calistir --canli --onayliyorum
```

Robot işlem açtığında Binance'te **Emirler → Açık Emirler** altında ARKMUSDT için bekleyen bir **Stop** satış emri görürsünüz. Bu emir robotun zarar kes emridir; elle iptal etmeyin.

**Not:** Robot Binance global (binance.com) spot API'si içindir. Binance TR farklı bir platform ve API kullanır; desteklenmez. Bulunduğunuz yerden api.binance.com'a erişilemiyorsa `baglanti` komutu hata verir.

### Diğer komutlar

```bash
python -m arkmbot baglanti         # API anahtari, izin ve bakiye kontrolu (emir vermez)
python -m arkmbot durum            # acik pozisyon, nakit, durdurma durumu
python -m arkmbot devam            # maksimum dusus nedeniyle durdurulan robotu yeniden ac
```

---

## Ayarlar (`ayarlar.json`)

Yalnızca değiştirmek istediğiniz alanları yazmanız yeterlidir; diğerleri varsayılan değerleri alır. Tüm alanlar `arkmbot/config.py` içinde açıklanmıştır.

| Ayar | Varsayılan | Açıklama |
|---|---|---|
| `sermaye_limiti_usdt` | 100 | Robotun kullanabileceği azami USDT |
| `ucret_orani` | 0,001 | İşlem komisyonu (BNB ile ödüyorsanız 0,00075) |
| `kayma_orani` | 0,0005 | Backtestte her işleme eklenen kayma payı |
| `islem_risk_orani` | null | Boş bırakılırsa Monte Carlo belirler; elle de verilebilir (azami 0,05) |
| `hedef_dusus_p95` | 0,20 | Monte Carlo düşüş hedefi |
| `gunluk_zarar_limiti` | 0,05 | Gün içinde %5 kayıpta yeni işlem açılmaz |
| `maks_dusus_limiti` | 0,25 | Zirveden %25 düşüşte robot yeni işlem açmayı durdurur (açık pozisyonun stopu çalışmaya devam eder) |
| `zarar_sonrasi_bekleme_bar` | 3 | Zararlı işlemden sonra beklenecek mum sayısı |
| `maks_spread_orani` | 0,003 | Alış-satış farkı %0,3'ü aşarsa piyasa emri verilmez |
| `kilit_acilim_tarihleri` | [] | `["2026-11-18"]` biçiminde; bu tarihlerin çevresinde işlem açılmaz |
| `kilit_acilim_bekleme_saat` | 48 | Kilit açılımı öncesi ve sonrası yasak süre |
| `egitim_gun` / `test_gun` | 240 / 60 | Walk-forward pencereleri; canlı robot da araştırmayı `test_gun` günde bir yeniler |
| `min_islem_sayisi` / `min_skor` | 8 / 1,0 | Parametre setinin seçilebilmesi için alt sınırlar |
| `zaman_dilimleri` | ["1h", "4h"] | Araştırmada denenen zaman dilimleri |

---

## 7/24 çalıştırma

Robot her saat başı mum kapanışında karar verir; bilgisayarın açık ve internete bağlı olması gerekir. Koruyucu stop Binance'te beklediği için bağlantı kopsa da zarar kes geçerli kalır, ancak iz süren stop ve kar al güncellemeleri yapılamaz.

Linux sunucuda örnek (systemd):

```ini
# /etc/systemd/system/arkmbot.service
[Unit]
Description=ARKM al-sat robotu
After=network-online.target

[Service]
WorkingDirectory=/home/kullanici/arkm-al-sat-robotu
ExecStart=/home/kullanici/arkm-al-sat-robotu/.venv/bin/python -m arkmbot calistir
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

Canlı modda `ExecStart` satırına `--canli --onayliyorum` ekleyin. Robot yeniden başladığında `durum.json` dosyasından açık pozisyonu okur, Binance'teki stop emrini kontrol eder ve eksikse yeniden yerleştirir.

---

## Dosya yapısı

```
arkm-al-sat-robotu/
├── ARASTIRMA.md            tasarim gerekcesi, kaynakli ARKM bilgileri
├── ayarlar.json            kullanici ayarlari
├── arkmbot/
│   ├── binance_client.py   imzali REST istemcisi, borsa filtreleri (LOT_SIZE, PRICE_FILTER, NOTIONAL)
│   ├── data.py             mum indirme, onbellek, 4h donusumu, piyasa profili
│   ├── indicators.py       EMA, RSI, ATR, ADX, Bollinger, Donchian (Wilder tanimlari)
│   ├── strategy.py         strateji modulleri, parametre izgarasi, komsuluk
│   ├── trade_manager.py    zarar kes / kar al / iz suren stop (backtest ve canli ortak)
│   ├── backtest.py         olay tabanli backtest ve olcutler
│   ├── research.py         walk-forward, plato secimi, stres testi, Monte Carlo, rapor
│   ├── broker.py           canli Binance ve paper emir katmani
│   ├── bot.py              canli dongu, risk korumalari, durum kaydi
│   └── __main__.py         komut satiri
└── tests/                  50 test (elle hesaplanmis senaryolar dahil)
```

## Bilinen sınırlamalar

- Backtest mum içi fiyat sırasını bilmez; aynı mumda hem stop hem hedef varsa stop varsayılır (temkinli).
- Emir defteri derinliği modellenmez; kayma payı sabittir. Büyük tutarlarda gerçek kayma daha yüksek olabilir.
- Borsadaki stop emri dolduğunda Binance'in emir sorgusu komisyon bilgisi vermez; robotun iç muhasebesinde komisyon ayardaki oranla tahmin edilir.
- Alış emri gönderilirken ağ hatası olursa emrin borsada gerçekleşip gerçekleşmediği bilinemez. Robot bu durumda kendini durdurur; Binance hesabınızı kontrol edip `devam` komutunu çalıştırmanız gerekir.
- Parametre ızgarası ve seçim eşikleri (SQN ≥ 1,0, en az 8 işlem, %20 düşüş hedefi) tasarım tercihleridir; `ARASTIRMA.md` içinde gerekçeleriyle açıklanmıştır ve ayarlardan değiştirilebilir.
