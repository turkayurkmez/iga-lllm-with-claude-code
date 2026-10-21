"""Uçuş tool'larının ortak parçaları (docs/tools.md › Ortak kurallar).

Kontrat okuma, kontratın input_schema'sıyla argüman doğrulama ve COPILOT_DATA'dan
veri okuma burada yapılır. Tool'lar veriyi yalnızca load_data ile alır; hata
durumunda DataError fırlatır, zarfı run_tool kurar.
"""

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, model_validator

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = Path(__file__).resolve().parent / "contracts"
DATA_VAR = "COPILOT_DATA"
# tool_definitions sırası (docs/tools.md'deki sıra).
TOOL_NAMES = ("get_flight_summary", "resolve_flight_identity", "get_flight_details")


class DataError(RuntimeError):
    """Veri okunamadığında ya da sözleşmeye uymadığında fırlatılır.

    Mesaj yalnızca sunucu loguna yazılır; istemciye genel mesaj gider.
    """


def load_contract(name: str) -> dict:
    path = CONTRACTS_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def args_model(input_schema: dict) -> type[BaseModel]:
    """Argümanları kontratın input_schema'sıyla doğrulayan pydantic modeli kurar.

    call_tool pydantic model beklediği için şema ince bir modele sarılır; ayrı bir
    pydantic şeması tutulmaz, tek doğruluk kaynağı kontrattır.
    """
    validator = Draft202012Validator(input_schema)

    class Args(BaseModel):
        # Ek alanları şema reddeder; geçenler model_dump'ta aynen döner.
        model_config = ConfigDict(extra="allow")

        @model_validator(mode="before")
        @classmethod
        def _match_schema(cls, data: Any) -> Any:
            errors = sorted(validator.iter_errors(data), key=str)
            if errors:
                raise ValueError("; ".join(error.message for error in errors))
            return data

    return Args


def load_data(keys: Iterable[str]) -> tuple[dict, str]:
    """COPILOT_DATA'daki JSON'u okur; (veri, source) döndürür.

    Değişken ve dosya her çağrıda yeniden okunur, önbellek yoktur. Göreli yol repo
    köküne göre çözülür; source, değişkenin değeridir.
    """
    source = os.getenv(DATA_VAR, "").strip()
    if not source:
        raise DataError(f"{DATA_VAR} tanımsız ya da boş.")

    path = Path(source)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise DataError(f"Veri dosyası okunamadı: {path}") from exc

    if not isinstance(data, dict):
        raise DataError(f"Veri dosyası bir JSON nesnesi değil: {path}")
    missing = [key for key in keys if key not in data]
    if missing:
        raise DataError(f"Veride üst anahtar yok: {', '.join(missing)}")
    return data, source
