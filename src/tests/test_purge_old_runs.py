"""Small purge safety contracts; isolated fixtures, no MATSim or real deletion.

Run explicitly with unittest or pytest. Loading this test file does not load the
maintenance tool; setUpClass loads it only when a user executes these tests.
"""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


TOOL_PATH = Path(__file__).resolve().parents[1] / "scripts/maintenance/purge_old_runs.py"
OLD_ID = "simz1-" + "1" * 32
OTHER_ID = "simz1-" + "2" * 32
CUTOFF = "2026-01-02T00:00:00+00:00"
OLD_START = "2026-01-01T00:00:00+00:00"
OLD_FINISH = "2026-01-01T01:00:00+00:00"
OLD_PATH = "scenarios/zona1/montecarlo/run-old"


class PurgeSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        name = "_simz1_purge_safety_test_tool"
        helper_directory = str(TOOL_PATH.parent)
        original_path = list(sys.path)
        cls.addClassCleanup(lambda: sys.path.__setitem__(slice(None), original_path))
        sys.path.insert(0, helper_directory)
        spec = importlib.util.spec_from_file_location(name, TOOL_PATH)
        cls.tool = importlib.util.module_from_spec(spec)
        sys.modules[name] = cls.tool
        cls.addClassCleanup(sys.modules.pop, name, None)
        spec.loader.exec_module(cls.tool)
        backend_name = "_simz1_purge_safety_test_windows_backend"
        backend_spec = importlib.util.spec_from_file_location(
            backend_name, TOOL_PATH.with_name("_windows_purge.py"))
        cls.backend = importlib.util.module_from_spec(backend_spec)
        sys.modules[backend_name] = cls.backend
        cls.addClassCleanup(sys.modules.pop, backend_name, None)
        backend_spec.loader.exec_module(cls.backend)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="simz1-purge-contract-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve() / "repository"
        self.repo.mkdir()
        # tracked=[] must prevent even a Git subprocess in fixture inventories.
        process_guard = patch.object(
            self.tool.subprocess, "run",
            side_effect=AssertionError("A purge unit test must not launch subprocesses"),
        )
        process_guard.start()
        self.addCleanup(process_guard.stop)
        native_guard = patch.object(
            self.backend, "_Api",
            side_effect=AssertionError("A purge unit test must not load the Windows API"),
        )
        native_guard.start()
        self.addCleanup(native_guard.stop)
        self.create_run(self.tool.PROTECTED_PATH, self.tool.PROTECTED_ID,
                        started=CUTOFF, finished="2026-01-02T01:00:00+00:00",
                        persons=100000)
        self.create_run(OLD_PATH, OLD_ID)

    def write_json(self, relative, value):
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
        path.write_bytes(raw)
        return path, raw

    def create_run(self, relative, run_id, *, started=OLD_START,
                   finished=OLD_FINISH, persons=1):
        directory = self.repo / relative
        directory.mkdir(parents=True)
        payload = b"ABCD"
        (directory / "data.bin").write_bytes(payload)
        manifest = dict(
            schema_version=1, run_id=run_id, folder=str(directory),
            created_utc=None, started_utc=started, finished_utc=finished,
            counts=dict(planned_persons=persons, planned_trips=persons),
            iterations=dict(first=0, last=0, requested=1, completed=[0]),
            status="completed", validation=dict(status="valid"), results={},
            inputs={"fixture": dict(path="data.bin", sha256=hashlib.sha256(payload).hexdigest())},
        )
        self.write_json(relative + "/run-manifest.json", manifest)
        return manifest

    def manifest(self, relative=OLD_PATH):
        return json.loads((self.repo / relative / "run-manifest.json").read_text(encoding="utf-8"))

    def change_manifest(self, relative=OLD_PATH, **changes):
        value = self.manifest(relative)
        value.update(changes)
        self.write_json(relative + "/run-manifest.json", value)

    def inventory(self, tracked=None):
        return self.tool.build_inventory(self.repo, tracked=[] if tracked is None else tracked)

    @staticmethod
    def row(plan, relative=OLD_PATH):
        return next(row for row in plan["runs"] if row["path"] == relative)

    def assert_manual(self, plan, relative=OLD_PATH, reason=None):
        row = self.row(plan, relative)
        self.assertEqual(row["classification"], "manual_review")
        if reason:
            self.assertIn(reason, " | ".join(row["reasons"]))
        self.assertNotIn("files", row)
        return row

    def write_inventory(self, plan):
        path, raw = self.write_json("runtime/maintenance/reviewed.json", plan)
        return path, hashlib.sha256(raw).hexdigest()

    def test_started_cutoff_distinguishes_old_equal_later_and_missing(self):
        equal = "scenarios/zona1/debug/run-equal"
        later = "scenarios/zona1/historical/run-later"
        missing = "scenarios/zona1/montecarlo/run-missing-time"
        self.create_run(equal, OTHER_ID, started=CUTOFF,
                        finished="2026-01-02T01:00:00Z")
        self.create_run(later, "simz1-" + "3" * 32,
                        started="2026-01-03T00:00:00Z", finished="2026-01-03T01:00:00Z")
        self.create_run(missing, "simz1-" + "4" * 32, started=None)
        # A misleading creation field must not replace the authorized started_utc.
        self.change_manifest(created_utc="2026-01-04T00:00:00Z")
        plan = self.inventory()
        self.assertEqual(self.row(plan)["classification"], "eligible")
        self.assertEqual(self.row(plan)["age"], "older")
        for relative in (equal, later):
            self.assertEqual(self.row(plan, relative)["classification"], "protected")
            self.assertEqual(self.row(plan, relative)["age"], "same_or_later")
        self.assert_manual(plan, missing, "timestamp")
        self.assertEqual(plan["summary"]["eligible_runs"], 1)
        self.assertEqual(plan["protected"]["started_utc"], CUTOFF)

    def test_timestamp_requires_timezone_and_normalizes_offset(self):
        self.assertEqual(self.tool.timestamp("2026-01-01T18:00:00-06:00"),
                         self.tool.timestamp(CUTOFF))
        for value in (None, 123, "", "not-a-date", "2026-01-01T00:00:00"):
            with self.subTest(value=value), self.assertRaises(self.tool.SafetyError):
                self.tool.timestamp(value)

    def test_overlap_or_nonterminal_run_is_manual(self):
        self.change_manifest(finished_utc=CUTOFF)
        self.assert_manual(self.inventory(), reason="overlaps")
        self.change_manifest(finished_utc=OLD_FINISH, status="running")
        self.assert_manual(self.inventory(), reason="Nonterminal")

    def test_protected_identity_change_stops_whole_inventory(self):
        self.change_manifest(self.tool.PROTECTED_PATH, run_id="simz1-" + "f" * 32)
        with self.assertRaisesRegex(self.tool.SafetyError, "Protected 100k"):
            self.inventory()

    def test_protected_counts_cannot_be_inferred_from_folder_name(self):
        self.change_manifest(self.tool.PROTECTED_PATH,
                             counts=dict(planned_persons=1, planned_trips=1))
        with self.assertRaisesRegex(self.tool.SafetyError, "Protected 100k"):
            self.inventory()

    def test_manifest_folder_mismatch_is_not_eligible(self):
        self.change_manifest(folder=str(self.repo / "unrelated"))
        self.assert_manual(self.inventory(), reason="folder does not match")

    def test_missing_manifest_stays_manual_without_filesystem_date_fallback(self):
        path = "scenarios/zona1/debug/run-20200101"
        (self.repo / path).mkdir(parents=True)
        (self.repo / path / "data.bin").write_bytes(b"legacy")
        row = self.assert_manual(self.inventory(), path, "manifest:")
        self.assertIsNone(row["started_utc"])
        self.assertEqual(row["age"], "unknown")

    def test_external_scientific_evidence_and_inventory_references_pin_old_run(self):
        self.write_json("evidence/reference.json", {"source": OLD_PATH, "run_id": OLD_ID})
        catalog = self.repo / "docs/maintenance/catalog.csv"
        catalog.parent.mkdir(parents=True)
        catalog.write_text('ruta_actual,clasificacion\n"' + OLD_PATH +
                           '/data.bin",evidencia\n', encoding="utf-8")
        row = self.assert_manual(self.inventory(), reason="referenced evidence")
        self.assertEqual({entry["source"] for entry in row["dependencies"]},
                         {"evidence/reference.json", "docs/maintenance/catalog.csv"})
        self.assertEqual({entry["kind"] for entry in row["dependencies"]},
                         {"external_reference", "inventory_reference"})

    def test_protected_replay_source_dependency_pins_candidate(self):
        source = self.tool.PROTECTED_PATH + "/webgl-continuo/continuous-manifest.json"
        self.write_json(source, {"source_directory": str(self.repo / OLD_PATH / "webgl")})
        row = self.assert_manual(self.inventory(), reason="referenced evidence")
        self.assertTrue(any(entry["source"] == source and
                            entry["kind"] == "protected_run_reference"
                            for entry in row["dependencies"]))

    def test_reports_inside_blocks_or_output_are_not_skipped(self):
        report = self.tool.PROTECTED_PATH + "/analysis/blocks/comparison.json"
        self.write_json(report, {"baseline": OLD_ID})
        csv = self.repo / self.tool.PROTECTED_PATH / "output/comparison.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        csv.write_text("baseline\n" + OLD_ID + "\n", encoding="utf-8")
        row = self.assert_manual(self.inventory(), reason="referenced evidence")
        sources = {entry["source"] for entry in row["dependencies"]}
        self.assertIn(report, sources)
        self.assertIn(csv.relative_to(self.repo).as_posix(), sources)

    def test_case_and_encoded_html_references_pin_candidate(self):
        source = self.repo / "evidence/reference.html"
        source.parent.mkdir()
        for reference in (OLD_PATH.upper(), OLD_PATH.upper().replace("-", "%2D"),
                          OLD_PATH.upper().replace("-", "&#45;")):
            source.write_text('<a href="' + reference + '/data.bin">Evidence</a>',
                              encoding="utf-8")
            with self.subTest(reference=reference):
                row = self.assert_manual(self.inventory(), reason="referenced evidence")
                self.assertTrue(any(item["source"] == "evidence/reference.html"
                                    for item in row["dependencies"]))

    def test_latest_successful_pins_exact_identity_and_hash(self):
        manifest_path = self.repo / OLD_PATH / "run-manifest.json"
        latest = dict(run_id=OLD_ID, folder=str(self.repo / OLD_PATH),
                      manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        self.write_json("scenarios/zona1/montecarlo/latest-successful.json", latest)
        plan = self.inventory()
        row = self.assert_manual(plan, reason="referenced evidence")
        self.assertTrue(any(item["kind"] == "latest_reference" for item in row["dependencies"]))
        self.assertFalse(plan["audit_problems"])
        latest["manifest_sha256"] = "0" * 64
        self.write_json("scenarios/zona1/montecarlo/latest-successful.json", latest)
        changed = self.inventory()
        self.assertTrue(any("Invalid latest-successful" in problem for problem in changed["audit_problems"]))
        self.assert_manual(changed)

    def test_duplicate_run_id_blocks_both_copies(self):
        other = "scenarios/zona1/debug/run-duplicate"
        self.create_run(other, OLD_ID)
        plan = self.inventory()
        self.assert_manual(plan, reason="duplicate run_id")
        self.assert_manual(plan, other, "duplicate run_id")

    def test_tracked_or_embedded_source_file_is_never_eligible(self):
        self.assert_manual(self.inventory(tracked=[OLD_PATH + "/data.bin"]), reason="tracked files")
        (self.repo / OLD_PATH / "source.py").write_text("# fixture, never executed\n", encoding="utf-8")
        self.assert_manual(self.inventory(), reason="source files")

    def test_same_size_same_mtime_payload_change_invalidates_approval(self):
        plan = self.inventory()
        payload = self.repo / OLD_PATH / "data.bin"
        original = payload.stat()
        payload.write_bytes(b"WXYZ")
        os.utime(payload, ns=(original.st_atime_ns, original.st_mtime_ns))
        current = self.inventory()
        self.assertEqual(self.row(plan)["tree"], self.row(current)["tree"])
        old_record = next(item for item in self.row(plan)["files"] if item["path"].endswith("/data.bin"))
        new_record = next(item for item in self.row(current)["files"] if item["path"].endswith("/data.bin"))
        self.assertNotEqual(old_record["sha256"], new_record["sha256"])
        with self.assertRaisesRegex(self.tool.SafetyError, "stale"):
            self.tool.check_fresh(plan, current, [OLD_ID])

    def test_new_reference_or_latest_after_review_invalidates_inventory(self):
        plan = self.inventory()
        self.write_json("evidence/new-reference.json", {"run_id": OLD_ID})
        with self.assertRaisesRegex(self.tool.SafetyError, "stale"):
            self.tool.check_fresh(plan, self.inventory(), [OLD_ID])
        # A latest-attempt reference has no manifest-hash requirement.
        self.write_json("scenarios/zona1/montecarlo/latest-attempt.json",
                        dict(run_id=OLD_ID, folder=str(self.repo / OLD_PATH)))
        current = self.inventory()
        self.assertTrue(any(item["exists"] for item in current["latest"]))
        with self.assertRaisesRegex(self.tool.SafetyError, "stale"):
            self.tool.check_fresh(plan, current, [OLD_ID])

    def test_symlink_is_not_followed_or_eligible_when_supported(self):
        outside = self.repo.parent / "outside.bin"
        outside.write_bytes(b"outside unchanged")
        link = self.repo / OLD_PATH / "linked.bin"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest("Symlink unavailable: " + str(error))
        row = self.assert_manual(self.inventory())
        self.assertIsNone(row["tree"])
        self.assertIn("Symlink/reparse", " | ".join(row["reasons"]))
        self.assertEqual(outside.read_bytes(), b"outside unchanged")

    def test_hardlinked_file_is_not_eligible_when_supported(self):
        outside = self.repo.parent / "shared.bin"
        outside.write_bytes(b"shared unchanged")
        try:
            os.link(outside, self.repo / OLD_PATH / "shared.bin")
        except (OSError, NotImplementedError) as error:
            self.skipTest("Hardlink unavailable: " + str(error))
        if outside.stat().st_nlink < 2:
            self.skipTest("Filesystem does not report hardlink count")
        self.assert_manual(self.inventory(), reason="shared/active")
        self.assertEqual(outside.read_bytes(), b"shared unchanged")

    def test_windows_readonly_file_is_not_eligible_when_supported(self):
        payload = self.repo / OLD_PATH / "data.bin"
        original_mode = payload.stat().st_mode
        try:
            payload.chmod(stat.S_IREAD)
            if not getattr(payload.stat(), "st_file_attributes", 0) & self.tool.READONLY:
                self.skipTest("Filesystem does not expose the Windows readonly attribute")
            self.assert_manual(self.inventory(), reason="shared/active")
        finally:
            payload.chmod(original_mode | stat.S_IWRITE)

    def test_relative_paths_reject_traversal_windows_aliases_and_roots(self):
        for relative in ("", "../outside", "/absolute", "C:/outside", "a\\b",
                         "a/../b", "a//b", "a/./b", "a/NUL.txt", "a/CON",
                         "a/name.", "a/name "):
            with self.subTest(path=relative), self.assertRaises(self.tool.SafetyError):
                self.tool.relative_name(relative)
        self.assertEqual(self.tool.relative_name(OLD_PATH), OLD_PATH)

    def test_selection_requires_explicit_unique_eligible_ids_and_safe_roots(self):
        plan = self.inventory()
        self.assertEqual([row["run_id"] for row in self.tool.selection(plan, [OLD_ID])], [OLD_ID])
        for ids in ([], [OLD_ID, OLD_ID], [OTHER_ID], [self.tool.PROTECTED_ID]):
            with self.subTest(ids=ids), self.assertRaises(self.tool.SafetyError):
                self.tool.selection(plan, ids)
        for relative in ("../outside", "other/run-old", self.tool.PROTECTED_PATH):
            forged = copy.deepcopy(plan)
            self.row(forged)["path"] = relative
            with self.subTest(path=relative), self.assertRaises(self.tool.SafetyError):
                self.tool.selection(forged, [OLD_ID])

    def test_selection_rejects_missing_colliding_or_external_file_records(self):
        plan = self.inventory()
        for relative in ("../outside.bin", self.tool.PROTECTED_PATH + "/data.bin",
                         OLD_PATH + "-sibling/data.bin", "evidence/source.json"):
            forged = copy.deepcopy(plan)
            self.row(forged)["files"][0]["path"] = relative
            with self.subTest(path=relative), self.assertRaises(self.tool.SafetyError):
                self.tool.selection(forged, [OLD_ID])
        for duplicate in (False, True):
            forged = copy.deepcopy(plan)
            records = self.row(forged)["files"]
            if duplicate:
                extra = copy.deepcopy(records[-1])
                extra["path"] = extra["path"].upper()
                records.append(extra)
            else:
                records.clear()
            with self.subTest(duplicate=duplicate), self.assertRaisesRegex(
                    self.tool.SafetyError, "Missing or colliding"):
                self.tool.selection(forged, [OLD_ID])

    def test_malformed_or_duplicate_key_manifest_is_manual(self):
        path = self.repo / OLD_PATH / "run-manifest.json"
        original = path.read_bytes()
        duplicate = original.replace(b'"schema_version":1',
                                     b'"schema_version":1,"schema_version":1')
        self.assertNotEqual(duplicate, original)
        for raw, reason in ((b'{"unfinished":', "manifest:"), (duplicate, "Duplicate JSON key")):
            path.write_bytes(raw)
            with self.subTest(reason=reason):
                self.assert_manual(self.inventory(), reason=reason)

    def test_inventory_requires_exact_approved_bytes_and_matching_policy(self):
        plan = self.inventory()
        path, approved_hash = self.write_inventory(plan)
        loaded, relative = self.tool.inventory_input(self.repo, path, approved_hash)
        self.assertEqual(loaded, plan)
        self.assertEqual(relative, "runtime/maintenance/reviewed.json")
        for invalid in (None, "", "bad", "0" * 64):
            with self.subTest(hash=invalid), self.assertRaises(self.tool.SafetyError):
                self.tool.inventory_input(self.repo, path, invalid)
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaisesRegex(self.tool.SafetyError, "hash differs"):
            self.tool.inventory_input(self.repo, path, approved_hash)
        changed = copy.deepcopy(plan)
        changed["policy"] = "unapproved-policy"
        path, changed_hash = self.write_inventory(changed)
        with self.assertRaisesRegex(self.tool.SafetyError, "another policy"):
            self.tool.inventory_input(self.repo, path, changed_hash)

    def test_inventory_duplicate_keys_are_rejected_even_with_matching_hash(self):
        plan = self.inventory()
        path, _ = self.write_inventory(plan)
        raw = path.read_bytes().replace(b'"schema_version":1',
                                       b'"schema_version":1,"schema_version":1', 1)
        path.write_bytes(raw)
        with self.assertRaisesRegex(self.tool.SafetyError, "Duplicate JSON key"):
            self.tool.inventory_input(self.repo, path, hashlib.sha256(raw).hexdigest())

    def test_inventory_file_must_be_inside_maintenance_directory(self):
        plan = self.inventory()
        path, raw = self.write_json("outside-maintenance.json", plan)
        with self.assertRaisesRegex(self.tool.SafetyError, "runtime/maintenance"):
            self.tool.inventory_input(self.repo, path, hashlib.sha256(raw).hexdigest())

    def test_fresh_inventory_does_not_depend_on_generation_timestamp(self):
        plan = self.inventory()
        current = copy.deepcopy(plan)
        current["generated_utc"] = "2026-01-04T00:00:00Z"
        chosen = self.tool.check_fresh(plan, current, [OLD_ID])
        self.assertEqual([row["path"] for row in chosen], [OLD_PATH])
        current["protected"]["manifest_sha256"] = "0" * 64
        with self.assertRaisesRegex(self.tool.SafetyError, "stale"):
            self.tool.check_fresh(plan, current, [OLD_ID])

    def test_verify_rejects_remaining_target_without_deleting_it(self):
        plan = self.inventory()
        payload = self.repo / OLD_PATH / "data.bin"
        before = payload.read_bytes()
        with self.assertRaisesRegex(self.tool.SafetyError, "target remains"):
            self.tool.verify_plan(self.repo, plan, [OLD_ID])
        self.assertEqual(payload.read_bytes(), before)

    def test_verify_can_inspect_mocked_absence_without_actual_removal(self):
        plan = self.inventory()
        retained = [row for row in plan["runs"] if row["path"] != OLD_PATH]
        actual_lexists = self.tool.os.path.lexists

        def mocked_lexists(path):
            return False if os.path.abspath(path) == str(self.repo / OLD_PATH) else actual_lexists(path)

        with patch.object(self.tool, "discover_runs", return_value=retained), \
                patch.object(self.tool.os.path, "lexists", side_effect=mocked_lexists):
            result = self.tool.verify_plan(self.repo, plan, [OLD_ID])
        self.assertEqual(result["status"], "verified")
        self.assertEqual(result["removed"], [OLD_PATH])
        self.assertTrue((self.repo / OLD_PATH / "data.bin").exists())

    def test_verify_rejects_mocked_disappearance_of_unapproved_retained_run(self):
        retained = "scenarios/zona1/debug/run-retained"
        self.create_run(retained, OTHER_ID, started=CUTOFF,
                        finished="2026-01-02T01:00:00Z")
        plan = self.inventory()
        current = [row for row in plan["runs"] if row["path"] not in (OLD_PATH, retained)]
        actual_lexists = self.tool.os.path.lexists

        def mocked_lexists(path):
            return False if os.path.abspath(path) == str(self.repo / OLD_PATH) else actual_lexists(path)

        with patch.object(self.tool, "discover_runs", return_value=current), \
                patch.object(self.tool.os.path, "lexists", side_effect=mocked_lexists):
            with self.assertRaisesRegex(self.tool.SafetyError, "retained runs are missing"):
                self.tool.verify_plan(self.repo, plan, [OLD_ID])
        self.assertTrue((self.repo / retained / "data.bin").exists())
        self.assertTrue((self.repo / OLD_PATH / "data.bin").exists())

    def test_non_windows_apply_refuses_before_backend_or_preflight(self):
        plan = self.inventory()
        with patch.object(self.tool.os, "name", "posix"), \
                patch.object(self.tool, "selection", side_effect=AssertionError("Selection reached apply")), \
                patch.object(self.tool, "build_inventory", side_effect=AssertionError("Apply preflight reached")):
            with self.assertRaisesRegex(self.tool.SafetyError, "Windows"):
                self.tool.apply_plan(self.repo, plan, "runtime/maintenance/reviewed.json", [OLD_ID],
                                     confirm=self.tool.CONFIRMATION, evidence_preserved=True)
        self.assertTrue((self.repo / OLD_PATH / "data.bin").exists())

    def test_apply_confirmation_guards_never_reach_backend(self):
        plan = self.inventory()
        for confirm, preserved in ((None, True), ("wrong", True), (self.tool.CONFIRMATION, False)):
            with self.subTest(confirm=confirm, preserved=preserved), \
                    self.assertRaisesRegex(self.tool.SafetyError, "confirmation"):
                self.tool.apply_plan(self.repo, plan, "runtime/maintenance/reviewed.json", [OLD_ID],
                                     confirm=confirm, evidence_preserved=preserved)
        self.assertFalse((self.repo / "runtime").exists())

    def test_apply_requires_idle_workspace_and_hash_before_backend_import(self):
        plan = self.inventory()
        # None makes any attempted backend import fail without loading native code.
        with patch.object(self.tool.os, "name", "nt"), \
                patch.dict(sys.modules, {"_windows_purge": None}):
            with self.assertRaisesRegex(self.tool.SafetyError, "workspace-idle"):
                self.tool.apply_plan(self.repo, plan, "runtime/maintenance/reviewed.json", [OLD_ID],
                                     confirm=self.tool.CONFIRMATION, evidence_preserved=True,
                                     workspace_idle=False, approved_sha256="a" * 64)
            with self.assertRaisesRegex(self.tool.SafetyError, "SHA-256"):
                self.tool.apply_plan(self.repo, plan, "runtime/maintenance/reviewed.json", [OLD_ID],
                                     confirm=self.tool.CONFIRMATION, evidence_preserved=True,
                                     workspace_idle=True, approved_sha256=None)
        self.assertFalse((self.repo / "runtime").exists())
        self.assertTrue((self.repo / OLD_PATH / "data.bin").exists())

    def test_mock_backend_guard_handle_cannot_request_deletion(self):
        locks = self.backend.WindowsLocks()
        locks._api = Mock()
        token = self.backend._Token(locks, 101, "fixture-only", False, False)
        with patch.object(locks, "describe", side_effect=AssertionError("Guard reached describe")):
            with self.assertRaisesRegex(self.backend.SafetyError, "guard handle"):
                locks.delete(token)
        locks._api.Disposition.assert_not_called()
        locks._api.Close.assert_not_called()
        self.assertFalse(token.delete_pending)

    def test_mock_backend_records_delete_pending_before_close_failure(self):
        locks = self.backend.WindowsLocks()
        locks._api = Mock()
        locks._api.Disposition.return_value = 1
        locks._api.Close.return_value = 0
        token = self.backend._Token(locks, 102, "fixture-only", True, False)
        with patch.object(locks, "describe", return_value={"kind": "file"}), \
                patch.object(self.backend, "_fail", side_effect=self.backend.SafetyError("mock close failed")):
            with self.assertRaisesRegex(self.backend.SafetyError, "mock close failed"):
                locks.delete(token)
        self.assertTrue(token.delete_pending)
        self.assertFalse(token.closed)
        locks._api.Disposition.assert_called_once()
        locks._api.Close.assert_called_once_with(102)

    def test_mock_backend_directory_kind_matches_inventory_contract(self):
        locks = self.backend.WindowsLocks()
        locks._api = Mock()
        locks._api.FileType.return_value = 1

        def provide_information(handle, pointer):
            self.assertEqual(handle, 103)
            info = self.backend.ctypes.cast(
                pointer, self.backend.ctypes.POINTER(self.backend._FileInformation)).contents
            info.attributes = self.backend._DIRECTORY
            info.links = 1
            info.index_low = 7
            info.volume = 2
            ticks = self.backend._EPOCH_100NS
            info.write.dwHighDateTime = ticks >> 32
            info.write.dwLowDateTime = ticks & 0xffffffff
            return 1

        locks._api.Information.side_effect = provide_information
        token = self.backend._Token(locks, 103, "fixture-only", False, True)
        current = locks.describe(token)
        self.assertEqual(current["kind"], "dir")
        before = dict(path=OLD_PATH, kind="dir", file_id=7, mtime_ns=0,
                      links=1, size=0, volume_id=2)
        self.tool.locked_record_matches(before, current)
        locks._api.Disposition.assert_not_called()
        locks._api.Close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
