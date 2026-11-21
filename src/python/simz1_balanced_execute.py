"""File-to-argv adapter; all generation/execution remains in ejecutar_simz1.

Only invoked by an explicit manual run.
Avoids loss of JSON quotes/decimal precision in Windows PowerShell native argv.
"""
import argparse
from pathlib import Path
import sys


def arguments(argv):
    from simz1_od_policy import percentage_document
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument('--od-mix-file', type=Path, required=True)
    parsed, rest = parser.parse_known_args(argv)
    if any(arg == '--od-mix' or arg.startswith('--od-mix=') for arg in rest):
        raise ValueError('Use solo --od-mix-file; no dos mezclas')
    if '--od-mode' not in rest or rest[rest.index('--od-mode')+1] != 'balanced-gateway-v1':
        raise ValueError('Este adaptador requiere balanced-gateway-v1 explicito')
    raw = parsed.od_mix_file.read_text(encoding='utf-8-sig')
    percentage_document(raw)
    return rest + ['--od-mix', raw]


def main():
    try:
        sys.argv = [sys.argv[0]] + arguments(sys.argv[1:])
    except (OSError, ValueError, IndexError) as exc:
        raise SystemExit('Balanced launch blocked: '+str(exc))
    from ejecutar_simz1 import main as execute
    execute()


if __name__ == '__main__':
    main()
