# ARKM Al-Sat Robotu: Araştırma Notları ve Tasarım Gerekçesi

Bu belge robotun neden bu şekilde tasarlandığını açıklar. İki tür bilgi ayrı tutulmuştur:

- **Kaynaklı bilgi:** Web kaynaklarından alınmış, kaynağı belirtilmiş veriler. Kaynaklar arasında çelişki varsa açıkça yazılmıştır.
- **Robotun kendi araştırması:** ARKM'nin tüm fiyat geçmişi üzerinde robotun `arastir` komutuyla yaptığı hesaplar. Bu sonuçlar robot çalıştırıldığında `rapor/arastirma_raporu.md` dosyasına yazılır.

> **Önemli:** Bu robotun hazırlandığı çalışma ortamından Binance sunucularına (api.binance.com, data-api.binance.vision, data.binance.vision) ağ erişimi engelliydi. Bu nedenle ARKM'nin gerçek mum verisi burada indirilemedi ve **gerçek veri üzerinde backtest sonucu bu belgede yer almıyor.** Gerçek veriyle araştırma, robotu kendi bilgisayarınızda çalıştırdığınızda otomatik olarak yapılır. Uydurma bir performans rakamı verilmemiştir.

---

## 1. ARKM hakkında kaynaklı bilgiler

| Konu | Bilgi | Kaynak |
|---|---|---|
| Proje | Arkham Intelligence, zincir üstü (on-chain) analiz platformu; token ARKM | [codex.arkm.com](https://codex.arkm.com/tokenomics) |
| Listeleme | Binance Launchpad satışıyla Temmuz 2023'te piyasaya çıktı; işlem başlangıcı 18 Temmuz 2023 | [codex.arkm.com](https://codex.arkm.com/tokenomics), [DropsTab](https://dropstab.com/coins/arkham) |
| Toplam arz | 1 milyar ARKM; planlanmış ek basım yok | [codex.arkm.com](https://codex.arkm.com/tokenomics) |
| İlk dolaşım | Toplam arzın %15'i | [codex.arkm.com](https://codex.arkm.com/tokenomics) |
| Kilit | Yatırımcı, çekirdek ekip ve danışman tokenları listelemeden sonra 1 yıl kilitli; ardından 3 yıl boyunca doğrusal açılım | [codex.arkm.com](https://codex.arkm.com/tokenomics) |
| Dağılım (kısmi) | Binance Launchpad %5, çekirdek ekip %20, yatırımcılar %17,5 | [codex.arkm.com](https://codex.arkm.com/tokenomics) |
| Ekosistem/hazine | %54,5; vakfın takdirinde, tam açılım yaklaşık Temmuz 2030 (üçüncü taraf kaynak) | [LeveX](https://levex.com/en/blog/arkm-tokenomics) |
| Tüm zamanların zirvesi | 4,002 USD, 10 Mart 2024 (CoinPaprika); 3,99 USD, 10 Mart 2024 (DropsTab) | [CoinPaprika](https://coinpaprika.com/coin/arkm-arkham), [DropsTab](https://dropstab.com/coins/arkham) |
| Tüm zamanların dibi | 0,0856 USD, 18 Ağustos 2026 (Messari); 2026 en düşük 0,085295 USD (CoinPaprika) | [Messari](https://messari.io/project/arkham), [CoinPaprika](https://coinpaprika.com/coin/arkm-arkham) |
| Yıllık aralıklar | 2023: 0,3266–0,7816; 2024: 0,4602–4,002; 2025: 0,1376–1,7627; 2026 (yılbaşından): 0,0853–0,2375 USD | [CoinPaprika](https://coinpaprika.com/coin/arkm-arkham) |
| Oynaklık | 30 günlük oynaklık %78,35; 1 yıllık performans %-84,07 (Messari anlık görüntüsü) | [Messari](https://messari.io/project/arkham) |

**Hesap kontrolü (zirveden dibe):** 0,085295 / 4,002 − 1 = −0,9787 → **%−97,87**. DropsTab rakamlarıyla (0,0854 / 3,99 − 1) sonuç %−97,86'dır. İki kaynak arasındaki fark 0,01 puandır.

### Çelişkili veya doğrulanamayan bilgiler

- **Dolaşımdaki arz:** Kaynaklar arasında büyük fark var (yaklaşık 225 milyon ile 659 milyon arası; DropsTab, CoinPaprika, CoinGecko, Tokenomist). Robot bu veriyi kullanmaz.
- **Eylül 2026 kilit açılımı:** Bazı kaynaklar yaklaşık 199 milyon ARKM'lik bir açılımdan söz ediyor ([LeveX](https://levex.com/en/blog/arkm-tokenomics), [CoinMarketCap](https://coinmarketcap.com/cmc-ai/arkham/latest-updates/)). Resmi kaynakla doğrulanamadı.
- **Temmuz 2025 açılımında %24 düşüş:** CoinMarketCap'in yapay zeka özet sayfasında geçiyor; bağımsız olarak doğrulanamadı.
- **Aylık açılım takvimi:** Resmi sayfa "doğrusal" diyor, ancak açılımın aylık mı sürekli mi olduğunu belirtmiyor.

Bu belirsizlik nedeniyle robotta kilit açılım tarihleri **varsayılan olarak boştur.** Kullanıcı tarihleri [Tokenomist](https://tokenomist.ai/arkham/unlock-events) gibi bir kaynaktan doğrulayıp `kilit_acilim_tarihleri` ayarına girerse, robot bu tarihlerin çevresinde yeni pozisyon açmaz.

### Bu bilgilerden çıkan tasarım sonuçları

1. **ARKM uzun süreli ve derin bir düşüş yaşadı** (zirveden %−97,87). Sürekli alım yapan veya düşüşte ortalama düşüren bir sistem bu dönemde büyük zarar biriktirirdi. Bu nedenle robotun **nakitte bekleyebilmesi** ve **her pozisyonda zarar kesmesi** zorunludur.
2. **Oynaklık çok yüksek** (30 günlük %78). Sabit yüzdeli stoplar ya çok dar (gereksiz stop) ya da çok geniş (büyük zarar) kalır. Bu nedenle stop ve hedefler **ATR (ortalama gerçek aralık)** ile oynaklığa göre ölçeklenir.
3. **Arz baskısı** (kilit açılımları) fiyat üzerinde ani satış baskısı yaratabilir. Bu nedenle tarih bazlı işlem yasağı seçeneği vardır.
4. **Spot hesapta açığa satış yoktur.** Düşüş dönemlerinde kazanç aramak yerine piyasa dışında kalmak tasarımın parçasıdır.

---

## 2. Sahada kullanılan robot türleri ve ARKM için değerlendirme

| Robot türü | Örnekler | Nasıl çalışır | ARKM için değerlendirme |
|---|---|---|---|
| Grid | Binance Spot Grid | Belirli fiyat aralığında kademeli al-sat | Yatay piyasada iyi çalışır. Aralığın altına düşüşte elde zararlı stok birikir. %−97,87'lik düşüş döneminde riskli olduğu için **seçilmedi.** |
| DCA / ortalama düşürme | Binance Spot DCA, 3Commas DCA | Fiyat düştükçe ek alım | Uzun düşüş trendinde zararı büyütür. Zarar kes mantığıyla çelişir. **Seçilmedi.** |
| Piyasa yapıcılığı | Hummingbot | Alış ve satış tarafına sürekli limit emir | Düşük komisyon kademesi, sürekli çalışma ve stok riski yönetimi gerektirir. Küçük sermayeli tek coin kullanımı için uygun değil. **Seçilmedi.** |
| Trend takibi | Turtle kuralları; Freqtrade trend stratejileri | Kırılımda al, iz süren stopla trendi taşı | Düşüşte işlem açmaz (trend filtresi). Yükseliş dönemlerini yakalamaya çalışır. **Seçildi (modül 1).** |
| Ortalamaya dönüş | Bollinger + RSI stratejileri | Aşırı satımda al, ortalamaya dönüşte sat | Yatay piyasada çalışır, güçlü düşüşte tehlikelidir. Bu nedenle yalnızca **düşük ADX (zayıf trend)** koşulunda ve stoplu kullanılır. **Seçildi (modül 2).** |

Robot iki modülden hangisinin kullanılacağına, hatta hiç işlem yapılmayacağına, **ARKM'nin geçmiş verisine bakarak kendisi karar verir** (bkz. bölüm 4).

### Sahadaki robotlardan alınan uygulamalar

| Uygulama | Kaynağı | Robottaki karşılığı |
|---|---|---|
| Donchian 20/55 kırılımı, ATR ("N") ile pozisyon boyutu, işlem başına sermayenin sabit bir yüzdesini riske etme | Turtle Trading kuralları (Richard Dennis ve William Eckhardt) | `donchian` ekseni 20/55; pozisyon boyutu = risk tutarı / (giriş − stop) |
| En yüksek fiyattan ATR katı kadar aşağıda iz süren stop | Chandelier Exit (Chuck LeBeau) | `trail_atr` |
| Zarar sonrası bekleme, maksimum düşüşte durma | Freqtrade "protections" (CooldownPeriod, StoplossGuard, MaxDrawdown) | `zarar_sonrasi_bekleme_bar`, `maks_dusus_limiti`, `gunluk_zarar_limiti` |
| BTC yönüne göre filtre | NostalgiaForInfinity (Freqtrade) gibi stratejilerin BTC bilgi çiftlerini kullanması ([kaynak](https://www.patreon.com/posts/89663923)) | `btc_filter`: BTC kapanışı kendi EMA200'ünün üstündeyse işlem |
| Kar al, kısmi kar al, başabaş stopa çekme | Yaygın uygulama (Freqtrade ROI/trailing ayarları vb.) | `tp_atr`, `tp_fraction`, başabaş stop |
| Parametreleri geçmişte optimize edip görülmemiş veride sınama | Walk-forward analizi (Robert Pardo) | `egitim_gun` / `test_gun` pencereleri |
| Sistem kalitesi ölçütü | SQN (Van Tharp) | Parametre seçim puanı |
| Borsa tarafında koruyucu stop emri | Profesyonel uygulama: bağlantı koparsa da stop geçerli kalır | `STOP_LOSS` / `STOP_LOSS_LIMIT` emri Binance'te bekler |

Not: Freqtrade'in popüler NostalgiaForInfinity stratejisinin 2023 tarihli bir incelemesine göre bu stratejide ROI ve stop kaybı fiilen kapalıdır ve çıkışlar satış sinyalleriyle yapılır ([kaynak](https://www.patreon.com/posts/89663923)). Bu robot bilinçli olarak farklı davranır: **her pozisyonda borsada bekleyen bir stop emri vardır.**

---

## 3. Zarar kes ve kar al seviyeleri nasıl belirlenir

Seviyeler sabit bir yüzde olarak yazılmamıştır. Robot, aşağıdaki seçenekler arasından ARKM geçmişinde en sağlam sonuç vereni **kendisi seçer**:

| Kural | Seçenekler | Açıklama |
|---|---|---|
| İlk zarar kes | 1,5 / 2 / 3 × ATR | Giriş fiyatı − katsayı × ATR(14) |
| Kar al | yok / 2 × ATR / 4 × ATR | Hedefe ulaşınca satış |
| Kar alda satılan oran | %50 veya %100 | %50 seçilirse kalan için stop başabaşa çekilir |
| İz süren stop | 2 / 3 / 4 × ATR | Girişten bu yana en yüksek fiyat − katsayı × ATR; stop yalnızca yukarı gider |
| İşlem başına risk | %0,25 – %2 | Monte Carlo ile seçilir (bölüm 4.4) |

**Başabaş fiyatı:** Kalan miktar bu fiyattan satılırsa alış ve satış komisyonu karşılanır: `giriş × (1 + komisyon) / (1 − komisyon)`. Komisyon %0,1 için: 100 × 1,001 / 0,999 = 100,2002.

**Pozisyon boyutu örneği** (testlerde doğrulanmıştır): Sermaye 1.000 USDT, risk %1 = 10 USDT, giriş 100, stop 98 → miktar = 10 / (100 − 98) = 5 adet. Maliyet 5 × 100 × 1,001 = 500,50 USDT. Stop olursa gelir 5 × 98 × 0,999 = 489,51 USDT, net zarar 10,99 USDT (−1,099 R; farkın 0,99 USDT'si komisyondur).

---

## 4. Robotun kendi araştırma yöntemi

### 4.1 Veri

- Binance'ten ARKMUSDT ve BTCUSDT 1 saatlik mumları, ARKM'nin işlem başladığı **18 Temmuz 2023'ten bugüne kadar eksiksiz** indirilir.
- 4 saatlik mumlar 1 saatlik veriden üretilir (UTC 00:00 hizalı, Binance ile aynı).
- Piyasa profili hesaplanır: zirve, dip, en büyük düşüş, yıllık oynaklık, en iyi ve en kötü gün, saat ve gün bazında ortalama getiri (`rapor/piyasa_profili.json`).

### 4.2 Parametre ızgarası

2 zaman dilimi × 2 BTC filtresi × 2 modül × 8 giriş varyantı × 45 çıkış varyantı = **2.880 kombinasyon**. Eksenler bilerek dar tutulmuştur, çünkü geniş ızgara aşırı uyum riskini artırır.

### 4.3 Walk-forward seçimi (aşırı uyum önlemleri)

1. Geçmiş, 240 günlük eğitim ve 60 günlük test pencerelerine bölünür. Pencereler 60 gün kayar.
2. Her eğitim penceresinde her kombinasyonun işlemleri **SQN** ile puanlanır. Uygunluk şartları: en az 8 işlem, ortalama R > 0, kar faktörü > 1. Yalnızca pencere içinde açılıp pencere bitmeden kapanan işlemler sayılır; böylece test dönemi fiyatları eğitim puanına sızmaz.
3. **Plato seçimi:** Bir kombinasyonun puanı, kendisi ve tek parametresi bir adım farklı komşularının ortalamasıdır. Komşuları kötü olan "şanslı tepe" elenir.
4. Düzeltilmiş puan 1,0'ın altındaysa o dönemde **işlem yapılmaz.**
5. Seçilen parametreler yalnızca bir sonraki, **hiç görülmemiş** 60 günlük pencerede işlem yapar. Sermaye pencereden pencereye taşınır.
6. Test pencerelerinin birleşimi yöntemin **örnek dışı** sonucudur. Al-tut ile karşılaştırılır.
7. **Stres testi:** Komisyon ve kayma payı iki katına çıkarılarak tekrar edilir.

### 4.4 Monte Carlo ile risk oranı

Örnek dışı işlemlerin R değerleri 5.000 kez yeniden örneklenir. %95 olasılıkla düşüşü %20'yi aşmayan en büyük işlem başına risk oranı seçilir (aday aralık %0,25–%2). Örnek dışı işlem sayısı 20'den azsa temkinli varsayılan %0,5 kullanılır. En küçük aday (%0,25) bile hedefi aşıyorsa en küçük aday kullanılır ve raporda belirtilir.

### 4.5 Canlı işlem kararı

- Son 240 günde eşiği geçen sağlam bir parametre seti yoksa, **veya**
- walk-forward örnek dışı sonucu pozitif değilse (toplam R ≤ 0 veya kar faktörü ≤ 1),

robot **işlem açmaz**, nakitte bekler ve 60 günde bir araştırmayı yeniler. Bu, "geçmişte üstünlüğü gösterilemeyen bir sistemle para riske edilmez" ilkesidir.

---

## 5. Backtest varsayımları (temkinli yönde)

| Varsayım | Değer |
|---|---|
| Komisyon | Her alım ve satımda %0,1 (Binance spot VIP0 standart oranı; BNB ile ödemede %0,075). [Kaynak](https://coinspot.io/en/analysis/binance-fees-2025-the-ultimate-guide/), [Binance.US tablosu](https://support.binance.us/en/articles/9843536-binance-us-launches-trading-fee-discount-and-vip-program-with-bnb) |
| Kayma payı | Her işlemde %0,05 (ayarlanabilir) |
| Giriş zamanı | Sinyal mumunun kapanışından sonraki mumun açılışı (ileriye bakma yok) |
| Aynı mumda stop ve hedef | Önce stop gerçekleşmiş kabul edilir |
| Boşluklu açılış | Mum stopun altında açılırsa dolum açılış fiyatından olur |
| Stop güncellemesi | Mum kapanışında hesaplanır, bir sonraki mumdan itibaren geçerlidir |

Komisyon oranları kaynaklarda üçüncü taraf siteler ve Binance.US üzerinden doğrulanmıştır; kendi hesabınızın oranını Binance ücret sayfasından kontrol edip `ucret_orani` ayarına yazın.

---

## 6. Kaynaklar

- Arkham resmi tokenomik: https://codex.arkm.com/tokenomics
- Tokenomist ARKM açılım takvimi: https://tokenomist.ai/arkham/unlock-events
- Messari ARKM: https://messari.io/project/arkham
- CoinPaprika ARKM: https://coinpaprika.com/coin/arkm-arkham
- DropsTab ARKM: https://dropstab.com/coins/arkham
- LeveX ARKM tokenomik: https://levex.com/en/blog/arkm-tokenomics
- CoinMarketCap ARKM güncellemeleri: https://coinmarketcap.com/cmc-ai/arkham/latest-updates/
- CoinGecko ARKM tokenomik: https://coingecko.com/en/coins/arkham/tokenomics
- NostalgiaForInfinity incelemesi: https://www.patreon.com/posts/89663923
- Freqtrade/NFI özet wiki: https://github-wiki-see.page/m/doubility-sky/daydayup/wiki/freqtrade
- Binance ücretleri (üçüncü taraf): https://coinspot.io/en/analysis/binance-fees-2025-the-ultimate-guide/
- Binance.US ücret ve BNB indirimi: https://support.binance.us/en/articles/9843536-binance-us-launches-trading-fee-discount-and-vip-program-with-bnb
