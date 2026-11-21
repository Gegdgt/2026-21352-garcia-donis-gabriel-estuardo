from simz1_history_fixtures import dataset
"""Small Prompt 2 preflight/diagnostic tests. No Maven or QSim is launched."""
from pathlib import Path
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from ejecutar_simz1 import diagnostico_causal_log, ejecutar, main
from generate_montecarlo_z1 import generar, SCENARIO
from simz1_config_validation import ConfigurationError, validate_configuration
from simz1_native_validation import NativeDecisionAudit
from simz1_run import MANIFEST, artifact, atomic_json, load_manifest, parameters, sha256


def set_option(root, module, name, value):
    group = root.find(f"module[@name='{module}']")
    if group is None:
        group = ET.SubElement(root, 'module', name=module)
    param = group.find(f"param[@name='{name}']")
    if param is None:
        param = ET.SubElement(group, 'param', name=name)
    param.set('value', str(value))


class SignalsConfigurationTests(unittest.TestCase):
    def test_preflight_combinations_signals_are_independent_of_lanes(self):
        for lanes in ('true', 'false'):
            for signals in ('true', 'false'):
                root = ET.parse(SCENARIO/'config-simz1.xml').getroot()
                set_option(root, 'qsim', 'useLanes', lanes)
                set_option(root, 'signalsystems', 'useSignalsystems', signals)
                result = validate_configuration(root)
                self.assertEqual(result['use_lanes'], lanes == 'true')
                self.assertEqual(result['signals_enabled'], signals == 'true')
                self.assertFalse(result['remove_stuck_vehicles'])
                self.assertEqual(result['stuck_time_seconds'], 10)
        set_option(root, 'signalsystems', 'useSignalsystems', 'true')
        set_option(root, 'qsim', 'usingFastCapacityUpdate', 'true')
        self.assertTrue(validate_configuration(root)['using_fast_capacity_update'])
        invalid = [('qsim', 'removeStuckVehicles', 'true', 'incompatible'),
                   ('travelTimeCalculator', 'separateModes', 'true', 'separateModes'),
                   ('travelTimeCalculator', 'calculateLinkToLinkTravelTimes', 'false', 'requiere'),
                   ('qsim', 'numberOfThreads', '0', 'entero positivo'),
                   ('qsim', 'stuckTime', '-1', 'no negativo'),
                   ('signalsystems', 'useSignalsystems', 'yes', 'true o false')]
        for module, name, value, error in invalid:
            root = ET.parse(SCENARIO/'config-simz1.xml').getroot()
            set_option(root, module, name, value)
            with self.subTest(name=name), self.assertRaisesRegex(ConfigurationError, error):
                validate_configuration(root)

    def test_generator_rejects_invalid_config_before_creating_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ET.parse(SCENARIO/'config-simz1.xml').getroot()
            set_option(root, 'qsim', 'removeStuckVehicles', 'true')
            source = Path(folder)/'invalid.xml'
            ET.ElementTree(root).write(source)
            directory = Path(folder)/'no generated run'
            with self.assertRaisesRegex(ConfigurationError, 'incompatible'):
                generar(source, directory, 7, agents=1, corridor_policy='redistribute')
            self.assertFalse(directory.exists())
            self.assertEqual(ET.parse(source).find("module[@name='qsim']/param[@name='removeStuckVehicles']").get('value'), 'true')
            source.write_text('<config><module')
            with self.assertRaisesRegex(ConfigurationError, 'XML de configuracion mal formado') as failure:
                validate_configuration(source)
            self.assertIsInstance(failure.exception.__cause__, ET.ParseError)
            with self.assertRaisesRegex(ConfigurationError, 'XML de configuracion mal formado'):
                generar(source, directory, 7, agents=1, corridor_policy='redistribute')
            self.assertFalse(directory.exists())

    def test_missing_separate_modes_default_is_derived_but_explicit_true_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = ET.parse(SCENARIO/'config-simz1.xml').getroot()
            calculator = root.find("module[@name='travelTimeCalculator']")
            separate = calculator.find("param[@name='separateModes']")
            if separate is not None:
                calculator.remove(separate)
            # Preserve the source dataset while testing a new config path with spaces.
            for module in ('network', 'facilities', 'vehicles', 'signalsystems'):
                for param in root.findall(f"module[@name='{module}']/param"):
                    value = param.get('value', '')
                    if value.endswith(('.xml', '.xml.gz')):
                        param.set('value', str((SCENARIO/value).resolve()))
            source = Path(folder)/'source missing default.xml'
            ET.ElementTree(root).write(source)
            before = sha256(source)
            directory = Path(folder)/'derived no signals'
            generar(source, directory, 17, agents=1, corridor_policy='redistribute', signals=False)
            self.assertEqual(parameters(directory/'config-simz1.xml')['travelTimeCalculator.separateModes'], 'false')
            self.assertEqual(sha256(source), before)
            self.assertTrue(any(c['parameter'] == 'travelTimeCalculator.separateModes' and
                                c['before'] is None and 'Derived missing default' in c['reason']
                                for c in load_manifest(directory)['configuration_overrides']))
            set_option(root, 'travelTimeCalculator', 'separateModes', 'true')
            ET.ElementTree(root).write(source)
            rejected = Path(folder)/'explicit true rejected'
            with self.assertRaisesRegex(ConfigurationError, 'separateModes'):
                generar(source, rejected, 17, agents=1, corridor_policy='redistribute', signals=False)
            self.assertFalse(rejected.exists())
            self.assertEqual(parameters(source)['travelTimeCalculator.separateModes'], 'true')

    def test_generator_options_preserve_inputs_seed_and_record_overrides(self):
        with tempfile.TemporaryDirectory() as folder:
            original_hash = sha256(SCENARIO/'config-simz1.xml')
            snapshots = []
            for index, enabled in enumerate((True, False)):
                directory = Path(folder)/f'paired run {index}'
                generar(SCENARIO/'config-simz1.xml', directory, 20261004, agents=1,
                        corridor_policy='redistribute', signals=enabled, incidents=enabled,
                        within_day_routing=enabled, use_lanes=True, qsim_threads=1 if enabled else 4)
                values = parameters(directory/'config-simz1.xml')
                for key in ('signalsystems.useSignalsystems', 'zona1Diagnostics.incidentsEnabled',
                            'zona1WithinDayRouting.enabled'):
                    self.assertEqual(values[key], str(enabled).lower())
                self.assertEqual(values['qsim.numberOfThreads'], '1' if enabled else '4')
                self.assertEqual(values['qsim.stuckTime'], '10')
                self.assertEqual(values['qsim.removeStuckVehicles'], 'false')
                state = load_manifest(directory)
                self.assertEqual(state['configuration_validation']['signals_enabled'], enabled)
                # The demand report includes the distinct run_dir; compare the
                # actual plans, vehicles and physical inputs, not provenance paths.
                snapshots.append({k:v['sha256'] for k,v in state['inputs'].items()
                                  if k not in ('config', 'demand_report')})
                self.assertTrue(any(c['parameter']=='zona1Diagnostics.incidentsEnabled'
                                    for c in state['configuration_overrides']))
            self.assertEqual(*snapshots)
            self.assertEqual(sha256(SCENARIO/'config-simz1.xml'), original_hash)

    def test_launcher_cli_propagates_disabled_flags(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/'CLI flags with spaces'
            args = ['ejecutar_simz1.py', '--seed', '17', '--agents', '1', '--corridor-policy', 'redistribute',
                    '--run-dir', str(directory), '--no-signals', '--no-incidents', '--no-use-lanes',
                    '--no-within-day-routing', '--qsim-threads', '4', '--iterations', '2']
            with patch('sys.argv', args), patch('ejecutar_simz1.ejecutar') as launch:
                main()
            self.assertEqual(launch.call_args.args[-1], 2)
            values = parameters(directory/'config-simz1.xml')
            self.assertEqual(values['qsim.useLanes'], 'false')
            self.assertEqual(values['signalsystems.useSignalsystems'], 'false')
            self.assertEqual(values['zona1Diagnostics.incidentsEnabled'], 'false')
            self.assertEqual(values['zona1WithinDayRouting.enabled'], 'false')
            signal_root = ET.parse(values['signalsystems.signalsystems']).getroot()
            self.assertFalse(any(e.tag.rsplit('}', 1)[-1] == 'lane' for e in signal_root.iter()))
            changes = load_manifest(directory)['configuration_overrides']
            self.assertTrue(any(c['parameter']=='signalsystems.lane_references' for c in changes))

    def test_launcher_preflight_retains_failed_attempt_and_success_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/'invalid attempt'
            generar(SCENARIO/'config-simz1.xml', directory, 17, agents=1, corridor_policy='redistribute')
            path = directory/'config-simz1.xml'
            root = ET.parse(path).getroot()
            set_option(root, 'qsim', 'removeStuckVehicles', 'true')
            ET.ElementTree(root).write(path)
            state = load_manifest(directory)
            state['inputs']['config'] = artifact(directory, path)
            atomic_json(directory/MANIFEST, state)
            latest = Path(folder)/'latest-successful.json'
            latest.write_text('previous successful reference')
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo') as launch:
                with self.assertRaisesRegex(ConfigurationError, 'incompatible'):
                    ejecutar(directory, latest_path=latest)
            launch.assert_not_called()
            failed = load_manifest(directory)
            self.assertEqual(failed['failure_category'], 'configuration_invalid')
            self.assertEqual(failed['returncode_origin'], 'not_started')
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(latest.read_text(), 'previous successful reference')
            self.assertFalse((directory/'output').exists())

    def test_first_causal_error_and_exception_chain_are_not_warnings(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'matsim-run.log'
            log = ('WARN QueueWithBuffer: traffic remains\nWARN CharyparNagelActivityScoring\n'
                   'java.lang.RuntimeException: shutdown failed\n'
                   'Caused by: java.io.IOException: original disk error\n'
                   '[ERROR] BUILD FAILURE\n')
            path.write_text(log)
            diagnostic = diagnostico_causal_log(path)
            self.assertEqual(diagnostic['first_error']['line'], 3)
            self.assertIn('original disk error', diagnostic['root_cause']['message'])
            self.assertEqual(diagnostic['category'], 'runtime_exception')
            self.assertEqual(path.read_text(), log)
            path.write_text(log.replace('[ERROR] BUILD FAILURE\n', '')+
                            '[ERROR] Shutdown failure\njava.lang.IllegalStateException: secondary\n'
                            'Caused by: java.lang.IllegalArgumentException: CONFIG_INVALID secondary\n')
            first = diagnostico_causal_log(path)
            self.assertEqual(first['category'], 'runtime_exception')
            self.assertEqual(first['first_error']['line'], 3)
            self.assertEqual(len(first['cause_chain']), 1)
            self.assertIn('original disk error', first['root_cause']['message'])
            path.write_text('[ERROR] COMPILATION ERROR :\n[ERROR] X.java:[1,2] cannot find symbol\n')
            self.assertEqual(diagnostico_causal_log(path)['category'], 'compilation_error')
            self.assertIn('cannot find symbol', diagnostico_causal_log(path)['first_error']['message'])
            path.write_text('SIMZ1_CONFIGURATION_ERROR calculateLinkToLinkTravelTimes\n')
            self.assertEqual(diagnostico_causal_log(path)['category'], 'configuration_invalid')
            path.write_text('[ERROR] Failed to execute goal exec:java\n[ERROR] \n'
                            '[ERROR] java.lang.IllegalArgumentException: original error\n')
            self.assertEqual(diagnostico_causal_log(path)['first_error']['line'], 3)

    def test_native_waits_forcing_and_route_abort_are_distinct(self):
        audit = NativeDecisionAudit()
        for reason in ('signal_red', 'signal_yellow', 'priority_stop', 'storage_wait', 'storage_forced_move'):
            audit.consume(ET.Element('event', type='simz1NativeDecision', reason=reason,
                                     decision='WAIT' if reason != 'storage_forced_move' else 'FORCE',
                                     signalState='GREEN', person='p', vehicle='v', link='a', nextLink='b'))
        summary = audit.summary()
        self.assertEqual(summary['forced_storage_moves'], 1)
        self.assertEqual(summary['physical_stability']['status'], 'not_demonstrated')
        self.assertFalse(summary['physical_stability']['proven'])
        self.assertEqual(summary['reasons']['signal_red'], 1)
        with self.assertRaisesRegex(ValueError, 'ABORT nativo.*WAIT por rojo'):
            audit.consume(ET.Element('event', type='simz1NativeDecision', reason='turn_abort_disconnected',
                                     person='p', vehicle='v', link='a', nextLink='b'))
        for state in ('GREEN', 'YELLOW', 'OFF'):
            NativeDecisionAudit().consume(ET.Element('event', type='simz1NativeDecision', reason='turn_go',
                                                     signalState=state, nativeHasGreen='true'))
        for state in ('RED', 'REDYELLOW'):
            with self.assertRaisesRegex(ValueError, 'senal nativa'):
                NativeDecisionAudit().consume(ET.Element('event', type='simz1NativeDecision', reason='turn_go',
                                                         signalState=state))
        with self.assertRaisesRegex(ValueError, 'cola nativa'):
            NativeDecisionAudit().consume(ET.Element('event', type='simz1NativeDecision',
                reason='storage_forced_move', decision='FORCE', nativeHasGreen='false',
                signalState='NOT_GREEN_NATIVE_COLOR_UNAVAILABLE'))

    def test_progress_aggregates_deltas_and_requires_deadlock_evidence(self):
        audit = NativeDecisionAudit()
        values = dict(type='simz1Progress', time='60', iteration='0', elapsedSimSeconds='60', stepCount='61',
                      processCpuNanos='400', wallNanos='500', linkTransitions='2', arrivals='1',
                      activeVehicles='3', rerouteCalculations='1', waitSignal='4', waitStorage='2',
                      waitPriority='1', forcedMoves='0', threadDeadlocks='0', classification='progress_observed')
        audit.consume(ET.Element('event', **values))
        values.update(time='120', processCpuNanos='-1', stepCount='121', activeVehicles='1',
                      classification='traffic_wait_observed')
        audit.consume(ET.Element('event', **values))
        result = audit.summary()
        self.assertEqual(result['progress_samples'], 2)
        progress = result['progress']
        self.assertEqual(progress['process_cpu_nanos'], 400)
        self.assertEqual(progress['cpu_timed_samples'], 1)
        self.assertEqual(progress['wall_nanos'], 1000)
        self.assertEqual(progress['elapsed_sim_seconds'], 120)
        self.assertEqual(progress['max_simulated_time'], 120)
        self.assertEqual(progress['wait_signal'], 8)
        self.assertEqual(progress['max_active_vehicles'], 3)
        self.assertEqual(progress['max_thread_deadlocks'], 0)
        values['classification'] = 'thread_deadlock_detected'
        with self.assertRaisesRegex(ValueError, 'deadlock sin evidencia'):
            audit.consume(ET.Element('event', **values))
        values['threadDeadlocks'] = '2'
        audit.consume(ET.Element('event', **values))
        self.assertEqual(audit.summary()['progress']['max_thread_deadlocks'], 2)

    def test_wait_categories_and_turn_restrictions_remain_distinct(self):
        audit = NativeDecisionAudit()
        for reason, category in (('priority_stop', 'mandatory_stop'), ('priority_fairness', 'yield'),
                                 ('signal_red', 'signal'), ('storage_wait', 'insufficient_storage'),
                                 ('congestion_queue', 'congestion')):
            audit.consume(ET.Element('event', type='simz1NativeDecision', reason=reason,
                                     decision='WAIT', waitCategory=category))
        self.assertEqual(audit.summary()['wait_categories'], {'mandatory_stop': 1, 'yield': 1,
                         'signal': 1, 'insufficient_storage': 1, 'congestion': 1})
        with self.assertRaisesRegex(ValueError, 'ABORT nativo'):
            audit.consume(ET.Element('event', type='simz1NativeDecision', reason='turn_restriction',
                                     decision='ABORT', waitCategory='turn_restriction'))
        with self.assertRaisesRegex(ValueError, 'Categoria de espera'):
            NativeDecisionAudit().consume(ET.Element('event', type='simz1NativeDecision',
                                          reason='storage_wait', decision='WAIT', waitCategory='guessed'))


class CausalDiagnosticTests(unittest.TestCase):
    """Only log extraction and an inert launcher double; never a JVM/simulation."""
    history = dataset('cursor')
    log_sha = 'f986ce076a40f3659936572d52ee222e0c312a96a1a891bce4366b40c0cde367'

    def historical_bytes(self):
        data=(self.history/'matsim-run.log').read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),self.log_sha)
        manifest=json.loads((self.history/'historical-manifest.json').read_bytes())
        self.assertEqual(manifest['run_id'],'simz1-8545ef106cbe43ce8fabb81bf0bc0a41')
        self.assertEqual(manifest['causal_exception_chain'],[])
        roster=json.loads((self.history/'roster.json').read_bytes())
        self.assertEqual(next(r for r in roster if r['vehicle_id']=='freight_000002')['departure_seconds'],52.69614317752584)
        return data

    def test_historical_propagated_cursor_and_secondary_cleanup(self):
        data=self.historical_bytes()
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'complete-historical.log';path.write_bytes(data)
            result=diagnostico_causal_log(path)
            self.assertEqual(result['diagnostic_status'],'explicit_propagated_chain')
            self.assertIn('Occupancy route cursor mismatch for z1_97936: 0',result['root_cause']['message'])
            self.assertEqual([e['depth'] for e in result['cause_chain']],[0,1])
            self.assertIn('Thread class',result['first_logged_error']['message'])
            self.assertEqual(result['first_error']['line'],2532)
            cleanup=[b for b in result['secondary_errors'] if b['context']=='cleanup']
            self.assertTrue(any('Freight abort without departure: freight_000002' in e['message']
                                for b in cleanup for e in b['evidence']))
            self.assertEqual(path.read_bytes(),data)

    def diagnostic(self, text):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'log';path.write_text(text,encoding='utf-8')
            return diagnostico_causal_log(path)

    def test_incomplete_logs_report_uncertainty(self):
        for log in ('[ERROR] BUILD FAILURE\n',
                    'ERROR worker failed\njava.lang.IllegalStateException: cleanup only\n',
                    'SIMZ1_CAUSE failure; simulation remains invalid\nSIMZ1_CAUSE 0 java.lang.RuntimeException: partial\n'):
            with self.subTest(log=log):
                result=self.diagnostic(log)
                self.assertIsNone(result['root_cause']);self.assertTrue(result['uncertainty'])
                self.assertNotEqual(result['diagnostic_status'],'explicit_propagated_chain')

    def test_suppressed_and_later_exceptions_do_not_replace_cause(self):
        log=('SIMZ1_CAUSE failure; simulation remains invalid\n'
             'SIMZ1_CAUSE 0 [root] java.lang.RuntimeException: step failed\n'
             'SIMZ1_CAUSE 1 [cause] java.lang.IllegalStateException: primary cursor\n'
             'SIMZ1_CAUSE 1 [suppressed] java.io.IOException: cleanup failed\n'
             'SIMZ1_CAUSE end\njava.lang.IllegalStateException: last unrelated exception\n[ERROR] BUILD FAILURE\n')
        result=self.diagnostic(log)
        self.assertIn('primary cursor',result['root_cause']['message'])
        self.assertEqual(len(result['cause_chain']),2)
        self.assertTrue(any(b['context']=='suppressed' for b in result['secondary_errors']))
        self.assertTrue(any('last unrelated' in e['message'] for b in result['secondary_errors'] for e in b['evidence']))

    def test_ambiguous_legacy_branch_and_conflicting_blocks_not_guessed(self):
        prefix='SIMZ1_CAUSE failure; simulation remains invalid\nSIMZ1_CAUSE 0 java.lang.RuntimeException: root\n'
        for log in (prefix+'SIMZ1_CAUSE 1 java.lang.IllegalStateException: one\nSIMZ1_CAUSE 1 java.io.IOException: two\nend of log record\n',
                    prefix+'end of log record\n'+prefix.replace(': root',': another')+'end of log record\n'):
            result=self.diagnostic(log)
            self.assertIsNone(result['root_cause']);self.assertTrue(result['uncertainty'])
            self.assertTrue(result['explicit_cause_blocks'])

    def test_new_manifest_keeps_nonzero_code_and_full_historical_log(self):
        raw=self.historical_bytes()
        with tempfile.TemporaryDirectory() as td:
            folder=Path(td); run=folder/'new-fixture'; latest=folder/'latest-successful.json'
            latest.write_text('previous successful reference')
            with contextlib.redirect_stdout(io.StringIO()):
                generar(SCENARIO/'config-simz1.xml',run,20261023,agents=1,corridor_policy='redistribute',no_freight_transport=True)
            def fail(command, log, **kwargs):
                log.write(raw.decode('utf-8').replace('\r\n','\n'))
                kwargs['process_state'].update(returncode=1,returncode_origin='natural_exit')
                kwargs['on_phase']('shutdown')
                return 1
            with patch('ejecutar_simz1.ejecutar_con_salida_en_vivo',side_effect=fail) as launch, \
                    patch('ejecutar_simz1.validate_outputs') as validate, patch('ejecutar_simz1.publish_success') as publish, \
                    contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError,'codigo 1'):
                    ejecutar(run,latest_path=latest)
            launch.assert_called_once();validate.assert_not_called();publish.assert_not_called()
            failed=load_manifest(run)
            self.assertEqual((failed['status'],failed['returncode'],failed['returncode_origin']),('failed',1,'natural_exit'))
            self.assertEqual(failed['causal_diagnostic_status'],'explicit_propagated_chain')
            self.assertIn('Occupancy route cursor mismatch',failed['root_cause']['message'])
            self.assertEqual(len(failed['causal_exception_chain']),2)
            self.assertTrue(failed['secondary_errors'])
            self.assertEqual((run/'matsim-run.log').read_bytes(),raw)
            self.assertEqual(latest.read_text(),'previous successful reference')


if __name__ == '__main__':
    unittest.main()
