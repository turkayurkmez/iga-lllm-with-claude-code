"""eval/rag_kos.py koşucusunun testleri (API'siz; sahte model, sahte arama zarfı).

Ham kayıt `eval/rag_skor.py` kayıt biçimindedir. Gerçek model, Voyage ve ağ yoktur:
model sahte istemcidir, `search_documents` zarfı `agent.run_tool` taklidiyle verilir.
"""

import importlib
import json
from pathlib import Path

import pytest
from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

from backend import agent
from eval import rag_kos, rag_skor

ROOT = Path(__file__).resolve().parent.parent
LLM_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "ANTHROPIC_TEMP_MODEL")
NOW = "2026-10-20T16:22:00+03:00"


def chunk(chunk_id, status="active"):
    doc = chunk_id.split("#")[0]
    return {
        "chunk_id": chunk_id,
        "doc_id": doc,
        "title": f"Belge {doc}",
        "section": "Bölüm",
        "revision": "2",
        "effective_from": "2026-03-01",
        "status": status,
        "text": f"{chunk_id} metni.",
    }


def envelope(chunks):
    return {
        "value": chunks,
        "source": "data/korpus",
        "as_of": NOW,
        "filters": {},
        "stale": False,
        "tool_version": "1.0.0",
        "error": None
        if chunks is not None
        else {"code": "NOT_FOUND", "message": "Kaynak yok."},
        "author": "tool",
    }


def message(stop_reason, content):
    return Message(
        id="msg_test",
        type="message",
        role="assistant",
        model="test-model",
        content=content,
        stop_reason=stop_reason,
        stop_sequence=None,
        usage=Usage(input_tokens=1, output_tokens=1),
    )


def search_turn(query):
    block = ToolUseBlock(
        type="tool_use", id="toolu_1", name="search_documents", input={"query": query}
    )
    return message("tool_use", [block])


def final(text):
    return message("end_turn", [TextBlock(type="text", text=text)])


class FakeClient:
    """Her soru için sıradaki yanıt listesini verir: [arama turu, cevap]."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.messages = self

    def create(self, **kwargs):
        assert self._responses, "Beklenenden fazla model çağrısı"
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    for name in LLM_VARS:
        monkeypatch.setenv(name, "sahte")
    monkeypatch.setenv("COPILOT_NOW", NOW)
    monkeypatch.setenv("COPILOT_INSTRUCTION", "v3")


def two_questions(tmp_path):
    questions = [
        {
            "id": "S1",
            "soru": "Soru bir?",
            "cevaplanabilir": True,
            "beklenen_belgeler": ["D01"],
            "include_superseded": False,
        },
        {
            "id": "U1",
            "soru": "Soru iki?",
            "cevaplanabilir": False,
            "beklenen_belgeler": [],
            "include_superseded": False,
        },
    ]
    path = tmp_path / "sorular.json"
    path.write_text(json.dumps(questions, ensure_ascii=False), encoding="utf-8")
    return path


def fake_search(monkeypatch, by_query):
    """agent.run_tool: search_documents için sahte zarf, kalanı gerçek."""
    real = agent.run_tool

    def run_tool(name, args):
        if name == "search_documents":
            return envelope(by_query[args["query"]])
        return real(name, args)

    monkeypatch.setattr(agent, "run_tool", run_tool)


def scripted_client():
    return FakeClient(
        [
            search_turn("bir"),
            final("Süre beş dakikadır [D01#01]. Başka bir şey [D99#01]."),
            search_turn("iki"),
            final("Belgelerde bu konuda kaynak bulamadım."),
        ]
    )


def run_main(argv, client=None):
    return rag_kos.main(argv, client=client)


def test_modul_var():
    assert importlib.util.find_spec("eval.rag_kos") is not None


def test_ham_kayit_aramalari_belge_sirasiyla_atiflari_denetciyle_cikarir(
    tmp_path, monkeypatch, capsys
):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    fake_search(
        monkeypatch,
        {"bir": [chunk("D01#01"), chunk("D02#03", "superseded")], "iki": None},
    )
    code = run_main(
        ["--sorular", str(sorular), "--cikti", str(cikti)], client=scripted_client()
    )
    assert code == 0
    run = json.loads((cikti / "rag-1.json").read_text(encoding="utf-8"))
    records = run["records"]
    assert [r["id"] for r in records] == ["S1", "U1"]

    s1, u1 = records
    assert s1["status"] == "tamam"
    assert s1["searches"] == [{"args": {"query": "bir"}, "doc_ids": ["D01", "D02"]}]
    assert len(s1["citations"]) == 2
    ok, bad = s1["citations"]
    assert ok == {
        "chunk_id": "D01#01",
        "doc_id": "D01",
        "dogrulandi": True,
        "status": "active",
    }
    assert bad == {
        "chunk_id": "D99#01",
        "doc_id": None,
        "dogrulandi": False,
        "status": None,
    }
    assert u1["searches"] == [{"args": {"query": "iki"}, "doc_ids": []}]
    assert u1["citations"] == []
    assert run["instruction"]["name"] == "v3"


def test_rapor_ham_kayittan_skor_hesabiyla_uretilir_ve_dosyaya_yazilir(
    tmp_path, monkeypatch, capsys
):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    fake_search(monkeypatch, {"bir": [chunk("D01#01")], "iki": None})
    run_main(
        ["--sorular", str(sorular), "--cikti", str(cikti)], client=scripted_client()
    )
    run = json.loads((cikti / "rag-1.json").read_text(encoding="utf-8"))
    questions = json.loads(sorular.read_text(encoding="utf-8"))
    expected = rag_skor.render(rag_skor.score(run["records"], questions))
    assert (cikti / "rag-1.md").read_text(
        encoding="utf-8"
    ).rstrip() == expected.rstrip()
    assert capsys.readouterr().out.rstrip() == expected.rstrip()


def test_koşu_numarasi_mevcut_dosyalardan_bir_sonrakidir(tmp_path, monkeypatch):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    cikti.mkdir()
    (cikti / "rag-4.json").write_text("{}", encoding="utf-8")
    fake_search(monkeypatch, {"bir": [chunk("D01#01")], "iki": None})
    run_main(
        ["--sorular", str(sorular), "--cikti", str(cikti)], client=scripted_client()
    )
    assert (cikti / "rag-5.json").is_file()
    assert (cikti / "rag-5.md").is_file()
    assert (cikti / "rag-4.json").read_text(encoding="utf-8") == "{}"


def test_kuru_modeli_cagirir_ama_dosya_yazmaz(tmp_path, monkeypatch, capsys):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    fake_search(monkeypatch, {"bir": [chunk("D01#01")], "iki": None})
    client = scripted_client()
    code = run_main(
        ["--kuru", "--sorular", str(sorular), "--cikti", str(cikti)], client=client
    )
    assert code == 0
    assert not cikti.exists()
    assert client._responses == []  # model gerçekten çağrıldı
    assert "RAG skor raporu" in capsys.readouterr().out


def test_rapor_n_modelsiz_raporu_yeniden_uretir(tmp_path, monkeypatch, capsys):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    fake_search(monkeypatch, {"bir": [chunk("D01#01")], "iki": None})
    run_main(
        ["--sorular", str(sorular), "--cikti", str(cikti)], client=scripted_client()
    )
    first = (cikti / "rag-1.md").read_text(encoding="utf-8")
    (cikti / "rag-1.md").write_text("bozuk", encoding="utf-8")
    capsys.readouterr()

    def forbidden(*args, **kwargs):
        raise AssertionError("--rapor modeli ya da ayarı yüklememeli")

    monkeypatch.setattr(rag_kos, "run_agent", forbidden)
    monkeypatch.setattr(rag_kos, "_load_llm", forbidden)
    code = run_main(["--rapor", "1", "--sorular", str(sorular), "--cikti", str(cikti)])
    assert code == 0
    assert (cikti / "rag-1.md").read_text(encoding="utf-8") == first
    assert "RAG skor raporu" in capsys.readouterr().out


def test_rapor_olmayan_dosyada_hata_verir(tmp_path, capsys):
    sorular = two_questions(tmp_path)
    code = run_main(
        ["--rapor", "9", "--sorular", str(sorular), "--cikti", str(tmp_path / "out")]
    )
    captured = capsys.readouterr()
    assert code == 1
    assert captured.err.startswith("Hata:")
    assert "rag-9.json" in captured.err


def test_rapor_kuru_ile_birlikte_kullanilamaz(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run_main(["--rapor", "1", "--kuru"])
    assert exc.value.code == 2


def test_bilinmeyen_talimat_surumu_koşu_baslamadan_hata_verir(tmp_path, capsys):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    code = run_main(
        ["--instruction", "v99", "--sorular", str(sorular), "--cikti", str(cikti)],
        client=FakeClient([]),
    )
    assert code == 1
    assert "Hata:" in capsys.readouterr().err
    assert not cikti.exists()


def test_agent_hatasinda_dosya_yazilmaz_ve_soru_adi_soylenir(
    tmp_path, monkeypatch, capsys
):
    sorular = two_questions(tmp_path)
    cikti = tmp_path / "out"
    fake_search(monkeypatch, {"bir": [chunk("D01#01")], "iki": None})
    client = FakeClient(
        [search_turn("bir"), final("Cevap [D01#01].")]
    )  # U1 için yanıt yok
    code = run_main(["--sorular", str(sorular), "--cikti", str(cikti)], client=client)
    err = capsys.readouterr().err
    assert code == 1
    assert "U1" in err
    assert not cikti.exists()


def test_atifsiz_olmayan_durumda_atif_cikarilmaz():
    question = {"id": "S1", "soru": "x"}
    result = {
        "status": "max_tokens",
        "text": "Kesildi [D01#01]",
        "turns": [
            {
                "tool_calls": [
                    {
                        "name": "search_documents",
                        "input": {"query": "q"},
                        "executed": True,
                        "envelope": envelope([chunk("D01#01")]),
                    }
                ]
            }
        ],
    }
    record = rag_kos.build_record(question, result)
    assert record["citations"] == []
    assert len(record["searches"]) == 1


def test_calismamis_cagri_aramaya_sayilmaz():
    question = {"id": "S1", "soru": "x"}
    result = {
        "status": "tekrar_siniri",
        "text": "",
        "turns": [
            {
                "tool_calls": [
                    {
                        "name": "search_documents",
                        "input": {"query": "q"},
                        "executed": False,
                        "envelope": None,
                    }
                ]
            }
        ],
    }
    assert rag_kos.build_record(question, result)["searches"] == []
