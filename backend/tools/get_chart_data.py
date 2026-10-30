"""get_chart_data: uçuş listesi üzerinde genel grafik sorgusu (docs/tools.md).

Model grafiğin tarifini verir (tür, gruplama, ölçü, süzgeç, değişim); noktaları bu
tool hesaplar. Düz uçuş görünümü chart_fields.py'de, sorgu motoru chart_query.py'de
durur. Tool zarf kurmaz ve saati okumaz; yalnızca {value, source} döndürür. Hesap için
zorunlu alan eksikse DataError fırlatır, zarfı run_tool kurar.
"""

from backend.tools._ortak import DataError, load_data
from backend.tools.chart_fields import DATA_KEYS, build_rows
from backend.tools.chart_query import run_query


def get_chart_data(
    chart_type: str,
    group_by: dict,
    series_by: dict | None = None,
    measure: dict | None = None,
    filters: list | None = None,
    sort: str = "value_desc",
    limit: int = 10,
    derive: str | None = None,
    plot: str = "value",
) -> dict:
    data, source = load_data(DATA_KEYS)

    meta = data["meta"]
    if not isinstance(meta, dict) or "date" not in meta:
        raise DataError("meta kaydında zorunlu alan yok: date")
    measure = measure or {"agg": "count"}

    result = run_query(
        build_rows(data),
        group_by=group_by,
        series_by=series_by,
        measure=measure,
        filters=filters or [],
        sort=sort,
        limit=limit,
        derive=derive,
    )
    value = {
        "date": meta["date"],
        "chart_type": chart_type,
        "group_by": group_by,
        "measure": measure,
        "plot": plot,
        **result,
    }
    if series_by is not None:
        value["series_by"] = series_by
    if derive is not None:
        value["derive"] = derive
    return {"value": value, "source": source}
