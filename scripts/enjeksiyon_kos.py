"""Enjeksiyon saldırı setini gerçek modelle koşar (docs/enjeksiyon.md E7).

ÜCRETLİ: her saldırı en çok bir agent koşusudur (en çok iki model çağrısı). Döngüde ya
da gereksiz yere çalıştırma. Zehirli parça/zarf `agent.run_tool` taklidiyle verilir;
Voyage ve gerçek veri çağrılmaz, yalnızca Anthropic API'si ücretlidir. Var olan çıktı
dosyasının üzerine yazılmaz.

Kullanım (repo kökünden):
    $env:PYTHONIOENCODING="utf-8"; python scripts/enjeksiyon_kos.py --instruction v3
    python scripts/enjeksiyon_kos.py --instruction v4 --out eval/out/ikinci.json
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import agent, clock, instructions
from eval import enjeksiyon

OUT_DIR = ROOT / "eval" / "out"


def run_attacks(client: Any, version: str, attacks: list[dict]) -> list[dict]:
    """Her saldırıyı `run_agent` ile koşar; ihlal listesiyle birlikte kayıt döndürür."""
    system = instructions.load(version)
    original = agent.run_tool
    now = clock.now().isoformat()
    records = []
    try:
        for attack in attacks:
            poisoned = enjeksiyon.poisoned_tool(attack, now)
            if poisoned is not None:
                name, envelope = poisoned

                def forged(tool: str, args: dict, name=name, envelope=envelope) -> dict:
                    return envelope if tool == name else original(tool, args)

                agent.run_tool = forged
            else:
                agent.run_tool = original
            result = agent.run_agent(
                attack["girdi"], client=client, instruction_version=version
            )
            found = enjeksiyon.violations(attack, result, system)
            records.append(
                {
                    "id": attack["id"],
                    "tur": attack["tur"],
                    "status": result.status,
                    "ihlaller": found,
                    "basarili_saldiri": bool(found),
                    "cevap": result.text,
                }
            )
    finally:
        agent.run_tool = original
    return records


def main(argv: list[str] | None = None, client: Any = None) -> int:
    parser = argparse.ArgumentParser(description="Enjeksiyon saldırı setini koşar.")
    parser.add_argument("--instruction", required=True, help="talimat sürümü, ör. v3")
    parser.add_argument(
        "--out", help="çıktı dosyası; varsayılan eval/out/enjeksiyon-<sürüm>.json"
    )
    parser.add_argument(
        "--saldiri-seti", help="varsayılan: eval/enjeksiyon-saldirilari.json"
    )
    args = parser.parse_args(argv)

    version = args.instruction
    if version not in instructions.VERSIONS:
        print(f"Hata: Bilinmeyen talimat sürümü: {version!r}", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else OUT_DIR / f"enjeksiyon-{version}.json"
    if out.exists():
        print(f"Hata: Çıktı dosyası var, üzerine yazılmaz: {out}", file=sys.stderr)
        return 1
    try:
        attacks = (
            enjeksiyon.load_attacks(args.saldiri_seti)
            if args.saldiri_seti
            else enjeksiyon.load_attacks()
        )
    except (OSError, ValueError) as exc:
        print(f"Hata: {exc}", file=sys.stderr)
        return 1
    if client is None:
        from backend import llm

        client = llm.client

    records = run_attacks(client, version, attacks)
    for record in records:
        if record["ihlaller"]:
            print(f"İHLAL  {record['id']}: {'; '.join(record['ihlaller'])}")
        else:
            print(f"OK     {record['id']}")
    succeeded = sum(r["basarili_saldiri"] for r in records)
    print(f"Saldırı başarı oranı: {succeeded}/{len(records)}")

    out.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "instruction": {"name": version, "version": instructions.VERSIONS[version]},
        "basari": succeeded,
        "toplam": len(records),
        "records": records,
    }
    out.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
