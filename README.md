Bilirkişi Raporu Asistanı (AI Skill)
Türk yargısına sunulacak bilirkişi raporlarının usul, yapı, dil ve son kontrol katmanını sağlayan bir yapay zeka skill paketi.
Amaç, raporun mevzuatın saydığı zorunlu unsurları eksiksiz taşıması, görev sınırının aşılmaması, her bulgunun kaynağa bağlanması ve sonucun denetime elverişli olmasıdır. Paket alan bağımsızdır: bir uzmanlık alanının hesap yöntemini içermez, o alanın yerine geçmez.
Kapsam
İçerir	İçermez
Görev kapsamı ve etik sınırlar (hakimin takdir alanına girmeme)	Alana özgü hesap yöntemleri ve birim ölçütler
Zorunlu rapor unsurları: HMK m.279/2 ve Yönetmelik m.55/1	Verim, hasar, rekolte, amortisman, kamulaştırma bedeli formülleri
Rapor yapısı ve resmi DOCX şablonunun doldurulması	Piyasa fiyatı, birim fiyat listesi veya istatistik verisi
Süreler: HMK m.274 teslim süresi, m.275 ve Yönetmelik m.53-54 bir haftalık bildirimler	Taraf dilekçesi, uzman görüşü, mahkeme kararı yazımı
Sade ve doğal rapor dili; sadeleştirmede anlam kaymasını önleme	İmza, e-imza, UYAP gönderimi veya resmi başvuru
Ek rapor, raporlar arası çelişki giderme, heyet ve karşı görüş düzeni	Bilirkişilik eğitimi, sicil kaydı veya yeterlilik belgesi
19 maddelik son kontrol listesi ve kaynak sürüm disiplini	Güncel mevzuat taraması (paket, yüklenen nüshalara dayanır)
Alan hesabı gerekiyorsa
Zirai, inşaat, mali müşavirlik gibi bir alanın hesabı gerekiyorsa bu paketi o alanın skilli ile birlikte kullanın. Hesap yöntemi alan skillinden, görev sınırı ve zorunlu rapor unsurları bu paketten gelir. Alan skilli yoksa paket hesabı uydurmaz; hangi ölçütün hangi uzmanlıktan gerektiğini raporun sınırlılık bölümünde belirtir.
Paket içeriği
```
bilirkisi-raporu/
├── SKILL.md                          altı adımlık iş akışı ve çekirdek sınırlar
├── references/
│   ├── gorev-ve-etik.md              ön inceleme, teknik iş / yargısal takdir ayrımı, süreler, gizlilik
│   ├── teknik-inceleme.md            çalışma kodları, soru-belge-yöntem-hesap zinciri, çıkarım kontrolleri
│   ├── rapor-yapisi.md               zorunlu içeriğin iki dayanağı ve altı ana bölüm
│   ├── sade-dil.md                   ağır ifade / açık karşılık tablosu, sadeleştirmede güvenlik kuralları
│   ├── son-kontrol.md                teslim öncesi 19 maddelik denetim
│   ├── ek-rapor-ve-heyet.md          ek rapor, çelişkili raporlar, heyet ve karşı görüş
│   ├── kaynak-haritasi.md            sekiz kaynağın işlevi, kaynaklar arası çelişkiler, güncellik kontrolü
│   ├── kaynak-kunyesi.json           her kaynağın SHA-256 değeri, boyutu ve temsil biçimi
│   └── metinler/                     6754 sayılı Kanun, HMK m.266-293 seçkisi, Yönetmelik,
│                                     Rehber İlkeler, 169 sayılı Genelge
├── assets/resmi-rapor-sablonu.docx   Hukuk / İdare / Vergi mahkemeleri resmi rapor şablonu
└── agents/openai.yaml                arayüz tanımı
```
Kaynaklar ve sürüm disiplini
Paket, kullanıcının yüklediği sekiz kaynağa dayanır. Her kaynağın adı, boyutu ve SHA-256 özeti `references/kaynak-kunyesi.json` dosyasındadır. Hazırlanma tarihi, mevzuat doğrulama tarihi değildir. Somut bir dosyada yürürlük, değişiklik veya süre sonucu etkiliyorsa Resmi Gazete, Mevzuat Bilgi Sistemi ve Bilirkişilik Daire Başkanlığı kaynaklarından yeniden doğrulanmalıdır.
Paket, kaynaklar arasındaki bilinen tutarsızlıkları da kayda geçirir. Örnek: Temel Eğitim Kaynak Kitabı rapor içeriği listesi için Yönetmelik m.56/1'e atıf yapar; liste yüklenen Yönetmelikte m.55/1'dedir. Paket, kitabın atfını çoğaltmak yerine Yönetmelikten doğrulamayı şart koşar.
Telif nedeniyle Temel Eğitim Kaynak Kitabı ve Katılımcı El Kitabı'nın tam metni pakete eklenmemiş, yalnızca ilgili ilkelerin özgün özetleri ve sayfa yönlendirmeleri konulmuştur.
Kurulum
`bilirkisi-raporu.skill` dosyasını indirin.
Kullandığınız platformun skill yükleme arayüzünden içe aktarın.
Görevlendirme kararını, keşif tutanağını ve dosya belgelerini verip rapor hazırlamasını, mevcut bir raporu sadeleştirmesini ya da usul yönünden denetlemesini isteyin.
Kaynaktan derleme
Depoda kaynak dosyalar ayrı ayrı sürümlenir; `.skill` paketi bunlardan üretilir:
```bash
python3 derle.py
```
Bu, `bilirkisi-raporu/` klasörünü `bilirkisi-raporu.skill` olarak paketler ve içeriğin bütünlüğünü kontrol eder.
Sınırlar
Bu bir yardımcı araçtır. Bilirkişinin bizzat yapması gereken incelemenin, keşfin, ölçümün, mesleki kanaatinin ve imzasının yerine geçmez (6754 sayılı Kanun m.3, HMK m.276-277, Yönetmelik m.5/4).
Paket, hukuki nitelendirme yapmaz; kusur oranı, asli/tali kusur, sorumluluk payı veya dava sonucu üretmez (Yönetmelik m.55/4, HMK m.279/4, Rehber İlkeler 27). Bu sınır, "takdir mahkemenindir" cümlesi eklenerek aşılamaz.
Üretilen metnin teknik doğruluğu, hukuki sorumluluğu ve imza yetkisi tamamen dosyaya atanan bilirkişiye aittir. UYAP üzerinden sunmadan önce insan kontrolü zorunludur.
Lisans
Paketteki kanun, yönetmelik, genelge ve resmi şablon metinleri, FSEK m.31 uyarınca serbestçe faydalanılabilen resmi metinlerdir. Rehber dosyalarının lisansı için `LICENSE` dosyasına bakınız.

Bu araç bir yapay zeka asistanıdır ve bilirkişilerin iş yükünü hafifletmek, formatlama süreçlerini hızlandırmak için tasarlanmıştır. Üretilen raporlardaki nihai teknik doğruluk, hukuki sorumluluk ve imza yetkisi **tamamen dosyaya atanan adli bilirkişiye aittir.** Raporları UYAP üzerinden mahkemeye sunmadan önce mutlaka son bir insan kontrolünden geçirmelisiniz.
