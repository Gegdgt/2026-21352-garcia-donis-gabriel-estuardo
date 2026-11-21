"""Export the authored visual-motion fixture; never run the integration tests or QSim."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python'))
from test_simz1_visual_motion_integration import fixture_main


if __name__ == '__main__':
    fixture_main()
