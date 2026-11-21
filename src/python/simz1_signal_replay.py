"""Native MATSim 15 signals, with exact scenario references and event order."""
from collections import Counter, defaultdict
import math
from simz1_lane_validation import _xml, read_signals, read_lanes

EVENT_TYPE = 'signalGroupStateChangedEvent'
STATES = {'RED', 'REDYELLOW', 'GREEN', 'YELLOW', 'OFF'}


def control_signature(path):
    # Ignore XML whitespace/namespaces and ordering; preserve every setting.
    def node(e):
        return (e.tag,tuple(sorted(e.attrib.items())),(e.text or '').strip(),tuple(sorted(node(c) for c in e)))
    return node(_xml(path))


def signal_groups(systems_path, groups_path, links, lanes_path=None):
    systems = read_signals(systems_path)
    lanes = read_lanes(lanes_path) if lanes_path else {}
    result, assigned = [], set()
    seen = set()
    for system in _xml(groups_path).findall('signalSystem'):
        sid = system.get('refId')
        if sid not in systems:
            raise ValueError(f'Grupo de sistema desconocido: {sid}')
        for group in system.findall('signalGroup'):
            gid = group.get('id')
            if not gid or (sid,gid) in seen:
                raise ValueError(f'Grupo ausente/duplicado: {sid}/{gid}')
            seen.add((sid,gid))
            signals = []
            for ref in group.findall('signal'):
                signal_id = ref.get('refId')
                if signal_id not in systems[sid] or (sid,signal_id) in assigned:
                    raise ValueError(f'Senal ausente o asignada dos veces: {sid}/{signal_id}')
                assigned.add((sid,signal_id))
                signal = systems[sid][signal_id]
                if signal['link'] not in links:
                    raise ValueError(f'Senal con enlace ajeno: {signal}')
                if not set(signal['lanes']).issubset(lanes.get(signal['link'],{})):
                    raise ValueError(f'Senal con carril ajeno: {signal}')
                if not set(signal['turning_moves']).issubset(links):
                    raise ValueError(f'Senal con destino ajeno: {signal}')
                signals.append(dict(signal_id=signal_id, **signal))
            if not signals:
                raise ValueError(f'Grupo vacio: {sid}/{gid}')
            result.append(dict(system_id=sid, group_id=gid, signals=sorted(signals,key=lambda s:s['signal_id'])))
    if assigned != {(sid,ident) for sid,signals in systems.items() for ident in signals}:
        raise ValueError('Senales sin correspondencia exacta con grupos')
    return sorted(result,key=lambda g:(g['system_id'],g['group_id']))


def selected_groups(selection, links):
    from simz1_run import checked_path, parameters
    directory, manifest = selection['directory'], selection['manifest']
    config = parameters(checked_path(directory, manifest['effective_config']))
    if config.get('signalsystems.useSignalsystems') != 'true':
        return []
    def source(name):
        item = manifest['inputs'].get('input:signalsystems-'+name+'.xml')
        if item is None:
            # Input copies can also be gzip files; use the configured path and
            # require it to be one of this manifest's verified artifacts.
            expected = (directory/config['signalsystems.'+name]).resolve()
            item = next((a for a in manifest['inputs'].values()
                         if (directory/a['path']).resolve() == expected), None)
        if item is None:
            raise ValueError(f'Sin entrada semaforica verificada: {name}')
        return checked_path(directory,item)
    lane_path = None
    if config.get('qsim.useLanes') == 'true':
        lane_path = next(checked_path(directory,a) for a in manifest['inputs'].values()
                         if (directory/a['path']).resolve() == (directory/config['network.laneDefinitionsFile']).resolve())
    return signal_groups(source('signalsystems'),source('signalgroups'),links,lane_path)


class SignalReplay:
    def __init__(self, groups, *, retain_series=True):
        self.retain_series = retain_series
        self.groups = groups
        self.series = {(g['system_id'],g['group_id']): [] for g in groups}
        self.states = {}
        self.by_link = defaultdict(list)
        for group in groups:
            for signal in group['signals']:
                self.by_link[signal['link']].append((group,signal))
        self.event_count = 0
        self.state_counts = Counter()
        self.crossings = Counter()

    def add(self, attrs):
        if attrs.get('type') == EVENT_TYPE:
            key = (attrs.get('signalSystemId'),attrs.get('signalGroupId'))
            if key not in self.series:
                raise ValueError(f'Evento semaforico de grupo ajeno: {key}')
            time, state = float(attrs['time']), attrs.get('signalGroupState')
            if not math.isfinite(time) or state not in STATES:
                raise ValueError(f'Estado/tiempo semaforico invalido: {attrs}')
            series = self.series[key]
            if series and time < series[-1][0]:
                raise ValueError(f'Eventos semaforicos fuera de orden: {key}')
            # Multiple distinct states at initialization can share a timestamp.
            # Preserve file order, but never silently discard duplicated events.
            for previous in reversed(series):
                if previous[0] != time: break
                if previous[1] == state:
                    raise ValueError(f'Evento semaforico duplicado: {key}/{time}/{state}')
            if not self.retain_series and series and series[-1][0] < time:
                series.clear()
            series.append([time,state])
            self.states[key] = state
            self.event_count += 1
            self.state_counts[state] += 1
        elif attrs.get('type') == 'simz1NativeDecision' and attrs.get('reason') == 'turn_go':
            candidates = [(g,s) for g,s in self.by_link.get(attrs.get('link'),[])
                          if (not s['lanes'] or attrs.get('lane') in s['lanes'])
                          and (not s['turning_moves'] or attrs.get('nextLink') in s['turning_moves'])]
            for group, signal in candidates:
                state = self.states.get((group['system_id'],group['group_id']))
                if state not in ('GREEN','YELLOW','OFF') or attrs.get('nativeHasGreen') != 'true':
                    raise ValueError(f'Movimiento sin permiso semaforico nativo: estado={state}, evento={attrs}')
                self.crossings[state] += 1

    def summary(self):
        return dict(event_count=self.event_count, state_counts=dict(self.state_counts),
                    groups=len(self.groups), groups_with_events=sum(bool(s) for s in self.series.values()),
                    permitted_decisions_by_state=dict(self.crossings), duplicate_events=0,
                    missing_state='UNKNOWN; no extrapolation before first event',
                    source='MATSim SignalGroupStateChangedEvent; original file order')

    def payload(self):
        if not self.retain_series:
            raise ValueError('La auditoria incremental no conserva series para replay')
        return dict(**self.summary(), series=[dict(**group, states=self.series[group['system_id'],group['group_id']])
                                             for group in self.groups])
