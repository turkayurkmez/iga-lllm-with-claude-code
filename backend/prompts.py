"""Modele verilen sistem talimatları.

Metin backend/instructions/ altındaki sürüm dosyasından, import anındaki
COPILOT_INSTRUCTION'a göre okunur (docs/system-talimat.md).
"""

from backend.instructions import VERSIONS, default_version, load

_VERSION = default_version()
SYSTEM_INSTRUCTIONS = load(_VERSION)
SYSTEM_INSTRUCTIONS_VERSION = VERSIONS[_VERSION]
