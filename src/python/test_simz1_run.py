"""Small end-to-end contract fixtures; Maven is substituted, never massive demand."""
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ejecutar_simz1 import ejecutar
from generate_montecarlo_z1 import generar, SCENARIO
from simz1_run import (MANIFEST, artifact, atomic_json, load_manifest, parameters, select_run,
                      sha256)


def fake_matsim(command, log, *, env, **kwargs):
    directory = Path(env['SIMZ1_CONFIG']).parent
    params = parameters(directory/'config-simz1.xml')
    output = directory/'output'
    output.mkdir()
    for name, source in [('network', params['network.inputNetworkFile']),
                         ('plans', params['plans.inputPlansFile'])]:
        with gzip.open(output/f'output_{name}.xml.gz', 'wb') as stream:
            if name == 'plans':
                # MATSim PlanRouter/TripRouter replaces legs, retaining person attributes.
                plans=ET.parse(source)
                for attrs in plans.findall('.//leg/attributes'):
                    for child in list(attrs):
                        if child.get('name')=='simz1TripId': attrs.remove(child)
                stream.write(ET.tostring(plans.getroot()))
            else:
                stream.write(Path(source).read_bytes())
    people = ET.parse(params['plans.inputPlansFile']).findall('person')
    events = []
    for i, person in enumerate(people):
        link = person.find('plan/activity').get('link')
        ident = person.get('id')
        time = 22000 + i*120
        for kind, delta in [('departure', 0), ('vehicle enters traffic', 0), ('entered link', 1),
                            ('left link', 61), ('vehicle leaves traffic', 61), ('arrival', 62)]:
            events.append(f'<event type="{kind}" time="{time+delta}" person="{ident}" vehicle="v{i}" link="{link}"/>')
    with gzip.open(output/'output_events.xml.gz', 'wt') as stream:
        stream.write('<events>'+''.join(events)+'</events>')
    output_config = ET.parse(directory/'config-simz1.xml')
    qsim = output_config.find("module[@name='qsim']")
    timestep = qsim.find("param[@name='timeStepSize']")
    if timestep is None:
        timestep = ET.SubElement(qsim, 'param', name='timeStepSize')
    # Real MATSim serializes this duration, even when input omitted the default.
    timestep.set('value', '00:00:01')
    output_config.write(output/'output_config.xml')
    for key, filename in [('network.laneDefinitionsFile', 'output_lanes.xml.gz'),
                          ('signalsystems.signalcontrol', 'output_signal_control_v2.0.xml.gz'),
                          ('signalsystems.signalgroups', 'output_signal_groups_v2.0.xml.gz'),
                          ('signalsystems.signalsystems', 'output_signal_systems_v2.0.xml.gz')]:
        if params.get(key) not in (None, '', 'null'):
            with gzip.open(output/filename, 'wb') as stream:
                stream.write(Path(params[key]).read_bytes())
    last = int(params['controler.lastIteration'])
    (output/'stopwatch.txt').write_text('Iteration\tEND iteration\n'+''.join(f'{i}\t00:00:01\n' for i in range(last+1)))
    for i in range(last+1):
        folder = output/'ITERS'/f'it.{i}'
        folder.mkdir(parents=True)
        (folder/f'{i}.legdurations.txt').write_text('average leg duration: 62 seconds\n')
        for name in ('plans', 'events'):
            shutil.copyfile(output/f'output_{name}.xml.gz', folder/f'{i}.{name}.xml.gz')
        fake_compact(directory,i)
    return 0


def fake_compact(directory,iteration):
    from simz1_trip_table import write_events,validate_compact
    from procesar_eventos_z1 import read_profiles
    from simz1_run import seconds
    folder=directory/'output/ITERS'/f'it.{iteration}'
    path=folder/f'{iteration}.simz1-trips.csv.gz'
    run_id=load_manifest(directory)['run_id']
    horizon=seconds(parameters(directory/'config-simz1.xml')['qsim.endTime'])
    stats=write_events(folder/f'{iteration}.events.xml.gz',path,run_id,iteration,
                       read_profiles(directory/'output/output_plans.xml.gz'),horizon)
    counts=validate_compact(path,run_id,iteration)
    atomic_json(folder/f'{iteration}.simz1-trip-summary.json',dict(schema_version=1,run_id=run_id,iteration=iteration,
                counts=counts,anomalies=stats['anomalies'],completion_rate=stats['completion_rate']))


class RunContractTests(unittest.TestCase):
    def test_replay_vehicle_limits_are_selected_and_fingerprinted(self):
        from simz1_motion import load_selected
        directory = self.prepare('verified vehicle types')
        def with_vehicles(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            with gzip.open(directory/'output/output_vehicles.xml.gz','wt') as stream:
                stream.write('<vehicleDefinitions><vehicleType id="custom"><maximumVelocity meterPerSecond="4"/></vehicleType>'
                             '<vehicle id="v0" type="custom"/></vehicleDefinitions>')
            return 0
        state = self.finish(directory, with_vehicles)
        self.assertEqual(state['admission_execution']['verification'], 'effective_config_matches')
        self.assertEqual(state['admission_execution']['storage_policy'], 'strict-receiver-v1')
        self.assertEqual(state['admission_execution']['qsim_threads'], 4)
        self.assertFalse(state['admission_execution']['native_execution_proven'])  # Fixture files are not a QSim run.
        self.assertEqual(state['effective_vehicles']['sha256'],sha256(directory/'output/output_vehicles.xml.gz'))
        motion = load_selected(select_run(directory))
        self.assertEqual(motion.vehicle_speeds,{'v0':4})
        self.assertIn('effective_vehicles',motion.sources)
        # Changing only vehicles is a mixed/corrupt replay too.
        with gzip.open(directory/'output/output_vehicles.xml.gz','wt') as stream:
            stream.write('<vehicleDefinitions/>')
        with self.assertRaisesRegex(ValueError,'Hash no coincide'):select_run(directory)

    def test_loaded_lanes_and_events_must_belong_to_the_selected_network(self):
        for mismatch in ('lane capacity', 'event lane', 'missing loaded lanes', 'effective storage factor'):
            directory = self.prepare(mismatch)
            def invalid(*args, **kwargs):
                fake_matsim(*args, **kwargs)
                path = directory/'output/output_lanes.xml.gz'
                if mismatch == 'missing loaded lanes':
                    path.unlink()
                elif mismatch == 'effective storage factor':
                    config_path = directory/'output/output_config.xml'
                    config = ET.parse(config_path)
                    config.find("module[@name='qsim']/param[@name='storageCapacityFactor']").set('value', '99')
                    config.write(config_path)
                elif mismatch == 'lane capacity':
                    with gzip.open(path, 'rb') as stream:
                        root = ET.parse(stream).getroot()
                    next(e for e in root.iter() if e.tag.rsplit('}', 1)[-1] == 'capacity').set('vehiclesPerHour', '99999')
                    with gzip.open(path, 'wb') as stream:
                        stream.write(ET.tostring(root))
                else:
                    path = directory/'output/output_events.xml.gz'
                    with gzip.open(path, 'rb') as stream:
                        root = ET.parse(stream).getroot()
                    link = root.find('event').get('link')
                    ET.SubElement(root, 'event', type='entered lane', time='23000',
                                  link=link, lane='queue from another run', vehicle='v0')
                    with gzip.open(path, 'wb') as stream:
                        stream.write(ET.tostring(root))
                return 0
            error = {'lane capacity': 'capacidad de flujo', 'event lane': 'cola ajena',
                     'missing loaded lanes': 'sin output_lanes',
                     'effective storage factor': 'parametros de discretizacion'}[mismatch]
            with self.subTest(mismatch=mismatch), self.assertRaisesRegex(ValueError, error):
                self.finish(directory, invalid)
            self.assertFalse(self.latest.exists())
            self.assertEqual(load_manifest(directory)['failure_category'], 'output_validation_error')

    def test_forced_storage_moves_are_valid_results_without_stability_certificate(self):
        directory = self.prepare('storage forced')
        # This is the historical native-policy contract. New prepared runs are
        # strict by default and must reject the same forced insertion evidence.
        config_path = directory/'config-simz1.xml'
        config = ET.parse(config_path)
        config.find("module[@name='simz1Admission']/param[@name='storagePolicy']").set('value','matsim15-native')
        config.write(config_path)
        state = load_manifest(directory)
        state['inputs']['config'] = artifact(directory,config_path)
        atomic_json(directory/MANIFEST,state)
        def forced(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            path = directory/'output/output_events.xml.gz'
            with gzip.open(path, 'rb') as stream:
                root = ET.parse(stream).getroot()
            ET.SubElement(root, 'event', type='simz1NativeDecision', time='23000',
                          reason='storage_forced_move', decision='FORCE', signalState='GREEN', nativeHasGreen='true',
                          waitSeconds='11', stuckTime='10', removeStuckVehicles='false')
            with gzip.open(path, 'wb') as stream:
                stream.write(ET.tostring(root))
            for iteration in (0, 1):
                shutil.copyfile(path, directory/f'output/ITERS/it.{iteration}/{iteration}.events.xml.gz')
            return 0
        state = self.finish(directory, forced)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['validation']['status'], 'valid')
        stability = state['validation']['physical_stability']
        self.assertEqual(stability['status'], 'not_demonstrated')
        self.assertEqual(stability['interventions'], 2)
        self.assertEqual(stability['forced_storage_moves'], 2)
        self.assertEqual(stability['storage_stuck_removals'], 0)
        self.assertEqual(stability['counting_unit'], 'native_decisions_across_iterations_not_unique_vehicles')
        self.assertFalse(stability['proven'])
        self.assertEqual(state['results']['1']['native_qsim']['forced_storage_moves'], 1)

    def test_native_disconnected_abort_never_published_or_confused_with_signal_wait(self):
        directory = self.prepare('native disconnected')
        def disconnected(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            path = directory/'output/output_events.xml.gz'
            with gzip.open(path, 'rb') as stream:
                root = ET.parse(stream).getroot()
            ET.SubElement(root, 'event', type='simz1NativeDecision', time='23000',
                          reason='signal_red', decision='WAIT', signalState='RED',
                          admissionPolicy='strict-receiver-v1', admissionPolicyVersion='1')
            ET.SubElement(root, 'event', type='simz1NativeDecision', time='23001',
                          reason='turn_abort_disconnected', decision='ABORT', vehicle='corrupt vehicle',
                          admissionPolicy='strict-receiver-v1', admissionPolicyVersion='1')
            with gzip.open(path, 'wb') as stream:
                stream.write(ET.tostring(root))
            return 0
        with self.assertRaisesRegex(ValueError, 'ABORT nativo'):
            self.finish(directory, disconnected)
        self.assertFalse(self.latest.exists())
        failed = load_manifest(directory)
        self.assertEqual(failed['failure_category'], 'output_validation_error')
        self.assertIn('corrupt vehicle', failed['first_causal_error']['message'])

    def test_invalid_physical_transition_never_published(self):
        directory=self.prepare('invalid transition')
        def invalid_transition(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            params=parameters(directory/'config-simz1.xml')
            links=ET.parse(params['network.inputNetworkFile']).findall('links/link')
            start=links[0]
            disconnected=next(link for link in links if link.get('from') != start.get('to'))
            person=ET.parse(params['plans.inputPlansFile']).find('person').get('id')
            content=(f'<event type="departure" person="{person}" time="1" link="{start.get("id")}"/>'
                     f'<event type="vehicle enters traffic" person="{person}" vehicle="car1" time="1" link="{start.get("id")}"/>'
                     f'<event type="left link" vehicle="car1" time="2" link="{start.get("id")}"/>'
                     f'<event type="entered link" vehicle="car1" time="2" link="{disconnected.get("id")}"/>')
            with gzip.open(directory/'output/output_events.xml.gz','wt') as stream:
                stream.write('<events>'+content+'</events>')
            return 0
        with self.assertRaisesRegex(ValueError,'Transicion fisica invalida'):
            self.finish(directory,invalid_transition)
        state=load_manifest(directory)
        self.assertEqual(state['validation']['status'],'invalid')
        self.assertIn('car1',state['error'])
        self.assertFalse(self.latest.exists())

    def test_manifest_separates_horizon_pending_from_completed(self):
        directory=self.prepare('pending horizon')
        def pending_at_horizon(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            path=directory/'output/output_events.xml.gz'
            with gzip.open(path,'rb') as stream:
                root=ET.parse(stream).getroot()
            arrival=root.findall("event[@type='arrival']")[-1]
            arrival.set('type','stuckAndAbort')
            arrival.set('time','86400')
            ET.SubElement(root,'event',type='zona1WithinDayReroute',changed='false',time='86400')
            ET.SubElement(root,'event',type='zona1RerouteStep',time='86400',candidates='1',calculations='1',
                          installed='0',rejected='0',deferred='0',budget='100',cpuNanos='5',wallNanos='8',enabled='true')
            with gzip.open(path,'wb') as stream:
                stream.write(ET.tostring(root))
            for iteration in (0,1):
                shutil.copyfile(path,directory/f'output/ITERS/it.{iteration}/{iteration}.events.xml.gz')
                fake_compact(directory,iteration)
            return 0
        state=self.finish(directory,pending_at_horizon)
        for iteration in ('0','1'):
            counts=state['results'][iteration]['counts']
            self.assertEqual(counts['completed_legs'],1)
            self.assertEqual(counts['pending_legs_at_horizon'],1)
            self.assertEqual(counts['horizon_abort_events'],1)
            self.assertEqual(counts['aborted_before_horizon'],0)
            self.assertEqual(counts['invalid_physical_transitions'],0)
            self.assertEqual(counts['reroute_installations'],0)
            self.assertEqual(counts['reroute_validated_candidates'],1)
            metrics=state['results'][iteration]['rerouting']
            self.assertEqual(metrics['calculations'],1)
            self.assertEqual(metrics['cpu_nanos'],5)
            self.assertEqual(metrics['installed'],0)
        self.assertEqual(state['validation']['status'],'valid')

    def test_explicit_reroute_budget_cannot_change_in_effective_config(self):
        directory=self.prepare('budget changed',reroute_budget=7)
        def changed_budget(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            path=directory/'output/output_config.xml'
            tree=ET.parse(path)
            tree.find("module[@name='zona1WithinDayRouting']/param[@name='maxReroutesPerStep']").set('value','8')
            tree.write(path)
            return 0
        with self.assertRaisesRegex(ValueError,'maxReroutesPerStep'):
            self.finish(directory,changed_budget)
        self.assertFalse(self.latest.exists())

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='simz1 contract ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.latest = self.root/'latest-successful.json'
        self.maven = self.root/'fake maven.cmd'
        self.maven.write_text('')

    def prepare(self, name='run A', seed=31, **options):
        directory = self.root/name
        options.setdefault('drain_seconds',0)  # These original horizon fixtures cut at exactly 86400.
        generar(SCENARIO/'config-simz1.xml', directory, seed, agents=2, corridor_policy='redistribute', **options)
        return directory

    def finish(self, directory, side_effect=fake_matsim):
        with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo', side_effect=side_effect):
            return ejecutar(directory, self.maven, iterations=2, latest_path=self.latest)

    def test_two_runs_spaces_cli_consumers_and_explicit_iteration(self):
        a = self.prepare(matsim_seed=1001)
        self.finish(a)
        first = select_run(latest_path=self.latest)
        b = self.prepare('run B', 32, matsim_seed=1002)
        self.finish(b)
        second = select_run(latest_path=self.latest)
        self.assertNotEqual(first['manifest']['run_id'], second['manifest']['run_id'])
        self.assertNotEqual(first['manifest']['inputs']['plans']['sha256'], second['manifest']['inputs']['plans']['sha256'])
        self.assertEqual(second['manifest']['matsim_seed'], 1002)
        self.assertEqual(select_run(a, 0)['directory'], a)
        for script in ('visualizador_z1.py', 'procesar_eventos_z1.py', 'generar_graficas_z1.py'):
            command = [sys.executable, str(Path(__file__).parent/script), '--run-dir', str(a), '--iteration', '0']
            if script == 'visualizador_z1.py':
                command += ['--output', str(self.root/'viewer with spaces.html')]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertIn(first['manifest']['run_id'], result.stdout)
        html = (self.root/'viewer with spaces.html').read_text(encoding='utf-8')
        payload = json.loads(html.split('<script id="replay-data" type="application/json">')[1].split('</script>')[0])
        self.assertEqual(payload['hud']['run_id'], first['manifest']['run_id'])
        self.assertEqual(payload['hud']['iteration'], 0)
        self.assertEqual(payload['hud']['planned_persons'], 2)
        self.assertEqual(payload['hud']['planned_trips'], 2)
        self.assertEqual(payload['hud']['reconstructed_vehicles'], 2)
        with self.assertRaisesRegex(ValueError, 'sin planes y eventos'):
            select_run(a, 7)

    def test_absent_running_interrupted_and_zero_exit_partial_preserve_latest(self):
        with self.assertRaisesRegex(ValueError, 'No hay latest-successful'):
            select_run(latest_path=self.latest)
        good = self.prepare()
        self.finish(good)
        original = self.latest.read_bytes()
        for status, failure in [('interrupted', KeyboardInterrupt()), ('failed', lambda *a, **k: 0)]:
            directory = self.prepare(status)
            with self.assertRaises((KeyboardInterrupt, RuntimeError)):
                self.finish(directory, failure)
            self.assertEqual(load_manifest(directory)['status'], status)
            self.assertEqual(self.latest.read_bytes(), original)
            with self.assertRaisesRegex(ValueError, 'Corrida no valida'):
                select_run(directory)
        running = self.prepare('running')
        state = load_manifest(running)
        state['status'] = 'running'
        atomic_json(running/MANIFEST, state)
        with self.assertRaisesRegex(ValueError, 'running'):
            select_run(running)
        with self.assertRaisesRegex(ValueError, 'No hay manifiesto'):
            select_run(self.root/'historical output')

    def test_modified_or_mixed_artifacts_rejected(self):
        a = self.prepare()
        b = self.prepare('B', 33)
        self.finish(a)
        self.finish(b)
        shutil.copyfile(b/'output/output_plans.xml.gz', a/'output/output_plans.xml.gz')
        with self.assertRaisesRegex(ValueError, 'Hash no coincide'):
            select_run(a)
        (b/'output/output_events.xml.gz').unlink()
        with self.assertRaisesRegex(ValueError, 'ausente'):
            select_run(b)

    def test_truncated_xml_and_incomplete_iteration_never_published(self):
        for name in ('truncated', 'incomplete'):
            directory = self.prepare(name)
            def broken(*args, **kwargs):
                result = fake_matsim(*args, **kwargs)
                if name == 'truncated':
                    with gzip.open(directory/'output/output_events.xml.gz', 'wt') as stream:
                        stream.write('<events><event')
                else:
                    (directory/'output/stopwatch.txt').write_text('Iteration\tEND iteration\n0\t00:00:01\n1\t\n')
                return result
            with self.assertRaises((ET.ParseError, ValueError)):
                self.finish(directory, broken)
            self.assertFalse(self.latest.exists())

    def test_interrupt_retains_completed_iteration_evidence(self):
        directory = self.prepare()
        def interrupted(*args, **kwargs):
            fake_matsim(*args, **kwargs)
            (directory/'output/stopwatch.txt').write_text('Iteration\tEND iteration\n0\t00:00:01\n1\t\n')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.finish(directory, interrupted)
        state = load_manifest(directory)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['iterations']['completed'], [0])
        self.assertFalse(self.latest.exists())

    def test_options_preserved_and_cli_overrides_recorded(self):
        a = self.prepare(within_day_routing=False, routing_share=.2)
        params = parameters(a/'config-simz1.xml')
        self.assertEqual(params['qsim.useLanes'], 'true')
        self.assertEqual(params['zona1WithinDayRouting.enabled'], 'false')
        self.assertEqual(params['zona1WithinDayRouting.agentShare'], '0.2')
        self.assertTrue(Path(params['network.laneDefinitionsFile']).is_relative_to(a))
        manifest = load_manifest(a)
        self.assertTrue(any(c['parameter'] == 'zona1WithinDayRouting.enabled' and c['after'] == 'false'
                            for c in manifest['configuration_overrides']))
        b = self.prepare('without lanes', use_lanes=False)
        self.assertEqual(parameters(b/'config-simz1.xml')['qsim.useLanes'], 'false')
        self.assertFalse(ET.parse(parameters(b/'config-simz1.xml')['signalsystems.signalsystems']).findall('.//{*}signal/{*}lane'))

    def test_atomic_reference_failure_keeps_previous_file(self):
        atomic_json(self.latest, {'run_id': 'previous'})
        original = self.latest.read_bytes()
        with patch('simz1_run.os.replace', side_effect=OSError('interrupted before replace')):
            with self.assertRaises(OSError):
                atomic_json(self.latest, {'run_id': 'next'})
        self.assertEqual(self.latest.read_bytes(), original)
        self.assertEqual(list(self.root.glob('*.tmp')), [])

    def test_all_consumer_clis_fail_without_manifest(self):
        for script in ('visualizador_z1.py', 'procesar_eventos_z1.py', 'generar_graficas_z1.py'):
            result = subprocess.run([sys.executable, str(Path(__file__).parent/script),
                                     '--run-dir', str(self.root/'absent run')],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout+result.stderr)
            self.assertIn('No hay manifiesto SimZ1', result.stderr)

    def test_shutdown_failure_warns_old_selection_until_next_success(self):
        import io
        from visualizador_z1 import export_selected
        good = self.prepare('previous')
        self.finish(good)
        original = self.latest.read_bytes()
        failed = self.prepare('failed shutdown')
        def shutdown_failure(*args, **kwargs):
            fake_matsim(*args, **kwargs)  # Even complete-looking outputs cannot override exit=7.
            kwargs['on_phase']('shutdown')
            args[1].write('WARN QueueWithBuffer\nWARN CharyparNagelActivityScoring\n'
                          '### ITERATION 1 ENDS\nException during shutdown\nBUILD FAILURE\n')
            return 7
        with self.assertRaisesRegex(RuntimeError, 'codigo 7'):
            self.finish(failed, shutdown_failure)
        state = load_manifest(failed)
        self.assertEqual(state['failure_phase'], 'shutdown')
        self.assertEqual(state['returncode'], 7)
        self.assertEqual(state['exception_type'], 'RuntimeError')
        self.assertIn('RuntimeError', state['exception_traceback'])
        self.assertEqual(self.latest.read_bytes(), original)
        console = io.StringIO()
        with patch('sys.stderr', console):
            selection = select_run(latest_path=self.latest)
        self.assertEqual(selection['directory'], good)
        self.assertIn('RESULTADOS ANTERIORES', console.getvalue())
        self.assertIn(state['run_id'], selection['selection_warning'])
        destination = self.root/'old selection.html'
        export_selected(selection, destination)
        html = destination.read_text(encoding='utf-8')
        self.assertIn('RESULTADOS ANTERIORES', html)
        self.assertIn(state['run_id'], html)
        # Pre-latest-attempt manifests still produce the warning; metadata discovery
        # must never change the selected results.
        self.latest.with_name('latest-attempt.json').unlink()
        self.assertEqual(select_run(latest_path=self.latest)['directory'], good)
        newer = self.prepare('new success')
        def success_with_warnings(*args, **kwargs):
            args[1].write('WARN QueueWithBuffer\nWARN CharyparNagelActivityScoring\n')
            return fake_matsim(*args, **kwargs)
        self.finish(newer, success_with_warnings)
        selected = select_run(latest_path=self.latest)
        self.assertEqual(selected['directory'], newer)
        self.assertIsNone(selected['selection_warning'])

    def test_shutdown_interruption_records_trace_and_forced_process_exit(self):
        directory = self.prepare()
        def interrupt(*args, **kwargs):
            kwargs['on_phase']('shutdown')
            kwargs['process_state'].update(returncode=1, returncode_origin='terminated_after_exception')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            self.finish(directory, interrupt)
        state = load_manifest(directory)
        self.assertEqual(state['status'], 'interrupted')
        self.assertEqual(state['failure_phase'], 'shutdown')
        self.assertEqual(state['returncode'], 1)
        self.assertEqual(state['returncode_origin'], 'terminated_after_exception')
        self.assertIn('KeyboardInterrupt', state['exception_traceback'])
        self.assertFalse(self.latest.exists())


if __name__ == '__main__':
    unittest.main()
