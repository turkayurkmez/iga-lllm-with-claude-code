"""docs/rag_olcum.md skor hesabının sözleşme testleri (API'siz, uydurma kayıtlarla).

Hedef: `eval/rag_skor.py` › `score(records, questions) -> dict` ve
`render(result) -> str`. Modül koddan önce yazılan bu testlerle belirlenir.

Kayıt biçimi:
    {"id", "answer", "status",
     "searches": [{"args": {...}, "doc_ids": [sıralı belge kimlikleri]}],
     "citations": [{"chunk_id", "doc_id" | None, "dogrulandi", "status" | None}]}

`score` sonucu:
    recall:        {"hit", "total", "per_question": {id: 0|1}}
    answerability: {"u_ret", "u_total", "s_gereksiz_ret", "s_total", "belirsiz",
                    "classes": {id: "ret" | "cevap" | "belirsiz"}}
    citation_precision: {"dogru", "toplam", "oran" (toplam 0 ise None)}
    eski_surum:    {"hedef", "beklenen"}   # hedef: include_superseded=False
                                          # soruları; beklenen: True olanlar
    atifsiz:       {"atifsiz_cumle", "toplam_cumle", "dogrulanamayan",
                    "toplam_atif"}
    rows:          [{"id", "recall_tam", "ret_sinifi", "belgeler",
                     "eski_surum_atfi"}]
"""

import copy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RET = "Belgelerde bu konuda kaynak bulamadım."


def _modul():
    assert importlib.util.find_spec("eval.rag_skor") is not None, "eval/rag_skor.py yok"
    return importlib.import_module("eval.rag_skor")


def _q(qid, beklenen, sup=False, answerable=True):
    return {
        "id": qid,
        "soru": f"{qid} sorusu",
        "cevaplanabilir": answerable,
        "beklenen_belgeler": beklenen,
        "include_superseded": sup,
    }


def _c(chunk_id, doc_id, dogrulandi=True, status="active"):
    if not dogrulandi:
        return {
            "chunk_id": chunk_id,
            "doc_id": None,
            "dogrulandi": False,
            "status": None,
        }
    return {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "dogrulandi": True,
        "status": status,
    }


def _r(qid, answer="Cevap [D01#01].", docs=(("D01",),), citations=None):
    """docs: her arama için belge kimlikleri dizisi."""
    if citations is None:
        citations = [_c("D01#01", "D01")]
    return {
        "id": qid,
        "answer": answer,
        "status": "tamam",
        "searches": [{"args": {"query": "x"}, "doc_ids": list(d)} for d in docs],
        "citations": citations,
    }


def _ret(qid, docs=(("D01",),)):
    return _r(qid, answer=RET, docs=docs, citations=[])


# ---------------------------------------------------------------- recall@5


def test_recall_beklenen_belgelerin_hepsi_ilk_besteyse_bir():
    m = _modul()
    qs = [_q("S1", ["D01", "D07"])]
    rec = _r("S1", docs=[("D01", "D02", "D07")])
    out = m.score([rec], qs)
    assert out["recall"]["per_question"] == {"S1": 1}
    assert out["recall"]["hit"] == 1
    assert out["recall"]["total"] == 1


def test_recall_kismi_dogru_tam_puan_almaz():
    m = _modul()
    qs = [_q("S1", ["D01", "D07"])]
    out = m.score([_r("S1", docs=[("D01", "D02")])], qs)
    assert out["recall"]["per_question"] == {"S1": 0}


def test_recall_birden_cok_aramanin_ilk_bes_sonucu_birlesir():
    m = _modul()
    qs = [_q("S3", ["D01", "D07"])]
    rec = _r("S3", docs=[("D01", "D02"), ("D07", "D03")])
    out = m.score([rec], qs)
    assert out["recall"]["per_question"] == {"S3": 1}


def test_recall_yalnizca_ilk_bes_sonuc_sayilir():
    m = _modul()
    qs = [_q("S1", ["D09"])]
    rec = _r("S1", docs=[("D01", "D02", "D03", "D04", "D05", "D09")])
    out = m.score([rec], qs)
    assert out["recall"]["per_question"] == {"S1": 0}


def test_recall_hic_arama_yoksa_sifir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", docs=[], citations=[])
    out = m.score([rec], qs)
    assert out["recall"]["per_question"] == {"S1": 0}


def test_recall_yalnizca_cevaplanabilir_sorulari_kapsar():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    out = m.score([_r("S1"), _ret("U1")], qs)
    assert set(out["recall"]["per_question"]) == {"S1"}
    assert out["recall"]["total"] == 1


# ---------------------------------------------------------- cevaplanabilirlik


def test_ret_sabit_cumle_ve_atifsiz_ise_retdir():
    m = _modul()
    qs = [_q("U1", [], answerable=False)]
    out = m.score([_ret("U1")], qs)
    assert out["answerability"]["classes"] == {"U1": "ret"}


def test_atifli_ve_ret_cumlesiz_cevap_cevaptir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    out = m.score([_r("S1")], qs)
    assert out["answerability"]["classes"] == {"S1": "cevap"}


def test_ret_cumlesi_atifla_birlikteyse_belirsiz():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer=f"{RET} Ama bir şey var [D01#01].")
    out = m.score([rec], qs)
    assert out["answerability"]["classes"] == {"S1": "belirsiz"}


def test_atifsiz_ve_ret_cumlesiz_cevap_belirsiz():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer="Süre 5 dakikadır.", citations=[])
    out = m.score([rec], qs)
    assert out["answerability"]["classes"] == {"S1": "belirsiz"}


def test_u_sorularinda_ret_sayisi_ve_gereksiz_ret_sayisi():
    m = _modul()
    qs = [
        _q("S1", ["D01"]),
        _q("S2", ["D01"]),
        _q("U1", [], answerable=False),
        _q("U2", [], answerable=False),
        _q("U3", [], answerable=False),
    ]
    recs = [
        _r("S1"),
        _ret("S2"),  # gereksiz ret
        _ret("U1"),
        _ret("U2"),
        _r("U3", answer="Tayfun için ... [D01#01]."),  # uydurma cevap
    ]
    a = m.score(recs, qs)["answerability"]
    assert a["u_ret"] == 2
    assert a["u_total"] == 3
    assert a["s_gereksiz_ret"] == 1
    assert a["s_total"] == 2
    assert a["belirsiz"] == 0


def test_belirsiz_ne_dogru_ne_yanlis_sayilir_ayri_gosterilir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    recs = [
        _r("S1", answer="Süre 5 dakikadır.", citations=[]),  # belirsiz
        _r("U1", answer="Bilmiyorum.", citations=[]),  # belirsiz
    ]
    a = m.score(recs, qs)["answerability"]
    assert a["belirsiz"] == 2
    assert a["u_ret"] == 0
    assert a["s_gereksiz_ret"] == 0


# ---------------------------------------------------------- citation precision


def test_citation_precision_beklenen_belge_atiflari_toplam_atifa_bolunur():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S3", ["D01", "D07"])]
    recs = [
        _r(
            "S1",
            citations=[_c("D01#01", "D01"), _c("D05#01", "D05")],
        ),
        _r(
            "S3",
            citations=[_c("D01#02", "D01"), _c("D07#01", "D07")],
        ),
    ]
    p = m.score(recs, qs)["citation_precision"]
    assert p["dogru"] == 3
    assert p["toplam"] == 4
    assert p["oran"] == pytest.approx(0.75)


def test_citation_precision_atiflar_sorular_arasinda_havuzlanir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S4", ["D03"])]
    recs = [
        _r("S1", citations=[_c("D01#01", "D01")]),
        _r("S4", citations=[_c("D02#01", "D02")] * 3),
    ]
    p = m.score(recs, qs)["citation_precision"]
    assert (p["dogru"], p["toplam"]) == (1, 4)
    assert p["oran"] == pytest.approx(0.25)


def test_citation_precision_dogrulanamayan_atif_paydada_sayilir_payda_degil():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r(
        "S1",
        citations=[_c("D01#01", "D01"), _c("D99#01", None, dogrulandi=False)],
    )
    p = m.score([rec], qs)["citation_precision"]
    assert (p["dogru"], p["toplam"]) == (1, 2)


def test_citation_precision_u_sorulari_havuza_girmez():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    recs = [
        _r("S1"),
        _r("U1", answer="Cevap [D05#01].", citations=[_c("D05#01", "D05")]),
    ]
    p = m.score(recs, qs)["citation_precision"]
    assert (p["dogru"], p["toplam"]) == (1, 1)


def test_citation_precision_hic_atif_yoksa_oran_yok():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer=RET, citations=[])
    p = m.score([rec], qs)["citation_precision"]
    assert p["toplam"] == 0
    assert p["oran"] is None


# ------------------------------------------------------------- eski sürüm


def test_eski_surum_atfi_superseded_olmayan_sorularda_sayilir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S4", ["D03"])]
    recs = [
        _r(
            "S1",
            citations=[
                _c("D01#01", "D01", status="superseded"),
                _c("D01#02", "D01"),
            ],
        ),
        _r("S4", citations=[_c("D03#01", "D03", status="superseded")]),
    ]
    out = m.score(recs, qs)
    assert out["eski_surum"]["hedef"] == 2


def test_eski_surum_include_superseded_true_sorusu_skora_girmez_ayri_sayilir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S2", ["D02", "D03"], sup=True)]
    recs = [
        _r("S1"),
        _r(
            "S2",
            citations=[
                _c("D02#01", "D02", status="superseded"),
                _c("D03#01", "D03"),
            ],
        ),
    ]
    out = m.score(recs, qs)
    assert out["eski_surum"]["hedef"] == 0
    assert out["eski_surum"]["beklenen"] == 1


def test_eski_surum_dogrulanamayan_atif_sayilmaz():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", citations=[_c("D01#09", None, dogrulandi=False)])
    out = m.score([rec], qs)
    assert out["eski_surum"]["hedef"] == 0


# ------------------------------------------------- atıfsız cümle / doğrulanamayan


def test_atifsiz_cumle_orani_ret_olmayan_cevaplarda_hesaplanir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r(
        "S1",
        answer="Birinci cümle [D01#01]. İkinci cümle atıfsız. Üçüncü [D01#02].",
        citations=[_c("D01#01", "D01"), _c("D01#02", "D01")],
    )
    a = m.score([rec], qs)["atifsiz"]
    assert a["toplam_cumle"] == 3
    assert a["atifsiz_cumle"] == 1


def test_atifsiz_cumle_ret_cevaplari_hesaba_girmez():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    recs = [
        _r("S1", answer="Tek cümle [D01#01]."),
        _ret("U1"),
    ]
    a = m.score(recs, qs)["atifsiz"]
    assert a["toplam_cumle"] == 1
    assert a["atifsiz_cumle"] == 0


def test_atifsiz_cumle_belirsiz_cevaplar_dahildir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer="Süre 5 dakikadır. Fazlası yok.", citations=[])
    a = m.score([rec], qs)["atifsiz"]
    assert (a["atifsiz_cumle"], a["toplam_cumle"]) == (2, 2)


def test_cumle_bolme_nokta_unlem_ve_soru_isaretinden_basitce_yapilir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer="Bir [D01#01]! İki mi? Üç.", citations=[_c("D01#01", "D01")])
    a = m.score([rec], qs)["atifsiz"]
    assert a["toplam_cumle"] == 3
    assert a["atifsiz_cumle"] == 2


def test_dogrulanamayan_atif_orani_citation_olayindan_gelir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S4", ["D03"])]
    recs = [
        _r(
            "S1",
            citations=[
                _c("D01#01", "D01"),
                _c("D99#01", None, dogrulandi=False),
            ],
        ),
        _r("S4", citations=[_c("D03#01", "D03"), _c("D03#02", "D03")]),
    ]
    a = m.score(recs, qs)["atifsiz"]
    assert a["dogrulanamayan"] == 1
    assert a["toplam_atif"] == 4


def test_atiflar_u_sorularindan_da_dogrulanamayan_sayisina_girer():
    m = _modul()
    qs = [_q("U1", [], answerable=False)]
    rec = _r(
        "U1",
        answer="Uydurma [D99#01].",
        citations=[_c("D99#01", None, dogrulandi=False)],
    )
    a = m.score([rec], qs)["atifsiz"]
    assert (a["dogrulanamayan"], a["toplam_atif"]) == (1, 1)


# ------------------------------------------------------------ soru bazında satır


def test_satirlar_soru_sirasiyla_gerekli_alanlari_tasir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("S2", ["D02"], sup=True)]
    recs = [
        _r("S2", docs=[("D02",)], citations=[_c("D02#01", "D02", status="superseded")]),
        _r("S1"),
    ]
    rows = m.score(recs, qs)["rows"]
    assert [r["id"] for r in rows] == ["S1", "S2"]
    assert rows[0]["recall_tam"] is True
    assert rows[0]["ret_sinifi"] == "cevap"
    assert rows[0]["belgeler"] == ["D01"]
    assert rows[0]["eski_surum_atfi"] is False
    assert rows[1]["eski_surum_atfi"] is True


def test_satirda_u_sorusu_icin_recall_tam_bos_ve_ret_sinifi_yazilir():
    m = _modul()
    qs = [_q("U1", [], answerable=False)]
    rows = m.score([_ret("U1")], qs)["rows"]
    assert len(rows) == 1
    assert rows[0]["ret_sinifi"] == "ret"
    assert rows[0]["recall_tam"] is None
    assert rows[0]["belgeler"] == []


# ------------------------------------------------------------ saflık / gerçek set


def test_score_ham_kaydi_degistirmez_ve_tekrarlanabilir():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    recs = [_r("S1"), _ret("U1")]
    once = copy.deepcopy(recs)
    first = m.score(recs, qs)
    second = m.score(recs, qs)
    assert recs == once
    assert first == second


def test_gercek_soru_setinde_kusursuz_kayitlar_tam_skor_verir():
    m = _modul()
    data = json.loads(
        (ROOT / "eval" / "kaynakli_sorulari.json").read_text(encoding="utf-8")
    )
    assert len(data) == 10
    recs = []
    for q in data:
        if q["cevaplanabilir"]:
            docs = q["beklenen_belgeler"]
            cits = [_c(f"{d}#01", d) for d in docs]
            tags = " ".join(f"[{d}#01]" for d in docs)
            recs.append(
                _r(q["id"], answer=f"Yanıt {tags}.", docs=[docs], citations=cits)
            )
        else:
            recs.append(_ret(q["id"]))
    out = m.score(recs, data)
    assert out["recall"]["hit"] == 7
    assert out["recall"]["total"] == 7
    a = out["answerability"]
    assert (a["u_ret"], a["u_total"]) == (3, 3)
    assert (a["s_gereksiz_ret"], a["s_total"], a["belirsiz"]) == (0, 7, 0)
    assert out["citation_precision"]["oran"] == pytest.approx(1.0)
    assert out["eski_surum"]["hedef"] == 0
    assert out["atifsiz"]["atifsiz_cumle"] == 0
    assert out["atifsiz"]["dogrulanamayan"] == 0
    assert len(out["rows"]) == 10


# ------------------------------------------------------------------ rapor


def _rapor():
    m = _modul()
    qs = [_q("S1", ["D01"]), _q("U1", [], answerable=False)]
    return m.render(m.score([_r("S1"), _ret("U1")], qs))


def test_rapor_son_metrigi_belgedeki_adla_yazar():
    text = _rapor()
    assert "atıfsız cümle / doğrulanamayan atıf oranı" in text
    assert "unsupported claim" not in text.lower()


def test_rapor_bes_metrigin_basligini_icerir():
    text = _rapor()
    for baslik in (
        "recall@5",
        "Cevaplanabilirlik",
        "Citation precision",
        "Eski sürüm kullanımı",
        "atıfsız cümle / doğrulanamayan atıf oranı",
    ):
        assert baslik in text, baslik


def test_rapor_sabit_iki_notu_en_altta_verir():
    text = _rapor().rstrip()
    not1 = (
        "Cümle düzeyinde destek denetimi bu eğitimde ölçülmemiştir, "
        "sonraki adım olarak LLM ile notlama önerilir."
    )
    not2 = (
        "Skor on soruda hesaplanmıştır; her cevaplanabilir soru recall'ı "
        "yaklaşık 14 puan oynatır. Küçük farklar değil belirgin düşüşler "
        "okunmalıdır."
    )
    assert not1 in text
    assert not2 in text
    assert text.index(not1) < text.index(not2)
    assert text.endswith(not2)
    # soru satırları notlardan önce gelir
    assert text.index("S1") < text.index(not1)
    assert text.index("U1") < text.index(not1)


def test_rapor_belirsiz_sayisini_ayri_gosterir():
    m = _modul()
    qs = [_q("S1", ["D01"])]
    rec = _r("S1", answer="Süre 5 dakikadır.", citations=[])
    text = m.render(m.score([rec], qs))
    assert "belirsiz" in text.lower()
