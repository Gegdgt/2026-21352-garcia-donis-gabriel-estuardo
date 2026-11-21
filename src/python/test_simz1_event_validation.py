from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from simz1_event_validation import MovementAudit, enabled_lane_movements, unfinished_counts


class MovementAuditTests(unittest.TestCase):
    def setUp(self):
        self.links = {'ab': ('a','b',{'car'}), 'bc': ('b','c',{'car'}),
                      'ca': ('c','a',{'car'}), 'aa': ('a','a',{'car'}),
                      'ba': ('b','a',{'car'}), 'walk': ('b','c',{'walk'})}

    def event(self, kind, link, vehicle='vehicle', **attributes):
        return ET.Element('event', type=kind, link=link, vehicle=vehicle, time='1', **attributes)

    def transition(self, audit, source, destination):
        audit.consume(self.event('left link',source))
        audit.consume(self.event('entered link',destination))

    def test_first_last_repeated_links_return_to_origin_and_two_trips(self):
        audit=MovementAudit(self.links)
        for iteration in range(2):
            audit.consume(self.event('vehicle enters traffic','ab',networkMode='car'))
            # Initial link may have no LinkEnter in MATSim; do not invent an edge.
            for source,target in (('ab','bc'),('bc','ca'),('ca','ab'),('ab','ba')):
                self.transition(audit,source,target)
            audit.consume(self.event('vehicle leaves traffic','ba'))
        self.assertEqual(audit.counts['physical_transitions'],8)
        self.assertEqual(audit.counts['invalid_physical_transitions'],0)
        # A one-link route has no observed inter-link transitions.
        audit.consume(self.event('vehicle enters traffic','aa'))
        audit.consume(self.event('vehicle leaves traffic','aa'))
        self.assertEqual(audit.counts['physical_transitions'],8)

    def test_disconnected_or_forbidden_transition_has_evidence(self):
        for source,target,reason in (('ab','ca','toNode'),('ab','ab','toNode'),('ab','walk','car')):
            audit=MovementAudit(self.links)
            with self.assertRaisesRegex(ValueError,reason) as failure:
                self.transition(audit,source,target)
            self.assertIn('vehicle',str(failure.exception))
            self.assertIn(target,str(failure.exception))
            self.assertEqual(audit.counts['invalid_physical_transitions'],1)
        audit=MovementAudit(self.links, {'ab': {'bc'}})
        with self.assertRaisesRegex(ValueError,'carriles'):
            self.transition(audit,'ab','ba')

    def test_vehicle_trip_boundary_resets_transition_state(self):
        audit=MovementAudit(self.links)
        audit.consume(self.event('left link','ab'))
        audit.consume(self.event('vehicle leaves traffic','ab'))
        audit.consume(self.event('vehicle enters traffic','ca'))
        audit.consume(self.event('entered link','ca'))
        self.assertEqual(audit.counts['physical_transitions'],0)

    def test_known_link_requires_leave_but_partial_first_event_is_allowed(self):
        for first_kind,first_link,next_link in (('vehicle enters traffic','ab','bc'),
                                               ('entered link','ab','bc'),
                                               ('entered link','ab','ab')):
            audit=MovementAudit(self.links)
            audit.consume(self.event(first_kind,first_link))
            with self.assertRaisesRegex(ValueError,'sin LinkLeave'):
                audit.consume(self.event('entered link',next_link))
        audit=MovementAudit(self.links)
        audit.consume(self.event('vehicle enters traffic','ab'))
        audit.consume(self.event('entered link','ab'))  # Initial-link compatibility.
        self.transition(audit,'ab','bc')
        with self.assertRaisesRegex(ValueError,'enlace actual conocido'):
            audit.consume(self.event('left link','ab'))

    def step_event(self, **overrides):
        values=dict(type='zona1RerouteStep',candidates='3',calculations='2',installed='1',
                    rejected='0',deferred='1',budget='2',cpuNanos='11',wallNanos='15',enabled='true')
        values.update(overrides)
        return ET.Element('event',values)

    def test_step_aggregates_and_only_changed_candidates_are_installations(self):
        audit=MovementAudit(self.links,expected_budget=2,expected_enabled=True)
        audit.consume(ET.Element('event',type='zona1WithinDayReroute',changed='false'))
        audit.consume(ET.Element('event',type='zona1WithinDayReroute',changed='true'))
        audit.consume(self.step_event())
        audit.consume(self.step_event(candidates='0',calculations='0',installed='0',deferred='0',cpuNanos='-1'))
        self.assertEqual(audit.counts['reroute_validated_candidates'],2)
        self.assertEqual(audit.counts['reroute_installations'],1)
        self.assertEqual(audit.summary(),dict(steps=2,candidates=3,calculations=2,installed=1,
            rejected=0,deferred=1,cpu_nanos=11,cpu_timed_steps=1,wall_nanos=30,
            max_calculations_per_step=2,max_attempts_per_step=2,budget=2))

    def test_step_budget_invalid_metrics_and_disabled_work_are_rejected(self):
        for overrides in ({'budget':'3'}, {'calculations':'3'}, {'deferred':'0'}, {'cpuNanos':'-2'},
                          {'enabled':'false'}, {'installed':'3'}, {'candidates':'x'}):
            audit=MovementAudit(self.links,expected_budget=2)
            with self.assertRaisesRegex(ValueError,'Metricas de reruteo invalidas'):
                audit.consume(self.step_event(**overrides))
        audit=MovementAudit(self.links)
        audit.consume(self.step_event())
        with self.assertRaisesRegex(ValueError,'eventos individuales'):
            audit.summary()

    def test_enabled_lane_target_union_and_route_failure(self):
        xml='''<laneDefinitions xmlns="http://www.matsim.org/files/dtd">
        <lanesToLinkAssignment linkIdRef="ab"><lane id="entry"><leadsTo><toLane refId="exit"/></leadsTo></lane>
        <lane id="exit"><leadsTo><toLink refId="bc"/></leadsTo></lane></lanesToLinkAssignment></laneDefinitions>'''
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'lanes.xml';path.write_text(xml)
            self.assertEqual(enabled_lane_movements(path),{'ab':{'bc'}})
        audit=MovementAudit(self.links)
        audit.consume(ET.Element('event',type='zona1RerouteRejected'))
        audit.consume(ET.Element('event',type='zona1WithinDayReroute',changed='true'))
        self.assertEqual(audit.counts['reroute_rejections'],1)
        self.assertEqual(audit.counts['reroute_installations'],1)
        with self.assertRaisesRegex(ValueError,'Ruta actual invalida'):
            audit.consume(ET.Element('event',type='zona1InvalidCurrentRoute',person='p',reason='broken prefix'))

    def test_pending_horizon_and_abort_are_distinct(self):
        counts=unfinished_counts({'active':1,'earlier':2,'horizon':3}, {'earlier':10,'horizon':100}, 100)
        self.assertEqual(counts,dict(incomplete_trips=3,aborted_trips=2,aborted_before_horizon=1,
                                    horizon_abort_events=1,pending_trips_at_horizon=2))


if __name__=='__main__':unittest.main()
