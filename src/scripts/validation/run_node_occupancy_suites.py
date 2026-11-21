"""Run existing replay Node suites and retain exit codes and source fingerprints."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Use a new evidence directory; previous results are preserved')
    output.mkdir(parents=True)
    sources = sorted((root/'python').glob('*.js'))
    def fingerprint():
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    before = fingerprint()
    results = []
    for path in sorted((root/'python').glob('test_simz1_*.cjs')):
        log = output/(path.name+'.log')
        start = time.monotonic()
        with log.open('wb') as stream:
            result = subprocess.run(['node', str(path)], cwd=root, stdout=stream, stderr=subprocess.STDOUT)
        results.append(dict(file=path.relative_to(root).as_posix(), command='node '+path.relative_to(root).as_posix(),
                            exit_code=result.returncode, elapsed_seconds=round(time.monotonic()-start, 3),
                            log=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        print(path.name, result.returncode, flush=True)
    report = dict(suite_count=len(results), failed_count=sum(row['exit_code'] != 0 for row in results),
                  results=results, before=before, after=fingerprint())
    (output/'summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    return int(bool(report['failed_count']) or report['before'] != report['after'])


if __name__ == '__main__':
    raise SystemExit(main())
