"""focus_map_object ve highlight_map_set sözleşmesi (docs/harita.md).

Testler koddan önce yazıldı; tool'lar yokken kırmızıdır. Uçuş kontrolü canlı depodan
yapılır: depo `backend.live.LiveHub`'a mesajlar doğrudan verilerek kurulur, ağa
çıkılmaz. Stand kontrolü COPILOT_DATA'daki `stands` dizisindendir.
"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from backend import live
from backend.tools import run_tool, tool_definitions

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = REPO_ROOT / "backend" / "tools" / "contracts"
REFERENCE = "data/referans/seed42-2026-10-20.json"
NOW = "2026-10-20T16:22:00+03:00"
VERSION = "1.0.0"
ROOT = "aocc/sim/v1"
TZ = timezone(timedelta(hours=3))
TOOLS = ["focus_map_object", "highlight_map_set"]

NOT_FOUND = {"code": "NOT_FOUND", "message": "Haritada bu nesne için konum yok."}
ARGS_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool argümanları şemaya uymuyor.",
}
DATA_INVALID = {
    "code": "SCHEMA_VALIDATION_FAILED",
    "message": "Tool çıktısı şemaya uymuyor; yanıt üretilemedi.",
}
FORBIDDEN_KEYWORDS = {"minLength", "maxLength", "minimum", "maximum", "multipleOf"}


def at(hh: int, mm: int, ss: int = 0) -> datetime:
    return datetime(2026, 10, 20, hh, mm, ss, tzinfo=TZ)


def epoch(hh: int, mm: int, ss: int = 0) -> int:
    return int(at(hh, mm, ss).timestamp())


def enc(record) -> bytes:
    return json.dumps(record, ensure_ascii=False).encode("utf-8")


def live_position(key="dc110c28", ts=None, flight="TK2345", **fields) -> dict:
    record = {
        "Key": key,
        "Latitude": 40.5,
        "Longitude": 29.0,
        "Track": 90,
        "Speed": 250,
        "LastUpdate": epoch(16, 10) if ts is None else ts,
        "Flight": flight,
        "Onground": False,
    }
    return record | fields


def put_position(hub, record: dict) -> None:
    hub.handle_message(f"{ROOT}/positions/{record['Key']}", enc(record))


def put_clock(hub, ts: int) -> None:
    now = datetime.fromtimestamp(ts, TZ).isoformat()
    hub.handle_message(f"{ROOT}/clock", enc({"now": now, "epoch": ts, "speed": 60}))


def load_contract(name: str) -> dict:
    return json.loads((CONTRACTS / f"{name}.json").read_text(encoding="utf-8"))


def stand_codes() -> list[str]:
    data = json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))
    return sorted(stand["stand_code"] for stand in data["stands"])


def call(name, args) -> dict:
    """run_tool'u çağırır; zarfın JSON'a yazılabildiğini ve 8 alanı taşıdığını denetler."""
    envelope = run_tool(name, args)
    assert json.loads(json.dumps(envelope, ensure_ascii=False)) == envelope
    assert set(envelope) == {
        "value",
        "source",
        "as_of",
        "filters",
        "stale",
        "tool_version",
        "error",
        "author",
    }
    if envelope["author"] == "tool":
        Draft202012Validator(load_contract(name)["value_schema"]).validate(
            envelope["value"]
        )
    return envelope


def tool_envelope(value, filters, error=None, as_of=NOW) -> dict:
    return {
        "value": value,
        "source": REFERENCE,
        "as_of": as_of,
        "filters": filters,
        "stale": False,
        "tool_version": VERSION,
        "error": error,
        "author": "tool",
    }


def layer_envelope(error, filters=None) -> dict:
    return {
        "value": None,
        "source": None,
        "as_of": None,
        "filters": filters if filters is not None else {},
        "stale": False,
        "tool_version": VERSION,
        "error": error,
        "author": "layer",
    }


@pytest.fixture(autouse=True)
def environment(monkeypatch):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_DATA", REFERENCE)
    yield
    # Bir testte açılan canlı mod sonrakine taşınmasın.
    live.deactivate()


@pytest.fixture
def hub():
    created = live.LiveHub(ROOT)
    live.activate(created)
    put_clock(created, epoch(16, 22))
    return created


def write_data(tmp_path: Path, **changes) -> str:
    data = json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            del data[key]
        else:
            data[key] = value
    path = tmp_path / "gun.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


# --- Kontrat ve tool_definitions ----------------------------------------------------


def test_tool_ciftinin_modulu_var():
    assert importlib.util.find_spec("backend.tools") is not None
    names = {definition["name"] for definition in tool_definitions()}
    assert set(TOOLS) <= names


def test_tool_definitions_mevcut_uc_tool_ve_ardindan_iki_harita_tool_u():
    names = [definition["name"] for definition in tool_definitions()]

    assert names == [
        "get_flight_summary",
        "resolve_flight_identity",
        "get_flight_details",
        "focus_map_object",
        "highlight_map_set",
    ]


@pytest.mark.parametrize("name", TOOLS)
def test_kontrat_surumu_ve_semalari_gecerlidir(name):
    contract = load_contract(name)

    assert contract["name"] == name
    assert contract["version"] == VERSION
    Draft202012Validator.check_schema(contract["input_schema"])
    Draft202012Validator.check_schema(contract["value_schema"])


def walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.values():
            yield from walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


@pytest.mark.parametrize("name", TOOLS)
def test_kontrat_yasak_anahtar_kelimeleri_kullanmaz(name):
    contract = load_contract(name)
    for key in ("input_schema", "value_schema"):
        keywords = {k for node in walk(contract[key]) for k in node}
        assert not keywords & FORBIDDEN_KEYWORDS, keywords & FORBIDDEN_KEYWORDS


@pytest.mark.parametrize("name", TOOLS)
def test_kontrattaki_her_nesne_ek_alani_reddeder(name):
    contract = load_contract(name)
    objects = [
        node
        for key in ("input_schema", "value_schema")
        for node in walk(contract[key])
        if node.get("type") == "object"
    ]
    # Hem giriş hem değer şemasında nesne var; liste boşsa döngü de boş geçerdi.
    assert len(objects) >= 2
    assert all(node.get("additionalProperties") is False for node in objects)


@pytest.mark.parametrize("name", TOOLS)
def test_aciklama_uc_bolumu_ve_ornek_deger_icerir(name):
    description = load_contract(name)["description"]

    assert "Ne zaman kullanılır" in description
    assert "Ne zaman KULLANILMAZ" in description
    assert "flight" in description
    assert "stand" in description
    properties = load_contract(name)["input_schema"]["properties"]
    assert properties["object_type"]["enum"] == ["flight", "stand"]
    assert all("examples" in prop for prop in properties.values())


# --- Giriş doğrulaması --------------------------------------------------------------

INVALID_FOCUS = [
    {},
    {"object_type": "stand"},
    {"id": "C101"},
    {"object_type": "stand", "id": "C101", "extra": 1},
    {"object_type": "gate", "id": "C101"},
    {"object_type": "STAND", "id": "C101"},
    {"object_type": None, "id": "C101"},
    {"object_type": "stand", "id": None},
    {"object_type": "stand", "id": 101},
    {"object_type": "stand", "id": ""},
    {"object_type": "stand", "id": " "},
    {"object_type": "stand", "id": "c101"},
    {"object_type": "stand", "id": "C10"},
    {"object_type": "stand", "id": "C1011"},
    {"object_type": "stand", "id": "CC101"},
    {"object_type": "stand", "id": " C101"},
    {"object_type": "stand", "id": "C101\n"},
    {"object_type": "flight", "id": "tk2345"},
    {"object_type": "flight", "id": "TK23"},
    {"object_type": "flight", "id": "TK23456"},
    {"object_type": "flight", "id": "THY2345"},
    {"object_type": "flight", "id": "TC-LSD"},
    {"object_type": "flight", "id": "FL-20261020-0270"},
    {"object_type": "flight", "id": "TK 2345"},
    # Biçim object_type'a göre denetlenir: tip ve kimlik birbirine uymalı.
    {"object_type": "stand", "id": "TK2345"},
    {"object_type": "flight", "id": "C101"},
]


@pytest.mark.parametrize("args", INVALID_FOCUS)
def test_odak_gecersiz_argumanda_sema_hatasi_verir(args):
    assert call("focus_map_object", args) == layer_envelope(ARGS_INVALID)


INVALID_HIGHLIGHT = [
    {},
    {"object_type": "stand"},
    {"ids": ["C101"]},
    {"object_type": "stand", "ids": ["C101"], "extra": 1},
    {"object_type": "gate", "ids": ["C101"]},
    {"object_type": "stand", "ids": "C101"},
    {"object_type": "stand", "ids": None},
    {"object_type": "stand", "ids": [101]},
    {"object_type": "stand", "ids": [None]},
    {"object_type": "stand", "ids": ["c101"]},
    {"object_type": "stand", "ids": ["C101", "THY2345"]},
    {"object_type": "stand", "ids": ["C101", ""]},
    {"object_type": "flight", "ids": ["TK2345", "C101"]},
    {"object_type": "flight", "ids": ["THY2345"]},
    {"object_type": "stand", "ids": ["TK2345"]},
    # Şemanın ötesi: boş küme, 50'yi aşan küme, tekrar.
    {"object_type": "stand", "ids": []},
    {"object_type": "stand", "ids": ["C101", "C102", "C101"]},
    {"object_type": "stand", "ids": ["C101", "C101"]},
]


@pytest.mark.parametrize("args", INVALID_HIGHLIGHT)
def test_vurgu_gecersiz_argumanda_sema_hatasi_verir(args):
    assert call("highlight_map_set", args) == layer_envelope(ARGS_INVALID)


def test_vurgu_elliden_fazla_kimlikte_sema_hatasi_verir():
    ids = [f"C{n:03d}" for n in range(101, 152)]
    assert len(ids) == 51
    args = {"object_type": "stand", "ids": ids}

    assert call("highlight_map_set", args) == layer_envelope(ARGS_INVALID)


@pytest.mark.parametrize("name", TOOLS)
@pytest.mark.parametrize("args", [None, [], "stand", 1])
def test_nesne_olmayan_argumanlar_sema_hatasi_verir(name, args):
    assert call(name, args) == layer_envelope(ARGS_INVALID)


@pytest.mark.parametrize("name", TOOLS)
def test_sema_hatasi_veriyi_okumaz(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))

    assert call(name, {}) == layer_envelope(ARGS_INVALID)


# --- Stand ----------------------------------------------------------------------


def test_stand_odak_komutu_girisin_kopyasidir():
    args = {"object_type": "stand", "id": "C101"}

    assert call("focus_map_object", args) == tool_envelope(
        {"command": "focus_map_object", "object_type": "stand", "id": "C101"}, args
    )


def test_stand_vurgu_komutu_girisin_kopyasidir_ve_sira_korunur():
    args = {"object_type": "stand", "ids": ["C102", "C101", "R201"]}

    assert call("highlight_map_set", args) == tool_envelope(
        {
            "command": "highlight_map_set",
            "object_type": "stand",
            "ids": ["C102", "C101", "R201"],
        },
        args,
    )


def test_musait_olmayan_stand_bulunmus_sayilir():
    data = json.loads((REPO_ROOT / REFERENCE).read_text(encoding="utf-8"))
    unavailable = next(s for s in data["stands"] if s["status"] != "AVAILABLE")
    args = {"object_type": "stand", "id": unavailable["stand_code"]}

    envelope = call("focus_map_object", args)

    assert envelope["error"] is None
    assert envelope["value"]["id"] == unavailable["stand_code"]


def test_vurgu_tam_elli_kimlikle_calisir():
    ids = stand_codes()[:50]
    assert len(ids) == 50
    args = {"object_type": "stand", "ids": ids}

    envelope = call("highlight_map_set", args)

    assert envelope["error"] is None
    assert envelope["value"]["ids"] == ids


def test_olmayan_stand_not_found_doner():
    args = {"object_type": "stand", "id": "Z999"}

    assert call("focus_map_object", args) == tool_envelope(None, args, NOT_FOUND)


def test_vurguda_tek_olmayan_stand_butun_komutu_reddeder():
    args = {"object_type": "stand", "ids": ["C101", "Z999", "C102"]}

    assert call("highlight_map_set", args) == tool_envelope(None, args, NOT_FOUND)


def test_not_found_mesaji_kimligi_icermez():
    envelope = call("focus_map_object", {"object_type": "stand", "id": "Z999"})

    assert "Z999" not in envelope["error"]["message"]


def test_stand_eslesmesi_tam_esitliktir():
    # Biçime uyan ama kayıtta olmayan kimlik; yakın kayıt seçilmez.
    assert "C100" not in stand_codes()
    args = {"object_type": "stand", "id": "C100"}

    assert call("focus_map_object", args)["error"] == NOT_FOUND


def test_stand_denetimi_uc_stand_kaydina_bakar(tmp_path, monkeypatch):
    stands = [{"stand_code": "C101", "status": "UNAVAILABLE"}]
    monkeypatch.setenv("COPILOT_DATA", write_data(tmp_path, stands=stands))

    assert call("focus_map_object", {"object_type": "stand", "id": "C101"})["value"]
    assert (
        call("focus_map_object", {"object_type": "stand", "id": "C102"})["error"]
        == NOT_FOUND
    )


# --- Uçuş (canlı depo) ----------------------------------------------------------


def test_gorunur_konumlu_ucus_odaklanir(hub):
    put_position(hub, live_position())
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args) == tool_envelope(
        {"command": "focus_map_object", "object_type": "flight", "id": "TK2345"},
        args,
    )


def test_ucus_vurgusu_sirayi_korur(hub):
    put_position(hub, live_position(key="a1", flight="TK2345"))
    put_position(hub, live_position(key="b2", flight="TK2344"))
    args = {"object_type": "flight", "ids": ["TK2345", "TK2344"]}

    envelope = call("highlight_map_set", args)

    assert envelope["error"] is None
    assert envelope["value"]["ids"] == ["TK2345", "TK2344"]


def test_uc_haneli_sefer_no_da_gecerlidir(hub):
    put_position(hub, live_position(key="c3", flight="AJ122"))
    args = {"object_type": "flight", "id": "AJ122"}

    assert call("focus_map_object", args)["error"] is None


def test_canli_mod_kapaliyken_ucus_not_found_doner():
    assert live.active() is None
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args) == tool_envelope(None, args, NOT_FOUND)


def test_depoda_olmayan_ucus_not_found_doner(hub):
    put_position(hub, live_position())
    args = {"object_type": "flight", "id": "TK9999"}

    assert call("focus_map_object", args) == tool_envelope(None, args, NOT_FOUND)


def test_dosyadaki_ucus_depoda_yoksa_bulunmaz(hub):
    # TK2345 gün verisinde var (uçuş kaydı yetmez), depoda konumu yok.
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args)["error"] == NOT_FOUND


def test_saatten_sonraki_konum_gorunur_degildir(hub):
    put_position(hub, live_position(ts=epoch(16, 40)))
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args)["error"] == NOT_FOUND


def test_saat_esit_konum_gorunurdur(hub):
    put_position(hub, live_position(ts=epoch(16, 22)))
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args)["error"] is None


def test_saat_ilerleyince_konum_gorunur_olur(hub):
    put_position(hub, live_position(ts=epoch(16, 40)))
    args = {"object_type": "flight", "id": "TK2345"}
    assert call("focus_map_object", args)["error"] == NOT_FOUND

    put_clock(hub, epoch(16, 40))

    assert call("focus_map_object", args)["error"] is None


def test_bayat_konum_bulunmus_sayilir_ve_zarf_bayat_degildir(hub):
    put_position(hub, live_position(ts=epoch(16, 5)))
    args = {"object_type": "flight", "id": "TK2345"}
    put_clock(hub, epoch(16, 22))

    envelope = call("focus_map_object", args)

    assert envelope["error"] is None
    assert envelope["stale"] is False


def test_final_konum_bulunmus_sayilir(hub):
    put_position(hub, live_position(ts=epoch(15, 0), Onground=True))
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args)["error"] is None


def test_silinen_konumlu_ucus_not_found_doner(hub):
    put_position(hub, live_position())
    hub.handle_message(f"{ROOT}/positions/dc110c28", b"")
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args)["error"] == NOT_FOUND


def test_vurguda_tek_konumsuz_ucus_butun_komutu_reddeder(hub):
    put_position(hub, live_position())
    args = {"object_type": "flight", "ids": ["TK2345", "TK9999"]}

    assert call("highlight_map_set", args) == tool_envelope(None, args, NOT_FOUND)


def test_ucus_eslesmesi_flight_alanina_tam_esitliktir(hub):
    put_position(hub, live_position(flight="TK2345"))
    args = {"object_type": "flight", "id": "TK2346"}

    assert call("focus_map_object", args)["error"] == NOT_FOUND


def test_as_of_canli_modda_simule_andir(hub):
    put_clock(hub, epoch(16, 30))
    put_position(hub, live_position())

    envelope = call("focus_map_object", {"object_type": "flight", "id": "TK2345"})

    assert envelope["as_of"] == "2026-10-20T16:30:00+03:00"


def test_stand_denetimi_canli_moddan_etkilenmez(hub):
    args = {"object_type": "stand", "id": "C101"}

    assert call("focus_map_object", args)["error"] is None


# --- Veri hatası --------------------------------------------------------------------

VALID_ARGS = {
    "focus_map_object": {"object_type": "stand", "id": "C101"},
    "highlight_map_set": {"object_type": "stand", "ids": ["C101", "C102"]},
}


@pytest.mark.parametrize("name", TOOLS)
def test_copilot_data_tanimsizsa_veri_hatasi_doner(name, monkeypatch):
    monkeypatch.delenv("COPILOT_DATA")
    args = VALID_ARGS[name]

    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOLS)
def test_dosya_yoksa_veri_hatasi_doner(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", str(tmp_path / "yok.json"))
    args = VALID_ARGS[name]

    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOLS)
def test_stands_anahtari_yoksa_veri_hatasi_doner(name, monkeypatch, tmp_path):
    monkeypatch.setenv("COPILOT_DATA", write_data(tmp_path, stands=None))
    args = VALID_ARGS[name]

    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


@pytest.mark.parametrize("name", TOOLS)
@pytest.mark.parametrize("stands", [{}, "C101", 5, [1, 2], ["C101"], [{"a": 1}, 3]])
def test_stands_nesne_listesi_degilse_veri_hatasi_doner(
    name, stands, monkeypatch, tmp_path
):
    monkeypatch.setenv("COPILOT_DATA", write_data(tmp_path, stands=stands))
    args = VALID_ARGS[name]

    assert call(name, args) == layer_envelope(DATA_INVALID, filters=args)


def test_ucus_denetimi_icin_de_veri_dosyasi_okunur(hub, monkeypatch):
    put_position(hub, live_position())
    monkeypatch.delenv("COPILOT_DATA")
    args = {"object_type": "flight", "id": "TK2345"}

    assert call("focus_map_object", args) == layer_envelope(DATA_INVALID, args)


def test_ucus_denetimi_stands_anahtarini_istemez(hub, monkeypatch, tmp_path):
    put_position(hub, live_position())
    monkeypatch.setenv("COPILOT_DATA", write_data(tmp_path, stands=None))
    args = {"object_type": "flight", "id": "TK2345"}

    envelope = call("focus_map_object", args)

    assert envelope["error"] is None


def test_veri_her_cagrida_ortamdan_yeniden_okunur(monkeypatch, tmp_path):
    args = {"object_type": "stand", "id": "C101"}
    assert call("focus_map_object", args)["error"] is None

    monkeypatch.setenv("COPILOT_DATA", write_data(tmp_path, stands=[]))
    second = call("focus_map_object", args)

    assert second["error"] == NOT_FOUND
    assert second["source"] == str(tmp_path / "gun.json")
