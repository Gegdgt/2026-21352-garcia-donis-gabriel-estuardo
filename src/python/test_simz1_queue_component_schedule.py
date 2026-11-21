import sqlite3
import unittest

from simz1_queue_component_schedule import ComponentSchedule


class ComponentScheduleTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE component(id INTEGER PRIMARY KEY); CREATE TABLE node(key TEXT PRIMARY KEY,component INTEGER); CREATE TABLE edge(source TEXT,target TEXT,kind TEXT);')

    def graph(self, components, edges):
        self.db.executemany('INSERT INTO component VALUES (?)',((value,) for value in sorted(set(components.values()))))
        self.db.executemany('INSERT INTO node VALUES (?,?)',components.items())
        self.db.executemany('INSERT INTO edge VALUES (?,?,?)',((a,b,kind) for a,b,kind in edges))

    def test_diamond_and_duplicate_edges_decrement_once_per_component(self):
        self.graph(dict(root=4,a=3,a2=3,b=2,leaf=1),[
            ('root','a','same_pass'),('root','a2','same_pass'),('root','b','same_pass'),
            ('a','leaf','same_pass'),('a2','leaf','same_pass'),('a','leaf','same_pass'),('b','leaf','same_pass')])
        schedule=ComponentSchedule(self.db,0)
        self.assertEqual(schedule.ready(8),[1]);schedule.resolved(1)
        self.assertEqual(schedule.ready(8),[3,2]);schedule.resolved(2)
        self.assertEqual(schedule.ready(8),[3]);schedule.resolved(3)
        self.assertEqual(schedule.ready(8),[4]);schedule.resolved(4)
        self.assertEqual(schedule.ready(8),[])
        self.assertEqual(self.db.execute('SELECT count(*) FROM component_schedule_dependency').fetchone()[0],4)

    def test_scc_internal_and_previous_generation_release_edges_do_not_order(self):
        self.graph(dict(a=1,b=1,c=2),[('a','b','same_pass'),('b','a','same_pass'),('a','a','same_pass'),('a','c','release'),('c','a','release')])
        schedule=ComponentSchedule(self.db,0)
        self.assertEqual(schedule.ready(8),[2,1]);schedule.resolved(1);schedule.resolved(2)
        self.assertEqual(schedule.ready(8),[])

    def test_claims_are_not_reissued_and_inflight_is_not_a_cycle(self):
        self.graph(dict(a=1,b=2,c=3),[]);schedule=ComponentSchedule(self.db,0)
        self.assertEqual(schedule.ready(2,claim=True),[3,2])
        self.assertEqual(schedule.ready(2,claim=True),[1])
        self.assertEqual(schedule.ready(2,claim=True),[])
        for value in (2,1,3):schedule.resolved(value)
        self.assertEqual(schedule.ready(2),[])

    def test_generation_isolation_and_no_restore_of_self_declared_state(self):
        self.graph(dict(a=1,b=2),[('b','a','same_pass')])
        first=ComponentSchedule(self.db,0);first.resolved(1)
        second=ComponentSchedule(self.db,1)
        self.assertEqual(first.ready(8),[2]);self.assertEqual(second.ready(8),[1])
        with self.assertRaises(ValueError):ComponentSchedule(self.db,0)

    def test_duplicate_unready_and_unknown_resolution_cannot_mutate_schedule(self):
        self.graph(dict(a=1,b=2),[('b','a','same_pass')]);schedule=ComponentSchedule(self.db,0)
        for value in (2,100,True):
            with self.subTest(value=value),self.assertRaises(ValueError):schedule.resolved(value)
        self.assertEqual(schedule.ready(8),[1]);schedule.resolved(1)
        with self.assertRaises(ValueError):schedule.resolved(1)
        self.assertEqual(schedule.ready(8),[2])

    def test_cross_component_cycle_is_rejected_instead_of_arbitrary_order(self):
        self.graph(dict(a=1,b=2),[('a','b','same_pass'),('b','a','same_pass')])
        schedule=ComponentSchedule(self.db,0)
        with self.assertRaisesRegex(ValueError,'cycle'):schedule.ready(8)

    def test_missing_partition_and_missing_edge_endpoint_reject_preparation(self):
        self.graph(dict(a=1),[('a','missing','same_pass')])
        with self.assertRaises(ValueError):ComponentSchedule(self.db,0)
        self.db.execute('DELETE FROM edge');self.db.execute('UPDATE node SET component=2')
        with self.assertRaises(ValueError):ComponentSchedule(self.db,0)
        self.assertEqual(self.db.execute('SELECT count(*) FROM component_schedule_generation').fetchone()[0],0)

    def test_transactions_stay_owned_by_the_caller_and_readiness_uses_index(self):
        self.graph({str(i):i for i in range(200)},[]);schedule=ComponentSchedule(self.db,0)
        self.assertTrue(self.db.in_transaction)
        self.assertEqual(schedule.ready(3),[199,198,197])
        plan=list(self.db.execute('EXPLAIN QUERY PLAN SELECT component FROM component_schedule_node WHERE generation=0 AND remaining=0 AND resolved=0 AND claimed=0 ORDER BY component DESC LIMIT 3'))
        self.assertIn('component_schedule_ready',' '.join(str(row) for row in plan))
        self.db.rollback()
        self.assertEqual(self.db.execute('SELECT count(*) FROM node').fetchone()[0],0)

    def test_completion_requires_actual_resolved_coverage_not_zero_counter(self):
        self.graph(dict(a=1,b=2),[]);schedule=ComponentSchedule(self.db,0)
        self.db.execute('UPDATE component_schedule_generation SET pending=0')
        with self.assertRaisesRegex(ValueError,'incomplete'):schedule.verify_complete()
        self.db.execute('UPDATE component_schedule_generation SET pending=2')
        schedule.resolved(1);schedule.resolved(2)
        self.assertEqual(schedule.verify_complete()['components'],2)
        self.db.execute('DELETE FROM component_schedule_node WHERE component=2')
        with self.assertRaisesRegex(ValueError,'incomplete'):schedule.verify_complete()


if __name__=='__main__':unittest.main()
