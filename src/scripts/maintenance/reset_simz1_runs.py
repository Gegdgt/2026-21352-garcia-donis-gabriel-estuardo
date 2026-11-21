"""Plan-bound reset of generated runs; mandatory failed-run protection, no implicit apply."""
import argparse
import codecs
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASES = tuple('scenarios/zona1/'+x for x in ('montecarlo','debug','historical'))
CONFIRM = 'BORRAR CORRIDAS SIMZ1'
TERMINAL = {'completed','failed','interrupted'}
SOURCE_EXT = {'.py','.ps1','.js','.cjs','.java','.jar','.class','.osm','.pbf'}
RUN_ID = re.compile(r'simz1-[a-f0-9]{32}\Z')
PROTECTED = 'scenarios/zona1/montecarlo/run-massive-50it-ee85beafe608490b9c184b7b148b86e7'
PROTECTED_ID = 'simz1-2f55639a0aee4fa0a70f657aa6b7ec9a'
DEPENDENCY_ROOTS = ('scenarios/zona1', 'runtime', 'output', 'entregables', 'docs')
NEVER_REMOVE = {'.git', '.venv', 'fixtures', 'evidence', 'evidencia', 'catalogs', 'catalogos'}
DEFAULT_METADATA_BYTES = 16 * 1024 * 1024
# simz1_sqlite_source._write_metadata publishes these two JSON documents with
# MAX_METADATA_BYTES=128 MiB. This is a read budget, not proof of ownership.
SQLITE_METADATA_BYTES = 128 * 1024 * 1024
SQLITE_METADATA_FILES = {'source-side.json', 'source-config.json'}
# Retained physical-contract diagnostics and validation/browser-results.json
# reports are complete JSON objects. Their producers declare no JSON size cap
# (browser reports: scripts/validation/*browser*.cjs, JSON.stringify(report)).
# This is our explicit per-document read budget, not a producer guarantee.
DIAGNOSTIC_METADATA_BYTES = 128 * 1024 * 1024
# inspect_simz1_conflicts.export writes complete window payloads and provenance
# to frame-input.json in a caller-selected diagnostic directory. Its compressed
# window budget does NOT bound the final JSON bytes (observed: 151,443,475).
# Allow this retained runtime artifact 256 MiB; this is a reader budget only.
OFFLINE_FRAME_METADATA_BYTES = 256 * 1024 * 1024
# Dependency-scanning budgets, not generator limits: the observed agent ledger
# is 120,173,249 bytes. Allow 256 MiB total, but only 1 MiB per physical line
# (including LF/CRLF). Never allocate the full ledger or retain its records.
JSONL_TOTAL_BYTES = 256 * 1024 * 1024
JSONL_LINE_BYTES = 1024 * 1024
_spec = importlib.util.spec_from_file_location('_reset_prune_guards', Path(__file__).with_name('prune_simz1_runs.py'))
guards = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guards)


def read_json(path):
    # Run manifests, plans and ownership records retain the original small limit.
    return read_metadata(path, DEFAULT_METADATA_BYTES, keep_value=True)[0]


def decode_json_document(raw):
    """BOM-directed Unicode only; no encoding guesses for BOM-less JSON.

    UTF-32 LE overlaps the UTF-16 LE signature, so reject both UTF-32 BOMs
    before testing UTF-16. This decoder is not used for JSONL or XML.
    """
    if raw.startswith((codecs.BOM_UTF32_LE,codecs.BOM_UTF32_BE)):
        raise ValueError('Unsupported JSON encoding: UTF-32 BOM')
    encoding=('utf-16' if raw.startswith((codecs.BOM_UTF16_LE,codecs.BOM_UTF16_BE)) else
              'utf-8-sig' if raw.startswith(codecs.BOM_UTF8) else 'utf-8')
    try:
        return raw.decode(encoding,errors='strict')
    except UnicodeError as error:
        raise ValueError(f'Invalid JSON encoding ({encoding}): {error}') from error


def read_metadata(path, limit, *, json_document=True, keep_value=False, reference_runs=None):
    """Read one bounded, stable file; hash exactly the bytes that were validated."""
    path=Path(path)
    before=path.stat()
    diagnostic=f'{path} (size={before.st_size} bytes, limit={limit} bytes)'
    def signature(info):
        return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns
    def invalid_constant(value):
        raise ValueError('Non-JSON constant: '+value)
    try:
        if before.st_size>limit:raise ValueError('Oversized dependency metadata')
        with path.open('rb') as stream:
            if signature(os.fstat(stream.fileno()))!=signature(before):
                raise ValueError('Metadata changed before reading')
            raw=stream.read(limit+1)
            if len(raw)>limit:raise ValueError(f'Metadata grew beyond limit; read={len(raw)} bytes')
            if len(raw)!=before.st_size:raise ValueError('Metadata changed size during reading')
            digest=hashlib.sha256(raw).hexdigest()
            text=decode_json_document(raw) if json_document else raw.decode('utf-8-sig')
            del raw
            if json_document:
                try:
                    options={'object_pairs_hook':lambda pairs:pairs} if reference_runs is not None else {}
                    value=json.loads(text,parse_constant=invalid_constant,**options)
                except (ValueError,RecursionError) as error:
                    raise ValueError('Invalid JSON document: '+str(error)) from error
                if not keep_value and reference_runs is None:del value
            if reference_runs is not None:
                references=set()
                # Search original spelling AND decoded strings (including duplicate
                # keys). Serialization is only for matching, never for the hash.
                contents=(text,json.dumps(value,ensure_ascii=False)) if json_document else (text,)
                for content in contents:
                    normalized=content.replace('\\\\','\\').replace('\\','/').casefold()
                    references.update(r['path'] for r in reference_runs if refers(normalized,r,normalized=True))
            if (signature(os.fstat(stream.fileno()))!=signature(before) or
                    signature(path.stat())!=signature(before)):
                raise ValueError('Metadata changed during reading')
        return (sorted(references) if reference_runs is not None else value if keep_value else text),digest
    except (OSError,ValueError,RecursionError) as error:
        raise ValueError(f'Cannot resolve dependency metadata: {diagnostic}: {error}') from error


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()


def read_jsonl_metadata(path, runs, *, total_limit, line_limit):
    """Validate through EOF with the standard decoder, one bounded record at a time.

    typed_people writes UTF-8 without BOM and LF; verify_type_ledger decodes
    UTF-8 and parses every line (no blank-line skipping). Follow that contract:
    reject BOM/blank records, accept CRLF and a valid final record without LF.
    Monolithic JSON has a separate BOM-aware decoder; JSONL does not use it.
    """
    path=Path(path);before=path.stat();line_number=0;total=0
    digest=hashlib.sha256();references=set()
    def signature(info):
        return info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns,info.st_ctime_ns
    def invalid_constant(value):
        raise ValueError('Non-JSON constant: '+value)
    try:
        if total_limit<=0 or line_limit<=0:raise ValueError('JSONL budgets must be positive')
        if before.st_size>total_limit:raise ValueError('Oversized JSONL file')
        with path.open('rb') as stream:
            if signature(os.fstat(stream.fileno()))!=signature(before):
                raise ValueError('JSONL changed before reading')
            while True:
                # One sentinel byte detects overflow without reading an enormous
                # line in full, including when a writer grows the file mid-scan.
                raw=stream.readline(min(line_limit,total_limit-total)+1)
                if not raw:break
                line_number+=1;total+=len(raw)
                if total>total_limit:raise ValueError('JSONL exceeds total byte limit')
                if len(raw)>line_limit:raise ValueError('JSONL line exceeds byte limit')
                digest.update(raw)
                text=raw.decode('utf-8')
                # Retain duplicate keys within THIS record for conservative
                # reference detection, including escaped keys/values overwritten
                # by a later duplicate in an ordinary Python dict.
                value=json.loads(text,parse_constant=invalid_constant,object_pairs_hook=lambda pairs:pairs)
                for content in (text,json.dumps(value,ensure_ascii=False)):
                    normalized=content.replace('\\\\','\\').replace('\\','/').casefold()
                    references.update(r['path'] for r in runs if refers(normalized,r,normalized=True))
                del raw,text,value,content,normalized
            if (total!=before.st_size or signature(os.fstat(stream.fileno()))!=signature(before) or
                    signature(path.stat())!=signature(before)):
                raise ValueError('JSONL changed during reading')
        return dict(sha256=digest.hexdigest(),references=sorted(references),
                    limit_bytes=total_limit,line_limit_bytes=line_limit,records=line_number)
    except (OSError,ValueError,RecursionError) as error:
        raise ValueError(f'Cannot resolve dependency metadata: {path} '
                         f'(size={before.st_size} bytes, total_limit={total_limit} bytes, '
                         f'line_limit={line_limit} bytes, line={line_number}): {error}') from error


def safe(root, relative):
    # Also reject Windows drive-relative paths, ADS and ambiguous trailing dots/spaces.
    value=Path(relative)
    if value.drive and not value.is_absolute():raise ValueError('Drive-relative path')
    parts=value.parts[1:] if value.is_absolute() else value.parts
    if any(':' in part or part.endswith((' ', '.')) for part in parts):raise ValueError('Ambiguous path')
    return guards.safe_path(root,value,must_exist=False)


def stat_row(root,path):
    path=safe(root,path)
    row=guards.stat_row(root,path); s=path.stat()
    if s.st_dev!=Path(root).stat().st_dev:raise ValueError('Cross-volume target/dependency: '+str(path))
    return dict(row,ctime_ns=s.st_ctime_ns,device=s.st_dev)


def snapshot(root,folder):
    result=[]
    def visit(path):
        row=stat_row(root,path); result.append(row)
        if row['directory']:
            for child in sorted(path.iterdir()): visit(child)
    visit(folder)
    return result


def idle(root, folders, process_rows=None):
    """Read-only process check. Never kills a process. Fail closed when Windows query fails."""
    if process_rows is not None:
        rows=process_rows
    elif os.name=='nt':
        rows=guards.processes()
        if not rows:raise ValueError('Empty process inventory')
    else:
        rows=[]
        if not Path('/proc/self/cmdline').is_file():raise ValueError('Process inspection unavailable')
        for p in Path('/proc').glob('[0-9]*'):
            try:
                rows.append(dict(ProcessId=int(p.name),Name='',CommandLine=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')))
            except FileNotFoundError:continue  # Process already exited.
            except (OSError,ValueError) as error:raise ValueError('Cannot inspect process '+str(p)) from error
    guards.check_processes(folders,rows)
    patterns=('ejecutar_simz1.py','serve_simz1','start_replay.py','visualizador_z1.py',
              'generar_graficas_z1.py','simz1_continuous_replay.py','run_simz1_with_analysis.ps1',
              'gt.edu.uvg.sim.zona1','exec:exec@simz1-fork','reset_simz1_runs.py','prune_simz1_runs.py',
              'generate_montecarlo_z1.py','prepare_replay.py','run_simz1_massive_verified.ps1',
              'simz1_workflow_state.py','purge_old_runs.py','simz1_sqlite')
    for row in rows:
        if row['ProcessId']==os.getpid():continue
        command=row.get('CommandLine')
        if command is None and str(row.get('Name','')).lower().startswith(('java','python','powershell','pwsh','node')):
            raise ValueError('Cannot inspect a potentially relevant process')
        if any(p in (command or '').casefold() for p in patterns):
            raise ValueError('Close the simulator/viewer/exporter first; PID='+str(row['ProcessId']))


def tracked(root):
    return guards.tracked_files(root)


def pointer(path, root):
    relative=path.relative_to(root)
    return (path.name.startswith('latest-') and path.suffix=='.json' or
            relative.as_posix()=='runtime/workflow/trial.json')


def dependency_metadata_limit(root,path):
    relative=path.relative_to(root)
    if relative.parts[0]=='runtime' and path.name=='frame-input.json':
        return OFFLINE_FRAME_METADATA_BYTES
    if relative.parts[:2]==('runtime','validation') and path.name=='browser-results.json':
        return DIAGNOSTIC_METADATA_BYTES
    if (path.suffix.lower()=='.json' and len(relative.parts)==3 and relative.parts[0]=='runtime' and
            re.fullmatch(r'physical-contract-\d{8}',relative.parts[1])):
        return DIAGNOSTIC_METADATA_BYTES
    return SQLITE_METADATA_BYTES if path.name in SQLITE_METADATA_FILES else DEFAULT_METADATA_BYTES


def dependency_metadata_record(root,path,runs):
    """One complete document, using exactly the same policy for plan and recheck."""
    path=safe(root,path);row=stat_row(root,path)
    if path.suffix.lower()=='.jsonl':
        limit=JSONL_TOTAL_BYTES
        summary=read_jsonl_metadata(path,runs,total_limit=limit,line_limit=JSONL_LINE_BYTES)
    else:
        limit=dependency_metadata_limit(root,path)
        references,digest=read_metadata(path,limit,json_document=path.suffix.lower()=='.json',reference_runs=runs)
        summary=dict(sha256=digest,limit_bytes=limit,references=references)
    if stat_row(root,path)!=row:
        raise ValueError(f'Metadata changed during reference resolution: {path} '
                         f'(size={row["bytes"]} bytes, limit={limit} bytes)')
    return dict(row,**summary)


def browser_profiles(root):
    """Retain opaque Chromium user-data dirs owned by the browser check tools.

    scripts/validation/{check_continuous_browser,check_simz1_transit_browser,
    occupancy_20261027_browser_audit}.cjs pass runtime/replay/browser-profile-UUID
    to --user-data-dir; measure_continuous_boundary.cjs uses the other namespace.
    Require their exact UUID namespace AND Chromium/CDP layout, not 'browser'
    anywhere in a name. This is scope classification, not content validation.
    Launch receipts and replay sidecars live outside these directories.
    """
    profiles=[]
    for base,prefix in (('runtime/replay','browser-profile-'),('runtime','window-measurement-profile-')):
        directory=safe(root,base)
        if not directory.is_dir():continue
        for path in sorted(directory.iterdir()):
            if not re.fullmatch(re.escape(prefix)+r'[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}',path.name):continue
            path=safe(root,path)
            if not path.is_dir():continue
            markers=[safe(root,path/name) for name in ('Local State','Default','DevToolsActivePort')]
            if not (markers[0].is_file() and markers[1].is_dir() and markers[2].is_file()):continue
            digest=hashlib.sha256(); count=0; size=0
            def inspect(node):
                nonlocal count,size
                row=stat_row(root,node)  # Reject links/reparse points, including descendants.
                count+=1; size+=row['bytes']
                if count>100000:raise ValueError('Browser profile snapshot entry limit exceeded: '+str(path))
                digest.update(json.dumps(row,sort_keys=True).encode('utf-8')+b'\n')
                if row['directory']:
                    for child in sorted(node.iterdir()):inspect(child)
            before=stat_row(root,path)
            inspect(path)
            if stat_row(root,path)!=before:raise ValueError('Browser profile changed during snapshot: '+str(path))
            profiles.append(dict(before,classification='retained_third_party_browser_profile',
                content_validated_as_simz1_metadata=False,snapshot_sha256=digest.hexdigest(),
                snapshot_entries=count,opaque_bytes=size,references=[],
                reason='Chromium/CDP user-data directory from browser validation tools; retained outside deletion scope'))
    return profiles


def metadata(root, extra=(), *, runs, omit=()):
    """Validate one document at a time; retain only snapshots, hashes and references.

    The JSON decoder may hold one bounded document's object tree transiently;
    neither that tree nor its text is accumulated across files/runs.
    """
    profiles=browser_profiles(root)
    rows={row['path']:row for row in profiles}
    profile_paths={Path(row['path']) for row in profiles}
    reference_targets=[*runs,*profiles]
    def visit(path):
        path=safe(root,path)
        if not path.exists():return
        if any(path==folder or path.is_relative_to(folder) for folder in omit):return
        relative=path.relative_to(root).as_posix()
        # Maintenance receipts are historical provenance, never operational pointers.
        if relative=='runtime/maintenance' or relative.startswith('runtime/maintenance/'):return
        if any(path==profile or path.is_relative_to(profile) for profile in profile_paths):return
        if path.is_dir():
            for child in sorted(path.iterdir()):visit(child)
        elif path.suffix.lower() in ('.json','.jsonl') or path.name in ('config-simz1.xml','output_config.xml'):
            if str(path) in rows:return
            if len(rows)>=100000:raise ValueError('Dependency metadata limit exceeded')
            row=dependency_metadata_record(root,path,reference_targets)
            for reference in row['references']:
                if Path(reference) in profile_paths:
                    # Never silently drop an explicit SimZ1 dependency crossing
                    # into opaque state (including escaped paths/identifiers).
                    # Its interpretation requires evidence; refuse a usable plan.
                    raise ValueError(f'Unresolved explicit SimZ1 reference into retained browser profile: {path} -> {reference}')
            rows[str(path)]=row
    for base in (*DEPENDENCY_ROOTS,*extra):visit(safe(root,base))
    return [rows[key] for key in sorted(rows)]


def refers(text, run, *, normalized=False):
    if not normalized:text=text.replace('\\\\','\\').replace('\\','/').casefold()
    return (bool(run.get('run_id')) and run['run_id'].casefold() in text or
            Path(run['path']).name.casefold() in text)


def owned_replay_js(root, folder, manifest, path):
    """Only an explicitly hashed replay artifact can bypass the .js source guard."""
    if path.relative_to(folder).parts[0] not in ('webgl-source','webgl-continuo'):
        raise ValueError('JS is outside an owned replay directory: '+str(path))
    for name in ('continuous-manifest.json','export-manifest.json'):
        owner=path.parent/name
        if not owner.is_file():continue
        safe(root,owner); value=read_json(owner)
        if value.get('run_id')!=manifest['run_id'] or value.get('status')!='complete':continue
        if value.get('run_manifest_sha256')!=sha(folder/'run-manifest.json'):continue
        # Existing manifests without a hash-addressed file record are NOT proof of ownership.
        def records(item):
            if isinstance(item,dict):
                yield item
                for child in item.values():yield from records(child)
            elif isinstance(item,list):
                for child in item:yield from records(child)
        for entry in records(value):
            filename=entry.get('file',entry.get('path'))
            if filename==path.name and entry.get('sha256')==sha(path):
                return dict(manifest=str(owner),sha256=sha(owner),artifact_sha256=entry['sha256'])
    raise ValueError('JS has no hash-bound replay ownership: '+str(path))


def inventory(root, git_files=None, *, exclusions=()):
    root=Path(root).absolute()
    safe(root,root)
    names=tracked(root) if git_files is None else git_files
    protected=safe(root,PROTECTED)
    protected_manifest=safe(root,protected/'run-manifest.json')
    protected_value=read_json(protected_manifest)
    if (protected_value.get('run_id')!=PROTECTED_ID or
            safe(root,protected_value.get('folder',''))!=protected):
        raise ValueError('Mandatory protected run identity cannot be resolved; no global reset')
    excluded=sorted({str(protected),*(str(safe(root,p)) for p in exclusions)})
    for value in excluded:
        if not Path(value).exists():raise ValueError('Unresolved exclusion: '+value)
        if Path(value).is_relative_to(root/'runtime/maintenance'):
            raise ValueError('Maintenance journal is already outside deletion scope; choose a run exclusion')
    all_runs=[]
    for base in BASES:
        directory=safe(root,base)
        if not directory.exists():continue
        for folder in sorted(directory.iterdir()):
            if not folder.name.startswith('run-'):continue
            relative=folder.relative_to(root).as_posix()
            run=dict(path=str(folder),relative_path=relative,run_id=None,status=None,bytes=None,
                     entries=[],dependencies=[],reasons=[],ownership_evidence=[])
            try:
                safe(root,relative)
                if not folder.is_dir():raise ValueError('Not a run directory')
                entries=snapshot(root,folder)
                run.update(entries=entries,bytes=sum(e['bytes'] for e in entries))
                meta=safe(root,folder/'run-manifest.json'); m=read_json(meta)
                run.update(run_id=m.get('run_id'),status=m.get('status'),manifest_sha256=sha(meta))
                if m.get('status') not in TERMINAL:run['reasons'].append('Not terminal; may be active')
                if not RUN_ID.fullmatch(str(m.get('run_id',''))):raise ValueError('Missing run identity')
                if safe(root,m.get('folder',''))!=folder:raise ValueError('Manifest folder mismatch')
                if any(n==relative or n.startswith(relative+'/') for n in names):run['reasons'].append('Contains Git-tracked files')
                for value in excluded:
                    p=Path(value)
                    if folder==p or folder.is_relative_to(p) or p.is_relative_to(folder):
                        run['reasons'].append('Explicit exclusion: '+value)
                for row in entries:
                    p=Path(row['path'])
                    local=p.relative_to(folder)
                    if any(part.casefold() in NEVER_REMOVE for part in local.parts):
                        raise ValueError('Contains protected evidence/fixture/source directory: '+str(p))
                    if row['directory']:continue
                    if p.name.casefold().endswith(('-wal','-shm','.lock','.pid')) or p.name.casefold()=='lock':
                        raise ValueError('Contains lock/active file: '+str(p))
                    if p.suffix.lower() in SOURCE_EXT:
                        if p.suffix.lower()!='.js':raise ValueError('Contains source file: '+str(p))
                        run['ownership_evidence'].append(owned_replay_js(root,folder,m,p))
            except (OSError,ValueError,KeyError,TypeError) as e:run['reasons'].append(str(e))
            all_runs.append(run)
    identities=[r['run_id'] for r in all_runs if r['run_id']]
    if len(set(identities))!=len(identities):raise ValueError('Ambiguous duplicate run identity')
    records=metadata(root,excluded,runs=all_runs)
    edges=[]; pointers=[]; evidence=[]
    for row in records:
        path=Path(row['path'])
        owner=next((r for r in all_runs if path.is_relative_to(Path(r['path']))),None)
        refs=[r for r in all_runs if r is not owner and r['path'] in row['references']]
        mutable=pointer(path,root) and owner is None and row['relative_path'] not in names and len(refs)==1
        evidence.append(row)
        if mutable:
            pointers.append(dict(evidence[-1],target=refs[0]['path'],action='invalidate',
                reason='Referenced run selected for deletion; no replacement selection or trial approval'))
        else:
            for ref in refs:
                edges.append(dict(source=row['path'],owner=owner['path'] if owner else None,target=ref['path']))
                if owner:owner['dependencies'].append(dict(path=ref['path'],source=row['path']))
    # Conserved consumers protect their dependencies, including chains/cycles.
    retained={r['path'] for r in all_runs if r['reasons']}
    changed=True
    while changed:
        changed=False
        for edge in edges:
            if edge['owner'] is None or edge['owner'] in retained:
                if edge['target'] not in retained:
                    retained.add(edge['target']); changed=True
                    next(r for r in all_runs if r['path']==edge['target'])['reasons'].append('Dependency of retained metadata: '+edge['source'])
    runs=[r for r in all_runs if r['path'] not in retained]
    for run in all_runs:
        run['decision']='retain' if run['path'] in retained else 'delete_only_after_confirmation'
        run['decision_reason']='; '.join(run['reasons']) if run['reasons'] else 'Terminal owned run, safe snapshot, no retained consumer dependency'
    pointers=[p for p in pointers if p['target'] not in retained]
    return dict(schema_version=4,root=str(root),created_utc=datetime.now(timezone.utc).isoformat(),
        exclusions=excluded,exclusion_snapshots=[dict(path=p,entries=snapshot(root,Path(p))) for p in excluded],
        dependency_metadata=evidence,dependencies=edges,tracked_paths=sorted(names),runs=runs,pointers=pointers,
        skipped=[r for r in all_runs if r['path'] in retained],bytes=sum(r['bytes'] for r in runs),
        note='Only listed run directories are candidates; runtime/output/scenarios roots, external artifacts and evidence remain. Manifest backups cannot restore deleted simulations.')


class JournalPersistenceError(OSError):
    """An uncommitted journal publication; its temporary is recovery evidence."""
    def __init__(self,operation,temporary,destination,attempts,cause):
        super().__init__(f'Journal persistence failed: operation={operation}; '
                         f'source={temporary}; destination={destination}; '
                         f'winerror={getattr(cause,"winerror",None)}; attempts={attempts}; {cause}')
        self.operation=operation;self.temporary=temporary;self.destination=destination
        self.attempts=attempts;self.winerror=getattr(cause,'winerror',None)


def publish_journal(destination,result):
    """Write once, close, then replace atomically; never retry cleanup operations.

    WinError 5/32/33 may be transient, but do not establish the underlying cause.
    Only replacement gets at most four attempts (waits: 0.05/0.10/0.20 seconds).
    On failure keep both the previous published receipt and the unique pending
    file. Even a pending 'completed' document is NOT a committed receipt.
    """
    temporary=destination.with_name('result-'+uuid.uuid4().hex+'.tmp')
    operation='write';attempts=0
    try:
        # Exclusive creation avoids reusing/overwriting an earlier failed save.
        with temporary.open('x',encoding='utf-8') as stream:
            stream.write(json.dumps(result,indent=2))
        operation='replace'
        for attempt in range(1,5):
            attempts=attempt
            try:
                temporary.replace(destination)
                return
            except OSError as error:
                if getattr(error,'winerror',None) not in (5,32,33) or attempt==4:
                    raise
                time.sleep((0.05,0.10,0.20)[attempt-1])
    except (OSError,ValueError,TypeError) as error:
        raise JournalPersistenceError(operation,temporary,destination,attempts,error) from error


def apply(root,plan,confirmation,*,git_files=None,process_rows=None):
    if confirmation!=CONFIRM:raise ValueError('Confirmation must be '+CONFIRM)
    root=Path(root).absolute()
    if plan.get('schema_version')!=4 or str(root)!=plan['root']:raise ValueError('Wrong project or obsolete plan schema')
    folders=[Path(r['path']) for r in plan['runs']]
    idle(root,folders,process_rows)
    current=inventory(root,git_files,exclusions=plan['exclusions'])
    for key in current:
        if key!='created_utc' and current[key]!=plan.get(key):
            raise ValueError('Files/identity/snapshot/exclusions changed since plan: '+key)
    for run in plan['runs']:
        for row in run['entries']:
            if not row['directory']:guards.check_file_unused(Path(row['path']))
    for row in plan['pointers']:guards.check_file_unused(Path(row['path']))
    journal=safe(root,'runtime/maintenance/reset-'+uuid.uuid4().hex)
    journal.mkdir(parents=True,exist_ok=False)
    result=dict(status='preparing',removed=[],removed_file_count=0,removed_bytes=0,pointer_changes=[],
        file_operations=str(journal/'file-operations.jsonl'),
        skipped=[dict(path=r['path'],reasons=r['reasons']) for r in plan['skipped']],backups=str(journal),
        free_bytes_before=shutil.disk_usage(root).free,
        warning='Manifest backups cannot restore deleted simulations; logical bytes are not measured free-space recovery.')
    log=journal/'result.json'
    def save():
        publish_journal(log,result)
    def usage():
        result['free_bytes_after']=shutil.disk_usage(root).free
        result['observed_free_delta_bytes']=result['free_bytes_after']-result['free_bytes_before']
        result['recovery_attribution']='Volume free-space delta; concurrent writers and journal overhead may affect it'
    def record_operation(state,row):
        # Append a bounded record instead of rewriting the entire removed-file list
        # for every unlink. A pending record without completion needs manual review.
        with Path(result['file_operations']).open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(state=state,**row))+'\n')
            stream.flush();os.fsync(stream.fileno())
    def check_preserved():
        for exclusion in plan['exclusion_snapshots']:
            if snapshot(root,Path(exclusion['path']))!=exclusion['entries']:
                raise ValueError('Exclusion changed during application: '+exclusion['path'])
        invalidated={p['path'] for p in result['pointer_changes']}
        expected=[row for row in plan['dependency_metadata'] if row['path'] not in invalidated and
                  not any(Path(row['path']).is_relative_to(folder) for folder in folders)]
        # Keep the original identity universe, including deleted candidates: a
        # newly added reference to one must still be detected during application.
        actual=metadata(root,plan['exclusions'],runs=plan['runs']+plan['skipped'],omit=folders)
        if actual!=expected:raise ValueError('Retained dependency/pointer added or changed during application')
    try:
        save()
        for run in plan['runs']:
            original=safe(root,Path(run['path'])/'run-manifest.json')
            (journal/(run['run_id']+'.json')).write_bytes(original.read_bytes())
        # Invalidate references BEFORE the first destructive operation. On partial
        # failure no latest/trial pointer may approve a partly deleted run.
        for row in plan['pointers']:
            path=safe(root,row['path'])
            current_row=stat_row(root,path)
            if current_row!={key:row[key] for key in current_row} or sha(path)!=row['sha256']:
                raise ValueError('Pointer changed before invalidation')
            guards.check_file_unused(path)
            backup=journal/('pointer-'+hashlib.sha256(row['path'].encode()).hexdigest()[:24]+'.json')
            backup.write_bytes(path.read_bytes())
            result['pending_operation']=dict(action='invalidate',path=str(path)); save()
            path.unlink()
            result['pointer_changes'].append(dict(path=str(path),backup=str(backup),action='invalidated'))
            result.pop('pending_operation',None); save()
        result['status']='deleting'; save()
        for run in plan['runs']:
            idle(root,folders,process_rows)
            check_preserved()
            if snapshot(root,Path(run['path']))!=run['entries']:raise ValueError('Target changed before deletion')
            # No rmtree: remove only inventoried regular files; added files block rmdir.
            for row in reversed(run['entries']):
                path=safe(root,row['path'])
                for exclusion in plan['exclusions']:guards.protected_target(path,Path(exclusion))
                result['pending_operation']=dict(action='rmdir' if row['directory'] else 'unlink',path=str(path),bytes=row['bytes']);save()
                record_operation('pending',result['pending_operation'])
                if row['directory']:
                    if not path.is_dir() or (path.stat().st_dev,path.stat().st_ino)!=(row['device'],row['inode']):raise ValueError('Directory replaced: '+str(path))
                    path.rmdir()
                else:
                    if stat_row(root,path)!=row:raise ValueError('File changed during reset: '+str(path))
                    guards.check_file_unused(path)
                    path.unlink()
                    result['removed_file_count']+=1
                    result['removed_bytes']+=row['bytes']
                record_operation('removed',result['pending_operation'])
                result.pop('pending_operation',None);save()
            result['removed'].append(run['path']);save()
        check_preserved();usage();result['status']='completed';save()
    except BaseException as error:
        result.update(status='stopped_partial',error=str(error))
        result['remaining_candidates']=[r['path'] for r in plan['runs'] if r['path'] not in result['removed']]
        try:usage()
        except OSError as measurement_error:result['space_measurement_error']=str(measurement_error)
        if isinstance(error,JournalPersistenceError):
            # Do not start another publication/retry cycle after a definitive
            # persistence failure. Preserve the last receipt and pending bytes.
            print(f'Cleanup stopped: {error}; last published receipt={log}; '
                  f'uncommitted temporary is not a receipt; '
                  f'removed_file_count={result["removed_file_count"]}; '
                  f'removed_bytes={result["removed_bytes"]}; '
                  f'file_operations={result["file_operations"]}. No rollback.',file=sys.stderr)
        else:
            try:save()
            except BaseException as diagnostic_error:
                # Reporting must never replace the original application error.
                print(f'Cleanup original error: {type(error).__name__}: {error}; '
                      f'diagnostic save also failed: {diagnostic_error}; '
                      f'last published receipt={log}; file_operations={result["file_operations"]}. '
                      'Pending temporaries are not committed receipts. No rollback.',file=sys.stderr)
        raise
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project',type=Path,default=ROOT)
    p.add_argument('--plan',type=Path,required=True)
    p.add_argument('--apply',action='store_true');p.add_argument('--confirm')
    p.add_argument('--plan-sha256',help='Required with --apply: fingerprint of the reviewed plan')
    p.add_argument('--exclude',action='append',default=[],help='Additional exclusion; mandatory failed run cannot be removed')
    a=p.parse_args(argv);root=a.project.absolute()
    try:
        relative=a.plan.absolute().relative_to(root) if a.plan.is_absolute() else a.plan
        if relative.parts[:2]!=('runtime','maintenance'):raise ValueError('Plan must be under runtime/maintenance')
        path=safe(root,relative)
        if a.apply:
            if a.exclude:raise ValueError('Exclusions belong to the saved plan; regenerate it to change them')
            if not a.plan_sha256 or sha(path)!=a.plan_sha256:raise ValueError('Reviewed plan hash missing or changed')
            output=apply(root,read_json(path),a.confirm)
        else:
            if a.confirm or a.plan_sha256:raise ValueError('Confirmation/hash only with --apply')
            data=inventory(root,exclusions=a.exclude);path.parent.mkdir(parents=True,exist_ok=True)
            # Overwriting an old plan is refused, avoiding accidental approval of a different inventory.
            with path.open('x',encoding='utf-8') as f:json.dump(data,f,indent=2)
            output=dict(status='plan_only',plan=str(path),plan_sha256=sha(path),
                        runs=[{k:r[k] for k in ('path','run_id','status','bytes','dependencies')} for r in data['runs']],
                        exclusions=data['exclusions'],skipped=[dict(path=r['path'],reasons=r['reasons']) for r in data['skipped']],
                        total_gib=round(data['bytes']/1024**3,3),note=data['note'])
        print(json.dumps(output,indent=2));return 0
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as e:
        print('Reset refused/stopped: '+str(e),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
