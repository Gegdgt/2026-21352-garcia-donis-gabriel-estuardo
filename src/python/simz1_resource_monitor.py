"""Best-effort Windows resource observation for a single SimZ1 process tree.

No simulation settings are changed. Memory is sampled independently of the
optional read-only jstat observer. All observer failures remain diagnostic.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time


def process_snapshot():
    """One OS enumeration, with UTC milliseconds shared by every producer/reader.

    A denied/incomplete query is evidence of uncertainty, never of death.
    This intentionally does not read events or attach a Java diagnostic agent.
    """
    observed = dt.datetime.now(dt.timezone.utc).isoformat()
    script = r"""$ErrorActionPreference='Stop'
Get-CimInstance Win32_Process -ErrorAction Stop | ForEach-Object {
 [pscustomobject]@{pid=[int]$_.ProcessId;parent_pid=[int]$_.ParentProcessId;
 created_utc=$_.CreationDate.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.fffZ');
 executable=$_.ExecutablePath;command=$_.CommandLine;name=$_.Name;identity_source='Win32_CIM';
 process_cpu_seconds=([double]$_.KernelModeTime+[double]$_.UserModeTime)/10000000}
} | ConvertTo-Json -Compress"""
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', script],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise OSError(result.stderr.strip())
        rows = json.loads(result.stdout)
        if isinstance(rows, dict): rows = [rows]
        if not isinstance(rows, list) or not rows: raise ValueError('Empty process enumeration')
        return dict(observed_at=observed, complete=True, processes=rows, error=None)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return dict(observed_at=observed, complete=False, processes=[], error=str(error))


def same_process(saved, observed):
    if any(saved.get(k) is None or observed.get(k) is None for k in
           ('pid','created_utc','executable','parent_pid')):
        return False
    if any(saved[k] != observed[k] for k in ('pid','created_utc','parent_pid')):
        return False
    normalize=lambda p: str(p).replace('/', '\\').casefold()
    if normalize(saved['executable']) != normalize(observed['executable']): return False
    # ProcessHandle and CIM serialize command-line quoting differently. Keep both
    # observations, but do not interpret a representation difference as PID reuse.
    if saved.get('identity_source') != observed.get('identity_source') and 'java_ProcessHandle' in (
            saved.get('identity_source'),observed.get('identity_source')):
        return True
    return saved.get('command') is not None and saved['command'] == observed.get('command')


def process_role(row):
    """Execution ownership needs an actual entry point, never a run-path mention."""
    command=row.get('command') or ''; name=row.get('name') or ''
    if re.match(r'^java(w)?\.exe$',name,re.I):
        if re.search(r'(?:^|[\s"])gt\.edu\.uvg\.sim\.zona1\.(?:RunZona1Simulation|SimZ1)(?=[\s"]|$)',command):
            return 'native_jvm'
        if 'org.codehaus.plexus.classworlds.launcher.Launcher' in command: return 'maven'
    if re.match(r'^python(w)?\.exe$',name,re.I):
        if re.search(r'(?:ejecutar_simz1|simz1_balanced_execute)\.py(?:[\s"]|$)',command): return 'executor'
        if '--watch' not in command and re.search(
                r'(?:analizar_simz1|simz1_operational_report|simz1_balanced_launch_report|simz1_result_quality|simz1_report_package|visualizador_z1|simz1_continuous_replay|prepare_replay)\.py(?:[\s"]|$)',command):
            return 'postprocessor'
    return None


def reconcile_processes(manifest, ledger, snapshot, run):
    """Derived observation only; never edits a historical manifest or exit code."""
    rows = {r['pid']: r for r in snapshot['processes']}
    saved = ledger.get('identities', [])
    live = [r for r in saved if r['pid'] in rows and same_process(r, rows[r['pid']])]
    reused = [r['pid'] for r in saved if r['pid'] in rows and
              rows[r['pid']].get('created_utc') and r.get('created_utc') != rows[r['pid']]['created_utc']]
    ambiguous = [r['pid'] for r in saved if r['pid'] in rows and r['pid'] not in reused
                 and not same_process(r, rows[r['pid']])]
    unknown = not snapshot['complete'] or bool(ambiguous)
    # A path in --observe-run/--watch is not evidence of a writer. Only known
    # execution entry points are eligible for legacy attribution.
    run_token = str(Path(run).resolve()).replace('/', '\\').lower()
    for r in rows.values():
        if re.match(r'^(java|python)(w)?\.exe$', r.get('name', ''), re.I):
            if not r.get('command') or not r.get('executable'): unknown = True
            elif run_token in r['command'].replace('/', '\\').lower() and r['pid'] not in {p['pid'] for p in live}:
                role=process_role(r)
                if role: live.append(dict(r,role=role,association_source='exact_run_path_and_entry_point'))
    native = [r for r in live if r.get('role') == 'native_jvm']
    native_seen = any(r.get('role')=='native_jvm' for r in saved)
    processing = any(r.get('role')=='postprocessor' for r in live) or (
        manifest.get('phase') in ('validating','completed','analysis') and bool(live))
    terminal = manifest.get('status') in ('completed', 'failed', 'interrupted')
    if unknown: status = 'unknown'
    elif native: status = 'writer_alive'
    elif processing: status = 'postprocessing_alive'
    elif live: status = 'supervisor_alive'
    elif terminal: status = 'terminal_persisted'
    else: status = 'orphaned/incomplete'
    return dict(observed_status=status, persisted_status=manifest.get('status'),
        observed_at=snapshot['observed_at'], enumeration_complete=snapshot['complete'],
        error=snapshot.get('error'), live_processes=live, reused_pids=reused, ambiguous_pids=ambiguous,
        writer_alive=bool(native), tree_absent=not live if not unknown else None,
        stream_final=(not native and (native_seen or terminal or not live)) if not unknown else None,
        returncode=manifest.get('returncode'), death_time_utc=None,
        returncode_process=manifest.get('process',{}).get('returncode_process','executor_child_not_native_jvm'),
        command_observations=[dict(pid=r['pid'],saved=r.get('command'),observed=rows[r['pid']].get('command'),
            sources=[r.get('identity_source'),rows[r['pid']].get('identity_source')]) for r in live
            if r['pid'] in rows and r.get('command')!=rows[r['pid']].get('command')],
        last_process_observation=ledger.get('observed_at'),
        process_activity=[dict(pid=r['pid'],created_utc=r['created_utc'],process_cpu_seconds=rows[r['pid']].get('process_cpu_seconds'),
            observed_at=snapshot['observed_at']) for r in live if r['pid'] in rows])


def native_identity(run, run_id, launch_id):
    """Read the JVM's atomic birth record, retaining unavailable fields as null."""
    from simz1_run import read_atomic_json
    path=Path(run)/'native-process.json'
    if not path.is_file(): return None
    value=read_atomic_json(path)
    if value.get('schema_version')!=1 or value.get('run_id')!=run_id or (
            launch_id is not None and value.get('launch_id')!=launch_id):
        raise ValueError('Native process identity belongs to another run/launch')
    row=value.get('identity')
    if not isinstance(row,dict) or row.get('role')!='native_jvm' or not isinstance(row.get('pid'),int):
        raise ValueError('Invalid native process identity')
    return dict(row,run_id=value['run_id'],launch_id=value.get('launch_id'))


def record_process(pid, launch_directory, launch_id, role):
    """Atomic birth observation before a pipeline/executor does any run work."""
    from simz1_run import atomic_json, read_atomic_json
    directory=Path(launch_directory).resolve(strict=True)
    request=read_atomic_json(directory/'request.json')
    if request.get('launch_id')!=launch_id or directory.name!=launch_id:
        raise ValueError('Launch identity/path mismatch')
    snapshot=process_snapshot()
    row=next((r for r in snapshot['processes'] if r['pid']==pid),None)
    if not snapshot['complete'] or row is None or any(row.get(k) is None for k in ('created_utc','executable','command','parent_pid')):
        raise ValueError('Process identity unavailable; no work started: '+str(pid))
    identity=dict(row,role=role,launch_id=launch_id,run_id=None,
                  observed_at=snapshot['observed_at'],run_directory=request['run_directory'])
    token=str(pid)+'-'+re.sub('[^0-9]','',row['created_utc'])
    path=directory/'processes'/(token+'.json')
    atomic_json(path,identity)
    return identity


def launch_identities(directory, launch_id, run_id):
    from simz1_run import read_atomic_json
    result=[]
    for path in sorted((Path(directory)/'processes').glob('*.json')):
        identity=read_atomic_json(path)
        if identity.get('launch_id')!=launch_id: raise ValueError('Foreign process birth in launch evidence')
        result.append(dict(identity,run_id=run_id,run_id_association='explicit_launch_manifest'))
    return result


class ProcessLedger:
    """Small atomic identity ledger owned by the existing executor (no relaunch)."""
    def __init__(self, run, run_id, launch_id=None):
        self.run = Path(run)
        self.value = dict(schema_version=1, run_id=run_id, launch_id=launch_id,
                          identities=[], observed_at=None)
        self.stop_event = threading.Event()
        self.lock = threading.RLock()
        self.thread = None
        self.phase = 'running'

    def set_phase(self, phase):
        with self.lock:
            self.phase=phase

    def record_native(self, document):
        from simz1_run import atomic_json
        if (document.get('schema_version')!=1 or document.get('run_id')!=self.value['run_id'] or
                document.get('launch_id')!=self.value['launch_id']):
            raise ValueError('Native birth notification belongs to another launch/run')
        row=document.get('identity')
        if not isinstance(row,dict) or row.get('role')!='native_jvm' or not isinstance(row.get('pid'),int):
            raise ValueError('Invalid native birth notification')
        with self.lock:
            self._add(dict(row,run_id=document['run_id'],launch_id=document.get('launch_id')))
            self.value['native_birth_recorded_utc']=dt.datetime.now(dt.timezone.utc).isoformat()
            atomic_json(self.run/'process-identities.json',self.value)

    def _add(self, identity):
        for old in self.value['identities']:
            if same_process(identity,old):
                if identity.get('identity_source')=='Win32_CIM' and old.get('identity_source')=='java_ProcessHandle':
                    old['native_birth_command']=old.get('command');old.update(identity)
                return
        self.value['identities'].append(identity)

    def capture(self):
        from simz1_run import atomic_json
        snapshot = process_snapshot()
        with self.lock:
            rows = {r['pid']: r for r in snapshot['processes']}
            roots = {os.getpid()}
            launcher = os.environ.get('SIMZ1_LAUNCH_PID')
            if launcher and int(launcher) in rows:
                expected = os.environ.get('SIMZ1_LAUNCH_CREATED_UTC')
                if rows[int(launcher)].get('created_utc') == expected: roots.add(int(launcher))
            selected = set(roots)
            # Parent PID alone is unsafe after reuse: a child cannot predate its
            # claimed current parent. Missing timestamps leave the association unknown.
            while True:
                children={pid for pid,r in rows.items() if r['parent_pid'] in selected and
                    r.get('created_utc') and rows.get(r['parent_pid'],{}).get('created_utc') and
                    r['created_utc']>=rows[r['parent_pid']]['created_utc']}
                if children.issubset(selected): break
                selected.update(children)
            # Do not retain our short lived CIM helper as an execution owner.
            for pid in sorted(selected):
                row = rows.get(pid)
                if not row or not row.get('command') or not row.get('executable'): continue
                if "Get-CimInstance Win32_Process" in row['command']: continue
                if pid == os.getpid(): role = 'executor'
                elif launcher and pid == int(launcher): role = 'launcher'
                else: role = process_role(row) or 'pipeline'
                identity = dict(row, role=role, run_id=self.value['run_id'], launch_id=self.value['launch_id'])
                self._add(identity)
            birth=native_identity(self.run,self.value['run_id'],self.value['launch_id'])
            if birth is not None: self._add(birth)
            launch_directory=os.environ.get('SIMZ1_LAUNCH_DIRECTORY')
            if launch_directory:
                for born in launch_identities(launch_directory,self.value['launch_id'],self.value['run_id']): self._add(born)
            self.value.update(observed_at=snapshot['observed_at'], enumeration_complete=snapshot['complete'],
                observation_error=snapshot.get('error'),phase=self.phase,
                activity=[dict(pid=r['pid'],created_utc=r['created_utc'],process_cpu_seconds=r.get('process_cpu_seconds'),
                    observed_at=snapshot['observed_at']) for r in rows.values()
                    if any(same_process(r,old) for old in self.value['identities'])])
            atomic_json(self.run/'process-identities.json', self.value)

    def start(self):
        self.capture()
        def loop():
            while not self.stop_event.wait(5):
                try: self.capture()
                except (OSError,ValueError) as error:
                    # Never terminate QSim because a diagnostic write/query failed.
                    self.value['observation_error']=repr(error)
        self.thread = threading.Thread(target=loop, name='SimZ1-process-identities', daemon=True)
        self.thread.start()
        return self

    def close(self):
        self.stop_event.set()
        if self.thread: self.thread.join(timeout=20)


def observe_run(run, snapshot=None, launch=None):
    from simz1_run import load_manifest, read_atomic_json
    run = Path(run)
    manifest = load_manifest(run)
    path = run/'process-identities.json'
    ledger = read_atomic_json(path) if path.is_file() else {}
    if launch is not None:
        launch_state=read_atomic_json(Path(launch)/'state.json')
        if Path(launch_state['run_directory']).resolve()!=run.resolve() or (
                launch_state.get('run_id') is not None and launch_state['run_id']!=manifest['run_id']):
            raise ValueError('Launch/manifest association differs')
        identities=list(ledger.get('identities',[]))
        for row in [launch_state.get('process'),*launch_identities(launch,launch_state['launch_id'],manifest['run_id'])]:
            if row and not any(same_process(row,old) for old in identities): identities.append(row)
        ledger=dict(ledger,identities=identities,launch_id=launch_state['launch_id'])
    try:
        birth=native_identity(run,manifest['run_id'],manifest.get('launch_id'))
        if birth is not None and not any(same_process(birth,r) for r in ledger.get('identities',[])):
            ledger=dict(ledger,identities=[*ledger.get('identities',[]),birth])
    except (OSError,ValueError) as error:
        snapshot=dict(snapshot or process_snapshot(),complete=False,error=str(error))
    result = reconcile_processes(manifest, ledger, snapshot or process_snapshot(), run)
    result.update(run_id=manifest['run_id'], last_completed_step=manifest.get('last_completed_step'),
                  launch_id=ledger.get('launch_id'))
    events = sorted((run/'output/ITERS').glob('it.*/*.events.xml.gz'))
    result['event_files'] = [dict(path=str(p), bytes=p.stat().st_size,
        last_write_utc=dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat()) for p in events]
    result['reader_coverage_seconds'] = None  # This lightweight observer does not parse events.
    return result


def observe_launch(directory):
    from simz1_run import read_atomic_json
    directory=Path(directory).resolve(strict=True)
    state=read_atomic_json(directory/'state.json');run=Path(state['run_directory'])
    if state.get('launch_id')!=directory.name: raise ValueError('Launch path/id differs')
    if (run/'run-manifest.json').is_file(): return observe_run(run,launch=directory)
    ledger=dict(identities=[state['process']] if state.get('process') else [])
    ledger['identities']+=launch_identities(directory,state['launch_id'],None)
    observed=reconcile_processes(dict(state,returncode=state.get('child_exit_code')),ledger,process_snapshot(),run)
    observed.update(launch_id=state['launch_id'],run_id=None,last_completed_step=None,event_files=[],reader_coverage_seconds=None)
    return observed


class EventReaderLease:
    """One heavy incremental reader per explicit run/iteration; observation only.

    Windows kernel ownership disappears with the client. No stale lock file is
    removed and no writer/supervisor is owned or terminated by this lease.
    """
    def __init__(self,run,iteration):
        self.handle=None
        token=(str(Path(run).resolve()).casefold()+'\0'+str(iteration)).encode()
        self.name='Global\\SimZ1EventReader-'+hashlib.sha256(token).hexdigest()

    def __enter__(self):
        if os.name!='nt': raise OSError('Event reader exclusivity requires the Windows runtime')
        self.kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        self.kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
        self.kernel.CreateMutexW.restype=wintypes.HANDLE
        self.kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD]
        self.kernel.WaitForSingleObject.restype=wintypes.DWORD
        self.kernel.ReleaseMutex.argtypes=[wintypes.HANDLE]
        self.kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        self.handle=self.kernel.CreateMutexW(None,False,self.name)
        if not self.handle: raise ctypes.WinError(ctypes.get_last_error())
        result=self.kernel.WaitForSingleObject(self.handle,0)
        if result not in (0,0x80):
            self.kernel.CloseHandle(self.handle);self.handle=None
            if result==0x102: raise RuntimeError('An explicit heavy event reader already owns this run/iteration')
            raise ctypes.WinError(ctypes.get_last_error())
        return self

    def __exit__(self,*args):
        if self.handle:
            self.kernel.ReleaseMutex(self.handle);self.kernel.CloseHandle(self.handle);self.handle=None


def descendant_pids(processes, root_pid):
    """Return only the root and its current transitive children, not namesakes."""
    result = {int(root_pid)}
    while True:
        children = {pid for pid, item in processes.items()
                    if item["parent_pid"] in result}
        enlarged = result | children
        if enlarged == result:
            return result.intersection(processes)
        result = enlarged


def parse_jstat_gc(output):
    """jstat -gc reports generation capacities/usage in KiB; metaspace excluded."""
    lines = [line.split() for line in output.splitlines() if line.strip()]
    for index, headers in enumerate(lines[:-1]):
        required = ("S0U", "S1U", "EU", "OU", "S0C", "S1C", "EC", "OC")
        if all(name in headers for name in required):
            values = dict(zip(headers, lines[index + 1]))
            numbers = {name: float(values[name]) for name in required}
            if not all(math.isfinite(value) and value >= 0 for value in numbers.values()):
                raise ValueError("jstat returned invalid heap values")
            return {
                "used_bytes": round(sum(numbers[k] for k in ("S0U", "S1U", "EU", "OU")) * 1024),
                "committed_bytes": round(sum(numbers[k] for k in ("S0C", "S1C", "EC", "OC")) * 1024),
                "source": "jstat_-gc",
            }
    raise ValueError("jstat generation columns unavailable")


def parse_jcmd_heap_info(output):
    """Read G1 GC.heap_info across JDK layouts; never infer heap from RSS."""
    modern = re.search(r"garbage-first heap\s+total reserved\s+(\d+)K,\s*committed\s+(\d+)K,\s*used\s+(\d+)K", output)
    legacy = re.search(r"garbage-first heap\s+total\s+(\d+)K,\s*used\s+(\d+)K", output)
    if modern:
        reserved, committed, used = (int(value) * 1024 for value in modern.groups())
    elif legacy:
        committed, used = (int(value) * 1024 for value in legacy.groups())
        reserved = None
    else:
        raise ValueError("GC.heap_info G1 heap totals unavailable")
    if used > committed or reserved is not None and committed > reserved:
        raise ValueError("GC.heap_info inconsistent heap totals")
    return {"used_bytes": used, "committed_bytes": committed, "reserved_bytes": reserved,
            "source": "jcmd_GC.heap_info"}


def java_tool(name):
    executable = shutil.which(name)
    if not executable and os.environ.get("JAVA_HOME"):
        candidate = Path(os.environ["JAVA_HOME"]) / "bin" / (name + ".exe")
        executable = str(candidate) if candidate.is_file() else None
    return executable


def read_java_heap(pid, *, prefer_jcmd=False):
    """Read-only heap commands: jstat first, then GC.heap_info if unavailable."""
    errors = []
    names = ("jcmd",) if prefer_jcmd else ("jstat", "jcmd")
    for name in names:
        executable = java_tool(name)
        if not executable:
            errors.append(name + " not found")
            continue
        command = [executable, str(pid), "GC.heap_info"] if name == "jcmd" else [executable, "-gc", str(pid)]
        try:
            completed = subprocess.run(command, capture_output=True, text=True, timeout=3,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if completed.returncode:
                raise RuntimeError(f"exit {completed.returncode}: {(completed.stderr or completed.stdout).strip()[:300]}")
            heap = parse_jcmd_heap_info(completed.stdout) if name == "jcmd" else parse_jstat_gc(completed.stdout)
            if errors:
                heap["fallback_reasons"] = errors
            return heap
        except Exception as error:
            errors.append(f"{name}: {error}")
    raise RuntimeError("; ".join(errors))


class _WindowsBackend:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows process observer unavailable on this platform")
        size_t = ctypes.c_size_t

        class ProcessEntry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("pid", wintypes.DWORD), ("defaultHeap", size_t),
                        ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                        ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                        ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

        class MemoryCounters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("pageFaults", wintypes.DWORD)] + [
                (name, size_t) for name in ("peakWorkingSet", "workingSet", "peakPagedPool", "pagedPool",
                                           "peakNonPagedPool", "nonPagedPool", "pagefile", "peakPagefile", "private")]

        class GlobalMemory(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in ("total", "available", "pageTotal", "pageAvailable",
                                                      "virtualTotal", "virtualAvailable", "extended")]

        self.ProcessEntry, self.MemoryCounters, self.GlobalMemory = ProcessEntry, MemoryCounters, GlobalMemory
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel = kernel
        self.snapshot = kernel.CreateToolhelp32Snapshot
        self.snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        self.snapshot.restype = wintypes.HANDLE
        for name in ("Process32FirstW", "Process32NextW"):
            fn = getattr(kernel, name)
            fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
            fn.restype = wintypes.BOOL
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(GlobalMemory)]
        kernel.GlobalMemoryStatusEx.restype = wintypes.BOOL
        self.memory = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
        self.memory.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
        self.memory.restype = wintypes.BOOL

    def processes(self):
        handle = self.snapshot(2, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        result = {}
        try:
            entry = self.ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            more = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while more:
                result[int(entry.pid)] = {"parent_pid": int(entry.parent), "exe": str(entry.exe)}
                more = self.kernel.Process32NextW(handle, ctypes.byref(entry))
        finally:
            self.kernel.CloseHandle(handle)
        return result

    def sample_process(self, pid):
        handle = self.kernel.OpenProcess(0x410, False, pid)
        if not handle:
            handle = self.kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            times = [wintypes.FILETIME() for _ in range(4)]
            if not self.kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                raise ctypes.WinError(ctypes.get_last_error())
            ticks = [(int(item.dwHighDateTime) << 32) | int(item.dwLowDateTime) for item in times]
            mem = self.MemoryCounters()
            mem.cb = ctypes.sizeof(mem)
            memory_available = bool(self.memory(handle, ctypes.byref(mem), mem.cb))
            return {"creation_ticks": ticks[0], "process_cpu_seconds": (ticks[2] + ticks[3]) / 10_000_000,
                    "working_set_bytes": int(mem.workingSet) if memory_available else None,
                    "private_bytes": int(mem.private) if memory_available else None,
                    "memory_available": memory_available}
        finally:
            self.kernel.CloseHandle(handle)

    def global_memory(self):
        mem = self.GlobalMemory()
        mem.length = ctypes.sizeof(mem)
        if not self.kernel.GlobalMemoryStatusEx(ctypes.byref(mem)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"total_ram_bytes": int(mem.total), "available_ram_bytes": int(mem.available),
                "memory_load_percent": int(mem.load)}


class ResourceMonitor:
    """Context manager writing resource-samples.jsonl and resource-summary.json.

    ``outputdir`` is created on entry. Use a separate diagnostics directory if
    the SimZ1 generator requires its run directory not to exist yet. Peaks are
    sampled aggregate values, not exact instantaneous peaks. CPU includes only
    observed descendants; short-lived processes between samples can be missed.
    """
    def __init__(self, outputdir, root_pid=None, interval_seconds=5,
                 heap_interval_seconds=30, enable_jstat=True):
        self.outputdir = Path(outputdir)
        self.root_pid = os.getpid() if root_pid is None else int(root_pid)
        self.interval = max(0.05, float(interval_seconds))
        self.heap_interval = max(0.1, float(heap_interval_seconds))
        self.enable_jstat = bool(enable_jstat)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._thread = self._heap_thread = None
        self._file = None
        self._backend = None
        self._cpu = {}
        self._cpu_initial = {}
        self._java = {}
        self._heap = {}
        self._started = None
        self._closed = False
        self.summary = {"schema_version": 1, "root_pid": self.root_pid, "samples": 0,
                        "monitor_available": False, "peak_working_set_bytes": None,
                        "peak_private_bytes": None, "peak_java_heap_used_bytes": None,
                        "minimum_available_ram_bytes": None, "cumulative_process_cpu_seconds": 0,
                        "errors": [], "error_count": 0,
                        "measurement": "sampled root plus exact live descendants; CPU tracks observed process identities",
                        "limitations": ["Processes born and exited between samples may be missed",
                                        "Working sets include shared pages and are not unique physical RAM",
                                        "jstat / read-only jcmd heap is optional; unavailable values remain null"]}

    def _error(self, error):
        with self._lock:
            self.summary["error_count"] += 1
            if len(self.summary["errors"]) < 20:
                self.summary["errors"].append(str(error))

    def start(self):
        if self._started is not None:
            return self
        self._started = time.monotonic()
        self.summary["started_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            self.outputdir.mkdir(parents=True, exist_ok=True)
            self._file = (self.outputdir / "resource-samples.jsonl").open("w", encoding="utf-8")
            self._backend = _WindowsBackend()
            self.summary["monitor_available"] = True
            self._sample()
            self._thread = threading.Thread(target=self._run, name="simz1-resource-monitor", daemon=True)
            self._thread.start()
            if self.enable_jstat:
                self._heap_thread = threading.Thread(target=self._run_heap, name="simz1-heap-monitor", daemon=True)
                self._heap_thread.start()
        except Exception as error:
            self._error(f"monitor startup: {error}")
        return self

    def _sample(self):
        try:
            inventory = self._backend.processes()
            selected = descendant_pids(inventory, self.root_pid)
            processes = []
            java = {}
            for pid in sorted(selected):
                try:
                    item = {"pid": pid, **inventory[pid], **self._backend.sample_process(pid)}
                    identity = (pid, item["creation_ticks"])
                    # Root may predate the monitor. Exclude its earlier CPU use.
                    self._cpu_initial.setdefault(identity, item["process_cpu_seconds"] if pid == self.root_pid else 0)
                    self._cpu[identity] = max(0, item["process_cpu_seconds"] - self._cpu_initial[identity])
                    processes.append(item)
                    if item["exe"].lower() in ("java.exe", "javaw.exe"):
                        java[pid] = item["creation_ticks"]
                except OSError as error:
                    # Exit races or access limitations do not invalidate other observations.
                    processes.append({"pid": pid, **inventory[pid], "unavailable_reason": str(error)})
            globals_ = self._backend.global_memory()
            memory_complete = all(item.get("memory_available", False) for item in processes)
            working = sum(item.get("working_set_bytes") or 0 for item in processes)
            private = sum(item.get("private_bytes") or 0 for item in processes)
            with self._lock:
                self._java = java
                heaps = [{"pid": pid, **heap, "sample_age_seconds": max(0, time.monotonic() - heap["sample_monotonic"])}
                         for pid, heap in self._heap.items() if pid in java and heap["creation_ticks"] == java[pid]]
                for heap in heaps:
                    heap.pop("sample_monotonic", None)
                sample = {"timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "elapsed_seconds": time.monotonic() - self._started, "root_pid": self.root_pid,
                          "processes": processes, "tree_working_set_bytes": working,
                          "tree_private_bytes": private, "memory_complete": memory_complete,
                          "cumulative_process_cpu_seconds": sum(self._cpu.values()),
                          "java_heap": heaps or None, **globals_}
                self.summary["samples"] += 1
                self.summary["cumulative_process_cpu_seconds"] = sample["cumulative_process_cpu_seconds"]
                for name, value in (("peak_working_set_bytes", working), ("peak_private_bytes", private)):
                    self.summary[name] = max(self.summary[name] or 0, value)
                old = self.summary["minimum_available_ram_bytes"]
                self.summary["minimum_available_ram_bytes"] = min(old if old is not None else globals_["available_ram_bytes"], globals_["available_ram_bytes"])
                self.summary["total_ram_bytes"] = globals_["total_ram_bytes"]
            self._file.write(json.dumps(sample, ensure_ascii=False, allow_nan=False) + "\n")
            self._file.flush()
        except Exception as error:
            self._error(f"resource sample: {error}")

    def _run(self):
        while not self._stop.wait(self.interval):
            self._sample()

    def _run_heap(self):
        if not java_tool("jstat") and not java_tool("jcmd"):
            self._error("heap observer unavailable: jstat and jcmd not found")
            return
        while not self._stop.is_set():
            with self._lock:
                java = dict(self._java)
            for pid, creation in java.items():
                if self._stop.is_set():
                    return
                try:
                    # Refresh ancestry and creation time immediately before attachment.
                    current = self._backend.processes()
                    if pid not in descendant_pids(current, self.root_pid):
                        continue
                    if self._backend.sample_process(pid)["creation_ticks"] != creation:
                        continue
                    heap = read_java_heap(pid)
                    heap.update({"creation_ticks": creation, "sample_monotonic": time.monotonic(),
                                 "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat()})
                    with self._lock:
                        self._heap[pid] = heap
                        self.summary["peak_java_heap_used_bytes"] = max(self.summary["peak_java_heap_used_bytes"] or 0, heap["used_bytes"])
                except Exception as error:
                    with self._lock:
                        self._heap.pop(pid, None)
                    self._error(f"heap pid {pid}: {error}")
            if self._stop.wait(self.heap_interval):
                return

    def stop(self):
        if self._closed:
            return self.summary
        self._closed = True
        self._stop.set()
        try:
            for thread in (self._thread, self._heap_thread):
                if thread is not None:
                    thread.join(timeout=7)
            if self._backend is not None and self._file is not None:
                self._sample()
            self.summary["ended_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            self.summary["total_wall_seconds"] = time.monotonic() - self._started if self._started is not None else 0
            if self._file is not None:
                self._file.close()
            temporary = self.outputdir / "resource-summary.json.tmp"
            temporary.write_text(json.dumps(self.summary, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
            temporary.replace(self.outputdir / "resource-summary.json")
        except Exception as error:
            self._error(f"monitor shutdown: {error}")
        return self.summary

    def __enter__(self):
        return self.start()

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        return False


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Read-only process reconciliation; no event reader.')
    group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--observe-run', type=Path)
    group.add_argument('--observe-launch',type=Path)
    group.add_argument('--record-process',type=int)
    parser.add_argument('--launch-directory',type=Path)
    parser.add_argument('--launch-id')
    parser.add_argument('--role',choices=('pipeline','executor'))
    arguments = parser.parse_args()
    if arguments.record_process is not None:
        if not arguments.launch_directory or not arguments.launch_id or not arguments.role:
            parser.error('record-process requires launch-directory, launch-id and role')
        value=record_process(arguments.record_process,arguments.launch_directory,arguments.launch_id,arguments.role)
    else:value=observe_launch(arguments.observe_launch) if arguments.observe_launch else observe_run(arguments.observe_run)
    print(json.dumps(value, ensure_ascii=False))
