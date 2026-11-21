"""Inventory the pre-existing thesis figures without touching native results.

The initial snapshot is immutable by default. Invoke before rendering additions.
Only small reports, figure sidecars and static transit metadata are inspected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RUNS = (
    ("Run1000", "a32f15487b1a49ac910ba799175658ca", "run-bg1-a32f15487b1a49ac910ba799175658ca"),
    ("Run10K", "e496c091b9ef46ee9ca381576135e299", "run-bg10-e496c091b9ef46ee9ca381576135e299"),
)

# variable, utility, limitation, objectives
CLASSES = {
    "carros_por_hora": ("Duración media de carros por perfil y hora de salida", "Identifica franjas y perfiles con viajes más largos", "Solo viajes completos; incluye espera desde departure; no fija una misma OD", ["general_parcial", "OE2", "OE3"]),
    "motos_por_hora": ("Duración media de motos por perfil y hora de salida", "Identifica franjas y heterogeneidad entre perfiles", "Solo viajes completos y OD heterogéneas; no demuestra un efecto causal del perfil", ["general_parcial", "OE2", "OE3"]),
    "comparacion_familias_por_hora": ("Duración media por familia y hora", "Compara carros y motos en la misma escala temporal", "Composición y OD diferentes; excluye censuras de duraciones", ["OE2", "OE3"]),
    "comparacion_global_perfiles": ("Duraciones agregadas y completitud por perfil", "Resume diferencias entre seis perfiles privados", "Un escenario por carga; los percentiles no son intervalos de confianza", ["OE2", "OE3"]),
    "completitud_por_hora": ("Completos, censurados y abortados por cohorte horaria", "Hace visible el sesgo de considerar únicamente llegadas", "No equivale a flujo de llegadas por hora real ni prueba causas de censura", ["OE3"]),
    "duration_distribution": ("Distribución de duraciones de viajes completos", "Muestra asimetría, dispersión y colas de tiempos", "Censuras excluidas; el reloj de inicio es departure, no necesariamente incorporación", ["general_parcial", "OE2", "OE3"]),
    "demanda_salida_insercion": ("Solicitudes, salidas e incorporaciones por hora", "Distingue demanda solicitada de entrada física", "Una salida no acredita incorporación; no mide flujo por sección vial", ["OE2", "OE3"]),
    "ocupacion_y_pendientes": ("Activos en red y pendientes de incorporación", "Distingue ocupación del sistema y espera exterior", "Snapshots horarios no son máximos continuos ni colas por intersección", ["OE2", "OE3"]),
    "llegadas_y_salidas": ("Llegadas y salidas en intervalos horarios", "Describe descarga temporal del sistema", "Conteos del sistema; no caudal de un enlace ni demanda simultánea", ["OE3"]),
    "cohortes_y_censura": ("Estado al corte de cohortes programadas", "Explica completitud respecto de la demanda programada", "No asignar censuras finales a abortos anteriores al horizonte", ["OE3"]),
    "operational_timeline": ("Activos, transiciones e intentos WAIT a través del tiempo", "Sustenta diagnóstico temporal y ausencia de intervenciones registradas", "WAIT cuenta intentos, no segundos ni vehículos; gauges muestreados no son máximos exactos", ["OE2_parcial", "OE3"]),
    "operational_timeline_ampliado": ("Mismas series de cronología operativa en formato vertical", "Facilita lectura de la cronología", "Redundante con operational_timeline; preferir una sola en tesis", ["OE3"]),
    "transporte_publico_flota_expediciones": ("Flota física y expediciones programadas/observadas", "Distingue vehículos de servicios diarios", "No mide pasajeros, ocupación ni demanda atendida", ["OE2", "OE3"]),
    "carga_clasificacion_ventanas": ("Clasificación de cumplimiento y retrasos de camiones", "Relaciona carga con ventanas de servicio", "Cumplimiento contractual sintético; no validación de normativa real", ["OE2", "OE3"]),
    "candidatos_ab": ("Frecuencias de pares de enlaces origen y destino", "Propone extremos reproducibles para estudio A–B", "Candidatos exploratorios; esta figura anterior no publica tiempos A–B ni trayectorias", ["general_parcial", "OE1_parcial"]),
    "demanda_programada_por_familia": ("Solicitudes programadas por familia y hora", "Describe composición y horarios de demanda", "Los buses son expediciones; N de escala es vehículos no públicos", ["OE2", "OE3"]),
    "demanda_privada_por_perfil": ("Demanda privada por perfil y hora", "Documenta la mezcla de demanda que alimenta la simulación", "Horarios y perfiles sintéticos, sin calibración observacional", ["OE2"]),
    "flujos_por_familia": ("Programaciones, incorporaciones y llegadas por familia", "Compara ejecución temporal de familias", "Son flujos del sistema, no flujos por enlace o corredor", ["OE2", "OE3"]),
    "cuatro_categorias_od": ("Completitud y duración por categoría OD", "Relaciona patrón espacial de viajes y duración", "Cuatro clases agregadas no son una pareja única A–B ni rutas idénticas", ["general_parcial", "OE2", "OE3"]),
    "camiones_programacion_ventanas_llegadas": ("Ventanas, salidas, incorporaciones y llegadas de camiones", "Comprueba tiempos observados frente a la programación", "La ventana puede tener cierre contractual posterior a 24h; no implica observación posterior al horizonte", ["OE2", "OE3"]),
    "buses_flota_y_expediciones_por_linea": ("Flota y expediciones por línea Transmetro/TuBus", "Localiza diferencias de ejecución de la oferta", "No modela pasajeros ni permite inferir utilización de asientos", ["OE2", "OE3"]),
    "buses_oferta_y_ejecucion_por_hora": ("Oferta horaria, inicios y llegadas reales, estado de cohortes", "Separa horario programado de ejecución real", "No iniciadas no indica hora exacta de cancelación; conservar denominadores", ["OE2", "OE3"]),
    "demand-day": ("Demanda, entradas, llegadas y estado a lo largo del día", "Resume el censo diario de la ejecución", "Conteos agregados; no mapa ni flujo de sección", ["OE2", "OE3"]),
    "profile_hour_distribution": ("Percentiles de duración por perfil y hora", "Muestra variabilidad temporal más allá del promedio", "Solo completos; pocas observaciones por celda pueden volver inestables los percentiles", ["OE2", "OE3"]),
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def rel(path: Path, root: Path):
    return path.resolve().relative_to(root.resolve()).as_posix()


def figure_record(path: Path, root: Path, label: str, run: Path):
    stem = path.stem
    variable, utility, limit, objectives = CLASSES[stem]
    sidecar = path.with_suffix(".json")
    metadata = read_json(sidecar) if sidecar.exists() else {}
    sources = metadata.get("sources", [])
    if not sources:
        if "graficas_perfiles" in path.parts:
            names = ["analysis/it.0/graficas_perfiles/resumen_perfiles.json", "analysis/it.0/trips.csv.gz"]
        elif "prompt13" in path.parts:
            names = ["analysis/prompt13/it.0/operational_report.json", "analysis/prompt13/it.0/individual_trips.csv.gz"]
        else:
            names = ["analysis/it.0/balanced-launch/report.json", "analysis/it.0/balanced-launch/hours-00-24.csv"]
        sources = [{"path": rel(run / name, root), "sha256": sha256(run / name)} for name in names]
    normalized_sources = []
    for source in sources:
        item = dict(source)
        p = Path(item["path"])
        if p.is_absolute():
            item["path"] = rel(p, root)
        normalized_sources.append(item)
    files = [{"path": rel(p, root), "format": p.suffix[1:], "bytes": p.stat().st_size, "sha256": sha256(p)}
             for ext in [".png", ".svg", ".csv", ".json"] if (p := path.with_suffix(ext)).exists()]
    return {"run": label, "figure": stem, "path": rel(path, root), "objective_ids": objectives,
            "variable": variable, "utility": utility, "limitation": limit, "sources": normalized_sources,
            "calculation": metadata.get("calculation", "Agregación previa publicada; consultar reporte fuente y script generador original."),
            "units": metadata.get("units"), "files": files, "legacy": "scenarios" in path.parts,
            "coverage_at_initial_audit": "partial" if any("parcial" in s for s in objectives) else "existing",
            "figure_metadata": metadata.get("metadata", {})}


def transit_comparison(run1: Path, run2: Path):
    # Static schedule: streaming line comparison; do not parse or rewrite native XML.
    from itertools import zip_longest
    differences = []
    name = "inputs/transit-weekday/transitSchedule.xml"
    with (run1 / name).open(encoding="utf-8") as a, (run2 / name).open(encoding="utf-8") as b:
        for number, (line1, line2) in enumerate(zip_longest(a, b), 1):
            if line1 != line2:
                differences.append({"line": number, "run1000": line1.strip() if line1 else None,
                                    "run10k": line2.strip() if line2 else None})
    allowed = ("simz1:monteCarloPersons", "simz1:weekdayPolicySha256")
    metadata_only = bool(differences) and all(any(key in (d["run1000"] or "") and key in (d["run10k"] or "") for key in allowed) for d in differences)
    return {"path": name, "byte_identical": not differences, "differences": differences,
            "same_schedule_except_demand_metadata": metadata_only or not differences,
            "interpretation": "Los cambios de atributos de demanda/procedencia se documentan; no se alteran ni normalizan hashes nativos."}


def build_inventory(root: Path):
    records, identities, manifests, native_dirs = [], [], [], []
    excluded = []
    for label, launch, dirname in RUNS:
        run = root / "scenarios/zona1/montecarlo" / dirname
        native_dirs.append(run)
        manifest_path = run / "run-manifest.json"
        manifest = read_json(manifest_path)
        manifests.append(manifest)
        state_path = root / "runtime/launches" / launch / "state.json"
        state = read_json(state_path)
        identities.append({"label": label, "launch_id": launch, "run_id": manifest["run_id"], "iteration": 0,
                           "run_directory": rel(run, root), "manifest_sha256": sha256(manifest_path),
                           "native_status": manifest["status"], "native_validation": manifest["validation"]["status"],
                           "counts": manifest["counts"], "time_horizon": manifest["time_horizon"],
                           "demand_seed": manifest["demand_seed"], "matsim_seed": manifest["matsim_seed"],
                           "launch_state": {key: state.get(key) for key in ["status", "phase", "outcome", "exit_code", "native_status", "native_validation", "screening", "finished_utc", "source_fingerprint"]},
                           "state_path": rel(state_path, root), "state_sha256": sha256(state_path)})
        folders = [run / "analysis"]
        if label == "Run1000":
            folders.append(root / "graficas_tesis_v2" / ("run1000-v8-" + launch))
        for folder in folders:
            for png in sorted(folder.rglob("*.png")):
                if png.stem not in CLASSES:
                    excluded.append({"path": rel(png, root), "reason": "Lámina QA o artefacto ajeno al catálogo científico previo; no se cuenta como figura."})
                    continue
                records.append(figure_record(png, root, label, run))
    m1, m2 = manifests
    checks = {key: {"equal": m1.get(key) == m2.get(key)} for key in ["time_horizon", "demand_seed", "matsim_seed", "scenario_version", "scenario_base_version", "signal_offsets", "signal_variant", "temporal_demand", "admission_execution", "origin_policy", "destination_policy", "freight_completion_policy"]}
    input_comparison = [{"input": key, "run1000_sha256": value["sha256"], "run10k_sha256": m2["inputs"].get(key, {}).get("sha256"), "equal": value["sha256"] == m2["inputs"].get(key, {}).get("sha256")} for key, value in m1["inputs"].items()]
    recovery_path = root / "runtime/recoveries/57c61494b1804a3cbaff53f7afdf797a/recovery-receipt.json"
    receipt = read_json(recovery_path)
    recovery = {key: receipt.get(key) for key in ["recovery_id", "original_launch_id", "run_id", "status", "exit_code", "native_status", "native_validation", "acceptance", "screening", "finished_utc"]}
    recovery.update(path=rel(recovery_path, root), sha256=sha256(recovery_path))
    return {"schema": "simz1-thesis-initial-inventory-v2", "created_utc": datetime.now(timezone.utc).isoformat(),
            "snapshot_policy": "Preservar primer inventario; regenerar figuras no sustituye este registro inicial.",
            "identities": identities, "figures": records, "excluded_non_scientific": excluded,
            "counts": dict(Counter(f'{r["run"]}: {"analysis" if r["legacy"] else "tesis"}' for r in records)),
            "run10k_recovery": recovery,
            "state_discrepancy": "Run10K: gateway histórico running/simulation_and_analysis con finished_utc; manifiesto y recibo de recuperación acreditan completed/valid y screening_pass. No se modifica evidencia histórica ni se promueve otra escala.",
            "comparability": {"configuration_checks": checks, "input_hash_comparison": input_comparison,
                              "transit_schedule": transit_comparison(*native_dirs),
                              "limitations": ["Una realización por carga con semilla común; sin replicaciones ni intervalo de confianza causal.", "La carga escala vehículos no públicos; 269 buses físicos y 13261 expediciones programadas se mantienen.", "Comparar duración incluye diferencias de OD/cohortes y censura; no atribuir todo cambio de promedio exclusivamente a congestión.", "Ciclos, composición proporcional y condiciones externas no varían independientemente: su influencia causal no se identifica con estas dos corridas."]},
            "initial_gaps": ["Colección equivalente de Run10K en PNG/SVG y respaldos", "Comparaciones 1K/10K con iguales definiciones", "Mapas de la red realmente simulada y atributos", "Flujo por enlaces/corredores", "Acumulación por enlace como proxy declarado", "Tiempos A–B para extremos explícitos con observaciones y censura", "Selección curada e índice unificado"],
            "coverage": {"OE1": "Pendiente: figuras existentes solo aportan pares candidatos; faltan mapas de red/atributos.", "OE2": "Parcial: demanda, perfiles, horarios, carga y operación pública; falta comparativa de carga. No identifica efectos de semáforos/clima no variados.", "OE3": "Duración y censo temporal disponibles; flujo espacial/acumulación aún no publicados en colección inicial.", "general": "Duraciones individuales y candidatos OD existentes; falta formalizar y medir pares A–B observables."}}


def ensure_inventory(root: Path, output: Path | None = None):
    output = output or root / "graficas_tesis_v2/auditoria-existente.json"
    if output.exists():
        return read_json(output)
    result = build_inventory(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive create preserves an inventory produced by another coordinated entry point.
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = ensure_inventory(args.root.resolve())
    print(json.dumps({"figures": len(result["figures"]), "counts": result["counts"]}, ensure_ascii=True))
