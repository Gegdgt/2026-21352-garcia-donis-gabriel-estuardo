"""Checks against the ten-iteration Lab06 export (LAB06_OUTPUT overrides path)."""
from collections import Counter
import csv
import gzip
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from visualize_network import load_network, load_special_areas, draw_special_areas, load_points_of_interest

OUTPUT = Path(os.environ.get("LAB06_OUTPUT", str(Path(__file__).resolve().parents[1]
                                               / "output/labs/06-zona1")))


def xml(name):
    with gzip.open(OUTPUT / f"output_{name}.xml.gz", "rb") as stream:
        return ET.parse(stream).getroot()


class Lab06Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / "output_network.xml.gz").exists():
            raise unittest.SkipTest("Generate Lab06 first")
        cls.nodes, cls.links = load_network(OUTPUT / "output_network.xml.gz")

    def test_closures_extent_and_one_way(self):
        roads = {r["attributes"]["roadId"] for r in self.links.values()}
        for a in range(5, 9):
            self.assertNotIn(f"C7_A{a}", roads)
        for c in range(5, 8):
            self.assertNotIn(f"A7_C{c}", roads)
        self.assertNotIn("C13_A7", roads)
        self.assertNotIn("C14_A8", roads)
        for a in (2, 3, 4, 9, 10):
            self.assertIn(f"C7_A{a}", roads)
        for a in range(2, 5):
            self.assertIn(f"B_A{a}_C2", self.nodes)
        pairs = {(r["from_id"], r["to_id"]) for r in self.links.values()}
        attached = {n for pair in pairs for n in pair}
        self.assertEqual(attached, set(self.nodes))
        for x, y in self.nodes.values():
            self.assertTrue(0 <= x <= 1084 and 0 <= y <= 1638)
        for road in self.links.values():
            self.assertEqual(road["lanes"], 1)
            self.assertNotIn((road["to_id"], road["from_id"]), pairs)
            axis = road["attributes"]["roadId"].split("_")[0]
            if axis == "D":
                self.assertFalse(road["routing_eligible"])
                self.assertFalse(any(r["from_id"] == road["to_id"] for r in self.links.values()))
                continue
            delta = road["to"][1 if axis[0] == "A" else 0] - road["from"][1 if axis[0] == "A" else 0]
            self.assertGreater(delta * (-1 if int(axis[1:]) % 2 == 0 else 1), 0)
            kind = road["attributes"]["roadClass"]
            speed, capacity = {"hospital": (25, 400), "local": (30, 600), "principal": (45, 1200)}[kind]
            self.assertAlmostEqual(road["freespeed"] * 3.6, speed)
            self.assertEqual(road["capacity"], capacity)

    def test_all_iterations_and_final_arrivals(self):
        people = xml("plans").findall("person")
        expected_agents = int(xml("network").find("attributes/attribute[@name='dailyAgents']").text)
        for iteration in range(10):
            path = OUTPUT / "ITERS" / f"it.{iteration}" / f"{iteration}.events.xml.gz"
            self.assertTrue(path.is_file())
            arrived = set()
            with gzip.open(path, "rb") as stream:
                for _, event in ET.iterparse(stream):
                    if event.tag != "event":
                        continue
                    self.assertNotEqual(event.get("type"), "stuckAndAbort")
                    if event.get("type") == "actstart" and event.get("actType") == "work":
                        arrived.add(event.get("person"))
                    event.clear()
            self.assertEqual(len(arrived), expected_agents, f"iteration {iteration}")
        people = xml("plans").findall("person")
        self.assertEqual(len(people), expected_agents)
        for person in people:
            plan = person.find("plan[@selected='yes']")
            acts = plan.findall("activity")
            self.assertTrue(self.links[acts[0].get("link")]["from_id"].startswith("B_"))
            self.assertTrue(self.links[acts[-1].get("link")]["to_id"].startswith("B_"))
            for route in plan.findall("leg/route"):
                keys = (route.text or "").split()
                self.assertTrue(all(self.links[key]["routing_eligible"] for key in keys))
                for first, second in zip(keys, keys[1:]):
                    self.assertEqual(self.links[first]["to_id"], self.links[second]["from_id"])

    def test_visual_polygons(self):
        areas = load_special_areas(OUTPUT / "output_network.xml.gz")
        self.assertEqual({a["kind"] for a in areas}, {"green", "institutional"})
        points = load_points_of_interest(OUTPUT / "output_network.xml.gz")
        self.assertEqual({p["kind"] for p in points}, {"hospital", "institutional"})
        fig, ax = plt.subplots()
        try:
            draw_special_areas(ax, areas)
            self.assertEqual(len(ax.patches), 3)
            self.assertTrue(all(p.get_alpha() == .25 for p in ax.patches))
            fig.canvas.draw()
        finally:
            plt.close(fig)

    def test_daily_demand_export(self):
        with (OUTPUT / "output_demand.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(len(rows), 48)
        totals = [int(r['generated_trips']) for r in rows]
        expected = int(xml('network').find("attributes/attribute[@name='dailyAgents']").text)
        self.assertEqual(sum(totals), expected)
        # Check the default scenario's intended peaks, without asserting random exact counts.
        morning = sum(totals[9:17]) / 4
        evening = sum(totals[32:40]) / 4
        midday = sum(totals[19:30]) / 5.5
        night = sum(totals[:8]) / 4
        self.assertGreater(morning, 3 * midday)
        self.assertGreater(evening, 3 * midday)
        self.assertGreater(midday, 5 * night)


if __name__ == "__main__":
    unittest.main()
