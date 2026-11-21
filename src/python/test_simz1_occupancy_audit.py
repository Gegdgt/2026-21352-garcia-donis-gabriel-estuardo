"""Reproducible native-ledger fixtures, not measured microscopic positions."""
from copy import deepcopy
import gzip
from pathlib import Path
import tempfile
import unittest

from simz1_occupancy_audit import (CorridorOccupancyAudit, POLICY, SOURCE, RECEIPT_ROUTE_POLICY,
                                  SIGNAL_WINDOW_POLICY, load_inputs)


NETWORK = {
    'a': dict(from_node='0', to_node='1', length_m=10, modes={'car', 'bus'}, represented_lanes=2),
    'a2': dict(from_node='1', to_node='2', length_m=20, modes={'car', 'bus'}, represented_lanes=2),
    'b': dict(from_node='2', to_node='3', length_m=20, modes={'car', 'bus'}, represented_lanes=1),
}
BODIES = {vehicle: dict(length_m=length, width_m=width, pcu=pcu, vehicle_type=vehicle)
          for vehicle, length, width, pcu in [('bus', 12, 2.5, 2.5), ('truck', 12, 2.5, 3.5),
                                            ('car', 4.5, 1.75, 1), ('motorcycle', 2.1, .8, .25)]}


def domain(link):
    corridor = 'a' if link in ('a', 'a2') else 'b'
    length, lanes = (30, 2) if corridor == 'a' else (20, 1)
    return dict(type='simz1OccupancyDomain', time='0', policy=POLICY, corridor=corridor, link=link,
                links='a,a2' if corridor == 'a' else 'b', linkOffsetMeters='10' if link == 'a2' else '0',
                linkLengthMeters=str(NETWORK[link]['length_m']), corridorLengthMeters=str(length),
                representedLanes=str(lanes), minimumGapMeters='0.1', endSetbackMeters='5',
                laneCapacityMeters=str(length-5), capacityMeters=str((length-5)*lanes), positionsObserved='false')


def receipt(action, vehicle, *, time=1, link='a', slot=0, ordinal=1, used=0, slot_used=None,
            previous=0, reason='arrival', **changes):
    corridor = 'a' if link in ('a', 'a2') else 'b'
    body = BODIES[vehicle]['length_m']
    if action == 'WAIT': slot, ordinal, slot_used = -1, 0, 0
    result = dict(type='simz1OccupancyReservation', time=str(time), policy=POLICY, action=action,
                  vehicle=vehicle, link=link, corridor=corridor, modelSlot=str(slot),
                  reservationOrdinal=str(ordinal), previousModelSlot=str(previous),
                  bodyLengthMeters=str(body), footprintMeters=str(body+.1), minimumGapMeters='0.1',
                  usedMeters=str(used), slotUsedMeters=str(used if slot_used is None else slot_used),
                  capacityMeters='50' if corridor == 'a' else '15',
                  laneCapacityMeters='25' if corridor == 'a' else '15',
                  source=SOURCE, laneObserved='false', reason=reason)
    result.update(changes)
    return result


def traffic(vehicle, link='a', time=1, kind='entered link'):
    return dict(type=kind, vehicle=vehicle, link=link, time=str(time))


def fixture(*, network=None):
    audit = CorridorOccupancyAudit(enabled=True, network=network or NETWORK, vehicles=BODIES)
    for link in NETWORK: audit.consume(domain(link))
    return audit


def completed_bus(*, native_before_receipt=False):
    audit = fixture()
    native, ledger = traffic('bus'), receipt('ENTER', 'bus', used=12.1)
    for event in (native, ledger) if native_before_receipt else (ledger, native): audit.consume(event)
    audit.consume(receipt('EXIT', 'bus', time=2))
    audit.consume(traffic('bus', time=2, kind='vehicle leaves traffic'))
    return audit


def passage_fixture(*, route_policy=None, transform=None):
    network = deepcopy(NETWORK)
    network.update(c=dict(from_node='-2', to_node='-1', length_m=6, modes={'car', 'bus'}, represented_lanes=1),
                   d=dict(from_node='-1', to_node='0', length_m=4, modes={'car', 'bus'}, represented_lanes=1))
    if transform is not None: transform(network)
    audit = CorridorOccupancyAudit(enabled=True, network=network, vehicles=BODIES)
    for link in NETWORK:
        event=domain(link)
        if route_policy is not None:event['receiptRouteCoveragePolicy']=route_policy
        audit.consume(event)
    for link in ('c', 'd'):
        length = network[link]['length_m']; capacity = max(0, length-5)
        row = domain('b')
        row.update(corridor=link, link=link, links=link, linkLengthMeters=str(length),
                   corridorLengthMeters=str(length), laneCapacityMeters=str(capacity), capacityMeters=str(capacity))
        if route_policy is not None:row['receiptRouteCoveragePolicy']=route_policy
        audit.consume(row)
    return audit


def passage_receipt(action, vehicle='bus', *, link='c', **options):
    event = receipt(action, vehicle, **options)
    event.update(link=link, passageLinks='c,d', passageSlots='0,0', receiptLink='a')
    return event


def passage_lock(action, *, time=1, vehicle='bus', ordinal=1, **changes):
    event = dict(type='simz1OccupancyPassage', time=str(time), policy=POLICY, action=action,
                 vehicle=vehicle, corridor='a', reservationOrdinal=str(ordinal), lockedNodes='-2,-1,0',
                 passageLinks='c,d', passageSlots='0,0', receiptLink='a', source=SOURCE,
                 positionsObserved='false', laneObserved='false', minimumReleaseTime='3', clearanceFrontMeters='15.1',
                 reason='authorized_downstream_receipt' if action == 'ACQUIRE' else 'body_clearance')
    event.update(changes)
    if event.get('receiptRouteCoveragePolicy')==RECEIPT_ROUTE_POLICY:
        event.setdefault('passageSignalWindowPolicy',SIGNAL_WINDOW_POLICY)
        for key in ('passageSignalLinks','passageSignalGreenSeconds','passageSignalTraversalSeconds'):
            event.setdefault(key,'')
    return event


def passage_progress(*, link='c', bound=-4, time=1):
    return dict(type='simz1OccupancyProgress', time=str(time), policy=POLICY, vehicle='bus', corridor='a',
                link=link, nativeQueue=link+'.0', modeledFrontLowerBoundMeters=str(bound), positionsObserved='false',
                source='native_buffer_arrival_and_reservation_order')


def leader_progress(vehicle, native, bound, *, leader=None, leader_bound=None, time=1, reason='buffer_arrival', link='a'):
    event=passage_progress(link=link,bound=bound,time=time)
    event.update(vehicle=vehicle,source='native_queue_endpoint_and_leader_reservation_order',
                 reason=reason,nativeFrontBoundMeters=str(native))
    if leader:
        event.update(leaderVehicle=leader,leaderFrontLowerBoundMeters=str(leader_bound),
                     leaderFootprintMeters=str(BODIES[leader]['length_m']+.1))
    return event


class LeaderBoundAuditTests(unittest.TestCase):
    def test_younger_trigger_can_repeat_but_cannot_advance_older_vehicle_snapshot(self):
        def active_pair():
            audit=fixture();audit.consume(receipt('ENTER','bus',used=12.1));audit.consume(traffic('bus'))
            audit.consume(leader_progress('bus',20,20))
            audit.consume(receipt('ENTER','car',ordinal=2,used=16.7));audit.consume(traffic('car'))
            audit.consume(leader_progress('car',20,7.9,leader='bus',leader_bound=20))
            return audit
        audit=active_pair()
        event=leader_progress('bus',20,20,time=2,reason='leader_progress');event['triggerVehicle']='car'
        audit.consume(event)
        for trigger,native,bound in [('car',25,25),('unknown',20,20)]:
            audit=active_pair()
            event=leader_progress('bus',native,bound,time=2,reason='leader_progress');event['triggerVehicle']=trigger
            with self.assertRaisesRegex(ValueError,'preceding active trigger'):audit.consume(event)

    def test_stop_queue_progress_requires_native_elapsed_time_and_preserves_leader_body(self):
        audit=fixture();audit.consume(receipt('ENTER','bus',used=12.1));audit.consume(traffic('bus'))
        event=leader_progress('bus',25,25,time=2,reason='native_earliest_exit_reached')
        event['nativeEarliestLinkExitTime']='2'
        audit.consume(event)
        audit.consume(receipt('ENTER','car',ordinal=2,used=16.7,time=2));audit.consume(traffic('car',time=2))
        event=leader_progress('car',25,12.9,time=2,reason='leader_progress',leader='bus',leader_bound=25)
        event['triggerVehicle']='bus';audit.consume(event)
        self.assertAlmostEqual(audit.active['bus']['front_bound']-12-audit.active['car']['front_bound'],.1)
        self.assertEqual(audit.counts['native_earliest_exit_checks'],1)
        for earliest in ('3',None):
            other=fixture();other.consume(receipt('ENTER','bus',used=12.1));other.consume(traffic('bus'))
            event=leader_progress('bus',25,25,time=2,reason='native_earliest_exit_reached')
            if earliest is not None:event['nativeEarliestLinkExitTime']=earliest
            with self.assertRaises(ValueError):other.consume(event)

    def test_bus_car_motorcycle_bounds_use_immediate_leader_and_refresh_after_release(self):
        audit=fixture()
        for vehicle,ordinal,used,bound,leader,leader_bound in [
                ('bus',1,12.1,25,None,None),('car',2,16.7,12.9,'bus',25),
                ('motorcycle',3,18.9,8.3,'car',12.9)]:
            audit.consume(receipt('ENTER',vehicle,ordinal=ordinal,used=used));audit.consume(traffic(vehicle))
            audit.consume(leader_progress(vehicle,25,bound,leader=leader,leader_bound=leader_bound))
        audit.consume(receipt('EXIT','bus',time=2,used=6.8))
        audit.consume(leader_progress('car',25,25,time=2,reason='leader_release'))
        audit.consume(leader_progress('motorcycle',25,20.4,leader='car',leader_bound=25,time=2,reason='leader_release'))
        audit.consume(receipt('EXIT','car',time=3,ordinal=2,used=2.2))
        audit.consume(leader_progress('motorcycle',25,25,time=3,reason='leader_release'))
        audit.consume(receipt('EXIT','motorcycle',time=4,ordinal=3))
        result=audit.summary()
        self.assertEqual(result['progress_sources'],['native_queue_endpoint_and_leader_reservation_order'])
        self.assertEqual(result['counters']['modeled_progress_events'],6)

    def test_forged_leader_coordinate_or_overlap_bound_is_rejected(self):
        for bad in (dict(leaderFrontLowerBoundMeters='26'),dict(modeledFrontLowerBoundMeters='13'),dict(leaderVehicle='truck')):
            audit=fixture();audit.consume(receipt('ENTER','bus',used=12.1));audit.consume(traffic('bus'))
            audit.consume(leader_progress('bus',25,25));audit.consume(receipt('ENTER','car',ordinal=2,used=16.7))
            event=leader_progress('car',25,12.9,leader='bus',leader_bound=25);event.update(bad)
            with self.subTest(bad=bad),self.assertRaises(ValueError):audit.consume(event)

    def test_passage_can_share_receiving_corridor_only_with_published_free_body_interval(self):
        for bus_front,reported,valid in ((25,12.9,True),(25,15,False),(18.1,6,False)):
            audit=passage_fixture();audit.consume(receipt('ENTER','bus',used=12.1));audit.consume(traffic('bus'))
            audit.consume(leader_progress('bus',bus_front,bus_front))
            audit.consume(passage_receipt('ENTER','car',ordinal=2,used=16.7));audit.consume(traffic('car',link='c'))
            acquire=passage_lock('ACQUIRE',vehicle='car',ordinal=2,clearanceFrontMeters='7.6',
                                 admissionBasis='modeled_free_entry_interval',receiptFreeFrontMeters=str(reported))
            if not valid:
                with self.subTest(bus_front=bus_front,reported=reported),self.assertRaisesRegex(ValueError,'free entry interval'):
                    audit.consume(acquire)
                continue
            audit.consume(acquire)
            audit.consume(dict(acquire,time='2',action='RELEASE',reason='reservation_exit'))
            audit.consume(passage_receipt('EXIT','car',ordinal=2,time=2,used=12.1,reason='abort'))
            audit.consume(receipt('EXIT','bus',time=2))
            self.assertEqual(audit.summary()['counters']['receipt_free_intervals_checked'],1)


    def test_boundary_exit_tail_cannot_extend_receiving_capacity(self):
        # Synthetic event sequence: a car retains its origin reservation while
        # exiting through a boundary passage. Its rear has passed the origin's
        # 25 m usable capacity; Java freeFront still caps free space at 25 m.
        for reported, valid in ((25, True), (30.4, False), (24, False)):
            with self.subTest(reported=reported):
                audit=passage_fixture()
                audit.consume(receipt('ENTER','car',used=4.6));audit.consume(traffic('car'))
                audit.consume(receipt('TRANSFER','car',link='a2',time=2,used=4.6))
                audit.consume(traffic('car',link='a2',time=2))
                fields=dict(exitLinks='b',exitSlots='0',exitFromLink='a2',passageKind='boundary_exit')
                transfer=receipt('TRANSFER','car',link='a2',time=3,used=4.6,**fields)
                transfer['link']='b';audit.consume(transfer);audit.consume(traffic('car',link='b',time=3))
                exit_lock=dict(type='simz1OccupancyPassage',time='3',policy=POLICY,action='ACQUIRE',
                    vehicle='car',corridor='a',reservationOrdinal='1',lockedNodes='2',source=SOURCE,
                    positionsObserved='false',laneObserved='false',minimumReleaseTime='5',
                    clearanceFrontMeters='50',reason='authorized_native_traffic_exit',**fields)
                audit.consume(exit_lock)
                audit.consume(leader_progress('car',35,35,link='b',time=4))
                audit.consume(passage_receipt('ENTER','bus',time=4,ordinal=2,used=16.7))
                audit.consume(traffic('bus',link='c',time=4))
                acquire=passage_lock('ACQUIRE',time=4,ordinal=2,minimumReleaseTime='5',
                    admissionBasis='modeled_free_entry_interval',receiptFreeFrontMeters=str(reported))
                if not valid:
                    with self.assertRaisesRegex(ValueError,'free entry interval'):audit.consume(acquire)
                    continue
                audit.consume(acquire)
                self.assertEqual(audit.active['car']['footprint'],4.6)
                self.assertEqual(audit.slot_used['a'][0],16.7)
                audit.consume(dict(acquire,time='5',action='RELEASE',reason='reservation_exit'))
                audit.consume(passage_receipt('EXIT','bus',time=5,ordinal=2,used=4.6,reason='abort'))
                audit.consume(dict(exit_lock,time='5',action='RELEASE',reason='reservation_exit'))
                leave=receipt('EXIT','car',link='a2',time=5,**fields);leave['link']='b';audit.consume(leave)
                self.assertEqual(audit.summary()['counters']['receipt_free_intervals_checked'],1)


class CorridorPassageAuditTests(unittest.TestCase):
    def test_rejected_activity_candidate_wait_is_not_an_occupied_position_or_traffic_receipt(self):
        audit=passage_fixture();audit.consume(receipt('ENTER','bus',used=12.1));audit.consume(traffic('bus'))
        wait=receipt('WAIT','car',used=12.1,reason='activity_requires_empty_model_slot',previous=-1)
        wait['link']='c'
        before=deepcopy((audit.active,audit.used,audit.slot_used,audit.step_coverage,audit.last_ordinal,
                         audit.pending_passages,audit.node_locks,audit.observed_vehicles))
        audit.consume(wait)
        self.assertEqual(before,(audit.active,audit.used,audit.slot_used,audit.step_coverage,audit.last_ordinal,
                                 audit.pending_passages,audit.node_locks,audit.observed_vehicles))
        audit.consume(receipt('EXIT','bus',time=2))
        self.assertEqual(audit.summary()['counters']['prospective_activity_waits_without_passage_metadata'],1)
        for changes in (dict(usedMeters='0'),dict(slotUsedMeters='1'),dict(modelSlot='0'),
                        dict(reservationOrdinal='2'),dict(bodyLengthMeters='1'),dict(footprintMeters='1'),
                        dict(previousModelSlot='0'),dict(corridor='unknown'),dict(link='unknown'),
                        dict(reason='capacity_or_terminal_slot')):
            other=passage_fixture();other.consume(receipt('ENTER','bus',used=12.1));other.consume(traffic('bus'))
            with self.subTest(changes=changes),self.assertRaises(ValueError):other.consume(dict(wait,**changes))
        other=passage_fixture();other.consume(receipt('ENTER','car',used=4.6));other.consume(traffic('car'))
        with self.assertRaisesRegex(ValueError,'live reservation'):other.consume(dict(wait,usedMeters='4.6'))
        for action in ('ENTER','TRANSFER'):
            other=passage_fixture();event=receipt(action,'car',ordinal=1,used=4.6,previous=0);event['link']='c'
            with self.subTest(action=action),self.assertRaisesRegex(ValueError,'outside domain'):other.consume(event)
        for native_before in (False,True):
            other=passage_fixture();event=dict(wait,usedMeters='0')
            events=(traffic('car',link='c'),event) if native_before else (event,traffic('car',link='c'))
            for row in events:other.consume(row)
            with self.subTest(native_before=native_before),self.assertRaisesRegex(ValueError,'without a corridor reservation'):
                other.summary()

    def test_signal_window_proves_strict_clearance_and_keeps_same_evidence_on_release(self):
        def pending():
            audit=passage_fixture(route_policy=RECEIPT_ROUTE_POLICY)
            audit.consume(passage_receipt('ENTER',used=12.1));audit.consume(traffic('bus',link='c'))
            return audit
        proof=dict(receiptRouteCoveragePolicy=RECEIPT_ROUTE_POLICY,receiptPathLinks='a,a2',
                   receiptReachableFrontMeters='25',admissionBasis='modeled_free_entry_interval',receiptFreeFrontMeters='25',
                   passageSignalLinks='c,d',passageSignalGreenSeconds='20,12',passageSignalTraversalSeconds='8,5')
        audit=pending();audit.consume(passage_lock('ACQUIRE',**proof))
        audit.consume(passage_lock('RELEASE',time=2,reason='reservation_exit',**proof))
        audit.consume(passage_receipt('EXIT',time=2,reason='abort'))
        self.assertEqual(audit.summary()['counters']['signal_window_bounds_checked'],2)
        for changes in (dict(passageSignalGreenSeconds='8,12'),dict(passageSignalGreenSeconds='nan,12'),
                        dict(passageSignalTraversalSeconds='-1,5'),dict(passageSignalLinks='d,c'),
                        dict(passageSignalLinks='c,a'),dict(passageSignalGreenSeconds='20'),
                        dict(passageSignalWindowPolicy='missing')):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                pending().consume(passage_lock('ACQUIRE',**dict(proof,**changes)))
        audit=pending();audit.consume(passage_lock('ACQUIRE',**proof))
        changed=dict(proof,passageSignalGreenSeconds='21,12')
        with self.assertRaisesRegex(ValueError,'release changed signal window'):
            audit.consume(passage_lock('RELEASE',time=2,reason='reservation_exit',**changed))
        event=passage_lock('ACQUIRE',**proof);event.pop('passageSignalTraversalSeconds')
        with self.assertRaisesRegex(ValueError,'missing/unknown passage signal window'):
            pending().consume(event)

    def test_new_launcher_expectation_rejects_older_emitter_without_relabeling_historical_contract(self):
        audit=CorridorOccupancyAudit(enabled=True,network=NETWORK,vehicles=BODIES,
                                    expected_receipt_route_coverage_policy=RECEIPT_ROUTE_POLICY)
        with self.assertRaisesRegex(ValueError,'omitted requested receipt route coverage policy'):
            audit.consume(domain('a'))
        historical=fixture()
        self.assertEqual(historical.receipt_route_policies,{None})
        event=domain('a');event['receiptRouteCoveragePolicy']=RECEIPT_ROUTE_POLICY
        fresh=CorridorOccupancyAudit(enabled=True,network=NETWORK,vehicles=BODIES,
                                    expected_receipt_route_coverage_policy=RECEIPT_ROUTE_POLICY)
        fresh.consume(event)
        self.assertEqual(fresh.receipt_route_policies,{RECEIPT_ROUTE_POLICY})

    def test_route_coverage_proves_clearance_before_real_route_leaves_receiving_domain(self):
        audit=passage_fixture(route_policy=RECEIPT_ROUTE_POLICY)
        audit.consume(passage_receipt('ENTER',used=12.1));audit.consume(traffic('bus',link='c'))
        proof=dict(receiptRouteCoveragePolicy=RECEIPT_ROUTE_POLICY,receiptPathLinks='a,a2',
                   receiptReachableFrontMeters='25',admissionBasis='modeled_free_entry_interval',receiptFreeFrontMeters='25')
        audit.consume(passage_lock('ACQUIRE',**proof))
        audit.consume(passage_lock('RELEASE',time=2,reason='reservation_exit',**proof))
        audit.consume(passage_receipt('EXIT',time=2,reason='abort'))
        summary=audit.summary()
        self.assertEqual(summary['receipt_route_coverage_policy'],RECEIPT_ROUTE_POLICY)
        self.assertEqual(summary['counters']['receipt_route_coverage_checked'],1)
        for changes in (dict(receiptPathLinks='a',receiptReachableFrontMeters='10'),
                        dict(receiptPathLinks='a',receiptReachableFrontMeters='25'),
                        dict(receiptPathLinks='a2'),dict(receiptPathLinks=''),
                        dict(receiptRouteCoveragePolicy='missing'),dict(admissionBasis='missing')):
            audit=passage_fixture(route_policy=RECEIPT_ROUTE_POLICY)
            audit.consume(passage_receipt('ENTER',used=12.1));audit.consume(traffic('bus',link='c'))
            event=passage_lock('ACQUIRE',**dict(proof,**changes))
            with self.subTest(changes=changes),self.assertRaises(ValueError):audit.consume(event)

    def test_route_coverage_policy_cannot_be_silently_dropped_on_other_domains_or_release(self):
        audit=CorridorOccupancyAudit(enabled=True,network=NETWORK,vehicles=BODIES)
        event=domain('a');event['receiptRouteCoveragePolicy']=RECEIPT_ROUTE_POLICY;audit.consume(event)
        with self.assertRaisesRegex(ValueError,'inconsistent receipt route coverage'):audit.consume(domain('a2'))
        audit=passage_fixture(route_policy=RECEIPT_ROUTE_POLICY)
        audit.consume(passage_receipt('ENTER',used=12.1));audit.consume(traffic('bus',link='c'))
        proof=dict(receiptRouteCoveragePolicy=RECEIPT_ROUTE_POLICY,receiptPathLinks='a,a2',
                   receiptReachableFrontMeters='25',admissionBasis='modeled_free_entry_interval',receiptFreeFrontMeters='25')
        audit.consume(passage_lock('ACQUIRE',**proof))
        with self.assertRaisesRegex(ValueError,'coverage policy differs'):
            audit.consume(passage_lock('RELEASE',time=2,reason='reservation_exit'))

    def test_domain_already_traversed_as_connector_cannot_be_reused_as_receiver(self):
        # Real-run regression: a later sublink had a smaller crossing margin,
        # and lookahead reconsidered a domain already committed as connector.
        audit=passage_fixture()
        event=passage_receipt('ENTER',used=12.1)
        event.update(passageLinks='c,d,a',passageSlots='0,0,0',receiptLink='a2')
        with self.assertRaisesRegex(ValueError,'incompatible passage connectors'):
            audit.consume(event)

    def test_boundary_exit_retains_origin_quota_and_can_reacquire_after_receipt_passage(self):
        audit=passage_fixture()
        audit.consume(passage_receipt('ENTER',used=12.1));audit.consume(passage_lock('ACQUIRE'));audit.consume(traffic('bus',link='c'))
        audit.consume(passage_receipt('TRANSFER',link='a',time=3,used=12.1));audit.consume(traffic('bus',time=3))
        audit.consume(passage_lock('RELEASE',time=3));audit.consume(passage_progress(link='a',bound=16,time=3))
        audit.consume(passage_receipt('TRANSFER',link='a2',time=4,used=12.1));audit.consume(traffic('bus',link='a2',time=4))
        fields=dict(exitLinks='b',exitSlots='0',exitFromLink='a2',passageKind='boundary_exit')
        transfer=receipt('TRANSFER','bus',link='a2',time=5,used=12.1,**fields);transfer['link']='b'
        audit.consume(traffic('bus',link='b',time=5));audit.consume(transfer)
        acquire=dict(type='simz1OccupancyPassage',time='5',policy=POLICY,action='ACQUIRE',vehicle='bus',corridor='a',
                     reservationOrdinal='1',lockedNodes='2',source=SOURCE,positionsObserved='false',laneObserved='false',
                     minimumReleaseTime='7',clearanceFrontMeters='50',reason='authorized_native_traffic_exit',**fields)
        audit.consume(acquire)
        audit.consume(passage_progress(link='b',bound=50,time=7))
        audit.consume(dict(acquire,time='7',action='RELEASE',reason='reservation_exit'))
        leave=receipt('EXIT','bus',link='a2',time=7,**fields);leave['link']='b';audit.consume(leave)
        result=audit.summary()
        self.assertEqual(result['counters']['ENTER'],1)
        self.assertEqual(result['counters']['passage_ACQUIRE'],2)
        self.assertEqual(result['counters']['EXIT'],1)

    def test_activity_uturn_can_revisit_node_while_retaining_one_exclusive_lock(self):
        audit = passage_fixture()
        audit.network['d']['to_node'] = '-2'
        audit.network['e'] = dict(from_node='-2', to_node='0', length_m=2, modes={'car', 'bus'}, represented_lanes=1)
        row = domain('b')
        row.update(corridor='e', link='e', links='e', linkLengthMeters='2', corridorLengthMeters='2',
                   laneCapacityMeters='0', capacityMeters='0')
        audit.consume(row)
        enter = passage_receipt('ENTER', used=12.1)
        enter.update(passageLinks='c,d,e', passageSlots='0,0,0')
        audit.consume(enter)
        metadata = dict(passageLinks='c,d,e', passageSlots='0,0,0', lockedNodes='-2,-1,0')
        audit.consume(passage_lock('ACQUIRE', **metadata)); audit.consume(traffic('bus', link='c'))
        audit.consume(passage_lock('RELEASE', time=2, reason='reservation_exit', **metadata))
        leave = passage_receipt('EXIT', time=2, reason='abort')
        leave.update(passageLinks='c,d,e', passageSlots='0,0,0')
        audit.consume(leave)
        self.assertEqual(audit.summary()['counters']['passage_ACQUIRE'], 1)

    def test_connected_short_passage_reserves_receiver_then_releases_exclusive_locks_after_body(self):
        audit = passage_fixture()
        audit.consume(traffic('bus', link='c'))  # Native LinkEnter legitimately precedes ENTER/ACQUIRE.
        audit.consume(passage_receipt('ENTER', used=12.1)); audit.consume(passage_lock('ACQUIRE'))
        audit.consume(passage_progress())
        audit.consume(traffic('bus', link='d', time=2))
        audit.consume(passage_receipt('TRANSFER', link='d', time=2, used=12.1))
        audit.consume(passage_progress(link='d', bound=0, time=2))
        audit.consume(traffic('bus', link='a', time=3))
        audit.consume(passage_receipt('TRANSFER', link='a', time=3, used=12.1))
        # The Java ledger releases first and emits the new Progress immediately
        # afterwards; time-group validation must not call that missing evidence.
        audit.consume(passage_lock('RELEASE', time=3))
        audit.consume(passage_progress(link='a', bound=16, time=3))
        audit.consume(passage_receipt('EXIT', link='a', time=4))
        result = audit.summary()
        self.assertEqual(result['counters']['passage_ACQUIRE'], 1)
        self.assertEqual(result['counters']['passage_RELEASE'], 1)
        self.assertEqual(result['geometry']['corridors']['d']['capacity_m'], 0)

    def test_missing_passage_locks_do_not_silently_validate_connector_occupancy(self):
        audit = passage_fixture(); audit.consume(passage_receipt('ENTER', used=12.1)); audit.consume(traffic('bus', link='c'))
        with self.assertRaisesRegex(ValueError, 'without acquiring passage locks'): audit.summary()

    def test_passage_path_slots_and_full_node_coverage_are_required(self):
        for changes in (dict(passageLinks='d,c'), dict(passageSlots='0,1'), dict(receiptLink='a2'),
                        dict(lockedNodes='-1,0'), dict(positionsObserved='true')):
            audit = passage_fixture(); audit.consume(passage_receipt('ENTER', used=12.1))
            with self.subTest(changes=changes), self.assertRaises(ValueError): audit.consume(passage_lock('ACQUIRE', **changes))
        audit = passage_fixture()
        with self.assertRaisesRegex(ValueError, 'without explicit connected passage'):
            event = receipt('ENTER', 'bus', used=12.1); event['link'] = 'c'; audit.consume(event)

    def test_second_body_cannot_acquire_or_cross_an_owned_passage_node(self):
        for attempt in ('acquire', 'native_entry'):
            audit = passage_fixture(); audit.consume(passage_receipt('ENTER', used=12.1)); audit.consume(passage_lock('ACQUIRE'))
            with self.subTest(attempt=attempt), self.assertRaisesRegex(ValueError, 'locked by multiple|another body passage lock'):
                if attempt == 'acquire':
                    audit.consume(passage_receipt('ENTER', 'truck', ordinal=2, used=24.2))
                    audit.consume(passage_lock('ACQUIRE', vehicle='truck', ordinal=2))
                else:
                    audit.consume(traffic('truck', link='d'))

    def test_early_release_and_missing_release_are_not_completed_valid_runs(self):
        for early in (True, False):
            audit = passage_fixture(); audit.consume(passage_receipt('ENTER', used=12.1))
            audit.consume(passage_lock('ACQUIRE')); audit.consume(traffic('bus', link='c'))
            if early:
                audit.consume(passage_lock('RELEASE', time=2))
                with self.assertRaisesRegex(ValueError, 'before modeled body cleared'): audit.summary()
            else:
                audit.consume(passage_receipt('EXIT', time=2))
                with self.assertRaisesRegex(ValueError, 'passage locks remained'): audit.summary()

    def test_terminal_exit_releases_body_and_locks_in_either_event_order(self):
        for release_before_exit in (True, False):
            audit = passage_fixture(); audit.consume(passage_receipt('ENTER', used=12.1))
            audit.consume(passage_lock('ACQUIRE')); audit.consume(traffic('bus', link='c'))
            release, leave = passage_lock('RELEASE', time=2, reason='reservation_exit'), passage_receipt('EXIT', time=2, reason='abort')
            for event in (release, leave) if release_before_exit else (leave, release): audit.consume(event)
            self.assertEqual(audit.summary()['counters']['EXIT'], 1)


class CorridorOccupancyAuditTests(unittest.TestCase):
    def test_bus_and_truck_block_one_slot_without_claiming_microscopic_observation(self):
        audit = fixture()
        audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        audit.consume(receipt('ENTER', 'truck', ordinal=2, used=24.2)); audit.consume(traffic('truck'))
        # The other slot is free, but a turning car may only use this occupied
        # terminal slot. WAIT must not be rejected based on total free capacity.
        audit.consume(receipt('WAIT', 'car', time=2, used=24.2))
        audit.consume(receipt('EXIT', 'bus', time=3, used=12.1))
        audit.consume(receipt('ENTER', 'car', time=3, ordinal=3, used=16.7)); audit.consume(traffic('car', time=3))
        audit.consume(receipt('EXIT', 'truck', time=4, ordinal=2, used=4.6))
        audit.consume(receipt('EXIT', 'car', time=4, ordinal=3))
        result = audit.summary()
        self.assertEqual(result['counters']['WAIT'], 1)
        self.assertEqual(result['vehicles_with_reservations'], 3)
        self.assertEqual(result['violations'], 0)
        self.assertFalse(result['continuous_positions_observed'])
        self.assertFalse(result['geometry']['lane_assignment_observed'])
        self.assertEqual(result['geometry']['links']['a2'], dict(corridor_id='a', offset_m=10, length_m=20))
        self.assertEqual(result['geometry']['corridors']['a']['end_setback_m'], 5)

    def test_native_event_order_same_timestamp_is_not_a_false_missing_reservation(self):
        for before in (True, False):
            result = completed_bus(native_before_receipt=before).summary()
            self.assertEqual(result['counters']['native_entries_checked'], 1)
            self.assertEqual(result['reservations_remaining'], 0)

    def test_transfer_preserves_slot_updates_link_then_cross_corridor_releases_before_reserving(self):
        audit = fixture()
        audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        audit.consume(traffic('bus', link='a2', time=2))
        audit.consume(receipt('TRANSFER', 'bus', link='a2', time=2, used=12.1))
        # Same-link internal-queue insertion produces an extra legitimate receipt.
        audit.consume(receipt('TRANSFER', 'bus', link='a2', time=2, used=12.1))
        audit.consume(traffic('bus', link='b', time=3))
        audit.consume(receipt('EXIT', 'bus', link='a2', time=3, reason='node_transfer'))
        audit.consume(receipt('ENTER', 'bus', link='b', time=3, ordinal=2, used=12.1))
        audit.consume(receipt('EXIT', 'bus', link='b', time=4, ordinal=2))
        self.assertEqual(audit.summary()['counters']['TRANSFER'], 2)

    def test_no_unobserved_slot_changes_and_progress_cannot_fabricate_observed_coordinates(self):
        audit = fixture(); audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        with self.assertRaisesRegex(ValueError, 'stable model slot'):
            audit.consume(receipt('TRANSFER', 'bus', time=2, slot=1, used=12.1))
        progress = dict(type='simz1OccupancyProgress', time='1', policy=POLICY, vehicle='bus', corridor='a',
                        link='a', nativeQueue='a.0', modeledFrontLowerBoundMeters='8', positionsObserved='false',
                        source='native_buffer_arrival_and_reservation_order')
        for changes in ({}, dict(positionsObserved='true'), dict(vehicle='truck'),
                        dict(link='b'), dict(modeledFrontLowerBoundMeters='31')):
            audit = fixture(); audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
            if changes:
                with self.subTest(changes=changes), self.assertRaises(ValueError): audit.consume(dict(progress, **changes))
            else:
                audit.consume(progress)
                with self.assertRaisesRegex(ValueError, 'non-monotone'):
                    audit.consume(dict(progress, modeledFrontLowerBoundMeters='7'))
                audit.consume(receipt('EXIT', 'bus', time=2))
                self.assertEqual(audit.summary()['counters']['modeled_progress_events'], 1)

    def test_motorcycle_reserves_body_plus_gap_and_does_not_turn_pcu_into_metres(self):
        audit = fixture()
        audit.consume(receipt('ENTER', 'motorcycle', used=2.2)); audit.consume(traffic('motorcycle'))
        audit.consume(receipt('EXIT', 'motorcycle', time=2))
        self.assertEqual(audit.summary()['minimum_gap_m'], .1)
        audit = fixture()
        with self.assertRaisesRegex(ValueError, 'body length plus'):
            audit.consume(receipt('ENTER', 'motorcycle', used=1.875, footprintMeters='1.875'))

    def test_per_slot_overflow_is_detected_even_when_total_corridor_capacity_remains(self):
        audit = fixture()
        audit.consume(receipt('ENTER', 'bus', used=12.1))
        audit.consume(receipt('ENTER', 'truck', ordinal=2, used=24.2))
        with self.assertRaisesRegex(ValueError, 'slot capacity exceeded'):
            audit.consume(receipt('ENTER', 'car', ordinal=3, used=28.8))

    def test_fabricated_load_body_gap_source_or_observed_lane_is_rejected(self):
        cases = [dict(usedMeters='0'), dict(slotUsedMeters='0'), dict(bodyLengthMeters='10'),
                 dict(footprintMeters='12'), dict(minimumGapMeters='.09'),
                 dict(minimumGapMeters='.09999999999999999'), dict(source='replay'),
                 dict(laneObserved='true'), dict(policy='other'), dict(capacityMeters='999')]
        for changes in cases:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                fixture().consume(receipt('ENTER', 'bus', used=12.1, **changes))

    def test_duplicate_reservation_and_ordinal_reuse_are_rejected(self):
        for vehicle, ordinal in [('bus', 2), ('truck', 1)]:
            audit = fixture(); audit.consume(receipt('ENTER', 'bus', used=12.1))
            with self.subTest(vehicle=vehicle), self.assertRaises(ValueError):
                audit.consume(receipt('ENTER', vehicle, ordinal=ordinal, used=24.2))

    def test_no_implicit_reservation_from_wait_or_prior_corridor_entry(self):
        for missing_transfer in (False, True):
            audit = fixture()
            if missing_transfer:
                audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
                audit.consume(traffic('bus', link='a2', time=2))
            else:
                audit.consume(receipt('WAIT', 'bus')); audit.consume(traffic('bus'))
            with self.subTest(missing_transfer=missing_transfer), self.assertRaisesRegex(ValueError, 'without a corridor reservation'):
                audit.summary()

    def test_completed_run_missing_releases_or_expected_policy_is_rejected(self):
        audit = fixture(); audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        with self.assertRaisesRegex(ValueError, 'live reservations'): audit.summary()
        with self.assertRaisesRegex(ValueError, 'service missing'): fixture().summary()
        with self.assertRaisesRegex(ValueError, 'domain coverage'):
            CorridorOccupancyAudit(enabled=True, network=NETWORK, vehicles=BODIES).summary()

    def test_native_exit_needs_same_timestamp_release(self):
        audit = fixture(); audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        audit.consume(traffic('bus', time=2, kind='vehicle leaves traffic'))
        with self.assertRaisesRegex(ValueError, 'without releasing'): audit.summary()

    def test_domain_metadata_requires_all_loaded_links_contiguous_offsets_and_unique_membership(self):
        for field, value in [('linkOffsetMeters', '11'), ('linkLengthMeters', '21'),
                             ('corridorLengthMeters', '31'), ('minimumGapMeters', '.09'),
                             ('positionsObserved', 'true'), ('representedLanes', '3')]:
            audit = CorridorOccupancyAudit(enabled=True, network=NETWORK, vehicles=BODIES)
            with self.subTest(field=field), self.assertRaises(ValueError):
                for link in NETWORK:
                    row = domain(link)
                    if link == 'a2': row[field] = value
                    audit.consume(row)
                audit.summary()
        audit = fixture()
        with self.assertRaisesRegex(ValueError, 'duplicate'): audit.consume(domain('a'))

    def test_zero_capacity_short_domain_is_not_silently_inflated(self):
        network = deepcopy(NETWORK); network['b']['length_m'] = 2
        audit = CorridorOccupancyAudit(enabled=True, network=network, vehicles=BODIES)
        for link in NETWORK:
            row = domain(link)
            if link == 'b': row.update(linkLengthMeters='2', corridorLengthMeters='2', laneCapacityMeters='0', capacityMeters='0')
            audit.consume(row)
        audit.consume(receipt('ENTER', 'bus', used=12.1)); audit.consume(traffic('bus'))
        audit.consume(receipt('EXIT', 'bus', time=2))
        self.assertEqual(audit.summary()['geometry']['corridors']['b']['capacity_m'], 0)

    def test_historical_runs_are_explicitly_not_applicable_without_reading_body_defaults(self):
        audit = CorridorOccupancyAudit()
        audit.consume(traffic('unknown-historical-vehicle'))
        self.assertEqual(audit.summary()['status'], 'not_applicable')
        with self.assertRaisesRegex(ValueError, 'policy disabled'): audit.consume(domain('a'))

    def test_loaded_body_is_xml_evidence_and_non_road_links_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); network = root/'network.xml.gz'; fleet = root/'vehicles.xml'
            with gzip.open(network, 'wt') as stream:
                stream.write('<network><links><link id="road" from="0" to="1" length="20" permlanes="1" modes="car,bus"/>'
                             '<link id="walk" from="1" to="2" length="1" modes="walk"/></links></network>')
            fleet.write_text('<vehicleDefinitions><vehicleType id="moto"><length meter="2.1"/><width meter="0.8"/>'
                             '<passengerCarEquivalents pce="0.25"/></vehicleType><vehicle id="m" type="moto"/></vehicleDefinitions>')
            links, vehicles = load_inputs(network, [fleet])
            self.assertEqual(set(links), {'road'})
            self.assertEqual(vehicles['m']['length_m'], 2.1)
            self.assertEqual(vehicles['m']['pcu'], .25)
            fleet.write_text(fleet.read_text().replace('<length meter="2.1"/>', ''))
            with self.assertRaisesRegex(ValueError, 'dimensions missing'): load_inputs(network, [fleet])



class StoppingReceiptTests(unittest.TestCase):
    policy = 'planned_stopping_prefix_v2'

    def pending(self):
        def geometry(network):
            for link in network.values(): link['stop_setback_m'] = 5.
            network['a']['stop_setback_m'] = 2.
            network['b'].update(from_node='1', to_node='0')  # interior return
        audit = passage_fixture(route_policy=self.policy, transform=geometry)
        audit.consume(passage_receipt('ENTER', vehicle='car', used=4.6))
        audit.consume(traffic('car', link='c'))
        return audit

    def proof(self, **changes):
        proof = dict(receiptRouteCoveragePolicy=self.policy, receiptPathLinks='a',
                     receiptReachableFrontMeters='8', receiptFollowingLink='b',
                     receiptStoppingSetbackMeters='2', clearanceFrontMeters='6',
                     admissionBasis='modeled_free_entry_interval', receiptFreeFrontMeters='25',
                     passageSignalWindowPolicy=SIGNAL_WINDOW_POLICY, passageSignalLinks='',
                     passageSignalGreenSeconds='', passageSignalTraversalSeconds='')
        proof.update(changes)
        return proof

    def test_interior_stop_exact_geometry_and_final_activity_are_distinct(self):
        for proof in (self.proof(), self.proof(receiptFollowingLink='',
                      receiptStoppingSetbackMeters='0', receiptReachableFrontMeters='10')):
            audit = self.pending()
            audit.consume(passage_lock('ACQUIRE', vehicle='car', **proof))
            audit.consume(passage_lock('RELEASE', vehicle='car', time=3, reason='reservation_exit', **proof))
            audit.consume(passage_receipt('EXIT', vehicle='car', time=3, reason='arrival'))
            self.assertEqual(audit.summary()['counters']['receipt_route_coverage_checked'], 1)

    def test_unsafe_or_forged_receipts_still_fail(self):
        for changes in (dict(receiptStoppingSetbackMeters='0'),
                        dict(receiptReachableFrontMeters='10'),
                        dict(clearanceFrontMeters='8.1'), dict(receiptFollowingLink='missing'),
                        dict(receiptFollowingLink='a2'), dict(receiptFollowingLink='d'),
                        dict(receiptFollowingLink='', receiptStoppingSetbackMeters='2')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.pending().consume(passage_lock('ACQUIRE', vehicle='car', **self.proof(**changes)))
        for missing in ('receiptFollowingLink', 'receiptStoppingSetbackMeters'):
            proof = self.proof(); proof.pop(missing)
            with self.subTest(missing=missing), self.assertRaises(ValueError):
                self.pending().consume(passage_lock('ACQUIRE', vehicle='car', **proof))

    def test_release_cannot_change_route_end_evidence(self):
        audit = self.pending(); audit.consume(passage_lock('ACQUIRE', vehicle='car', **self.proof()))
        with self.assertRaisesRegex(ValueError, 'release changed receipt route coverage'):
            audit.consume(passage_lock('RELEASE', vehicle='car', time=3, reason='reservation_exit',
                **self.proof(receiptFollowingLink='', receiptStoppingSetbackMeters='0', receiptReachableFrontMeters='10')))

    def test_new_expectation_rejects_old_emitter_and_forged_domain_capacity(self):
        expected = CorridorOccupancyAudit(enabled=True, network=NETWORK, vehicles=BODIES,
            expected_receipt_route_coverage_policy=self.policy)
        old = domain('a'); old['receiptRouteCoveragePolicy'] = RECEIPT_ROUTE_POLICY
        with self.assertRaisesRegex(ValueError, 'omitted requested receipt route coverage policy'):
            expected.consume(old)
        network = deepcopy(NETWORK); network['a2']['stop_setback_m'] = 5.
        audit = CorridorOccupancyAudit(enabled=True, network=network, vehicles=BODIES)
        forged = domain('a'); forged.update(receiptRouteCoveragePolicy=self.policy,
            endSetbackMeters='4', laneCapacityMeters='26', capacityMeters='52')
        with self.assertRaisesRegex(ValueError, 'domain stopping setback differs'):
            audit.consume(forged)

    def test_loaded_geometry_includes_nonroad_inverse_lane_width(self):
        with tempfile.TemporaryDirectory() as tmp:
            network = Path(tmp)/'network.xml'
            network.write_text('<network><nodes><node id="0" x="0" y="0"/>'
                '<node id="1" x="10" y="0"/><node id="2" x="10" y="10"/></nodes><links>'
                '<link id="a" from="0" to="1" length="10" permlanes="1" modes="car"/>'
                '<link id="ar" from="1" to="0" length="10" permlanes="2" modes="walk"/>'
                '<link id="c" from="2" to="1" length="10" permlanes="1" modes="car"/>'
                '<link id="cr" from="1" to="2" length="10" permlanes="3" modes="walk"/>'
                '</links></network>')
            links, _ = load_inputs(network, [])
            self.assertEqual(set(links), {'a', 'c'})
            self.assertAlmostEqual(links['a']['stop_setback_m'], 8.)
            self.assertAlmostEqual(links['c']['stop_setback_m'], 6.5)

if __name__ == '__main__': unittest.main()
