import unittest
from simz1_thesis_runs_v2 import active_metrics, distribution

def row(vehicle,a,b):
    return dict(vehicle_id=vehicle,traffic_entry=a,traffic_exit=b,arrival=b,abort_before_cleanup=None)

class LifecycleMetrics(unittest.TestCase):
    def test_touching_expeditions_are_one_physical_bus(self):
        result=active_metrics([row('bus',10,20),row('bus',20,30)],0,40)
        self.assertEqual(result,dict(peak_active=1,mean_active=.5,vehicle_seconds=20.))
    def test_overlap_rejected(self):
        with self.assertRaises(ValueError): active_metrics([row('bus',10,21),row('bus',20,30)])
    def test_pending_and_horizon_censored(self):
        result=active_metrics([row('pending',None,None),row('active',86390,None)],82800,86400)
        self.assertEqual(result['vehicle_seconds'],10)
        self.assertEqual(result['peak_active'],1)
    def test_hour_is_clipped_and_zero_duration_has_no_stock(self):
        self.assertEqual(active_metrics([row('a',100,3700),row('b',3650,3650)],3600,7200)['vehicle_seconds'],100)
    def test_missing_percentiles_not_zero(self):
        self.assertIsNone(distribution([])['p90_minutes'])
        self.assertEqual(distribution([0,10])['p90_minutes'],9)
    def test_invalid_duration_rejected(self):
        for a in ([-1],[float('nan')]):
            with self.assertRaises(ValueError): distribution(a)

if __name__=='__main__': unittest.main()
