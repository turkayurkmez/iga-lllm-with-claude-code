"""Eval ölçütleri sözleşme testleri (docs/eval.md › Ölçütler, Metne çevirme, Eşleşme).

Testler koddan önce yazıldı; eval.criteria yokken kırmızıdır. Koşu kayıtları sahte
AgentResult.model_dump() sözlükleridir (docs/agent.md › Sonuç); model, ağ ve veri
dosyası kullanılmaz. Değer referansları önceden çözülmüş verilir.
"""

import importlib
import importlib.util

import pytest

GECTI, KALDI, UYGULANMAZ = "geçti", "kaldı", "uygulanmaz"
CRITERIA = ["durum", "tool", "arguman", "deger", "uydurmama", "netlestirme"]


@pytest.fixture
def criteria():
    return importlib.import_module("eval.criteria")


def call(name, input_, executed=True):
    return {
        "id": f"toolu_{name}",
        "name": name,
        "input": input_,
        "executed": executed,
        "envelope": {} if executed else None,
    }


def result(text, *calls, status="tamam"):
    turns = [
        {"index": 1, "stop_reason": "tool_use", "tool_calls": list(calls)},
        {"index": 2, "stop_reason": "end_turn", "tool_calls": []},
    ]
    return {
        "status": status,
        "reason": None if status == "tamam" else "neden",
        "text": text,
        "turns": turns,
        "instruction": {"name": "v1", "version": "1.0.0", "summary": "0" * 64},
    }


def question(**fields):
    base = {
        "id": "G99",
        "category": "ozet",
        "behavior": "cevap",
        "question": "Soru?",
        "tools": [],
    }
    return base | fields


SUMMARY = call("get_flight_summary", {"direction": "all"})
RESOLVE = call("resolve_flight_identity", {"query": "TK2345"})
DETAILS = call("get_flight_details", {"flight_id": "FL-20261020-0270"})


def calc(name="x"):
    return {"calc": name, "params": {}}


def evaluate(criteria, q, res, expect=(), forbid=()):
    return criteria.evaluate(q, list(expect), list(forbid), res)


# --- Modül ---


def test_modul_var():
    assert importlib.util.find_spec("eval") is not None
    assert importlib.util.find_spec("eval.criteria") is not None


def test_sonuc_alanlari_ve_olcut_sirasi(criteria):
    out = evaluate(criteria, question(), result("Cevap."))
    assert set(out) == {"criteria", "missing", "found_forbidden", "passed"}
    assert list(out["criteria"]) == CRITERIA
    assert tuple(criteria.CRITERIA) == tuple(CRITERIA)


# --- durum ---


@pytest.mark.parametrize(
    ("status", "verdict"),
    [
        ("tamam", GECTI),
        ("max_tokens", KALDI),
        ("durduruldu", KALDI),
        ("tekrar_siniri", KALDI),
        ("iterasyon_siniri", KALDI),
    ],
)
def test_durum_yalnizca_tamamda_gecer(criteria, status, verdict):
    out = evaluate(criteria, question(), result("Metin.", status=status))
    assert out["criteria"]["durum"] == verdict


# --- tool ---


def test_tool_kume_tam_esit_gecer(criteria):
    q = question(tools=["resolve_flight_identity", "get_flight_details"])
    out = evaluate(criteria, q, result("x", DETAILS, RESOLVE))
    assert out["criteria"]["tool"] == GECTI


def test_tool_tekrar_eden_cagri_kumeyi_degistirmez(criteria):
    retry = call("get_flight_summary", {"direction": "ALL"})
    q = question(tools=["get_flight_summary"])
    out = evaluate(criteria, q, result("x", retry, SUMMARY))
    assert out["criteria"]["tool"] == GECTI


def test_tool_fazla_cagri_kalir(criteria):
    q = question(tools=["resolve_flight_identity"])
    out = evaluate(criteria, q, result("x", RESOLVE, DETAILS))
    assert out["criteria"]["tool"] == KALDI


def test_tool_eksik_cagri_kalir(criteria):
    q = question(tools=["resolve_flight_identity", "get_flight_details"])
    out = evaluate(criteria, q, result("x", RESOLVE))
    assert out["criteria"]["tool"] == KALDI


def test_tool_calismamis_cagri_sayilmaz(criteria):
    q = question(tools=["resolve_flight_identity"])
    unexecuted = call("get_flight_details", {"flight_id": "x"}, executed=False)
    out = evaluate(criteria, q, result("x", RESOLVE, unexecuted))
    assert out["criteria"]["tool"] == GECTI


def test_tool_bos_liste_hic_cagri_yoksa_gecer(criteria):
    out = evaluate(criteria, question(tools=[]), result("Kapsam dışı."))
    assert out["criteria"]["tool"] == GECTI


def test_tool_bos_listede_cagri_varsa_kalir(criteria):
    out = evaluate(criteria, question(tools=[]), result("x", RESOLVE))
    assert out["criteria"]["tool"] == KALDI


def test_tool_durum_tamam_degilken_de_degerlendirilir(criteria):
    q = question(tools=["get_flight_summary"])
    out = evaluate(criteria, q, result("", SUMMARY, status="tekrar_siniri"))
    assert out["criteria"]["tool"] == GECTI


# --- arguman ---


def test_arguman_args_yoksa_uygulanmaz(criteria):
    out = evaluate(criteria, question(), result("x"))
    assert out["criteria"]["arguman"] == UYGULANMAZ


def test_arguman_kanonik_json_esitligi(criteria):
    args = [{"name": "t", "input": {"a": 1, "b": {"c": 2, "d": 3}}}]
    q = question(tools=["t"], args=args)
    out = evaluate(criteria, q, result("x", call("t", {"b": {"d": 3, "c": 2}, "a": 1})))
    assert out["criteria"]["arguman"] == GECTI


def test_arguman_farkli_deger_kalir(criteria):
    args = [{"name": "get_flight_summary", "input": {"direction": "arrival"}}]
    q = question(tools=["get_flight_summary"], args=args)
    out = evaluate(criteria, q, result("x", SUMMARY))
    assert out["criteria"]["arguman"] == KALDI


def test_arguman_ayni_input_baska_tool_kalir(criteria):
    args = [{"name": "get_flight_summary", "input": {"query": "TK2345"}}]
    q = question(tools=["get_flight_summary"], args=args)
    out = evaluate(criteria, q, result("x", RESOLVE))
    assert out["criteria"]["arguman"] == KALDI


def test_arguman_calismamis_cagri_sayilmaz(criteria):
    args = [{"name": "get_flight_summary", "input": {"direction": "all"}}]
    q = question(tools=["get_flight_summary"], args=args)
    unexecuted = call("get_flight_summary", {"direction": "all"}, executed=False)
    out = evaluate(criteria, q, result("x", unexecuted))
    assert out["criteria"]["arguman"] == KALDI


def test_arguman_her_oge_aranir(criteria):
    args = [
        {"name": "get_flight_summary", "input": {"direction": "all"}},
        {"name": "get_flight_summary", "input": {"direction": "arrival"}},
    ]
    q = question(tools=["get_flight_summary"], args=args)
    out = evaluate(criteria, q, result("x", SUMMARY))
    assert out["criteria"]["arguman"] == KALDI


# --- deger ---


def test_deger_expect_yoksa_uygulanmaz(criteria):
    out = evaluate(criteria, question(), result("x"))
    assert out["criteria"]["deger"] == UYGULANMAZ
    assert out["missing"] == []


def test_deger_hepsi_bulunursa_gecer(criteria):
    q = question(expect=[calc(), calc()])
    expect = [(calc(), 600), (calc(), "R236")]
    out = evaluate(criteria, q, result("Bugün 600 uçuş var; stand R236."), expect)
    assert out["criteria"]["deger"] == GECTI
    assert out["missing"] == []


def test_deger_eksik_deger_listelenir(criteria):
    expect = [(calc(), 600), (calc(), 115)]
    out = evaluate(criteria, question(), result("Bugün 600 uçuş var."), expect)
    assert out["criteria"]["deger"] == KALDI
    assert out["missing"] == ["115"]


def test_deger_listenin_her_ogesi_bulunmali(criteria):
    expect = [(calc(), ["TK2344", "TK2345"])]
    out = evaluate(criteria, question(), result("Aday: TK2345. Hangisi?"), expect)
    assert out["criteria"]["deger"] == KALDI
    assert out["missing"] == ["TK2344"]


def test_deger_durum_tamam_degilse_kalir(criteria):
    expect = [(calc(), 600)]
    out = evaluate(criteria, question(), result("600", status="max_tokens"), expect)
    assert out["criteria"]["deger"] == KALDI


# --- uydurmama ---


def test_uydurmama_forbid_yoksa_uygulanmaz(criteria):
    out = evaluate(criteria, question(), result("x"))
    assert out["criteria"]["uydurmama"] == UYGULANMAZ
    assert out["found_forbidden"] == []


def test_uydurmama_yasak_deger_yoksa_gecer(criteria):
    forbid = [(calc(), 596)]
    out = evaluate(criteria, question(), result("600 uçuş, 4 iptal."), forbid=forbid)
    assert out["criteria"]["uydurmama"] == GECTI


def test_uydurmama_yasak_deger_bulunursa_kalir(criteria):
    forbid = [(calc(), 596), (calc(), ["BUS4", "A1"])]
    text = "İptal olmayan 596 uçuş var; gate BUS4."
    out = evaluate(criteria, question(), result(text), forbid=forbid)
    assert out["criteria"]["uydurmama"] == KALDI
    assert out["found_forbidden"] == ["596", "BUS4"]


def test_uydurmama_durum_tamam_degilse_kalir(criteria):
    forbid = [(calc(), 596)]
    res = result("x", status="durduruldu")
    out = evaluate(criteria, question(), res, forbid=forbid)
    assert out["criteria"]["uydurmama"] == KALDI


# --- netlestirme ---


def test_netlestirme_asks_yoksa_uygulanmaz(criteria):
    out = evaluate(criteria, question(), result("x?"))
    assert out["criteria"]["netlestirme"] == UYGULANMAZ


def test_netlestirme_soru_isareti_ister(criteria):
    q = question(asks=True)
    assert evaluate(criteria, q, result("Hangisi?"))["criteria"]["netlestirme"] == GECTI
    assert evaluate(criteria, q, result("Hangisi."))["criteria"]["netlestirme"] == KALDI


def test_netlestirme_durum_tamam_degilse_kalir(criteria):
    q = question(asks=True)
    out = evaluate(criteria, q, result("Hangisi?", status="tekrar_siniri"))
    assert out["criteria"]["netlestirme"] == KALDI


# --- passed ---


def test_gecer_uygulanan_olcutlerin_hepsi_gecince(criteria):
    q = question(tools=["get_flight_summary"], expect=[calc()])
    out = evaluate(criteria, q, result("600 uçuş.", SUMMARY), [(calc(), 600)])
    assert out["passed"] is True


def test_tek_olcut_kalirsa_gecmez(criteria):
    q = question(tools=["get_flight_summary"], expect=[calc()])
    out = evaluate(criteria, q, result("599 uçuş.", SUMMARY), [(calc(), 600)])
    assert out["passed"] is False


def test_tamam_olmayan_kosu_gecmez(criteria):
    q = question(tools=["get_flight_summary"])
    out = evaluate(criteria, q, result("", SUMMARY, status="iterasyon_siniri"))
    assert out["passed"] is False


# --- Metne çevirme ---


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        (25, ["25"]),
        (1200, ["1200"]),
        ("2026-10-20T16:05:00+03:00", ["16:05"]),
        ("2026-10-20T13:05:00+00:00", ["16:05"]),  # +03:00'e çevrilir
        (41.05, ["41.05", "41,05"]),
        ("R236", ["R236"]),
        ("93", ["93"]),
    ],
)
def test_metne_cevirme(criteria, value, rendered):
    assert criteria.render(calc(), value) == rendered


def test_metne_cevirme_literal_oldugu_gibi(criteria):
    assert criteria.render({"literal": "ZZ9999"}, "ZZ9999") == ["ZZ9999"]


def test_ondalik_virgulle_de_bulunur(criteria):
    expect = [(calc(), 41.05)]
    out = evaluate(criteria, question(), result("Konum 41,05 kuzey."), expect)
    assert out["criteria"]["deger"] == GECTI


def test_zaman_hhmm_olarak_aranir(criteria):
    expect = [(calc(), "2026-10-20T16:05:00+03:00")]
    out = evaluate(criteria, question(), result("Tahmini kalkış 16:05."), expect)
    assert out["criteria"]["deger"] == GECTI


def test_zaman_ham_damga_degil(criteria):
    expect = [(calc(), "2026-10-20T16:05:00+03:00")]
    out = evaluate(criteria, question(), result("Saat 1605."), expect)
    assert out["missing"] == ["16:05"]


# --- Eşleşme ---


@pytest.mark.parametrize(
    ("value", "text", "found"),
    [
        (4, "4 uçuş iptal.", True),
        (4, "TK2345 seferi.", False),  # başka sayının içinde
        (4, "Saat 16:04.", False),
        ("A1", "Gate A12.", False),
        ("A1", "Gate A1'de.", True),  # kesme işareti sınırdır
        ("TK2345", "TK2345'in gate'i.", True),
        ("TK2345", "TK23456 değil.", False),
        ("R236", "r236", False),  # kod büyük/küçük harfe duyarlı
        (600, "(600)", True),
        ("2026-10-20T16:05:00+03:00", "16:05'te", True),
        ("2026-10-20T16:05:00+03:00", "16:055", False),
        (41.05, "41.051", False),
    ],
)
def test_eslesme_sinirlari(criteria, value, text, found):
    out = evaluate(criteria, question(), result(text), [(calc(), value)])
    assert (out["missing"] == []) is found


@pytest.mark.parametrize(
    ("literal", "text", "found"),
    [
        ("iptal", "Uçuş İPTAL edildi.", True),
        ("iptal", "İptal edildi.", True),
        ("iptal", "Uçuş iptaldir.", True),  # Türkçe ek: sağ sınır aranmaz
        ("iptal", "Uçuş iptali.", True),
        ("iptal", "Kriptal.", False),  # sol sınır aranır
        ("ırmak", "IRMAK", True),  # I → ı
        ("ZZ9999", "ZZ9999 bulunamadı.", True),
        ("ZZ9999", "zz9999 bulunamadı.", False),  # rakamlı literal: tam yazım
        ("ZZ9999", "ZZ99990 bulunamadı.", False),
    ],
)
def test_eslesme_literal(criteria, literal, text, found):
    ref = {"literal": literal}
    out = evaluate(criteria, question(), result(text), [(ref, literal)])
    assert (out["missing"] == []) is found


# --- summarize ---


def run(id_, passed, category="ozet", repeat=1, error=None, **verdicts):
    crit = {name: verdicts.get(name, UYGULANMAZ) for name in CRITERIA}
    return {
        "id": id_,
        "repeat": repeat,
        "category": category,
        "criteria": {} if error else crit,
        "passed": passed,
        "error": error,
    }


def test_ozet_golden_skor(criteria):
    runs = [
        run("G01", True, durum=GECTI),
        run("G02", False, durum=KALDI),
        run("G03", True, durum=GECTI),
        run("G04", False, error="api_hatasi"),
    ]
    out = criteria.summarize(runs)
    assert set(out) == {"score", "criteria", "categories", "stable"}
    assert out["score"] == {"passed": 2, "total": 4, "ratio": 0.5}


def test_ozet_olcut_orani_uygulanmazi_saymaz(criteria):
    runs = [
        run("G01", True, durum=GECTI, deger=GECTI),
        run("G02", False, durum=GECTI, deger=KALDI),
        run("G03", True, durum=GECTI),
    ]
    out = criteria.summarize(runs)
    assert list(out["criteria"]) == CRITERIA
    assert out["criteria"]["durum"] == {"passed": 3, "total": 3, "ratio": 1.0}
    assert out["criteria"]["deger"] == {"passed": 1, "total": 2, "ratio": 0.5}
    assert out["criteria"]["arguman"] == {"passed": 0, "total": 0, "ratio": None}


def test_ozet_hata_kosusu_olcut_oranina_girmez(criteria):
    runs = [
        run("G01", True, durum=GECTI),
        run("G02", False, error="hesap_hatasi"),
    ]
    out = criteria.summarize(runs)
    assert out["criteria"]["durum"]["total"] == 1
    assert out["score"]["total"] == 2


def test_ozet_kategori_skoru(criteria):
    runs = [
        run("G01", True, category="ozet"),
        run("G02", False, category="ozet"),
        run("G13", True, category="bozulma"),
    ]
    out = criteria.summarize(runs)
    assert out["categories"] == {
        "bozulma": {"passed": 1, "total": 1, "ratio": 1.0},
        "ozet": {"passed": 1, "total": 2, "ratio": 0.5},
    }
    assert list(out["categories"]) == ["bozulma", "ozet"]


def test_ozet_kararli_soru_tum_tekrarlarda_gecer(criteria):
    runs = [
        run("G01", True, repeat=1),
        run("G01", True, repeat=2),
        run("G02", True, repeat=1),
        run("G02", False, repeat=2),
        run("G03", False, repeat=1, error="api_hatasi"),
        run("G03", False, repeat=2, error="api_hatasi"),
    ]
    out = criteria.summarize(runs)
    assert out["stable"] == {"stable": 1, "questions": 3}


def test_ozet_bos_kosu_listesi(criteria):
    out = criteria.summarize([])
    assert out["score"] == {"passed": 0, "total": 0, "ratio": None}
    assert out["stable"] == {"stable": 0, "questions": 0}
    assert out["categories"] == {}
