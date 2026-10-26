"""Tüketici deposu: canlı konum durumu ve SSE olayları (docs/canli_akis.md › Tüketici).

`PositionStore` saf bir sınıftır: ağa bağlanmaz, sistem saatini okumaz. MQTT aboneliği
gelen her mesajı `apply(topic, payload)`'a verir; dönen olaylar SSE'ye olduğu gibi
iletilir. Tek saat son `clock` mesajıdır (saat çapası).
"""

from stream import messages

Event = tuple[str, dict]


class _Shown:
    """SSE'ye verilmiş konum ve en son bildirilen bayatlık durumu."""

    def __init__(self, record: dict, stale: bool):
        self.record = record
        self.stale = stale


def _sort_key(record: dict) -> tuple[str, str]:
    # Flight eksik ya da metin değilse de sıralama bozulmaz.
    return (str(record.get("Flight") or ""), record["Key"])


class PositionStore:
    def __init__(self, root: str):
        self._prefix = f"{root}/"
        # Key → alınan son konum (gelecekte olabilir).
        self._latest: dict[str, dict] = {}
        # Key → SSE'ye verilmiş konum; snapshot yalnızca bunları içerir.
        self._shown: dict[str, _Shown] = {}
        self._flights: dict[str, dict] = {}
        self._clock: dict | None = None
        self._state = messages.STATE_NO_BROKER

    @property
    def flights(self) -> dict[str, dict]:
        return {flight_id: dict(record) for flight_id, record in self._flights.items()}

    def apply(self, topic: str, payload: bytes) -> list[Event]:
        """Tek mesajı işler; geçersiz mesaj sessizce atılır ve olay çıkmaz."""
        if not topic.startswith(self._prefix):
            return []
        match topic[len(self._prefix) :].split("/"):
            case ["positions", key]:
                return self._apply_position(key, payload)
            case ["flights", flight_id]:
                self._apply_flight(flight_id, payload)
                return []
            case ["clock"]:
                return self._apply_clock(payload)
            case ["status"]:
                state = messages.parse_status(payload)
                return self._set_state(state) if state is not None else []
        return []

    @property
    def clock(self) -> dict | None:
        """Son saat mesajı (kopya); yoksa None."""
        return dict(self._clock) if self._clock is not None else None

    def shown_records(self) -> list[dict]:
        """SSE'ye verilmiş (görünür) konum kayıtları, görünüm alanları olmadan."""
        return [dict(item.record) for item in self._shown.values()]

    def broker_lost(self) -> list[Event]:
        """Broker bağlantısı koptu: durum broker_yok, konumlar korunur."""
        return self._set_state(messages.STATE_NO_BROKER)

    def snapshot(self) -> dict:
        shown = sorted((item.record for item in self._shown.values()), key=_sort_key)
        return {
            "clock": dict(self._clock) if self._clock is not None else None,
            "status": {"state": self._state},
            "positions": [self._view(record) for record in shown],
        }

    def _apply_position(self, key: str, payload: bytes) -> list[Event]:
        if payload == b"":
            # Retained kayıt silindi; yalnızca gösterilmiş konum için olay çıkar.
            self._latest.pop(key, None)
            if self._shown.pop(key, None) is None:
                return []
            return [("removed", {"Key": key})]
        record = messages.parse_position(key, payload)
        if record is None:
            return []
        current = self._latest.get(key)
        if current is not None and record["LastUpdate"] < current["LastUpdate"]:
            return []
        self._latest[key] = record
        if not self._visible(record):
            # Gelecek konum saklanır; eldeki gösterilmiş konum saat ona ulaşana dek kalır.
            return []
        return [self._show(key, record)]

    def _apply_flight(self, flight_id: str, payload: bytes) -> None:
        if payload == b"":
            self._flights.pop(flight_id, None)
            return
        record = messages.parse_flight(flight_id, payload)
        if record is not None:
            self._flights[flight_id] = record

    def _apply_clock(self, payload: bytes) -> list[Event]:
        clock = messages.parse_clock(payload)
        if clock is None:
            return []
        if self._clock is not None and clock["epoch"] < self._clock["epoch"]:
            # Saat geri gitmez.
            return []
        self._clock = clock
        changes: list[tuple[dict, Event]] = []
        for key, latest in self._latest.items():
            shown = self._shown.get(key)
            if (shown is None or shown.record is not latest) and self._visible(latest):
                changes.append((latest, self._show(key, latest)))
            elif shown is not None and not shown.stale and self._is_stale(shown.record):
                shown.stale = True
                changes.append((shown.record, ("stale", self._view(shown.record))))
        changes.sort(key=lambda change: _sort_key(change[0]))
        return [("clock", dict(clock)), *(event for _, event in changes)]

    def _set_state(self, state: str) -> list[Event]:
        if state == self._state:
            return []
        self._state = state
        return [("status", {"state": state})]

    def _show(self, key: str, record: dict) -> Event:
        self._shown[key] = _Shown(record, self._is_stale(record))
        return ("position", self._view(record))

    def _visible(self, record: dict) -> bool:
        # Gelecek konum gösterilmez; saat yoksa karşılaştırılacak an da yoktur.
        return self._clock is None or record["LastUpdate"] <= self._clock["epoch"]

    @staticmethod
    def _is_final(record: dict) -> bool:
        return record.get("Onground") is True

    def _is_stale(self, record: dict) -> bool:
        if self._clock is None or self._is_final(record):
            return False
        return self._clock["epoch"] - record["LastUpdate"] > messages.STALE_AFTER_S

    def _view(self, record: dict) -> dict:
        """Kayıt aynen + as_of, age_s, stale (saat varsa) + final."""
        view = dict(record)
        if self._clock is not None:
            view["as_of"] = self._clock["now"]
            view["age_s"] = self._clock["epoch"] - record["LastUpdate"]
            view["stale"] = self._is_stale(record)
        view["final"] = self._is_final(record)
        return view
