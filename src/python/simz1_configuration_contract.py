"""One read-only MATSim 15 configuration/retention contract for every run size.

ControlerConfigGroup 15.0 exposes write*UntilIteration only as Java methods,
without StringGetter/StringSetter. They are NOT XML parameters. The constructor
defaults (events=0, plans=1) are therefore applicable to SimZ1, which does not
call those setters. The native API probe in test_simz1_configuration_contract
checks this distinction against the actual runtime jar, without starting QSim.
Source: matsim-org/matsim-libs tag 15.0, ControlerConfigGroup,
EventsHandlingImpl and PlansDumpingImpl.
"""
import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

SCHEMA = 'simz1-matsim15-configuration-v1'
PROJECT = Path(__file__).resolve().parents[1]
NATIVE_DEFAULTS = {'firstIteration': 0, 'lastIteration': 1000,
    'writeEventsInterval': 50, 'writePlansInterval': 50,
    'eventsFileFormat': 'xml', 'compressionType': 'gzip',
    'cleanItersAtEnd': 'keep', 'dumpDataAtEnd': 'true', 'runId': 'null'}
JAVA_ONLY_DEFAULTS = {'writeEventsUntilIteration': 0, 'writePlansUntilIteration': 1}
PHYSICAL = {'qsim.numberOfThreads': '1', 'qsim.useLanes': 'true',
    'qsim.removeStuckVehicles': 'false', 'signalsystems.useSignalsystems': 'true',
    'simz1Admission.storagePolicy': 'strict-receiver-v1',
    'simz1Admission.wholeVehicleReservation': 'true',
    'simz1Admission.originPolicy': 'empty-slot-origin-v1'}


def _parameters(config):
    root = config if isinstance(config, ET.Element) else ET.parse(config).getroot()
    if root.tag != 'config':
        raise ValueError('Expected a MATSim config document')
    values = {}
    for module in root.findall('module'):
        for param in module.findall('param'):
            key = module.get('name', '') + '.' + param.get('name', '')
            if key in values or param.get('value') is None:
                raise ValueError('Duplicate or valueless configuration parameter: ' + key)
            values[key] = param.get('value')
    return values


def _integer(value, key):
    text = str(value)
    if not text.isascii() or not text.isdecimal():
        raise ValueError('Invalid nonnegative integer configuration: ' + key)
    return int(text)


def _seconds(value, key):
    try:
        parts = str(value).split(':')
        result = float(value) if len(parts) == 1 else sum(float(v)*factor for v, factor in zip(parts, (3600, 60, 1)))
        if len(parts) not in (1, 3) or not 0 <= result < float('inf'):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise ValueError('Invalid configuration time: ' + key) from None


def normalize_configuration(config, *, published=False):
    """Normalize only known native defaults; missing custom physics is never allowed."""
    values = _parameters(config)
    for name in JAVA_ONLY_DEFAULTS:
        if 'controler.' + name in values:
            raise ValueError('Unsupported MATSim 15 XML parameter: controler.' + name + ' (Java API only)')
    retention = {}
    for name, default in NATIVE_DEFAULTS.items():
        key = 'controler.' + name
        if published and key not in values:
            raise ValueError('Missing published configuration parameter: ' + key)
        value = values.get(key, default)
        retention[name] = _integer(value, key) if isinstance(default, int) else str(value)
    retention.update(JAVA_ONLY_DEFAULTS)
    output_events_key = 'vspExperimental.writingOutputEvents'
    if published and output_events_key not in values:
        raise ValueError('Missing published configuration parameter: ' + output_events_key)
    # The 15.0 constructor is true, despite an outdated XML comment saying false.
    retention['writingOutputEvents'] = values.get(output_events_key, 'true')
    if retention['firstIteration'] > retention['lastIteration']:
        raise ValueError('Reversed native iteration range')
    if min(retention['writeEventsInterval'], retention['writePlansInterval']) <= 0:
        raise ValueError('Native event and plan retention cannot be disabled')
    if (retention['eventsFileFormat'] != 'xml' or retention['compressionType'] != 'gzip' or
            retention['cleanItersAtEnd'] != 'keep' or retention['dumpDataAtEnd'] != 'true' or
            retention['writingOutputEvents'] != 'true' or retention['runId'] not in ('null', '')):
        raise ValueError('Retention requires XML gzip, retained ITERS and final native dumps')
    retention['runId'] = 'null'
    physical = {key: values.get(key) for key in PHYSICAL}
    # Absence is the old origin policy, never an implicit gap-policy opt-in.
    physical['simz1Admission.originPolicy'] = values.get('simz1Admission.originPolicy', 'empty-slot-origin-v1')
    times = {key: (_seconds(values[key], key) if key in values else None)
             for key in ('qsim.startTime', 'qsim.endTime', 'qsim.timeStepSize')}
    return dict(schema=SCHEMA, matsim_version='15.0', retention=retention,
                physical=physical, times=times)


def retained_iterations(configuration):
    retention = configuration['retention']
    iterations = range(retention['firstIteration'], retention['lastIteration'] + 1)
    events = [i for i in iterations if i == retention['lastIteration'] or
              i <= retention['writeEventsUntilIteration'] or
              (i > 0 and i % retention['writeEventsInterval'] == 0)]
    plans = [i for i in iterations if i <= retention['writePlansUntilIteration'] or
             (i > 0 and i % retention['writePlansInterval'] == 0)]
    return dict(native_event_iterations=events, native_plan_iterations=plans,
                native_event_files_including_final_copy=len(events)+1,
                native_plan_files_including_final_copy=len(plans)+1)


def planned_configuration(base_path, first_iteration=0, last_iteration=0, native_end_seconds=86399):
    """Mirror the authorized versioned generator overrides; never edit the source XML."""
    result = normalize_configuration(base_path)
    if type(first_iteration) is not int or type(last_iteration) is not int or not 0 <= first_iteration <= last_iteration:
        raise ValueError('Invalid planned iteration range')
    # The versioned generator writes every authorized iteration, independently of N.
    result['retention'].update(firstIteration=first_iteration, lastIteration=last_iteration,
                               writeEventsInterval=1, writePlansInterval=1)
    # Values explicitly configured by the production preparation path; source
    # signals/lanes/removeStuck are preserved and must already be compatible.
    for key in ('qsim.useLanes', 'signalsystems.useSignalsystems'):
        if result['physical'][key] != PHYSICAL[key]:
            raise ValueError('Incompatible base configuration: ' + key)
    if result['physical']['qsim.removeStuckVehicles'] not in (None, 'false'):
        raise ValueError('Incompatible base configuration: qsim.removeStuckVehicles')
    result['physical'] = dict(PHYSICAL)
    result['times'] = {'qsim.startTime': 0.0, 'qsim.endTime': float(native_end_seconds), 'qsim.timeStepSize': 1.0}
    return result


def expected_from_selection(selection, *, project=PROJECT):
    source = Path(selection['base_inputs']['source_config'])
    if not source.is_absolute():
        source = Path(project)/source
    result = planned_configuration(source, 0, selection['iterations']-1,
                                   selection['native_qsim_end_seconds'])
    from simz1_scale_contract import origin_policy_for_selection
    result['physical']['simz1Admission.originPolicy'] = origin_policy_for_selection(selection)
    return result


def assert_configuration(actual, expected):
    if actual.get('schema') != SCHEMA or expected.get('schema') != SCHEMA:
        raise ValueError('Unknown configuration contract')
    for section in ('retention', 'physical', 'times'):
        if actual[section] != expected[section]:
            keys = sorted(set(actual[section]) | set(expected[section]))
            differences = [key for key in keys if actual[section].get(key) != expected[section].get(key)]
            raise ValueError('Effective configuration differs: ' + section + ': ' + ', '.join(differences))


def validate_input_configuration(config, selection, *, project=PROJECT):
    expected = expected_from_selection(selection, project=project)
    assert_configuration(normalize_configuration(config), expected)
    return expected


def validate_run_configuration(run_dir, expected=None, *, project=PROJECT):
    """Read-only closure; native inspector owns full gzip/hash/event verification."""
    run = Path(run_dir).resolve(strict=True)
    manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8-sig'))
    if expected is None:
        expected = expected_from_selection(manifest['experiment'], project=project)
    assert_configuration(normalize_configuration(run/'config-simz1.xml'), expected)
    assert_configuration(normalize_configuration(run/'output/output_config.xml', published=True), expected)
    retained = retained_iterations(expected)
    paths = [f'output/ITERS/it.{i}/{i}.events.xml.gz' for i in retained['native_event_iterations']]
    paths += [f'output/ITERS/it.{i}/{i}.plans.xml.gz' for i in retained['native_plan_iterations']]
    paths += ['output/output_events.xml.gz', 'output/output_plans.xml.gz']
    files = []
    for relative in paths:
        path = run/relative
        with path.open('rb') as stream:
            if stream.read(2) != b'\x1f\x8b':
                raise ValueError('Retained file is not gzip: ' + relative)
        files.append(dict(path=relative, bytes=path.stat().st_size))
    return dict(schema=SCHEMA, status='configuration_and_retention_verified',
                run_id=manifest['run_id'], configuration=expected, **retained,
                files=files, coverage='configuration and gzip presence; native inspector verifies full contents')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('plan', 'verify-run'))
    p.add_argument('--base-config', type=Path)
    p.add_argument('--iterations', type=int)
    p.add_argument('--native-end-seconds', type=int)
    p.add_argument('--experiment-spec', type=Path)
    p.add_argument('--experiment-scenario')
    p.add_argument('--run-dir', type=Path)
    p.add_argument('--expected', type=Path)
    p.add_argument('--output', type=Path)
    a = p.parse_args()
    try:
        if a.action == 'plan':
            if a.base_config is None or a.iterations is None or a.native_end_seconds is None:
                raise ValueError('plan requires base-config, iterations and native-end-seconds')
            configuration = planned_configuration(a.base_config, 0, a.iterations-1, a.native_end_seconds)
            if a.experiment_spec is not None:
                from simz1_scale_contract import experiment, require_base_inputs
                selected = experiment(a.experiment_spec, a.experiment_scenario)
                require_base_inputs(selected, source_config=a.base_config)
                if (selected['iterations'] != a.iterations or
                        selected['native_qsim_end_seconds'] != a.native_end_seconds):
                    raise ValueError('Configuration plan differs from the selected experiment')
                configuration = expected_from_selection(selected)
            elif a.experiment_scenario is not None:
                raise ValueError('Configuration plan scenario requires its specification')
            result = dict(configuration=configuration, **retained_iterations(configuration))
        else:
            expected = json.loads(a.expected.read_text(encoding='utf-8-sig'))['configuration'] if a.expected else None
            result = validate_run_configuration(a.run_dir, expected)
        raw = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False)
        if a.output:
            a.output.write_text(raw+'\n', encoding='utf-8')
        print(raw)
        return 0
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
