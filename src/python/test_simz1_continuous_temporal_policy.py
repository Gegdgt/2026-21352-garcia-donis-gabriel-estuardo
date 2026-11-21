"""Small deterministic temporal fixtures; never run QSim or alter archived runs."""
from collections import Counter
import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar,SCENARIO
from simz1_agent_types import load_catalog,allocation_counts,allocate_types
from simz1_agent_demand import verify_type_ledger
from simz1_population import verify_population
from simz1_temporal import (load_temporal_policy,compile_temporal_policy,policy_spec,intensity_segments,
    intensity_integral,ContinuousDepartureSampler,context_allocations,hourly_fit,main)
from simz1_run import sha256,parameters
from simz1_experiment_preflight import check as preflight
from generate_demand_z1 import principal_links

POLICY=SCENARIO/'temporal/weekday-continuous-v1.json'
CATALOG=SCENARIO/'agent-types-car-moto-v1.json'


class ContinuousTemporalPolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy=load_temporal_policy(POLICY)
        self.catalog=load_catalog(CATALOG)

    def test_exact_principal_N_and_six_profiles_small_and_massive_allocation_only(self):
        for n in (1,6,17,1000,183154,250000):
            kinds=allocate_types(n,20261023,self.catalog)
            counts=allocation_counts(n,self.catalog)
            self.assertEqual(len(kinds),n)
            self.assertEqual(Counter(kinds),{k:v for k,v in counts.items() if v})
            self.assertEqual(sum(counts.values()),n)
            self.assertEqual(counts['TransportePesado'],0)
            if n>=17:self.assertEqual(sum(v>0 for v in counts.values()),6)
            # Auxiliary integration cannot mutate the original allocation.
            before=counts.copy()
            context_allocations(counts,self.policy,self.catalog['canonical_order'])
            self.assertEqual(counts,before)

    def test_civil_calendar_absolute_windows_and_midnight_continuity(self):
        p=self.policy;w=p['windows'];study=w['study']
        self.assertEqual(p['technical_origin_local'],'2026-10-27T18:00:00-06:00')
        self.assertEqual(p['study_origin_local'],'2026-10-28T00:00:00-06:00')
        self.assertEqual(p['civil_utc_offset_seconds'],-21600)
        self.assertEqual(study,dict(start_seconds=21600,end_seconds=108000))
        self.assertEqual(w['simulation']['end_seconds'],136800)
        self.assertEqual(w['post_demand']['end_seconds'],129600)
        self.assertGreater(w['drain']['end_seconds'],w['post_demand']['end_seconds'])
        self.assertEqual(p['intensity']['knots'][0],p['intensity']['knots'][-1])
        self.assertGreater(p['intensity']['knots'][0],0)
        for boundary in range(study['start_seconds'],study['end_seconds']+1,3600):
            left=list(intensity_segments(p,boundary-.001,boundary))[0][-1]
            right=list(intensity_segments(p,boundary,boundary+.001))[0][-2]
            self.assertAlmostEqual(left,right,places=10)

    def test_duration_integrals_and_constant_density_partial_windows(self):
        raw=copy.deepcopy(self.policy['configuration']);raw['intensity']['knots']=[2.]*97
        raw['windows']['warmup_seconds']=1777;raw['windows']['post_demand_seconds']=2411
        p=compile_temporal_policy(raw)
        self.assertAlmostEqual(intensity_integral(p,0,1777),2*1777)
        self.assertAlmostEqual(intensity_integral(p,1777,1777+86400),2*86400)
        counts=allocation_counts(86400,self.catalog)
        context=context_allocations(counts,p,self.catalog['canonical_order'])
        self.assertEqual(context['warmup_context']['persons'],1777)
        self.assertEqual(context['post_context']['persons'],2411)
        self.assertAlmostEqual(sum(policy_spec(p)['hourly_probabilities']),1.)

    def test_invalid_negative_nonfinite_zero_nonperiodic_and_calendar(self):
        changes=[('negative',lambda v:v['intensity']['knots'].__setitem__(8,-1)),
                 ('nan',lambda v:v['intensity']['knots'].__setitem__(8,float('nan'))),
                 ('infinite',lambda v:v['intensity']['knots'].__setitem__(8,float('inf'))),
                 ('zero',lambda v:v['intensity'].__setitem__('knots',[0.]*97)),
                 ('overflow',lambda v:v['intensity'].__setitem__('knots',[1e308]*97)),
                 ('midnight',lambda v:v['intensity']['knots'].__setitem__(-1,2)),
                 ('coarse',lambda v:v['intensity'].__setitem__('step_seconds',3600)),
                 ('duration',lambda v:v['windows'].__setitem__('warmup_seconds',-1)),
                 ('shortday',lambda v:v['windows'].__setitem__('study_seconds',86399)),
                 ('timezone',lambda v:v.__setitem__('timezone','UTC')),
                 ('weekend',lambda v:v.__setitem__('study_date','2026-10-25')),
                 ('seed',lambda v:v.__setitem__('temporal_seed',True)),
                 ('adaptation',lambda v:v.__setitem__('departure_adaptation','adaptive'))]
        for label,change in changes:
            with self.subTest(label=label):
                raw=copy.deepcopy(self.policy['configuration']);change(raw)
                with self.assertRaises(ValueError):compile_temporal_policy(raw)

    def test_sampling_reproducible_finite_no_hour_boundary_mass(self):
        n=25000;counts=[0]*24;boundary=0
        for number in range(n):
            t=ContinuousDepartureSampler(self.policy,'Normal',f'z1_{number:05}').sample()[0]
            local=t-self.policy['windows']['study']['start_seconds']
            self.assertTrue(0<=local<86400)
            counts[int(local//3600)]+=1
            boundary += local%3600 < 1
        self.assertLess(boundary,30)
        self.assertTrue(all(row['within_tolerance'] for row in hourly_fit(counts,policy_spec(self.policy)['hourly_probabilities'])))
        a=ContinuousDepartureSampler(self.policy,'Normal','same').sample(10)
        b=ContinuousDepartureSampler(self.policy,'Normal','same').sample(10)
        self.assertEqual(a,b)
        self.assertEqual(a,sorted(set(a)))
        other=load_temporal_policy(POLICY,99)
        self.assertNotEqual(a,ContinuousDepartureSampler(other,'Normal','same').sample(10))
        self.assertNotEqual(self.policy['policy_sha256'],other['policy_sha256'])

    def test_auxiliary_windows_and_counts_are_explicit(self):
        context=context_allocations(allocation_counts(1000,self.catalog),self.policy,self.catalog['canonical_order'])
        self.assertEqual(context['warmup_context']['persons'],320)
        self.assertEqual(context['post_context']['persons'],76)
        pre=ContinuousDepartureSampler(self.policy,'Normal','ctx_pre_00001','warmup_context').sample(30)
        post=ContinuousDepartureSampler(self.policy,'Normal','ctx_post_00001','post_context').sample(30)
        self.assertTrue(all(0<=t<21600 for t in pre))
        self.assertTrue(all(108000<=t<129600 for t in post))
        self.assertTrue(all(t>86400 for t in post))

    def test_profile_curve_override_changes_only_timing_assumption(self):
        raw=copy.deepcopy(self.policy['configuration'])
        raw['profile_multipliers']={'Normal':[1+(i%96)/96 if i!=96 else 1 for i in range(97)]}
        changed=compile_temporal_policy(raw)
        before=allocate_types(1000,7,self.catalog)
        after=allocate_types(1000,7,self.catalog)
        self.assertEqual(before,after)
        self.assertNotEqual(ContinuousDepartureSampler(self.policy,'Normal','p').sample(),ContinuousDepartureSampler(changed,'Normal','p').sample())

    def generate(self,run,*,policy=POLICY,temporal_seed=None):
        with patch('generate_montecarlo_z1.duplicate_population_check',return_value={'matches':[],'unverifiable_manifests':[]}):
            return generar(SCENARIO/'config-simz1.xml',run,20261023,agents=17,corridor_policy='redistribute',
                origin_policy='uniform-nodes-v1',agent_catalog=CATALOG,temporal_policy=policy,temporal_seed=temporal_seed,
                incidents=False,within_day_routing=False)

    def test_generation_preserves_principal_OD_profiles_seeds_and_immutable_times(self):
        originals={p:sha256(p) for p in (SCENARIO/'config-simz1.xml',CATALOG,POLICY)}
        with tempfile.TemporaryDirectory(prefix='temporal-contract-') as folder:
            base=Path(folder);reports={}
            for name,policy,seed in [('legacy',None,None),('new',POLICY,None),('repeat',POLICY,None),('newseed',POLICY,777)]:
                reports[name]=self.generate(base/name,policy=policy,temporal_seed=seed)
            def footprint(name):
                output=[]
                for p in ET.parse(base/name/'plans.xml').findall('person'):
                    if not p.get('id').startswith('z1_'):continue
                    attrs={a.get('name'):a.text for a in p.findall('attributes/attribute')}
                    output.append((p.get('id'),attrs['simz1AgentType'],[(a.get('link'),a.get('x'),a.get('y')) for a in p.findall('plan/activity')]))
                return output
            self.assertEqual(footprint('legacy'),footprint('new'))
            self.assertEqual(footprint('new'),footprint('newseed'))
            self.assertEqual(sha256(base/'new/plans.xml'),sha256(base/'repeat/plans.xml'))
            self.assertNotEqual(sha256(base/'new/plans.xml'),sha256(base/'newseed/plans.xml'))
            r=reports['new'];self.assertEqual(r['principal_cohort_persons'],17)
            self.assertEqual(r['principal_agent_type_counts'],allocation_counts(17,self.catalog))
            self.assertEqual(r['agents'],17+r['context_persons'])
            self.assertEqual(r['xml_verified_counts']['principal_cohort_persons'],17)
            for p in ET.parse(base/'new/plans.xml').findall('person'):
                attrs={a.get('name'):a.text for a in p.findall('attributes/attribute')}
                self.assertEqual(float(attrs['simz1PlannedDepartureSeconds']),float(p.find('plan/activity').get('end_time')))
                self.assertEqual(attrs['simz1TemporalPolicySha256'],self.policy['policy_sha256'])
            params=parameters(base/'new/config-simz1.xml')
            self.assertEqual(params['qsim.startTime'],'00:00:00');self.assertEqual(params['qsim.endTime'],'38:00:00')
            self.assertEqual(verify_type_ledger(base/'new/plans.xml',base/'new/inputs/agent-types.jsonl',self.catalog,temporal_policy=self.policy),r['agent_type_counts'])
            manifest=json.loads((base/'new/run-manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(manifest['study_window'],self.policy['windows']['study'])
            self.assertEqual(manifest['temporal_policy']['policy_sha256'],self.policy['policy_sha256'])
            self.assertNotEqual(manifest['scenario_version'],manifest['scenario_base_version'])
        self.assertEqual(originals,{p:sha256(p) for p in originals})

    def test_policy_conflicts_fail_before_run_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'new'
            for override in ({'hourly_weights':[1]*24},{'drain_seconds':0},{'trips_per_person':2},{'temporal_profile':'full-day'}):
                with self.subTest(override=override),self.assertRaises(ValueError):
                    generar(SCENARIO/'config-simz1.xml',target,7,agents=2,corridor_policy='redistribute',agent_catalog=CATALOG,temporal_policy=POLICY,**override)
                self.assertFalse(target.exists())

    def test_fixed_policy_rejects_activity_time_mutator(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'bad.xml';root=ET.parse(SCENARIO/'config-simz1.xml')
            root.find("module[@name='strategy']/parameterset/param[@name='strategyName']").set('value','TimeAllocationMutator')
            root.write(config,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'mutate departure'):
                generar(config,Path(folder)/'new',7,agents=2,corridor_policy='redistribute',agent_catalog=CATALOG,temporal_policy=POLICY)
            self.assertFalse((Path(folder)/'new').exists())

    def test_validation_cli_sensitivity_is_not_a_simulation(self):
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'validated.json'
            self.assertEqual(main(['--policy',str(POLICY),'--agents','1000','--agent-catalog',str(CATALOG),'--output',str(output)]),0)
            value=json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(len(value['sensitivity']),3)
            self.assertEqual(value['principal_cohort_persons'],1000)
            self.assertIn('does not establish QSim',value['sensitivity_scope'])
            self.assertEqual(len(list(Path(folder).iterdir())),1)

    def test_preflight_reports_effective_policy_separately_from_catalog(self):
        args=(SCENARIO/'config-simz1.xml',CATALOG,1000,1000,'uniform-nodes-v1','strict-receiver-v1')
        legacy=preflight(*args)
        value=preflight(*args,temporal_policy=POLICY)
        self.assertEqual(value['catalog_temporal_demand'],legacy['temporal_demand'])
        actual=value['temporal_demand']
        self.assertEqual(actual['policy_sha256'],self.policy['policy_sha256'])
        self.assertEqual(actual['weight_source'],'explicit-synthetic-continuous-policy')
        self.assertNotEqual(actual['hourly_weights'],value['catalog_temporal_demand']['hourly_weights'])
        self.assertAlmostEqual(sum(actual['hourly_probabilities']),1.)
        for observed,expected in zip(actual['hourly_probabilities'],policy_spec(self.policy)['hourly_probabilities']):
            self.assertAlmostEqual(observed,expected)
        self.assertEqual(set(actual['per_type_hourly_probabilities']),set(value['active_profiles']))

    def test_preflight_profile_override_range_and_unknown_profile(self):
        raw=copy.deepcopy(self.policy['configuration'])
        raw['profile_multipliers']={'Normal':[1+(i%96)/96 if i!=96 else 1 for i in range(97)]}
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'policy.json';path.write_text(json.dumps(raw),encoding='utf-8')
            value=preflight(SCENARIO/'config-simz1.xml',CATALOG,17,1000,
                'uniform-nodes-v1','strict-receiver-v1',temporal_policy=path)['temporal_demand']
            self.assertNotIn('hourly_probabilities',value)
            by_type=value['per_type_hourly_probabilities']
            for n in (17,1000):
                expected=value['hourly_probabilities_by_population_bound'][str(n)]
                counts=allocation_counts(n,self.catalog)
                for hour in range(24):
                    self.assertAlmostEqual(expected[hour],sum(counts[k]*values[hour] for k,values in by_type.items())/n)
            raw['profile_multipliers']={'nonexistent':[1.]*97}
            path.write_text(json.dumps(raw),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Perfiles temporales desconocidos'):
                preflight(SCENARIO/'config-simz1.xml',CATALOG,1000,1000,
                    'uniform-nodes-v1','strict-receiver-v1',temporal_policy=path)


if __name__=='__main__':unittest.main()
