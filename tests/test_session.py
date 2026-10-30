"""Oturum deposu ve geçmiş çevirici (docs/superpowers/specs/2026-10-30-…-design.md › A).

Saat COPILOT_NOW ile sabitlenir; sistem saatine bağlı test yoktur. Ağ ve model yok.
"""

import importlib
import importlib.util
import re
import threading
from datetime import datetime, timedelta

import pytest

START = datetime.fromisoformat("2026-10-20T16:22:00+03:00")


def load():
    assert importlib.util.find_spec("backend.session") is not None, (
        "backend.session yok"
    )
    return importlib.import_module("backend.session")


def set_now(monkeypatch, moment: datetime) -> None:
    monkeypatch.setenv("COPILOT_NOW", moment.isoformat())


@pytest.fixture(autouse=True)
def sabit_saat(monkeypatch):
    set_now(monkeypatch, START)


def make_turn(question="Soru", answer="Cevap", tool_calls=None) -> dict:
    return {"question": question, "answer": answer, "tool_calls": tool_calls or []}


def test_modul_var():
    assert load() is not None


def test_bos_session_id_yeni_oturum_acar():
    session = load()
    store = session.SessionStore()

    begin = store.begin(None)

    assert begin.reset is False
    assert begin.turn_index == 1
    assert re.fullmatch(session.SESSION_ID_PATTERN, begin.session_id)


def test_bilinmeyen_id_yeni_oturum_ve_reset():
    store = load().SessionStore()

    begin = store.begin("a" * 32)

    assert begin.reset is True
    assert begin.session_id != "a" * 32
    assert begin.turn_index == 1


def test_bilinen_id_ayni_oturumu_surdurur():
    store = load().SessionStore()
    first = store.begin(None)
    store.add(first.session_id, make_turn())

    second = store.begin(first.session_id)

    assert second.session_id == first.session_id
    assert second.reset is False
    assert second.turn_index == 2


def test_iki_saat_hareketsizlikte_oturum_dolar(monkeypatch):
    store = load().SessionStore()
    first = store.begin(None)
    store.add(first.session_id, make_turn())

    set_now(monkeypatch, START + timedelta(hours=1, minutes=59))
    assert store.begin(first.session_id).reset is False

    # Son kullanım 1 sa 59 dk'daki begin'dir; ondan 2 saat 1 sn sonrası süreyi aşar.
    set_now(
        monkeypatch,
        START + timedelta(hours=1, minutes=59) + timedelta(hours=2, seconds=1),
    )
    assert store.begin(first.session_id).reset is True


def test_en_eski_kullanilan_oturum_atilir():
    store = load().SessionStore(max_sessions=2)
    first = store.begin(None)
    second = store.begin(None)
    store.add(first.session_id, make_turn())
    store.add(second.session_id, make_turn())
    # İlk oturuma dokunulur; en eski kullanılan ikinci olur.
    store.begin(first.session_id)

    store.begin(None)

    assert store.begin(first.session_id).reset is False
    assert store.begin(second.session_id).reset is True


def test_oturum_basina_en_fazla_yirmi_tur_saklanir():
    store = load().SessionStore()
    begin = store.begin(None)
    for number in range(25):
        store.add(begin.session_id, make_turn(question=f"S{number}"))

    assert store.begin(begin.session_id).turn_index == 21


def test_modele_son_alti_tur_gider_eskiden_yeniye():
    store = load().SessionStore()
    begin = store.begin(None)
    for number in range(8):
        store.add(begin.session_id, make_turn(question=f"S{number}"))

    history = store.history(begin.session_id)

    assert [turn["question"] for turn in history] == [f"S{n}" for n in range(2, 8)]


def test_toplam_karakter_butcesi_asilirsa_en_eski_tur_tamamen_atilir():
    store = load().SessionStore()
    begin = store.begin(None)
    for number in range(3):
        store.add(begin.session_id, make_turn(question=f"S{number}", answer="x" * 5000))

    history = store.history(begin.session_id)

    assert [turn["question"] for turn in history] == ["S1", "S2"]
    assert all(len(turn["answer"]) == 5000 for turn in history)


def test_butceyi_tek_basina_asan_tur_modele_hic_gitmez():
    store = load().SessionStore()
    begin = store.begin(None)
    store.add(begin.session_id, make_turn(answer="x" * 12001))

    assert store.history(begin.session_id) == []
    # Kayıt durur: sıradaki tur ikinci turdur.
    assert store.begin(begin.session_id).turn_index == 2


def test_history_kopya_doner_depoyu_degistirmez():
    store = load().SessionStore()
    begin = store.begin(None)
    store.add(begin.session_id, make_turn())

    store.history(begin.session_id).clear()

    assert len(store.history(begin.session_id)) == 1


def test_render_history_metin_turlari_ve_arac_notu():
    session = load()
    turns = [
        make_turn(
            question="Gelenleri grafikle göster",
            answer="Hangi tür?",
            tool_calls=[{"name": "get_chart_data", "input": {"group_by": "airline"}}],
        ),
        make_turn(question="Pasta", answer="Çizdim."),
    ]

    messages = session.render_history(turns)

    assert messages == [
        {"role": "user", "content": "Gelenleri grafikle göster"},
        {
            "role": "assistant",
            "content": 'Hangi tür?\n\n[Önceki turda çağrılan araçlar: get_chart_data {"group_by":"airline"}]',
        },
        {"role": "user", "content": "Pasta"},
        {"role": "assistant", "content": "Çizdim."},
    ]


def test_render_history_turkce_karakter_kacissiz():
    session = load()
    turns = [make_turn(tool_calls=[{"name": "t", "input": {"x": "İş"}}])]

    content = session.render_history(turns)[1]["content"]

    assert "İş" in content
    assert "\\u" not in content


def test_eszamanli_ekleme_tur_kaybetmez_ve_bozulmaz():
    store = load().SessionStore()
    begin = store.begin(None)
    errors: list[Exception] = []

    def worker() -> None:
        try:
            for _ in range(10):
                store.add(begin.session_id, make_turn())
        except Exception as exc:  # noqa: BLE001 - test iş parçacığı hatayı toplar
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert store.begin(begin.session_id).turn_index == 21
