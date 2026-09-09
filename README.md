# ⚖️ Adli Bilirkişi Raporu Asistanı (AI Skill)

Bu depo, Türk Hukuk Sistemine uygun, HMK ve Bilirkişilik Kanunu standartlarında resmi adli raporlar hazırlamak için tasarlanmış özel bir Yapay Zeka (AI) "Skill" dosyasını içermektedir.

Yoğun dosya yükü olan adli bilirkişilerin; keşif notlarını, teknik tespitlerini ve hesaplamalarını saniyeler içinde mahkemeye sunulmaya hazır, resmi formatlı bir rapora dönüştürmesine yardımcı olur.

## 🌟 Temel Özellikler

- **Hukuki Standartlara Tam Uyum:** Yapay zeka; 6100 sayılı HMK, 6754 sayılı Bilirkişilik Kanunu ve Bilirkişilik Yönetmeliği ile Rehber İlkeler'i referans alarak çalışır.
- **Görev Sınırlarının Korunması:** Asistan, hakimin takdir yetkisine giren konularda (hukuki nitelendirme, kusur oranı veya ceza tayini) kesinlikle görüş bildirmez; sadece teknik verileri ve tespitleri sunar.
- **Matematiksel Doğrulama & Anti-Halüsinasyon:** Arazi ve miras payı hesaplamalarında "payın hiçbir zaman paydayı geçmemesi" gibi kritik mantık kontrollerini otomatik yapar. Meyve bahçesi değerlemeleri, 5 yıllık ortalama verim ve rekolte bedeli gibi hesaplamalarda formülleri adım adım işler.
- **Teknik ve Zirai İnceleme Desteği:** Zirai hasar tespitleri, toprak analizleri, güzergah/parsel eşleştirmeleri ve kamulaştırma bedelleri gibi teknik konularda elde edilen taslak notları profesyonel bir dile çevirir.
- **Sade ve Anlaşılır Dil:** Teknik terimleri, mahkeme heyetinin ve hukukçuların net bir şekilde anlayabileceği sade bir yapıya kavuşturur.

## 🚀 Nasıl Kullanılır?

Bu asistan, `.skill` formatını destekleyen yapay zeka arayüzleri ve platformları için paketlenmiştir.

1. **İndirin:** Bu depoda yer alan `bilirkisi-raporu.skill` dosyasını bilgisayarınıza indirin.
2. **İçe Aktarın:** Kullandığınız yapay zeka platformunun (Claude, özel ajan platformları vb.) yetenek/skill yükleme arayüzüne gidin ve dosyayı "Import" (İçe Aktar) seçeneği ile yükleyin.
3. **Çalıştırın:** Keşif tutanaklarınızı, ham notlarınızı veya hesaplanacak verilerinizi asistana iletin ve raporunuzu oluşturmasını isteyin.

## 📂 İçerik Mimarisi (Skill Neleri Kapsar?)

Skill dosyasının arka planında çalışan referans yapıları şunlardır:
- `6100-hmk-bilirkisi.md` & `6754-kanun.md`: Yasal çerçeve ve sınırlar.
- `rehber-ilkeler.md` & `gorev-ve-etik.md`: Bilirkişi davranış kuralları.
- `teknik-inceleme.md`: Zirai ve mühendislik hesaplama metodolojileri.
- `resmi-rapor-sablonu.docx`: Çıktıların oturtulacağı adliye standartlarındaki taslak.
- `sade-dil.md` & `son-kontrol.md`: Anlaşılabilirlik ve veri eşleştirme denetimleri.

## ⚠️ Yasal Uyarı

Bu araç bir yapay zeka asistanıdır ve bilirkişilerin iş yükünü hafifletmek, formatlama süreçlerini hızlandırmak için tasarlanmıştır. Üretilen raporlardaki nihai teknik doğruluk, hukuki sorumluluk ve imza yetkisi **tamamen dosyaya atanan adli bilirkişiye aittir.** Raporları UYAP üzerinden mahkemeye sunmadan önce mutlaka son bir insan kontrolünden geçirmelisiniz.
