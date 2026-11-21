"""Numerical contracts for visual trajectories, independent of the renderer."""
import copy
import math
import random
import unittest
from unittest.mock import patch

import simz1_visual_motion as motion_module
from simz1_visual_motion import apply_visual_motion, normalize_settings, sample_motion, solve_motion


def segment(start=0, end=20, distance=100, cap=10, *, profile='Normal', wait=None, queue_delay=False):
    item = dict(vehicle='v',Agent_ID='p',Trip={'Trip_ID':'p:1'},Profile=profile,
                timestamps=[start,end],path=[[start,0],[end,0]],Distance_m=distance,Speed_kmh=distance/(end-start)*3.6,
                Movement_End=start+distance/cap,Inferred=False,Observed_Waits={},
                Motion_Provenance={'vehicle_limit_mps':cap,'link_speed_at_entry_mps':cap,'changes_inside_interval':False})
    if wait is not None:
        reason = 'congestion_queue' if queue_delay else 'signal_red'
        item['Observed_Waits'][reason] = dict(first=wait,last=end-1,attempts=1,
            position_evidence='unknown_queue_position' if queue_delay else 'queue_exit',
            sources=['MATSim15_queue_post_step' if queue_delay else 'MATSim15_QNode_native_branch'])
    return item


class VisualMotionTests(unittest.TestCase):
    def assert_integrates(self, plan):
        phases = plan['phases']
        if not phases:
            self.assertEqual(plan['status'],'unavailable')
            return
        expected_s, expected_t, previous_speed = 0.0,plan['start_time'],None
        for t0,t1,s0,v0,acceleration in phases:
            self.assertAlmostEqual(t0,expected_t,places=7)
            self.assertAlmostEqual(s0,expected_s,places=6)
            self.assertGreater(t1,t0)
            self.assertGreaterEqual(v0,-1e-8)
            end_speed = v0+acceleration*(t1-t0)
            self.assertGreaterEqual(end_speed,-1e-7)
            if plan.get('cap_mps') is not None:
                self.assertLessEqual(max(v0,end_speed),plan['cap_mps']+1e-7)
            if previous_speed is not None and plan['feasible']:
                self.assertAlmostEqual(v0,previous_speed,places=6)
            if plan['feasible']:
                self.assertLessEqual(acceleration,plan['acceleration_mps2']+1e-8)
                self.assertGreaterEqual(acceleration,-plan['deceleration_mps2']-1e-8)
            expected_s += v0*(t1-t0)+0.5*acceleration*(t1-t0)**2
            expected_t, previous_speed = t1,end_speed
        self.assertAlmostEqual(expected_s,plan['distance_m'],places=6)
        self.assertAlmostEqual(expected_t,plan['end_time'],places=7)

    def test_normal_braking_reference_and_exact_native_hold(self):
        item=segment(wait=12)
        old=copy.deepcopy(item)
        result=apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'kinematic')
        self.assertEqual(plan['hold_start'],12)
        self.assertEqual(plan['source'],'native_wait')
        self.assertAlmostEqual(plan['reference_deceleration_mps2'],2.5)
        self.assertAlmostEqual(plan['rate_adaptation_factor'],1)
        self.assertEqual(sample_motion(plan,12),(100,0))
        self.assertEqual(sample_motion(plan,19),(100,0))
        self.assert_integrates(plan)
        self.assertEqual({k:v for k,v in item.items() if k!='Motion_Plan'},old)
        self.assertEqual(result['counts']['native_wait_holds'],1)

    def test_no_wait_residual_and_unknown_queue_position_never_create_hold(self):
        for item in (segment(),segment(wait=5,queue_delay=True)):
            apply_visual_motion([item])
            plan=item['Motion_Plan']
            self.assertIsNone(plan['hold_start'])
            self.assertAlmostEqual(sample_motion(plan,10)[0],50)
            self.assertGreater(sample_motion(plan,19)[1],0)
            self.assert_integrates(plan)

    def test_ten_kmh_vehicle_moves_entire_exact_interval(self):
        item=segment(end=36,cap=10/3.6,profile='Tortuga')
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        for time in (0,1,5,18,35.9,36):
            distance,speed=sample_motion(plan,time)
            self.assertAlmostEqual(distance,time*10/3.6)
            self.assertAlmostEqual(speed,10/3.6)
        self.assertIsNone(plan['hold_start'])
        self.assert_integrates(plan)

    def test_following_link_accelerates_from_observed_stop(self):
        first=segment(wait=12)
        following=segment(start=20,end=40)
        apply_visual_motion([first,following])
        plan=following['Motion_Plan']
        self.assertTrue(plan['feasible'])
        self.assertAlmostEqual(plan['entry_speed_mps'],0)
        self.assertEqual(plan['entry_continuity'],'matched')
        self.assertEqual(sample_motion(plan,20),(0,0))
        self.assertGreater(sample_motion(plan,21)[1],0)
        self.assertLess(sample_motion(plan,21)[0],sample_motion(plan,22)[0])
        self.assert_integrates(first['Motion_Plan'])
        self.assert_integrates(plan)

    def test_uniform_links_do_not_stop_at_uncontrolled_boundaries(self):
        items=[segment(start=i*10,end=(i+1)*10) for i in range(4)]
        apply_visual_motion(items)
        for index,item in enumerate(items):
            plan=item['Motion_Plan']
            self.assertEqual(plan['status'],'constant')
            self.assertAlmostEqual(plan['entry_speed_mps'],10)
            self.assertAlmostEqual(plan['exit_speed_mps'],10)
            self.assertIsNone(plan['hold_start'])
            if index:
                self.assertEqual(plan['entry_continuity'],'matched')

    def test_slow_unobserved_link_cannot_create_a_stationary_valley(self):
        first=segment(end=10)
        short_distance=(1200-math.sqrt(1200**2-4*1200*20))/2
        following=segment(start=10,end=30,distance=short_distance)
        apply_visual_motion([first,following])
        plan=following['Motion_Plan']
        self.assertIsNone(plan['hold_start'])
        self.assertTrue(all(max(p[3],p[3]+p[4]*(p[1]-p[0]))>1e-8 for p in plan['phases']))
        self.assert_integrates(plan)

    def test_fallback_prior_wait_preserves_stop_and_next_entry_continuity(self):
        first=segment(wait=10)
        following=segment(start=20,end=40)
        apply_visual_motion([first,following])
        self.assertEqual(first['Motion_Plan']['status'],'fallback')
        self.assertEqual(first['Motion_Plan']['hold_start'],10)
        self.assertEqual(sample_motion(first['Motion_Plan'],15),(100,0))
        self.assertEqual(following['Motion_Plan']['entry_speed_mps'],first['Motion_Plan']['exit_speed_mps'])
        self.assertEqual(following['Motion_Plan']['entry_continuity'],'matched')

    def test_reference_can_adapt_only_within_declared_limits(self):
        item=segment(wait=11)
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertTrue(plan['feasible'])
        self.assertGreater(plan['rate_adaptation_factor'],1)
        self.assertLessEqual(plan['rate_adaptation_factor'],4)
        self.assertAlmostEqual(plan['deceleration_mps2'],5,places=6)
        self.assert_integrates(plan)
        strict=segment(wait=11)
        apply_visual_motion([strict],{'max_rate_multiplier':1})
        self.assertEqual(strict['Motion_Plan']['status'],'fallback')
        self.assertEqual(strict['Motion_Plan']['hold_start'],11)
        self.assertLessEqual(sample_motion(strict['Motion_Plan'],10)[1],10)

    def test_incompatible_stop_has_explicit_cap_safe_fallback(self):
        item=segment(wait=10)
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'fallback')
        self.assertFalse(plan['feasible'])
        self.assertEqual(plan['fallback_reason'],'native_wait_kinematics_infeasible')
        self.assertEqual(plan['native_wait_boundary'],10)
        self.assertEqual(plan['hold_start'],10)
        self.assertEqual(sample_motion(plan,10),(100,0))
        self.assert_integrates(plan)

    def test_impossible_native_wait_is_unavailable_even_if_full_duration_fits(self):
        item=segment(wait=5)
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'unavailable')
        self.assertEqual(plan['fallback_reason'],'native_wait_boundary_exceeds_speed_cap')
        self.assertEqual(plan['phases'],[])
        self.assertEqual(plan['end_time'],20)

    def test_disabled_smoothing_keeps_native_stop(self):
        item=segment(wait=12)
        apply_visual_motion([item],{'enabled':False})
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'fallback')
        self.assertEqual(plan['fallback_reason'],'smoothing_disabled')
        self.assertEqual(sample_motion(plan,13),(100,0))
        self.assert_integrates(plan)

    def test_distance_that_exceeds_cap_is_gap_not_overspeed(self):
        plan=solve_motion(100,0,1,10,10,10)
        self.assertEqual(plan['status'],'unavailable')
        self.assertEqual(plan['phases'],[])
        self.assertEqual(sample_motion(plan,.5),(None,None))
        item=segment(end=1)
        apply_visual_motion([item])
        self.assertEqual(item['Motion_Plan']['status'],'unavailable')

    def test_fixed_geometry_midnight_and_zero_time(self):
        plan=solve_motion(0,86390,86410,0,0,10)
        self.assertEqual(plan['status'],'stationary')
        self.assertEqual(sample_motion(plan,86400),(0,0))
        self.assert_integrates(plan)
        plan=solve_motion(100,86390,86410,5,5,10)
        self.assert_integrates(plan)
        self.assertAlmostEqual(sample_motion(plan,86400)[0],50)
        self.assertEqual(solve_motion(1,9,9,0,0,10)['status'],'unavailable')

    def test_settings_are_validated_and_profile_specific(self):
        for raw in ({'enabled':1},{'profiles':{'Inventado':{}}},{'profiles':{'Normal':{'acceleration_mps2':0}}},
                    {'minimum_ramp_seconds':-1},{'max_rate_multiplier':.9},{'surprise':1}):
            with self.assertRaises(ValueError):normalize_settings(raw)
        defaults=normalize_settings()
        self.assertEqual([defaults['profiles'][p]['deceleration_mps2'] for p in ('Tortuga','Normal','Liebre')],[1.5,2.5,3.5])
        customized=normalize_settings({'profiles':{'Tortuga':{'deceleration_mps2':2}}})
        self.assertEqual(customized['profiles']['Tortuga']['deceleration_mps2'],2)
        self.assertEqual(normalize_settings()['profiles']['Tortuga']['deceleration_mps2'],1.5)

    def test_disconnected_trips_do_not_share_speed_state(self):
        first=segment(wait=12)
        following=segment(start=30,end=50)
        apply_visual_motion([first,following])
        self.assertEqual(following['Motion_Plan']['entry_continuity'],'unobserved_boundary')
        self.assertGreater(following['Motion_Plan']['entry_speed_mps'],0)

    def test_dynamic_limits_use_interval_minimum_and_do_not_claim_unknown_changes(self):
        item=segment(end=30)
        item['Motion_Provenance'].update(changes_inside_interval=True,minimum_link_speed_in_interval_mps=4)
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'fallback')
        self.assertEqual(plan['cap_mps'],4)
        self.assertEqual(plan['fallback_reason'],'speed_change_with_unknown_internal_entry')
        self.assert_integrates(plan)
        item=segment()
        item['Motion_Provenance']['fallback_reason']='unregistered_network_changes'
        apply_visual_motion([item])
        plan=item['Motion_Plan']
        self.assertEqual(plan['status'],'fallback')
        self.assertEqual(plan['fallback_reason'],'unregistered_network_changes')
        self.assertFalse(plan['limits_complete'])

    def test_seeded_feasible_trajectories_integrate_with_bounded_rates(self):
        # Independently construct a trapezoid, then ask the solver to reproduce
        # its distance/time/endpoints without prescribing the internal phases.
        rng=random.Random(20261016)
        for _ in range(200):
            acceleration,deceleration=rng.uniform(.5,3),rng.uniform(1,4)
            cap=rng.uniform(2,20)
            entry,exit_speed=rng.uniform(0,cap),rng.uniform(0,cap)
            peak=rng.uniform(max(entry,exit_speed),cap)
            accelerate=(peak-entry)/acceleration
            brake=(peak-exit_speed)/deceleration
            cruise=rng.uniform(0,20)
            duration=accelerate+cruise+brake
            distance=(entry+peak)*accelerate/2+peak*cruise+(exit_speed+peak)*brake/2
            plan=solve_motion(distance,86390,86390+duration,entry,exit_speed,cap,acceleration,deceleration)
            self.assertTrue(plan['feasible'],plan)
            self.assert_integrates(plan)
            sampled=[sample_motion(plan,86390+duration*j/50)[0] for j in range(51)]
            self.assertTrue(all(a<=b+1e-7 for a,b in zip(sampled,sampled[1:])))

    def test_fast_feasibility_matches_piecewise_envelope_and_numerical_edges(self):
        rng=random.Random(20261016)
        cases=[(0,0,0,0,0,10,1.5,2.5),(1,0,0,0,0,10,1.5,2.5),
               (0,0,10,0,0,10,1.5,2.5),(100,0,10,10,10,10,1.5,2.5)]
        for _ in range(1000):
            cap=rng.uniform(.1,40);duration=rng.uniform(.001,200)
            entry,exit_speed=rng.uniform(0,cap),rng.uniform(0,cap)
            acceleration,deceleration=rng.uniform(.1,12),rng.uniform(.1,14)
            cases.append((rng.uniform(0,cap*duration*1.2),0,duration,entry,exit_speed,cap,acceleration,deceleration))
            if exit_speed-entry<=acceleration*duration and entry-exit_speed<=deceleration*duration:
                _,low,high=motion_module._envelope_parts(duration,cap,entry,exit_speed,acceleration,deceleration)
                # Both exact envelope extrema and their tolerance boundaries:
                # representable neighbors force the guarded rounding path.
                for boundary in (low,high):
                    for value in (boundary,boundary-max(1e-8,boundary*1e-10),boundary+max(1e-8,boundary*1e-10)):
                        for distance in (math.nextafter(value,-math.inf),value,math.nextafter(value,math.inf)):
                            if distance>=0:
                                cases.append((distance,0,duration,entry,exit_speed,cap,acceleration,deceleration))
        for args in cases:
            self.assertEqual(motion_module._feasible(*args),motion_module._bounded(*args) is not None,args)

    def test_optimized_rate_search_preserves_complete_plans_and_metadata(self):
        rng=random.Random(17)
        records=[]
        for trip in range(20):
            start=86390.0+trip*300
            for index in range(8):
                duration=rng.uniform(8,40);distance=rng.uniform(20,200);cap=rng.choice([10/3.6,10,15])
                wait=start+rng.uniform(.4,.95)*duration if index%3==0 else None
                item=segment(start=start,end=start+duration,distance=distance,cap=cap,wait=wait,
                             queue_delay=index%6==0,profile=rng.choice(['Tortuga','Normal','Liebre']))
                item.update(vehicle=f'v{trip}',Agent_ID=f'p{trip}',Trip={'Trip_ID':f'p{trip}:1'})
                records.append(item);start+=duration
        expected=copy.deepcopy(records)
        with patch.object(motion_module,'_feasible',side_effect=lambda *args:motion_module._bounded(*args) is not None):
            original_summary=apply_visual_motion(expected)
        actual_summary=apply_visual_motion(records)
        self.assertEqual(actual_summary,original_summary)
        self.assertEqual(records,expected,'phases, native timestamps, holds, continuity and provenance must remain identical')

    def test_phase_constructor_remains_authoritative_if_fast_search_disagrees(self):
        expected=segment(wait=11)
        with patch.object(motion_module,'_feasible',side_effect=lambda *args:motion_module._bounded(*args) is not None):
            apply_visual_motion([expected])
        actual=segment(wait=11)
        # A deliberately incorrect fast predicate triggers the retained original
        # search instead of emitting a false feasible plan or changing the hold.
        with patch.object(motion_module,'_feasible',return_value=True):
            apply_visual_motion([actual])
        self.assertEqual(actual,expected)


if __name__=='__main__':
    unittest.main()
