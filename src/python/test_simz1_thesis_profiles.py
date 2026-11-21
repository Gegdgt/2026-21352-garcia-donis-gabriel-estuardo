"""Profile presentation fixtures: exact data, missingness and conservation."""
import copy
import csv
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

from simz1_trip_distributions import profile_statistics
from simz1_trip_table import COLUMNS, UNIT
from simz1_thesis_profiles import (PROFILE_ORDER, PROFILE_COLORS, FAMILY_COLORS,
                                  validate_profile_report, distribution_data, render_profiles)


class CapturePublisher:
    def __init__(self, destination=None):
        self.destination = destination
        self.results = {}

    def save(self, fig, stem, rows, metadata):
        if stem in self.results:
            plt.close(fig)
            raise FileExistsError("Gráfica repetida")
        json.dumps(dict(rows=rows, metadata=metadata), ensure_ascii=False, allow_nan=False)
        self.results[stem] = dict(rows=rows, metadata=metadata, axes=fig.axes,
                                  titles=[text.get_text() for text in fig.texts])
        if self.destination:
            for suffix in ("png", "svg"):
                target = self.destination / f"{stem}.{suffix}"
                if target.exists():
                    raise FileExistsError(target)
                fig.savefig(target, dpi=90)
        plt.close(fig)


class ThesisProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="simz1-thesis-profile-tests-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.table = self.root / "trips.csv.gz"
        self.identity = dict(run_id="fixture-profile", iteration=3, N_configured=13751,
                             publication_status="official")
        self.metadata = {}
        records = []
        trips = (("Normal", 3601, 60, "completed"), ("Normal", 3610, 180, "completed"),
                 ("Tortuga", 3620, 600, "completed"), ("Liebre", 7201, None, "censored"),
                 ("Motociclista", 0, 120, "completed"), ("MotocicletaLenta", 86000, None, "aborted"))
        for i, (profile, departure, duration, status) in enumerate(trips):
            person = f"p{i}"
            family = "carro" if profile in PROFILE_ORDER[:3] else "moto"
            self.metadata[person] = dict(effective_vehicle_type=profile, family=family, monte_carlo_eligible=True)
            records.append(dict(run_id=self.identity["run_id"], iteration=self.identity["iteration"],
                person_id=person, vehicle_id=person, trip_index=1, mode="car", profile=profile,
                departure=departure, arrival=departure + duration if duration is not None else None,
                duration_seconds=duration, status=status, abort=86300 if status == "aborted" else None,
                departure_link="a", arrival_link="b" if status == "completed" else None,
                unit=UNIT, vehicle_ids=json.dumps([person])))
        self.write_rows(records)
        self.report = profile_statistics(self.table, self.metadata, self.identity["run_id"], self.identity["iteration"])
        self.report["distribution"].pop("values_minutes")
        self.bundle = dict(identity=self.identity, profile_report=self.report, trips_path=self.table)

    def write_rows(self, records):
        with gzip.open(self.table, "wt", encoding="utf8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(records)

    def test_distribution_counts_exact_quantiles_and_bounded_bins(self):
        bins, stats = distribution_data(self.bundle)
        self.assertEqual(stats["n_complete"], 4)
        self.assertEqual(stats["n_excluded"], 2)
        self.assertEqual(stats["n_rows_read"], 6)
        self.assertEqual(stats["median_minutes"], 2.5)
        self.assertAlmostEqual(stats["p95_minutes"], 8.95)
        self.assertEqual(sum(row["count"] for row in bins), 4)
        self.assertEqual(bins[-1]["cumulative_fraction"], 1)
        self.assertLessEqual(len(bins), 60)
        self.assertEqual(bins[0]["left_minutes"], 0)
        self.assertEqual(bins[-1]["right_minutes"], 10)
        json.dumps(bins, allow_nan=False)

    def test_no_zero_duration_for_empty_hours_or_incomplete_profiles(self):
        publisher = CapturePublisher()
        render_profiles(self.bundle, publisher)
        car = publisher.results["carros_por_hora"]
        empty = next(r for r in car["rows"] if r["group"] == "Normal" and r["hour"] == 0)
        incomplete = next(r for r in car["rows"] if r["group"] == "Liebre" and r["hour"] == 2)
        self.assertIsNone(empty["mean_minutes"])
        self.assertIsNone(incomplete["mean_minutes"])
        self.assertEqual(incomplete["n_censored"], 1)
        self.assertTrue(np.isnan(car["axes"][1].lines[0].get_ydata()[0]))
        self.assertEqual(car["axes"][0].get_ylim()[0], 0)
        self.assertEqual(len(car["axes"][-1].get_xticks()), 24)

    def test_family_statistics_are_pooled_and_preserved_exactly(self):
        publisher = CapturePublisher()
        render_profiles(self.bundle, publisher)
        family = publisher.results["comparacion_familias_por_hora"]
        row = next(r for r in family["rows"] if r["group"] == "Carro" and r["hour"] == 1)
        self.assertAlmostEqual(row["mean_minutes"], 14 / 3)
        self.assertNotEqual(row["mean_minutes"], (2 + 10) / 2)
        self.assertEqual(row["n_complete"], 3)
        self.assertIn("13751".replace("13751", "13,751"), " ".join(family["titles"]))

    def test_identity_rejected_before_any_figures(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["identity"]["run_id"] = "wrong"
        publisher = CapturePublisher()
        with self.assertRaisesRegex(ValueError, "corrida"):
            render_profiles(bundle, publisher)
        self.assertFalse(publisher.results)

    def test_duplicate_report_rows_and_nonfinite_data_rejected(self):
        report = copy.deepcopy(self.report)
        report["profile_hour"].append(report["profile_hour"][0])
        with self.assertRaisesRegex(ValueError, "repetida"):
            validate_profile_report(report, self.identity)
        report = copy.deepcopy(self.report)
        report["profiles"][0]["mean_minutes"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finito"):
            validate_profile_report(report, self.identity)

    def test_inconsistent_completeness_denominator_rejected(self):
        report = copy.deepcopy(self.report)
        report["profiles"][0]["n_total"] += 1
        with self.assertRaisesRegex(ValueError, "Denominador"):
            validate_profile_report(report, self.identity)

    def test_trip_identity_and_summary_mutation_rejected(self):
        bundle = copy.deepcopy(self.bundle)
        bundle["identity"]["iteration"] = 4
        with self.assertRaisesRegex(ValueError, "corrida"):
            distribution_data(bundle)
        bundle = copy.deepcopy(self.bundle)
        bundle["profile_report"]["profiles"][0]["mean_minutes"] += 1
        with self.assertRaisesRegex(ValueError, "incompatible"):
            distribution_data(bundle)

    def test_missing_table_and_unrecognized_filter_are_pending(self):
        bundle = dict(self.bundle, trips_path=None)
        publisher = CapturePublisher()
        result = render_profiles(bundle, publisher)
        self.assertEqual(len(result["figures"]), 5)
        self.assertEqual(len(result["pending"]), 1)
        self.assertNotIn("duration_distribution", publisher.results)
        bundle = copy.deepcopy(self.bundle)
        bundle["profile_report"]["filters"]["cohort_hour_basis"] = "unknown criterion"
        with self.assertRaisesRegex(FileNotFoundError, "temporal"):
            distribution_data(bundle)

    def test_png_svg_generated_without_source_changes(self):
        before = hashlib.sha256(self.table.read_bytes()).hexdigest()
        publisher = CapturePublisher(self.root)
        result = render_profiles(self.bundle, publisher)
        self.assertEqual(len(result["figures"]), 6)
        self.assertFalse(result["pending"])
        for stem in result["figures"]:
            with Image.open(self.root / f"{stem}.png") as image:
                self.assertGreater(image.width, 1000)
                self.assertGreater(image.height, 400)
            self.assertIn("<svg", (self.root / f"{stem}.svg").read_text(encoding="utf8"))
        self.assertEqual(hashlib.sha256(self.table.read_bytes()).hexdigest(), before)
        with self.assertRaises(FileExistsError):
            render_profiles(self.bundle, publisher)
        self.assertEqual(PROFILE_COLORS["Normal"], FAMILY_COLORS["Carro"])
        self.assertEqual(PROFILE_COLORS["Motociclista"], FAMILY_COLORS["Moto"])


if __name__ == "__main__":
    unittest.main()
