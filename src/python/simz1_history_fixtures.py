"""Verified historical regression inputs, independent of disposable runs.

Materialization only relocates config paths. The copied historical manifest is
unaltered, failed, and is used as an OD contract by native component fixtures;
it never certifies the subset as a run.
"""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/'tests/fixtures/simz1-history-v1'
REQUIRED_HISTORY_FILES = ('tests/fixtures/simz1-history-v1/c529-evidence/DIAGNOSTICO_C529.md', 'tests/fixtures/simz1-history-v1/c529-evidence/code_excerpts.txt', 'tests/fixtures/simz1-history-v1/c529-evidence/code_sources.json', 'tests/fixtures/simz1-history-v1/c529-evidence/early_case_plans.json', 'tests/fixtures/simz1-history-v1/c529-evidence/early_cases_minimal.json', 'tests/fixtures/simz1-history-v1/c529-evidence/early_dependency.json', 'tests/fixtures/simz1-history-v1/c529-evidence/effective_config_summary.json', 'tests/fixtures/simz1-history-v1/c529-evidence/focus_dependency_evidence.json', 'tests/fixtures/simz1-history-v1/c529-evidence/focus_state_history.json', 'tests/fixtures/simz1-history-v1/c529-evidence/monitor_first_rejection.json', 'tests/fixtures/simz1-history-v1/c529-evidence/rerouting_decisions_summary.json', 'tests/fixtures/simz1-history-v1/c529/config-simz1.xml', 'tests/fixtures/simz1-history-v1/c529/historical-manifest.json', 'tests/fixtures/simz1-history-v1/c529/inputs/od-access-catalog.json', 'tests/fixtures/simz1-history-v1/c529/inputs/od-source.osm', 'tests/fixtures/simz1-history-v1/c529/inputs/signalsystems-signalcontrol.xml', 'tests/fixtures/simz1-history-v1/c529/inputs/signalsystems-signalgroups.xml', 'tests/fixtures/simz1-history-v1/c529/inputs/signalsystems-signalsystems.xml', 'tests/fixtures/simz1-history-v1/c529/inputs/transit-weekday/lanes.xml', 'tests/fixtures/simz1-history-v1/c529/inputs/transit-weekday/network.xml', 'tests/fixtures/simz1-history-v1/c529/inputs/zone-boundary.geojson', 'tests/fixtures/simz1-history-v1/cursor/historical-manifest.json', 'tests/fixtures/simz1-history-v1/cursor/historical.xml', 'tests/fixtures/simz1-history-v1/cursor/matsim-run.log', 'tests/fixtures/simz1-history-v1/cursor/roster.json', 'tests/fixtures/simz1-history-v1/provenance.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-L18-first-duty.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-first-window-freight.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-first-window-violations.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-freight_000155.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-freight_000426.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-prefix-counts.csv', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-prefix-reconciliation.json', 'tests/fixtures/simz1-history-v1/second-avenue/Run-3-retention-conclusion.json', 'tests/fixtures/simz1-history-v1/second-avenue/Validate-identities.json', 'tests/fixtures/simz1-history-v1/second-avenue/current-checkpoint.json', 'tests/fixtures/simz1-history-v1/second-avenue/final-process-check.json', 'tests/fixtures/simz1-history-v1/second-avenue/regressions.json', 'tests/fixtures/simz1-history-v1/temporal-evidence/signal_fixture_input.json', 'tests/fixtures/simz1-history-v1/temporal/config-simz1.xml', 'tests/fixtures/simz1-history-v1/temporal/historical-manifest.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/effective-access-review.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/freight-weekday/routes.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/network-inputNetworkFile.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/network-laneDefinitionsFile.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/od-access-catalog.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/od-source.osm', 'tests/fixtures/simz1-history-v1/temporal/inputs/signalsystems-signalcontrol.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/signalsystems-signalgroups.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/signalsystems-signalsystems.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/lanes.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/network.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/roster.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/route-bundle.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/source-service.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/stops.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/transit-fleet-manifest.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/transitSchedule.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/transitVehicles.xml', 'tests/fixtures/simz1-history-v1/temporal/inputs/transit-weekday/weekday-policy.json', 'tests/fixtures/simz1-history-v1/temporal/inputs/zone-boundary.geojson')
REQUIRED_HISTORY_FILES += ('tests/fixtures/simz1-history-v1/c529-evidence/routing_observation_summary.json', 'tests/fixtures/simz1-history-v1/c529-evidence/reroute_trigger_timeline.csv')


def verify(base=BASE):
    index=json.loads((base/'provenance.json').read_bytes())
    for name,row in index['files'].items():
        path=base/name
        if not path.is_file():raise ValueError('Missing historical fixture: '+name)
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
        digest=h.hexdigest()
        if digest!=row['sha256']:raise ValueError('Changed historical fixture: '+name)
    return index

def dataset(name):
    verify()
    path=BASE/name
    if not path.is_dir():raise ValueError('Missing historical dataset: '+name)
    return path

def materialize(name):
    source=dataset(name)
    dest=Path(tempfile.mkdtemp(prefix='historical-fixture-'+name+'-',dir=ROOT/'runtime'))
    shutil.copytree(source,dest,dirs_exist_ok=True)
    manifest=json.loads((source/'historical-manifest.json').read_bytes())
    if manifest['status']!='failed':raise ValueError('Historical subset must never carry an accepted manifest')
    shutil.copyfile(source/'historical-manifest.json',dest/'run-manifest.json')
    original=manifest['folder'].replace('\\','/').rstrip('/')+'/'
    tree=ET.parse(source/'config-simz1.xml')
    relocations=[]
    for param in tree.findall('.//param'):
        value=param.get('value','').replace('\\','/')
        if value.startswith(original):
            relative=value[len(original):]
            param.set('value',str(dest/relative))
            relocations.append(dict(parameter=param.get('name'),original=value,relative=relative))
    from prepare_simz1 import write_xml
    write_xml(dest/'config-simz1.xml',tree.getroot(),'config_v2.dtd')
    (dest/'fixture-scope.json').write_text(json.dumps(dict(scope='historical regression subset, NOT a run',relocations=relocations),indent=2))
    return dest

def temporal():
    run=materialize('temporal'); evidence=run/'evidence';evidence.mkdir()
    original=dataset('temporal-evidence')/'signal_fixture_input.json'
    row=json.loads(original.read_bytes());row['run']=str(run)
    (evidence/'signal_fixture_input.json').write_text(json.dumps(row,indent=2),encoding='utf-8')
    return run,evidence
