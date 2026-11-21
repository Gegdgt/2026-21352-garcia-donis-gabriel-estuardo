"""Provisional plots from one explicit run. Reads inputs; writes only diagnostic output.

Never starts MATSim, edits manifests, promotes acceptance, or uses current scenario
inputs in place of the selected run's evidence. Partial gzip/XML prefixes are labelled.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zlib

NOTICE = 'DIAGNOSTICO PROVISIONAL — NO son graficas cientificas completed/valid'


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def log_lines(path):
    with path.open(encoding='utf-8',errors='replace') as stream:
        yield from stream


def local(run, value):
    path=(run/value).resolve(strict=True)
    if not path.is_relative_to(run): raise ValueError('Evidence must be inside the selected run')
    return path


def prefix_events(path, info):
    """Retain complete events before a truncated/corrupt suffix; never accept it."""
    parser=ET.XMLPullParser(events=('start','end'));root=None
    compressed=path.suffix=='.gz'; decoder=zlib.decompressobj(31) if compressed else None
    info.update(complete=False,bytes_read=0,error=None)
    closed=False
    try:
        with path.open('rb') as stream:
            while True:
                chunk=stream.read(65536)
                if not chunk: break
                info['bytes_read']+=len(chunk)
                parser.feed(decoder.decompress(chunk) if decoder else chunk)
                for action, element in parser.read_events():
                    if root is None:
                        if action!='start' or element.tag!='events': raise ValueError('Expected events root')
                        root=element
                    if action=='end' and element.tag=='event':
                        yield dict(element.attrib);element.clear();root.clear()
                    elif action=='end' and element.tag=='events':closed=True
                if decoder and decoder.unused_data:raise ValueError('Unexpected bytes after gzip member')
        parser.close()
        info['complete']=bool(closed and (not decoder or decoder.eof))
        if not info['complete']:info['error']='Incomplete gzip/XML stream'
    except (ET.ParseError,zlib.error,EOFError,OSError,ValueError) as e:
        info['error']=str(e)


def pinned(run, manifest, key):
    rec=manifest.get('inputs',{}).get(key)
    if not rec or not rec.get('sha256'):return None
    path=local(run,rec['path'])
    if digest(path)!=rec['sha256']:raise ValueError('Input hash mismatch: '+key)
    return path


def schedules(run, manifest, missing, sources):
    planned=Counter();road=set();freight=set();buses=set()
    try:
        path=pinned(run,manifest,'plans')
        if path:
            from simz1_freight import is_freight
            with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as f:
                for _, person in ET.iterparse(f,events=('end',)):
                    if person.tag!='person':continue
                    road.add(person.get('id'))
                    if is_freight(person):freight.add(person.get('id'))
                    plan=next((p for p in person.findall('plan') if p.get('selected')=='yes'),person.find('plan'))
                    act=plan.find('act') if plan is not None else None
                    end=act.get('end_time') if act is not None else None
                    if end is not None:
                        parts=end.split(':');seconds=float(end) if len(parts)==1 else sum(float(p)*s for p,s in zip(parts,(3600,60,1)))
                        if math.isfinite(seconds) and seconds>=0:planned[int(seconds//3600)]+=1
                    person.clear()
            sources['scheduled_departures']=str(path.relative_to(run))+' (pinned plans; first activity end_time, road persons only)'
        else: missing.append('Scheduled departures and freight: no pinned plans')
    except (OSError,ValueError,ET.ParseError,EOFError) as e:
        planned.clear();road.clear();freight.clear();missing.append('Plans unavailable: '+str(e))
    try:
        path=pinned(run,manifest,'transit_vehicles')
        if path:
            with (gzip.open(path,'rb') if path.suffix=='.gz' else path.open('rb')) as f:
                buses={v.get('id') for v in ET.parse(f).getroot().findall('{*}vehicle')}
            sources['bus_ids']=str(path.relative_to(run))+' (pinned vehicles)'
    except (OSError,ValueError,ET.ParseError,EOFError) as e:missing.append('Bus roster unavailable: '+str(e))
    return planned,road,freight,buses


def collect(run, manifest, iteration, explicit_events=None):
    missing=[];sources={};rows=defaultdict(Counter);stream={}
    planned,road,freight,buses=schedules(run,manifest,missing,sources)
    result=manifest.get('results',{}).get(str(iteration),{})
    if explicit_events: path=local(run,explicit_events)
    elif result.get('events'): path=local(run,result['events']['path'])
    else:
        candidates=[run/f'output/ITERS/it.{iteration}/{iteration}.events.xml.gz',run/f'output/ITERS/it.{iteration}/{iteration}.events.xml']
        path=next((p for p in candidates if p.is_file()),None)
        if path is None and manifest.get('iterations',{}).get('last')==iteration:
            path=next((p for p in (run/'output/output_events.xml.gz',run/'output/output_events.xml') if p.is_file()),None)
    first=None;last=None;active=set();initial={};observed=set();drivers={};seen=set();metrics=set()
    if path:
        event_source=str(path.relative_to(run));before=(path.stat().st_size,path.stat().st_mtime_ns)
        for event in prefix_events(path,stream):
            try:
                at=float(event['time'])
                if not math.isfinite(at) or at<0 or last is not None and at<last:raise ValueError('Non-monotone event time')
            except (ValueError,KeyError) as e:stream['error']=str(e);stream['complete']=False;break
            hour=int(at//3600)
            if last is not None:
                for bucket in range(int(last//3600),hour):
                    rows[bucket]['active']=len(active)
                    if freight:rows[bucket]['freight_active']=len(active&freight)
                    if buses:rows[bucket]['bus_active']=len(active&buses)
            if first is None:first=at
            last=at;kind=event.get('type');vehicle=event.get('vehicle');seen.add(kind)
            if kind=='TransitDriverStarts':drivers[event.get('driverId')]=event.get('vehicleId')
            if kind=='vehicle enters traffic':
                active.add(vehicle);observed.add(vehicle);initial[vehicle]=event.get('link');rows[hour]['entries']+=1
                if vehicle in road:rows[hour]['road_entries']+=1
            elif kind=='entered link':
                if vehicle in active and initial.pop(vehicle,None)==event.get('link'):continue
                rows[hour]['transitions']+=1
            elif kind=='left link':initial.pop(vehicle,None)
            elif kind in ('vehicle leaves traffic','vehicle aborts','stuckAndAbort'):
                ident=vehicle or drivers.get(event.get('person'),event.get('person'))
                active.discard(ident);initial.pop(ident,None)
            elif kind=='arrival':
                rows[hour]['arrivals']+=1
                ident=drivers.get(event.get('person'),event.get('person'))
                if ident in freight:rows[hour]['freight_arrivals']+=1
                if ident in buses:rows[hour]['bus_arrivals']+=1
            elif kind=='simz1NativeDecision' and event.get('reason')=='storage_wait':rows[hour]['storage_wait_attempts']+=1
            elif kind=='simz1Progress' and 'waitStorage' in event:
                rows[hour]['progress_storage_attempts']+=int(event['waitStorage'])
            rows[hour]['active']=len(active)
            if freight:rows[hour]['freight_active']=len(active&freight)
            if buses:rows[hour]['bus_active']=len(active&buses)
        stream.update(path=event_source,sha256=digest(path),changed_during_read=before!=(path.stat().st_size,path.stat().st_mtime_ns))
        expected=result.get('events',{})
        if expected.get('path')==event_source and expected.get('sha256'):
            stream['hash_matches_manifest']=stream['sha256']==expected['sha256']
            if not stream['hash_matches_manifest']:missing.append('Events differ from manifest hash; observations cannot establish integrity')
        if stream['changed_during_read']:stream['complete']=False;missing.append('Events changed during reading; snapshot is provisional')
        for metric,kind in (('transitions','entered link'),('arrivals','arrival'),('entries','vehicle enters traffic'),('active','vehicle enters traffic')):
            if kind in seen:metrics.add(metric);sources[metric]=event_source+': '+kind
        if 'simz1NativeDecision' in seen:
            metrics.add('storage_wait_attempts');sources['storage_wait_attempts']=event_source+': simz1NativeDecision reason=storage_wait; attempts, not duration/unique vehicles'
        elif any('progress_storage_attempts' in r for r in rows.values()):
            metrics.add('storage_wait_attempts');sources['storage_wait_attempts']=event_source+': simz1Progress waitStorage delta, assigned to interval end hour'
            for r in rows.values():r['storage_wait_attempts']=r['progress_storage_attempts']
        if 'active' in metrics:
            if freight:metrics.add('freight_active');sources['freight_active']=event_source+' + pinned plans simz1FreightService'
            if buses:metrics.add('bus_active');sources['bus_active']=event_source+' + '+sources['bus_ids']
        if road and 'entries' in metrics:metrics.add('road_entries');sources['road_entries']=event_source+' vehicle enters traffic filtered to pinned road persons'
    if not path or last is None:
        # Exact native progress format; never infer metrics from arbitrary text.
        log=run/'matsim-run.log'
        if log.is_file():
            for line in log_lines(log):
                m=re.search(r'SIMZ1_PROGRESS simulatedTime=([\d.]+) \{([^}]+)\}',line)
                if not m:continue
                data=dict(p.strip().split('=',1) for p in m[2].split(', ') if '=' in p)
                if data.get('iteration')!=str(iteration):continue
                at=float(m[1]);hour=int(at//3600)
                if last is not None and at<last:missing.append('Log time reset; stopped at first iteration stream');break
                first=at-float(data.get('elapsedSimSeconds',0)) if first is None else first;last=at
                for metric,key in (('transitions','linkTransitions'),('arrivals','arrivals'),('storage_wait_attempts','waitStorage'),('active','activeVehicles')):
                    if key not in data:continue
                    value=int(data[key])
                    if value<0:continue
                    if metric=='active':rows[hour][metric]=value
                    else:rows[hour][metric]+=value
                    metrics.add(metric);sources[metric]='matsim-run.log: SIMZ1_PROGRESS '+key+'; deltas assigned to end hour, no interpolation'
            stream=dict(path='matsim-run.log',sha256=digest(log),complete=False,error='Log-only observations; no complete event stream')
    if planned and 'road_entries' in metrics:
        metrics.add('scheduled_departures')
        for h,n in planned.items():rows[h]['scheduled_departures']=n
    for metric in ('transitions','arrivals','active','storage_wait_attempts','scheduled_departures','freight_active','bus_active'):
        if metric not in metrics:missing.append(metric+': insufficient evidence; no metric fabricated')
    if last is None:missing.append('No usable event/progress interval; PNG metrics cannot be generated')
    missing.append('Arrivals are native event observations, not proof of body clearance or accepted trip completion')
    if first is not None and first>0:missing.append('Prefix before first observed time not proven; active counts may be lower bounds')
    return dict(rows=rows,metrics=sorted(metrics),sources=sources,missing=missing,stream=stream,
                covered_seconds=[first,last],distinct_traffic_vehicles=len(observed))


def generate(run, expected_id, iteration=0, events=None):
    run=Path(run).resolve(strict=True);mp=run/'run-manifest.json';mh=digest(mp)
    manifest=json.loads(mp.read_text(encoding='utf-8-sig'))
    if manifest.get('run_id')!=expected_id:raise ValueError('Run ID mismatch')
    if manifest.get('folder') and Path(manifest['folder']).resolve()!=run:raise ValueError('Manifest folder mismatch')
    data=collect(run,manifest,iteration,events)
    if digest(mp)!=mh:raise ValueError('Manifest changed while reading; rerun after it stabilizes')
    out=run/'analysis/diagnostico-provisional'
    if not out.resolve().is_relative_to(run):raise ValueError('Diagnostic destination escapes selected run')
    out.mkdir(parents=True,exist_ok=True)
    # Keep every prior diagnostic export; never overwrite historical evidence.
    from datetime import datetime, timezone
    import uuid
    out=out/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]);out.mkdir()
    report=dict(schema_version='simz1-diagnostic-provisional-v1',notice=NOTICE,run_id=expected_id,
        manifest_status=manifest.get('status'),manifest_validation=manifest.get('validation'),manifest_sha256=mh,
        iteration=iteration,acceptance_unchanged=True,incomplete_data=True,**{k:v for k,v in data.items() if k!='rows'})
    report['png_files']=[]
    if data['metrics'] and data['covered_seconds'][1] is not None:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        first,last=data['covered_seconds'];hours=list(range(int(first//3600),int(last//3600)+1))
        for metric in data['metrics']:
            if metric in ('scheduled_departures','road_entries'):continue
            fig,ax=plt.subplots(figsize=(12,6))
            values=[data['rows'][h].get(metric,0) if h in data['rows'] else math.nan for h in hours]
            ax.plot(hours,values,marker='o')
            ax.set(xlabel='Hora simulada (ultima cubeta parcial)',ylabel=metric,title=metric)
            label=f'{NOTICE}\nRun ID: {expected_id} | manifiesto: {manifest.get("status")} / {manifest.get("validation",{}).get("status")}\nCobertura: {first:g}–{last:g} s | DATOS INCOMPLETOS\nFuente: {data["sources"][metric]}'
            fig.text(.02,.02,label,fontsize=8,wrap=True);fig.subplots_adjust(bottom=.28)
            name=metric+'.png';fig.savefig(out/name,dpi=140);plt.close(fig);report['png_files'].append(name)
        if 'scheduled_departures' in data['metrics']:
            fig,ax=plt.subplots(figsize=(12,6))
            ax.plot(hours,[data['rows'][h]['scheduled_departures'] for h in hours],label='Programadas: primera actividad vial')
            ax.plot(hours,[data['rows'][h]['road_entries'] for h in hours],label='Incorporaciones viales observadas')
            ax.legend();ax.set(xlabel='Hora simulada',ylabel='Salidas / incorporaciones')
            fig.text(.02,.02,f'{NOTICE}\nRun ID: {expected_id} | {manifest.get("status")} / {manifest.get("validation",{}).get("status")} | {first:g}–{last:g} s\nDATOS INCOMPLETOS\nFuentes: {data["sources"]["scheduled_departures"]}\n{data["sources"]["road_entries"]}',fontsize=8,wrap=True)
            fig.subplots_adjust(bottom=.3);name='programadas-vs-incorporaciones.png';fig.savefig(out/name,dpi=140);plt.close(fig);report['png_files'].append(name)
    with (out/'hours.csv').open('w',encoding='utf-8',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['hour']+data['metrics']);w.writeheader()
        first,last=data['covered_seconds']
        if last is not None:
            for h in range(int(first//3600),int(last//3600)+1):
                row=data['rows'].get(h)
                w.writerow(dict(hour=h,**{k:row.get(k,0) if row is not None else None for k in data['metrics']}))
    (out/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(run_id=expected_id,status='provisional',output=str(out),png_files=report['png_files']),ensure_ascii=False))
    return 0 if report['png_files'] else 2


def main():
    p=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--expected-run-id',required=True)
    p.add_argument('--iteration',type=int,default=0);p.add_argument('--events',help='Explicit path inside selected run, if native location differs')
    a=p.parse_args()
    try:return generate(a.run_dir,a.expected_run_id,a.iteration,a.events)
    except (OSError,ValueError,KeyError,ET.ParseError) as e:print('Diagnostic blocked: '+str(e),file=sys.stderr);return 1


if __name__=='__main__':sys.exit(main())
