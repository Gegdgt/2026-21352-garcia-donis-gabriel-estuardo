"""Presentation of verified SimZ1 profile products; no events, replay or simulation.

The statistics in the existing profile report remain authoritative. The compact
trip table is read incrementally only to recover histogram counts which older
report versions did not publish. Its selection must reproduce every profile's
counts and duration statistics before a distribution can be published.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing
import math
from pathlib import Path
import sqlite3
import tempfile

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.ticker import MaxNLocator, PercentFormatter
import numpy as np

from simz1_trip_table import rows as trip_rows


PROFILE_ORDER = ("Tortuga", "Normal", "Liebre", "MotocicletaLenta", "Motociclista", "MotocicletaRapida")
PROFILE_COLORS = {
    "Tortuga": "#CC8A21", "Normal": "#23638D", "Liebre": "#407B48",
    "MotocicletaLenta": "#B46238", "Motociclista": "#6C4B97", "MotocicletaRapida": "#218B8D",
}
FAMILY_COLORS = {"Carro": "#23638D", "Moto": "#6C4B97"}
PROFILE_LABELS = {
    "Tortuga": "Carro · Tortuga", "Normal": "Carro · Normal", "Liebre": "Carro · Liebre",
    "MotocicletaLenta": "Moto · Tortuga", "Motociclista": "Moto · Normal", "MotocicletaRapida": "Moto · Liebre",
}
METRICS = (("mean_minutes", "Media", "-", "o"),
           ("median_minutes", "Mediana", "--", "s"),
           ("p95_minutes", "P95", ":", "^"))
COUNT_KEYS = ("n_total", "n_complete", "n_aborted", "n_censored", "n_excluded")


def _number(value):
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Valor no finito en el resumen de perfiles")
    return number


def validate_profile_report(report, identity):
    """Reject mixed identities, invented durations and inconsistent denominators."""
    if report.get("run_id") != identity["run_id"] or report.get("iteration") != identity["iteration"]:
        raise ValueError("Resumen de perfiles de otra corrida o iteración")
    for section, key in (("profiles", "profile"), ("families", "family"),
                         ("profile_hour", "profile"), ("family_hour", "family")):
        seen = set()
        for row in report.get(section, []):
            if row.get("run_id") != identity["run_id"] or row.get("iteration") != identity["iteration"]:
                raise ValueError("Fila de perfiles de otra corrida o iteración")
            item = (row.get(key), row.get("hour"))
            if item in seen:
                raise ValueError("Fila de perfiles repetida")
            seen.add(item)
            if "hour" in section and (type(row.get("hour")) is not int or not 0 <= row["hour"] < 24):
                raise ValueError("Hora de perfiles inválida")
            for field in COUNT_KEYS:
                if type(row.get(field)) is not int or row[field] < 0:
                    raise ValueError("Conteo de perfiles ausente o inválido")
            if row["n_total"] != row["n_complete"] + row["n_aborted"] + row["n_censored"]:
                raise ValueError("Denominador de perfiles inconsistente")
            if row["n_excluded"] != row["n_aborted"] + row["n_censored"]:
                raise ValueError("Exclusiones de perfiles inconsistentes")
            for field, _, _, _ in METRICS:
                value = _number(row.get(field))
                if row["n_complete"] == 0 and value is not None:
                    raise ValueError("Duración sin viajes completos")
                if value is not None and value < 0:
                    raise ValueError("Duración negativa")
            for field, numerator in (("completion_rate", "n_complete"), ("aborted_rate", "n_aborted"),
                                     ("censored_rate", "n_censored")):
                value = _number(row.get(field))
                expected = row[numerator] / row["n_total"] if row["n_total"] else None
                if (value is None) != (expected is None) or (value is not None and not math.isclose(value, expected, abs_tol=1e-10)):
                    raise ValueError("Tasa y denominador de perfiles incompatibles")


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#DEE4EA", linewidth=.6)
    ax.set_axisbelow(True)


def _subtitle(identity):
    count = identity.get("N_configured", identity.get("n_configured"))
    number = f"{count:,}" if isinstance(count, int) else "no disponible"
    prefix = " · Prefijo diagnóstico" if identity.get("publication_status") == "diagnostic_prefix" else ""
    return f"N configurado = {number} · Iteración {identity['iteration']}{prefix}"


def _heading(fig, title, identity, *, y=.99):
    fig.suptitle(title, fontsize=16, fontweight="semibold", y=y, color="#203449")
    fig.text(.5, y - .40 / fig.get_figheight(), _subtitle(identity), ha="center", va="top",
             fontsize=10, color="#4C5C68")


def _hour_label(report):
    planned = "planned" in str(report.get("filters", {}).get("cohort_hour_basis", ""))
    return "Hora de salida planificada de la cohorte" if planned else "Hora de salida observada"


def _base_metadata(report, **extra):
    return dict(objective="Describir tiempos y completitud por perfil y franja horaria",
                units="minutos simulados; viajes (etapas departure–arrival)",
                filters=report.get("filters", {}),
                denominator="n_total: etapas iniciadas de la misma cohorte, perfil y hora; n_complete para duraciones",
                calculation=report.get("metric_definition"),
                source_schema_version=report.get("schema_version"),
                weighting=report.get("weighting"),
                missing_values="null: sin duración observada; horas ausentes no se imputan como cero",
                **extra)


def _hour_rows(report, section, key, groups):
    lookup = {(r[key], r["hour"]): r for r in report.get(section, [])}
    output = []
    for group in groups:
        for hour in range(24):
            source = lookup.get((group, hour))
            if source is None:
                output.append(dict(group=group, label=PROFILE_LABELS.get(group, group), hour=hour,
                                   source_record_available=False,
                                   **{field: None for field in COUNT_KEYS},
                                   **{field: None for field, *_ in METRICS}))
            else:
                row = dict(source)
                row.update(group=group, label=PROFILE_LABELS.get(group, group), source_record_available=True)
                output.append(row)
    return output


def _hourly(report, identity, publisher, groups, section, key, stem, title):
    records = _hour_rows(report, section, key, groups)
    index = {(r["group"], r["hour"]): r for r in records}
    fig, axes = plt.subplots(len(groups) + 1, 1, figsize=(12.4, 3.1 * len(groups) + 3.2), sharex=True,
                             gridspec_kw={"height_ratios": [1] * len(groups) + [.75]})
    fig.subplots_adjust(left=.09, right=.97, top=1 - 1.35 / fig.get_figheight(), bottom=.13, hspace=.29)
    _heading(fig, title, identity)
    metric_handles = [Line2D([], [], color="#394C60", linestyle=style, marker=marker, markersize=4, label=label)
                      for _, label, style, marker in METRICS]
    fig.legend(handles=metric_handles, loc="upper center", bbox_to_anchor=(.5, 1 - .70 / fig.get_figheight()), ncol=3, frameon=False)
    values = [r[field] for r in records for field, *_ in METRICS if r.get(field) is not None]
    upper = max(values, default=1) * 1.13 or 1
    hours = np.arange(24)
    for ax, group in zip(axes[:-1], groups):
        rows = [index[(group, hour)] for hour in range(24)]
        color = PROFILE_COLORS.get(group, FAMILY_COLORS.get(group, "#23638D"))
        complete = sum(r["n_complete"] or 0 for r in rows)
        excluded = sum(r["n_excluded"] or 0 for r in rows)
        available = any(r["source_record_available"] for r in rows)
        for field, label, style, marker in METRICS:
            ax.plot(hours, [np.nan if r.get(field) is None else r[field] for r in rows],
                    linestyle=style, marker=marker, color=color, markersize=3.3, linewidth=1.35)
        sample_text = (f"completos: {complete:,}    ·    incompletos: {excluded:,}"
                       if available else "sin registro publicado")
        ax.set_title(f"{PROFILE_LABELS.get(group, group)}    ·    {sample_text}",
                     loc="left", fontsize=10.5, color=color, fontweight="semibold")
        ax.set(ylabel="Duración (min)", ylim=(0, upper))
        if not complete:
            ax.text(.5, .5, "Sin viajes completos" if available else "Sin registro publicado",
                    transform=ax.transAxes, ha="center", color="#67727D")
        _style(ax)
    sample = axes[-1]
    for group in groups:
        group_rows = [index[(group, hour)] for hour in range(24)]
        color = PROFILE_COLORS.get(group, FAMILY_COLORS.get(group, "#23638D"))
        sample.plot(hours, [np.nan if r["n_complete"] is None else r["n_complete"] for r in group_rows],
                    marker="o", markersize=3, linewidth=1.15, color=color,
                    label=PROFILE_LABELS.get(group, group))
        sample.plot(hours, [np.nan if r["n_excluded"] is None else r["n_excluded"] for r in group_rows],
                    linestyle=":", linewidth=1.4, color=color)
    sample.set(ylabel="Viajes", xlabel=_hour_label(report), xlim=(-.35, 23.35), ylim=(0, None))
    sample.set_title("Muestra por hora: línea continua = completos; punteada = abortados + censurados", loc="left", fontsize=9.5)
    sample.set_xticks(hours, [f"{hour:02d}" for hour in hours], fontsize=9)
    sample.yaxis.set_major_locator(MaxNLocator(integer=True))
    sample.legend(loc="upper right", ncol=len(groups), fontsize=8, frameon=False)
    _style(sample)
    fig.text(.5, .025, "Duración = llegada válida − salida. Huecos: sin duración observada.\n"
             "Conteos exactos y exclusiones por franja en CSV; los viajes incompletos no aportan duración.",
             ha="center", fontsize=9, color="#4C5C68")
    metadata = _base_metadata(report, n_observations=sum(r["n_complete"] or 0 for r in records),
                              n_excluded=sum(r["n_excluded"] or 0 for r in records),
                              source_rows_available=sum(r["source_record_available"] for r in records),
                              source_rows_expected=len(records),
                              family_aggregation="Estadísticas originales por viaje individual; no se promedian medias de perfiles")
    publisher.save(fig, stem, records, metadata)


def _global(report, identity, publisher):
    lookup = {row["profile"]: row for row in report["profiles"]}
    records = []
    fig, ax = plt.subplots(figsize=(12.4, 7.3))
    fig.subplots_adjust(left=.25, right=.96, top=.80, bottom=.15)
    _heading(fig, "Duración de viaje de los seis perfiles", identity)
    maximum = 1
    labels = []
    for position, profile in enumerate(PROFILE_ORDER):
        row = lookup.get(profile)
        if row is None:
            labels.append(PROFILE_LABELS[profile] + "\nSin registro publicado")
            records.append(dict(profile=profile, source_record_available=False))
            continue
        records.append(dict(row, source_record_available=True))
        labels.append(f"{PROFILE_LABELS[profile]}\ncompletos = {row['n_complete']:,}; incompletos = {row['n_excluded']:,}")
        values = [row.get(field) for field, *_ in METRICS]
        valid = [value for value in values if value is not None]
        if valid:
            maximum = max(maximum, *valid)
            ax.plot([min(valid), max(valid)], [position, position], color=PROFILE_COLORS[profile], alpha=.3, linewidth=6)
            for (field, label, _, marker), shift in zip(METRICS, (-.12, 0, .12)):
                if row.get(field) is not None:
                    ax.scatter(row[field], position + shift, s=45, marker=marker, color=PROFILE_COLORS[profile], zorder=3)
        else:
            ax.text(.02, position, "Sin viajes completos", transform=ax.get_yaxis_transform(), va="center", color="#66717C")
    ax.set_yticks(range(6), labels, fontsize=10)
    ax.invert_yaxis()
    ax.set(xlabel="Duración de etapas completadas (minutos)", xlim=(0, maximum * 1.12))
    handles = [Line2D([], [], color="#394C60", marker=marker, linestyle="", label=label, markersize=7)
               for _, label, _, marker in METRICS]
    ax.legend(handles=handles, ncol=3, frameon=False, loc="lower center", bbox_to_anchor=(.5, 1.03))
    _style(ax)
    ax.grid(axis="x", color="#DEE4EA", linewidth=.6)
    fig.text(.5, .035, "Estadísticas de viajes completados; los perfiles identifican tipos configurados.\n"
             "La figura no mide velocidades máximas ni sustituye duraciones faltantes.", ha="center", fontsize=9, color="#4C5C68")
    publisher.save(fig, "comparacion_global_perfiles", records,
                   _base_metadata(report, n_observations=sum(r.get("n_complete", 0) for r in records),
                                  n_excluded=sum(r.get("n_excluded", 0) for r in records)))


def _completeness(report, identity, publisher):
    records = _hour_rows(report, "profile_hour", "profile", PROFILE_ORDER)
    index = {(r["group"], r["hour"]): r for r in records}
    fig, axes = plt.subplots(3, 2, figsize=(14.3, 10.8))
    fig.subplots_adjust(left=.14, right=.96, top=.87, bottom=.12, hspace=.52, wspace=.45)
    _heading(fig, "Completitud por perfil y hora", identity)
    states = (("n_complete", "Viajes completos", "Blues"), ("n_aborted", "Viajes abortados", "Oranges"),
              ("n_censored", "Viajes censurados", "Purples"))
    for axes_row, (field, label, cmap_name) in zip(axes, states):
        counts = np.full((6, 24), np.nan)
        rates = np.full((6, 24), np.nan)
        for i, profile in enumerate(PROFILE_ORDER):
            for hour in range(24):
                row = index[(profile, hour)]
                if row.get("n_total"):
                    counts[i, hour] = row[field]
                    rates[i, hour] = 100 * row[field] / row["n_total"]
                # No initiated trip: denominator absent, not zero percent.
        cmap = plt.get_cmap(cmap_name).copy()
        cmap.set_bad("#E9ECEF")
        for column, (values, suffix, unit, vmax) in enumerate((
            (counts, "conteos", "Viajes", max(1, float(np.nanmax(counts)) if np.isfinite(counts).any() else 1)),
            (rates, "porcentaje", "% de etapas iniciadas", 100),
        )):
            ax = axes_row[column]
            mesh = ax.imshow(np.ma.masked_invalid(values), aspect="auto", cmap=cmap, vmin=0, vmax=vmax, interpolation="nearest")
            ax.set_title(f"{label} · {suffix}", fontsize=10, loc="left", fontweight="semibold")
            ax.set_xticks(range(0, 24, 2), [f"{h:02d}" for h in range(0, 24, 2)], fontsize=9)
            ax.set_yticks(range(6), [PROFILE_LABELS[p] for p in PROFILE_ORDER], fontsize=9)
            ax.set_xlabel(_hour_label(report), fontsize=9)
            colorbar = fig.colorbar(mesh, ax=ax, fraction=.035, pad=.025)
            colorbar.set_label(unit, fontsize=8.5)
            if column == 0:
                colorbar.locator = MaxNLocator(integer=True)
                colorbar.update_ticks()
    fig.text(.5, .035, "Denominador de cada porcentaje: etapas iniciadas del mismo perfil y hora.\n"
             "Gris: sin etapas iniciadas o sin registro publicado. Conteos y tasas exactos: CSV.\n"
             "Las salidas programadas que nunca comenzaron no forman parte de este denominador.", ha="center", fontsize=9, color="#4C5C68")
    publisher.save(fig, "completitud_por_hora", records,
                   _base_metadata(report, n_observations=sum(r["n_total"] or 0 for r in records),
                                  n_excluded=sum(r["n_excluded"] or 0 for r in records)))


def _quantile(connection, profile, count, probability):
    if not count:
        return None
    rank = (count - 1) * probability
    lower, upper = math.floor(rank), math.ceil(rank)
    where, args = ("WHERE profile = ?", [profile]) if profile is not None else ("", [])
    query = f"SELECT minutes FROM durations {where} ORDER BY minutes LIMIT 1 OFFSET ?"
    a = connection.execute(query, args + [lower]).fetchone()[0]
    b = connection.execute(query, args + [upper]).fetchone()[0]
    return a + (b - a) * (rank - lower)


def distribution_data(bundle):
    """Bounded memory, exact quantiles and histogram counts from a compact CSV.

    Returns bounded histogram bins and exact summary values. The cumulative
    series is evaluated at histogram edges; it is explicitly labelled as such.
    """
    report = bundle["profile_report"]
    identity = bundle["identity"]
    path = bundle.get("trips_path")
    if path is None or not Path(path).is_file():
        raise FileNotFoundError("Distribución pendiente: falta la tabla compacta de viajes verificada")
    basis = report.get("filters", {}).get("cohort_hour_basis")
    study = report.get("temporal_policy", {}).get("windows", {}).get("study")
    metadata = bundle.get("metadata")
    if study:
        if metadata is None:
            raise FileNotFoundError("Distribución pendiente: se necesita metadata verificada de la cohorte planificada")
    elif basis != "observed PersonDepartureEvent absolute hour":
        raise FileNotFoundError("Distribución pendiente: definición temporal publicada no reconocida")
    selected_counts = {profile: Counter() for profile in PROFILE_ORDER}
    n_read = 0
    with tempfile.TemporaryDirectory(prefix="simz1-thesis-hist-") as folder:
        with closing(sqlite3.connect(str(Path(folder) / "distribution.sqlite"))) as connection:
            connection.execute("PRAGMA cache_size = -4096")
            connection.execute("PRAGMA temp_store = FILE")
            connection.execute("CREATE TABLE durations (profile TEXT NOT NULL, minutes REAL NOT NULL)")
            batch = []
            for row in trip_rows(path):
                n_read += 1
                if row["run_id"] != identity["run_id"] or row["iteration"] != identity["iteration"]:
                    raise ValueError("Tabla de distribución de otra corrida o iteración")
                profile = row["profile"]
                if study:
                    person = metadata.get(row["person_id"], {})
                    if person.get("population_cohort") != "main":
                        continue
                    planned = person.get("planned_departure_seconds")
                    if planned is None or not study["start_seconds"] <= planned < study["end_seconds"]:
                        raise ValueError("Cohorte planificada incoherente")
                    profile = person.get("effective_vehicle_type") or person.get("profile")
                    if not person.get("monte_carlo_eligible"):
                        continue
                elif not 0 <= row["departure"] < 86400:
                    continue
                if profile not in selected_counts:
                    continue
                selected_counts[profile][row["status"]] += 1
                if row["status"] == "completed":
                    batch.append((profile, row["duration_seconds"] / 60))
                    if len(batch) >= 1000:
                        connection.executemany("INSERT INTO durations VALUES (?, ?)", batch)
                        batch.clear()
            connection.executemany("INSERT INTO durations VALUES (?, ?)", batch)
            connection.execute("CREATE INDEX profile_durations ON durations (profile, minutes)")
            connection.execute("CREATE INDEX all_durations ON durations (minutes)")
            for expected in report["profiles"]:
                profile = expected["profile"]
                observed = selected_counts[profile]
                for field, state in (("n_complete", "completed"), ("n_aborted", "aborted"), ("n_censored", "censored")):
                    if expected[field] != observed[state]:
                        raise ValueError(f"La cohorte de distribución no reproduce {profile}/{field}")
                count, mean = connection.execute("SELECT COUNT(*), AVG(minutes) FROM durations WHERE profile = ?", (profile,)).fetchone()
                actual = {"mean_minutes": mean, "median_minutes": _quantile(connection, profile, count, .5),
                          "p95_minutes": _quantile(connection, profile, count, .95)}
                for field, value in actual.items():
                    reference = expected.get(field)
                    if (value is None) != (reference is None) or value is not None and not math.isclose(value, reference, rel_tol=1e-8, abs_tol=1e-8):
                        raise ValueError(f"Distribución incompatible con resumen: {profile}/{field}")
            count, mean, maximum = connection.execute("SELECT COUNT(*), AVG(minutes), MAX(minutes) FROM durations").fetchone()
            stats = dict(n_complete=count, mean_minutes=mean, median_minutes=_quantile(connection, None, count, .5),
                         p95_minutes=_quantile(connection, None, count, .95), n_rows_read=n_read,
                         n_excluded=sum(sum(states.values()) - states["completed"] for states in selected_counts.values()))
            expected = report["distribution"]
            if count != expected["n_complete"]:
                raise ValueError("Muestra de distribución incompatible con resumen")
            for field in ("mean_minutes", "median_minutes", "p95_minutes"):
                value, reference = stats[field], expected.get(field)
                if (value is None) != (reference is None) or value is not None and not math.isclose(value, reference, rel_tol=1e-8, abs_tol=1e-8):
                    raise ValueError("Estadística global de distribución incompatible")
            if not count:
                return [], stats
            bins = min(60, max(1, math.ceil(math.sqrt(count))))
            high = maximum if maximum else 1.0
            width = high / bins
            counts = dict(connection.execute("SELECT MIN(?, CAST(minutes / ? AS INTEGER)), COUNT(*) FROM durations GROUP BY 1", (bins - 1, width)))
            output, cumulative = [], 0
            for index in range(bins):
                number = counts.get(index, 0)
                cumulative += number
                output.append(dict(bin_index=index, left_minutes=index * width, right_minutes=(index + 1) * width,
                                   count=number, cumulative_count=cumulative, cumulative_fraction=cumulative / count,
                                   right_edge_inclusive=index == bins - 1))
            return output, stats


def _distribution(bundle, publisher):
    report, identity = bundle["profile_report"], bundle["identity"]
    records, stats = distribution_data(bundle)
    fig, axes = plt.subplots(1, 2, figsize=(12.4, 5.9))
    fig.subplots_adjust(left=.07, right=.97, bottom=.20, top=.75, wspace=.26)
    _heading(fig, "Distribución de la duración de viaje", identity)
    fig.text(.5, .875, f"Seis perfiles · Completos = {stats['n_complete']:,} · Incompletos excluidos = {stats['n_excluded']:,}",
             ha="center", fontsize=10, color="#4C5C68")
    if records:
        axes[0].bar([r["left_minutes"] for r in records], [r["count"] for r in records],
                    width=[r["right_minutes"] - r["left_minutes"] for r in records], align="edge",
                    color="#23638D", edgecolor="white", linewidth=.5)
        axes[1].step([0] + [r["right_minutes"] for r in records], [0] + [r["cumulative_fraction"] for r in records],
                     where="post", color="#23638D", linewidth=1.7)
        for field, label, color in (("median_minutes", "Mediana", "#CC8A21"), ("p95_minutes", "P95", "#6C4B97")):
            for ax in axes:
                ax.axvline(stats[field], linestyle="--", linewidth=1.3, color=color,
                           label=f"{label}: {stats[field]:.2f} min")
        axes[0].legend(frameon=False, fontsize=9)
    else:
        for ax in axes:
            ax.text(.5, .5, "Sin viajes completos", transform=ax.transAxes, ha="center", color="#66717C")
    for ax in axes:
        ax.set(xlabel="Duración de etapas completadas (minutos)", xlim=(0, None), ylim=(0, None))
        _style(ax)
    axes[0].set(ylabel="Viajes completos", title="Histograma")
    axes[0].yaxis.set_major_locator(MaxNLocator(integer=True))
    axes[1].set(ylabel="Fracción acumulada", title="Acumulada en límites de clases", ylim=(0, 1.03))
    axes[1].yaxis.set_major_formatter(PercentFormatter(1))
    fig.text(.5, .04, "Duración = llegada válida − salida. Percentiles exactos por viaje; clases publicadas en CSV.\n"
             "La curva acumulada se evalúa en los límites del histograma; incluye toda la muestra completa.",
             ha="center", fontsize=9, color="#4C5C68")
    publisher.save(fig, "duration_distribution", records,
                   _base_metadata(report, n_observations=stats["n_complete"], n_excluded=stats["n_excluded"],
                                  exact_statistics=stats, quantiles="Interpolación lineal exacta; rango (n-1)*p",
                                  histogram_rule="Clases uniformes desde cero hasta el máximo; min(60,ceil(sqrt(n))) clases; último límite incluido",
                                  cumulative_rule="Suma de conteos hasta el límite derecho de cada clase / n_complete"))


def render_profiles(bundle, publisher):
    """Improve the six historical figure names through a provenance publisher."""
    report = bundle.get("profile_report")
    if not report:
        return {"figures": [], "pending": ["Perfiles: falta resumen_perfiles.json verificado"]}
    identity = bundle["identity"]
    validate_profile_report(report, identity)
    figures, pending = [], []
    for groups, section, key, stem, title in (
        (PROFILE_ORDER[:3], "profile_hour", "profile", "carros_por_hora", "Carros: duración por hora de salida"),
        (PROFILE_ORDER[3:], "profile_hour", "profile", "motos_por_hora", "Motos: duración por hora de salida"),
        (("Carro", "Moto"), "family_hour", "family", "comparacion_familias_por_hora", "Carros y motos: duración por hora de salida"),
    ):
        _hourly(report, identity, publisher, groups, section, key, stem, title)
        figures.append(stem)
    _global(report, identity, publisher)
    figures.append("comparacion_global_perfiles")
    _completeness(report, identity, publisher)
    figures.append("completitud_por_hora")
    try:
        _distribution(bundle, publisher)
        figures.append("duration_distribution")
    except FileNotFoundError as error:
        pending.append(str(error))
    return {"figures": figures, "pending": pending}
