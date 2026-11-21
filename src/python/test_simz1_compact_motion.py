"""Generated compact-freight XML through occupancy inputs, motion and SQLite; no MATSim."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from generate_montecarlo_z1 import generar, SCENARIO
from simz1_motion import load_selected
from simz1_occupancy_audit import load_inputs
from simz1_paged_replay import SqliteTrajectorySink, unpacked, windows
from simz1_run import artifact, parameters
from simz1_trajectories import extract


class CompactMotionTests(unittest.TestCase):
    def test_generated_compact_body_survives_motion_audit_and_sqlite_with_public_fleet_unchanged(self):
        with tempfile.TemporaryDirectory(prefix='simz1-compact-motion-') as folder, redirect_stdout(io.StringIO()):
            run = Path(folder)/'run'
            generar(SCENARIO/'config-simz1.xml', run, 20261030, agents=100, mode='montecarlo',
                corridor_policy='redistribute', origin_policy='uniform-nodes-v1', destination_policy='lane-length-destinations-v1',
                agent_catalog=SCENARIO/'agent-types-balanced-v1.json', storage_policy='strict-receiver-v1',
                transit_service=SCENARIO/'transit/weekday-v2/service-fleet-176-93-v1.json',
                transit_service_date='2026-10-23', accept_transit_route_assumptions=True,
                freight_service=SCENARIO/'freight/weekday-compact-v3/service-composition-v3.json',
                freight_service_date='2026-10-23')
            manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
            # The fixture supplies an explicit selected XML artifact. It does
            # not claim a completed native run or create a native result file.
            manifest['effective_config'] = artifact(run, run/'config-simz1.xml')
            manifest['effective_vehicles'] = artifact(run, run/'inputs/vehicles.xml')
            manifest['results'] = {'0': {'plans': artifact(run, run/'plans.xml')}}
            configured = parameters(run/'config-simz1.xml')
            network = (run/configured['network.inputNetworkFile']).resolve()
            lanes = (run/configured['network.laneDefinitionsFile']).resolve()
            manifest['effective_lane_configuration_validation'] = dict(loaded_artifacts=dict(lanes=artifact(run, lanes)))
            selection = dict(directory=run, manifest=manifest, iteration=0, plans=run/'plans.xml', network=network)
            motion = load_selected(selection)
            truck = manifest['freight_transport']['fleet_vehicle_ids'][0]
            metadata = motion.metadata(truck, truck)
            for field in ('Vehicle_Dimensions', 'Vehicle_Physical_Dimensions'):
                self.assertEqual((metadata[field]['length_m'], metadata[field]['width_m']), (8., 2.3))
            self.assertEqual(metadata['Vehicle_PCU'], 3.5)
            native_hash = manifest['effective_vehicles']['sha256']
            self.assertEqual(metadata['Vehicle_Physical_Dimensions']['provenance']['artifact_sha256'], native_hash)
            buses = [v for v,t in motion.vehicle_types.items() if t == 'TuBus_RigidProxy']
            self.assertEqual(len(buses), 93)
            self.assertTrue(all(motion.vehicle_dimensions[v]['length_m'] == 12 and
                                motion.vehicle_dimensions[v]['width_m'] == 2.5 for v in buses))
            self.assertEqual(sum(t == 'Transmetro_RigidProxy' for t in motion.vehicle_types.values()), 176)
            _, bodies = load_inputs(network, [run/'inputs/vehicles.xml'])
            self.assertEqual((bodies[truck]['length_m'], bodies[truck]['width_m'], bodies[truck]['pcu']), (8., 2.3, 3.5))

            # Synthetic one-link event fixture verifies serialization only;
            # it is not offered as evidence of route completion in Zona 1.
            roster=motion.freight_contract[truck]
            link=roster['link_ids'][0];departure=roster['departure_seconds']
            # The geometric segment stays synthetic, while actor/link/time
            # identity is the exact verified roster consumed by the replay.
            links = {link: dict(length=100, freespeed=10, from_node='a', to_node='b',
                              **{'from': [0,0], 'to': [.001,0]})}
            events = [dict(type='departure', time=str(departure), person=truck, link=link),
                      dict(type='vehicle enters traffic', time=str(departure), person=truck, vehicle=truck, link=link, relativePosition='0'),
                      dict(type='vehicle leaves traffic', time=str(departure+20), person=truck, vehicle=truck, link=link, relativePosition='1'),
                      dict(type='arrival', time=str(departure+20), person=truck, link=link)]
            for mismatch in ({'link':'wrong-native-link'},{'time':str(departure+3601)}):
                with self.assertRaisesRegex(ValueError,'Freight replay departure differs'):
                    extract([dict(events[0],**mismatch),*events[1:]],links,lambda _:True,lambda _:[1,2,3],
                        SimpleNamespace(inv=lambda *args:(0,0,100)),motion=motion,horizon=departure+100)
            sink = SqliteTrajectorySink(run/'fixture.sqlite', windows(departure,departure+100,10))
            try:
                extract(events, links, lambda _:True, lambda _:[1,2,3],
                    SimpleNamespace(inv=lambda *args:(0,0,100)), motion=motion, segment_sink=sink, horizon=departure+100)
                payload = unpacked(sink.connection.execute('SELECT payload FROM segments LIMIT 1').fetchone()[0])
                for field in ('Vehicle_Dimensions', 'Vehicle_Physical_Dimensions'):
                    self.assertEqual(payload[field], metadata[field])
            finally:
                sink.close()


if __name__ == '__main__':
    unittest.main()
