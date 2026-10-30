"""Grafik sorgu motoru ve tarif denetimi (spec: 2026-10-30-…-design.md › B).

Saf fonksiyonlar: ağa, dosyaya ve sistem saatine bağlanmaz. Girdi chart_fields
.build_rows satırlarıdır; çıktı grafiğin noktalarıdır. Model tarifi verir, sayıyı bu
modül hesaplar (CLAUDE.md › Yasaklar: model hesap yapmaz).
"""

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from backend.tools.chart_fields import FIELDS, TIME

MAX_SERIES = 8
MAX_CELLS = 200
MAX_IN_VALUES = 20
LIMITS = (5, 10, 20, 50)
BUCKETS = ("hour", "half_hour")
STATUS_ORDER = ("cancelled", "delayed", "on_time")
# Kova başına dakika ve grup üst sınırı (hücre sınırı denetimi için).
BUCKET_MINUTES = {"hour": 60, "half_hour": 30}
BUCKET_GROUPS = {"hour": 24, "half_hour": 48}
STATUS_GROUPS = 3
CHANGE_PLOT_TYPES = ("bar_horizontal", "bar_vertical", "grouped_bar", "line", "area")
SERIES_REQUIRED = ("stacked_bar", "grouped_bar", "heatmap")
SERIES_FORBIDDEN = ("pie", "doughnut")
TIME_OF_DAY = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
COMPARING = {"gt", "ge", "lt", "le"}


# --- Tarif denetimi --------------------------------------------------------------


def _iso(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _check_value(field: str, value: object) -> str | None:
    kind = FIELDS[field].kind
    if kind == "numeric":
        return None if _is_number(value) else f"{field} için sayı bekleniyor."
    if kind == "time":
        if isinstance(value, str) and (TIME_OF_DAY.fullmatch(value) or _iso(value)):
            return None
        return f"{field} için saat dilimli ISO zaman ya da HH:MM bekleniyor."
    if isinstance(value, str) or (field == "cancelled" and isinstance(value, bool)):
        return None
    return f"{field} için metin bekleniyor."


def _check_filter(item: dict) -> str | None:
    field, op, value = item["field"], item["op"], item["value"]
    kind = FIELDS[field].kind
    if op in COMPARING and kind == "categorical":
        return f"{op} kategorik alanda kullanılamaz: {field}."
    if op == "in":
        if not isinstance(value, list) or not value:
            return "in için boş olmayan bir dizi gerekir."
        if len(value) > MAX_IN_VALUES:
            return f"in en çok {MAX_IN_VALUES} değer alır."
        values = value
    elif isinstance(value, list):
        return f"{op} için tek değer gerekir."
    else:
        values = [value]
    for single in values:
        message = _check_value(field, single)
        if message is not None:
            return message
    return None


def _check_bucket(spec: dict, name: str) -> str | None:
    field = FIELDS[spec["field"]]
    if field.kind == "numeric":
        return f"{name} sayısal alan olamaz."
    if field.kind == "time" and "bucket" not in spec:
        return f"{name} zaman alanı için bucket gerekir."
    if field.kind != "time" and "bucket" in spec:
        return f"bucket yalnızca zaman alanıyla kullanılır ({name})."
    return None


def check_query(args: dict) -> str | None:
    """Şemanın anlatamadığı kuralları denetler; ihlalde mesaj, yoksa None."""
    chart_type = args["chart_type"]
    group_by = args["group_by"]
    series_by = args.get("series_by")
    measure = args.get("measure") or {"agg": "count"}
    derive = args.get("derive")
    group_is_bucket = FIELDS[group_by["field"]].kind == "time" and "bucket" in group_by

    message = _check_bucket(group_by, "group_by")
    if message is None and series_by is not None:
        message = _check_bucket(series_by, "series_by")
    if message is not None:
        return message
    if series_by is not None and series_by["field"] == group_by["field"]:
        return "series_by, group_by ile aynı alan olamaz."
    if chart_type in ("line", "area") and not group_is_bucket:
        return f"{chart_type} yalnızca zaman kovasıyla (bucket) kullanılır."
    if chart_type in SERIES_REQUIRED and series_by is None:
        return f"{chart_type} için series_by gerekir."
    if chart_type in SERIES_FORBIDDEN and series_by is not None:
        return f"{chart_type} ile series_by kullanılamaz."
    if measure["agg"] == "count":
        if "field" in measure:
            return "count ölçüsü alan almaz."
    elif FIELDS.get(measure.get("field", ""), None) is None or (
        FIELDS[measure["field"]].kind != "numeric"
    ):
        return f"{measure['agg']} için sayısal bir alan gerekir."
    for item in args.get("filters") or []:
        message = _check_filter(item)
        if message is not None:
            return message
    if derive is not None and not group_is_bucket:
        return "derive yalnızca zaman kovasıyla (bucket) kullanılır."
    if args.get("plot", "value") == "change_pct":
        if derive is None:
            return "plot change_pct için derive gerekir."
        if chart_type not in CHANGE_PLOT_TYPES:
            return f"{chart_type} ile değişim (change_pct) çizilemez."
    if series_by is not None:
        if group_is_bucket:
            groups = BUCKET_GROUPS[group_by["bucket"]]
        elif group_by["field"] == "status":
            groups = STATUS_GROUPS
        else:
            groups = args.get("limit", 10)
        if groups * MAX_SERIES > MAX_CELLS:
            return (
                f"Hücre sayısı en çok {MAX_CELLS} olabilir "
                "(limit/bucket küçültülmeli)."
            )
    return None


# --- Süzgeç ------------------------------------------------------------------------


def _compare(actual: Any, value: Any, kind: str) -> int:
    """actual ile value sırası: -1, 0, 1 (zaman: ISO kronolojik ya da HH:MM)."""
    if kind == "time":
        moment = datetime.fromisoformat(actual)
        if TIME_OF_DAY.fullmatch(value):
            left = moment.hour * 60 + moment.minute
            right = int(value[:2]) * 60 + int(value[3:])
        else:
            left, right = moment.timestamp(), datetime.fromisoformat(value).timestamp()
    elif kind == "categorical":
        left, right = actual, _normalize(value)
    else:
        left, right = actual, value
    return (left > right) - (left < right)


def _normalize(value: Any) -> Any:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _matches(row: dict, item: dict) -> bool:
    field, op, value = item["field"], item["op"], item["value"]
    if field not in row:
        return False
    kind = FIELDS[field].kind
    actual = row[field]
    if op == "in":
        return any(_compare(actual, one, kind) == 0 for one in value)
    order = _compare(actual, value, kind)
    return {
        "eq": order == 0,
        "ne": order != 0,
        "gt": order > 0,
        "ge": order >= 0,
        "lt": order < 0,
        "le": order <= 0,
    }[op]


# --- Gruplama ----------------------------------------------------------------------


def _label(row: dict, spec: dict) -> str | None:
    """Satırın grup/seri etiketi; alan satırda yoksa None."""
    value = row.get(spec["field"])
    if value is None:
        return None
    bucket = spec.get("bucket")
    if bucket is None:
        return value
    moment = datetime.fromisoformat(value)
    minute = 0 if bucket == "hour" or moment.minute < 30 else 30
    return f"{moment.hour:02d}:{minute:02d}"


def _aggregate(rows: list[dict], measure: dict) -> float | None:
    agg = measure["agg"]
    if agg == "count":
        return len(rows)
    values = [row[measure["field"]] for row in rows if measure["field"] in row]
    if not values:
        return None
    if agg == "sum":
        return sum(values)
    if agg == "avg":
        return round(sum(values) / len(values), 1)
    return min(values) if agg == "min" else max(values)


def _ranked(values: dict[str, float], sort: str) -> list[str]:
    if sort == "label":
        return sorted(values)
    sign = 1 if sort == "value_asc" else -1
    return sorted(values, key=lambda label: (sign * values[label], label))


def _previous(label: str, bucket: str) -> str | None:
    minutes = int(label[:2]) * 60 + int(label[3:]) - BUCKET_MINUTES[bucket]
    return None if minutes < 0 else f"{minutes // 60:02d}:{minutes % 60:02d}"


def _add_change(items: list[dict], bucket: str) -> None:
    by_key = {(item["label"], item.get("series")): item["value"] for item in items}
    for item in items:
        previous = _previous(item["label"], bucket)
        before = by_key.get((previous, item.get("series")))
        if before is None or before <= 0:
            continue
        item["change_pct"] = round((item["value"] - before) / before * 100, 1)
        change = item["value"] - before
        item["trend"] = "up" if change > 0 else "down" if change < 0 else "flat"


def run_query(
    rows: list[dict],
    *,
    group_by: dict,
    series_by: dict | None,
    measure: dict,
    filters: list[dict],
    sort: str,
    limit: int,
    derive: str | None = None,
) -> dict:
    scoped = [row for row in rows if all(_matches(row, item) for item in filters)]
    cells: dict[tuple[str, str | None], list[dict]] = defaultdict(list)
    unclassified = 0
    for row in scoped:
        group = _label(row, group_by)
        series = None if series_by is None else _label(row, series_by)
        if group is None or (series_by is not None and series is None):
            unclassified += 1
            continue
        cells[(group, series)].append(row)

    by_group: dict[str, list[dict]] = defaultdict(list)
    by_series: dict[str, list[dict]] = defaultdict(list)
    for (group, series), members in cells.items():
        by_group[group].extend(members)
        if series is not None:
            by_series[series].extend(members)
    group_values = {
        label: value
        for label, members in by_group.items()
        if (value := _aggregate(members, measure)) is not None
    }

    natural = group_by.get("bucket") is not None or group_by["field"] == "status"
    if group_by["field"] == "status":
        order = sorted(group_values, key=STATUS_ORDER.index)
    elif natural:
        order = sorted(group_values)
    else:
        order = _ranked(group_values, sort)
    kept = order if natural else order[:limit]

    series_order: list[str | None] = [None]
    series_truncated = 0
    if series_by is not None:
        series_values = {
            label: value
            for label, members in by_series.items()
            if (value := _aggregate(members, measure)) is not None
        }
        ranked = _ranked(series_values, "value_desc")
        series_order = ranked[:MAX_SERIES]
        series_truncated = len(ranked) - len(series_order)

    items = []
    for group in kept:
        for series in series_order:
            members = cells.get((group, series))
            value = None if not members else _aggregate(members, measure)
            if value is None:
                continue
            item = {"label": group, "value": value}
            if series is not None:
                item = {"label": group, "series": series, "value": value}
            items.append(item)
    if derive is not None and group_by.get("bucket") is not None:
        _add_change(items, group_by["bucket"])

    result = {
        "flights": len(scoped),
        "groups_total": len(group_values),
        "unclassified": unclassified,
        "items": items,
    }
    if series_by is not None:
        result["series_truncated"] = series_truncated
    return result


__all__ = [
    "BUCKETS",
    "LIMITS",
    "MAX_CELLS",
    "MAX_IN_VALUES",
    "MAX_SERIES",
    "TIME",
    "check_query",
    "run_query",
]
