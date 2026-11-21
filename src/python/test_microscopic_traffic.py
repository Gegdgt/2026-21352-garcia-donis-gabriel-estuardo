import gzip
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from microscopic_traffic import (
    GAP, MicroscopicPlayback, Operation, Profile, agent_profile,
    read_operations, replay_frames, position, speed_color, SPEED_COLORS, Sample,
    desired_speed, following_acceleration,
)
from traffic_routing import balanced_routes, routing_summary


def road(length=60, lanes=1, internal=False):
    return dict(length=length, lanes=lanes, freespeed=15, capacity=3600,
                internal=internal, **{"from": (0, 0), "to": (length, 0)})


class PlaybackTests(unittest.TestCase):
    def check_spacing(self, frames):
        for _, frame in frames:
            lanes = {}
            for agent, sample in frame.items():
                self.assertGreaterEqual(sample.speed, 0)
                for other in lanes.setdefault((sample.link, sample.lane), []):
                    self.assertGreaterEqual(abs(sample.distance - other.distance), GAP - 1e-7)
                lanes[sample.link, sample.lane].append(sample)

    def test_xml_fractional_activity_and_repeated_links(self):
        xml = '''<events>
        <event time="0.1" type="vehicle enters traffic" person="p" vehicle="v" link="a" relativePosition="0.25"/>
        <event time="2.1" type="left link" vehicle="v" link="a"/>
        <event time="2.1" type="entered link" vehicle="v" link="a"/>
        <event time="4.1" type="vehicle leaves traffic" person="p" vehicle="v" link="a" relativePosition="0.5"/>
        <event time="4.1" type="actstart" person="p" link="a" actType="parking"/>
        <event time="7.1" type="actend" person="p" link="a" actType="parking"/>
        </events>'''
        with tempfile.TemporaryDirectory() as tmp:
            for suffix in (".xml", ".xml.gz"):
                path = Path(tmp) / ("events" + suffix)
                if suffix.endswith("gz"):
                    with gzip.open(path, "wt") as f:
                        f.write(xml)
                else:
                    path.write_text(xml)
                routes = read_operations(path, {"a": road()})
                self.assertEqual(list(routes), ["p"])
                self.assertEqual(len(routes["p"]), 3)
                frames = list(replay_frames(routes, {"a": road()}, .2))
                parked = [(t, f["p"]) for t, f in frames if "p" in f and f["p"].state == "parking"]
                self.assertEqual(len(parked), 15)
                self.assertEqual({s.distance for _, s in parked}, {30})

    def test_parking_obstructs_lane_and_simultaneous_spawns_queue(self):
        routes = {"parked": [Operation("a", 0, 3, .5, .5, "parking")]}
        routes.update({f"f{i}": [Operation("a", 0, 8)] for i in range(5)})
        engine = MicroscopicPlayback(routes, {"a": road()}, synthetic_stops=False)
        frames = list(engine.frames())
        self.check_spacing(frames)
        parked = [f["parked"] for _, f in frames if "parked" in f]
        self.assertEqual(len(parked), 15)
        self.assertEqual({s.distance for s in parked}, {30})
        self.assertTrue(all(s.state == "parking" and s.speed == 0 for s in parked))
        self.assertEqual(engine.completed, 6)

    def test_downstream_blockage_spills_back(self):
        links = {"a": road(24), "b": road(24)}
        links["a"].update(from_id="n0", to_id="n1")
        links["b"].update(from_id="n1", to_id="n2")
        routes = {"parked": [Operation("b", 0, 20, 0, 0, "parking")],
                  "follower": [Operation("a", 0, 1, .5, 1), Operation("b", 1, 4)]}
        frames = list(MicroscopicPlayback(routes, links, synthetic_stops=False).frames())
        self.check_spacing(frames)
        retained = [s for t, f in frames if 10 <= t < 20 for a, s in f.items() if a == "follower"]
        self.assertTrue(retained)
        self.assertTrue(all(s.link == "a" and s.distance <= 24 - GAP for s in retained))

    def test_synthetic_stop_is_frozen_for_exactly_three_seconds(self):
        routes = {"p": [Operation("a", 0, 10)]}
        with patch("microscopic_traffic.agent_profile", return_value=Profile(1, 1)):
            engine = MicroscopicPlayback(routes, {"a": road(internal=True)})
            first = list(engine.frames())
            second = list(engine.frames())
        self.assertEqual(first, second)
        parked = [s for _, f in first for s in f.values() if s.state == "parking"]
        self.assertEqual(len(parked), 15)
        self.assertEqual({s.distance for s in parked}, {33})
        self.assertTrue(all(s.source == "synthetic" and s.speed == 0 for s in parked))
        self.assertAlmostEqual(engine.parking_log[0][2] - engine.parking_log[0][1], 3)

    def test_profiles_and_geometry(self):
        profiles = {agent_profile(str(i)) for i in range(100)}
        self.assertGreater(len(profiles), 2)
        self.assertTrue(all(0 < p.speed_factor <= 1 for p in profiles))
        link = road()
        self.assertNotEqual(position(link, 10, 0), position(link, 10, 1))

    def test_invalid_steps_and_incomplete_xml(self):
        for step in (0, float("nan"), .7, .17):
            with self.assertRaises(ValueError):
                MicroscopicPlayback({}, {}, dt=step)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.xml"
            path.write_text('<events><event time="0" type="entered link" vehicle="p" link="a"/></events>')
            with self.assertWarns(UserWarning):
                self.assertEqual(read_operations(path, {"a": road()}), {})

    def test_speed_color_boundaries(self):
        cases = [(0, 0), (.01, 1), (1, 1), (30, 1), (30.01, 2),
                 (31, 2), (60, 2), (60.01, 3), (100, 3), (100.01, 4),
                 (149.99, 4), (150, 4), (160, 4)]
        for kmh, index in cases:
            with self.subTest(kmh=kmh):
                self.assertEqual(speed_color(kmh / 3.6), SPEED_COLORS[index])
        for speed in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                speed_color(speed)

    def test_free_bypass_keeps_speed_at_geometry_nodes(self):
        links = {"a": road(1000), "b": road(50), "c": road(1000)}
        for i, (key, start, end) in enumerate((("a", 0, 1000), ("b", 1000, 1050), ("c", 1050, 2050))):
            links[key].update(freespeed=22.22, from_id=f"n{i}", to_id=f"n{i+1}")
            links[key]["from"], links[key]["to"] = (start, 0), (end, 0)
        routes = {"fast": [Operation("a", 0, 45), Operation("b", 45, 48), Operation("c", 48, 94)]}
        with patch("microscopic_traffic.agent_profile", return_value=Profile(1, 0)):
            frames = list(MicroscopicPlayback(routes, links, synthetic_stops=False).frames())
        samples = [f["fast"] for _, f in frames if "fast" in f]
        self.assertAlmostEqual(max(s.speed for s in samples), 22.22)
        self.assertTrue(all(s.speed > 20 for s in samples if s.link == "b"))
        self.assertTrue(all(s.speed <= links[s.link]["freespeed"] + 1e-8 for s in samples))
        self.assertEqual({speed_color(s.speed) for s in samples}, set(SPEED_COLORS[:4]))

    def test_renderer_refreshes_same_agent_including_parking(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.colors import to_rgba
        from visualize_network import render_agents
        fig, ax = plt.subplots()
        points = ax.scatter([], [])
        try:
            for speed, expected in ((22, 3), (10, 2), (1, 1), (0, 0), (1, 1), (22, 3)):
                state = "parking" if speed == 0 else "drive"
                frame = {"same_agent": Sample("a", 0, 30, speed, state)}
                render_agents(points, frame, {"a": road()})
                self.assertEqual(tuple(points.get_facecolors()[0]), to_rgba(SPEED_COLORS[expected]))
            render_agents(points, {}, {"a": road()})
            self.assertEqual(points.get_offsets().shape, (0, 2))
            fig.canvas.draw()
        finally:
            plt.close(fig)

    def test_extreme_blinks_each_frame_and_aggression_is_bypass_only(self):
        for kmh in (150, 151, 200):
            self.assertEqual([speed_color(kmh / 3.6, i) for i in range(4)],
                             ["#FF0000", "#FFFF00", "#FF0000", "#FFFF00"])
        self.assertEqual(speed_color(149 / 3.6, 1), "#FF0000")
        profile = Profile(.88, 0, 2.15)
        bypass = dict(road(4000), freespeed=22.22, is_bypass=True)
        self.assertGreater(desired_speed(profile, bypass) * 3.6, 150)
        self.assertLessEqual(desired_speed(profile, road()), road()["freespeed"])
        self.assertLess(desired_speed(profile, bypass, False), bypass["freespeed"])
        with patch("microscopic_traffic.agent_profile", return_value=profile):
            frames = list(MicroscopicPlayback({"p": [Operation("a", 0, 1)]}, {"a": bypass},
                                             synthetic_stops=False).frames())
        self.assertGreater(max(s.speed for _, f in frames for s in f.values()) * 3.6, 150)

    def test_fast_follower_slows_to_stop_then_recovers(self):
        link = dict(road(2000), freespeed=22.22)
        routes = {"parked": [Operation("a", 0, 140, .6, .6, "parking")],
                  "follower": [Operation("a", 0, 1)]}
        with patch("microscopic_traffic.agent_profile", return_value=Profile(1, 0)):
            frames = list(MicroscopicPlayback(routes, {"a": link}, synthetic_stops=False).frames())
        self.check_spacing(frames)
        samples = [(t, f["follower"]) for t, f in frames if "follower" in f]
        for begin, end in ((0, 140), (140, 250)):
            colors = {speed_color(s.speed) for t, s in samples if begin <= t < end}
            self.assertTrue(set(SPEED_COLORS[:4]).issubset(colors))
        self.assertLess(following_acceleration(20, 30, 5, 30), 0)
        self.assertGreater(following_acceleration(0, 30, 5, 30), 0)

    def test_balanced_routes_are_connected_reproducible_and_keep_od(self):
        # Bidirectional 3x3 grid with a central ring of alternate paths.
        links = {}
        for x in range(3):
            for y in range(3):
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    q = (x + dx, y + dy)
                    if all(0 <= z < 3 for z in q):
                        key = f"{x}{y}_{q[0]}{q[1]}"
                        links[key] = dict(road(100), from_id=f"{x}{y}", to_id=f"{q[0]}{q[1]}")
                        links[key]["from"], links[key]["to"] = (x * 100, y * 100), (q[0] * 100, q[1] * 100)
        routes = {str(i): [Operation("00_10", i, i+1), Operation("10_20", i+1, i+2),
                           Operation("10_20", i+2, i+5, 1, 1, "parking")] for i in range(20)}
        balanced = balanced_routes(routes, links)
        self.assertEqual(balanced, balanced_routes(routes, links))
        self.assertGreater(routing_summary(balanced, links)[0], routing_summary(routes, links)[0])
        for agent, ops in balanced.items():
            self.assertEqual(ops[0].link, routes[agent][0].link)
            self.assertEqual(ops[-2].link, routes[agent][-2].link)
            self.assertAlmostEqual(ops[-1].end - ops[-1].start, 3)
            for a, b in zip(ops, ops[1:]):
                if a.kind == b.kind == "drive":
                    self.assertEqual(links[a.link]["to_id"], links[b.link]["from_id"])
                    self.assertNotEqual(links[a.link]["from_id"], links[b.link]["to_id"])
                self.assertEqual(a.source, "synthetic-route")
        self.assertEqual(routes["0"][0].source, "XML")

    def test_header_and_legend_stay_outside_map_on_resize(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from visualize_network import create_traffic_figure
        fig, ax, text = create_traffic_figure("Lab 5", "Microscópico visual")
        try:
            ax.plot([0, 10], [0, 10])
            text.set_text("08:00:00\nEscala: 10x")
            for size in ((11, 11), (7, 8), (14, 7)):
                fig.set_size_inches(*size)
                fig.canvas.draw()
                renderer = fig.canvas.get_renderer()
                map_box = ax.get_window_extent(renderer)
                for label in fig.axes[0].texts:
                    self.assertFalse(label.get_window_extent(renderer).overlaps(map_box))
                legend_box = fig.axes[2].get_legend().get_window_extent(renderer)
                self.assertLess(legend_box.x1, map_box.x0)
                self.assertGreater(fig._traffic_panel.get_window_extent(renderer).x0, map_box.x1)
        finally:
            plt.close(fig)

    def test_telemetry_distance_elapsed_and_parking_average(self):
        links = {"a": road(100), "b": road(100)}
        routes = {"p": [Operation("a", 10, 15, .25, .75),
                        Operation("a", 15, 18, .75, .75, "parking"),
                        Operation("b", 18, 23)]}
        frames = list(MicroscopicPlayback(routes, links, synthetic_stops=False).frames())
        samples = [(t, f["p"]) for t, f in frames if "p" in f]
        for (t, sample) in samples:
            self.assertAlmostEqual(sample.elapsed_time, t - 10)
            self.assertEqual(sample.min_speed, 0)
            self.assertAlmostEqual(sample.mean_speed,
                                   sample.travelled_distance / sample.elapsed_time if t > 10 else 0)
        distances = [s.travelled_distance for _, s in samples]
        self.assertEqual(distances, sorted(distances))
        parked = [s for _, s in samples if s.state == "parking"]
        self.assertEqual(len(parked), 15)
        self.assertTrue(all(abs(s.travelled_distance - 50) < 1e-8 for s in parked))
        self.assertGreater(parked[0].mean_speed, parked[-1].mean_speed)
        replay = dict(replay_frames(routes, links, dt=1))
        self.assertAlmostEqual(replay[14]["p"].travelled_distance, 40)
        self.assertAlmostEqual(replay[17]["p"].mean_speed, 50 / 7)
        self.assertAlmostEqual(replay[20]["p"].travelled_distance, 90)
        self.assertEqual(replay[17]["p"].min_speed, 0)

    def test_queue_report_never_exceeds_available_displacement(self):
        links = {"a": dict(road(1000), freespeed=22.22)}
        routes = {"parked": [Operation("a", 10, 100, .23, .23, "parking")],
                  "fast": [Operation("a", 0, 1)]}
        with patch("microscopic_traffic.agent_profile", return_value=Profile(1, 0)):
            frames = list(MicroscopicPlayback(routes, links, synthetic_stops=False).frames())
        for _, frame in frames:
            if "parked" not in frame or "fast" not in frame:
                continue
            follower, leader = frame["fast"], frame["parked"]
            if follower.distance <= leader.distance:
                clearance = max(0, leader.distance - follower.distance - GAP)
                self.assertLessEqual(follower.speed * .2, clearance + 1e-8)
            if follower.state == "queued":
                self.assertEqual(speed_color(follower.speed), "#FFFFFF")
            if follower.state == "following":
                self.assertEqual(speed_color(follower.speed), "#FF6600")

    def test_hover_metrics_current_ids_idle_and_pixel_tolerance(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backend_bases import MouseEvent, Event
        from visualize_network import create_traffic_figure, AgentInspector, render_agents
        fig, ax, _ = create_traffic_figure("Lab 5", "Prueba")
        ax.set(xlim=(-10, 110), ylim=(-10, 100))
        points = ax.scatter([], [])
        inspector = AgentInspector(ax, points, fig._traffic_panel)
        links = {"a": road(100)}
        try:
            frame = {"another": Sample("a", 0, 10, 2, "drive"),
                     "agent_42": Sample("a", 0, 50, 5, "drive", "XML", 10, 100, 0)}
            render_agents(points, frame, links)
            inspector.update(10, frame)
            fig.canvas.draw()
            x, y = ax.transData.transform(position(links["a"], 50, 0))
            fig.canvas.callbacks.process("motion_notify_event", MouseEvent("motion_notify_event", fig.canvas, x+6, y))
            self.assertEqual(inspector.selected_id, "agent_42")
            self.assertIn("18.00 km/h", inspector.text.get_text())
            self.assertIn("36.00 km/h", inspector.text.get_text())
            # No new mouse event: update the hovered vehicle's statistics anyway.
            frame = {"agent_42": Sample("a", 0, 50, 0, "queued", "XML", 12, 100, 0)}
            render_agents(points, frame, links)
            inspector.update(12, frame)
            self.assertIn("30.00 km/h", inspector.text.get_text())
            self.assertIn("Velocidad actual\n0.00", inspector.text.get_text())
            # Moving away from the stationary cursor must clear the inspector.
            frame = {"agent_42": Sample("a", 0, 90, 5, "drive")}
            render_agents(points, frame, links)
            inspector.update(13, frame)
            self.assertIsNone(inspector.selected_id)
            self.assertEqual(inspector.text.get_text(), inspector.WAITING)
            # Recompute pixel proximity after a zoom, then handle figure exit.
            ax.set_xlim(0, 1000)
            fig.canvas.draw()
            x, y = ax.transData.transform(position(links["a"], 90, 0))
            fig.canvas.callbacks.process("motion_notify_event", MouseEvent("motion_notify_event", fig.canvas, x+5, y))
            self.assertEqual(inspector.selected_id, "agent_42")
            fig.canvas.callbacks.process("figure_leave_event", Event("figure_leave_event", fig.canvas))
            self.assertIsNone(inspector.selected_id)
            render_agents(points, {}, links)
            inspector.update(14, {})
            self.assertEqual(inspector.text.get_text(), inspector.WAITING)
            inspector.update(0, {})  # Animation repeat resets prior state.
            self.assertEqual(inspector.time, 0)
        finally:
            inspector.disconnect()
            plt.close(fig)


if __name__ == "__main__":
    unittest.main()
