"""Read a fixed, tiny historical SimZ1 sample without opening a replay server.

This is evidence extraction, not a renderer or a simulation. SQLite is opened
read-only/immutable, all data queries use indexed IDs and bounded LIMITs. No
historical files are modified. Output distinguishes model positions from actual
browser visibility, which cannot be established by this script.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET
import zlib


RUN_ID = "simz1-0dd152dabbc24d1d84d9b738c449cc35"
CASES = (
    ("unavailable_before_arrival_z1_43360", (927, 939), (123.999, 124.0, 124.5, 124.999, 125.0, 125.001)),
    ("short_link_native_wait_z1_38616", (115, 151, 169), (38.999, 39.0, 40.999, 41.0, 45.999, 46.0, 46.001)),
    ("arrival_zero_duration_z1_167074", (1682, 1684), (168.999, 169.0, 169.001)),
)


def geometry_excerpt(database, link_ids):
    """Retain source XML data only; do not run the production geometry builder."""
    directory = database.parents[1]
    run = json.loads((directory / "run-manifest.json").read_bytes())
    if run.get("run_id") != RUN_ID:
        raise ValueError("Geometry run differs from SQLite sample")
    specifications = {
        "network": run["results"]["0"]["network"],
        "lanes": run["effective_lane_configuration_validation"]["loaded_artifacts"]["lanes"],
    }
    roots, sources = {}, {}
    for name, specification in specifications.items():
        path = (directory / specification["path"]).resolve(strict=True)
        if not path.is_relative_to(directory) or path.stat().st_size > 2_000_000:
            raise ValueError("Geometry input exceeds this bounded historical inspection")
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != specification["sha256"]:
            raise ValueError("Effective geometry hash differs from run manifest")
        xml = gzip.decompress(raw)
        if len(xml) > 30_000_000:
            raise ValueError("Uncompressed geometry exceeds the inspection bound")
        roots[name] = ET.fromstring(xml)
        # MATSim laneDefinitions uses a default XML namespace. Preserve source
        # attributes while matching local element names in this evidence excerpt.
        for element in roots[name].iter():
            element.tag = element.tag.rsplit("}", 1)[-1]
        sources[name] = {"path": str(path), "sha256": digest, "bytes": len(raw)}
    selected = [link for link in roots["network"].findall("links/link")
                if link.get("id") in link_ids]
    nodes = {link.get(key) for link in selected for key in ("from", "to")}
    nearby = [link for link in roots["network"].findall("links/link")
              if link.get("from") in nodes or link.get("to") in nodes]
    if len(nearby) > 100:
        raise ValueError("Incident network excerpt exceeds 100 links")
    nearby_ids = {link.get("id") for link in nearby}
    nearby_nodes = {link.get(key) for link in nearby for key in ("from", "to")}

    def xml_data(element):
        value = {"tag": element.tag, "attributes": dict(element.attrib)}
        if element.text and element.text.strip():
            value["text"] = element.text.strip()
        if len(element):
            value["children"] = [xml_data(child) for child in element]
        return value

    return {
        "provenance": "Effective historical XML excerpt, not generated visual_lanes or rendered geometry",
        "coordinate_system": "EPSG:32615; raw effective coordinates",
        "sources": sources,
        "links": {link.get("id"): {"attributes": dict(link.attrib),
                  "metadata": {item.get("name"): item.text
                               for item in link.findall("attributes/attribute")}}
                  for link in nearby},
        "nodes": {node.get("id"): dict(node.attrib)
                  for node in roots["network"].findall("nodes/node")
                  if node.get("id") in nearby_nodes},
        "lane_assignments": [xml_data(assignment) for assignment in roots["lanes"].findall("lanesToLinkAssignment")
                             if assignment.get("linkIdRef") in nearby_ids],
    }


def model_position(record, instant):
    """Preview only the stored Motion_Plan on its unshifted centerline."""
    plan = record.get("Motion_Plan") or {}
    if plan.get("status") == "unavailable":
        return None
    distance = float(plan.get("distance_m", 0))
    traveled = 0.0
    for start, end, offset, speed, acceleration in plan.get("phases", []):
        if instant >= start:
            delta = min(instant, end) - start
            traveled = offset + speed * delta + acceleration * delta * delta / 2
    fraction = min(1.0, max(0.0, traveled / distance)) if distance else 0.0
    path = record["path"]
    if len(path) != 2:
        raise ValueError("This tiny fixture supports only the observed two-point paths")
    return [path[0][axis] + fraction * (path[1][axis] - path[0][axis]) for axis in (0, 1)]


def extract(manifest_path):
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    if (manifest.get("run_id"), manifest.get("iteration"), manifest.get("source_type")) != (
            RUN_ID, 0, "sqlite-direct-v1"):
        raise ValueError("Fixed sample requires its recorded run, iteration and SQLite source")
    database = Path(manifest["database"]).resolve(strict=True)
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Immutable inspection requires an offline database without sidecars")
    stat = database.stat()
    if stat.st_size != manifest["database_bytes"] or stat.st_mtime_ns != manifest["database_mtime_ns"]:
        raise ValueError("Database size/mtime no longer matches the historical manifest")
    connection = sqlite3.connect(database.as_uri() + "?mode=ro&immutable=1", uri=True)
    connection.execute("PRAGMA query_only=ON")
    budget = [0]

    def progress():
        budget[0] += 1000
        return int(budget[0] > 1_000_000)

    connection.set_progress_handler(progress, 1000)
    try:
        identity = dict(connection.execute("SELECT key,value FROM export_identity LIMIT 16"))
        if (identity.get("run_id") != RUN_ID or identity.get("iteration") != "0"
                or identity.get("run_manifest_sha256") != manifest.get("run_manifest_sha256")):
            raise ValueError("SQLite export identity differs from the manifest")
        cases = []
        for case_id, segment_ids, instants in CASES:
            records = []
            journey = None
            for segment_id in segment_ids:
                row = connection.execute(
                    "SELECT journey,vehicle,start,end,payload FROM segments WHERE id=? LIMIT 1",
                    (segment_id,),
                ).fetchone()
                if row is None:
                    raise ValueError(f"Missing historical segment {segment_id}")
                if journey is not None and row[0] != journey:
                    raise ValueError("Sample contains more than one journey")
                journey = row[0]
                record = json.loads(zlib.decompress(row[4]))
                records.append({"sqlite_segment_id": segment_id, "record": record})
            trip = json.loads(connection.execute(
                "SELECT metadata FROM journeys WHERE key=? LIMIT 1", (journey,)
            ).fetchone()[0])
            vehicle = records[0]["record"]["vehicle"]
            start, end = min(instants), max(instants)
            previous = connection.execute(
                "SELECT seq,payload FROM lane_events WHERE vehicle=? AND time<? "
                "ORDER BY time DESC,seq DESC LIMIT 1", (vehicle, start)
            ).fetchall()
            events = connection.execute(
                "SELECT seq,payload FROM lane_events WHERE vehicle=? AND time>=? AND time<=? "
                "ORDER BY time,seq LIMIT 33", (vehicle, start, end)
            ).fetchall()
            if len(events) == 33:
                raise ValueError("Lane evidence exceeded the fixed sample bound")
            lanes = [{"sqlite_seq": seq, **json.loads(zlib.decompress(raw))}
                     for seq, raw in previous + events]
            trace = []
            for instant in instants:
                active = [item for item in records
                          if item["record"]["timestamps"][0] <= instant
                          < item["record"]["timestamps"][1]]
                lane_events = [event for event in lanes if event["time"] <= instant]
                lane = lane_events[-1] if lane_events else None
                record = active[0]["record"] if len(active) == 1 else None
                arrived = trip.get("Status") == "completed" and instant >= trip["Arrival"]
                unavailable = record and (record.get("Motion_Plan") or {}).get("status") == "unavailable"
                reason = ("recorded_arrival" if arrived else
                          "motion_plan_unavailable:" + record["Motion_Plan"]["fallback_reason"] if unavailable else
                          "unknown_interval" if not active else
                          "active_native_interval_render_unknown")
                trace.append({
                    "run_id": RUN_ID, "iteration": 0, "vehicle_id": vehicle,
                    "person_id": trip["Person_ID"], "trip_id": trip["Trip_ID"],
                    "simulated_time": instant,
                    "sqlite_segment_id": active[0]["sqlite_segment_id"] if record else None,
                    "link_id": record["Link_ID"] if record else None,
                    "native_lane_id": lane["lane"] if lane and lane["type"] == "entered lane" else None,
                    "native_lane_last_event": lane,
                    "position_centerline_model_lonlat": model_position(record, instant) if record else None,
                    "position_rendered_lonlat": None,
                    "position_provenance": "stored Motion_Plan on centerline; not lane/queue/body placement",
                    "native_dimensions_m": None,
                    "client_nominal_dimensions_m": [4.5, 1.8],
                    "dimensions_provenance": "simz1_visual_queues.js defaults, not measured native dimensions",
                    "native_active_interval_count": len(active),
                    "visibility_reason": reason,
                    "visibility_reason_provenance": "native metadata and stored Motion_Plan; browser not observed",
                    "browser_visibility": "not_observed",
                    "qsim_forced_movement": "not_established_by_this_evidence",
                })
            cases.append({
                "case_id": case_id,
                "classification": (
                    "Intervalo abierto o desconocido: closed interval with unavailable position" if case_id.startswith("unavailable") else
                    "Ocultación por solapamiento o desborde: candidate only; renderer/roster not executed" if case_id.startswith("short_link") else
                    "Salida del dominio o llegada real"),
                "cause_confirmed_for_current_screenshot": False,
                "journey_key": journey, "trip": trip, "segments": records,
                "lane_events": lanes, "trace": trace,
            })
        link_ids = {item["record"]["Link_ID"] for case in cases for item in case["segments"]}
        return {
            "schema_version": 1,
            "evidence_kind": "bounded historical SQLite extraction; not a browser trace",
            "source": {
                "run_id": RUN_ID, "iteration": 0, "source_type": "sqlite-direct-v1",
                "manifest": str(manifest_path),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
                "database": str(database), "database_bytes": stat.st_size,
                "database_mtime_ns": stat.st_mtime_ns, "database_hash": "not_computed",
                "export_identity": identity,
            },
            "limits": {"vehicles": 3, "cases": 3, "segments": 7,
                       "lane_events_per_case_max": 33, "sqlite_instruction_budget": 1_000_000},
            "selection_inspection": {
                "description": "Earlier bounded PK inspection used to select fixed cases; not repeated by this CLI",
                "primary_key_range": [1, 2048], "rows_read": 2048, "compressed_payload_bytes": 2049135,
                "unavailable_positive_duration_terminal": 2,
                "unavailable_zero_duration_terminal": 4,
                "native_holds_under_4_5_m": 18,
                "unavailable_nonterminal_found": 0,
            },
            "client_loaded_version": "unknown; browser not opened",
            "scope": "Candidate historical replay only; no supplied screenshot identity",
            "effective_geometry_excerpt": geometry_excerpt(database, link_ids),
            "cases": cases,
        }
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, help="Optional small fixture outside historical runtime/scenarios")
    args = parser.parse_args()
    report = extract(args.manifest.resolve(strict=True))
    if args.output:
        output = args.output.resolve()
        repository = Path(__file__).resolve().parents[1]
        if output.parent != repository / "python" / "fixtures":
            raise ValueError("Fixture output must be directly under python/fixtures")
        output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"run_id": RUN_ID, "iteration": 0, "cases": [
        {"id": case["case_id"], "segments": len(case["segments"]),
         "lane_events": len(case["lane_events"]), "trace_rows": len(case["trace"])}
        for case in report["cases"]], "fixture": str(args.output) if args.output else None}, indent=2))


if __name__ == "__main__":
    main()
