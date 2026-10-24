---
name: prompt-netlestir
description: AOCC Copilot reposunda bir görev prompt'unu çalışmaya başlamadan önce Amaç, Bağlam, Veri, Kısıt ve Format alanlarına göre değerlendirir; eksik alanları sorar, 5 alanlık özeti onaya sunar. prompt-gate hook'u hatırlattığında ya da kullanıcı /prompt-netlestir yazdığında kullan.
---

# Prompt netleştirme

Amaç: bu projede varsayım yapma ihtimalini en aza indirmek. Eksik ya da belirsiz bir alanı
kendin doldurma; kullanıcıya sor. Repodan (CLAUDE.md, kod, git) kesin olarak çıkarabildiğin
bilgiyi sorma, kaynağını göstererek kullan.

## Ne zaman atlanır

Mesaj senin sorduğun bir soruya ya da gösterdiğin özete yanıtsa (onay, seçim, düzeltme) bu
skill'i uygulama; konuşmaya devam et. Elle çağrıldıysa (`/prompt-netlestir`) asla atlama.

## Alanlar

| Alan | Ne sorar | Repodan çıkarılabilir (sorma, kaynak göster) | Eksik sayılır, sor |
|---|---|---|---|
| **Amaç** | Bu iş neden yapılıyor, bitince ne değişmiş olacak? | Kilometre taşı bağlamı (git log, `docs/`) | Başarı ölçütü belirsizse ("iyileştir", "düzelt", "ekle" ama ne için?) |
| **Bağlam** | Hangi dosya/modül, hangi kilometre taşı, mevcut durum ne? | Dosya yapısı, `backend/llm.py`, `backend/main.py`, mevcut spec'ler | Prompt'ta geçen modül/özellik birden fazla yere eşlenebiliyorsa ya da repoda yoksa |
| **Veri** | Hangi girdiyle çalışılacak? (uçuş/gate/olay alanları, örnek istek, mock veri, model yanıtı) | Var olan şema ve örnekler | Uydurulması gereken her alan adı, değer, örnek kayıt. Canlı veri olmadığı için bunları asla kendin üretme |
| **Kısıt** | Neye dokunulmamalı, hangi kurallar geçerli? | CLAUDE.md Kurallar/Yasaklar (ör. model adını gömme, ücretli API çağrısı) | Kapsam sınırı belirsizse (sadece backend mi, test de mi?) ya da iş ücretli API çağrısı gerektiriyorsa ve bu açıkça istenmemişse |
| **Format** | Çıktı ne olacak? (kod değişikliği, script, doc, commit, sadece açıklama) | Proje kuralları (Türkçe yorum, commit öneki) | Çıktı türü belirsizse ("bak bakalım" → analiz mi, düzeltme mi?), commit/push istenip istenmediği belli değilse |

## Karar kuralı

1. Beş alanın her biri prompt'tan ya da repodan kesin olarak doluyorsa soru sormadan çalış.
2. Bir alan "eksik sayılır" sütununa düşüyorsa çalışmaya başlamadan önce yalnızca eksik alanları
   sor.
3. Cevaplardan sonra 5 alanlık özeti göster ve onay bekle. Onaydan önce dosya değiştirme, komut
   çalıştırma. Değerlendirme için yalnızca dosya okuma/arama ve `git log`, `git status`,
   `git diff`, `git show` serbesttir; script, test ya da API çağrısı yapan hiçbir komut değil.
4. "Repodan çıkarılabilir", "tahmin edilebilir" anlamına gelmez. Bir değeri dosyada ya da komut
   çıktısında doğrudan göremiyorsan o alan eksiktir.

## Soru kuralları

- `AskUserQuestion` aracını kullan; tek turda en fazla 4 soru.
- Mümkünse seçenekli sor; repodan bir öneri çıkarabiliyorsan onu ilk seçenek yap.
- Yalnızca eksik alanları sor; dolu alanları tekrar sorma.

## Özet şablonu

```
Amaç:   ...
Bağlam: ...  (kaynak: backend/main.py)
Veri:   ...
Kısıt:  ...  (kaynak: CLAUDE.md › Yasaklar)
Format: ...
Varsayım: yok   ← sıfır değilse her biri ayrı satırda listelenir
Onaylıyor musun?
```

Repodan doldurduğun her alanın yanına kaynağını parantez içinde yaz.

## Elle çağırma

`/prompt-netlestir <metin>`: "net ise sessiz geç" kuralı uygulanmaz; prompt net olsa bile özeti
göster ve onay bekle. Argüman yoksa değerlendirilecek prompt bir önceki kullanıcı mesajıdır.
