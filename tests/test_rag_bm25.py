"""BM25 sözleşmesi (docs/hibrit.md › BM25 için metin hazırlama, BM25 skoru).

Ağa çıkmaz, `.env` gerektirmez. Testler koddan önce yazıldı: `backend/rag/bm25.py`
ve `search(method="bm25")` yokken kırmızıdır.

Sözleşmenin test için sabitlenen adları (docs'ta açık değil):
- `backend.rag.bm25.tokenize(text) -> list[str]`: hazırlama adımlarını uygular;
  sıra ve tekrarlar korunur (terim sıklığı için).
- `search(query, ..., method="bm25")`: gömme çağrısı yapmaz, model uyuşmazlığına
  bakmaz. İndeks dosyalarından biri eksikse yine `IndexNotReadyError`.
- Skorun terim bileşeni standart Okapi biçimindedir:
  `idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / avgdl))`; sorgu sözcükleri
  toplanır. Sorguda tekrar eden sözcüğün nasıl sayılacağı belgede yok, test edilmez.
"""

import importlib.util
import json
import math
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.rag import embed, search

MODEL = "sahte-gomme-modeli"
K1 = 1.5
B = 0.75
RESULT_FIELDS = (
    "score",
    "chunk_id",
    "doc_id",
    "revision",
    "status",
    "language",
    "section",
    "text",
)


def load_bm25():
    assert importlib.util.find_spec("backend.rag.bm25") is not None, (
        "backend/rag/bm25.py yok"
    )
    from backend.rag import bm25

    return bm25


def tokens(text: str) -> list[str]:
    return load_bm25().tokenize(text)


# ───────── Metin hazırlama ─────────


def test_modul_var():
    assert importlib.util.find_spec("backend.rag.bm25") is not None


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("İSTANBUL", "istanbul"),
        ("arıza", "arızası"),
        ("stand'ına", "stand"),
        ("ISIK", "ışık"),
    ],
)
def test_belge_ornekleri_ayni_sozcuk(left, right):
    assert tokens(left) == tokens(right)
    assert len(tokens(left)) == 1


def test_tk2345_ile_tk2346_farkli_sozcuk():
    assert tokens("TK2345") != tokens("TK2346")
    assert len(tokens("TK2345")) == 1
    assert len(tokens("TK2346")) == 1


def test_dusuk_gorus_ornegi():
    assert tokens("Düşük görüş") == ["dusuk", "gorus"]


def test_ilk_bes_harf_alinir():
    assert tokens("arızası") == ["ariza"]
    assert tokens("köprüsü") == ["kopru"]


def test_bes_harften_kisa_sozcuk_oldugu_gibi_kalir():
    assert tokens("PBB pist") == ["pbb", "pist"]


def test_rakam_iceren_sozcuk_kisaltilmaz():
    assert tokens("TK2345") == ["tk2345"]
    assert tokens("B12") == ["b12"]
    assert tokens("D07rev2") == ["d07rev2"]


def test_kesme_isaretinden_sonraki_ek_atilir_duz_ve_kivrik():
    assert tokens("stand'ına") == ["stand"]
    assert tokens("stand’ına") == ["stand"]
    assert tokens("TK2345'in") == ["tk2345"]
    assert tokens("TK2345’in") == ["tk2345"]


def test_kesme_isareti_yalnizca_kendi_sozcugunu_etkiler():
    assert tokens("A stand'ına kod E uçağı") == ["a", "stand", "kod", "e", "ucagi"]


def test_ek_atildiktan_sonra_kalan_kok_de_kisaltilir():
    # Adım 1 adım 4'ten önce: kök 5 harften uzunsa kök kısaltılır, ek zaten yok.
    assert tokens("havalimanı'nın") == ["haval"]


def test_turkce_kucuk_harf_ve_ascii_indirme():
    assert tokens("İ I ı ç ş ğ ü ö") == ["i", "i", "i", "c", "s", "g", "u", "o"]
    assert tokens("ÇIKIŞ") == ["cikis"]


def test_buyuk_i_noktali_kucuk_i_olmaz():
    # `str.lower()` "İ"yi "i" + birleştirici nokta yapar; ASCII'ye inmez.
    assert tokens("İSTANBUL") == tokens("istanbul")
    for token in tokens("İzmir İSTANBUL IŞIK ıslak"):
        assert token.isascii()


def test_tum_cikti_ascii():
    for token in tokens("Çalışma önlüğü şüpheli ığdır İÇERİ"):
        assert token.isascii(), token


def test_noktalama_ve_bosluk_sozcuk_ayirir():
    assert tokens("pist-kapat, stand.") == ["pist", "kapat", "stand"]
    assert tokens("pist\tkapat\nstand") == ["pist", "kapat", "stand"]


def test_sira_ve_tekrar_korunur():
    assert tokens("pist stand pist") == ["pist", "stand", "pist"]


def test_durdurma_listesi_yok():
    assert tokens("ve ile bir bu") == ["ve", "ile", "bir", "bu"]


@pytest.mark.parametrize("text", ["", "   ", "!!! ... ---", "'", "’’"])
def test_sozcuk_yoksa_bos_liste(text):
    assert tokens(text) == []


def test_sorgu_ve_parca_ayni_adimlardan_gecer():
    # Aynı işlev iki taraf için de kullanılır: büyük/küçük harf ve ek fark etmez.
    assert tokens("ARIZASI") == tokens("arızası") == tokens("arıza")


# ───────── İndeks kurulumu (BM25 vektör kullanmaz) ─────────


def make_chunk(chunk_id, doc_id, status, language, type_, text) -> dict:
    return {
        "doc_id": doc_id,
        "title": f"Belge {doc_id}",
        "type": type_,
        "authority": "Kurgusal Makam",
        "airport": "XXXX",
        "language": language,
        "revision": "1",
        "effective_from": "2025-03-01",
        "status": status,
        "chunk_id": chunk_id,
        "section": f"Bölüm {chunk_id}",
        "text": text,
        "context": f"[{doc_id} · Belge {doc_id} · Bölüm {chunk_id}]",
    }


def write_index(directory: Path, rows, model: str = MODEL) -> None:
    """§5 dosyalarını doğrudan yazar; vektörler anlamsız (BM25 bakmaz)."""
    directory.mkdir(parents=True, exist_ok=True)
    chunks = [make_chunk(*row) for row in rows]
    (directory / "chunks.json").write_text(
        json.dumps(chunks, ensure_ascii=False), encoding="utf-8"
    )
    np.save(
        directory / "vektorler.npy",
        np.zeros((len(chunks), 3), dtype=np.float32),
        allow_pickle=False,
    )
    meta = {
        "model": model,
        "dimension": 3,
        "chunk_count": len(chunks),
        "corpus_sha256": "0" * 64,
    }
    (directory / "meta.json").write_text(json.dumps(meta), encoding="utf-8")


# (chunk_id, doc_id, status, language, type, text). Metinlerde yalnızca 5 harfi
# aşmayan küçük ASCII sözcükler var: hazırlama adımı kimlik işlevi görür ve
# skor elle hesaplanabilir.
#   N = 3, uzunluklar 3, 2, 3 → avgdl = 8/3
#   idf(n=1) = ln(1 + 2.5/1.5), idf(n=2) = ln(1 + 1.5/2.5)
CHUNKS = [
    ("D01#01", "D01", "active", "tr", "manual", "pist pist kapat"),
    ("D01#02", "D01", "active", "tr", "manual", "stand kapat"),
    ("D02#01", "D02", "superseded", "en", "procedure", "stand stand stand"),
]
# Elle hesaplanmış (yukarıdaki formül): sorgu → {chunk_id: skor}.
SCORES = {
    "pist": {"D01#01": 1.347062},
    "kapat": {"D01#02": 0.529582, "D01#01": 0.444974},
    "stand": {"D02#01": 0.759602, "D01#02": 0.529582},
    "pist kapat": {"D01#01": 1.792035, "D01#02": 0.529582},
    "pist stand": {"D01#01": 1.347062, "D02#01": 0.759602, "D01#02": 0.529582},
}


def reference_scores(texts: dict[str, str], query: str) -> dict[str, float]:
    """Belgedeki formülün bağımsız bir yazımı (sözcükler zaten hazır)."""
    docs = {cid: text.split() for cid, text in texts.items()}
    count = len(docs)
    avgdl = sum(len(words) for words in docs.values()) / count
    result = {}
    for cid, words in docs.items():
        total = 0.0
        for term in query.split():
            n = sum(term in other for other in docs.values())
            tf = words.count(term)
            if not tf:
                continue
            idf = math.log(1 + (count - n + 0.5) / (n + 0.5))
            total += (
                idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * len(words) / avgdl))
            )
        if total > 0:
            result[cid] = total
    return result


@pytest.fixture
def index_dir(tmp_path):
    directory = tmp_path / "data" / "indeks"
    write_index(directory, list(reversed(CHUNKS)))
    return directory


@pytest.fixture
def no_env(monkeypatch, tmp_path):
    """Gömme ayarı yok: BM25 buna ihtiyaç duymamalı."""
    monkeypatch.setattr(embed, "ENV_FILE", tmp_path / "yok.env")
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.delenv("COPILOT_EMBED_MODEL", raising=False)

    def no_client(key):
        raise AssertionError("BM25 Voyage istemcisi kurmamalı")

    monkeypatch.setattr(embed, "_make_client", no_client)


class ExplodingClient:
    """Çağrılırsa test düşer: BM25 gömme yapmaz."""

    def embed(self, texts, model, input_type):
        raise AssertionError("BM25 gömme çağrısı yapmamalı")


def run(index_dir, query, **kwargs):
    kwargs.setdefault("client", ExplodingClient())
    return search.search(query, index_dir=index_dir, method="bm25", **kwargs)


def ids(results) -> list[str]:
    return [r["chunk_id"] for r in results]


# ───────── Skor ─────────


@pytest.mark.parametrize("query", list(SCORES))
def test_skorlar_elle_hesaplanan_degerlerle_eslesir(index_dir, query):
    results = run(index_dir, query, k=5)

    assert len(results) == len(SCORES[query])
    assert {r["chunk_id"]: r["score"] for r in results} == pytest.approx(
        SCORES[query], abs=1e-5
    )


@pytest.mark.parametrize("query", list(SCORES))
def test_skor_sirasi_azalan(index_dir, query):
    results = run(index_dir, query, k=5)

    assert ids(results) == list(SCORES[query])
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_elle_hesap_bagimsiz_formulle_tutarli(index_dir):
    # Tablodaki sabitler formülün yazımıyla çelişmesin.
    texts = {row[0]: row[5] for row in CHUNKS}
    for query, expected in SCORES.items():
        assert reference_scores(texts, query) == pytest.approx(expected, abs=1e-5)


def test_k1_ve_b_degerleri_formule_uyar(tmp_path):
    # Tek sözcüklü iki parça: tf=1, dl=avgdl → paydadaki uzunluk terimi 1'dir,
    # skor = idf * (k1 + 1) / (1 + k1).
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D01#01", "D01", "active", "tr", "manual", "pist"),
            ("D01#02", "D01", "active", "tr", "manual", "stand"),
        ],
    )

    results = run(directory, "pist", k=5)

    idf = math.log(1 + (2 - 1 + 0.5) / (1 + 0.5))
    assert len(results) == 1
    assert results[0]["score"] == pytest.approx(idf * (K1 + 1) / (1 + K1), abs=1e-9)


def test_idf_formulu_her_parcada_gecen_sozcuk_da_pozitif_skor_alir(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D01#01", "D01", "active", "tr", "manual", "pist"),
            ("D01#02", "D01", "active", "tr", "manual", "pist"),
        ],
    )

    results = run(directory, "pist", k=5)

    assert len(results) == 2
    assert all(r["score"] > 0 for r in results)


def test_nadir_sozcuk_yaygin_sozcukten_agirdir(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D01#01", "D01", "active", "tr", "manual", "pist pist"),
            ("D01#02", "D01", "active", "tr", "manual", "pist stand"),
            ("D01#03", "D01", "active", "tr", "manual", "pist kapat"),
        ],
    )

    by_id = {r["chunk_id"]: r["score"] for r in run(directory, "pist stand", k=5)}

    # "stand" yalnızca D01#02'de, "pist" her yerde: D01#02 tek başına öndedir.
    assert max(by_id, key=by_id.get) == "D01#02"


def test_uzun_parca_kisa_parcadan_dusuk_skor_alir(index_dir):
    # "kapat": D01#02 (dl=2) ve D01#01 (dl=3), ikisinde de tf=1.
    scores = {r["chunk_id"]: r["score"] for r in run(index_dir, "kapat", k=5)}

    assert scores["D01#02"] > scores["D01#01"]


def test_terim_sikligi_artinca_skor_artar_ama_dogrusal_degil(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D01#01", "D01", "active", "tr", "manual", "pist kapat stand"),
            ("D01#02", "D01", "active", "tr", "manual", "pist pist stand"),
            ("D01#03", "D01", "active", "tr", "manual", "pist pist pist"),
            ("D01#04", "D01", "active", "tr", "manual", "kapat kapat kapat"),
        ],
    )

    by_id = {r["chunk_id"]: r["score"] for r in run(directory, "pist", k=5)}

    assert by_id["D01#01"] < by_id["D01#02"] < by_id["D01#03"]
    assert by_id["D01#02"] < 2 * by_id["D01#01"]


def test_idf_ve_ortalama_uzunluk_tum_parcalardan_hesaplanir(index_dir):
    # doc_id=D01 filtresi D01#02'yi tek başına bırakmaz; skoru süzülmemiş aramayla
    # aynıdır (N=3, avgdl=8/3 hâlâ tüm indeksten).
    unfiltered = {r["chunk_id"]: r["score"] for r in run(index_dir, "stand", k=5)}
    filtered = {
        r["chunk_id"]: r["score"] for r in run(index_dir, "stand", k=5, doc_id="D01")
    }

    assert filtered == {"D01#02": unfiltered["D01#02"]}
    assert filtered["D01#02"] == pytest.approx(0.529582, abs=1e-5)


def test_skor_duz_python_float(index_dir):
    results = run(index_dir, "pist kapat", k=5)

    assert results
    assert all(type(r["score"]) is float for r in results)


# ───────── Sıfır skor ve boş sonuç ─────────


def test_skoru_sifir_olan_parca_sonuc_degildir(index_dir):
    # 3 parça var ama "pist" yalnızca birinde geçiyor.
    assert ids(run(index_dir, "pist", k=5)) == ["D01#01"]


def test_hic_ortak_sozcuk_yoksa_bos_liste(index_dir):
    assert run(index_dir, "yagmur ruzgar", k=5) == []


def test_sorguda_sozcuk_kalmazsa_bos_liste(index_dir):
    assert run(index_dir, "!!! ...", k=5) == []


def test_bos_soru_reddedilir(index_dir):
    with pytest.raises(ValueError):
        run(index_dir, "   ")


def test_k_den_az_eslesen_varsa_hepsi_doner(index_dir):
    assert ids(run(index_dir, "kapat", k=20)) == ["D01#02", "D01#01"]


# ───────── Eşleşme: hazırlama adımları aramada ─────────


def test_ek_ve_buyuk_harf_farki_eslesmeyi_bozmaz(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D05#01", "D05", "active", "tr", "sop", "PBB arızası durumunda"),
            ("D05#02", "D05", "active", "tr", "sop", "Pist kapanışı"),
        ],
    )

    assert ids(run(directory, "arıza", k=5)) == ["D05#01"]
    assert ids(run(directory, "ARIZASI", k=5)) == ["D05#01"]


def test_istanbul_buyuk_i_ile_eslesir(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [("D01#01", "D01", "active", "tr", "manual", "İSTANBUL havalimanı")],
    )

    assert ids(run(directory, "istanbul", k=5)) == ["D01#01"]
    assert ids(run(directory, "İstanbul", k=5)) == ["D01#01"]


def test_kesme_isaretli_ek_eslesir(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D01#01", "D01", "active", "tr", "manual", "A stand'ına kod E park eder"),
            ("D01#02", "D01", "active", "tr", "manual", "Gate B12 kapandı"),
        ],
    )

    assert ids(run(directory, "stand", k=5)) == ["D01#01"]
    assert ids(run(directory, "stand’ında", k=5)) == ["D01#01"]


def test_sefer_numarasi_tam_eslesir(tmp_path):
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [
            ("D13#01", "D13", "active", "tr", "memory", "TK2345 gecikti"),
            ("D13#02", "D13", "active", "tr", "memory", "TK2346 iptal edildi"),
        ],
    )

    assert ids(run(directory, "TK2345", k=5)) == ["D13#01"]
    assert ids(run(directory, "TK2346'nın", k=5)) == ["D13#02"]


def test_dort_harfli_kok_ekli_haliyle_eslesmez(tmp_path):
    # Belgedeki "bilinen sınır": uçuş ≠ uçuşlarda.
    directory = tmp_path / "indeks"
    write_index(
        directory,
        [("D01#01", "D01", "active", "tr", "manual", "uçuşlarda gecikme")],
    )

    assert run(directory, "uçuş", k=5) == []


# ───────── Sıralama ve k ─────────


def test_esit_skorda_chunk_id_artan(tmp_path):
    directory = tmp_path / "indeks"
    rows = [
        ("D05#01", "D05", "active", "tr", "manual", "pist kapat"),
        ("D01#02", "D01", "active", "tr", "manual", "pist kapat"),
        ("D03#01", "D03", "active", "tr", "manual", "pist kapat"),
        ("D01#01", "D01", "active", "tr", "manual", "pist kapat"),
    ]
    write_index(directory, rows)

    assert ids(run(directory, "pist", k=5)) == [
        "D01#01",
        "D01#02",
        "D03#01",
        "D05#01",
    ]


def test_esit_skorda_k_siniri_chunk_id_ye_gore_keser(tmp_path):
    directory = tmp_path / "indeks"
    rows = [
        ("D03#01", "D03", "active", "tr", "manual", "pist"),
        ("D01#01", "D01", "active", "tr", "manual", "pist"),
        ("D02#01", "D02", "active", "tr", "manual", "pist"),
    ]
    write_index(directory, rows)

    assert ids(run(directory, "pist", k=2)) == ["D01#01", "D02#01"]


def test_varsayilan_k_bes(tmp_path):
    directory = tmp_path / "indeks"
    rows = [
        (f"D01#0{i}", "D01", "active", "tr", "manual", "pist") for i in range(1, 8)
    ]
    write_index(directory, rows)

    results = search.search(
        "pist", index_dir=directory, method="bm25", client=ExplodingClient()
    )

    assert ids(results) == [f"D01#0{i}" for i in range(1, 6)]


@pytest.mark.parametrize("k", [1, 2])
def test_k_kadar_sonuc(index_dir, k):
    assert ids(run(index_dir, "pist kapat", k=k)) == ["D01#01", "D01#02"][:k]


def test_ayni_soru_ayni_sonuc(index_dir):
    assert run(index_dir, "pist kapat", k=5) == run(index_dir, "pist kapat", k=5)


# ───────── Sonuç biçimi ─────────


def test_sonuc_alanlari_vektor_aramasiyla_ayni(index_dir):
    results = run(index_dir, "pist", k=5)

    assert results
    for result in results:
        for field in RESULT_FIELDS:
            assert field in result, field
    top = results[0]
    assert top["doc_id"] == "D01"
    assert top["revision"] == "1"
    assert top["status"] == "active"
    assert top["language"] == "tr"
    assert top["section"] == "Bölüm D01#01"
    assert top["text"] == "pist pist kapat"


# ───────── Filtreler ─────────


def test_status_filtresi(index_dir):
    assert ids(run(index_dir, "stand", k=5, status="superseded")) == ["D02#01"]


def test_language_filtresi(index_dir):
    assert ids(run(index_dir, "stand", k=5, language="en")) == ["D02#01"]


def test_type_filtresi(index_dir):
    assert ids(run(index_dir, "stand", k=5, type="manual")) == ["D01#02"]


def test_doc_id_filtresi(index_dir):
    assert ids(run(index_dir, "kapat", k=5, doc_id="D01")) == ["D01#02", "D01#01"]


def test_filtreler_birlikte_ve_ile_birlesir(index_dir):
    assert ids(run(index_dir, "stand", k=5, status="active", language="tr")) == [
        "D01#02"
    ]


def test_filtre_siralamadan_once_uygulanir(index_dir):
    # "stand" genel sırada D02#01 önde; D01 filtresi onu eler ve k=1 yine D01#02'yi
    # döndürür (son-süzme yapılsaydı boş kalırdı).
    assert ids(run(index_dir, "stand", k=1, doc_id="D01")) == ["D01#02"]


def test_filtre_hicbir_parca_birakmazsa_bos_liste(index_dir):
    assert run(index_dir, "stand", k=5, doc_id="D99") == []


def test_filtreye_uyan_ama_eslesmeyen_parca_sonuc_degildir(index_dir):
    assert run(index_dir, "pist", k=5, doc_id="D02") == []


# ───────── Gömme ve model: BM25 bunlara bağımlı değil ─────────


def test_gomme_istemcisi_cagrilmaz(index_dir):
    class Recorder:
        def __init__(self):
            self.calls = []

        def embed(self, texts, model, input_type):
            self.calls.append(texts)
            raise AssertionError("gömme çağrılmamalı")

    recorder = Recorder()

    results = run(index_dir, "pist", k=5, client=recorder)

    assert ids(results) == ["D01#01"]
    assert recorder.calls == []


def test_ayar_yokken_calisir(index_dir, no_env):
    # `.env` yok, VOYAGE_API_KEY ve COPILOT_EMBED_MODEL yok, Voyage istemcisi
    # kurulursa test düşer.
    assert ids(search.search("pist", index_dir=index_dir, method="bm25")) == [
        "D01#01"
    ]


def test_model_uyusmazligi_bm25i_reddettirmez(index_dir):
    results = run(index_dir, "pist", k=5, model="baska-model")

    assert ids(results) == ["D01#01"]


def test_vektor_boyutu_ya_da_icerigi_sonucu_etkilemez(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    write_index(first, CHUNKS)
    write_index(second, CHUNKS)
    np.save(
        second / "vektorler.npy",
        np.random.default_rng(0).normal(size=(3, 3)).astype(np.float32),
        allow_pickle=False,
    )

    assert run(first, "pist kapat", k=5) == run(second, "pist kapat", k=5)


# ───────── İndeks yok ─────────


def test_indeks_klasoru_yoksa_index_not_ready(tmp_path):
    with pytest.raises(search.IndexNotReadyError) as info:
        run(tmp_path / "yok", "pist")

    assert info.value.code == "INDEX_NOT_READY"


@pytest.mark.parametrize("missing", ["chunks.json", "vektorler.npy", "meta.json"])
def test_indeks_dosyalarindan_biri_eksikse_index_not_ready(index_dir, missing):
    (index_dir / missing).unlink()

    with pytest.raises(search.IndexNotReadyError):
        run(index_dir, "pist")


# ───────── Bellekte kurulur, çağrılar arası saklanmaz, diske yazılmaz ─────────


def test_tablo_her_aramada_indeksten_yeniden_kurulur(index_dir):
    assert ids(run(index_dir, "pist", k=5)) == ["D01#01"]

    # `rag_indeksle.py` sunucu çalışırken indeksi yenilemiş gibi: aynı klasör,
    # aynı parça sayısı, farklı metin.
    rows = [
        ("D01#01", "D01", "active", "tr", "manual", "stand kapat"),
        ("D01#02", "D01", "active", "tr", "manual", "pist kapat"),
        ("D02#01", "D02", "superseded", "en", "procedure", "stand stand stand"),
    ]
    write_index(index_dir, rows)

    assert ids(run(index_dir, "pist", k=5)) == ["D01#02"]


def test_ayri_indeks_klasorleri_birbirine_karismaz(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    write_index(first, [("D01#01", "D01", "active", "tr", "manual", "pist")])
    write_index(second, [("D09#01", "D09", "active", "tr", "manual", "pist")])

    assert ids(run(first, "pist")) == ["D01#01"]
    assert ids(run(second, "pist")) == ["D09#01"]
    assert ids(run(first, "pist")) == ["D01#01"]


def test_arama_diske_hicbir_sey_yazmaz(index_dir, tmp_path):
    before = {p.name: p.read_bytes() for p in index_dir.iterdir()}
    tree_before = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))

    run(index_dir, "pist kapat", k=5)
    run(index_dir, "stand", k=2, status="active")

    assert {p.name: p.read_bytes() for p in index_dir.iterdir()} == before
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == (
        tree_before
    )


def test_arama_gercek_data_klasorune_dokunmaz(index_dir):
    data = Path(__file__).resolve().parent.parent / "data"
    names_before = sorted(p.name for p in data.iterdir()) if data.exists() else None

    run(index_dir, "pist")

    names_after = sorted(p.name for p in data.iterdir()) if data.exists() else None
    assert names_after == names_before


# ───────── HTTP: bm25 gömme istemez (docs/hibrit.md › HTTP) ─────────


@pytest.fixture
def http(index_dir, no_env, monkeypatch):
    monkeypatch.setattr(search, "INDEX_DIR", index_dir)
    return TestClient(app)


def test_http_bm25_ayar_olmadan_200_doner(http):
    response = http.get("/rag/search", params={"q": "pist", "method": "bm25"})

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "bm25"
    assert [r["chunk_id"] for r in body["results"]] == ["D01#01"]
    assert set(RESULT_FIELDS) <= set(body["results"][0])


def test_http_bm25_filtre_ve_k(http):
    response = http.get(
        "/rag/search",
        params={"q": "kapat", "method": "bm25", "k": 1, "doc_id": "D01"},
    )

    assert response.status_code == 200
    assert [r["chunk_id"] for r in response.json()["results"]] == ["D01#02"]


def test_http_bm25_eslesme_yoksa_bos_liste_hata_degil(http):
    response = http.get("/rag/search", params={"q": "yagmur", "method": "bm25"})

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_http_bm25_indeks_yoksa_503_index_not_ready(http, tmp_path, monkeypatch):
    monkeypatch.setattr(search, "INDEX_DIR", tmp_path / "yok")

    response = http.get("/rag/search", params={"q": "pist", "method": "bm25"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INDEX_NOT_READY"
