"""Synthetic event/export benchmark only. Does not run MATSim or publish a run."""
import argparse
import gzip
import heapq
import json
import os
from pathlib import Path
import time
import tracemalloc
import visualizador_z1 as viewer
from simz1_motion import MotionContext


def peak_rss():
    if os.name != 'nt':
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024
    import ctypes
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in
            ('PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
             'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    info=Counters();info.cb=ctypes.sizeof(info)
    kernel=ctypes.WinDLL('kernel32');kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi');psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(info),info.cb):raise ctypes.WinError()
    return info.PeakWorkingSetSize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--agents',type=int,required=True)
    parser.add_argument('--output-dir',type=Path,default=Path('target/prompt7-benchmark'))
    parser.add_argument('--trace-memory',action='store_true')
    parser.add_argument('--no-html',action='store_true')
    args=parser.parse_args()
    if args.agents<1:parser.error('--agents must be positive')
    folder=args.output_dir/str(args.agents);folder.mkdir(parents=True,exist_ok=True)
    path=folder/'synthetic-events.xml.gz'
    scheduled=[]
    def end_events(i,t):
        return f'<event type="vehicle leaves traffic" time="{t}" person="p{i}" vehicle="v{i}" link="l" relativePosition="1"/><event type="arrival" time="{t}" person="p{i}" link="l"/>\n'
    with gzip.open(path,'wt') as stream:
        stream.write('<events>\n')
        for i in range(args.agents):
            t=i*86300/args.agents
            while scheduled and scheduled[0][0]<=t:
                end,j=heapq.heappop(scheduled);stream.write(end_events(j,end))
            stream.write(f'<event type="departure" time="{t}" person="p{i}" link="l"/><event type="vehicle enters traffic" time="{t}" person="p{i}" vehicle="v{i}" link="l" relativePosition="0"/>\n')
            heapq.heappush(scheduled,(t+180,i))
        for end,j in sorted(scheduled):stream.write(end_events(j,end))
        stream.write('</events>')
    if args.trace_memory:tracemalloc.start()
    start=time.perf_counter()
    context=MotionContext({f'v{i}':20/3.6 for i in range(args.agents)},
                          {f'p{i}':'Tortuga' for i in range(args.agents)},lanes=False)
    metadata_done=time.perf_counter()
    viewer.EVENTS_FILE=path
    links={'l':dict(length=1000,freespeed=50/3.6,**{'from':[-90.51,14.63],'to':[-90.50,14.63]})}
    stats={};segments=viewer.extraer_trayectorias(links,motion=context,stats=stats)
    events_done=time.perf_counter()
    assert len(segments)==args.agents and stats['observed_persons']==args.agents
    assert all(s['Movement_End']==s['timestamps'][1] for s in segments)
    if not args.no_html:viewer.generar_html_animado(segments,links,output=folder/'replay.html')
    end=time.perf_counter()
    report=dict(agents=args.agents,segments=len(segments),events=4*args.agents,
        phases_seconds=dict(metadata=metadata_done-start,trajectories=events_done-metadata_done,html=end-events_done,total=end-start),
        python_traced_peak_bytes=tracemalloc.get_traced_memory()[1] if args.trace_memory else None,
        process_peak_working_set_bytes=peak_rss(),html_bytes=(folder/'replay.html').stat().st_size if not args.no_html else None,
        synthetic=True,matsim_executed=False,gpu_measured=False,
        note='One free 1 km link per vehicle, 20 km/h; synthetic export load, not a traffic stability experiment')
    if args.trace_memory:tracemalloc.stop()
    (folder/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
