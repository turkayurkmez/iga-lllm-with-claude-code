"""RAG golden set koşucusu (docs/rag_olcum.md › Koşu).

`eval/kaynakli_sorulari.json`'daki soruları sırayla gerçek modelle `run_agent`'a sorar.
Agent'a dokunulmaz: koşucu yalnızca `AgentResult.turns` içindeki `search_documents`
çağrılarını okur ve atıfları `/chat`'in kullandığı denetçiyle (`backend.cards`)
çıkarır. Ham kayıt `eval/out/rag-N.json`'a, rapor `eval/rag_skor.py` ile ham kayıttan
üretilip `eval/out/rag-N.md`'ye yazılır.

Gerçek koşu ÜCRETLİDİR (soru başına agent döngüsü + Voyage gömme). Repo kökünden:
python -m eval.rag_kos                 # koşar, rag-N.json ve rag-N.md yazar
python -m eval.rag_kos --kuru          # koşar (ücretli), dosya yazmaz, raporu basar
python -m eval.rag_kos --rapor N       # modelsiz: rag-N.json'dan raporu yeniden üretir
"""

import argparse
import importlib
import json
import re
import sys
from pathlib import Path

from backend.agent import run_agent
from backend.cards import SEARCH_TOOL, CardBuilder, retrieved_chunks
from eval import rag_skor

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "kaynakli_sorulari.json"
OUT_DIR = ROOT / "eval" / "out"
RUN_FILE = re.compile(r"rag-(\d+)\.json")


class RunnerError(Exception):
    """Koşu durdu; mesaj stderr'e "Hata:" ile yazılır."""


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="python -m eval.rag_kos", description=__doc__)
    parser.add_argument(
        "--kuru", action="store_true", help="Modeli çağırır, dosya yazmaz"
    )
    parser.add_argument(
        "--rapor",
        type=int,
        metavar="N",
        help="Modelsiz: eval/out/rag-N.json'dan raporu yeniden üretir",
    )
    parser.add_argument("--instruction", help="Talimat sürümü, ör. v3")
    parser.add_argument("--sorular", default=str(QUESTIONS), help=argparse.SUPPRESS)
    parser.add_argument("--cikti", default=str(OUT_DIR), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.rapor is not None and (args.kuru or args.instruction):
        parser.error("--rapor modelsizdir; --kuru ve --instruction ile birlikte olmaz")
    return args


def main(argv=None, client=None) -> int:
    args = parse_args(argv)
    try:
        return _run(args, client)
    except RunnerError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1


def _run(args, client):
    questions = load_questions(Path(args.sorular))
    out_dir = Path(args.cikti)
    if args.rapor is not None:
        return _report_only(args.rapor, questions, out_dir)

    _llm, instruction = _load_llm(args.instruction)
    records = []
    for index, question in enumerate(questions, start=1):
        print(f"[{index}/{len(questions)}] {question['id']}", file=sys.stderr)
        try:
            result = run_agent(
                question["soru"], client=client, instruction_version=instruction["name"]
            )
        except Exception as exc:
            raise RunnerError(
                f"{question['id']} sorusunda agent durdu ({type(exc).__name__}); "
                "koşu yarıda kesildi, hiçbir dosya yazılmadı."
            ) from exc
        records.append(build_record(question, result.model_dump()))

    report = rag_skor.render(rag_skor.score(records, questions))
    if args.kuru:
        print(report)
        return 0
    number = _write_run(out_dir, instruction, records, report)
    print(report)
    print(f"Yazıldı: eval/out/rag-{number}.json, rag-{number}.md", file=sys.stderr)
    return 0


def _report_only(number, questions, out_dir):
    path = out_dir / f"rag-{number}.json"
    if not path.is_file():
        raise RunnerError(f"Koşu dosyası yok: {path.name}")
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
        records = run["records"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RunnerError(f"Koşu dosyası okunamadı: {path.name}") from exc
    report = rag_skor.render(rag_skor.score(records, questions))
    _write_text(out_dir / f"rag-{number}.md", report)
    print(report)
    return 0


def load_questions(path):
    try:
        questions = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError(f"Soru dosyası okunamadı: {path.name}") from exc
    if not isinstance(questions, list) or not questions:
        raise RunnerError(f"Soru dosyası boş ya da liste değil: {path.name}")
    return questions


def _load_llm(version):
    """Ayarları ve talimatı ilk sorudan önce yükler; sorun varsa koşu başlamaz."""
    instructions = importlib.import_module("backend.instructions")
    try:
        llm = importlib.import_module("backend.llm")
    except RuntimeError as exc:  # backend.llm.ConfigError
        raise RunnerError("Model ayarları yüklenemedi (.env).") from exc
    # Ortamdaki sürüm .env yüklendikten sonra okunur.
    name = version or instructions.default_version()
    if name not in instructions.VERSIONS:
        raise RunnerError(f"Bilinmeyen talimat sürümü: {name}.")
    text = instructions.load(name)
    instruction = {
        "name": name,
        "version": instructions.VERSIONS[name],
        "summary": instructions.summary(text),
    }
    return llm, instruction


def build_record(question, result):
    """Bir sorunun ham kaydı; `result` `AgentResult.model_dump()` çıktısıdır.

    Saf: yalnızca çalışmış `search_documents` çağrılarını okur. Atıflar
    `CardBuilder` ile (chat'teki denetçi) ve yalnızca `tamam`'da çıkarılır.
    """
    builder = CardBuilder()
    searches = []
    docs_by_chunk = {}
    for turn in result["turns"]:
        for call in turn["tool_calls"]:
            if not call["executed"]:
                continue
            envelope = call["envelope"]
            builder.cards(call["name"], envelope)
            if call["name"] != SEARCH_TOOL:
                continue
            chunks = retrieved_chunks(call["name"], envelope)
            for chunk in chunks:
                docs_by_chunk.setdefault(chunk["chunk_id"], chunk["doc_id"])
            searches.append(
                {"args": call["input"], "doc_ids": [c["doc_id"] for c in chunks]}
            )

    citations = []
    if result["status"] == "tamam":
        for event in builder.citations(result["text"]):
            verified = event["dogrulandi"]
            citations.append(
                {
                    "chunk_id": event["chunk_id"],
                    "doc_id": docs_by_chunk.get(event["chunk_id"])
                    if verified
                    else None,
                    "dogrulandi": verified,
                    "status": event.get("status") if verified else None,
                }
            )
    return {
        "id": question["id"],
        "soru": question["soru"],
        "answer": result["text"],
        "status": result["status"],
        "searches": searches,
        "citations": citations,
    }


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text if text.endswith("\n") else text + "\n")


def _next_number(out_dir):
    taken = [
        int(m.group(1))
        for p in (out_dir.glob("rag-*.json") if out_dir.is_dir() else [])
        if (m := RUN_FILE.fullmatch(p.name))
    ]
    return max(taken, default=0) + 1


def _write_run(out_dir, instruction, records, report):
    number = _next_number(out_dir)
    run = {"instruction": instruction, "records": records}
    _write_text(
        out_dir / f"rag-{number}.json", json.dumps(run, ensure_ascii=False, indent=2)
    )
    _write_text(out_dir / f"rag-{number}.md", report)
    return number


if __name__ == "__main__":
    sys.exit(main())
