"""Integration checks on Lab05's exported XML; generate --iter 1 before running.

ZONA1_OUTPUT can select a different output directory.
"""
from collections import Counter, defaultdict
import gzip
import math
import os
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

OUTPUT = Path(os.environ.get("ZONA1_OUTPUT", str(
    Path(__file__).resolve().parents[1] / "output/labs/05-zona1")))


def read_xml(name):
    with gzip.open(OUTPUT / f"output_{name}.xml.gz", "rb") as stream:
        return ET.parse(stream).getroot()


class Zona1ExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (OUTPUT / "output_network.xml.gz").exists():
            raise unittest.SkipTest("Generate Lab05 --iter 1 first")
        cls.network = read_xml("network")
        cls.nodes = {n.get("id"): n for n in cls.network.findall("nodes/node")}
        cls.links = {l.get("id"): l for l in cls.network.findall("links/link")}

    def test_extent_directions_and_geometry(self):
        expected = {(a, c) for a in range(2, 12) for c in range(2, 16)}
        actual = set()
        for key, node in self.nodes.items():
            x, y = float(node.get("x")), float(node.get("y"))
            self.assertTrue(0 <= x <= 1084 and 0 <= y <= 1638)
            if not key.startswith("S_"):
                _, a, c = key.split("_")
                actual.add((int(a[1:]), int(c[1:])))
        self.assertEqual(actual, expected)
        self.assertEqual(len(self.nodes), 148)  # 140 crossings + 8 shape points
        self.assertEqual(len(self.links), 264)
        roads = defaultdict(list)
        pairs = {(l.get("from"), l.get("to")) for l in self.links.values()}
        for key, link in self.links.items():
            axis, cross, segment = key.split("_")
            roads[axis + "_" + cross].append(link)
            start, end = self.nodes[link.get("from")], self.nodes[link.get("to")]
            dx = float(end.get("x")) - float(start.get("x"))
            dy = float(end.get("y")) - float(start.get("y"))
            self.assertGreater((-dy if axis.startswith("A") else -dx)
                               * (1 if int(axis[1:]) % 2 == 0 else -1), 0)
            self.assertAlmostEqual(float(link.get("length")), math.hypot(dx, dy))
            self.assertNotIn((link.get("to"), link.get("from")), pairs)
            self.assertEqual(float(link.get("permlanes")), 1)
            main = axis in ("A6", "A7", "C9", "C12")
            self.assertAlmostEqual(float(link.get("freespeed")), (50 if main else 35) / 3.6)
            self.assertEqual(float(link.get("capacity")), 1500 if main else 800)
        self.assertEqual(len(roads), 256)

    def test_every_node_is_reachable_from_every_other_node(self):
        outgoing = defaultdict(list)
        incoming = defaultdict(list)
        for link in self.links.values():
            outgoing[link.get("from")].append(link.get("to"))
            incoming[link.get("to")].append(link.get("from"))
        for root in self.nodes:
            self.assertTrue(incoming[root])
            pending, visited = [root], set()
            while pending:
                current = pending.pop()
                if current in visited:
                    continue
                visited.add(current)
                pending.extend(outgoing[current])
            self.assertEqual(visited, set(self.nodes))

    def test_boundary_population_routes_and_arrivals(self):
        people = read_xml("plans").findall("person")
        self.assertEqual(len(people), 700)
        origins, destinations = Counter(), Counter()
        interior = set()
        for person in people:
            plan = person.find("plan[@selected='yes']")
            activities = plan.findall("activity")
            self.assertEqual([a.get("type") for a in activities], ["home", "parking", "work"])
            start = self.links[activities[0].get("link")]
            end = self.links[activities[-1].get("link")]
            origins[start.get("from")] += 1
            destinations[end.get("to")] += 1
            self.assertNotEqual(start.get("from"), end.get("to"))
            for route in plan.findall("leg/route"):
                sequence = (route.text or "").split()
                for left, right in zip(sequence, sequence[1:]):
                    self.assertEqual(self.links[left].get("to"), self.links[right].get("from"))
                interior.update(key for key in sequence if self.links[key].get("from").startswith("G_"))
        boundary = {key for key in self.nodes if key.startswith("B_")}
        self.assertEqual(len(boundary), 44)
        for counts in (origins, destinations):
            self.assertEqual(set(counts), boundary)
            self.assertTrue(all(15 <= count <= 16 for count in counts.values()))
        self.assertGreater(len(interior), 100)
        arrived, stuck = set(), []
        for event in read_xml("events").findall("event"):
            if event.get("type") == "actstart" and event.get("actType") == "work":
                arrived.add(event.get("person"))
            if event.get("type") == "stuckAndAbort":
                stuck.append(event.attrib)
        self.assertEqual(len(arrived), 700)
        self.assertFalse(stuck)

    def test_lane_connections_match_all_legal_exits(self):
        lanes = read_xml("lanes")
        # MATSim lanes v2 uses a default XML namespace.
        assignments = lanes.findall("{*}lanesToLinkAssignment")
        self.assertEqual(len(assignments), len(self.links))
        for assignment in assignments:
            link = self.links[assignment.get("linkIdRef")]
            actual = {e.get("refId") for e in assignment.findall(".//{*}toLink")}
            expected = {key for key, other in self.links.items() if other.get("from") == link.get("to")}
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
