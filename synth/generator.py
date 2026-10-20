"""Bir günlük sentetik AODB verisi üretir (docs/spec.md §6–§9).

Repo kökünden çalıştırın:
    python -m synth.generator --seed N --date YYYY-MM-DD --out dosya.json

Aynı seed ve tarih birebir aynı dosyayı verir: rastgelelik yalnızca random.Random(seed)'den
gelir; sistem saati, set sırası ve hash() kullanılmaz. Tüm listeler çekilişten önce kararlı
sıradadır.
"""

import argparse
import json
import math
import random
import string
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GENERATOR_VERSION = "1.0.0"

TZ = timezone(timedelta(hours=3))
LOCAL_AIRPORT = "XXXX"

AIRCRAFT_COUNT = 200
PAIR_RANGE = (280, 320)
CANCELLED_PAIR_RANGE = (2, 5)
UNAVAILABLE_STAND_RANGE = (5, 8)
# Gecikmeli oranı iptal edilmeyen hareketlerin %15–25'i olmalı; sınırlardan biraz içeride kalınır.
DELAY_RATIO_RANGE = (0.16, 0.24)

# Gün içi pencere (dakika): ilk tarife 00:30; son off-block 23:35 (iz ve kalkış aynı günde biter).
DAY_START = 30
DAY_END = 23 * 60 + 35
TRACK_MINUTES = 20
TRACK_STEP_SECONDS = 30
# Aynı uçağın iki rotasyonu arasında, ve aynı stand'ı kullanan iki uçak arasında bırakılan süre.
ROTATION_GAP = 60
STAND_BUFFER = 10
# Gerçekleşen block zamanı tahmini zamandan bu kadar sapabilir.
BLOCK_DEVIATION = (-3, 4)

# En çok geciken altı hareketin dakikaları bu aralıktan, birbirinden farklı çekilir; diğer
# gecikmeler aralığın altında kalır, böylece ilk altı sıra belirsizlik taşımaz.
TOP_DELAY_COUNT = 6
TOP_DELAY_RANGE = (130, 250)
SINGLE_DELAY_RANGE = (15, 120)
# Günde iki rotasyon yapan uçakta gecikme kısa tutulur; ikinci rotasyon gün içine sığsın.
DOUBLE_DELAY_RANGE = (15, 60)

# Sabit kayıtlar (§9): her seed ve tarihte aynıdır.
PINNED_AIRCRAFT = {
    "registration": "TC-LSD",
    "type_icao": "A321",
    "code_letter": "C",
    "operator_iata": "TK",
}
PINNED_ARRIVAL_NO = "TK2344"
PINNED_DEPARTURE_NO = "TK2345"
PINNED_CALLSIGN_PREFIX = "THY"
PINNED_ARRIVAL_TIME = 13 * 60 + 5
PINNED_DEPARTURE_TIME = 15 * 60 + 40
PINNED_DEPARTURE_DELAY = 25
PINNED_NUMBER = 2344

# (IATA, ICAO callsign öneki, ağırlık)
OPERATORS = (
    ("TK", "THY", 50),
    ("AJ", "TKJ", 12),
    ("PC", "PGT", 8),
    ("LH", "DLH", 5),
    ("BA", "BAW", 4),
    ("AF", "AFR", 4),
    ("KL", "KLM", 4),
    ("LX", "SWR", 3),
    ("QR", "QTR", 5),
    ("EK", "UAE", 5),
)

# (ICAO tip kodu, kod harfi, ağırlık)
AIRCRAFT_TYPES = (
    ("A320", "C", 14),
    ("A321", "C", 18),
    ("B738", "C", 14),
    ("B38M", "C", 10),
    ("E190", "C", 5),
    ("AT76", "C", 4),
    ("A333", "E", 9),
    ("A359", "E", 7),
    ("B77W", "E", 9),
    ("B789", "E", 10),
)

AIRPORTS = (
    "ESB", "AYT", "ADB", "ADA", "TZX", "GZT", "DIY", "VAN", "ERZ", "SZF",
    "LHR", "FRA", "CDG", "AMS", "FCO", "MAD", "BCN", "MUC", "VIE", "ZRH",
    "ATH", "SOF", "OTP", "WAW", "DXB", "DOH", "CAI", "JFK", "ORD", "ICN",
)  # fmt: skip

DELAY_CODES = {
    "PASSENGER_BAGGAGE": ("11", "12", "14"),
    "AIRCRAFT_TECHNICAL": ("41", "42", "46"),
    "GROUND_HANDLING": ("31", "32", "33"),
    "WEATHER": ("71", "72", "75"),
    "ATC_RESTRICTION": ("81", "82", "83"),
    "AIRPORT_FACILITIES": ("87", "88", "89"),
    "REACTIONARY": ("91", "93", "94"),
}
DELAY_CATEGORIES = tuple(DELAY_CODES)
DELAY_CATEGORY_WEIGHTS = (14, 12, 16, 8, 14, 6, 30)

# Kurgusal yerleşim: İGA çevresinde ızgara. Gerçek stand geometrisi değildir (Gün 4).
AIRPORT_LAT = 41.262
AIRPORT_LON = 28.742
ARRIVAL_THRESHOLD = (41.2850, 28.7030)
DEPARTURE_THRESHOLD = (41.2420, 28.7650)
APPROACH_ENTRIES = ((41.5200, 28.6200), (41.4800, 28.4500), (41.5500, 28.8800))
CLIMB_EXITS = ((40.9800, 29.0500), (41.0500, 28.4000), (41.0200, 29.2000))

PIERS = ("A", "B", "C", "D")
GATES_PER_PIER = 18
BUS_GATE_COUNT = 8
CONTACT_STAND_COUNT = 72
REMOTE_STAND_COUNT = 48
# Contact stand'lar için kod harfi dağılımı (sırayla), remote için ayrı.
CONTACT_STAND_LETTERS = ("C",) * 50 + ("E",) * 18 + ("F",) * 4
REMOTE_STAND_LETTERS = ("C",) * 30 + ("E",) * 18
CONTACT_PREFERENCE = 0.7


def weighted_choice(rng: random.Random, items: tuple, weights: tuple):
    return rng.choices(items, weights=weights, k=1)[0]


def build_aircraft(rng: random.Random) -> list[dict]:
    letters = string.ascii_uppercase
    candidates = [f"TC-{a}{b}{c}" for a in letters for b in letters for c in letters]
    candidates.remove(PINNED_AIRCRAFT["registration"])
    registrations = rng.sample(candidates, AIRCRAFT_COUNT - 1)

    operator_weights = tuple(w for _, _, w in OPERATORS)
    type_weights = tuple(w for _, _, w in AIRCRAFT_TYPES)
    aircraft = [dict(PINNED_AIRCRAFT)]
    for registration in registrations:
        operator = weighted_choice(rng, OPERATORS, operator_weights)
        type_icao, code_letter, _ = weighted_choice(rng, AIRCRAFT_TYPES, type_weights)
        aircraft.append(
            {
                "registration": registration,
                "type_icao": type_icao,
                "code_letter": code_letter,
                "operator_iata": operator[0],
            }
        )
    return sorted(aircraft, key=lambda a: a["registration"])


def build_stands(rng: random.Random) -> list[dict]:
    stands = []
    for i, letter in enumerate(CONTACT_STAND_LETTERS):
        pier, slot = divmod(i, GATES_PER_PIER)
        stands.append(
            {
                "stand_code": f"C{101 + i}",
                "stand_type": "CONTACT",
                "max_code_letter": letter,
                "mars": letter != "C" and slot % 2 == 0,
                "status": "AVAILABLE",
                "lat": round(AIRPORT_LAT + 0.0030 * pier, 6),
                "lon": round(AIRPORT_LON + 0.0009 * slot, 6),
            }
        )
    for i, letter in enumerate(REMOTE_STAND_LETTERS):
        row, slot = divmod(i, 12)
        stands.append(
            {
                "stand_code": f"R{201 + i}",
                "stand_type": "REMOTE",
                "max_code_letter": letter,
                "mars": False,
                "status": "AVAILABLE",
                "lat": round(AIRPORT_LAT - 0.0060 - 0.0025 * row, 6),
                "lon": round(AIRPORT_LON + 0.0011 * slot, 6),
            }
        )

    unavailable = rng.sample(range(len(stands)), rng.randint(*UNAVAILABLE_STAND_RANGE))
    for i in sorted(unavailable):
        stands[i]["status"] = "UNAVAILABLE"
    return stands


def build_gates(stands: list[dict]) -> list[dict]:
    contact = [s for s in stands if s["stand_type"] == "CONTACT"]
    gates = []
    for i, stand in enumerate(contact):
        pier, slot = divmod(i, GATES_PER_PIER)
        gates.append(
            {
                "gate_code": f"{PIERS[pier]}{slot + 1}",
                "terminal": "T1",
                "pier": PIERS[pier],
                "stand_code": stand["stand_code"],
            }
        )
    for i in range(BUS_GATE_COUNT):
        gates.append(
            {
                "gate_code": f"BUS{i + 1}",
                "terminal": "T1",
                "pier": "BUS",
                "stand_code": None,
            }
        )
    return sorted(gates, key=lambda g: g["gate_code"])


def pair_span(pair: dict) -> int:
    """Tarifeli arrival'dan en geç off-block'a kadar geçebilecek süre (dakika)."""
    return pair["turnaround"] + pair["dep_delay"] + BLOCK_DEVIATION[1]


def slot(rng: random.Random, earliest: int, latest: int) -> int:
    """[earliest, latest] içinde 5 dakikalık tarife saati çeker."""
    first = math.ceil(earliest / 5) * 5
    last = latest // 5 * 5
    if last < first:
        raise RuntimeError("Rotasyon gün içine sığmıyor.")
    return first + 5 * rng.randint(0, (last - first) // 5)


def schedule_pair(rng: random.Random, pair: dict, arrival: int) -> None:
    pair["arr_sched"] = arrival
    pair["dep_sched"] = arrival + pair["turnaround"]
    if pair["cancelled"]:
        return
    pair["on_block"] = arrival + pair["arr_delay"] + rng.randint(*BLOCK_DEVIATION)
    pair["off_block"] = (
        pair["dep_sched"] + pair["dep_delay"] + rng.randint(*BLOCK_DEVIATION)
    )


def build_pairs(rng: random.Random, aircraft: list[dict]) -> list[dict]:
    """Uçak başına bir ya da iki rotasyon (arrival + departure çifti) kurar."""
    pair_count = rng.randint(*PAIR_RANGE)
    pinned_registration = PINNED_AIRCRAFT["registration"]
    others = [a for a in aircraft if a["registration"] != pinned_registration]
    # Yalnızca üyelik sorgusu; sırası hiçbir yerde kullanılmaz.
    doubled = {
        a["registration"] for a in rng.sample(others, pair_count - AIRCRAFT_COUNT)
    }

    pinned = {
        "aircraft": next(
            a for a in aircraft if a["registration"] == pinned_registration
        ),
        "pinned": True,
        "double": False,
        "cancelled": False,
    }
    pairs = [pinned]
    for a in others:
        for _ in range(2 if a["registration"] in doubled else 1):
            pairs.append(
                {
                    "aircraft": a,
                    "pinned": False,
                    "double": a["registration"] in doubled,
                    "cancelled": False,
                }
            )

    singles = [p for p in pairs if not p["pinned"] and not p["double"]]
    for p in rng.sample(singles, rng.randint(*CANCELLED_PAIR_RANGE)):
        p["cancelled"] = True

    assign_delays(rng, pairs)

    for p in pairs:
        base = rng.randint(50, 110 if p["double"] else 150)
        p["turnaround"] = max(base, p["arr_delay"] + 50)
    pinned["turnaround"] = PINNED_DEPARTURE_TIME - PINNED_ARRIVAL_TIME

    schedule_pair(rng, pinned, PINNED_ARRIVAL_TIME)
    by_aircraft: dict[str, list[dict]] = {}
    for p in pairs:
        if not p["pinned"]:
            by_aircraft.setdefault(p["aircraft"]["registration"], []).append(p)
    for registration in sorted(by_aircraft):
        rotations = by_aircraft[registration]
        if len(rotations) == 1:
            (p,) = rotations
            schedule_pair(rng, p, slot(rng, DAY_START, DAY_END - pair_span(p)))
        else:
            first, second = rotations
            latest = DAY_END - pair_span(second) - ROTATION_GAP - pair_span(first)
            schedule_pair(rng, first, slot(rng, DAY_START, latest))
            earliest = first["off_block"] + ROTATION_GAP
            schedule_pair(rng, second, slot(rng, earliest, DAY_END - pair_span(second)))
    return pairs


def assign_delays(rng: random.Random, pairs: list[dict]) -> None:
    for p in pairs:
        p["arr_delay"] = 0
        p["dep_delay"] = 0
        p["arr_delay_reason"] = None
        p["dep_delay_reason"] = None
    pinned = next(p for p in pairs if p["pinned"])
    pinned["dep_delay"] = PINNED_DEPARTURE_DELAY

    active = sum(2 for p in pairs if not p["cancelled"])
    delay_count = rng.randint(
        math.ceil(DELAY_RATIO_RANGE[0] * active),
        math.floor(DELAY_RATIO_RANGE[1] * active),
    )
    # Hareket: (çift sırası, "arr" | "dep"). Sabit çift rastgele gecikme almaz.
    eligible = [
        (i, side)
        for i, p in enumerate(pairs)
        if not p["cancelled"] and not p["pinned"]
        for side in ("arr", "dep")
    ]
    singles = [m for m in eligible if not pairs[m[0]]["double"]]
    top = rng.sample(singles, TOP_DELAY_COUNT)
    top_minutes = rng.sample(
        range(TOP_DELAY_RANGE[0], TOP_DELAY_RANGE[1] + 1), TOP_DELAY_COUNT
    )
    remaining = [m for m in eligible if m not in top]
    rest = rng.sample(remaining, delay_count - 1 - TOP_DELAY_COUNT)

    for (i, side), minutes in zip(top, top_minutes, strict=True):
        pairs[i][f"{side}_delay"] = minutes
    for i, side in rest:
        bounds = DOUBLE_DELAY_RANGE if pairs[i]["double"] else SINGLE_DELAY_RANGE
        pairs[i][f"{side}_delay"] = rng.randint(*bounds)

    weights = DELAY_CATEGORY_WEIGHTS
    for p in pairs:
        for side in ("arr", "dep"):
            if p[f"{side}_delay"]:
                category = weighted_choice(rng, DELAY_CATEGORIES, weights)
                p[f"{side}_delay_reason"] = (
                    rng.choice(DELAY_CODES[category]),
                    category,
                )


def assign_stands(
    rng: random.Random, pairs: list[dict], stands: list[dict], gates: list[dict]
):
    """Stand'ları on-block sırasıyla, boş ve kod harfine uygun olanlardan dağıtır."""
    gate_by_stand = {g["stand_code"]: g["gate_code"] for g in gates if g["stand_code"]}
    bus_gates = [g["gate_code"] for g in gates if g["stand_code"] is None]
    available = [s for s in stands if s["status"] == "AVAILABLE"]
    free_at = {s["stand_code"]: 0 for s in available}

    active = [p for p in pairs if not p["cancelled"]]
    active.sort(
        key=lambda p: (p["on_block"], p["aircraft"]["registration"], p["arr_sched"])
    )
    for p in active:
        letter = p["aircraft"]["code_letter"]
        fits = [
            s
            for s in available
            if s["max_code_letter"] >= letter
            and free_at[s["stand_code"]] <= p["on_block"]
        ]
        contact = [s for s in fits if s["stand_type"] == "CONTACT"]
        remote = [s for s in fits if s["stand_type"] == "REMOTE"]
        preferred, fallback = (
            (contact, remote)
            if rng.random() < CONTACT_PREFERENCE
            else (remote, contact)
        )
        candidates = preferred or fallback
        if not candidates:
            raise RuntimeError("Uygun boş stand bulunamadı.")
        stand = rng.choice(candidates)
        code = stand["stand_code"]
        free_at[code] = p["off_block"] + STAND_BUFFER
        p["stand_code"] = code
        p["gate_code"] = gate_by_stand.get(code) or rng.choice(bus_gates)


def assign_flight_numbers(rng: random.Random, pairs: list[dict]) -> None:
    numbers = [n for n in range(100, 9000, 2) if n != PINNED_NUMBER]
    bases = rng.sample(numbers, len(pairs) - 1)
    others = [p for p in pairs if not p["pinned"]]
    icao = {iata: prefix for iata, prefix, _ in OPERATORS}
    for p, base in zip(others, bases, strict=True):
        p["number"] = base
        p["operator"] = p["aircraft"]["operator_iata"]
        p["prefix"] = icao[p["operator"]]
        p["airport"] = rng.choice(AIRPORTS)
    pinned = next(p for p in pairs if p["pinned"])
    pinned["number"] = PINNED_NUMBER
    pinned["operator"] = "TK"
    pinned["prefix"] = PINNED_CALLSIGN_PREFIX
    pinned["airport"] = rng.choice(AIRPORTS)


def interpolate(start: tuple, end: tuple, fraction: float) -> tuple[float, float]:
    return (
        start[0] + (end[0] - start[0]) * fraction,
        start[1] + (end[1] - start[1]) * fraction,
    )


def bearing(start: tuple, end: tuple) -> float:
    dlat = end[0] - start[0]
    dlon = (end[1] - start[1]) * math.cos(math.radians(start[0]))
    return math.degrees(math.atan2(dlon, dlat)) % 360


def track_point(
    flight_id: str, ts: datetime, point: tuple, heading: float, speed: float, phase
):
    return {
        "flight_id": flight_id,
        "ts": ts.isoformat(),
        "lat": round(point[0], 6),
        "lon": round(point[1], 6),
        "heading_deg": round(heading, 1),
        "speed_kt": round(speed, 1),
        "phase": phase,
    }


def build_track(flight_id: str, kind: str, block: datetime, runway: datetime, stand: tuple,
                outer: tuple) -> list[dict]:  # fmt: skip
    """Doğrusal ara değerlemeli 20 dakikalık iz; arrival on-block'ta biter, departure başlar."""
    step = timedelta(seconds=TRACK_STEP_SECONDS)
    count = TRACK_MINUTES * 60 // TRACK_STEP_SECONDS
    points = []
    if kind == "ARRIVAL":
        start = block - timedelta(minutes=TRACK_MINUTES)
        for k in range(count + 1):
            ts = start + k * step
            if ts < runway:
                f = (ts - start) / (runway - start)
                point = interpolate(outer, ARRIVAL_THRESHOLD, f)
                heading = bearing(outer, ARRIVAL_THRESHOLD)
                points.append(
                    track_point(flight_id, ts, point, heading, 220 - 80 * f, "APPROACH")
                )
            elif ts < block:
                f = (ts - runway) / (block - runway)
                point = interpolate(ARRIVAL_THRESHOLD, stand, f)
                heading = bearing(ARRIVAL_THRESHOLD, stand)
                points.append(track_point(flight_id, ts, point, heading, 15, "TAXI_IN"))
            else:
                heading = bearing(ARRIVAL_THRESHOLD, stand)
                points.append(track_point(flight_id, ts, stand, heading, 0, "AT_STAND"))
    else:
        end = block + timedelta(minutes=TRACK_MINUTES)
        for k in range(count + 1):
            ts = block + k * step
            if ts < runway:
                f = (ts - block) / (runway - block)
                point = interpolate(stand, DEPARTURE_THRESHOLD, f)
                heading = bearing(stand, DEPARTURE_THRESHOLD)
                speed = 0 if k == 0 else 12
                points.append(
                    track_point(flight_id, ts, point, heading, speed, "TAXI_OUT")
                )
            else:
                f = (ts - runway) / (end - runway)
                point = interpolate(DEPARTURE_THRESHOLD, outer, f)
                heading = bearing(DEPARTURE_THRESHOLD, outer)
                points.append(
                    track_point(flight_id, ts, point, heading, 160 + 120 * f, "CLIMB")
                )
    return points


def generate(seed: int, day: date) -> dict:
    rng = random.Random(seed)
    midnight = datetime(day.year, day.month, day.day, tzinfo=TZ)

    def at(minutes: int) -> datetime:
        return midnight + timedelta(minutes=minutes)

    aircraft = build_aircraft(rng)
    stands = build_stands(rng)
    gates = build_gates(stands)
    pairs = build_pairs(rng, aircraft)
    assign_stands(rng, pairs, stands, gates)
    assign_flight_numbers(rng, pairs)

    stand_position = {s["stand_code"]: (s["lat"], s["lon"]) for s in stands}
    pairs.sort(
        key=lambda p: (p["arr_sched"], p["aircraft"]["registration"], p["number"])
    )

    flights, movements, delays, positions = [], [], [], []
    stamp = day.strftime("%Y%m%d")
    for n, p in enumerate(pairs):
        registration = p["aircraft"]["registration"]
        for side, kind, seq in (
            ("arr", "ARRIVAL", 2 * n + 1),
            ("dep", "DEPARTURE", 2 * n + 2),
        ):
            flight_id = f"FL-{stamp}-{seq:04d}"
            number = p["number"] + (0 if side == "arr" else 1)
            scheduled = p[f"{side}_sched"]
            delay = p[f"{side}_delay"]
            arriving = kind == "ARRIVAL"
            flights.append(
                {
                    "flight_id": flight_id,
                    "flight_no": f"{p['operator']}{number}",
                    "callsign": f"{p['prefix']}{number}",
                    "registration": registration,
                    "aircraft_type": p["aircraft"]["type_icao"],
                    "origin": p["airport"] if arriving else LOCAL_AIRPORT,
                    "destination": LOCAL_AIRPORT if arriving else p["airport"],
                    "scheduled_time": at(scheduled).isoformat(),
                    "estimated_time": at(scheduled + delay).isoformat(),
                    "cancelled": p["cancelled"],
                }
            )

            if p["cancelled"]:
                movements.append(
                    {
                        "flight_id": flight_id,
                        "movement_type": kind,
                        "stand_code": None,
                        "gate_code": None,
                        "actual_runway_time": None,
                        "actual_block_time": None,
                    }
                )
                continue

            block = at(p["on_block"] if arriving else p["off_block"])
            taxi = timedelta(
                minutes=rng.randint(4, 12) if arriving else rng.randint(6, 15)
            )
            runway = block - taxi if arriving else block + taxi
            movements.append(
                {
                    "flight_id": flight_id,
                    "movement_type": kind,
                    "stand_code": p["stand_code"],
                    "gate_code": p["gate_code"],
                    "actual_runway_time": runway.isoformat(),
                    "actual_block_time": block.isoformat(),
                }
            )
            outer = rng.choice(APPROACH_ENTRIES if arriving else CLIMB_EXITS)
            positions.extend(
                build_track(
                    flight_id,
                    kind,
                    block,
                    runway,
                    stand_position[p["stand_code"]],
                    outer,
                )
            )
            if delay:
                code, category = p[f"{side}_delay_reason"]
                delays.append(
                    {
                        "flight_id": flight_id,
                        "delay_minutes": delay,
                        "delay_code": code,
                        "category": category,
                    }
                )

    return {
        "meta": {
            "seed": seed,
            "date": day.isoformat(),
            "generator_version": GENERATOR_VERSION,
        },
        "aircraft": aircraft,
        "stands": stands,
        "gates": gates,
        "flights": flights,
        "movements": movements,
        "delays": delays,
        "positions": sorted(positions, key=lambda p: (p["flight_id"], p["ts"])),
    }


def summary(data: dict) -> str:
    kinds = [m["movement_type"] for m in data["movements"]]
    cancelled = sum(f["cancelled"] for f in data["flights"])
    return (
        f"toplam={len(kinds)} arrival={kinds.count('ARRIVAL')} "
        f"departure={kinds.count('DEPARTURE')} gecikmeli={len(data['delays'])} "
        f"iptal={cancelled} uçak={len(data['aircraft'])} stand={len(data['stands'])} "
        f"gate={len(data['gates'])}"
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Bir günlük sentetik AODB verisi üretir."
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--date", type=date.fromisoformat, required=True, help="YYYY-MM-DD"
    )
    parser.add_argument("--out", type=Path, required=True, help="Çıktı JSON dosyası")
    args = parser.parse_args(argv)

    data = generate(args.seed, args.date)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": Windows'ta da birebir aynı byte'lar yazılır.
    args.out.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(summary(data))


if __name__ == "__main__":
    main()
