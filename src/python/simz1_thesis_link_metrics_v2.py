"""Hourly flow and native link association from an existing pinned replay cache.

This reuses simz1_aggregate_replay's tested census/replay adapters. Native source
files are only read. Link association is a spatial accumulation proxy, never a
reconstruction of bodies, measured queues, speeds or signal waiting time.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
import csv
from datetime import datetime, timezone
import itertools
import json
import math
from pathlib import Path
import sqlite3

from simz1_aggregate_replay import AggregateReplay, build, digest
from simz1_thesis_inventory_v2 import RUNS

VERSION = "simz1-thesis-link-metrics-v2.1"
FIELDS = ["link_id", "hour", "entries", "traffic_entries", "vehicle_seconds", "mean_active", "peak_active", "coverage_seconds"]


def hourly_metrics(changes, horizon=86400.0, bin_seconds=3600.0):
    """Integrate piecewise constant association and exact native entry counts.

    changes is sorted (time, stock_delta, LinkEnter_delta, traffic_entry_delta).
    Simultaneous events are combined before stock/peak computation. Repeated
    observations cannot increase flow unless their cumulative entry changed.
    """
    if horizon <= 0 or bin_seconds <= 0:
        raise ValueError("Positive horizon/bin size required")
    bins = [{"hour": h, "entries": 0, "traffic_entries": 0,
             "vehicle_seconds": 0.0, "mean_active": 0.0, "peak_active": 0,
             "coverage_seconds": min(bin_seconds, horizon-h*bin_seconds)}
            for h in range(math.ceil(horizon/bin_seconds))]
    active, previous = 0, 0.0

    def integrate(start, end, stock):
        while start < end:
            index = min(int(start // bin_seconds), len(bins)-1)
            upper = min(end, (index+1)*bin_seconds)
            bins[index]["vehicle_seconds"] += stock * (upper-start)
            bins[index]["peak_active"] = max(bins[index]["peak_active"], stock)
            start = upper

    for time, same_time in itertools.groupby(changes, key=lambda row: row[0]):
        if not math.isfinite(time) or time < previous or time < 0 or time > horizon:
            raise ValueError("Invalid or unordered native association time")
        group = list(same_time)
        delta = sum(row[1] for row in group)
        entries = sum(row[2] for row in group)
        insertions = sum(row[3] for row in group)
        if entries < 0 or insertions < 0:
            raise ValueError("Cumulative entry counters decreased")
        integrate(previous, time, active)
        active += delta
        if active < 0:
            raise ValueError("Negative native association stock")
        # Final pre-cleanup stock is reported in metadata, not an extra hour.
        if time < horizon:
            index = int(time//bin_seconds)
            bins[index]["entries"] += entries
            bins[index]["traffic_entries"] += insertions
            bins[index]["peak_active"] = max(bins[index]["peak_active"], active)
        elif entries or insertions:
            raise ValueError("Entry exactly at excluded horizon requires separate accounting")
        previous = time
    integrate(previous, horizon, active)
    for row in bins:
        row["mean_active"] = row["vehicle_seconds"] / row["coverage_seconds"]
    return bins, active


def iter_link_changes(connection):
    """One ordered pass over aggregate series; at most one link kept in RAM."""
    query = "SELECT link,family,time,count,entries,link_enters FROM series ORDER BY link,family,time"
    current_link, previous_family, previous = None, None, (0, 0, 0)
    changes = defaultdict(lambda: [0, 0, 0])
    for link, family, time, count, entries, link_enters in connection.execute(query):
        if link != current_link:
            if current_link is not None:
                yield current_link, [(t, *values) for t, values in sorted(changes.items())]
            current_link, previous_family, previous = link, None, (0, 0, 0)
            changes = defaultdict(lambda: [0, 0, 0])
        if family != previous_family:
            previous, previous_family = (0, 0, 0), family
        count_delta, all_entry_delta, link_entry_delta = count-previous[0], entries-previous[1], link_enters-previous[2]
        traffic_entry_delta = all_entry_delta-link_entry_delta
        if min(all_entry_delta, link_entry_delta, traffic_entry_delta) < 0:
            raise ValueError("Invalid cumulative entry counter")
        values = changes[time]
        values[0] += count_delta
        values[1] += link_entry_delta
        values[2] += traffic_entry_delta
        previous = count, entries, link_enters
    if current_link is not None:
        yield current_link, [(t, *values) for t, values in sorted(changes.items())]


def write_csv(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def extract_metrics(aggregate_directory: Path, output: Path):
    manifest_path = aggregate_directory / "aggregate-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    aggregate = AggregateReplay(aggregate_directory, manifest["identity"])
    horizon = float(manifest["replay_window"]["end_seconds"])
    if manifest["replay_window"]["start_seconds"] != 0 or horizon != 86400:
        raise ValueError("This thesis collection requires the exact 24-hour window")
    output.mkdir(parents=True, exist_ok=True)
    hourly_path, summary_path = output / "link_hourly.csv", output / "link_summary.csv"
    summaries, global_association = [], defaultdict(int)
    native_active = defaultdict(int)
    with closing(aggregate.connection()) as connection, hourly_path.open("w", newline="", encoding="utf-8-sig") as hourly_file:
        writer = csv.DictWriter(hourly_file, fieldnames=FIELDS)
        writer.writeheader()
        for link, changes in iter_link_changes(connection):
            bins, final_active = hourly_metrics(changes, horizon)
            for time, delta, _, _ in changes:
                global_association[time] += delta
            writer.writerows({"link_id": link, **row} for row in bins)
            vehicle_seconds = sum(row["vehicle_seconds"] for row in bins)
            summaries.append({"link_id": link, "entries": sum(row["entries"] for row in bins),
                              "traffic_entries": sum(row["traffic_entries"] for row in bins),
                              "vehicle_seconds": vehicle_seconds, "mean_active": vehicle_seconds/horizon,
                              "peak_active": max(row["peak_active"] for row in bins),
                              "coverage_seconds": horizon, "associated_at_cut": final_active})
        # Independent census traffic lifetime coverage, including unrepresented tails.
        for entered, arrived, exited, retired in connection.execute("SELECT entered,arrival,exited,retired FROM trips"):
            if entered is None:
                continue
            terminal = min((value for value in (arrived, exited, retired) if value is not None), default=horizon)
            if terminal < entered or terminal > horizon:
                raise ValueError("Invalid census lifetime")
            native_active[entered] += 1
            if terminal < horizon or any(v == horizon for v in (arrived, exited, retired)):
                native_active[terminal] -= 1
        counts = {"series_rows": connection.execute("SELECT count(*) FROM series").fetchone()[0],
                  "trips": connection.execute("SELECT count(*) FROM trips").fetchone()[0]}
    write_csv(summary_path, [field for field in FIELDS if field != "hour"] + ["associated_at_cut"], summaries)
    missing_changes = [(time, native_active[time]-global_association[time], 0, 0)
                       for time in sorted(set(native_active) | set(global_association))]
    missing, missing_at_cut = hourly_metrics(missing_changes, horizon)
    native_bins, native_at_cut = hourly_metrics([(t, d, 0, 0) for t,d in sorted(native_active.items())], horizon)
    associated_bins, associated_at_cut = hourly_metrics([(t, d, 0, 0) for t,d in sorted(global_association.items())], horizon)
    coverage_rows = [{"hour": n["hour"], "native_vehicle_seconds": n["vehicle_seconds"],
                      "associated_vehicle_seconds": a["vehicle_seconds"], "unassociated_vehicle_seconds": u["vehicle_seconds"],
                      "native_peak_active": n["peak_active"], "associated_peak_active": a["peak_active"],
                      "unassociated_peak_active": u["peak_active"], "native_mean_active": n["mean_active"],
                      "associated_mean_active": a["mean_active"]} for n,a,u in zip(native_bins,associated_bins,missing)]
    coverage_path = output / "coverage_hourly.csv"
    write_csv(coverage_path, list(coverage_rows[0]), coverage_rows)
    aggregate.check_source_files()
    source_manifest_path = next(Path(p["path"]) for p in manifest["sources"] if Path(p["path"]).name == "sqlite-source-manifest.json")
    source_manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    segments_read = manifest["counts"].get("segments_read", 0)
    segments_excluded = manifest["counts"].get("excluded_non_native_association_segments", 0)
    expected_segments = source_manifest["counts"]["segments"]
    if segments_read + segments_excluded != expected_segments:
        raise ValueError("Aggregate scan coverage differs from complete source receipt")
    report = {"schema": VERSION, "status": "complete", "created_utc": datetime.now(timezone.utc).isoformat(),
              "identity": manifest["identity"], "replay_window": manifest["replay_window"],
              "postprocessor_sha256": digest(__file__), "aggregate_producer_sha256": manifest["producer_sha256"],
              "aggregate_manifest": str(manifest_path.resolve()), "aggregate_manifest_sha256": digest(manifest_path),
              "source_pins": manifest["sources"], "aggregate_counts": manifest["counts"], "table_counts": counts,
              "coverage": {"complete_native_scan": True, "expected_segments": expected_segments,
                           "segments_read": segments_read, "segments_excluded_non_native": segments_excluded,
                           "complete_link_association": not any(r["vehicle_seconds"] or r["peak_active"] for r in missing) and missing_at_cut == 0,
                           "absent_link": "No observed entries or native association; only infer zero observed flow after complete scan, never a physical geometry/queue measurement."},
              "outputs": [{"path": str(p.resolve()), "sha256": digest(p), "bytes": p.stat().st_size}
                          for p in [hourly_path, summary_path, coverage_path]],
              "totals": {"links_with_observed_association_or_entries": len(summaries),
                         "entries": sum(row["entries"] for row in summaries),
                         "traffic_entries": sum(row["traffic_entries"] for row in summaries),
                         "associated_vehicle_seconds": sum(row["vehicle_seconds"] for row in summaries),
                         "native_vehicle_seconds": sum(row["vehicle_seconds"] for row in native_bins),
                         "unassociated_vehicle_seconds": sum(row["vehicle_seconds"] for row in missing),
                         "native_peak_active": max(row["peak_active"] for row in native_bins),
                         "native_active_at_cut": native_at_cut, "associated_at_cut": associated_at_cut,
                         "unassociated_at_cut": missing_at_cut},
              "definitions": {"entries": "Incrementos de LinkEnter nativo; no incluye VehicleEntersTraffic ni intervalos de render.",
                              "traffic_entries": "Incrementos de VehicleEntersTraffic, separados del flujo por transiciones.",
                              "vehicle_seconds": "Integral exacta del conteo de asociación nativa a enlace en [h*3600,(h+1)*3600).",
                              "mean_active": "vehicle_seconds / duración del intervalo; asociación de vehículos, no ocupación corporal.",
                              "peak_active": "Máximo exacto de la suma simultánea de familias; no suma de máximos por familia.",
                              "coverage_seconds": "Ventana observada, no garantía de representación espacial de cada segundo-vehículo."},
              "limitations": ["Asociación nativa a enlace es proxy de acumulación. No determina posición dentro del enlace, longitud de cola, densidad corporal ni espera ante semáforo.",
                              "Sin asociación observada no se asigna un enlace inventado. La cobertura faltante se reporta mediante comparación con censos nativos.",
                              "Flujo cuenta transiciones observadas; un vehículo puede pasar repetidamente. No es conteo de vehículos únicos ni suma válida de un corredor sin definir sección.",
                              "Instantes al horizonte se conservan como estado al corte; no generan una hora 24 ni duraciones adicionales."]}
    (output / "manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def ensure_metrics(root: Path, label: str, run: Path, output_root: Path | None = None):
    output = ((output_root or root / "graficas_tesis_v2/datos-espaciales") / label).resolve()
    if output.is_relative_to(root.resolve() / "scenarios"):
        raise ValueError("Spatial postprocessing output must be outside native scenarios")
    aggregate_directory = output / "aggregate"
    if not (aggregate_directory / "aggregate-manifest.json").exists():
        if (aggregate_directory / "aggregate.sqlite").exists():
            raise ValueError("Incomplete aggregate preserved; investigate existing build.log before retrying")
        build(run / "webgl-source-it.0/sqlite-source", aggregate_directory,
              progress=lambda item: print(json.dumps({"run": label, **item}), flush=True))
    native = json.loads((run / "run-manifest.json").read_text(encoding="utf-8"))
    expected = {"run_id": native["run_id"], "iteration": 0,
                "run_manifest_sha256": digest(run / "run-manifest.json"),
                "source_version": digest(run / "webgl-source-it.0/sqlite-source/sqlite-source-manifest.json")}
    # Requested run identity is independent of the cache's own declaration.
    AggregateReplay(aggregate_directory, expected).check_source_files()
    output_manifest = output / "manifest.json"
    if output_manifest.exists():
        previous = json.loads(output_manifest.read_text(encoding="utf-8"))
        if previous.get("schema") == VERSION and previous.get("postprocessor_sha256") == digest(__file__):
            manifest = json.loads((aggregate_directory / "aggregate-manifest.json").read_text(encoding="utf-8"))
            AggregateReplay(aggregate_directory, manifest["identity"]).check_source_files()
            if all(digest(item["path"]) == item["sha256"] for item in previous["outputs"]):
                return previous
    return extract_metrics(aggregate_directory, output)


def generate(output: Path | None = None, root: Path | None = None):
    root = (root or Path(__file__).resolve().parents[1]).resolve()
    output = (output or root / "graficas_tesis_v2/datos-espaciales").resolve()
    if output.is_relative_to(root / "scenarios"):
        raise ValueError("Spatial postprocessing output must be outside native scenarios")
    return [ensure_metrics(root, label, root/"scenarios/zona1/montecarlo"/dirname, output)
            for label, (_, _, dirname) in zip(["run1000", "run10000"], RUNS)]


def self_test():
    import unittest

    class Semantics(unittest.TestCase):
        def test_hour_boundary_and_simultaneous_events(self):
            rows, final = hourly_metrics([(3590, 1, 0, 1), (3600, -1, 0, 0), (3600, 1, 1, 0), (3610, -1, 0, 0)], 7200)
            self.assertEqual([r["vehicle_seconds"] for r in rows], [10, 10])
            self.assertEqual([r["peak_active"] for r in rows], [1, 1])
            self.assertEqual([r["entries"] for r in rows], [0, 1])
            self.assertEqual([r["traffic_entries"] for r in rows], [1, 0])
            self.assertEqual(final, 0)

        def test_repeat_observation_and_exact_family_peak(self):
            with sqlite3.connect(":memory:") as db:
                db.execute("CREATE TABLE series(link,family,time,count,entries,link_enters)")
                db.executemany("INSERT INTO series VALUES(?,?,?,?,?,?)", [("A","carro",0,1,1,0),("A","carro",5,1,1,0),("A","carro",10,0,1,0),("A","moto",10,1,1,1),("A","moto",20,0,1,1)])
                link, changes = next(iter_link_changes(db))
                rows, _ = hourly_metrics(changes, 30, 30)
                self.assertEqual(link, "A")
                self.assertEqual(rows[0]["vehicle_seconds"],20)
                self.assertEqual(rows[0]["peak_active"],1)
                self.assertEqual(rows[0]["entries"],1)
                self.assertEqual(rows[0]["traffic_entries"],1)

        def test_censored_tail_and_null_not_zero(self):
            rows, final = hourly_metrics([(2,1,0,1)],10,10)
            self.assertEqual(rows[0]["vehicle_seconds"],8)
            self.assertEqual(final,1)

        def test_reject_invalid_stock_time_and_counter(self):
            for rows in [[(1,-1,0,0)],[(11,1,0,1)],[(2,1,0,1),(1,0,0,0)],[(1,0,-1,0)],[(10,1,1,0)]]:
                with self.assertRaises(ValueError): hourly_metrics(rows,10,10)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Semantics)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--run", choices=["all", "run1000", "run10000"], default="all")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        raise SystemExit(0 if self_test() else 1)
    for label, (_, _, dirname) in zip(["run1000", "run10000"], RUNS):
        if args.run not in ("all", label):
            continue
        result = ensure_metrics(args.root.resolve(), label, args.root.resolve()/"scenarios/zona1/montecarlo"/dirname, args.output)
        print(json.dumps({"run": label, "totals": result["totals"]}), flush=True)
