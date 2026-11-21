"""Streaming checks of observed SimZ1 movements; no inference of abort causes."""
import json
import xml.etree.ElementTree as ET


def enabled_lane_movements(path):
    """Reachable to-link targets declared in the enabled lane definitions.

    Link events do not identify the physical lane occupied by a vehicle. This
    validates existence of an enabled movement; QSim's per-agent lane/position
    checks must additionally run before a reroute is installed.
    """
    movements = {}
    for assignment in ET.parse(path).getroot().findall('{*}lanesToLinkAssignment'):
        link = assignment.get('linkIdRef')
        movements[link] = {item.get('refId') for item in assignment.findall('.//{*}toLink')}
    return movements


class MovementAudit:
    def __init__(self, links, lane_movements=None, *, expected_budget=None, expected_enabled=None,
                 registered_vehicle_modes=None):
        # link id -> (from node, to node, allowed modes)
        self.links = links
        self.lane_movements = lane_movements or {}
        self.previous_leave = {}
        self.current_link = {}
        self.initial_enter = set()
        self.vehicle_modes = {}
        # MATSim 15 transit drivers use a car leg internally. Only a separately
        # validated VehicleType registry may supply the physical network mode.
        # Keep the raw event untouched, including its native networkMode field.
        self.registered_vehicle_modes = dict(registered_vehicle_modes or {})
        if any(not vehicle or not mode for vehicle, mode in self.registered_vehicle_modes.items()):
            raise ValueError('Registered vehicle mode requires explicit vehicle/type identities')
        self.expected_budget = expected_budget
        self.expected_enabled = expected_enabled
        self.counts = dict(physical_transitions=0, invalid_physical_transitions=0,
                           reroute_rejections=0, reroute_installations=0,
                           reroute_validated_candidates=0,
                           invalid_current_route_events=0)
        self.rerouting = dict(steps=0, candidates=0, calculations=0, installed=0, rejected=0,
                             deferred=0, cpu_nanos=0, cpu_timed_steps=0, wall_nanos=0,
                             max_calculations_per_step=0, max_attempts_per_step=0,
                             budget=expected_budget)

    def reject(self, reason, event, previous=None):
        self.counts['invalid_physical_transitions'] += 1
        evidence = dict(reason=reason, event=dict(event.attrib), previous_leave=previous)
        raise ValueError('Transicion fisica invalida: '+json.dumps(evidence, ensure_ascii=False))

    def record_step(self, event):
        def invalid(reason):
            raise ValueError('Metricas de reruteo invalidas: '+json.dumps(
                dict(reason=reason, event=dict(event.attrib)), ensure_ascii=False))
        values = {}
        for key in ('candidates','calculations','installed','rejected','deferred','budget','cpuNanos','wallNanos'):
            try:
                values[key] = int(event.get(key))
            except (TypeError, ValueError):
                invalid(f'{key} debe ser entero')
            if values[key] < (-1 if key == 'cpuNanos' else 1 if key == 'budget' else 0):
                invalid(f'{key} fuera de rango')
        enabled = event.get('enabled')
        if enabled not in ('true','false'):
            invalid('enabled debe ser true/false')
        if self.expected_enabled is not None and (enabled == 'true') != self.expected_enabled:
            invalid('enabled difiere de la configuracion efectiva')
        if self.expected_budget is not None and values['budget'] != self.expected_budget:
            invalid('budget difiere de la configuracion efectiva')
        if self.rerouting['budget'] is not None and values['budget'] != self.rerouting['budget']:
            invalid('budget cambio entre pasos')
        self.rerouting['budget'] = values['budget']
        attempts = values['candidates'] - values['deferred']
        if attempts != min(values['budget'], values['candidates']):
            invalid('candidatos atendidos/deferred no respetan el presupuesto')
        if values['calculations'] > attempts or values['installed'] > values['calculations']:
            invalid('calculos/instalaciones exceden los intentos permitidos')
        if values['installed'] + values['rejected'] > attempts:
            invalid('instalaciones y rechazos exceden los intentos permitidos')
        if enabled == 'false' and any(values[key] for key in ('candidates','calculations','installed','rejected','deferred')):
            invalid('reruteo apagado con trabajo registrado')
        for key in ('candidates','calculations','installed','rejected','deferred'):
            self.rerouting[key] += values[key]
        self.rerouting['steps'] += 1
        self.rerouting['wall_nanos'] += values['wallNanos']
        if values['cpuNanos'] >= 0:
            self.rerouting['cpu_nanos'] += values['cpuNanos']
            self.rerouting['cpu_timed_steps'] += 1
        self.rerouting['max_calculations_per_step'] = max(self.rerouting['max_calculations_per_step'],values['calculations'])
        self.rerouting['max_attempts_per_step'] = max(self.rerouting['max_attempts_per_step'],attempts)

    def summary(self):
        if self.rerouting['steps'] and (self.rerouting['installed'] != self.counts['reroute_installations'] or
                                       self.rerouting['rejected'] != self.counts['reroute_rejections']):
            raise ValueError('Metricas agregadas de reruteo no coinciden con los eventos individuales')
        return dict(self.rerouting)

    def consume(self, event):
        kind = event.get('type')
        if kind == 'zona1RerouteRejected':
            self.counts['reroute_rejections'] += 1
        elif kind == 'zona1WithinDayReroute':
            if event.get('changed') not in ('true','false'):
                raise ValueError('Evento de reruteo validado sin changed=true/false')
            self.counts['reroute_validated_candidates'] += 1
            self.counts['reroute_installations'] += event.get('changed') == 'true'
        elif kind == 'zona1RerouteStep':
            self.record_step(event)
        elif kind == 'zona1InvalidCurrentRoute':
            self.counts['invalid_current_route_events'] += 1
            raise ValueError('Ruta actual invalida registrada por QSim: '+json.dumps(dict(event.attrib), ensure_ascii=False))
        if kind not in ('vehicle enters traffic', 'vehicle leaves traffic', 'left link', 'entered link'):
            return
        vehicle, link = event.get('vehicle'), event.get('link')
        if not vehicle or link not in self.links:
            self.reject('vehicle/link ausente o desconocido', event)
        if kind == 'vehicle leaves traffic':
            self.previous_leave.pop(vehicle, None)
            self.current_link.pop(vehicle, None)
            self.initial_enter.discard(vehicle)
            self.vehicle_modes.pop(vehicle, None)
            return
        if kind == 'vehicle enters traffic':
            self.previous_leave.pop(vehicle, None)  # New trip, possibly a different origin.
            self.current_link[vehicle] = dict(link=link, time=event.get('time'))
            self.initial_enter.add(vehicle)
            self.vehicle_modes[vehicle] = self.registered_vehicle_modes.get(vehicle, event.get('networkMode', 'car'))
        mode = self.registered_vehicle_modes.get(vehicle, self.vehicle_modes.get(vehicle, 'car'))
        if mode not in self.links[link][2]:
            self.reject(f'enlace no habilitado para {mode}', event)
        if kind == 'left link':
            current = self.current_link.get(vehicle)
            if current is not None and current['link'] != link:
                self.reject('LinkLeave no coincide con el enlace actual conocido', event, current)
            if vehicle in self.previous_leave:
                self.reject('LinkLeave duplicado sin LinkEnter', event, self.previous_leave[vehicle])
            self.initial_enter.discard(vehicle)
            self.previous_leave[vehicle] = dict(link=link, time=event.get('time'))
        elif kind == 'entered link':
            previous = self.previous_leave.pop(vehicle, None)
            if previous is not None:
                self.counts['physical_transitions'] += 1
                source = previous['link']
                if self.links[source][1] != self.links[link][0]:
                    self.reject('toNode(anterior) != fromNode(siguiente)', event, previous)
                if source in self.lane_movements and link not in self.lane_movements[source]:
                    self.reject('movimiento ausente en carriles habilitados', event, previous)
            elif vehicle in self.current_link:
                current = self.current_link[vehicle]
                if vehicle not in self.initial_enter or current['link'] != link:
                    self.reject('LinkEnter sin LinkLeave del enlace actual conocido', event, current)
            # A partial fixture may begin with LinkEnter; its first origin is
            # unknowable, but every subsequent movement now has known state.
            self.current_link[vehicle] = dict(link=link, time=event.get('time'))
            self.initial_enter.discard(vehicle)


def unfinished_counts(pending, aborted, horizon=None):
    """Keep all unfinished trips, but separate earlier aborts from the horizon.

    MATSim may emit stuckAndAbort while draining QSim at its configured end.
    Such events are reported explicitly; their cause is not called route damage.
    """
    aborts = {person: time for person, time in aborted.items() if person in pending}
    at_horizon = sum(horizon is not None and time >= horizon for time in aborts.values())
    earlier = len(aborts) - at_horizon
    return dict(incomplete_trips=len(pending), aborted_trips=len(aborts),
                aborted_before_horizon=earlier, horizon_abort_events=at_horizon,
                pending_trips_at_horizon=len(pending)-earlier)
