"""Conservative cleanup of SimZ1 runs; no writes unless --inventory or --apply.

Chronology uses manifest started_utc, explicitly authorized by the user. It is
NOT a filesystem creation date. References to scientific evidence veto deletion.
Dry-run inventories are not approvals. Apply is Windows-only, uses locked native
handles, and never changes latest references or the protected 100k run.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import uuid
from urllib.parse import unquote

PROTECTED_ID = "simz1-3dd8683a7d5e44c0944587feff4fe0c8"
PROTECTED_PATH = "scenarios/zona1/montecarlo/run-052734f90d154b23bb8899cd0bbc3ef4"
ROOTS = tuple("scenarios/zona1/" + mode for mode in ("montecarlo", "debug", "historical"))
MANIFEST = "run-manifest.json"
POLICY = "manifest-started-utc-user-authorized-v1"
CONFIRMATION = "DELETE-REVIEWED-OLD-RUNS"
MAX_JSON = 16 * 1024 * 1024
MAX_REFERENCE = 64 * 1024 * 1024
MAX_HANDLES = 12000
REPARSE = 0x400
READONLY = 0x1
TERMINAL = {"completed", "failed", "interrupted"}
SKIP_DIRS = {".git", ".venv", "node_modules", "target", "__pycache__",
             ".pytest_cache", ".mypy_cache", ".ruff_cache"}
TEXT_SUFFIXES = {".md", ".json", ".jsonl", ".csv", ".tsv", ".xml", ".py",
                 ".ps1", ".sh", ".js", ".cjs", ".ini", ".yaml", ".yml", ".txt", ".html",
                 ".java", ".properties", ".toml"}
CODE_SUFFIXES = {".py", ".java", ".ps1", ".sh", ".js", ".cjs", ".class", ".jar", ".properties"}
BAD_PART = re.compile(r'[:\\<>|"?*\x00-\x1f]')
RUN_ID = re.compile(r"simz1-[0-9a-f]{32}\Z")


class SafetyError(ValueError):
    pass


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise SafetyError("Duplicate JSON key: " + key)
            result[key] = value
        return result

    def constant(value):
        raise SafetyError("Non-finite JSON value: " + value)

    value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs,
                       parse_constant=constant)
    if not isinstance(value, dict):
        raise SafetyError("Expected a JSON object")
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False).encode("ascii")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value):
    if not isinstance(value, str):
        raise SafetyError("Missing recorded timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SafetyError("Invalid recorded timestamp") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise SafetyError("Timestamp without timezone")
    return result.astimezone(timezone.utc)


def relative_name(value):
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise SafetyError("Expected a nonempty repository-relative path")
    parts = value.split("/")
    if any(part in ("", ".", "..") or BAD_PART.search(part) or
           part.endswith((" ", ".")) or
           re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part)
           for part in parts):
        raise SafetyError("Unsafe path: " + value)
    return PurePosixPath(value).as_posix()


def no_link(path):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & REPARSE:
        raise SafetyError("Symlink/reparse point: " + str(path))
    if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise SafetyError("Special file: " + str(path))
    return info


def safe_root(repo):
    repo = Path(os.path.abspath(repo))
    # Check ancestors before traversing any descendant. Do not resolve links.
    for current in reversed((repo, *repo.parents)):
        no_link(current)
    return repo


def safe_path(repo, relative):
    relative_name(relative)
    current = repo
    for part in relative.split("/"):
        current = current / part
        if os.path.lexists(current):
            no_link(current)
    if os.path.commonpath((str(repo), str(current))) != str(repo):
        raise SafetyError("Outside repository")
    return current


def stat_record(repo, path):
    info = no_link(path)
    is_dir = stat.S_ISDIR(info.st_mode)
    return dict(path=path.relative_to(repo).as_posix(), kind="dir" if is_dir else "file",
                size=0 if is_dir else info.st_size, mtime_ns=info.st_mtime_ns,
                file_id=info.st_ino, volume_id=info.st_dev,
                links=info.st_nlink, attributes=getattr(info, "st_file_attributes", 0))


def read_bytes(repo, relative, limit=MAX_JSON):
    path = safe_path(repo, relative)
    before = stat_record(repo, path)
    if before["kind"] != "file" or before["size"] > limit:
        raise SafetyError("Metadata is not a bounded regular file: " + relative)
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before["volume_id"], before["file_id"]):
            raise SafetyError("File identity changed: " + relative)
        raw = stream.read(limit + 1)
    if len(raw) > limit or stat_record(repo, path) != before:
        raise SafetyError("Metadata changed while reading: " + relative)
    return raw, {**before, "sha256": hashlib.sha256(raw).hexdigest()}


def tree_snapshot(repo, relative, hashes=False):
    records = []

    def visit(path):
        entry = stat_record(repo, path)
        if entry["kind"] == "file":
            if hashes:
                if entry["links"] != 1 or entry["attributes"] & READONLY:
                    raise SafetyError("Shared/readonly file: " + entry["path"])
                value = hashlib.sha256()
                flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                fd = os.open(path, flags)
                with os.fdopen(fd, "rb") as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino) != (entry["volume_id"], entry["file_id"]):
                        raise SafetyError("File replaced: " + entry["path"])
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        value.update(chunk)
                if stat_record(repo, path) != entry:
                    raise SafetyError("File changed while hashing: " + entry["path"])
                entry["sha256"] = value.hexdigest()
            records.append(entry)
            return
        records.append(entry)
        with os.scandir(path) as scan:
            children = sorted((Path(item.path) for item in scan), key=lambda p: p.name.casefold())
        for child in children:
            no_link(child)
            visit(child)
        if stat_record(repo, path) != entry:
            raise SafetyError("Directory changed while enumerating: " + entry["path"])

    visit(safe_path(repo, relative))
    if len({item["path"].casefold() for item in records}) != len(records):
        raise SafetyError("Case-insensitive path collision")
    return records


def tree_summary(records):
    return dict(bytes=sum(item["size"] for item in records),
                files=sum(item["kind"] == "file" for item in records),
                metadata_sha256=digest([{key: value for key, value in item.items() if key != "sha256"}
                                        for item in records]))


def load_run(repo, relative):
    row = dict(path=relative, run_id=None, created_utc=None, started_utc=None,
               finished_utc=None, persons=None, planned_trips=None, iterations=None,
               status=None, validation=None, manifest_sha256=None,
               age="unknown", classification="manual_review", reasons=[], dependencies=[])
    try:
        raw, record = read_bytes(repo, relative + "/" + MANIFEST)
        value = strict_json(raw)
        row.update(run_id=value.get("run_id"), created_utc=value.get("created_utc"),
                   started_utc=value.get("started_utc"), finished_utc=value.get("finished_utc"),
                   status=value.get("status"), validation=value.get("validation", {}).get("status"),
                   iterations=value.get("iterations"), manifest_sha256=record["sha256"])
        if value.get("schema_version") != 1 or not RUN_ID.fullmatch(str(row["run_id"])):
            raise SafetyError("Unsupported manifest identity/schema")
        if Path(os.path.abspath(value["folder"])) != safe_path(repo, relative):
            raise SafetyError("Manifest folder does not match")
        counts = value["counts"]
        for field in ("planned_persons", "planned_trips"):
            if type(counts.get(field)) is not int or counts[field] < 1:
                raise SafetyError("Invalid counts")
        row.update(persons=counts["planned_persons"], planned_trips=counts["planned_trips"])
        iterations = value["iterations"]
        if (type(iterations.get("first")) is not int or type(iterations.get("last")) is not int or
                iterations["first"] < 0 or iterations["last"] < iterations["first"] or
                not isinstance(iterations.get("completed"), list)):
            raise SafetyError("Invalid iteration metadata")
        for iteration in iterations["completed"]:
            if type(iteration) is not int or not iterations["first"] <= iteration <= iterations["last"]:
                raise SafetyError("Invalid completed iteration")
        started = timestamp(row["started_utc"])
        if started > datetime.now(timezone.utc):
            raise SafetyError("Start timestamp is in the future")
        if row["status"] not in TERMINAL:
            raise SafetyError("Nonterminal/possibly active run")
        finished = timestamp(row["finished_utc"])
        if finished < started:
            raise SafetyError("Finish precedes start")
        if finished > datetime.now(timezone.utc):
            raise SafetyError("Finish timestamp is in the future")
        if row["status"] == "completed" and row["validation"] != "valid":
            raise SafetyError("Completed run is not validated")
        row["manifest_valid"] = True
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        row["manifest_valid"] = False
        row["reasons"].append("manifest: " + str(error))
    return row


def discover_runs(repo):
    rows = []
    for root in ROOTS:
        folder = safe_path(repo, root)
        if not folder.exists():
            continue
        with os.scandir(folder) as scan:
            children = sorted((Path(item.path) for item in scan), key=lambda p: p.name.casefold())
        for child in children:
            # All direct directories are reviewed; names do not establish age.
            try:
                info = no_link(child)
                if not stat.S_ISDIR(info.st_mode):
                    continue
                relative = child.relative_to(repo).as_posix()
                row = load_run(repo, relative)
                try:
                    records = tree_snapshot(repo, relative)
                    row["tree"] = tree_summary(records)
                    blockers = [item["path"] for item in records if item["kind"] == "file" and (
                        item["links"] != 1 or item["attributes"] & READONLY or
                        item["path"].lower().endswith(("-wal", "-shm", ".lock", ".lck", ".pid")) or
                        Path(item["path"]).suffix.lower() in CODE_SUFFIXES or
                        any(part.lower() in ("src", "tests", "fixtures", "evidence", "resources", ".git")
                            for part in PurePosixPath(item["path"]).parts[4:]))]
                    if blockers:
                        row["reasons"].append("shared/active/evidence/source files: " + ", ".join(blockers))
                except (OSError, ValueError) as error:
                    row["tree"] = None
                    row["reasons"].append("tree: " + str(error))
                rows.append(row)
            except (OSError, ValueError) as error:
                rows.append(dict(path=child.relative_to(repo).as_posix(), run_id=None,
                                 created_utc=None, started_utc=None, finished_utc=None,
                                 persons=None, planned_trips=None, iterations=None, status=None,
                                 validation=None, manifest_sha256=None, manifest_valid=False,
                                 tree=None, age="unknown", classification="manual_review",
                                 reasons=["unsafe entry: " + str(error)], dependencies=[]))
    return rows


def owner(relative, rows):
    return next((row["path"] for row in rows
                 if relative == row["path"] or relative.startswith(row["path"] + "/")), None)


def reference_sources(repo, rows, *, locked_entries=None):
    """Enumerate bounded metadata, including historical catalogs; never silently waive evidence."""
    paths, problems = [], []

    def visit(folder):
        relative = folder.relative_to(repo).as_posix()
        if relative == "runtime/maintenance":
            return  # This tool's inventories/journals are not scientific consumers.
        try:
            with os.scandir(folder) as scan:
                children = sorted((Path(item.path) for item in scan), key=lambda p: p.name.casefold())
            for path in children:
                if path.name in SKIP_DIRS:
                    continue
                rel = path.relative_to(repo).as_posix()
                held = (locked_entries or {}).get(rel)
                if held is None:
                    info = no_link(path)
                    is_directory, size = stat.S_ISDIR(info.st_mode), info.st_size
                else:
                    # The caller retains native handles and validated these records;
                    # do not reopen exclusively locked deletion targets via lstat.
                    is_directory, size = held["kind"] == "dir", held["size"]
                if is_directory:
                    visit(path)
                elif path.suffix.lower() in TEXT_SUFFIXES:
                    source_owner = owner(rel, rows)
                    tail = rel[len(source_owner) + 1:] if source_owner else None
                    if tail == "plans.xml":
                        continue  # Native population payload; its provenance is in run-manifest.json.
                    if (tail and re.fullmatch(r"webgl/blocks/[0-9]{4,}\.html", tail) and
                            os.path.lexists(safe_path(repo, source_owner + "/webgl/export-manifest.json"))):
                        continue  # Known paged movement payload; inspect its export manifest instead.
                    if size > MAX_REFERENCE:
                        problems.append("reference too large/unreviewed: " + rel)
                    else:
                        paths.append(rel)
        except (OSError, ValueError) as error:
            problems.append("reference scan incomplete: " + str(error))

    visit(repo)
    return sorted(set(paths)), problems


def dependency_audit(repo, rows):
    paths, problems = reference_sources(repo, rows)
    tokens = {}
    for row in rows:
        tokens.setdefault(Path(row["path"]).name.casefold(), set()).add(row["path"])
        if isinstance(row["run_id"], str):
            tokens.setdefault(row["run_id"].casefold(), set()).add(row["path"])
    matcher = re.compile("|".join(re.escape(token) for token in sorted(tokens, key=len, reverse=True))) if tokens else None
    guards = []
    for path in paths:
        try:
            raw, record = read_bytes(repo, path, MAX_REFERENCE)
            guards.append(record)
            text = raw.decode("utf-8-sig")  # Unreadable provenance blocks automatic deletion.
            text = html.unescape(unquote(text)).casefold()
            if matcher is None:
                continue
            source_owner = owner(path, rows)
            targets = {target for match in matcher.finditer(text) for target in tokens[match.group(0)]}
            for row in rows:
                if row["path"] in targets and row["path"] != source_owner:
                    row["dependencies"].append(dict(source=path, source_run=source_owner,
                        kind="inventory_reference" if path.startswith("docs/maintenance/") else
                             "protected_run_reference" if source_owner == PROTECTED_PATH else
                             "external_reference"))
        except (OSError, ValueError, UnicodeError) as error:
            problems.append("reference unreadable: " + path + ": " + str(error))
    return guards, problems


def git_paths(repo):
    result = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"],
                            capture_output=True, check=False,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise SafetyError("Cannot inspect tracked files; no deletion permitted")
    return [relative_name(path.decode("utf-8")) for path in result.stdout.split(b"\0") if path]


def latest_snapshot(repo, rows):
    result, problems = [], []
    for root in ROOTS:
        for name in ("latest-successful.json", "latest-attempt.json"):
            path = root + "/" + name
            full = safe_path(repo, path)
            if not os.path.lexists(full):
                result.append(dict(path=path, exists=False))
                continue
            try:
                raw, record = read_bytes(repo, path)
                value = strict_json(raw)
                target = next((row for row in rows
                               if row["run_id"] == value.get("run_id") and
                               Path(os.path.abspath(value.get("folder", ""))) == repo / row["path"]), None)
                if target is None:
                    raise SafetyError("Unresolvable latest identity")
                if name == "latest-successful.json" and (
                        target["status"] != "completed" or target["validation"] != "valid" or
                        value.get("manifest_sha256") != target["manifest_sha256"]):
                    raise SafetyError("Invalid latest-successful hash/state")
                target["dependencies"].append(dict(source=path, kind="latest_reference", source_run=None))
                result.append(dict(path=path, exists=True, sha256=record["sha256"],
                                   target=target["path"], run_id=target["run_id"]))
            except (OSError, ValueError, TypeError) as error:
                problems.append("latest: " + path + ": " + str(error))
    return result, problems


def tool_hash():
    files = (Path(__file__), Path(__file__).with_name("_windows_purge.py"))
    repo = safe_root(Path(__file__).absolute().parents[2])
    return digest({path.name: read_bytes(repo, path.absolute().relative_to(repo).as_posix())[1]["sha256"]
                   for path in files})


def build_inventory(repo, *, tracked=None):
    repo = safe_root(repo)
    rows = discover_runs(repo)
    protected = next((row for row in rows if row["path"] == PROTECTED_PATH), None)
    if (protected is None or not protected["manifest_valid"] or
            protected["run_id"] != PROTECTED_ID or protected["persons"] != 100000 or
            protected["planned_trips"] != 100000 or protected["status"] != "completed" or
            protected["validation"] != "valid" or protected["tree"] is None):
        raise SafetyError("Protected 100k identity/metadata cannot be verified; stop")
    cutoff = timestamp(protected["started_utc"])
    duplicates = {key for key, count in Counter(row["run_id"] for row in rows if row["run_id"]).items() if count > 1}
    guards, problems = dependency_audit(repo, rows)
    latest, latest_problems = latest_snapshot(repo, rows)
    problems += latest_problems
    tracked = git_paths(repo) if tracked is None else tracked
    for row in rows:
        if row["run_id"] in duplicates:
            row["reasons"].append("duplicate run_id")
        tracked_inside = [path for path in tracked if path == row["path"] or path.startswith(row["path"] + "/")]
        if tracked_inside:
            row["reasons"].append("tracked files: " + ", ".join(tracked_inside))
        if row["path"] == PROTECTED_PATH or row["run_id"] == PROTECTED_ID:
            row["age"], row["classification"] = "protected_anchor", "protected"
            row["reasons"].append("absolute 100k protection by path OR identity")
        elif row["manifest_valid"]:
            started = timestamp(row["started_utc"])
            if started >= cutoff:
                row["age"], row["classification"] = "same_or_later", "protected"
                row["reasons"].append("execution starts at/after protected cutoff")
            else:
                row["age"] = "older"
                if timestamp(row["finished_utc"]) >= cutoff:
                    row["reasons"].append("execution overlaps protected cutoff")
                if row["dependencies"]:
                    row["reasons"].append("referenced evidence/resources; preserve pending manual review")
                if problems:
                    row["reasons"].append("incomplete global dependency/latest audit")
                if not row["reasons"]:
                    records = tree_snapshot(repo, row["path"], hashes=True)
                    if tree_summary(records) != row["tree"]:
                        raise SafetyError("Run changed during inventory: " + row["path"])
                    row["files"] = records
                    row["classification"] = "eligible"
                    row["reasons"].append("older terminal run; no detected dependency; subject to explicit approval")
        row["risk"] = ("protected; never deleted" if row["classification"] == "protected" else
                       "irreversible; exact regeneration not guaranteed; approve only after preserving unique evidence"
                       if row["classification"] == "eligible" else
                       "manual review required; automatic deletion forbidden")
    selected = [row for row in rows if row["classification"] == "eligible"]
    older = [row for row in rows if row["age"] == "older"]
    return dict(schema_version=1, policy=POLICY, repository=str(repo), tool_sha256=tool_hash(),
                generated_utc=datetime.now(timezone.utc).isoformat(),
                chronology_note="started_utc orders execution, not directory creation; user-authorized criterion",
                protected=dict(path=PROTECTED_PATH, run_id=PROTECTED_ID,
                               started_utc=protected["started_utc"],
                               manifest_sha256=protected["manifest_sha256"], tree=protected["tree"]),
                latest=latest, reference_guards=guards, audit_problems=problems, runs=rows,
                summary=dict(total_runs=len(rows), older_native_runs=len(older),
                             older_native_bytes=sum(row["tree"]["bytes"] for row in older if row["tree"]),
                             eligible_runs=len(selected),
                             recoverable_logical_bytes=sum(row["tree"]["bytes"] for row in selected),
                             protected_runs=sum(row["classification"] == "protected" for row in rows),
                             manual_review_runs=sum(row["classification"] == "manual_review" for row in rows)),
                limitations=["Logical bytes are not guaranteed free disk space (compression/sparse files).",
                             "References are conservative vetoes, including historical inventories.",
                             "No metadata is invented for legacy folders without a native manifest.",
                             "Apply rejects active runtimes/open files and can fail partially; no rollback.",
                             "The user must stop all writers during apply; directory handles do not seal new children.",
                             "Dependency scan excludes native plans.xml, compressed data and numbered WebGL block payloads; provenance is read from manifests.",
                             "Latest targets are pinned; references are never rewritten and there is no fallback."])


def inventory_input(repo, path, expected_sha):
    relative = Path(os.path.abspath(path)).relative_to(repo).as_posix()
    if not relative.startswith("runtime/maintenance/"):
        raise SafetyError("Reviewed inventory must be under runtime/maintenance/")
    raw, _ = read_bytes(repo, relative, 256 * 1024 * 1024)
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha or ""):
        raise SafetyError("An explicit --approve-sha256 is required")
    if hashlib.sha256(raw).hexdigest() != expected_sha.lower():
        raise SafetyError("Approved inventory hash differs")
    plan = strict_json(raw)
    if (plan.get("schema_version") != 1 or plan.get("policy") != POLICY or
            plan.get("repository") != str(repo) or plan.get("tool_sha256") != tool_hash() or
            plan.get("protected", {}).get("run_id") != PROTECTED_ID or
            plan.get("protected", {}).get("path") != PROTECTED_PATH):
        raise SafetyError("Inventory belongs to another policy/repository/tool/identity")
    return plan, relative


def selection(plan, run_ids):
    if not run_ids or len(set(run_ids)) != len(run_ids):
        raise SafetyError("Supply distinct explicit --run-id values from the reviewed inventory")
    selected = []
    for run_id in run_ids:
        matches = [row for row in plan["runs"] if row["run_id"] == run_id]
        if len(matches) != 1 or matches[0]["classification"] != "eligible":
            raise SafetyError("Run is not eligible in approved inventory: " + str(run_id))
        row = matches[0]
        relative_name(row["path"])
        if (row["path"] == PROTECTED_PATH or run_id == PROTECTED_ID or
                str(PurePosixPath(row["path"]).parent) not in ROOTS):
            raise SafetyError("Forbidden deletion target")
        records = row.get("files", [])
        if not records or len({item["path"].casefold() for item in records}) != len(records):
            raise SafetyError("Missing or colliding deletion inventory")
        for item in records:
            relative_name(item["path"])
            if item["path"] != row["path"] and not item["path"].startswith(row["path"] + "/"):
                raise SafetyError("Deletion inventory escapes the approved run")
        selected.append(row)
    return selected


def check_fresh(plan, current, run_ids):
    # No new selection, no silent rebase of approval, no stale dependencies.
    for key in ("policy", "repository", "tool_sha256", "protected", "latest",
                "reference_guards", "audit_problems", "runs"):
        if plan.get(key) != current.get(key):
            raise SafetyError("Inventory is stale (" + key + "); create and review a new dry-run")
    return selection(current, run_ids)


def no_active_runtimes(runtime_list):
    offenders = []
    for item in runtime_list:
        if item["pid"] == os.getpid():
            continue
        # Windows venv launcher is sometimes the immediate Python parent.
        same_launcher = (item["pid"] == os.getppid() and item.get("image") and
                         os.path.normcase(os.path.abspath(item["image"])) ==
                         os.path.normcase(os.path.abspath(sys.executable)))
        if not same_launcher:
            offenders.append(dict(pid=item["pid"], exe=item["exe"]))
    if offenders:
        raise SafetyError("Apply conservatively refuses other Java/Python/Node runtimes; close them manually: " +
                          json.dumps(offenders))


def locked_record_matches(before, current):
    # st_dev is not a Win32 volume serial on every Python release; retain the
    # native volume ID separately throughout apply, and compare file IDs/time/size.
    for key in ("kind", "file_id", "mtime_ns", "links"):
        if before[key] != current[key]:
            raise SafetyError("Locked file identity/metadata differs: " + before["path"])
    if before["kind"] == "file" and before["size"] != current["size"]:
        raise SafetyError("Locked file size differs: " + before["path"])


def locked_tree_membership(repo, records):
    """Check names only; file content/identity is checked through retained handles."""
    children = {item["path"]: set() for item in records if item["kind"] == "dir"}
    for item in records:
        parent = str(PurePosixPath(item["path"]).parent)
        if parent in children:
            children[parent].add(PurePosixPath(item["path"]).name)
    for relative, expected in children.items():
        with os.scandir(repo / relative) as scan:
            actual = {item.name for item in scan}
        if actual != expected:
            raise SafetyError("Directory membership changed after locks: " + relative)


def new_output(repo, path):
    full = Path(os.path.abspath(path))
    relative = full.relative_to(repo).as_posix()
    relative_name(relative)
    if not relative.startswith("runtime/maintenance/"):
        raise SafetyError("Inventory/journal must be a new file under runtime/maintenance/")
    safe_path(repo, relative)
    if os.path.lexists(full):
        raise SafetyError("Refusing to overwrite: " + relative)
    full.parent.mkdir(parents=True, exist_ok=True)
    safe_path(repo, relative)
    return full


def apply_plan(repo, plan, inventory_relative, run_ids, *, confirm, evidence_preserved,
               workspace_idle=False, approved_sha256=None):
    if confirm != CONFIRMATION or not evidence_preserved:
        raise SafetyError("Explicit confirmation and --evidence-preserved are required")
    if os.name != "nt":
        raise SafetyError("Apply is supported only by the Windows native-handle backend")
    if not workspace_idle:
        raise SafetyError("Close all writers and explicitly confirm --workspace-idle")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", approved_sha256 or ""):
        raise SafetyError("An explicit approved inventory SHA-256 is required")
    raw, _ = read_bytes(repo, inventory_relative, 256 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != approved_sha256.lower() or strict_json(raw) != plan:
        raise SafetyError("Inventory changed before preflight")
    from _windows_purge import WindowsLocks, running_runtimes
    selected = selection(plan, run_ids)
    no_active_runtimes(running_runtimes())
    current = build_inventory(repo)
    selected = check_fresh(plan, current, run_ids)
    targets = {record["path"]: record for row in selected for record in row["files"]}
    # Guards include all inspected references, the inventory and every ancestor.
    guard_paths = {item["path"] for item in plan["reference_guards"]}
    guard_paths.add(inventory_relative)
    all_paths = set(targets) | guard_paths
    for relative in list(all_paths):
        for parent in PurePosixPath(relative).parents:
            if str(parent) != ".":
                all_paths.add(parent.as_posix())
    if len(all_paths) + 1 > MAX_HANDLES:
        raise SafetyError("Too many handles; approve a smaller subset, never unsafe batches")
    journal_path = new_output(repo, repo / "runtime/maintenance" / ("purge-" + uuid.uuid4().hex + ".jsonl"))
    changed = False
    with journal_path.open("x", encoding="utf-8", newline="\n") as journal, WindowsLocks() as locks:
        def record(event, **fields):
            journal.write(json.dumps(dict(event=event, utc=datetime.now(timezone.utc).isoformat(),
                                          **fields), ensure_ascii=False, allow_nan=False) + "\n")
            journal.flush()
            os.fsync(journal.fileno())

        tokens = {}
        held_entries = {}
        record("preflight", inventory=inventory_relative, inventory_sha256=approved_sha256.lower(),
            run_ids=run_ids, targets=[row["path"] for row in selected])
        try:
            # Retain each ancestor before opening descendants; never resolve links.
            for ancestor in reversed((repo, *repo.parents)):
                no_link(ancestor)
                locks.open(ancestor, directory=True)
            for relative in sorted(all_paths, key=lambda item: (len(PurePosixPath(item).parts), item.casefold())):
                path = safe_path(repo, relative)
                before = stat_record(repo, path)
                token = locks.open(path, delete=relative in targets, directory=before["kind"] == "dir")
                tokens[relative] = token
                locked_record_matches(targets.get(relative, before), locks.describe(token))
                held_entries[relative] = before
            # Validate all hashes after every target/guard is locked, before first deletion.
            for relative, before in targets.items():
                token = tokens[relative]
                if before["kind"] == "file" and locks.sha256(token) != before["sha256"]:
                    raise SafetyError("Locked content differs: " + relative)
            for before in plan["reference_guards"]:
                if locks.sha256(tokens[before["path"]]) != before["sha256"]:
                    raise SafetyError("Reference changed after locks: " + before["path"])
            # Approval binds the exact bytes already parsed above. Do not reopen
            # held files: Python 3.10 lstat's sharing fallback can lose file IDs.
            if locks.sha256(tokens[inventory_relative]) != approved_sha256.lower():
                raise SafetyError("Inventory changed during preflight")
            for row in selected:
                locked_tree_membership(repo, row["files"])
            # Detect new references/entries after guard acquisition, without reopening
            # exclusive target files. Stable reference bytes have already been checked.
            source_paths, source_problems = reference_sources(repo, current["runs"], locked_entries=held_entries)
            if source_problems:
                raise SafetyError("Reference discovery became incomplete")
            if source_paths != [item["path"] for item in plan["reference_guards"]]:
                raise SafetyError("Reference set changed after locks")
            for ref in plan["latest"]:
                if not ref["exists"] and os.path.lexists(safe_path(repo, ref["path"])):
                    raise SafetyError("A latest reference appeared")
            tracked_now = git_paths(repo)
            if any(path == row["path"] or path.startswith(row["path"] + "/")
                   for path in tracked_now for row in selected):
                raise SafetyError("Approved run now contains tracked files")
            no_active_runtimes(running_runtimes())
            record("approved", run_ids=run_ids, files=sum(row["tree"]["files"] for row in selected),
                   logical_bytes=sum(row["tree"]["bytes"] for row in selected))
            # Only approved handles; never recursively delete by path or follow new entries.
            ordered = sorted(targets.values(), key=lambda item: (
                item["kind"] == "dir", -len(PurePosixPath(item["path"]).parts), item["path"]))
            for before in ordered:
                relative = before["path"]
                token = tokens[relative]
                if before["kind"] == "dir":
                    with os.scandir(safe_path(repo, relative)) as scan:
                        if next(scan, None) is not None:
                            raise SafetyError("Directory has new/unremoved children: " + relative)
                record("delete_intent", path=relative)
                # A disposition request may succeed even if closing its handle fails.
                # Once attempted, conservatively report a partial/uncertain outcome.
                changed = True
                locks.delete(token)
                record("deleted", path=relative)
            record("complete", run_ids=run_ids, latest="unchanged", protected=PROTECTED_ID)
        except BaseException as error:
            record("partial_or_uncertain" if changed else "aborted", error=str(error),
                   note="No rollback; inspect this journal before any new approval")
            raise
    return dict(status="complete", journal=str(journal_path), latest="unchanged")


def verify_plan(repo, plan, run_ids):
    chosen = selection(plan, run_ids)
    current = discover_runs(repo)
    protected = next((row for row in current if row["path"] == PROTECTED_PATH), None)
    if protected is None:
        raise SafetyError("Protected directory missing")
    for key in ("run_id", "started_utc", "manifest_sha256", "tree"):
        if protected[key] != plan["protected"][key]:
            raise SafetyError("Protected metadata changed: " + key)
    for row in chosen:
        if os.path.lexists(safe_path(repo, row["path"])):
            raise SafetyError("Approved target remains (possibly partial): " + row["path"])
    latest, problems = latest_snapshot(repo, current)
    if problems or latest != plan["latest"]:
        raise SafetyError("Latest references changed or invalid")
    before = {row["path"]: row for row in plan["runs"]}
    retained = set(before) - {row["path"] for row in chosen}
    missing = retained - {row["path"] for row in current}
    if missing:
        raise SafetyError("Unapproved retained runs are missing: " + ", ".join(sorted(missing)))
    for row in current:
        if row["path"] in before and row["tree"] != before[row["path"]]["tree"]:
            raise SafetyError("Retained run metadata changed: " + row["path"])
    return dict(status="verified", removed=[row["path"] for row in chosen],
                protected_metadata_unchanged=True, latest_unchanged=True,
                limitation="Metadata/file identity check; does not rehash the protected massive SQLite/events.")


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify", action="store_true")
    result.add_argument("--inventory", type=Path,
                        help="Dry-run: new JSON under runtime/maintenance; apply/verify: reviewed inventory")
    result.add_argument("--approve-sha256", help="Exact SHA-256 of reviewed inventory (apply/verify)")
    result.add_argument("--run-id", action="append", default=[], help="Explicit eligible run; repeat for each approval")
    result.add_argument("--confirm", help="Apply requires " + CONFIRMATION)
    result.add_argument("--evidence-preserved", action="store_true",
                        help="User confirms unique scientific evidence is preserved; never bypasses dependency vetoes")
    result.add_argument("--workspace-idle", action="store_true",
                        help="Apply only: user closed all writers, servers, simulations and editors that can write results")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    repo = Path(__file__).absolute().parents[2]
    try:
        repo = safe_root(repo)
        if args.apply or args.verify:
            if args.inventory is None:
                raise SafetyError("--inventory is required")
            plan, relative = inventory_input(repo, args.inventory, args.approve_sha256)
            output = (apply_plan(repo, plan, relative, args.run_id, confirm=args.confirm,
                                 evidence_preserved=args.evidence_preserved, workspace_idle=args.workspace_idle,
                                 approved_sha256=args.approve_sha256) if args.apply else
                      verify_plan(repo, plan, args.run_id))
        else:
            if args.approve_sha256 or args.run_id or args.confirm or args.evidence_preserved or args.workspace_idle:
                raise SafetyError("Approval options require --apply or --verify")
            output = build_inventory(repo)
            if args.inventory is not None:
                destination = new_output(repo, args.inventory)
                raw = json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8") + b"\n"
                with destination.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                output = dict(status="dry_run", inventory=str(destination),
                              inventory_sha256=hashlib.sha256(raw).hexdigest(), **output["summary"],
                              note="Review the full JSON; no deletion approved or performed.")
        print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("Purge refused: " + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

