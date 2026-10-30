"""Grafik sorgu motoru ve tarif denetimi (spec: 2026-10-30-…-design.md › B).

Küçük elle yazılmış satırlarla çalışır; dosya, ağ ve model yok. Beklenen değerler
her testte tam yazılır.
"""

import importlib
import importlib.util

import pytest

MODULE = "backend.tools.chart_query"


def load():
    assert importlib.util.find_spec(MODULE) is not None, f"{MODULE} yok"
    return importlib.import_module(MODULE)


def q(rows, **overrides):
    args = {
        "group_by": {"field": "airline"},
        "series_by": None,
        "measure": {"agg": "count"},
        "filters": [],
        "sort": "value_desc",
        "limit": 10,
        "derive": None,
    }
    return load().run_query(rows, **(args | overrides))


def counts(result):
    return [(item["label"], item["value"]) for item in result["items"]]


def airlines(spec: dict[str, int], **extra) -> list[dict]:
    return [{"airline": code, **extra} for code, n in spec.items() for _ in range(n)]


def at(time: str, **extra) -> dict:
    return {"scheduled_time": f"2026-10-20T{time}:00+03:00", **extra}


HOUR = {"field": "scheduled_time", "bucket": "hour"}


def test_modul_var():
    assert load() is not None


# --- Gruplama ----------------------------------------------------------------


def test_sayim_degere_gore_azalan_esitlikte_etikete_gore_artan():
    result = q(airlines({"TK": 3, "AJ": 3, "QR": 1}))

    assert counts(result) == [("AJ", 3), ("TK", 3), ("QR", 1)]
    assert result["flights"] == 7
    assert result["groups_total"] == 3
    assert result["unclassified"] == 0


def test_value_asc_ve_label_siralari():
    rows = airlines({"TK": 3, "AJ": 3, "QR": 1})

    assert counts(q(rows, sort="value_asc")) == [("QR", 1), ("AJ", 3), ("TK", 3)]
    assert counts(q(rows, sort="label")) == [("AJ", 3), ("QR", 1), ("TK", 3)]


def test_limit_kirpar_groups_total_kalir():
    result = q(airlines({"TK": 3, "AJ": 3, "QR": 1}), limit=2)

    assert counts(result) == [("AJ", 3), ("TK", 3)]
    assert result["groups_total"] == 3


# --- Kova ---------------------------------------------------------------------


def test_hour_kovasi_etiketi_HH_00_ve_zaman_sirasi_limitsiz():
    rows = [at("14:00"), at("09:10"), at("09:50")]

    result = q(rows, group_by=HOUR, limit=1)

    assert counts(result) == [("09:00", 2), ("14:00", 1)]
    assert result["groups_total"] == 2


def test_half_hour_kovasi_29_dakika_00_30_dakika_30():
    rows = [at("10:29"), at("10:30"), at("10:59"), at("11:00")]

    result = q(rows, group_by={"field": "scheduled_time", "bucket": "half_hour"})

    assert counts(result) == [("10:00", 1), ("10:30", 2), ("11:00", 1)]


def test_status_siralamasi_sabit():
    rows = (
        [{"status": "on_time"}] * 3
        + [{"status": "cancelled"}]
        + [{"status": "delayed"}] * 2
    )

    result = q(rows, group_by={"field": "status"}, limit=1)

    assert counts(result) == [("cancelled", 1), ("delayed", 2), ("on_time", 3)]


# --- Ölçüler --------------------------------------------------------------------


def delay_rows() -> list[dict]:
    rows = [{"airline": "TK", "delay_minutes": m} for m in (10, 20, 40)]
    return rows + [{"airline": "AJ", "delay_minutes": 5}, {"airline": "QR"}]


def test_sum_avg_min_max_delay_minutes():
    rows = delay_rows()
    field = {"field": "delay_minutes"}

    assert counts(q(rows, measure={"agg": "sum", **field}))[0] == ("TK", 70)
    assert counts(q(rows, measure={"agg": "avg", **field}))[0] == ("TK", 23.3)
    assert dict(counts(q(rows, measure={"agg": "min", **field}))) == {"TK": 10, "AJ": 5}
    assert dict(counts(q(rows, measure={"agg": "max", **field}))) == {"TK": 40, "AJ": 5}


def test_avg_bir_ondalik_yuvarlanir():
    rows = [{"airline": "TK", "delay_minutes": m} for m in (1, 1, 2)]

    result = q(rows, measure={"agg": "avg", "field": "delay_minutes"})

    assert counts(result) == [("TK", 1.3)]


def test_gecikmesiz_ucus_ortalamaya_girmez_ve_bos_grup_items_ta_yok():
    result = q(delay_rows(), measure={"agg": "avg", "field": "delay_minutes"})

    assert [label for label, _ in counts(result)] == ["TK", "AJ"]
    assert result["groups_total"] == 2
    assert result["flights"] == 5


def test_count_tum_suzgecli_ucuslari_sayar():
    result = q(delay_rows())

    assert dict(counts(result)) == {"TK": 3, "AJ": 1, "QR": 1}


# --- Süzgeç ---------------------------------------------------------------------


def typed_rows() -> list[dict]:
    rows = airlines({"TK": 2}, movement_type="ARRIVAL")
    rows += airlines({"TK": 1, "AJ": 2}, movement_type="DEPARTURE")
    return rows


def test_eq_ne_in():
    rows = typed_rows()

    def flights(op, value):
        f = [{"field": "movement_type", "op": op, "value": value}]
        return q(rows, filters=f)["flights"]

    assert flights("eq", "ARRIVAL") == 2
    assert flights("ne", "ARRIVAL") == 3
    assert flights("in", ["ARRIVAL", "DEPARTURE"]) == 5
    assert flights("in", ["NOPE"]) == 0


def test_ne_alani_olmayan_ucusu_gecirmez():
    rows = [{"airline": "TK", "stand_code": "C1"}, {"airline": "AJ"}]

    result = q(rows, filters=[{"field": "stand_code", "op": "ne", "value": "C2"}])

    assert result["flights"] == 1
    assert counts(result) == [("TK", 1)]


def test_gt_lt_sayisal_ve_ge_le_dahil():
    rows = [{"airline": "TK", "delay_minutes": m} for m in (10, 20, 30)]

    def flights(op):
        f = [{"field": "delay_minutes", "op": op, "value": 20}]
        return q(rows, filters=f)["flights"]

    assert (flights("gt"), flights("ge"), flights("lt"), flights("le")) == (1, 2, 1, 2)


def test_tarihsiz_saat_suzgeci_yerel_saat_bolumuyle_karsilastirir():
    rows = [at("16:59"), at("17:00"), at("18:30"), at("19:00")]
    filters = [
        {"field": "scheduled_time", "op": "ge", "value": "17:00"},
        {"field": "scheduled_time", "op": "lt", "value": "19:00"},
    ]

    result = q(rows, group_by=HOUR, filters=filters)

    assert result["flights"] == 2
    assert counts(result) == [("17:00", 1), ("18:00", 1)]


def test_tarihsiz_saat_ve_iso_ayni_alanda_birlikte():
    rows = [at("17:00"), at("17:30"), at("18:30"), at("19:00")]
    filters = [
        {"field": "scheduled_time", "op": "gt", "value": "2026-10-20T17:00:00+03:00"},
        {"field": "scheduled_time", "op": "le", "value": "18:30"},
    ]

    assert q(rows, group_by=HOUR, filters=filters)["flights"] == 2


def test_gt_lt_zaman_farkli_saat_diliminde_kronolojik():
    rows = [{"airline": "TK", "scheduled_time": "2026-10-20T10:00:00+00:00"}]

    def flights(op, value):
        f = [{"field": "scheduled_time", "op": op, "value": value}]
        return q(rows, filters=f)["flights"]

    assert flights("eq", "2026-10-20T13:00:00+03:00") == 1
    assert flights("gt", "2026-10-20T12:59:00+03:00") == 1
    assert flights("lt", "2026-10-20T12:59:00+03:00") == 0


def test_birden_cok_suzgec_ve_ile():
    rows = typed_rows()
    filters = [
        {"field": "movement_type", "op": "eq", "value": "DEPARTURE"},
        {"field": "airline", "op": "eq", "value": "AJ"},
    ]

    assert q(rows, filters=filters)["flights"] == 2


def test_hicbir_ucus_kalmazsa_items_bos_flights_sifir():
    result = q(
        typed_rows(), filters=[{"field": "airline", "op": "eq", "value": "ZZ"}]
    )

    assert result["items"] == []
    assert result["flights"] == 0
    assert result["groups_total"] == 0
    assert result["unclassified"] == 0


# --- Değişim (derive) -----------------------------------------------------------


def hourly(spec: dict[str, int], **extra) -> list[dict]:
    return [
        at(f"{hour}:{i:02d}", **extra) for hour, n in spec.items() for i in range(n)
    ]


def derived(rows, **overrides):
    overrides = {"derive": "pct_change_vs_previous"} | overrides
    return q(rows, group_by=HOUR, **overrides)["items"]


def test_change_pct_onceki_saate_gore_bir_ondalik_ve_trend():
    items = derived(hourly({"17": 4, "18": 5, "19": 3}))

    assert items == [
        {"label": "17:00", "value": 4},
        {"label": "18:00", "value": 5, "change_pct": 25.0, "trend": "up"},
        {"label": "19:00", "value": 3, "change_pct": -40.0, "trend": "down"},
    ]
    third = derived(hourly({"17": 3, "18": 4}))
    assert third[1]["change_pct"] == 33.3


def test_ilk_kovada_degisim_yok():
    first = derived(hourly({"17": 4, "18": 5}))[0]

    assert "change_pct" not in first
    assert "trend" not in first


def test_onceki_kova_yoksa_ya_da_sifirsa_alan_yazilmaz():
    missing = derived(hourly({"17": 4, "19": 5}))
    assert [("change_pct" in item) for item in missing] == [False, False]

    rows = [
        at("17:00", delay_minutes=0),
        at("18:00", delay_minutes=5),
    ]
    zero = derived(rows, measure={"agg": "sum", "field": "delay_minutes"})
    assert zero == [{"label": "17:00", "value": 0}, {"label": "18:00", "value": 5}]


def test_degisim_seri_basina_ayri_hesaplanir():
    rows = hourly({"17": 2, "18": 4}, movement_type="A") + hourly(
        {"17": 4, "18": 2}, movement_type="B"
    )

    items = derived(rows, series_by={"field": "movement_type"})

    by_key = {(i["label"], i["series"]): i for i in items}
    assert by_key[("18:00", "A")]["change_pct"] == 100.0
    assert by_key[("18:00", "A")]["trend"] == "up"
    assert by_key[("18:00", "B")]["change_pct"] == -50.0
    assert by_key[("18:00", "B")]["trend"] == "down"
    assert "change_pct" not in by_key[("17:00", "A")]


def test_flat_esit_deger():
    items = derived(hourly({"17": 3, "18": 3}))

    assert items[1] == {
        "label": "18:00",
        "value": 3,
        "change_pct": 0.0,
        "trend": "flat",
    }


def test_derive_yoksa_change_pct_ve_trend_yok():
    items = q(hourly({"17": 4, "18": 5}), group_by=HOUR)["items"]

    assert len(items) == 2
    assert all("change_pct" not in i and "trend" not in i for i in items)


# --- İkinci boyut ---------------------------------------------------------------


def test_series_by_duz_satirlar_grup_sirasiyla():
    rows = airlines({"TK": 3}, movement_type="ARRIVAL")
    rows += airlines({"TK": 1, "AJ": 2}, movement_type="DEPARTURE")

    result = q(
        rows,
        series_by={"field": "movement_type"},
        group_by={"field": "airline"},
    )

    assert result["items"] == [
        {"label": "TK", "series": "ARRIVAL", "value": 3},
        {"label": "TK", "series": "DEPARTURE", "value": 1},
        {"label": "AJ", "series": "DEPARTURE", "value": 2},
    ]
    assert result["series_truncated"] == 0


def test_dokuzuncu_seri_series_truncated():
    rows = []
    for number in range(1, 10):
        rows += airlines({f"A{number}": number}, movement_type="X")

    result = q(
        rows,
        group_by={"field": "movement_type"},
        series_by={"field": "airline"},
    )

    series = [item["series"] for item in result["items"]]
    assert len(series) == 8
    assert series == [f"A{n}" for n in range(9, 1, -1)]
    assert result["series_truncated"] == 1


def test_series_by_yoksa_series_anahtari_ve_series_truncated_yok():
    result = q(airlines({"TK": 1}))

    assert len(result["items"]) == 1
    assert "series" not in result["items"][0]
    assert "series_truncated" not in result


def test_unclassified_group_ya_da_series_alani_eksik_bir_kez_sayilir():
    rows = [
        {"airline": "TK", "movement_type": "ARRIVAL"},
        {"movement_type": "ARRIVAL"},
        {"airline": "TK"},
        {},
    ]

    result = q(
        rows,
        group_by={"field": "airline"},
        series_by={"field": "movement_type"},
    )

    assert result["unclassified"] == 3
    assert result["flights"] == 4
    assert counts(result) == [("TK", 1)]


# --- check_query ----------------------------------------------------------------

VALID = {
    "chart_type": "bar_horizontal",
    "group_by": {"field": "airline"},
    "measure": {"agg": "count"},
    "filters": [],
    "sort": "value_desc",
    "limit": 10,
    "plot": "value",
}
SERIES = {"field": "movement_type"}


def filt(field, op, value):
    return {"filters": [{"field": field, "op": op, "value": value}]}


INVALID = {
    "line_kategorik": {"chart_type": "line"},
    "line_bucketsiz_zaman": {
        "chart_type": "line",
        "group_by": {"field": "scheduled_time"},
    },
    "stacked_serisiz": {"chart_type": "stacked_bar"},
    "grouped_serisiz": {"chart_type": "grouped_bar"},
    "heatmap_serisiz": {"chart_type": "heatmap"},
    "pie_seriyle": {"chart_type": "pie", "series_by": SERIES},
    "doughnut_seriyle": {"chart_type": "doughnut", "series_by": SERIES},
    "seri_grupla_ayni": {
        "chart_type": "grouped_bar",
        "series_by": {"field": "airline"},
    },
    "bucket_kategorik": {"group_by": {"field": "airline", "bucket": "hour"}},
    "zaman_bucketsiz": {"group_by": {"field": "scheduled_time"}},
    "seri_sayisal": {
        "chart_type": "grouped_bar",
        "series_by": {"field": "delay_minutes"},
    },
    "count_field": {"measure": {"agg": "count", "field": "delay_minutes"}},
    "sum_fieldsiz": {"measure": {"agg": "sum"}},
    "sum_kategorik": {"measure": {"agg": "sum", "field": "airline"}},
    "in_bos": filt("airline", "in", []),
    "in_21_oge": filt("airline", "in", [f"A{n}" for n in range(21)]),
    "eq_dizi": filt("airline", "eq", ["TK"]),
    "gt_kategorik": filt("airline", "gt", "TK"),
    "sayisal_metin": filt("delay_minutes", "eq", "yirmi"),
    "sayisal_bool": filt("delay_minutes", "eq", True),
    "zaman_dun": filt("scheduled_time", "gt", "dün"),
    "zaman_saat_dilimsiz": filt("scheduled_time", "gt", "2026-10-20T17:00:00"),
    "zaman_24": filt("scheduled_time", "lt", "24:00"),
    "zaman_7_5": filt("scheduled_time", "lt", "7:5"),
    "zaman_sayi": filt("scheduled_time", "lt", 1700),
    "kategorik_sayi": filt("airline", "eq", 5),
    "bool_baska_alan": filt("airline", "eq", True),
    "derive_kategorik": {"derive": "pct_change_vs_previous"},
    "derive_bucketsiz": {
        "derive": "pct_change_vs_previous",
        "group_by": {"field": "scheduled_time"},
    },
    "plot_derivesiz": {"plot": "change_pct", "group_by": HOUR},
    "plot_pie": {
        "plot": "change_pct",
        "derive": "pct_change_vs_previous",
        "group_by": HOUR,
        "chart_type": "pie",
    },
    "plot_stacked": {
        "plot": "change_pct",
        "derive": "pct_change_vs_previous",
        "group_by": HOUR,
        "series_by": SERIES,
        "chart_type": "stacked_bar",
    },
    "plot_heatmap": {
        "plot": "change_pct",
        "derive": "pct_change_vs_previous",
        "group_by": HOUR,
        "series_by": SERIES,
        "chart_type": "heatmap",
    },
    "hucre_half_hour": {
        "chart_type": "grouped_bar",
        "group_by": {"field": "scheduled_time", "bucket": "half_hour"},
        "series_by": SERIES,
    },
    "hucre_limit_50": {
        "chart_type": "grouped_bar",
        "series_by": SERIES,
        "limit": 50,
    },
}


@pytest.mark.parametrize("name", INVALID)
def test_gecersiz_tarif_mesajla_reddedilir(name):
    message = load().check_query(VALID | INVALID[name])

    assert isinstance(message, str)
    assert message


VALID_VARIANTS = {
    "temel": {},
    "seri_ve_saat": {
        "chart_type": "stacked_bar",
        "group_by": HOUR,
        "series_by": SERIES,
        "limit": 10,
    },
    "cancelled_bool": filt("cancelled", "eq", True),
    "cancelled_metin": filt("cancelled", "eq", "true"),
    "tarihsiz_saat": filt("scheduled_time", "ge", "17:00"),
    "iso_saat": filt("scheduled_time", "gt", "2026-10-20T17:00:00+03:00"),
    "in_20_oge": filt("airline", "in", [f"A{n}" for n in range(20)]),
    "line_saat": {"chart_type": "line", "group_by": HOUR},
    "plot_degisim": {
        "chart_type": "bar_horizontal",
        "group_by": HOUR,
        "series_by": SERIES,
        "derive": "pct_change_vs_previous",
        "plot": "change_pct",
    },
    "gt_sayisal": filt("delay_minutes", "gt", 60),
    "limit_20_seriyle": {
        "chart_type": "grouped_bar",
        "series_by": SERIES,
        "limit": 20,
    },
}


@pytest.mark.parametrize("name", VALID_VARIANTS)
def test_gecerli_tarif_none_doner(name):
    assert load().check_query(VALID | VALID_VARIANTS[name]) is None
