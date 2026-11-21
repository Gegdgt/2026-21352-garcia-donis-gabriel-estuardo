"""Aggregate ledger provenance survives analysis and copied deliverables."""
from contextlib import redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

import simz1_analysis
import simz1_report_package as package
from simz1_occupancy_audit import report_summary
from simz1_run import MANIFEST, atomic_json, load_manifest
import test_simz1_analysis as analysis_fixtures
import test_simz1_report_package as package_fixtures
from test_simz1_occupancy_audit import completed_bus


class OccupancyReportingTests(unittest.TestCase):
    def test_analysis_exports_aggregate_counts_and_fingerprints_native_events(self):
        harness = analysis_fixtures.AnalysisLifecycleTests()
        harness.setUp(); self.addCleanup(harness.doCleanups)
        directory = harness.make_run()
        manifest = load_manifest(directory)
        ledger = completed_bus().summary()
        manifest['results']['0']['corridor_occupancy'] = ledger
        atomic_json(directory/MANIFEST, manifest)
        with patch('simz1_analysis.plot_profile_analysis', side_effect=analysis_fixtures.fixture_renderer):
            harness.analyze(directory)
        root = harness.analysis_folder(directory)
        report = json.loads((root/'graficas_perfiles/corridor_occupancy.json').read_text(encoding='utf-8'))
        analyzed = json.loads((root/'analysis-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(report['corridor_occupancy'], report_summary(ledger))
        self.assertNotIn('geometry', report['corridor_occupancy'])
        self.assertEqual(report['corridor_occupancy']['corridor_domains'], 2)
        self.assertFalse(report['corridor_occupancy']['continuous_positions_observed'])
        self.assertEqual(analyzed['sources']['corridor_occupancy_events'], manifest['results']['0']['events'])
        self.assertIn('graficas_perfiles/corridor_occupancy.json', {x['path'] for x in analyzed['artifacts']})

    def prepare_package(self):
        harness = package_fixtures.PackageTests()
        harness.setUp(); self.addCleanup(harness.doCleanups)
        ledger = completed_bus().summary()
        native = package.read_json(harness.run/MANIFEST)
        native['results'] = {'0': {'corridor_occupancy': ledger}}
        package_fixtures.save_json(harness.run/MANIFEST, native)
        harness.native_before = harness.snapshot_native()
        return harness, native, ledger

    def test_package_rejects_missing_occupancy_report_in_completed_run(self):
        harness, _, _ = self.prepare_package()
        with self.assertRaisesRegex(ValueError, 'resumen de ocupacion nativa'):
            package._source_files(harness.run, 0)

    def test_package_copies_exact_summary_and_rejects_refingerprinted_mismatched_counts(self):
        harness, native, ledger = self.prepare_package()
        proxy_path=harness.run/'inputs/stops.json'
        package_fixtures.save_json(proxy_path, [{'stop_id':'original-stop','proxy_placement':{'source_position':[1,2]}}])
        native['public_transport']={'stop_proxy_manifest':dict(path='inputs/stops.json',sha256=package.file_sha(proxy_path))}
        package_fixtures.save_json(harness.run/MANIFEST,native)
        harness.native_before=harness.snapshot_native()
        path = harness.source/'corridor_occupancy.json'
        record = dict(run_id=native['run_id'], iteration=0, corridor_occupancy=report_summary(ledger))
        package_fixtures.save_json(path, record)
        report_path = harness.analysis/'analysis-manifest.json'
        analysis = package.read_json(report_path)
        analysis['specification'] = dict(corridor_occupancy=report_summary(ledger))
        artifact = dict(path='graficas_perfiles/corridor_occupancy.json', size_bytes=path.stat().st_size,
                        sha256=package.file_sha(path))
        analysis['artifacts'].append(artifact)
        package_fixtures.save_json(report_path, analysis)
        status_path = harness.analysis/'analysis-status.json'
        status = package.read_json(status_path)
        status['manifest_sha256'] = package.file_sha(report_path)
        package_fixtures.save_json(status_path, status)
        with redirect_stdout(io.StringIO()):
            outcome = package.pack(harness.run)
        copied = harness.final()/'docs/corridor_occupancy.json'
        self.assertEqual(copied.read_bytes(), path.read_bytes())
        self.assertEqual((harness.final()/'docs/transit-stop-proxies.json').read_bytes(),proxy_path.read_bytes())
        self.assertEqual(outcome['status'], 'completed')
        record['corridor_occupancy']['vehicles_with_reservations'] += 1
        package_fixtures.save_json(path, record)
        artifact.update(size_bytes=path.stat().st_size, sha256=package.file_sha(path))
        package_fixtures.save_json(report_path, analysis)
        status['manifest_sha256'] = package.file_sha(report_path)
        package_fixtures.save_json(status_path, status)
        with self.assertRaisesRegex(ValueError, 'resumen de ocupacion nativa'):
            package._source_files(harness.run, 0)


if __name__ == '__main__': unittest.main()
