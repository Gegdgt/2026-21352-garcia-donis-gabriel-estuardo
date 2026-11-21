"""Observe one verified SimZ1 JVM with read-only jcmd GC.heap_info."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

from simz1_resource_monitor import _WindowsBackend, descendant_pids, read_java_heap


def observe(outputdir, root_pid, java_pid, creation_ticks, interval_seconds=15):
    backend = _WindowsBackend()
    directory = Path(outputdir)
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    summary = {"root_pid": root_pid, "java_pid": java_pid, "creation_ticks": creation_ticks,
               "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(), "samples": 0,
               "successful_samples": 0, "peak_heap_used_bytes": None,
               "peak_heap_committed_bytes": None, "last_error": None,
               "source": "jcmd_GC.heap_info", "sampling_interval_seconds": interval_seconds,
               "coverage": "Observation begins after JVM startup; sampled peak only"}

    def save_summary():
        summary["elapsed_seconds"] = time.monotonic() - started
        temporary = directory / "heap-jcmd-summary.json.tmp"
        temporary.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        temporary.replace(directory / "heap-jcmd-summary.json")

    try:
        with (directory / "heap-jcmd.jsonl").open("a", encoding="utf-8") as stream:
            while True:
                inventory = backend.processes()
                if java_pid not in inventory:
                    summary["end_reason"] = "java_process_exited"
                    break
                if java_pid not in descendant_pids(inventory, root_pid):
                    summary["end_reason"] = "java_not_descendant_of_authorized_root"
                    break
                if inventory[java_pid]["exe"].lower() not in ("java.exe", "javaw.exe"):
                    summary["end_reason"] = "pid_no_longer_java"
                    break
                try:
                    identity = backend.sample_process(java_pid)
                except OSError:
                    summary["end_reason"] = "java_exited_during_identity_check"
                    break
                if identity["creation_ticks"] != creation_ticks:
                    summary["end_reason"] = "pid_identity_changed"
                    break
                sample = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "elapsed_seconds": time.monotonic() - started,
                          "root_pid": root_pid, "java_pid": java_pid,
                          "creation_ticks": creation_ticks, "ancestry_verified": True}
                try:
                    heap = read_java_heap(java_pid, prefer_jcmd=True)
                    # Reject a sample if the PID changed while the command ran.
                    if backend.sample_process(java_pid)["creation_ticks"] != creation_ticks:
                        summary["end_reason"] = "pid_identity_changed_during_sample"
                        break
                    sample["heap"] = heap
                    summary["successful_samples"] += 1
                    for field, value in (("peak_heap_used_bytes", heap["used_bytes"]),
                                         ("peak_heap_committed_bytes", heap["committed_bytes"])):
                        summary[field] = max(summary[field] or 0, value)
                except Exception as error:
                    sample["heap"] = None
                    sample["error"] = str(error)
                    summary["last_error"] = str(error)
                summary["samples"] += 1
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                save_summary()
                if summary["samples"] == 1:
                    print(json.dumps({"observer": "started", **sample}), flush=True)
                time.sleep(max(0.1, interval_seconds))
    except KeyboardInterrupt:
        summary["end_reason"] = "observer_interrupted"
    except Exception as error:
        summary["end_reason"] = "observer_error"
        summary["last_error"] = str(error)
    finally:
        summary["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        save_summary()
        print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--root-pid", type=int, required=True)
    parser.add_argument("--java-pid", type=int, required=True)
    parser.add_argument("--creation-ticks", type=int, required=True)
    parser.add_argument("--interval-seconds", type=float, default=15)
    args = parser.parse_args()
    observe(args.output_dir, args.root_pid, args.java_pid, args.creation_ticks, args.interval_seconds)
