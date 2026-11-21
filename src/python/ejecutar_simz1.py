"""Genera demanda SimZ1 por modo, valida su config y ejecuta Maven con registro por corrida."""
import argparse
from collections import deque
from datetime import datetime, timezone
import os
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

from generate_montecarlo_z1 import generar, PROJECT, SCENARIO, add_generation_options, generation_options
from simz1_run import (MANIFEST, load_manifest, atomic_json, artifact, parameters, config_changes,
                      checked_path, validate_outputs, publish_success, completed_iterations, register_attempt,
                      lane_policy_source)
from prepare_simz1 import write_xml
from simz1_config_validation import (ConfigurationError, validate_configuration,
                                    admission_execution_contract, SIMZ1_LAUNCH_MAIN_CLASS)
from simz1_lane_validation import audit_configuration

CONSOLE_KEYWORDS = ('ITERATION', 'MemoryObserver', 'WARN', 'ERROR', 'BUILD SUCCESS', 'BUILD FAILURE',
                    'SIMZ1_CONFIG', 'SIMZ1_PROGRESS', 'SIMZ1_WATCHDOG', 'SIMZ1_TRANSIT_INSTALLED', 'SIMZ1_CAUSE',
                    'SIMZ1_PROCESS_IDENTITY')

def memoria_fisica_bytes():
    """Installed RAM on Windows; physical pages on POSIX. None if detection fails."""
    try:
        if os.name == 'nt':
            import ctypes
            kib = ctypes.c_ulonglong()
            function = ctypes.WinDLL('kernel32', use_last_error=True).GetPhysicallyInstalledSystemMemory
            function.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
            function.restype = ctypes.c_int
            if not function(ctypes.byref(kib)):
                return None
            return kib.value * 1024 or None
        return os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, AttributeError):
        return None


def heap_para_ram(total):
    return 12 if total is not None and total >= 16 * 1024**3 else 8


def diagnostico_log(path):
    """Bound console output even when a high-density run produces a huge log."""
    try:
        with path.open('r', encoding='utf-8', errors='replace') as stream:
            oom = False
            tail = deque(maxlen=20)
            for line in stream:
                oom = oom or 'OutOfMemoryError' in line
                tail.append(line.rstrip('\r\n'))
        return oom, '\n'.join(tail)
    except OSError:
        return False, '(No se pudo leer el log.)'


def _primer_error_log(path):
    """Retain the first causal error and its exception chain, never WARN counts.

    Full process output remains in matsim-run.log; numbered evidence points into
    that unabridged log. Maven's BUILD FAILURE is a result, not a cause.
    """
    first, causes, category = None, [], None
    chain_closed = False
    exception_header_seen = False
    try:
        with Path(path).open(encoding='utf-8', errors='replace') as stream:
            for number, raw in enumerate(stream, 1):
                line = re.sub(r'\x1b\[[0-9;]*m', '', raw).rstrip()
                if not line.strip() or re.search(r'\bWARN(?:ING)?\b', line):
                    continue
                evidence = dict(line=number, message=line)
                is_cause = 'Caused by:' in line
                # A later shutdown exception must not replace the cause of the
                # original execution failure. A stack's first exception header
                # may immediately follow its logger ERROR message.
                content = re.sub(r'^\s*\[(?:ERROR|INFO)\]\s*', '', line).lstrip()
                if not content:
                    continue  # Maven separates exception paragraphs with bare [ERROR] lines.
                header = bool(re.match(r'(?:[\w$]+\.)+[\w$]*(?:Exception|Error)(?::|$)', content))
                logged_error = '[ERROR]' in line or ' ERROR ' in line
                if first is not None and not is_cause:
                    if header and exception_header_seen or logged_error and not header and not content.startswith(('at ', '... ')):
                        chain_closed = True
                if not chain_closed:
                    if 'COMPILATION ERROR' in line or 'maven-compiler-plugin' in line and 'Failed to execute goal' in line:
                        category = 'compilation_error'
                    if 'SIMZ1_CONFIGURATION_ERROR' in line or 'CONFIG_INVALID' in line or 'Configuracion invalida:' in line:
                        category = 'configuration_invalid'
                    if is_cause:
                        causes.append(evidence)
                    exception_header_seen |= header
                summary = any(s in line for s in ('BUILD FAILURE', 'For more information about the errors',
                                                  'Re-run Maven', 'Failed to execute goal', 'COMPILATION ERROR'))
                error = ('[ERROR]' in line or ' ERROR ' in line or 'SIMZ1_CONFIGURATION_ERROR' in line or 'CONFIG_INVALID' in line or
                         re.search(r'(?:Exception|Error)(?::| in thread| during|$)', line))
                if first is None and error and not summary:
                    first = evidence
    except OSError:
        pass
    return dict(category=category or 'runtime_exception', first_error=first,
                cause_chain=causes, root_cause=causes[-1] if causes else first)


def diagnostico_causal_log(path):
    """Prefer the propagated SIMZ1_CAUSE block over chronological ERROR order.

    Evidence retains line numbers in the complete, untouched log. Legacy depth
    blocks are accepted only as a single linear chain, never by last exception.
    """
    fallback = _primer_error_log(path)
    blocks, ordinary, current, stack = [], [], None, []
    header = re.compile(r'^(?:Caused by: |Exception in thread "[^"]+" )?(?:[\w$]+\.)+[\w$]*(?:Exception|Error)(?::|$)')

    def finish_stack():
        if stack:
            ordinary.append(dict(start_line=stack[0]['line'], end_line=stack[-1]['line'],
                evidence=list(stack), context='cleanup' if any('cleanupSim' in e['message'] for e in stack) else 'logged_exception'))
            stack.clear()

    try:
        with Path(path).open(encoding='utf-8', errors='replace') as stream:
            for number, raw in enumerate(stream, 1):
                line = re.sub(r'\x1b\[[0-9;]*m', '', raw).rstrip()
                content = re.sub(r'^\s*\[(?:ERROR|INFO)\]\s*', '', line).lstrip()
                evidence = dict(line=number, message=line)
                if content.startswith('SIMZ1_CAUSE failure;'):
                    finish_stack()
                    current = dict(evidence=[evidence], entries=[], closed=False, truncated=False)
                    blocks.append(current)
                    continue
                if current is not None:
                    if content.startswith('SIMZ1_CAUSE '):
                        current['evidence'].append(evidence)
                        match = re.match(r'SIMZ1_CAUSE (\d+) (?:\[(root|cause|suppressed|injector)\] )?(.+)', content)
                        if match:
                            current['entries'].append(dict(evidence, depth=int(match[1]), relation=match[2], exception=match[3]))
                        if content == 'SIMZ1_CAUSE truncated':
                            current['truncated'] = True
                        if content == 'SIMZ1_CAUSE end':
                            current['closed'] = True
                            current = None
                        continue
                    # Historical reporters did not emit an end marker. A following
                    # record closes that legacy block; EOF alone does not prove it.
                    if content:
                        current['closed'] = all(e['relation'] is None for e in current['entries'])
                        current = None
                if header.match(content) and not content.startswith('Caused by:'):
                    finish_stack(); stack.append(evidence)
                elif stack and (content.startswith(('at ', 'Caused by:', 'Suppressed:', '... '))):
                    stack.append(evidence)
                elif content:
                    finish_stack()
        finish_stack()
    except OSError:
        pass

    candidates = [b for b in blocks if b['entries'] and b['entries'][0]['depth'] == 0]
    primary, secondary = [], []
    status = 'unconfirmed_first_logged_chain'
    uncertainty = 'No complete explicit propagated exception block; chronological log order does not establish the process cause.'
    root = fallback['root_cause'] if fallback['cause_chain'] else None
    first = fallback['first_error']
    if candidates:
        selected = candidates[0]
        entries = selected['entries']
        primary = [e for e in entries if e['relation'] in (None, 'root', 'cause')]
        secondary = [dict(context=e['relation'], evidence=[e]) for e in entries if e['relation'] in ('suppressed','injector')]
        linear = [e['depth'] for e in primary] == list(range(len(primary)))
        same_blocks = all([(e['depth'],e['relation'],e['exception']) for e in b['entries']] ==
                          [(e['depth'],e['relation'],e['exception']) for e in entries] for b in candidates)
        complete = selected['closed'] and not selected['truncated']
        first = entries[0]
        root = primary[-1] if primary and linear and same_blocks and complete else None
        status = 'explicit_propagated_chain' if root else 'ambiguous_or_incomplete_explicit_block'
        uncertainty = None if root else 'Explicit block is truncated, branched without relationship labels, or conflicts with another block.'
        if root:
            fallback['category'] = ('configuration_invalid' if any('CONFIG_INVALID' in e['exception'] or
                'SIMZ1_CONFIGURATION_ERROR' in e['exception'] for e in primary) else 'runtime_exception')
        messages = [e['exception'] for e in primary]
        secondary += [b for b in ordinary if not any(m in e['message'] for m in messages for e in b['evidence'])]
    else:
        secondary = ordinary
    return dict(category=fallback['category'], first_error=first,
        first_logged_error=fallback['first_error'], cause_chain=primary or fallback['cause_chain'], root_cause=root,
        secondary_errors=secondary, explicit_cause_blocks=blocks, diagnostic_status=status, uncertainty=uncertainty)


def ejecutar_con_salida_en_vivo(command, log, *, cwd, env, process_state=None, on_phase=None,
                              on_process=None, on_line=None):
    """Guarda toda la salida; muestra solo palabras clave criticas en consola."""
    details = process_state if process_state is not None else {}
    with subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                          errors='replace', bufsize=1,
                          start_new_session=os.name != 'nt') as process:
        details.update(pid=process.pid, returncode=None, returncode_origin='pending',
                       returncode_process='executor_child_not_native_jvm')
        try:
            if on_process is not None: on_process()
            for line in process.stdout:
                log.write(line)
                log.flush()
                if on_line is not None: on_line(line)
                if any(keyword in line for keyword in CONSOLE_KEYWORDS):
                    print(line, end='', flush=True)
                if '### ITERATION ' in line and ' ENDS' in line:
                    print('Iteracion finalizada; la corrida todavia NO esta validada. '
                          'Espere el cierre de MATSim/Maven y la validacion de archivos.', flush=True)
                if 'start shutdown' in line and on_phase is not None:
                    on_phase('shutdown')
            code = process.wait()
            details.update(returncode=code, returncode_origin='natural_exit')
            if on_process is not None: on_process()
            return code
        except BaseException:
            # Maven en Windows es cmd -> java: detener solo cmd deja QSim escribiendo.
            details['returncode_origin'] = 'observed_after_exception'
            try:
                if process.poll() is None:
                    details['returncode_origin'] = 'terminated_after_exception'
                    if os.name == 'nt':
                        stopped = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                                                 capture_output=True, text=True, check=False, timeout=10)
                        if stopped.returncode:
                            raise RuntimeError(f'taskkill: {stopped.stderr.strip()}')
                    else:
                        os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        if os.name == 'nt':
                            process.kill()
                        else:
                            os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
            except Exception as cleanup_error:
                details['cleanup_error'] = repr(cleanup_error)
                print(f'Error adicional al detener el proceso {process.pid}: {cleanup_error}',
                      file=sys.stderr, flush=True)
                if process.poll() is None:
                    process.kill()
                    process.wait()
            finally:
                details['returncode'] = process.poll()
                if on_process is not None: on_process()
            raise


def run_post_analysis(directory, latest_path=None):
    """Analysis has its own lifecycle; never rewrite a published MATSim manifest."""
    try:
        from simz1_analysis import analyze_run
        result = analyze_run(directory, all_iterations=True, latest_path=latest_path)
    except (Exception, KeyboardInterrupt) as exc:
        # Also isolate import/selection failures outside MATSim's scientific
        # failure handler. A full disk can prevent even the diagnostic write.
        result = dict(status='analysis_failed', error=str(exc) or type(exc).__name__,
                      exception_type=type(exc).__name__,
                      finished_utc=datetime.now(timezone.utc).isoformat(), iterations=[])
        try:
            manifest = load_manifest(directory)
            result['run_id'] = manifest['run_id']
            atomic_json(Path(directory)/'analysis/analysis-status.json', result)
        except Exception as diagnostic_error:
            result['status_write_error'] = str(diagnostic_error)
    if result['status'] != 'completed':
        print(f"analysis_failed: MATSim conserva completed/valid. {result.get('error', '')} "
              f"Reintentar: {sys.executable} python/generar_graficas_z1.py --run-dir \"{directory}\" "
              '--profiles-only --all-iterations', file=sys.stderr, flush=True)
        for item in result.get('iterations', []):
            if item['status'] != 'completed':
                print(f"Iteracion {item['iteration']}: {item.get('error', item['status'])}",
                      file=sys.stderr, flush=True)
    else:
        reused = sum(bool(item.get('reused')) for item in result['iterations'])
        print(f"Analisis completado: {Path(directory)/'analysis'} "
              f"({len(result['iterations'])} iteraciones; {reused} reutilizadas)", flush=True)
    return result


def ejecutar(run_dir, maven=None, offline=False, iterations=None, *, latest_path=None):
    directory=Path(run_dir).resolve()
    config_path=directory/'config-simz1.xml'
    state=load_manifest(directory)
    if state['status'] != 'prepared':
        raise ValueError(f"No se sobrescriben corridas iniciadas: {state['status']}")
    for record in state['inputs'].values():
        checked_path(directory, record)
    try:
        state['configuration_validation'] = validate_configuration(config_path)
        state['admission_execution'] = admission_execution_contract(config_path,
            expected_receipt_route_coverage_policy='planned_stopping_prefix_v2'
            if state['configuration_validation']['whole_vehicle_reservation'] else None)
        admission = state['admission_execution']
        print(f"Admision QSim: {admission['storage_policy']}; hilos={admission['qsim_threads']}; "
              f"receptor bloqueado={admission['receiver_rejection']}; "
              f"FORCE tras stuckTime={admission['force_after_stuck_time']}. "
              'La activacion efectiva se contrastara con output_config.xml.', flush=True)
        lane_selection_source = state.get('lane_configuration_validation', {}).get('selection_source', 'prepared configuration')
        state['lane_configuration_validation'] = audit_configuration(
            config_path, osm_path=lane_policy_source(directory, state))
        state['lane_configuration_validation']['selection_source'] = lane_selection_source
        audit = state['lane_configuration_validation']
        print(f"Carriles detallados: {audit['use_lanes']} ({lane_selection_source}); "
              f"{audit['counts']['assignments']} asignaciones definidas / "
              f"{audit['baseline_queue_metrics'].get('terminal_queues', 0)} colas terminales definidas; "
              f"{audit['counts']['active_detailed_assignments']} asignaciones activas en QSim. "
              'La auditoria estructural no acredita estabilidad fisica.', flush=True)
    except ConfigurationError as exc:
        # Register this attempted launch without starting Maven or touching the
        # last successful pointer. The invalid config remains available as evidence.
        state.update(status='failed', phase='preflight', failure_phase='preflight',
                     failure_category='configuration_invalid', error=str(exc),
                     first_causal_error=dict(message=str(exc), source='configuration preflight'),
                     exception_type=type(exc).__name__, exception_traceback=traceback.format_exc(),
                     returncode=None, returncode_origin='not_started',
                     started_utc=datetime.now(timezone.utc).isoformat(),
                     finished_utc=datetime.now(timezone.utc).isoformat(),
                     validation=dict(status='invalid', error=str(exc)))
        atomic_json(directory/MANIFEST, state)
        register_attempt(directory, state, latest_path)
        print(f'Configuracion invalida antes de Maven: {exc}; latest-successful se conserva.',
              file=sys.stderr, flush=True)
        raise
    before=parameters(config_path)
    root=ET.parse(config_path).getroot()
    def param(module,name):
        element=root.find(f"module[@name='{module}']/param[@name='{name}']")
        if element is None: raise ValueError(f'Falta {module}.{name}')
        return element
    for module,name in [('network','inputNetworkFile'),('plans','inputPlansFile'),('facilities','inputFacilitiesFile')]:
        element=param(module,name)
        path=(directory/element.get('value')).resolve()
        if not path.is_file(): raise FileNotFoundError(path)
        element.set('value',str(path))
    output=(directory/'output').resolve()
    if output.exists(): raise ValueError(f'No se sobrescriben resultados: {output}')
    param('controler','outputDirectory').set('value',str(output))
    param('controler','overwriteFiles').set('value','failIfDirectoryExists')
    if state.get('experiment') and iterations not in (None,state['experiment']['iterations']):
        raise ValueError('Execution iterations differ from selected experiment')
    if iterations is not None:
        if iterations<1: raise ValueError('--iterations debe ser positivo')
        param('controler','firstIteration').set('value','0')
        param('controler','lastIteration').set('value',str(iterations-1))
    write_xml(config_path,root,'config_v2.dtd')
    state['configuration_overrides'] += config_changes(before, parameters(config_path), 'launcher')
    state['inputs']['config'] = artifact(directory, config_path)
    first=int(param('controler','firstIteration').get('value'))
    last=int(param('controler','lastIteration').get('value'))
    state['iterations'] = dict(first=first, last=last, requested=last-first+1, completed=[])
    if state.get('experiment', {}).get('base_scenario_identity'):
        from simz1_configuration_contract import validate_input_configuration
        # The same normalized plan was checked in DryRun. Reject generated
        # drift before the JVM starts; this gate never changes configuration.
        validate_input_configuration(config_path, state['experiment'])
    executable=str(Path(maven).resolve()) if maven else str(PROJECT/('mvnw.cmd' if os.name=='nt' else 'mvnw'))
    if not Path(executable).is_file(): raise FileNotFoundError(executable)
    command=[executable,'--batch-mode','--no-transfer-progress','--errors']
    if offline:command.append('--offline')
    env=os.environ.copy()
    total_ram = memoria_fisica_bytes()
    heap_gib = heap_para_ram(total_ram)
    # The application runs in its own JVM, with an explicit heap. Maven only builds/launches it.
    command += ['compile', 'exec:exec@simz1-fork',
                f'-Dsimz1.mainClass={SIMZ1_LAUNCH_MAIN_CLASS}', f'-Dsimz1.heap={heap_gib}G']
    if (state.get('freight_transport', {}).get('enabled') or
            state['configuration_validation']['whole_vehicle_reservation']):
        # IDE auto-builds can replace target/classes with another Java version.
        # A new service run compiles to its own untouched output directory.
        command.append('-Dsimz1.buildDirectory='+str(directory/'build'))
    env['MAVEN_OPTS'] = '-Xmx2G'
    # No nested exec.args quoting: the absolute config path is passed as plain environment data.
    env['SIMZ1_CONFIG']=str(config_path)
    env['SIMZ1_RUN_ID']=state['run_id']
    state['trip_export_schema']=1
    state.update(status='running', config=str(config_path), output=str(output), command=command,
                 physical_ram_bytes=total_ram, heap_gib=heap_gib, maven_opts=env['MAVEN_OPTS'],
                 java_execution='forked-jvm-v1',
                 started_utc=datetime.now(timezone.utc).isoformat(), phase='running',
                 returncode=None, returncode_origin='pending', process={})
    status_path=directory/MANIFEST
    from simz1_resource_monitor import ProcessLedger
    ledger = ProcessLedger(directory, state['run_id'], os.environ.get('SIMZ1_LAUNCH_ID'))
    state['launch_id'] = os.environ.get('SIMZ1_LAUNCH_ID')
    def save(): atomic_json(status_path, state)
    def process_changed():
        # Persist Popen's PID/return value BEFORE the potentially slower OS query.
        save()
        try: ledger.capture()
        except (OSError,ValueError) as error:
            state['process']['identity_observation_error']=repr(error)
        state['process']['identities'] = list(ledger.value['identities'])
        save()
    def process_line(line):
        if 'SIMZ1_PROCESS_IDENTITY ' in line:
            document=json.loads(line.split('SIMZ1_PROCESS_IDENTITY ',1)[1])
            ledger.record_native(document)
            state['process']['identities']=list(ledger.value['identities'])
            save()
        elif 'SIMZ1_PROCESS_STARTED' in line: process_changed()
        if 'SIMZ1_PROGRESS simulatedTime=' in line and 'observationPhase=after_step' in line:
            match = re.search(r'SIMZ1_PROGRESS simulatedTime=([0-9.]+)', line)
            if match:
                state['last_completed_step'] = dict(seconds=float(match[1]),
                    observed_utc=datetime.now(timezone.utc).isoformat(), source='native_after_step_log')
                save()
    def phase(value):
        state['phase'] = value
        ledger.set_phase(value)
        save()
        if value == 'shutdown':
            print('Cerrando MATSim y escribiendo salidas finales; aun no hay resultado validado.', flush=True)
    save()
    register_attempt(directory, state, latest_path)
    ram_label = f'{total_ram/1024**3:.1f} GiB' if total_ram is not None else 'no detectada (respaldo 8G)'
    print(f"RAM: {ram_label}; Java QSim -Xmx{heap_gib}G; MAVEN_OPTS={env['MAVEN_OPTS']}",flush=True)
    print(f"Ejecutando {state['iterations']['requested']} iteraciones. Log: {directory/'matsim-run.log'}",flush=True)
    try:
        ledger.start()
        with (directory/'matsim-run.log').open('w',encoding='utf-8') as log:
            returncode=ejecutar_con_salida_en_vivo(command,log,cwd=PROJECT,env=env,
                process_state=state['process'], on_phase=phase, on_process=process_changed, on_line=process_line)
        state['returncode']=returncode
        state['returncode_origin']='natural_exit'
        if returncode:
            raise RuntimeError(f'Maven termino con codigo {returncode}; revisar matsim-run.log')
        phase('validating')
        print('Maven termino con codigo 0. Validando archivos, hashes e iteraciones...', flush=True)
        validate_outputs(directory, state)
        stability = state['validation'].get('physical_stability', {})
        if stability.get('interventions', 0):
            print(f"Intervenciones nativas observadas: {stability['forced_storage_moves']} movimientos forzados; "
                  f"{stability['storage_stuck_removals']} retiros por almacenamiento. "
                  'Son decisiones, no vehiculos distintos. Las salidas estan completas; NO acreditan estabilidad fisica.',
                  file=sys.stderr, flush=True)
        state['status']='completed'
        state['phase']='completed'
        ledger.set_phase('completed')
    except BaseException as exc:
        state['status']='interrupted' if isinstance(exc,KeyboardInterrupt) else 'failed'
        state['error']=str(exc) or type(exc).__name__
        state['exception_type']=type(exc).__name__
        state['exception_traceback']=traceback.format_exc()
        state['failure_phase']=state['phase']
        causal = diagnostico_causal_log(directory/'matsim-run.log')
        state['failure_category'] = ('manual_interruption' if isinstance(exc, KeyboardInterrupt) else
                                     'output_validation_error' if state['phase'] == 'validating' else
                                     causal['category'])
        state['first_causal_error'] = causal['first_error'] or dict(message=state['error'], source='launcher')
        state['causal_exception_chain'] = causal['cause_chain']
        state['root_cause'] = causal['root_cause']
        state['first_logged_error'] = causal['first_logged_error']
        state['secondary_errors'] = causal['secondary_errors']
        state['causal_diagnostic_status'] = causal['diagnostic_status']
        state['causal_diagnostic_uncertainty'] = causal['uncertainty']
        state['explicit_cause_blocks'] = causal['explicit_cause_blocks']
        if state['returncode_origin'] == 'pending':
            state['returncode'] = state['process'].get('returncode')
            state['returncode_origin'] = state['process'].get('returncode_origin', 'unavailable')
        state['validation'] = dict(status='invalid', error=state['error'])
        try:
            state['iterations']['completed'] = completed_iterations(output)
        except (OSError, ValueError, KeyError):
            pass  # No stopwatch yet, or it was interrupted while writing.
        oom, tail = diagnostico_log(directory/'matsim-run.log')
        state['out_of_memory_detected'] = oom
        label = {'manual_interruption':'Interrupcion manual', 'compilation_error':'Error de compilacion',
                 'configuration_invalid':'Configuracion invalida', 'runtime_exception':'Excepcion de ejecucion',
                 'output_validation_error':'Fallo de validacion de salidas'}[state['failure_category']]
        print(f"{label} durante {state['failure_phase']}: {state['error']}. "
              f"Codigo de proceso={state['returncode']} ({state['returncode_origin']}).\n"
              f"latest-successful se conserva; no corresponde a este intento.\n"
              f"Log: {directory/'matsim-run.log'}", file=sys.stderr, flush=True)
        if causal['first_error']:
            print(f"Diagnostico {causal['diagnostic_status']} (linea {causal['first_error']['line']}): "
                  f"{causal['first_error']['message']}", file=sys.stderr, flush=True)
        if causal['uncertainty']:
            print(causal['uncertainty'], file=sys.stderr, flush=True)
        if oom:
            print(f'Java reporto OutOfMemoryError con heap maximo {heap_gib}G. '
                  'Revisar el log: aumentar el heap no garantiza memoria suficiente para esta demanda.',
                  file=sys.stderr,flush=True)
        if tail:
            print(f'Ultimas 20 lineas de matsim-run.log (o todas si hay menos):\n{tail}',file=sys.stderr,flush=True)
        raise
    finally:
        ledger.close()
        state['finished_utc']=datetime.now(timezone.utc).isoformat()
        save()
    publish_success(directory, state, latest_path)
    print(f"Corrida completada y validada: {state['run_id']} | {output}",flush=True)
    # Deliberately after save/publish and outside the MATSim try/except/finally.
    # This field is returned to callers only, never saved into run-manifest.json.
    if state.get('experiment', {}).get('base_scenario_identity'):
        from simz1_configuration_contract import validate_run_configuration
        # Keep native completed/valid intact if a closure-only check fails.
        # Analysis and packaging must not be the first readers of this contract.
        validate_run_configuration(directory)
    state['analysis'] = run_post_analysis(directory, latest_path)
    return state


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=SCENARIO/'config-simz1.xml')
    parser.add_argument('--seed',type=int)
    parser.add_argument('--run-dir',type=Path,
                        help='Carpeta nueva explicita (error si existe); si se omite crea una carpeta unica con UUID')
    parser.add_argument('--maven',type=Path,help='Maven alternativo; por defecto usa mvnw del proyecto')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--iterations',type=int,help='Sobrescribe SOLO la copia; por defecto conserva el XML de origen')
    add_generation_options(parser)
    args=parser.parse_args()
    try:
        if os.environ.get('SIMZ1_LAUNCH_DIRECTORY'):
            from simz1_resource_monitor import record_process
            record_process(os.getpid(),os.environ['SIMZ1_LAUNCH_DIRECTORY'],os.environ['SIMZ1_LAUNCH_ID'],'executor')
        if args.iterations is not None and args.iterations<1:raise ValueError('--iterations debe ser positivo')
        report=generar(args.config,args.run_dir,args.seed, **generation_options(args))
        directory=Path(report['run_dir'])
        state=ejecutar(directory,args.maven,args.offline,args.iterations)
        if state['analysis']['status'] == 'analysis_failed':
            parser.exit(2, 'analysis_failed: la simulacion conserva completed/valid; reintente solo el analisis.\n')
    except KeyboardInterrupt:
        parser.exit(130, 'Corrida interrumpida; latest-successful no se actualizo.\n')
    except (OSError,ValueError,ET.ParseError,RuntimeError,EOFError) as exc:
        parser.exit(1,f'Error: {exc}\n')


if __name__=='__main__':main()
