"""Read-only measurements of the existing SimZ1 replay and continuous transport.

Each direct sample runs in a fresh Python process; the HTTP mode measures a
dedicated server across cache misses and hits. No event stream, motion solver
or MATSim process is invoked. Old export timings are historical observations;
the measurements cover reads and transport preparation on this machine.
"""
import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zlib


def memory(pid=None):
    if os.name == "nt":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
        values = Counters()
        values.cb = ctypes.sizeof(values)
        current_process = ctypes.windll.kernel32.GetCurrentProcess
        current_process.restype = wintypes.HANDLE
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
        handle = current_process()
        if pid is not None:
            open_process = ctypes.windll.kernel32.OpenProcess
            open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            open_process.restype = wintypes.HANDLE
            handle = open_process(0x410, False, pid)
            if not handle:
                raise ctypes.WinError()
        try:
            if not get_memory(handle, ctypes.byref(values), values.cb):
                raise ctypes.WinError()
        finally:
            if pid is not None:
                close_handle = ctypes.windll.kernel32.CloseHandle
                close_handle.argtypes = [wintypes.HANDLE]
                close_handle(handle)
        return dict(working_set_bytes=values.WorkingSetSize,
                    peak_working_set_bytes=values.PeakWorkingSetSize)
    if pid is not None:
        return {"working_set_bytes": None, "peak_working_set_bytes": None}
    import resource
    return dict(peak_working_set_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def implementation_hashes():
    root = Path(__file__).resolve().parent
    return {name: digest(root/name) for name in (
        "simz1_continuous_replay.py", "serve_simz1_continuous.py", "benchmark_simz1_continuous.py")}


def read_context(directory):
    from serve_simz1_replay import read_export
    root, manifest, database = read_export(directory)
    run_path = Path(manifest["run_directory"]) / "run-manifest.json"
    run = json.loads(run_path.read_text(encoding="utf-8"))
    if run.get("status") != "completed" or run.get("validation", {}).get("status") != "valid":
        raise ValueError("The source run must be completed and validated")
    if digest(run_path) != manifest["run_manifest_sha256"]:
        raise ValueError("The original run manifest hash differs from the replay")
    if run["run_id"] != manifest["run_id"]:
        raise ValueError("The original run identity differs from the replay")
    return root, manifest, database


def legacy_sample(root, manifest, index):
    block = manifest["blocks"][index]
    begin = time.perf_counter()
    raw = (root / "blocks" / block["url"]).read_text(encoding="utf-8")
    read_done = time.perf_counter()
    marker = '<script id="replay-data" type="application/json">'
    start = raw.index(marker) + len(marker)
    text = raw[start:raw.index("</script>", start)]
    slice_done = time.perf_counter()
    payload = json.loads(text)
    parsed = time.perf_counter()
    records = next(layer["data"] for layer in payload["layers"] if layer["id"] == "trips")
    static_layer_bytes = sum(len(json.dumps(layer, separators=(",", ":")).encode("utf-8"))
                             for layer in payload["layers"] if layer["id"] not in ("trips", "incidents"))
    return dict(kind="legacy_html_read_parse", block=block, records=len(records),
                payload_utf8_bytes=len(text.encode("utf-8")),
                static_layer_json_bytes=static_layer_bytes,
                inline_html_and_javascript_bytes=len(raw.encode("utf-8"))-len(text.encode("utf-8")),
                seconds=dict(html_read=read_done-begin, payload_slice=slice_done-read_done,
                             json_parse=parsed-slice_done, read_to_parsed=parsed-begin),
                memory=memory(),
                scope="Fresh Python process reading full historical HTML; not browser parsing or GPU rendering")


def sqlite_sample(root, manifest, database, index):
    block = manifest["blocks"][index]
    begin = time.perf_counter()
    seconds = dict(sql_fetch=0.0, zlib_decode=0.0, json_parse=0.0, unique_trip_parse=0.0)
    records, journeys = [], {}
    compressed_bytes = decoded_bytes = 0
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        connection.execute("PRAGMA cache_size=-32768")
        tick = time.perf_counter()
        cursor = connection.execute('''SELECT s.journey,s.payload,j.metadata
            FROM segment_blocks b JOIN segments s ON s.id=b.segment
            JOIN journeys j ON j.key=s.journey WHERE b.block=? ORDER BY s.start,s.end,s.id''', (index,))
        seconds["sql_fetch"] += time.perf_counter()-tick
        while True:
            tick = time.perf_counter()
            row = cursor.fetchone()
            seconds["sql_fetch"] += time.perf_counter()-tick
            if row is None:
                break
            key, compressed, trip = row
            compressed_bytes += len(compressed)
            tick = time.perf_counter()
            decoded = zlib.decompress(compressed)
            seconds["zlib_decode"] += time.perf_counter()-tick
            decoded_bytes += len(decoded)
            tick = time.perf_counter()
            record = json.loads(decoded)
            seconds["json_parse"] += time.perf_counter()-tick
            records.append(record)
            if key not in journeys:
                tick = time.perf_counter()
                journeys[key] = json.loads(trip)
                seconds["unique_trip_parse"] += time.perf_counter()-tick
        loaded = time.perf_counter()
    loaded_memory = memory()
    payload = dict(run_id=manifest["run_id"], iteration=manifest["iteration"],
                   block=index, records=records, journeys=journeys)
    tick = time.perf_counter()
    encoded = json.dumps(payload, separators=(",", ":"), allow_nan=False).encode("utf-8")
    seconds["compact_json_encode"] = time.perf_counter()-tick
    encoded_memory = memory()
    tick = time.perf_counter()
    compressed = gzip.compress(encoded, compresslevel=1, mtime=0)
    seconds["gzip_level_1"] = time.perf_counter()-tick
    seconds["load_records_total"] = loaded-begin
    seconds["total"] = time.perf_counter()-begin
    return dict(kind="sqlite_segment_transport", block=block, records=len(records), journeys=len(journeys),
                sqlite_compressed_payload_bytes=compressed_bytes, decoded_segment_json_bytes=decoded_bytes,
                segment_transport_json_bytes=len(encoded), segment_transport_gzip_bytes=len(compressed),
                seconds=seconds, memory_after_load=loaded_memory, memory_after_encode=encoded_memory,
                memory=memory(), scope="All original fields and Motion_Plan retained; Trip deduplicated by journey. "
                "This diagnostic excludes lanes, signals, fixed geometry and HTTP. It is not the final API benchmark.")


def run_worker(args):
    if args.worker == "server":
        from serve_simz1_continuous import ContinuousServer, handler_for
        import threading
        server = ContinuousServer(("127.0.0.1", 0), handler_for(args.continuous_directory))
        print(json.dumps(dict(port=server.server_address[1], pid=os.getpid())), flush=True)
        # Windows venv python.exe may be a launcher whose PID is not the real
        # Python server. Report the serving PID and stop it through its stdin.
        def stop_on_stdin():
            sys.stdin.readline()
            server.shutdown()
        threading.Thread(target=stop_on_stdin, daemon=True).start()
        try:
            server.serve_forever()
        finally:
            server.server_close()
        return
    if args.worker == "continuous":
        print(json.dumps(continuous_sample(args.continuous_directory, args.time),
                         separators=(",", ":"), allow_nan=False))
        return
    root, manifest, database = read_context(args.directory)
    if args.worker == "legacy":
        result = legacy_sample(root, manifest, args.index)
    else:
        result = sqlite_sample(root, manifest, database, args.index)
    print(json.dumps(result, separators=(",", ":"), allow_nan=False))


def continuous_sample(directory, at):
    from simz1_continuous_replay import ContinuousReplay
    begin = time.perf_counter()
    replay = ContinuousReplay(directory)
    initialized = time.perf_counter()
    manifest = replay.manifest
    if not manifest["replay_window"]["start_seconds"] <= at <= manifest["replay_window"]["end_seconds"]:
        raise ValueError(f"Probe {at} is outside the served replay window")
    index = min(manifest["window_count"]-1, int((at-manifest["replay_window"]["start_seconds"])/manifest["window_seconds"]))
    raw = replay.window_bytes(index)
    loaded = time.perf_counter()
    loaded_memory = memory()
    compressed = gzip.compress(raw, compresslevel=1, mtime=0)
    done = time.perf_counter()
    production_memory = memory()
    # Inspection is deliberately outside the timed production hot path and its
    # recorded peak: the server transmits the assembled original JSON bytes.
    payload = json.loads(raw)
    return dict(kind="continuous_complete_window", requested_time_seconds=at, index=index,
                start_seconds=payload["start_seconds"], end_seconds=payload["end_seconds"],
                records=len(payload["segments"]), journeys=len(payload["trips"]),
                lanes=len(payload["lane_replay"]["events"]),
                signal_groups=len(payload["signal_replay"]["series"]),
                signal_state_events=payload["signal_replay"]["retained_state_events"],
                incidents=len(payload["incidents"]), json_bytes=len(raw), gzip_bytes=len(compressed),
                seconds=dict(initialize=initialized-begin, load_window=loaded-initialized,
                             gzip_level_1=done-loaded,
                             ready_gzip_excluding_initialization=done-initialized, total=done-begin),
                backend_phases_seconds=payload["timings_seconds"], memory_after_load=loaded_memory,
                memory=production_memory, scope="Complete production window_bytes hot path retains original JSON bytes, plus native lanes/signals/incidents; fresh Python process; validation parsing occurs after the production peak is recorded; excludes HTTP and browser")


def continuous_report(args, source_manifest, source_root):
    from simz1_continuous_replay import ContinuousReplay
    replay = ContinuousReplay(args.continuous_directory)
    stat = replay.database.stat()
    before = (stat.st_size, stat.st_mtime_ns)
    results = []
    for at in (0, 63000, 63300, 86399, 86400):
        print(f"Measuring complete continuous window at {at:g} s in a fresh process...", flush=True)
        worker = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--directory", str(source_root),
                                "--continuous-directory", str(args.continuous_directory.resolve()),
                                "--worker", "continuous", "--time", str(at)], capture_output=True, text=True)
        if worker.returncode:
            raise RuntimeError(worker.stderr)
        results.append(json.loads(worker.stdout))
    stat = replay.database.stat()
    if before != (stat.st_size, stat.st_mtime_ns):
        raise RuntimeError("The source database changed during the benchmark")
    report = dict(schema_version=1, status="complete", run_id=replay.manifest["run_id"],
                  iteration=replay.manifest["iteration"], source_export=str(source_root),
                  continuous_directory=str(args.continuous_directory.resolve()),
                  continuous_manifest_sha256=digest(args.continuous_directory / "continuous-manifest.json"),
                  implementation_sha256=implementation_hashes(),
                  source_database_size_mtime_unchanged=True, window_seconds=replay.manifest["window_seconds"],
                  application_build=dict(phases_seconds=replay.manifest["phases_seconds"],
                    reused_incomplete_temporal_files=replay.manifest.get("reused_incomplete_temporal_files", 0),
                    peak_working_set_bytes=replay.manifest["process_peak_working_set_bytes"],
                    application_bytes=replay.manifest["application_bytes"],
                    temporal_bytes=replay.manifest["temporal_bytes"]),
                  old_export=dict(phases_seconds=source_manifest["phases_seconds"],
                    peak_working_set_bytes=source_manifest["process_peak_working_set_bytes"],
                    html_bytes=source_manifest["html_bytes"]), samples=results,
                  limitations=["Filesystem cache was not flushed and this shared machine was not reserved exclusively.",
                    "Generation reuses validated SQLite and existing signal evidence. Historical export also included event extraction and all journey interpolation.",
                    "application_build reports the measured attempt recorded in the served manifest; nonzero reused_incomplete_temporal_files means it is not a fresh preparation.",
                    "Sampled data windows are not a scan of all windows; sampled peak is not a global worst case.",
                    "These are direct backend calls, JSON encoding and gzip measurements. HTTP latency, browser memory and GPU FPS require separate browser evidence."])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    print(args.output)


def http_report(args, source_root):
    from simz1_continuous_replay import ContinuousReplay
    replay = ContinuousReplay(args.continuous_directory)
    query = urlencode(replay.identity)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    log_path = args.output.with_suffix(".server.log")
    samples = []
    with log_path.open("x", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
            "--directory", str(source_root), "--continuous-directory", str(args.continuous_directory.resolve()),
            "--worker", "server"], stdout=subprocess.PIPE, stdin=subprocess.PIPE, stderr=log, text=True)
        try:
            line = process.stdout.readline().strip()
            try:
                handshake = json.loads(line)
                server_pid, port = int(handshake["pid"]), int(handshake["port"])
            except (ValueError, KeyError, TypeError):
                raise RuntimeError(f"Benchmark server did not start; inspect {log_path}")
            base = f"http://127.0.0.1:{port}"
            def request(path):
                before = time.perf_counter()
                with urlopen(Request(base+path, headers={"Accept-Encoding": "gzip"}), timeout=120) as response:
                    raw = response.read()
                    received = time.perf_counter()
                    content = gzip.decompress(raw) if response.headers.get("Content-Encoding") == "gzip" else raw
                    decoded = json.loads(content)
                    return decoded, dict(http_seconds=received-before, client_decode_parse_seconds=time.perf_counter()-received,
                        wire_bytes=len(raw), decoded_bytes=len(content), status=response.status)
            initial_memory = memory(server_pid)
            middle = min(replay.manifest["window_count"]-1, int(63000/replay.manifest["window_seconds"]))
            # Repeated miss/hit then enough distinct adjacent windows to exercise
            # both entry- and byte-bounded response eviction on production data.
            indices = [middle, middle] + list(range(middle+1, min(middle+11, replay.manifest["window_count"]))) + [middle]
            if args.http_short:
                indices = indices[:3]
            for index in indices:
                print(f"Measuring localhost request {len(samples)+1}/{len(indices)}: window {index}...", flush=True)
                payload, measured = request(f"/api/window?{query}&index={index}")
                metrics, _ = request(f"/api/metrics?{query}")
                if any(payload[key] != value for key, value in replay.identity.items()):
                    raise RuntimeError("HTTP response identity mismatch")
                cache = metrics["cache"]
                if cache["bytes"] > cache["max_bytes"] or cache["entries"] > cache["max_entries"]:
                    raise RuntimeError("Production cache exceeded its declared limits")
                samples.append(dict(index=index, records=len(payload["segments"]), **measured,
                                    server_memory=memory(server_pid), cache=cache))
                del payload
            final_memory = memory(server_pid)
        finally:
            if process.poll() is None:
                try:
                    process.stdin.write("stop\n")
                    process.stdin.flush()
                except (BrokenPipeError, OSError):
                    pass
            process.wait(timeout=15)
            process.stdout.close()
            process.stdin.close()
    report = dict(schema_version=1, status="complete", run_id=replay.manifest["run_id"],
        iteration=replay.manifest["iteration"], window_seconds=replay.manifest["window_seconds"],
        continuous_manifest_sha256=digest(args.continuous_directory / "continuous-manifest.json"),
        implementation_sha256=implementation_hashes(),
        serving_process_id=server_pid, launcher_process_id=process.pid,
        memory_measurement="GetProcessMemoryInfo of os.getpid() reported by the actual serving Python worker, not the venv launcher",
        initial_server_memory=initial_memory, final_server_memory=final_memory,
        samples=samples, cache_limits_passed=True, cache_eviction_exercised=not args.http_short, server_log=str(log_path),
        limitations=["Fresh dedicated loopback server; filesystem cache was not flushed; shared-machine activity was not excluded.",
            "Sequential HTTP misses and hits exercise the server LRU. These are not simultaneous cancellation stress tests or an all-day memory leak proof.",
            "Server native process peak and HTTP latency do not measure browser memory or GPU frame rate."])
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    print(args.output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--continuous-directory", type=Path,
                        help="Measure complete production windows from an already generated continuous viewer")
    parser.add_argument("--http", action="store_true", help="Measure the production loopback HTTP server and its bounded cache")
    parser.add_argument("--http-short", action="store_true", help="Only three HTTP requests for isolated server-memory verification")
    parser.add_argument("--blocks", type=int, nargs="+")
    parser.add_argument("--worker", choices=("legacy", "sqlite", "continuous", "server"), help=argparse.SUPPRESS)
    parser.add_argument("--index", type=int, help=argparse.SUPPRESS)
    parser.add_argument("--time", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        run_worker(args)
        return
    if not args.output:
        parser.error("--output is required")
    if args.output.exists():
        parser.error("Choose a new output filename; benchmark evidence is never overwritten")
    root, manifest, database = read_context(args.directory)
    if args.http and not args.continuous_directory:
        parser.error("--http requires --continuous-directory")
    if args.http:
        http_report(args, root)
        return
    if args.continuous_directory:
        continuous_report(args, manifest, root)
        return
    before = database.stat()
    export_hash = digest(root / "export-manifest.json")
    blocks = args.blocks or list(dict.fromkeys([0, max(manifest["blocks"], key=lambda b:b["html_bytes"])["index"],
                            287, 288, 299, len(manifest["blocks"])-1]))
    if any(index < 0 or index >= len(manifest["blocks"]) for index in blocks):
        parser.error("An index lies outside the exported blocks")
    results = []
    for index in blocks:
        for kind in ("legacy", "sqlite"):
            print(f"Measuring {kind} block {index} in a fresh process...", flush=True)
            worker = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--directory", str(root),
                                     "--worker", kind, "--index", str(index)], capture_output=True, text=True)
            if worker.returncode:
                raise RuntimeError(worker.stderr)
            results.append(json.loads(worker.stdout))
    after = database.stat()
    unchanged = (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    unchanged = unchanged and export_hash == digest(root / "export-manifest.json")
    if not unchanged:
        raise RuntimeError("The source evidence changed during this read-only benchmark")
    phases = manifest["phases_seconds"]
    report = dict(schema_version=1, status="complete", run_id=manifest["run_id"], iteration=manifest["iteration"],
                  source_export=str(root), source_export_sha256=export_hash,
                  python_version=sys.version, sample_rate=manifest["sample_rate"],
                  historical_export=dict(phases_seconds=phases,
                    phase_share_percent={key:100*phases[key]/phases["total"] for key in
                        ("metadata", "event_spool", "sqlite_indexes", "complete_journey_motion", "blocks")},
                    html_files=len(manifest["blocks"]), html_bytes=manifest["html_bytes"],
                    database_bytes=manifest["database_bytes"],
                    peak_working_set_bytes=manifest["process_peak_working_set_bytes"],
                    memory_attribution="Only overall peak was recorded; no per-phase peak can be inferred",
                    block_segment_occurrences=manifest["block_segment_occurrences"],
                    unique_segments=manifest["counts"]["segments"]),
                  samples=results, source_database_size_mtime_unchanged=unchanged,
                  limitations=["Filesystem cache was not flushed; this is not a guaranteed cold-cache measurement; shared machine activity was not excluded.",
                    "Fresh processes isolate peak memory per sample. SQLite rows are decoded incrementally, with all records retained for JSON encoding.",
                    "Legacy HTML parse is measured in Python, not a browser. No FPS or GPU claims follow from these timings.",
                    "The segment-transport diagnostic excludes native signal/lane payloads; use final API measurements for end-to-end comparisons.",
                    "Historical export phases are nested: events_and_motion includes event_spool, sqlite_indexes and complete_journey_motion."])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False)+"\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
