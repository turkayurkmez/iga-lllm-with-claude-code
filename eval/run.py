"""Golden set koşucusu (docs/eval.md › Koşucu).

Golden set'i doğrular, temel veriyi ve bozuk veriyi geçici klasörde hazırlar,
beklenen değerleri eval.expected ile hesaplar, her soruyu run_agent'tan geçirir ve
ölçütleri eval.criteria ile değerlendirir. --kuru'da model çağrılmaz ve backend.llm
yüklenmez; yalnızca hesaplanan beklentiler soru başına bir JSON satırı olarak yazılır.

Gerçek koşum ücretlidir (soru × tekrar agent döngüsü). Repo kökünden:
python -m eval.run --out eval\\out\\sonuc.json [--soru G01,G13] [--tekrar 1]
python -m eval.run --kuru [--soru ...]
"""

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from eval import criteria, expected
from eval.golden import validate

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "eval" / "golden.json"
DEFAULT_DATA = "data/referans/seed42-2026-10-20.json"
CALC_ERROR, API_ERROR = "hesap_hatasi", "api_hatasi"


class RunnerError(Exception):
    """Koşu başlamadan durdu; mesaj stderr'e "Hata:" ile yazılır."""


@dataclass
class Prepared:
    """Bir sorunun koşuma hazır hali: doldurulmuş metin, veri, now ve beklentiler."""

    question: dict
    text: str
    data_path: str | None = None
    now: str | None = None
    expect: list = field(default_factory=list)
    forbid: list = field(default_factory=list)
    error: str | None = None


def _positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("en az 1 olmalı")
    return number


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="python -m eval.run", description="Golden set koşucusu (docs/eval.md)."
    )
    parser.add_argument("--out", help="Sonuç dosyası; --kuru yoksa zorunlu")
    parser.add_argument("--soru", help="Virgülle ayrılmış id'ler, ör. G01,G13")
    parser.add_argument("--tekrar", type=_positive, default=1)
    parser.add_argument("--instruction", help="Talimat sürümü, ör. v1")
    parser.add_argument("--data", help=f"Temel veri; varsayılan {DEFAULT_DATA}")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--date")
    parser.add_argument("--kuru", action="store_true", help="Model çağırmadan")
    parser.add_argument("--golden", default=str(GOLDEN), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if not args.kuru and not args.out:
        parser.error("--kuru verilmediyse --out zorunlu.")
    if (args.seed is None) != (args.date is None):
        parser.error("--seed ve --date birlikte verilir.")
    if args.data and args.seed is not None:
        parser.error("--data, --seed/--date ile birlikte verilemez.")
    return args


def main(argv=None, client=None) -> int:
    args = parse_args(argv)
    try:
        return _run(args, client)
    except RunnerError as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1


def _run(args, client):
    golden = _load_golden(Path(args.golden))
    questions = _select(golden["questions"], args.soru)
    out = None
    if not args.kuru:
        out = Path(args.out)
        if out.exists():
            raise RunnerError(f"Sonuç dosyası zaten var: {out}.")
        llm, instruction = _load_llm(args.instruction)

    with tempfile.TemporaryDirectory(prefix="eval-") as tmp:
        base_path = _base_path(args, Path(tmp))
        base = _read_json(base_path)
        datasets = _corrupt(questions, base_path, Path(tmp))
        prepared = [
            _prepare(q, golden["now"], base_path, base, datasets) for q in questions
        ]
        if args.kuru:
            for item in prepared:
                print(json.dumps(_dry_line(item), ensure_ascii=False))
            return 1 if any(item.error for item in prepared) else 0

        runnable = sum(1 for item in prepared if item.error is None)
        print(
            f"Ücretli agent koşusu: {runnable * args.tekrar} "
            f"({runnable} soru × {args.tekrar} tekrar).",
            file=sys.stderr,
        )
        runs = [
            _execute(item, repeat, instruction["name"], client)
            for item in prepared
            for repeat in range(1, args.tekrar + 1)
        ]

    summary = criteria.summarize(runs)
    result = {
        "golden_version": golden["version"],
        "instruction": instruction,
        "model": llm.MODEL,
        "base": {"path": base_path, "meta": base.get("meta")},
        "runs": runs,
        "summary": summary,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    _print_summary(summary, out)
    return 0 if all(run["passed"] for run in runs) else 1


# --- Hazırlık ---


def _load_golden(path):
    try:
        golden = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError(f"Golden set okunamadı: {path}.") from exc
    errors = validate(golden)
    if errors:
        raise RunnerError("Golden set geçersiz:\n" + "\n".join(errors))
    return golden


def _select(questions, ids):
    if not ids:
        return questions
    wanted = [i.strip() for i in ids.split(",") if i.strip()]
    known = {q["id"] for q in questions}
    unknown = [i for i in wanted if i not in known]
    if unknown:
        raise RunnerError(f"Bilinmeyen soru id'si: {', '.join(unknown)}.")
    return [q for q in questions if q["id"] in wanted]


def _load_llm(version):
    """Ayarları ve talimatı ilk koşumdan önce yükler; sorun varsa koşu başlamaz."""
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


def _subprocess(args):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    command = [sys.executable, "-m", *args]
    return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, check=False)


def _base_path(args, tmp):
    if args.seed is None:
        return args.data or DEFAULT_DATA
    path = tmp / "base.json"
    done = _subprocess(
        [
            "synth.generator",
            "--seed",
            str(args.seed),
            "--date",
            args.date,
            "--out",
            str(path),
        ]
    )
    if done.returncode != 0:
        raise RunnerError("Temel veri üretilemedi (synth.generator).")
    return str(path)


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RunnerError(f"Temel veri okunamadı: {path}.") from exc


def _corruption_key(question):
    corruption = question.get("corruption")
    if corruption is None:
        return None
    return corruption["scenario"], corruption["flight_no"], corruption.get("field")


def _corrupt(questions, base_path, tmp):
    """Her farklı bozulma bir kez üretilir; başarısızsa değeri None olur."""
    datasets = {}
    for question in questions:
        key = _corruption_key(question)
        if key is None or key in datasets:
            continue
        scenario, flight_no, field_name = key
        out = tmp / f"bozuk-{len(datasets) + 1}-{scenario}.json"
        command = [
            "synth.corruption",
            "--in",
            os.path.abspath(base_path),
            "--scenario",
            scenario,
            "--out",
            str(out),
            "--flight-no",
            flight_no,
        ]
        if field_name is not None:
            command += ["--field", field_name]
        done = _subprocess(command)
        datasets[key] = (str(out), _read_json(out)) if done.returncode == 0 else None
    return datasets


def _resolve(ref, base, data, now):
    if "literal" in ref:
        return ref["literal"]
    return expected.compute(ref, base, data, now)


def _prepare(question, default_now, base_path, base, datasets):
    item = Prepared(question=question, text=question["question"])
    key = _corruption_key(question)
    dataset = (base_path, base) if key is None else datasets[key]
    if dataset is None:
        item.error = CALC_ERROR
        return item
    item.data_path, data = dataset
    try:
        now_iso = expected.compute(question.get("now", default_now), base, data, None)
        now = datetime.fromisoformat(now_iso)
        if now.tzinfo is None:
            raise expected.ExpectedError("now saat dilimi taşımalı.")
        slots = {
            name: expected.compute(ref, base, data, now)
            for name, ref in question.get("slots", {}).items()
        }
        item.text = question["question"].format_map(slots)
        item.now = now_iso
        item.expect = [
            (r, _resolve(r, base, data, now)) for r in question.get("expect", [])
        ]
        item.forbid = [
            (r, _resolve(r, base, data, now)) for r in question.get("forbid", [])
        ]
    except (expected.ExpectedError, ValueError, TypeError):
        item.error = CALC_ERROR
    return item


def _rendered(pairs):
    return [
        criteria.render(ref, value)[0]
        for ref, values in pairs
        for value in (values if isinstance(values, list) else [values])
    ]


def _dry_line(item):
    return {
        "id": item.question["id"],
        "question": item.text,
        "corruption": item.question.get("corruption"),
        "now": item.now,
        "expect": _rendered(item.expect),
        "forbid": _rendered(item.forbid),
        "error": item.error,
    }


# --- Koşum ---


@contextmanager
def _environment(**values):
    before = {name: os.environ.get(name) for name in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for name, value in before.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_record(item, repeat):
    q = item.question
    return {
        "id": q["id"],
        "repeat": repeat,
        "category": q["category"],
        "behavior": q["behavior"],
        "question": item.text,
        "now": item.now,
        "corruption": q.get("corruption"),
        "status": None,
        "executed_tools": [],
        "criteria": {},
        "missing": [],
        "found_forbidden": [],
        "text": "",
        "passed": False,
        "error": None,
        "exception": None,
    }


def _execute(item, repeat, instruction_name, client):
    record = _run_record(item, repeat)
    if item.error is not None:
        record["error"] = item.error
        return record

    anthropic = importlib.import_module("anthropic")
    agent = importlib.import_module("backend.agent")
    with _environment(COPILOT_DATA=item.data_path, COPILOT_NOW=item.now):
        try:
            result = agent.run_agent(
                item.text, client=client, instruction_version=instruction_name
            ).model_dump()
        except anthropic.APIError as exc:
            # Ayrıntı sonuca girmez (CLAUDE.md › Yasaklar); yalnızca sınıf adı.
            record["error"] = API_ERROR
            record["exception"] = type(exc).__name__
            return record

    verdict = criteria.evaluate(item.question, item.expect, item.forbid, result)
    record.update(
        status=result["status"],
        executed_tools=[
            {"name": call["name"], "input": call["input"]}
            for turn in result["turns"]
            for call in turn["tool_calls"]
            if call["executed"]
        ],
        text=result["text"],
        **verdict,
    )
    return record


def _print_summary(summary, out):
    score = summary["score"]
    print(f"Golden skor: {score['passed']}/{score['total']}")
    for name, rate in summary["criteria"].items():
        if rate["total"]:
            print(f"  {name}: {rate['passed']}/{rate['total']}")
    for name, rate in summary["categories"].items():
        print(f"  [{name}] {rate['passed']}/{rate['total']}")
    stable = summary["stable"]
    print(f"Kararlı soru: {stable['stable']}/{stable['questions']}")
    print(f"Sonuç: {out}")


if __name__ == "__main__":
    sys.exit(main())
