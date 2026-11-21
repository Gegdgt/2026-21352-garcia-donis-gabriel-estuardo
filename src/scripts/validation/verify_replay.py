"""Reusable small replay regressions, migrated from the preserved historical audit.

Runs only when the user explicitly invokes this CLI. No MATSim, real browser,
native population generation or 100k data are part of this suite.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

PROJECT = Path(__file__).resolve().parents[2]


def commands():
    checks = [
        [sys.executable, '-m', 'unittest', 'discover', '-s', 'python', '-p', pattern]
        for pattern in ('test_simz1_replay_launch.py', 'test_simz1_validation_cli.py',
                        'test_simz1_paged_replay.py')
    ]
    checks.extend(['node', 'python/' + name] for name in (
        'test_visualizador_z1_controls.cjs', 'test_visualizador_z1_motion.cjs',
        'test_visualizador_z1_selection.cjs', 'test_visualizador_z1_paged.cjs'))
    checks.append(['node', 'tests/test_check_motion_fixture_controls.cjs'])
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path,
                        help='New report file; default: runtime/validation/replay-checks-UUID.json')
    parser.add_argument('--list', action='store_true', help='List commands without running checks or writing files')
    args = parser.parse_args()
    checks = commands()
    if args.list:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        return
    destination = args.output or PROJECT / 'runtime/validation' / f'replay-checks-{uuid.uuid4().hex}.json'
    results = []
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Reserve first; a repeated output cannot launch tests and overwrite evidence.
        with destination.open('x', encoding='utf-8') as stream:
            for command in checks:
                try:
                    completed = subprocess.run(command, cwd=PROJECT, capture_output=True,
                                               text=True, encoding='utf-8', errors='replace')
                    result = dict(command=command, exit_code=completed.returncode,
                                  stdout=completed.stdout, stderr=completed.stderr)
                except OSError as error:
                    result = dict(command=command, exit_code=1, stdout='', stderr=str(error))
                results.append(result)
                print('PASS' if result['exit_code'] == 0 else 'FAIL', command[-1], flush=True)
                if result['exit_code'] != 0:
                    break
            source_names = (
                'scripts/replay/start_replay.py', 'scripts/replay/start_replay.ps1',
                'python/simz1_continuous_replay.py', 'python/serve_simz1_continuous.py',
                'python/simz1_paged_replay.py', 'python/visualizador_z1_controls.js')
            hashes = {name: hashlib.sha256((PROJECT / name).read_bytes()).hexdigest()
                      for name in source_names if (PROJECT / name).is_file()}
            passed = len(results) == len(checks) and all(item['exit_code'] == 0 for item in results)
            report = dict(schema_version=1, checked_utc=datetime.now(timezone.utc).isoformat(),
                          status='pass' if passed else 'fail', results=results,
                          commands_planned=len(checks), commands_executed=len(results),
                          source_sha256=hashes, browser_rendering_verified=False,
                          scope='Small fixture regressions; no native population or MATSim execution; no 100k input.',
                          historical_source='audits/prompt13/verify_replay.py (not imported or executed)')
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    except OSError as error:
        parser.exit(1, f'No se pudo guardar la verificacion: {error}\n')
    print(destination)
    if not passed:
        parser.exit(1, 'Detenerse: revisar el primer fallo conservado en el reporte.\n')


if __name__ == '__main__':
    main()
