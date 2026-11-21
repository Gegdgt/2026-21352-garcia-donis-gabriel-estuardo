"""Read-only launch contracts, plus explicit creation of a fresh isolated build.

This tool never launches Java, Maven, a simulation, a replay server or a browser.
Only ``build-files`` writes, exclusively into a previously nonexistent directory.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'python'))
from simz1_agent_demand import generation_catalog, validate_road_access
from simz1_agent_types import active_types, load_catalog
from simz1_config_validation import validate_configuration
from simz1_lane_validation import audit_configuration
from simz1_osm_turn_audit import inspect_restrictions
from simz1_population import population_spec
from simz1_run import load_manifest, parameters, sha256, validate_outputs

SCENARIO = PROJECT / 'scenarios/zona1'
SCHEMA = 'simz1-massive-verified-v1'
SUBSET_VERSION = 'simz1-massive-verified-road-subset-v1'
EXPECTED = {
    'simz1Admission.storagePolicy': 'strict-receiver-v1',
    'qsim.removeStuckVehicles': 'false', 'qsim.stuckTime': '10',
    'qsim.useLanes': 'true', 'qsim.usingFastCapacityUpdate': 'false',
    'signalsystems.useSignalsystems': 'true',
    'zona1Diagnostics.incidentsEnabled': 'false',
    'simz1IncidentConsequences.enabled': 'false',
    'simz1IncidentConsequences.durationSeconds': '1800',
    'simz1LanePolicy.enabled': 'false',
    'zona1Priority.enabled': 'true',
    'zona1Priority.classification': 'osm-hierarchy',
    'zona1Priority.conflicts': 'geometric',
    'zona1Priority.stopSeconds': '5', 'zona1Priority.maxYieldSeconds': '30',
    'zona1WithinDayRouting.enabled': 'true',
    'zona1WithinDayRouting.agentShare': '0.5',
    'zona1WithinDayRouting.maxReroutesPerStep': '64',
    'zona1WithinDayRouting.routingPolicy': 'fastest-time',
    'controler.enableLinkToLinkRouting': 'true',
    'travelTimeCalculator.calculateLinkToLinkTravelTimes': 'true',
    'travelTimeCalculator.separateModes': 'false',
    'qsim.flowCapacityFactor': '1.0', 'qsim.storageCapacityFactor': '1.0',
    'transit.useTransit': 'false',
}
INPUT_KEYS = ('network.inputNetworkFile', 'network.laneDefinitionsFile',
              'facilities.inputFacilitiesFile', 'vehicles.vehiclesFile',
              'signalsystems.signalsystems', 'signalsystems.signalgroups',
              'signalsystems.signalcontrol')


def _git(*args):
    return subprocess.check_output(['git', *args], cwd=PROJECT, text=True,
                                   encoding='utf-8', errors='strict').strip()


def accepted_launcher_options():
    """Inspect the actual parser declarations; do not run main or fabricate CLI."""
    result = set()
    for file, function in [('ejecutar_simz1.py', 'main'),
                           ('generate_montecarlo_z1.py', 'add_generation_options')]:
        tree = ast.parse((PROJECT / 'python' / file).read_text(encoding='utf-8-sig'))
        declaration = next(node for node in tree.body
                           if isinstance(node, ast.FunctionDef) and node.name == function)
        for node in ast.walk(declaration):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != 'add_argument':
                continue
            names = [arg.value for arg in node.args if isinstance(arg, ast.Constant)
                     and isinstance(arg.value, str) and arg.value.startswith('--')]
            result.update(names)
            if any(keyword.arg == 'action' and isinstance(keyword.value, ast.Attribute)
                   and keyword.value.attr == 'BooleanOptionalAction' for keyword in node.keywords):
                result.update('--no-' + name[2:] for name in names)
    return sorted(result)


def launcher_arguments(config, catalog, minimum, maximum, seed, threads=4):
    population_spec('montecarlo', min_agents=minimum, max_agents=maximum, massive=True)
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Seed must be an integer in 0..2147483647 for the reproducible Java/Python contract')
    if threads not in (1, 4):
        raise ValueError('Only one thread or four concurrency-tested threads are supported')
    args = ['--config', str(Path(config).resolve()), '--agent-catalog', str(Path(catalog).resolve()),
            '--mode', 'montecarlo', '--massive', '--min-agents', str(minimum), '--max-agents', str(maximum),
            '--seed', str(seed), '--matsim-seed', str(seed), '--iterations', '1',
            '--qsim-threads', str(threads), '--storage-policy', 'strict-receiver-v1',
            '--od-mode', 'network', '--corridor-policy', 'redistribute',
            '--use-lanes', '--signals', '--unsignalized-priority', '--within-day-routing',
            '--routing-share', '0.5', '--reroute-budget', '64', '--priority-stop-seconds', '5', '--priority-max-yield-seconds', '30',
            '--priority-classification', 'osm-hierarchy', '--priority-conflicts', 'geometric',
            '--no-incidents', '--signal-offset-policy', 'preserve', '--trips-per-person', '1', '--drain-seconds', '0']
    accepted = set(accepted_launcher_options())
    unknown = [value for value in args if value.startswith('--') and value not in accepted]
    if unknown:
        raise ValueError(f'Launcher no longer accepts required options: {unknown}')
    return args


def source_hashes(extra=()):
    files = {PROJECT / 'pom.xml', PROJECT / 'mvnw.cmd', PROJECT / 'AGENTS.md',
             PROJECT / '.mvn/wrapper/maven-wrapper.properties', PROJECT / '.mvn/wrapper/maven-wrapper.jar'}
    for directory in ('src/main/java/gt/edu/uvg/sim/zona1',
                      'src/main/java/org/matsim/core/mobsim/qsim/qnetsimengine',
                      'src/test/java/gt/edu/uvg/sim/zona1',
                      'src/test/java/org/matsim/core/mobsim/qsim/qnetsimengine'):
        files.update((PROJECT / directory).rglob('*.java'))
    for extension in ('*.py', '*.js', '*.cjs'):
        files.update((PROJECT / 'python').glob(extension))
    files.update((PROJECT / 'scripts').rglob('*.ps1'))
    files.update((PROJECT / 'scripts').rglob('*.py'))
    files.add(PROJECT / 'check_simz1_lane_policy.ps1')
    files.update(Path(path).resolve() for path in extra)
    return {str(path.resolve()): sha256(path) for path in sorted(files) if path.is_file()}


def verify_sources(receipt):
    inventory = receipt.get('code_inventory')
    if inventory is not None and sorted(source_hashes()) != inventory:
        raise ValueError('Source inventory changed after preflight; new or removed code requires fresh regressions')
    missing = [path for path, fingerprint in receipt['source_sha256'].items()
               if not Path(path).is_file() or sha256(path) != fingerprint]
    if missing:
        raise ValueError(f'Inputs or sources changed after preflight: {missing}')
    return {'status': 'valid', 'checked_files': len(receipt['source_sha256'])}


def _configuration_values(root):
    return {f"{module.get('name')}.{param.get('name')}": param.get('value')
            for module in root.findall('module') for param in module.findall('param')}


def _set(root, key, value):
    module, name = key.split('.', 1)
    parent = root.find(f"module[@name='{module}']")
    if parent is None:
        parent = ET.SubElement(root, 'module', name=module)
    item = parent.find(f"param[@name='{name}']")
    if item is None:
        item = ET.SubElement(parent, 'param', name=name)
    item.set('value', value)


def preflight(config, catalog, minimum, maximum, seed, threads):
    config, catalog = Path(config).resolve(), Path(catalog).resolve()
    if config != (SCENARIO / 'config-simz1.xml').resolve():
        raise ValueError('Only the existing historical network config is eligible; gateway/new-network approval is absent')
    root = ET.parse(config).getroot()
    original = _configuration_values(root)
    # A new reviewed network needs a separate launcher contract. Never regenerate here.
    inputs = {key: (config.parent / original[key]).resolve() for key in INPUT_KEYS}
    expected_files = dict(zip(INPUT_KEYS, ('network.xml', 'lanes.xml', 'facilities.xml', 'vehicle-types.xml',
                                          'signalSystems.xml', 'signalGroups.xml', 'signalControl.xml')))
    if any(path != (SCENARIO / expected_files[key]).resolve() for key, path in inputs.items()):
        raise ValueError('Historical network input references changed; explicit scenario review is required')
    tracked = [str(path.relative_to(PROJECT)).replace('\\', '/')
               for path in [config, *inputs.values(), SCENARIO / 'map.osm', SCENARIO / 'processing-report.json']]
    if _git('diff', '--name-only', 'HEAD', '--', *tracked):
        raise ValueError('Historical network inputs differ from HEAD; this launcher does not authorize a new network')
    _git('ls-files', '--error-unmatch', '--', *tracked)
    if 'zona1SpatialRouting.mode' in original:
        raise ValueError('gateway-od/through-traffic is blocked in this historical network contract')
    parsed_catalog = generation_catalog(catalog, mode='montecarlo', temporal_profile=None,
                                       hourly_weights=None, drain_seconds=0)
    if parsed_catalog['scenario_version'] != SUBSET_VERSION:
        raise ValueError('Use the explicitly derived and versioned road subset catalog')
    validate_road_access(inputs['network.inputNetworkFile'], parsed_catalog)
    if set(active_types(parsed_catalog)) != {'Normal', 'Liebre', 'Tortuga', 'MotocicletaLenta', 'Motociclista', 'MotocicletaRapida'}:
        raise ValueError('The verified subset requires the six supported road profiles; heavy/public services remain blocked')
    # Values not exposed as CLI flags must already agree, except absent native defaults.
    overrides = {'simz1Admission.storagePolicy', 'qsim.numberOfThreads', 'qsim.useLanes',
                 'signalsystems.useSignalsystems', 'zona1Diagnostics.incidentsEnabled',
                 'zona1Priority.enabled', 'zona1Priority.classification', 'zona1Priority.conflicts',
                 'zona1Priority.stopSeconds', 'zona1Priority.maxYieldSeconds',
                 'zona1WithinDayRouting.enabled', 'zona1WithinDayRouting.agentShare',
                 'zona1WithinDayRouting.maxReroutesPerStep'}
    for key, expected in EXPECTED.items():
        if key not in overrides and key in original and original[key] != expected:
            raise ValueError(f'Inconsistent source option {key}: {original[key]!r}, expected {expected!r}')
        _set(root, key, expected)
    _set(root, 'qsim.numberOfThreads', str(threads))
    validation = validate_configuration(root)
    lane_audit = audit_configuration(root, base_dir=config.parent)
    restriction = inspect_restrictions(SCENARIO / 'map.osm', inputs['network.inputNetworkFile'],
                                       inputs['network.laneDefinitionsFile'])['summary']
    args = launcher_arguments(config, catalog, minimum, maximum, seed, threads)
    return dict(schema=SCHEMA, status='ready_for_disclosed_subset', full_requested_suite='BLOCKED',
                simulation_executed=False, scenario_version=SUBSET_VERSION, od_mode='network',
                network_status='existing_historical_network_with_known_unimported_OSM_restrictions',
                gateway_od='BLOCKED: no approved boundary or complete turn-restriction import',
                git_head=_git('rev-parse', 'HEAD'), git_status=_git('status', '--short'),
                demand_seed=seed, matsim_seed=seed, minimum=minimum, maximum=maximum,
                predicted_persons=random.Random(seed).randint(minimum, maximum),
                qsim_threads=threads, concurrency_test_required=threads == 4,
                launcher_arguments=args, accepted_launcher_options=accepted_launcher_options(),
                expected_configuration={**EXPECTED, 'qsim.numberOfThreads': str(threads)},
                configuration_validation=validation,
                lane_counts=lane_audit['counts'], turn_restriction_audit=restriction,
                active_road_profiles=sorted(active_types(parsed_catalog)),
                expected_catalog=parsed_catalog,
                historical_input_sha256={key: sha256(path) for key, path in inputs.items()
                                         if key != 'vehicles.vehiclesFile'},
                physical={'receiver_admission': 'strict WAIT when receiver rejects',
                          'storage': 'PCU queues; candidate metric footprint not reserved',
                          'continuous_following': False, 'microscopic_lane_changes': False,
                          'incidents': False, 'lane_blockage_1800_seconds': False,
                          'fixed_public_fleet': False, 'heavy_vehicles': False},
                visual={'stopline_and_spacing': 'event-based queue reconstruction, not continuous native positions',
                        'arrival_notice': '5000 real ms only on confirmed arrivals with verified final position',
                        'accident_from_visual_overlap': False},
                code_inventory=sorted(source_hashes()),
                source_sha256=source_hashes([config, catalog, catalog.parent / 'pom.xml', catalog.parent / 'maven-isolated.cmd',
                                             *inputs.values(), SCENARIO / 'map.osm',
                                             SCENARIO / 'processing-report.json', SCENARIO / 'osm-source.json']))


def _safe_cmd_path(path):
    value = str(Path(path).resolve())
    if any(character in value for character in '\r\n%!' + '"'):
        raise ValueError('Batch wrapper paths must not contain CR/LF, percent, exclamation or quote characters')
    return value


def build_files(directory, maven):
    """Create only new files; never clean, overwrite or repurpose target/classes."""
    directory, maven = Path(directory).resolve(), Path(maven).resolve()
    permitted_scenario = (directory.name == 'build' and directory.parent.name.startswith('verified-')
                          and directory.parent.parent == SCENARIO / 'montecarlo')
    if not directory.is_relative_to(PROJECT / 'target') and not permitted_scenario:
        raise ValueError('An isolated build must be new below target/ or scenarios/zona1/montecarlo/verified-*/build')
    if directory.exists():
        raise ValueError('The isolated build directory must not exist')
    if not maven.is_file():
        raise ValueError(f'Maven executable does not exist: {maven}')
    _safe_cmd_path(directory); _safe_cmd_path(maven)
    catalog = json.loads((SCENARIO / 'agent-types-road-v1.json').read_text(encoding='utf-8-sig'))
    catalog['scenario_version'] = SUBSET_VERSION
    catalog['description'] = ('Explicit runnable subset: motorcycles and cars only. Heavy weight is zero; '
                              'all seven definitions remain for the native profile contract. No fixed public fleet.')
    catalog['allocation']['road_weights']['TransportePesado'] = 0
    namespace = 'http://maven.apache.org/POM/4.0.0'
    ET.register_namespace('', namespace)
    qualified = lambda value: '{' + namespace + '}' + value
    root = ET.parse(PROJECT / 'pom.xml').getroot()
    build = root.find(qualified('build'))
    for name, path in [('directory', directory / 'build'), ('sourceDirectory', PROJECT / 'src/main/java'),
                       ('testSourceDirectory', PROJECT / 'src/test/java')]:
        element = build.find(qualified(name))
        if element is None:
            element = ET.SubElement(build, qualified(name))
        element.text = path.as_posix()
    for name, item, folder in [('resources', 'resource', 'src/main/resources'),
                               ('testResources', 'testResource', 'src/test/resources')]:
        previous = build.find(qualified(name))
        if previous is not None:
            build.remove(previous)
        collection = ET.SubElement(build, qualified(name))
        resource = ET.SubElement(collection, qualified(item))
        ET.SubElement(resource, qualified('directory')).text = (PROJECT / folder).as_posix()
    # Compile only this scenario and its QSim extension, never a stale lab class.
    compiler = next(plugin for plugin in build.find(qualified('plugins'))
                    if plugin.findtext(qualified('artifactId')) == 'maven-compiler-plugin')
    settings = compiler.find(qualified('configuration'))
    for group, item in [('includes', 'include'), ('testIncludes', 'testInclude')]:
        collection = ET.SubElement(settings, qualified(group))
        for pattern in ('gt/edu/uvg/sim/zona1/**/*.java', 'org/matsim/core/mobsim/qsim/qnetsimengine/**/*.java'):
            ET.SubElement(collection, qualified(item)).text = pattern
    ET.SubElement(settings, qualified('proc')).text = 'none'
    ET.SubElement(settings, qualified('debug')).text = 'false'
    # Maven debug=false merely omits -g; javac then still emits line/source
    # metadata. Pin -g:none explicitly to match the independent fixture build.
    compiler_args = settings.find(qualified('compilerArgs'))
    if compiler_args is None:
        compiler_args = ET.SubElement(settings, qualified('compilerArgs'))
    ET.SubElement(compiler_args, qualified('arg')).text = '-g:none'
    directory.mkdir(parents=True, exist_ok=False)
    pom = directory / 'pom.xml'
    ET.indent(root)
    ET.ElementTree(root).write(pom, encoding='utf-8', xml_declaration=True)
    catalog_path = directory / 'agent-types-road-subset.json'
    catalog_path.write_text(json.dumps(catalog, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    # Do not CALL: its second expansion would reinterpret values in quoted paths.
    wrapper = directory / 'maven-isolated.cmd'
    wrapper.write_text('@echo off\r\nsetlocal DisableDelayedExpansion\r\n"' + _safe_cmd_path(maven)
                       + '" -f "' + _safe_cmd_path(pom) + '" %*\r\n', encoding='utf-8', newline='')
    parsed_catalog = load_catalog(catalog_path)
    validate_road_access(SCENARIO / 'network.xml', parsed_catalog)
    return dict(schema=SCHEMA, status='build_files_created', simulation_executed=False,
                directory=str(directory), pom=str(pom), maven_wrapper=str(wrapper), wrapper=str(wrapper),
                agent_catalog=str(catalog_path), catalog=str(catalog_path), classes=str(directory / 'build/classes'),
                compile_classes=str(directory / 'build/classes'),
                test_classes=str(directory / 'build/test-classes'),
                dependency_classpath=str(directory / 'dependencies.txt'),
                generated_sha256={str(path): sha256(path) for path in (pom, wrapper, catalog_path)})


def verify_run(directory, receipt):
    verify_sources(receipt)
    directory = Path(directory).resolve()
    manifest = load_manifest(directory)
    if manifest['status'] != 'completed' or manifest.get('validation', {}).get('status') != 'valid':
        raise ValueError('Run is not completed and validated')
    if manifest['demand_seed'] != receipt['demand_seed'] or manifest['matsim_seed'] != receipt['matsim_seed']:
        raise ValueError('Run seeds do not match the preflight contract')
    count = manifest['counts']['planned_persons']
    if not receipt['minimum'] <= count <= receipt['maximum']:
        raise ValueError('Run population is outside the requested range')
    if count != receipt.get('predicted_persons', count):
        raise ValueError('Run population draw does not match the seeded inclusive range')
    if manifest.get('spatial_demand') is not None:
        raise ValueError('A gateway run cannot satisfy the historical network contract')
    original_bytes = (directory / 'run-manifest.json').read_bytes()
    # Existing full event/hash/iteration validation mutates this dictionary only.
    validate_outputs(directory, manifest)
    if 'expected_catalog' in receipt:
        if manifest.get('scenario_version') != SUBSET_VERSION or manifest.get('agent_configuration', {}).get('catalog') != receipt['expected_catalog']:
            raise ValueError('Run road profile catalog/version differs from the verified subset')
        if manifest.get('population_generation', {}).get('massive_authorized') is not True:
            raise ValueError('Missing explicit massive authorization in the generated manifest')
        if manifest.get('public_transport', {}).get('enabled') is not False:
            raise ValueError('Unexpected public fleet in the road-only subset')
    requested = parameters(directory / 'config-simz1.xml') if receipt.get('historical_input_sha256') else {}
    for key, expected_hash in receipt.get('historical_input_sha256', {}).items():
        path = (directory / requested[key]).resolve()
        if not path.is_relative_to(directory) or sha256(path) != expected_hash:
            raise ValueError(f'Run input differs from the pinned historical scenario: {key}')
    effective = parameters(directory / 'output/output_config.xml')
    for key, expected in receipt['expected_configuration'].items():
        actual = effective.get(key)
        # Disabled modules may not serialize if absent: native defaults are explicit here.
        if actual is None and key in ('transit.useTransit', 'simz1IncidentConsequences.enabled',
                                      'simz1IncidentConsequences.durationSeconds', 'simz1LanePolicy.enabled'):
            actual = EXPECTED[key]
        numeric = key in ('zona1Priority.stopSeconds', 'zona1Priority.maxYieldSeconds',
                          'zona1WithinDayRouting.agentShare', 'qsim.flowCapacityFactor', 'qsim.storageCapacityFactor')
        if actual != expected and not (numeric and actual is not None and float(actual) == float(expected)):
            if key == 'qsim.stuckTime' and actual == '00:00:10':
                continue
            raise ValueError(f'Effective configuration mismatch: {key}={actual!r}, expected {expected!r}')
    admission = manifest.get('admission_execution', {})
    if admission.get('verification') != 'effective_config_matches' or admission.get('force_after_stuck_time') is not False:
        raise ValueError('Missing effective strict admission verification')
    if (directory / 'run-manifest.json').read_bytes() != original_bytes:
        raise ValueError('Run manifest changed during read-only validation')
    return dict(schema=SCHEMA, status='completed_and_revalidated', full_requested_suite='BLOCKED',
                simulation_executed=False, run_id=manifest['run_id'], population=count,
                run_manifest_sha256=hashlib.sha256(original_bytes).hexdigest(),
                effective_configuration=manifest['effective_configuration_validation'],
                admission_execution=admission, validation=manifest['validation'],
                iterations=manifest['iterations'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare = commands.add_parser('build-files')
    prepare.add_argument('--directory', type=Path, required=True)
    prepare.add_argument('--maven', type=Path, required=True)
    pre = commands.add_parser('preflight')
    pre.add_argument('--config', type=Path, default=SCENARIO / 'config-simz1.xml')
    pre.add_argument('--agent-catalog', type=Path, required=True)
    pre.add_argument('--min-agents', type=int, required=True)
    pre.add_argument('--max-agents', type=int, required=True)
    pre.add_argument('--seed', type=int, required=True)
    pre.add_argument('--qsim-threads', type=int, choices=(1, 4), default=4)
    for name in ('verify-sources', 'verify-run'):
        command = commands.add_parser(name)
        command.add_argument('--preflight', type=Path, required=True)
        if name == 'verify-run':
            command.add_argument('--run-dir', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'build-files':
            result = build_files(args.directory, args.maven)
        elif args.command == 'preflight':
            result = preflight(args.config, args.agent_catalog, args.min_agents, args.max_agents, args.seed, args.qsim_threads)
        else:
            receipt = json.loads(args.preflight.read_text(encoding='utf-8-sig'))
            if receipt.get('schema') != SCHEMA:
                raise ValueError('Unsupported preflight receipt')
            result = verify_sources(receipt) if args.command == 'verify-sources' else verify_run(args.run_dir, receipt)
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    except (OSError, ValueError, KeyError, RuntimeError, ET.ParseError, subprocess.CalledProcessError) as error:
        print(json.dumps(dict(schema=SCHEMA, status='BLOCKED', error=str(error)), ensure_ascii=True))
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
