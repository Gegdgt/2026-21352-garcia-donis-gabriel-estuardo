"""Thesis figures from validated SimZ1 trip summaries, without rereading events.

All statistics are supplied by the trip aggregation layer.  In particular, the
family views never average profile means, and a missing duration is never drawn
as zero.  The only loops here cover the six profiles and the 24 departure hours.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import textwrap

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


PROFILE_GROUPS = (
    ("Normal", "Carro (Normal)", "Carro"),
    ("Tortuga", "Carro Tortuga (Tortuga)", "Carro"),
    ("Liebre", "Carro liebre (Liebre)", "Carro"),
    ("Motociclista", "Moto", "Moto"),
    ("MotocicletaLenta", "Moto tortuga", "Moto"),
    ("MotocicletaRapida", "Moto Liebre", "Moto"),
)
COLORS = ("#23638D", "#CC8A21", "#407B48", "#6C4B97", "#B46238", "#218B8D")
FILENAMES = (
    "carros_por_hora.png",
    "motos_por_hora.png",
    "comparacion_familias_por_hora.png",
    "comparacion_global_perfiles.png",
    "completitud_por_hora.png",
)


def _count(row, key):
    return int(row.get(key, 0) or 0) if row else 0


def _mean(row):
    if not row or not _count(row, "n_complete"):
        return np.nan
    value = row.get("mean_minutes")
    return float(value) if value is not None and math.isfinite(float(value)) else np.nan


def _sample(row, minimum):
    if not _count(row, "n_total"):
        return "SD"
    complete = _count(row, "n_complete")
    if not complete:
        return "SC"
    return f"{complete:,}" + ("*" if complete < minimum else "")


def _identity(report):
    return f"SimZ1 · {report['run_id']} · iteración {report['iteration']}"


def _hour_definition(report):
    return ("Hora planificada de la cohorte principal; 00..23 respecto al inicio de jornada"
            if report.get('temporal_policy') else
            "Hora de PersonDepartureEvent: 00:00–00:59, …, 23:00–23:59")


def _metadata(report):
    return {
        "Title": "SimZ1: tiempos de viaje por perfil y hora de salida",
        "run_id": str(report["run_id"]),
        "iteration": str(report["iteration"]),
        "metric_definition": json.dumps(report["metric_definition"], ensure_ascii=False),
        "filters": json.dumps(report.get("filters", {}), ensure_ascii=False, sort_keys=True),
        "units": "minutos simulados",
        "hour_definition": _hour_definition(report),
        "min_sample": str(report.get("min_sample", 30)),
        "missing_values": "SD = sin datos; SC = sin viajes completos. No representan duración cero.",
        "duration_definition": "(PersonArrivalEvent.time - PersonDepartureEvent.time) / 60; llegada válida",
        "aggregation": "Medias recibidas del agregador de viajes individuales; no se promedian medias de perfiles.",
    }


def _save(fig, path, report):
    try:
        fig.savefig(path, dpi=180, bbox_inches="tight", metadata=_metadata(report))
    finally:
        plt.close(fig)
    return path


def _heading(fig, title, report):
    identity = textwrap.fill(_identity(report), width=110)
    quality = report.get('result_quality', {})
    rate = quality.get('completion_rate')
    detail = (f" | Finalización: {rate:.1%}" if rate is not None else "")
    caution = " | REQUIERE REVISIÓN" if quality.get('status') == 'review_required' else ""
    fig.suptitle(f"{title}\n{identity}\nMedias solo de viajes completados{detail}{caution}",
                 fontsize=13, fontweight="semibold", y=.98)


def _footer(fig, text, y=.025):
    fig.text(.5, y, text, ha="center", va="bottom", fontsize=9, color="#343B43")


def _style_axis(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#DDE2E7", linewidth=.7)
    ax.set_axisbelow(True)


def _hourly(report, destination, records, groups, key, filename, title, note):
    """Render supplied means and their actual sample sizes, including empty bins."""
    minimum = int(report.get("min_sample", 30))
    index = {(row[key], row["hour"]): row for row in records}
    hours = np.arange(24)
    fig, ax = plt.subplots(figsize=(17, 8))
    fig.subplots_adjust(left=.11, right=.98, top=.83, bottom=.35)
    _heading(fig, title, report)
    width = .8 / len(groups)
    all_means = []
    sample_rows = []
    for position, (identifier, label, color) in enumerate(groups):
        hourly = [index.get((identifier, hour)) for hour in range(24)]
        means = [_mean(row) for row in hourly]
        all_means.extend(value for value in means if math.isfinite(value))
        offset = (position - (len(groups) - 1) / 2) * width
        # NaN bars have no visible geometry: missing profiles are not zero trips.
        ax.bar(hours + offset, means, width=width, label=label, color=color, zorder=3)
        sample_rows.append([_sample(row, minimum) for row in hourly])
    ax.set(
        xlabel=_hour_definition(report),
        ylabel="Duración media de viajes completos (minutos simulados)",
        xlim=(-.6, 23.6),
        ylim=(0, max(all_means, default=1) * 1.16 or 1),
    )
    ax.set_xticks(hours, [f"{hour:02d}" for hour in hours])
    _style_axis(ax)
    ax.legend(loc="upper center", bbox_to_anchor=(.5, 1.10), ncol=len(groups), frameon=False)
    if not all_means:
        ax.text(.5, .52, "Sin viajes completos para esta selección", transform=ax.transAxes,
                ha="center", va="center", fontsize=14, color="#59616B")

    # An aligned sample strip makes every missing hour/profile explicit without
    # putting a fictitious zero on the duration axis or crowding bar annotations.
    table = ax.table(
        cellText=sample_rows,
        rowLabels=[label for _, label, _ in groups],
        colLabels=[f"{hour:02d}" for hour in hours],
        cellLoc="center", rowLoc="right", bbox=[0, -.55, 1, .34],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(7.7)
    for (row_number, column_number), cell in table.get_celld().items():
        cell.set_edgecolor("#E1E5E9")
        cell.set_linewidth(.5)
        if row_number == 0:
            cell.set_facecolor("#EEF2F6")
        elif column_number >= 0:
            value = sample_rows[row_number - 1][column_number]
            if value in ("SD", "SC"):
                cell.set_facecolor("#F0F0F0")
                cell.get_text().set_color("#676767")
            elif value.endswith("*"):
                cell.set_facecolor("#FFF3D7")
    _footer(fig, "Tabla: N de viajes completos por hora. SD = sin datos; SC = sin completos. "
            f"* Muestra pequeña: N < {minimum}.\n{note}", y=.025)
    return _save(fig, destination / filename, report)


def _global(report, destination):
    minimum = int(report.get("min_sample", 30))
    index = {row["profile"]: row for row in report["profiles"]}
    records = [index.get(profile) for profile, _, _ in PROFILE_GROUPS]
    means = [_mean(row) for row in records]
    maximum = max((value for value in means if math.isfinite(value)), default=1)
    fig, ax = plt.subplots(figsize=(14, 7.5))
    fig.subplots_adjust(left=.09, right=.98, top=.81, bottom=.27)
    _heading(fig, "Comparación global de los seis perfiles", report)
    ax.bar(np.arange(6), means, color=COLORS, width=.67, zorder=3)
    labels = []
    for x, ((_, label, _), row, mean) in enumerate(zip(PROFILE_GROUPS, records, means)):
        complete = _count(row, "n_complete")
        excluded = _count(row, "n_excluded")
        sample = _sample(row, minimum)
        small = " · muestra pequeña" if 0 < complete < minimum else ""
        labels.append(label.replace(" (", "\n(") + f"\nN = {complete:,}{'*' if small else ''}\nexcluidos = {excluded:,}")
        if math.isfinite(mean):
            annotation = f"{mean:.2f} min"
            ax.annotate(annotation, (x, mean), xytext=(0, 7), textcoords="offset points",
                        ha="center", va="bottom", fontsize=10, fontweight="semibold")
        else:
            ax.text(x, max(maximum, 1) * .06, "Sin datos" if sample == "SD" else "Sin completos",
                    ha="center", va="bottom", fontsize=10, color="#676767")
    ax.set_xticks(np.arange(6), labels, fontsize=10)
    ax.set(ylabel="Duración media de viajes completos (minutos simulados)",
           ylim=(0, max(maximum * 1.25, 1)), xlim=(-.6, 5.6))
    _style_axis(ax)
    separate = " Buses y transporte pesado, si existen, se contabilizan por separado."
    _footer(fig, "Jornada de salidas 00:00–23:59. Cada barra usa todos los viajes completos del perfil.\n"
            f"N = viajes completos; excluidos = abortados + censurados. * N < {minimum}."
            + ("\n" + separate.strip() if report.get("separate_categories") else ""), y=.025)
    return _save(fig, destination / "comparacion_global_perfiles.png", report)


def _completeness(report, destination):
    index = {(row["profile"], row["hour"]): row for row in report["profile_hour"]}
    fig, axes = plt.subplots(3, 1, figsize=(17, 12))
    fig.subplots_adjust(left=.16, right=.94, top=.88, bottom=.10, hspace=.53)
    _heading(fig, "Completitud por perfil y hora de salida", report)
    panels = (
        ("n_complete", "completion_rate", "Viajes completados", "Blues"),
        ("n_aborted", "aborted_rate", "Viajes abortados", "Oranges"),
        ("n_censored", "censored_rate", "Viajes censurados", "Purples"),
    )
    for ax, (count_field, rate_field, title, color_map) in zip(axes, panels):
        counts = np.full((6, 24), np.nan)
        for profile_number, (profile, _, _) in enumerate(PROFILE_GROUPS):
            for hour in range(24):
                row = index.get((profile, hour))
                if _count(row, "n_total"):
                    counts[profile_number, hour] = _count(row, count_field)
        cmap = plt.get_cmap(color_map).copy()
        cmap.set_bad("#EEEEEE")
        maximum = max(float(np.nanmax(counts)) if np.isfinite(counts).any() else 0, 1)
        heatmap = ax.imshow(counts, cmap=cmap, vmin=0, vmax=maximum, aspect="auto", interpolation="nearest")
        for profile_number, (profile, _, _) in enumerate(PROFILE_GROUPS):
            for hour in range(24):
                row = index.get((profile, hour))
                value = counts[profile_number, hour]
                if math.isnan(value):
                    label = "SD"
                else:
                    rate = row.get(rate_field)
                    label = f"{int(value):,}" + (f"\n{float(rate):.0%}" if rate is not None else "")
                ax.text(hour, profile_number, label, ha="center", va="center", fontsize=7.2,
                        color="white" if math.isfinite(value) and value > .6 * maximum else "#333333")
        ax.set_xticks(range(24), [f"{hour:02d}" for hour in range(24)], fontsize=9)
        ax.set_yticks(range(6), [label for _, label, _ in PROFILE_GROUPS], fontsize=10)
        ax.set_title(title, loc="left", fontsize=12, fontweight="semibold", pad=10)
        ax.set_xlabel(_hour_definition(report), fontsize=9)
        colorbar = fig.colorbar(heatmap, ax=ax, fraction=.018, pad=.014)
        colorbar.set_label("N de viajes", fontsize=9)
        colorbar.locator = matplotlib.ticker.MaxNLocator(integer=True)
        colorbar.update_ticks()
    _footer(fig, "Cada celda muestra N y tasa respecto de los viajes iniciados de ese perfil/hora. "
            "SD = sin datos; 0 es un conteo observado.\n"
            "Los abortos y las censuras no aportan duraciones a las medias. "
            "El CSV detalla los N excluidos y los tamaños de muestra.", y=.025)
    return _save(fig, destination / "completitud_por_hora.png", report)


def render_profile_plots(report, destination):
    """Write the five fixed SimZ1 deliverable figures and return their Paths.

    ``report`` contains already calculated ``profile_hour``, ``family_hour`` and
    ``profiles`` records. Existing target images cause an error before writing,
    so an invocation cannot silently replace earlier results.
    """
    destination = Path(destination)
    existing = [destination / filename for filename in FILENAMES if (destination / filename).exists()]
    if existing:
        raise FileExistsError("No se sobrescriben gráficas existentes: " + ", ".join(map(str, existing)))
    destination.mkdir(parents=True, exist_ok=True)
    files = []
    for family, filename, title in (
        ("Carro", "carros_por_hora.png", "Carros: duración media por hora de salida"),
        ("Moto", "motos_por_hora.png", "Motos: duración media por hora de salida"),
    ):
        groups = [(profile, label, COLORS[position])
                  for position, (profile, label, group_family) in enumerate(PROFILE_GROUPS)
                  if group_family == family]
        files.append(_hourly(report, destination, report["profile_hour"], groups, "profile", filename, title,
                             "Duración = llegada válida − salida; abortados y censurados se muestran en completitud."))
    files.append(_hourly(report, destination, report["family_hour"],
                         [("Carro", "Carro", COLORS[0]), ("Moto", "Moto", COLORS[3])], "family",
                         "comparacion_familias_por_hora.png", "Carro y Moto: comparación por hora de salida",
                         "Las medias de familia se calculan sobre viajes individuales, ponderadas por su N real."))
    files.append(_global(report, destination))
    files.append(_completeness(report, destination))
    return files
