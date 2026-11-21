import tempfile
import unittest
from pathlib import Path
from generar_graficas_z1 import iteration_metrics, generar_historial


class LearningPlotsTests(unittest.TestCase):
    def test_numeric_order_units_scores_and_missing(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for i in (10,2,0):
                (root/'ITERS'/f'it.{i}').mkdir(parents=True)
            (root/'scorestats.txt').write_text('ITERATION\tavg. EXECUTED\n0\t-100\n2\t-50\n10\t-40\n')
            (root/'ITERS/it.0/0.legdurations.txt').write_text('average leg duration: 120 seconds = 00:02:00\n')
            (root/'ITERS/it.2/traveltimes.txt').write_text('iteration\tmean_travel_time_seconds\n2\t60\n')
            data=generar_historial(root)
            self.assertEqual(data.Iteration.tolist(),[0,2,10])
            self.assertEqual(data.Mean_Travel_Time_Minutes.iloc[:2].tolist(),[2,1])
            self.assertEqual(data.Status.iloc[2],'sin datos')
            self.assertEqual(len(list((root/'graficas_aprendizaje').glob('*.png'))),3)
            self.assertEqual(data.Executed_Score.iloc[0],-100)

    def test_missing_duration_is_not_inferred_from_score(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'ITERS/it.0').mkdir(parents=True)
            (root/'scorestats.txt').write_text('ITERATION\tavg. EXECUTED\n0\t-3\n')
            with self.assertRaisesRegex(ValueError,'duraciones'):
                generar_historial(root)

if __name__=='__main__': unittest.main()
