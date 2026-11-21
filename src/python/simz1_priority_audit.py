"""Validate queue-head waits against executed MATSim link transitions.

Decision counts are attempts, not seconds. The head-to-cross duration is measured
from emitted events. A GO with a full target is never counted as a crossing.
"""
from collections import Counter
import math
from simz1_native_validation import native_wait_category, checked_wait_category


class PriorityAudit:
    def __init__(self, *, legacy_bus_context=None):
        self.policy = {}
        self.legacy_bus_context = legacy_bus_context
        self.reconstructed_policy_keys = set()
        self.native_policy_keys = set()
        self.full_mode_coverage = False
        self.policy_by_link = {}
        from simz1_priority_passage import PassagePriorityCredit
        self.passage_credit = PassagePriorityCredit(self.policy_by_link)
        self.heads = {}
        self.head_by_vehicle = {}
        self.awaiting_cross = {}
        self.leaves, self.enters = {}, {}
        self.actions, self.reasons, self.sources = Counter(), Counter(), Counter()
        self.native_reasons, self.wait_causes = Counter(), Counter()
        self.wait_by_role = {role: dict(count=0, total_seconds=0., maximum_seconds=0., minimum_seconds=None)
                             for role in ('street', 'avenue')}
        self.forced_crossings = 0
        self.nodes, self.eligible_nodes = set(), set()
        self.crossings = self.street_crossings = 0
        self.max_wait = 0.
        self.min_street_wait = None
        self.crossing_examples = []

    @staticmethod
    def _matches_policy(observed, expected):
        numeric = {'stopSeconds', 'appliedStopSeconds', 'maxYieldSeconds'}
        for key, value in expected.items():
            actual = observed.get(key)
            if key in numeric:
                try:
                    agrees = math.isfinite(float(actual)) and float(actual) == float(value)
                except (TypeError, ValueError):
                    agrees = False
            else:
                agrees = actual == value
            if not agrees:
                raise ValueError(f'Prioridad nativa invalida: {key} difiere de entradas verificadas: {dict(observed)}')

    def _policy_for_link(self, link, event, verified_transit):
        policy = self.policy_by_link.get(link)
        if policy is not None:
            if (policy['node'], link) in self.reconstructed_policy_keys and not verified_transit:
                raise ValueError('Prioridad nativa invalida: politica reconstruida requiere bus verificado')
            return policy
        context = self.legacy_bus_context
        if not context or not verified_transit or context['vehicle_modes'].get(event.get('vehicle')) != 'bus':
            return {}
        policy = context['bus_only'].get(link)
        if policy is None:
            return {}  # Never infer missing car/shared-mode policies or strip a prefix.
        if self.full_mode_coverage:
            raise ValueError('Prioridad nativa invalida: emisor car-bus-v2 omitio politica de bus')
        key = (policy['node'], link)
        self.policy[key] = dict(policy)  # Derived evidence, NOT a fabricated event.
        self.policy_by_link[link] = self.policy[key]
        self.reconstructed_policy_keys.add(key)
        self.sources[policy['classificationSource']] += 1
        if policy['eligible'] == 'true':
            self.eligible_nodes.add(policy['node'])
        return self.policy[key]

    def consume(self, event, *, verified_transit=False):
        self.passage_credit.consume(event)
        kind = event.get('type')
        if kind == 'simz1NativeDecision':
            reason = event.get('reason', 'unknown')
            self.native_reasons[reason] += 1
            observed_category = checked_wait_category(event)
            version2 = event.get('waitCategoryVersion') == '2'
            if event.get('decision') == 'WAIT' or not version2 and event.get('decision') == 'ABORT':
                category = observed_category if version2 else native_wait_category(reason)
                # Historical flow-capacity labels predate version 2; preserve their interpretation.
                if not version2 and reason.startswith(('congestion', 'flow_capacity')):
                    category = 'congestion'
                self.wait_causes[category] += 1
            return
        if kind in ('vehicle enters traffic', 'vehicle leaves traffic'):
            self.leaves.pop(event.get('vehicle'), None)
            self.enters.pop(event.get('vehicle'), None)
        if kind in ('left link', 'entered link'):
            target = self.leaves if kind == 'left link' else self.enters
            target[event.get('vehicle')] = (event.get('link'), float(event['time']))
            if kind == 'entered link':
                vehicle = event.get('vehicle')
                previous = self.leaves.get(vehicle)
                if previous is not None and previous[1] == float(event['time']) and self._policy_for_link(previous[0], event, verified_transit).get('eligible') == 'true':
                    head_key = self.head_by_vehicle.get(vehicle)
                    if head_key is None or self.heads[head_key]['identity'][-1] != previous[0]:
                        raise ValueError(f'Prioridad nativa invalida: transicion elegible sin cabecera: {dict(event)}')
                    self.awaiting_cross[vehicle] = (previous[0],event['link'],float(event['time']))
            return
        if kind not in ('simz1PriorityPolicy','simz1Priority'):
            return

        def require(condition, reason):
            if not condition:
                raise ValueError(f'Prioridad nativa invalida: {reason}: {dict(event)}')

        key = (event.get('node'), event.get('link'))
        if kind == 'simz1PriorityPolicy':
            require(key not in self.policy, 'politica duplicada o tardia')
            coverage = event.get('policyCoverage')
            require(coverage in (None, 'car-bus-v2'), 'cobertura de politica desconocida')
            if coverage == 'car-bus-v2':
                require(not self.reconstructed_policy_keys, 'emisor moderno con politicas ya reconstruidas')
                self.full_mode_coverage = True
            if self.legacy_bus_context is not None:
                expected = self.legacy_bus_context['expected'].get(key)
                require(expected is not None, 'politica ajena a enlaces viales de la corrida')
                self._matches_policy(event, expected)
            require(event.get('role') in ('street','avenue'), 'clasificacion ausente')
            require(event.get('eligible') != 'true' or (event.get('enabled') == 'true' and event.get('controlled') == 'false'),
                    'cruce elegible deshabilitado o semaforizado')
            self.policy[key] = dict(event)
            self.native_policy_keys.add(key)
            self.policy_by_link[event['link']] = dict(event)
            self.sources[event.get('classificationSource')] += 1
            if event.get('eligible') == 'true':
                self.eligible_nodes.add(event['node'])
            return
        policy = self._policy_for_link(event.get('link'), event, verified_transit)
        require(bool(policy) and policy.get('node') == event.get('node'), 'politica no registrada para nodo/enlace')
        require(policy.get('eligible') == 'true', 'decision fuera de cruce elegible')
        require(event.get('role') == policy.get('role'), 'rol difiere de configuracion efectiva')
        for field in ('classificationSource', 'stopSeconds', 'conflictPolicy'):
            agrees = event.get(field) == policy.get(field)
            if key in self.reconstructed_policy_keys and field == 'stopSeconds':
                try:
                    agrees = math.isfinite(float(event.get(field))) and float(event[field]) == float(policy[field])
                except (TypeError, ValueError):
                    agrees = False
            require(agrees, f'{field} difiere de politica')
        if key in self.reconstructed_policy_keys:
            try:
                max_yield = float(event.get('maxYieldSeconds'))
            except (TypeError, ValueError):
                max_yield = math.nan
            require(math.isfinite(max_yield) and max_yield == float(policy['maxYieldSeconds']), 'maxYieldSeconds difiere de entradas verificadas')
        now, head, ready, stop = (float(event[k]) for k in ('time','headTime','readyTime','stopSeconds'))
        require(all(math.isfinite(v) for v in (now,head,ready,stop)) and now >= head and stop >= 0, 'reloj invalido')
        control = event.get('control', 'stop' if event['role'] == 'street' else 'free')
        require(control in ('stop', 'yield', 'free'), 'control desconocido')
        require(event['role'] != 'avenue' or control == 'free', 'Alto aplicado a avenida prioritaria')
        if 'control' in policy:
            require(control == policy['control'], 'control difiere de politica')
        expected_stop = (max(5., stop) if 'appliedStopSeconds' in event else stop) if control == 'stop' else 0
        applied = float(event.get('appliedStopSeconds', expected_stop))
        require(math.isfinite(applied) and applied == expected_stop, 'parada aplicada incorrecta')
        if 'appliedStopSeconds' in policy:
            require(applied == float(policy['appliedStopSeconds']), 'parada aplicada difiere de politica')
        require(abs(ready-head-applied) < 1e-7, 'readyTime incorrecto')
        head_key = (event['node'], event['lane'])
        identity = tuple(event[k] for k in ('vehicle','person','visit','headTime','readyTime','link'))
        action, reason = event['action'], event['reason']
        require(action in ('HEAD','GO','WAIT','CROSS'), 'accion desconocida')
        self.nodes.add(event['node'])
        self.actions[action] += 1
        self.reasons[reason] += 1
        if action == 'HEAD':
            require(head_key not in self.heads, 'cabecera reiniciada sin cruce')
            require(now == head, 'HEAD tardio')
            self.heads[head_key] = dict(identity=identity, permission=None, passage_permission=None)
            require(event['vehicle'] not in self.head_by_vehicle, 'vehiculo en dos cabeceras')
            self.head_by_vehicle[event['vehicle']] = head_key
            return
        state = self.heads.get(head_key)
        require(state is not None and state['identity'] == identity, 'cronometro o visita cambiados')
        if reason == 'priority_stop':
            require(action == 'WAIT' and control == 'stop' and now < ready, 'parada artificial despues de readyTime')
        passage_token = None
        if action in ('GO','CROSS'):
            passage_token = self.passage_credit.permission(event, applied,
                state['passage_permission'] if action == 'CROSS' else None)
            require(now >= ready or passage_token is not None and now-head+passage_token[4]+1e-7 >= applied,
                    'parada minima omitida')
        if action == 'GO':
            state['permission'] = (now,event['nextLink'])
            state['passage_permission'] = passage_token
        if action == 'CROSS':
            require(state['permission'] == (now,event['nextLink']), 'cruce sin permiso de este paso')
            require(self.leaves.get(event['vehicle']) == (event['link'],now), 'cruce sin LinkLeaveEvent correspondiente')
            require(self.enters.get(event['vehicle']) == (event['nextLink'],now), 'cruce sin LinkEnterEvent correspondiente')
            require(self.awaiting_cross.pop(event['vehicle'], None) == (event['link'],event['nextLink'],now), 'cruce duplicado o sin transicion elegible')
            self.passage_credit.crossed(passage_token)
            self.crossings += 1
            self.forced_crossings += reason == 'storage_forced_move'
            waits = self.wait_by_role[event['role']]
            waits['count'] += 1
            waits['total_seconds'] += now-head
            waits['maximum_seconds'] = max(waits['maximum_seconds'], now-head)
            waits['minimum_seconds'] = now-head if waits['minimum_seconds'] is None else min(waits['minimum_seconds'], now-head)
            if len(self.crossing_examples) < 20:
                self.crossing_examples.append(dict(event))
            self.max_wait = max(self.max_wait, now-head)
            if event['role'] == 'street':
                self.street_crossings += 1
                self.min_street_wait = now-head if self.min_street_wait is None else min(self.min_street_wait,now-head)
            del self.heads[head_key]
            del self.head_by_vehicle[event['vehicle']]

    def summary(self):
        if self.awaiting_cross:
            raise ValueError(f'Prioridad nativa invalida: transiciones ejecutadas sin CROSS: {self.awaiting_cross}')
        return dict(status='validated' if self.policy else 'not_instrumented',
                    policy_links=len(self.policy), eligible_nodes=len(self.eligible_nodes),
                    native_policy_links=len(self.native_policy_keys),
                    reconstructed_bus_policy_links=len(self.reconstructed_policy_keys),
                    policy_coverage='car-bus-v2' if self.full_mode_coverage else 'legacy_event_stream',
                    policy_reconstruction=(self.legacy_bus_context['evidence'] if self.reconstructed_policy_keys else None),
                    observed_nodes=len(self.nodes), classification_sources=dict(self.sources),
                    actions=dict(self.actions), decision_reasons=dict(self.reasons),
                    native_decision_reasons=dict(self.native_reasons), native_wait_causes=dict(self.wait_causes),
                    native_wait_causes_basis='derived_from_raw_reason;historical_WAIT_or_ABORT;version2_WAIT_only',
                    executed_crossings=self.crossings, street_crossings=self.street_crossings,
                    forced_priority_crossings=self.forced_crossings,
                    passage_stop_credit=self.passage_credit.summary(),
                    head_to_cross_by_role={role: dict(values, mean_seconds=values['total_seconds']/values['count'] if values['count'] else None)
                                           for role, values in self.wait_by_role.items()},
                    pending_heads_at_cut=len(self.heads), minimum_street_head_to_cross_seconds=self.min_street_wait,
                    maximum_head_to_cross_seconds=self.max_wait,
                    note='WAIT counts are attempts, not seconds; CROSS requires native LinkLeave/LinkEnter at the same time; '
                         'pending heads are not assigned an artificial crossing')


def export_selected(selection, destination):
    """Export the effective link classification and evidence for the selected run."""
    from simz1_run import xml_elements, atomic_json, parameters, population, checked_path
    from simz1_transit_events import verified_transit_contract, TransitEventAudit
    from simz1_priority_context import build_bus_context
    directory = selection['directory']
    manifest = selection['manifest']
    requested = parameters(directory/'config-simz1.xml')
    effective = parameters(directory/'output/output_config.xml')
    ids, _ = population(checked_path(directory, manifest['inputs']['plans']))
    links = {e.get('id'): (e.get('from'), e.get('to'), frozenset(e.get('modes', 'car').split(',')))
             for e in xml_elements(selection['network'], 'link', 'network')}
    contract = verified_transit_contract(directory, manifest, requested, checked_path, ids, links)
    transit = TransitEventAudit(contract, ids)
    audit = PriorityAudit(legacy_bus_context=build_bus_context(directory, manifest, effective, contract))
    for event in xml_elements(selection['events'], 'event', 'events'):
        is_transit = transit.consume(event)
        audit.consume(event.attrib, verified_transit=is_transit)
    names = {e.get('id'): e.findtext("attributes/attribute[@name='osm:name']", default='')
             for e in xml_elements(selection['network'], 'link', 'network')}
    catalogue = [dict(row, osm_name=names.get(row['link'], ''),
                      audit_policy_source='verified_run_inputs' if key in audit.reconstructed_policy_keys else 'native_event')
                 for key, row in sorted(audit.policy.items())]
    atomic_json(destination, dict(run_id=selection['manifest']['run_id'], iteration=selection['iteration'],
        configuration=selection['manifest'].get('effective_configuration_validation',{}).get('unsignalized_priority'),
        observed=audit.summary(), classification_table=catalogue, crossing_examples=audit.crossing_examples,
        sources={key:selection['manifest']['results'][str(selection['iteration'])][key] for key in ('network','events')}))
    return audit.summary()
