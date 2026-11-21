"""Reproducible measurements; fixtures are distinguished from actual Lab07 runs."""
import argparse
import ctypes
from ctypes import wintypes
from collections import defaultdict, deque
from dataclasses import replace
import gc
import json
import math
from pathlib import Path
import platform
import pickle
import statistics
import time
import tracemalloc

from microscopic_traffic import (Vehicle, Profile, Operation, Sample, LaneIndex,
    lane_change_candidate, agent_profile, MicroscopicPlayback, DAY_SECONDS,
    daily_operations, read_operations, position, speed_color, PlaybackClock, GAP)


def memory():
    class Counters(ctypes.Structure):
        _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD)] + [
            (n, ctypes.c_size_t) for n in ('PeakWorkingSetSize', 'WorkingSetSize',
            'QuotaPeakPagedPoolUsage', 'QuotaPagedPoolUsage', 'QuotaPeakNonPagedPoolUsage',
            'QuotaNonPagedPoolUsage', 'PagefileUsage', 'PeakPagefileUsage')]
    if platform.system() != 'Windows':
        return {}
    c = Counters()
    c.cb = ctypes.sizeof(c)
    kernel = ctypes.WinDLL('kernel32')
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL('psapi')
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(c), c.cb):
        raise ctypes.WinError()
    return {'rss_mib': c.WorkingSetSize / 2**20, 'peak_rss_mib': c.PeakWorkingSetSize / 2**20}


def timings(values):
    values = sorted(values)
    return {'count': len(values), 'mean_ms': statistics.mean(values) * 1000,
            'p50_ms': values[len(values)//2]*1000,
            'p95_ms': values[min(len(values)-1, int(len(values)*.95))]*1000,
            'max_ms': values[-1]*1000}


def probes():
    # 1500 vehicles in 4 lanes. Long link intentionally isolates neighbor cost.
    road = dict(length=6000, lanes=4, lane_changing=True)
    vehicles = [Vehicle(str(i), [Operation('l', 0, 0)], Profile(1, 0),
                        lane=i%4, distance=30+(i//4)*12, speed=4+i%11) for i in range(1500)]
    occupied = defaultdict(list)
    for v in vehicles:
        occupied['l', v.lane].append(v)
    index = LaneIndex(occupied)
    old = [lane_change_candidate(v, road, occupied, 10, 20) for v in vehicles]
    new = [lane_change_candidate(v, road, occupied, 10, 20, index) for v in vehicles]
    assert old == new
    result = {'fixture': '1500 vehicles, four lanes, 6000m link; identical decisions', 'neighbors': {}}
    for name in ('linear', 'indexed'):
        samples = []
        cpu = time.process_time()
        wall = time.perf_counter()
        for _ in range(12):
            start = time.perf_counter()
            idx = LaneIndex(occupied) if name == 'indexed' else None
            for v in vehicles:
                lane_change_candidate(v, road, occupied, 10, 20, idx)
            samples.append(time.perf_counter()-start)
        result['neighbors'][name] = dict(timings(samples), cpu_s=time.process_time()-cpu,
                                         wall_s=time.perf_counter()-wall)
    # Exact previous eager construction vs new lazy departure descriptors.
    routes = {str(i): [Operation(str(j), i, i+1) for j in range(20)] for i in range(72000)}
    result['construction'] = {}
    for name in ('eager', 'lazy'):
        gc.collect()
        tracemalloc.start()
        start, cpu = time.perf_counter(), time.process_time()
        if name == 'eager':
            pending = [Vehicle(f'{day}::{a}', [replace(op, start=op.start+day*86400,
                        end=op.end+day*86400) for op in ops], agent_profile(a), seed_agent=a)
                       for day in range(3) for a, ops in sorted(routes.items())]
            pending = deque(sorted(pending, key=lambda v: (v.op.start, v.agent)))
        else:
            pending = deque(sorted((ops[0].start+day*86400, f'{day}::{a}', day, a)
                                   for day in range(3) for a, ops in routes.items()))
        result['construction'][name] = dict(wall_s=time.perf_counter()-start,
            cpu_s=time.process_time()-cpu, python_peak_mib=tracemalloc.get_traced_memory()[1]/2**20,
            pending=len(pending), **memory())
        tracemalloc.stop()
        del pending
    return result


def network_neighbors(output):
    from visualize_network import load_network
    _, links = load_network(output/'output_network.xml.gz')
    vehicles, occupied = [], defaultdict(list)
    for key, road in links.items():
        for distance in range(12, int(road['length'])-8, 12):
            for lane in range(road['lanes']):
                if len(vehicles) == 1500:
                    break
                v = Vehicle(str(len(vehicles)), [Operation(key, 0, 0)], Profile(1, 0),
                            lane=lane, distance=distance, speed=4+len(vehicles)%9)
                vehicles.append(v)
                occupied[key,lane].append(v)
    assert len(vehicles) == 1500
    index = LaneIndex(occupied)
    expected = [lane_change_candidate(v,links[v.op.link],occupied,10,12.5) for v in vehicles]
    assert expected == [lane_change_candidate(v,links[v.op.link],occupied,10,12.5,index) for v in vehicles]
    result = {'fixture': '1500 vehicles on actual Lab07 link lengths, 12m spacing; identical decisions'}
    for name in ('linear','indexed'):
        samples = []
        cpu, wall = time.process_time(), time.perf_counter()
        for _ in range(50):
            tick = time.perf_counter()
            index = LaneIndex(occupied) if name == 'indexed' else None
            for v in vehicles:
                lane_change_candidate(v,links[v.op.link],occupied,10,12.5,index)
            samples.append(time.perf_counter()-tick)
        result[name] = dict(timings(samples), cpu_s=time.process_time()-cpu, wall_s=time.perf_counter()-wall)
    return result


def steady():
    from unittest.mock import patch
    roads = {str(i): dict(length=192, lanes=3, capacity=2400, freespeed=12.5,
              lane_width=3.2, lane_changing=True, max_active=1500, from_id=str(i),
              to_id=str((i+1)%20), **{'from':(0,0),'to':(192,0)}) for i in range(20)}
    routes = {f'{i}-{d}-{lane}': [Operation(str(i),0,0,first=d/192),Operation(str((i+1)%20),0,0)]
              for i in range(20) for d in range(0,193,8) for lane in range(3)}
    result, reference = {'fixture': '1500 vehicles in a fully blocked three-lane ring'}, {}
    for name in ('recomputed','certified'):
        engine = MicroscopicPlayback(routes,roads,.5,synthetic_stops=False)
        stream = engine.frames(start_time=0,end_time=120)
        from contextlib import nullcontext
        context = patch('microscopic_traffic.absorbing_gridlock',return_value=False) if name == 'recomputed' else nullcontext()
        times, decode = [], []
        wall,cpu = time.perf_counter(),time.process_time()
        with context:
            while True:
                tick = time.perf_counter()
                try:
                    t,frame = next(stream)
                except StopIteration:
                    break
                times.append(time.perf_counter()-tick)
                assert len(frame) == 1500
                tick = time.perf_counter()
                decoded = dict(frame)
                decode.append(time.perf_counter()-tick)
                if t in (0,60,120):
                    if name == 'recomputed':
                        reference[t] = decoded
                    else:
                        assert reference[t] == decoded
        result[name] = dict(physics=timings(times),decode=timings(decode),
             cpu_s=time.process_time()-cpu,wall_s=time.perf_counter()-wall,
             gridlock_time=engine.gridlock_time, memory=memory())
    return result


def capture_state(engine, stream):
    """Capture only at a yielded boundary; resumed state starts at the next tick."""
    local = stream.gi_frame.f_locals
    keys = ('pending','waiting','active','occupied','start','deadline','quiet_gap','vehicle_count','frozen_frame')
    state = {key: local[key] for key in keys}
    state['tick'],state['last_exit'] = local['tick']+1,dict(local['last_exit'])
    state['engine_attrs'] = {key: getattr(engine,key) for key in
        ('completed','peak_active','parking_log','lane_change_log','quiet','gridlock_time')}
    return state


def checkpoint_probe(checkpoint, frames=600):
    """Measure the real saturated state; do not mix it with a full-day run."""
    if checkpoint is None:
        raise ValueError('checkpoint mode requires --resume with a trusted local checkpoint')
    load_start = time.perf_counter()
    with checkpoint.open('rb') as source:
        saved = pickle.load(source)
    engine = saved['engine']
    stream = engine.frames(start_time=0, end_time=2*DAY_SECONDS,
                           repeat_period=DAY_SECONDS, cycles=2,
                           resume_state=saved['state'])
    result = dict(kind='actual Lab07 saturated checkpoint, physics only',
                  checkpoint=str(checkpoint), load_wall_s=time.perf_counter()-load_start,
                  memory_loaded=memory(), completed_before=engine.completed)
    durations = []
    cpu, wall = time.process_time(), time.perf_counter()
    for index in range(frames):
        tick = time.perf_counter()
        t, frame = next(stream)
        durations.append(time.perf_counter()-tick)
        assert len(frame) == 1500
        if index == 0:
            result['start_time'] = t
    elapsed_cpu, elapsed_wall = time.process_time()-cpu, time.perf_counter()-wall
    result.update(end_time=t, frames=frames, physics=timings(durations),
                  wall_s=elapsed_wall, cpu_s=elapsed_cpu,
                  cpu_one_core_percent=100*elapsed_cpu/elapsed_wall,
                  memory_final=memory(), completed_after=engine.completed,
                  moving_final=sum(s.speed > 0 for s in frame.values()))
    stream.close()
    return result


def full(output, destination, resume=None):
    from visualize_network import load_network
    start, cpu = time.perf_counter(), time.process_time()
    saved = None
    if resume:
        with resume.open('rb') as f:
            saved = pickle.load(f)  # Only checkpoints created locally by this harness.
        engine = saved['engine']
        links,routes = engine.links,engine.routes
    else:
        _, links = load_network(output/'output_network.xml.gz')
        routes = daily_operations(read_operations(output/'output_events.xml.gz', links))
    result = {'kind': 'actual Lab07 calibrated, observed routes, two joint cohorts',
              'load_wall_s': time.perf_counter()-start, 'agents_per_day': len(routes),
              'hourly': [], 'midnight': {}, 'memory_loaded': memory()}
    engine = engine if saved else MicroscopicPlayback(routes, links, dt=.5, daily=True)
    stream = engine.frames(start_time=0, end_time=2*DAY_SECONDS, repeat_period=DAY_SECONDS, cycles=2,
                           resume_state=saved['state'] if saved else None)
    samples, dense, last_hour, count = [], [], -1, 0
    simulation_start = time.perf_counter()
    previous_midnight = None
    if saved:
        result = saved['result']
        result['resumed_from'] = str(resume)
        result['timing_scope'] = (
            'CPU and wall totals cover this resumed invocation only; physics '
            'samples include the saved prefix. Hourly wall_s is relative to '
            'the invocation identified by resumed_segment.')
        samples,dense,count,last_hour = saved['samples'],saved['dense'],saved['count'],saved['last_hour']
        previous_midnight = saved['previous_midnight']
    while True:
        tick = time.perf_counter()
        try:
            t, frame = next(stream)
        except StopIteration:
            break
        duration = time.perf_counter()-tick
        samples.append(duration)
        if len(frame) >= 1500:
            dense.append(duration)
        count += 1
        if t in (86399, 86399.5, 86400, 86400.5, 86401):
            summary = {'active': len(frame), 'completed': engine.completed,
                       'moving': sum(s.speed > 0 for s in frame.values()),
                       'day2_visible': sum(a.startswith('1::') for a in frame)}
            if previous_midnight is not None:
                summary['same_ids'] = set(frame) == set(previous_midnight)
                summary['same_positions'] = all(a in previous_midnight and
                    (s.link,s.lane,s.distance)==(previous_midnight[a].link,previous_midnight[a].lane,previous_midnight[a].distance)
                    for a,s in frame.items())
            result['midnight'][str(t)] = summary
            previous_midnight = frame
        hour = int(t//3600)
        if hour != last_hour:
            last_hour = hour
            lanes = defaultdict(list)
            for s in frame.values():
                assert math.isfinite(s.speed) and s.speed >= 0
                lanes[s.link,s.lane].append(s.distance)
            for distances in lanes.values():
                distances.sort()
                assert all(b-a >= GAP-1e-6 for a,b in zip(distances, distances[1:]))
            row = dict(hour=hour, active=len(frame), completed=engine.completed,
                       resumed_segment=bool(saved),
                       gridlock_time=engine.gridlock_time,
                       moving=sum(s.speed>0 for s in frame.values()),
                       wall_s=time.perf_counter()-simulation_start, **memory())
            result['hourly'].append(row)
            print(json.dumps(row), flush=True)
            destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
            if hour == 8 and engine.gridlock_time is None and not saved:
                # Recovery only if the conservative certificate did not close
                # the case; avoid rerunning the morning to inspect a blocker.
                state = capture_state(engine,stream)
                checkpoint = dict(engine=engine,state=state,result=result,samples=samples,dense=dense,
                                  count=count,last_hour=last_hour,previous_midnight=previous_midnight)
                with destination.with_suffix('.checkpoint.pkl').open('wb') as f:
                    pickle.dump(checkpoint,f,protocol=pickle.HIGHEST_PROTOCOL)
                print('Recovery checkpoint saved',flush=True)
    result.update(frames=count, peak_active=engine.peak_active, completed=engine.completed,
                  gridlock_time=engine.gridlock_time,
                  pending=2*len(routes)-engine.completed, quiet=engine.quiet,
                  physics=timings(samples), dense_physics=timings(dense) if dense else None,
                  simulation_wall_s=time.perf_counter()-simulation_start,
                  total_cpu_s=time.process_time()-cpu, total_wall_s=time.perf_counter()-start,
                  memory_final=memory())
    return result


def gui(output, backend='Agg'):
    import matplotlib
    matplotlib.use(backend)
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.colors import to_rgba
    from matplotlib.backend_bases import MouseEvent
    from visualize_network import (load_network, create_traffic_figure, draw_road,
         render_agents, AgentInspector, PlaybackControls)
    _, links = load_network(output/'output_network.xml.gz')
    places = [(key, lane, d) for key, r in links.items() for lane in range(r['lanes'])
              for d in range(12, int(r['length'])-8, 12)][:1500]
    assert len(places) == 1500
    fig, ax, header = create_traffic_figure('Lab07 stress', 'Synthetic 1500-agent UI fixture', controls=True)
    if backend.lower() == 'tkagg':
        fig.canvas.manager.window.withdraw()
    for road in links.values():
        draw_road(ax, road)
    points = ax.scatter([], [], s=5)
    inspector = AgentInspector(ax, points, fig._traffic_panel)
    now = [0.0]
    clock = PlaybackClock(now=lambda: now[0])
    current = {}
    def render(t):
        nonlocal current
        # Deterministic seek fixture; no claim of physical trajectories.
        current = {str(i): Sample(key, lane, d+math.sin(t/100), (i%6)*5,
                      'drive' if i%6 else 'queued', 'stress-fixture', t, t*(i%6)*5, 0)
                   for i,(key,lane,d) in enumerate(places)}
        render_agents(points, current, links, int(t/4))
        inspector.update(t, current)
        header.set_text(f'{t:.1f} | {len(current)} agents')
        return [points,header,inspector.text]
    controls = PlaybackControls(fig, clock, render)
    controls.refresh()
    fig.canvas.draw()
    cpu, wall = time.process_time(), time.perf_counter()
    samples = []
    for t in [0,64800,18000,86399,1,43200]*5:
        tick = time.perf_counter()
        controls.slider.set_val(t)
        fig.canvas.flush_events()
        assert clock.time == t
        assert inspector.time == t
        np.testing.assert_allclose(points.get_offsets(), [position(links[s.link],s.distance,s.lane) for s in current.values()])
        np.testing.assert_allclose(points.get_facecolors(), [to_rgba(speed_color(s.speed,int(t/4))) for s in current.values()])
        target = next(iter(current))
        pixel = ax.transData.transform(points.get_offsets()[0])
        fig.canvas.callbacks.process('motion_notify_event', MouseEvent('motion_notify_event',fig.canvas,*pixel))
        assert inspector.selected_id is not None
        selected = current[inspector.selected_id]
        assert f'{selected.speed*3.6:.2f} km/h' in inspector.text.get_text()
        assert f'{selected.mean_speed*3.6:.2f} km/h' in inspector.text.get_text()
        fig.canvas.draw()
        samples.append(time.perf_counter()-tick)
    for index, scale, rate in ((0,120,0),(0,120,1),(1,1,1),(2,6,1),
                               (3,60,1),(4,120,1),(5,240,1)):
        button = controls.buttons[index]
        x,y = button.ax.transAxes.transform((.5,.5))
        for kind in ('button_press_event','button_release_event'):
            fig.canvas.callbacks.process(kind, MouseEvent(kind,fig.canvas,x,y,button=1))
        assert clock.rate == rate
        assert clock.base_speed == scale
        before = clock.time
        now[0] += .1
        controls.tick()
        assert abs(clock.time-max(0,before+rate*scale*.1)) < 1e-7
        assert inspector.time == clock.time
    result = dict(backend=matplotlib.get_backend(), fixture_agents=1500,
                  seek_hover_render=timings(samples), wall_s=time.perf_counter()-wall,
                  cpu_s=time.process_time()-cpu, memory=memory(), assertions='passed')
    update_times, draw_times = [], []
    for i in range(40):
        tick = time.perf_counter()
        render(64800+i*4)
        update_times.append(time.perf_counter()-tick)
        tick = time.perf_counter()
        fig.canvas.draw()
        draw_times.append(time.perf_counter()-tick)
    result['frame_update'] = timings(update_times)
    result['canvas_draw'] = timings(draw_times)
    result['frame_total'] = timings([a+b for a,b in zip(update_times,draw_times)])
    result['measured_full_draw_fps'] = 1/statistics.mean([a+b for a,b in zip(update_times,draw_times)])
    controls.refresh()  # Restore clock/slider/telemetry after the raw draw benchmark.
    fig.savefig('target/lab07-stress-gui.png')
    controls.close()
    plt.close(fig)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['probes','neighbors','steady','full','gui','checkpoint'])
    parser.add_argument('--output-dir', type=Path, default=Path('output/labs/07-calibrated-zona1'))
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--backend', default='Agg')
    parser.add_argument('--resume', type=Path, help='Trusted local checkpoint from this harness only')
    args = parser.parse_args()
    result = checkpoint_probe(args.resume) if args.mode == 'checkpoint' else probes() if args.mode == 'probes' else steady() if args.mode == 'steady' else network_neighbors(args.output_dir) if args.mode == 'neighbors' else gui(args.output_dir,args.backend) if args.mode == 'gui' else full(args.output_dir,args.result,args.resume)
    result['python'] = platform.python_version()
    result['platform'] = platform.platform()
    args.result.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2), flush=True)
