"""CLI for the single importable SimZ1 OSM/link/lane restriction audit."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'python'))
from simz1_osm_turn_audit import main


if __name__ == '__main__':
    main()
