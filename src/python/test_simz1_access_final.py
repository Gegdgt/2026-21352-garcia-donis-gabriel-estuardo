"""Small contract fixtures + static checks of the isolated access revision. No QSim."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_balanced_od import BalancedGatewayModel, IncorporationBudget, load_model, digest
from simz1_od_policy import GatewayBudget, validate_osm_turns
from simz1_osm_turn_audit import load_xml, load_lanes
from test_simz1_balanced_gateway_od import fixture, record

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scenarios/zona1/od/balanced-gateway-v1'
COPY=OUT/'access-review-v2'


class BoundaryFlowTests(unittest.TestCase):
    def boundary_fixture(self):
        base,doc,ends,moves=fixture()
        for role in ('entry','exit'):
            row=doc[role+'_gateways'][0]
            row.update(flow_role='boundary_'+role,activity_allowed=None,incorporation_capacity_pcu_h=None,
                       **{role+'_capacity_pcu_h':2.})
        return base,doc,ends,moves

    def test_boundary_sources_and_sinks_do_not_require_activity_permission(self):
        graph=BalancedGatewayModel(*self.boundary_fixture())
        budget=IncorporationBudget(graph)
        row=record()
        self.assertTrue(budget.accept(row,7,1.))
        self.assertTrue(budget.accept(row,7,1.))
        self.assertFalse(budget.accept(row,7,.25))
        self.assertEqual(budget.used[7,'anchor-in'],2.)

    def test_exit_budget_is_separate_and_rejection_does_not_consume_entry(self):
        base,doc,ends,moves=self.boundary_fixture()
        doc['exit_gateways'][0]['exit_capacity_pcu_h']=.5
        budget=IncorporationBudget(BalancedGatewayModel(base,doc,ends,moves))
        self.assertFalse(budget.accept(record(),7,1.))
        self.assertEqual(budget.used[7,'anchor-in'],0.)
        self.assertEqual(dict(budget.gateway.used),{})
        self.assertEqual(budget.rejected['exit_cohort_capacity'],1)

    def test_missing_boundary_budget_cannot_fall_back_to_incorporation(self):
        base,doc,ends,moves=self.boundary_fixture()
        doc['exit_gateways'][0].pop('exit_capacity_pcu_h')
        doc['exit_gateways'][0]['incorporation_capacity_pcu_h']=2.
        with self.assertRaisesRegex(ValueError,'boundary storage/flow'):
            BalancedGatewayModel(base,doc,ends,moves)

    def test_same_crossing_with_another_id_cannot_duplicate_budget(self):
        base,doc,ends,moves=self.boundary_fixture()
        duplicate=copy.deepcopy(doc['entry_gateways'][0]); duplicate['id']='other-id'
        doc['entry_gateways'].append(duplicate)
        with self.assertRaisesRegex(ValueError,'Duplicate physical gateway crossing'):
            BalancedGatewayModel(base,doc,ends,moves)

    def test_chain_bottleneck_and_native_queue_storage_are_limits(self):
        for case in ('flow','storage'):
            base,doc,ends,moves=self.boundary_fixture()
            if case=='flow': base.links['cross-in']['capacity']=1.
            else: ends['anchor-in']=1.
            with self.subTest(case=case),self.assertRaises(ValueError):
                BalancedGatewayModel(base,doc,ends,moves)

    def test_internal_sites_still_require_explicit_model_eligibility(self):
        base,doc,ends,moves=self.boundary_fixture()
        doc['internal_origins'][0]['activity_allowed']=None
        with self.assertRaisesRegex(ValueError,'activity access'):
            BalancedGatewayModel(base,doc,ends,moves)

    def test_common_chain_links_share_one_budget(self):
        graph=BalancedGatewayModel(*self.boundary_fixture())
        graph.links['observe-in']['capacity']=1.
        budget=GatewayBudget(graph)
        self.assertIn('observe-in',budget.resources(record()))
        self.assertTrue(budget.accept(record(),7,1))
        self.assertFalse(budget.accept(record(),7,.25))
        self.assertEqual(budget.used[7,'observe-in'],1)


class IsolatedEvidenceTests(unittest.TestCase):
    def test_only_proven_terminal_targets_change_no_physics_or_other_inputs(self):
        report=json.loads((OUT/'osm-turn-resolution.json').read_bytes())
        for name,sha in report['unchanged_copied_files'].items():
            self.assertEqual(digest(COPY/name),sha)
            self.assertEqual(digest(ROOT/'scenarios/zona1'/name),sha)
        before=load_xml(ROOT/'scenarios/zona1/lanes.xml')
        after=load_xml(COPY/'lanes.xml')
        expected={(c['from_link'],lane,c['to_link']) for c in report['changes'] for lane in c['terminal_lanes']}
        removed=set()
        for assignment in before.findall('lanesToLinkAssignment'):
            for lane in assignment.findall('lane'):
                for target in list(lane.findall('leadsTo/toLink')):
                    key=(assignment.get('linkIdRef'),lane.get('id'),target.get('refId'))
                    if key in expected:
                        lane.find('leadsTo').remove(target);removed.add(key)
        # Ignore indentation only: capacities, startsAt, represented lanes and all
        # other attributes/elements must still match exactly.
        def semantic(e): return (e.tag,sorted(e.attrib.items()),(e.text or '').strip(),[semantic(c) for c in e])
        self.assertEqual(semantic(before),semantic(after))
        self.assertEqual(removed,expected)
        self.assertEqual(len(report['changes']),10)
        self.assertEqual(len(removed),22)
        load_lanes(COPY/'lanes.xml')

    def test_remaining_two_relations_use_verified_contract(self):
        result=validate_osm_turns(COPY/'map.osm',COPY/'network.xml',COPY/'lanes.xml')
        rows={r['relation_id']:r for r in result['relations']}
        self.assertEqual(rows['17478998']['status'],'enforced_by_shared_sequence_contract')
        self.assertEqual(rows['17884471']['status'],'MALFORMED_SOURCE_NO_EXECUTABLE_MANEUVER')
        model=load_model(COPY/'network.xml',OUT/'perimeter.geojson',COPY/'lanes.xml',COPY/'map.osm',OUT/'access.json')
        self.assertIsNone(model.sequences.progress(['osm_1273145789_0_forward','osm_1270930401_0_forward','osm_1273145790_0_forward']))

    def test_all_candidates_receive_one_decision_and_physical_gateways_are_unique(self):
        original=json.loads((OUT/'source/access-candidates-v1.json').read_bytes())
        report=json.loads((OUT/'access-review.json').read_bytes())
        access=json.loads((OUT/'access.json').read_bytes())
        for role in ('entry','exit'):
            self.assertEqual(len([r for r in report['decisions'] if r['role']==role]),len(original['candidate_'+role+'_gateways']))
            rows=access[role+'_gateways']
            self.assertEqual(len(rows),len({r['crossing_link'] for r in rows}))
            self.assertEqual(len(rows),len({r['anchor_link'] for r in rows}))
            for row in rows:
                self.assertIsNone(row['incorporation_capacity_pcu_h'])
                self.assertIsNone(row['capacity_basis']['observed_pcu_h'])
        self.assertEqual(len(report['internal_origin_decisions']),62)
        rows=access['internal_origins']
        self.assertEqual(len(rows),len({r['facility_component'] for r in rows}))
        self.assertIsNone(report['scheduled_requests_per_gateway_hour'])
        self.assertFalse(report['simulation_started'])
        usable=set().union(*(set(r['eligible_origin_links']) for r in report['class_eligibility']
                            if r['od_type'].startswith('external')))
        self.assertEqual({r['anchor_link'] for r in access['entry_gateways']},usable)
        connected_exits={r['exit'] for r in report['entry_exit_pairs'] if r['status']=='static_shortest_path_admissible'}
        self.assertEqual({r['anchor_link'] for r in access['exit_gateways']},connected_exits)

    def test_freight_copy_only_rebinds_hash_and_osm_path(self):
        source=ROOT/'scenarios/zona1/freight/weekday-compact-v3'
        before=json.loads((source/'routes.json').read_bytes())
        after=json.loads((COPY/'freight/routes.json').read_bytes())
        before['lanes_sha256']=digest(COPY/'lanes.xml')
        self.assertEqual(before,after)
        before=json.loads((source/'service-composition-v3.json').read_bytes())
        after=json.loads((COPY/'freight/service-composition-v3.json').read_bytes())
        before['osm_file']='../map.osm'
        self.assertEqual(before,after)


@unittest.skipUnless(shutil.which('powershell.exe'),'Windows wrapper contract')
class IsolatedLauncherTests(unittest.TestCase):
    def test_180k_forwards_source_config_and_services_without_launching(self):
        with tempfile.TemporaryDirectory(prefix='access source spaces ') as temp:
            folder=Path(temp); scripts=folder/'scripts'; scripts.mkdir()
            for name in ('run_simz1_180k_balanced_gateway.ps1','run_massive_z1_pasante_1it.ps1'):
                shutil.copyfile(ROOT/'scripts'/name,scripts/name)
            wrapper=scripts/'run_simz1_180k_balanced_gateway.ps1'
            text=wrapper.read_text(encoding='utf-8')
            text=text.replace("(Join-Path $project '.venv/Scripts/python.exe')", "'"+sys.executable.replace("'","''")+"'")
            text=text.replace("(Join-Path $project 'python/simz1_scale_contract.py')", "'"+str(ROOT/'python/simz1_scale_contract.py').replace("'","''")+"'")
            wrapper.write_text(text,encoding='utf-8-sig')
            # The real outer wrapper reaches only this inert shared function.
            # Capture the object separately to avoid interfering with its exit.
            (scripts/'run_massive_z1_pasante_10it.ps1').write_text(
                'function Invoke-SimZ1MassiveLaunch { param($Options)\n'
                '$Options | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath '
                "(Join-Path $PSScriptRoot 'captured.json') -Encoding UTF8\nreturn 0\n}",encoding='utf-8')
            completed=subprocess.run(['powershell.exe','-NoProfile','-ExecutionPolicy','Bypass','-File',
                str(scripts/'run_simz1_180k_balanced_gateway.ps1'),'-DryRun',
                '-ExperimentSpec',str(ROOT/'scenarios/zona1/experiments/final-20261104-24h-v3.json'),'-ExperimentScenario','full-1'],
                capture_output=True,text=True,timeout=30)
            self.assertEqual(completed.returncode,0,completed.stdout+completed.stderr)
            options=json.loads((scripts/'captured.json').read_text(encoding='utf-8-sig'))
            self.assertEqual(Path(options['SourceConfig']),folder/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/config-l18-local-v1.xml')
            self.assertEqual(Path(options['FreightService']),folder/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/freight/service-composition-v3.json')
            self.assertEqual(options['MinAgents'],204186)
            self.assertEqual(options['MaxAgents'],204186)
            self.assertEqual(options['ExperimentScenario'],'full-1')
            self.assertFalse(options['FirstScaleTrial'])
            self.assertEqual(options['Seed'],20261023)
            self.assertEqual(options['Iterations'],1)
            self.assertTrue(options['DryRun'])


if __name__=='__main__': unittest.main()
