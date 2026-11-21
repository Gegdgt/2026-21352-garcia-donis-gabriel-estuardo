"""Audit prepaid STOP seconds against native passage HOLD/ACQUIRE/RELEASE.

An acquisition is not a queue head. This module only supplies a checked credit
to the ordinary HEAD/GO/native-link-transition/CROSS audit.
"""
from collections import Counter
import math


POLICY = 'corridor-length-v1'
SOURCE = 'synchronous_QSim_corridor_ledger'
EPSILON = 1e-7
TIME_FIELDS = ('passageHoldStartTime', 'passageAuthorizedTime', 'passageRequiredStopSeconds')
PATH_FIELDS = ('passageKind', 'passageLinks', 'passageSlots', 'receiptLink',
               'exitLinks', 'exitSlots', 'exitFromLink', 'passageStopLinks', 'passageStopSeconds')


def require(condition, message):
    if not condition:
        raise ValueError('Prioridad nativa invalida: credito de pasaje: ' + message)


def number(event, field):
    try:
        value = float(event[field])
    except (KeyError, TypeError, ValueError):
        value = math.nan
    require(math.isfinite(value) and value >= 0, 'numero invalido ' + field)
    return value


def integer(event, field):
    value = number(event, field)
    require(value.is_integer(), 'entero invalido ' + field)
    return int(value)


def csv(event, field):
    require(field in event and isinstance(event[field], str), 'lista ausente ' + field)
    values = event[field].split(',') if event[field] else []
    require(all(values), 'elemento vacio ' + field)
    return values


class PassagePriorityCredit:
    def __init__(self, policies):
        self.policies = policies
        self.holds, self.active, self.locks = {}, {}, {}
        self.counts = Counter()
        self.spent = set()

    def stops(self, event):
        links, raw_seconds = csv(event, 'passageStopLinks'), csv(event, 'passageStopSeconds')
        require(len(links) == len(raw_seconds) and len(links) == len(set(links)), 'listas de paradas incompatibles')
        seconds = []
        for link, raw in zip(links, raw_seconds):
            policy = self.policies.get(link)
            require(policy is not None and 'control' in policy and 'appliedStopSeconds' in policy,
                    'parada sin politica explicita del enlace ' + link)
            actual = number(dict(value=raw), 'value')
            expected = number(policy, 'appliedStopSeconds') if policy.get('eligible') == 'true' else 0.
            require(abs(actual - expected) <= EPSILON, 'segundos difieren de politica de ' + link)
            seconds.append(actual)
        total = number(event, 'passageRequiredStopSeconds')
        require(abs(sum(seconds) - total) <= EPSILON, 'total de paradas no coincide con politicas')
        return tuple(links), tuple(seconds), total

    def descriptor(self, event):
        kind = event.get('passageKind')
        require(kind in ('downstream_receipt', 'boundary_exit'), 'tipo de pasaje desconocido')
        exiting = kind == 'boundary_exit'
        links = csv(event, 'exitLinks' if exiting else 'passageLinks')
        slots = csv(event, 'exitSlots' if exiting else 'passageSlots')
        require(links and len(links) == len(set(links)) and len(links) == len(slots), 'conectores invalidos')
        require(all(integer(dict(slot=slot), 'slot') >= 0 for slot in slots), 'slot invalido')
        require(bool(event.get('exitFromLink' if exiting else 'receiptLink')), 'extremo de pasaje ausente')
        stop_links, stop_seconds, total = self.stops(event)
        require(stop_links == tuple(links[:-1] if exiting else links), 'credito no cubre exactamente giros de conectores')
        return dict(kind=kind, links=tuple(links), slots=tuple(int(float(slot)) for slot in slots),
                    receipt=None if exiting else event['receiptLink'], exit_from=event.get('exitFromLink') if exiting else None,
                    stop_links=stop_links, stop_seconds=stop_seconds, total=total,
                    hold=number(event, 'passageHoldStartTime'), authorized=number(event, 'passageAuthorizedTime'))

    def consume(self, event):
        kind, vehicle = event.get('type'), event.get('vehicle')
        if kind == 'simz1OccupancyPassageHold':
            require(bool(vehicle) and bool(event.get('link')) and bool(event.get('requestedLink')),
                    'solicitud sin vehiculo/origen/destino')
            require(event.get('source') == 'native_admission_hold' and event.get('positionsObserved') == 'false',
                    'procedencia de espera no nativa')
            now = number(event, 'time'); start = number(event, 'passageHoldStartTime')
            require(now == start, 'HOLD no corresponde al primer intento')
            links, seconds, total = self.stops(event)
            if vehicle in self.holds:
                require(start > self.holds[vehicle]['start'], 'HOLD duplicado o reloj reiniciado')
                self.counts['superseded_unacquired_holds'] += 1
            self.holds[vehicle] = dict(start=start, source=event['link'], requested=event['requestedLink'],
                                      stop_links=links, stop_seconds=seconds, total=total, movement=[])
            self.counts['hold_events'] += 1
            return
        if kind in ('left link', 'entered link', 'vehicle enters traffic', 'vehicle leaves traffic'):
            hold = self.holds.get(vehicle)
            if hold is not None and len(hold['movement']) < 4:
                hold['movement'].append((kind, event.get('link'), number(event, 'time')))
            return
        if kind != 'simz1OccupancyPassage':
            return
        if not any(field in event for field in TIME_FIELDS + ('passageStopLinks', 'passageStopSeconds')):
            # Historical passages supply no STOP credit. Existing ordinary
            # ready/head checks remain mandatory on that event stream.
            self.counts['legacy_passage_events_without_stop_credit'] += 1
            return
        require(event.get('policy') == POLICY and event.get('source') == SOURCE and
                event.get('positionsObserved') == 'false', 'procedencia de reserva no nativa')
        now = number(event, 'time'); ordinal = integer(event, 'reservationOrdinal')
        key = (vehicle, ordinal); corridor = event.get('corridor')
        require(bool(vehicle) and bool(corridor), 'reserva sin identidad')
        data = self.descriptor(event); nodes = csv(event, 'lockedNodes')
        require(nodes and len(nodes) == len(set(nodes)), 'locks ausentes o duplicados')
        require(all(self.policies[link]['node'] in nodes for link in data['stop_links']),
                'giro de conector fuera de locks publicados')
        action = event.get('action')
        if action == 'ACQUIRE':
            require(key not in self.active and not any(k[0] == vehicle for k in self.active), 'adquisicion duplicada')
            require(all(node not in self.locks for node in nodes), 'locks compartidos por reservas activas')
            hold = self.holds.get(vehicle)
            require(hold is not None and hold['start'] == data['hold'] and
                    hold['requested'] == data['links'][0] and hold['stop_links'] == data['stop_links'] and
                    hold['stop_seconds'] == data['stop_seconds'] and hold['total'] == data['total'],
                    'ACQUIRE sin HOLD nativo coincidente')
            require(data['authorized'] == now and now + EPSILON >= data['hold'] + data['total'],
                    'autorizacion antes de pagar todas las paradas')
            movement = hold['movement']
            allowed = [(('left link', hold['source'], now),),
                       (('left link', hold['source'], now), ('entered link', hold['requested'], now))]
            if hold['source'] == hold['requested']:
                allowed.extend([(('vehicle enters traffic', hold['requested'], now),),
                                (('entered link', hold['requested'], now),)])
            require(not movement or tuple(movement) in allowed, 'movimiento durante HOLD antes de autorizacion')
            require(not data['exit_from'] or data['exit_from'] == hold['source'], 'salida difiere del origen detenido')
            self.active[key] = dict(data=data, corridor=corridor, nodes=tuple(nodes))
            for node in nodes:
                self.locks[node] = key
            del self.holds[vehicle]
            self.counts['verified_acquisitions'] += 1
        elif action == 'RELEASE':
            current = self.active.get(key)
            require(current is not None and current == dict(data=data, corridor=corridor, nodes=tuple(nodes)),
                    'RELEASE sin adquisicion coincidente o con credito alterado')
            require(now >= data['authorized'] and all(self.locks.get(node) == key for node in nodes), 'release sin locks activos')
            for node in nodes:
                del self.locks[node]
            del self.active[key]
            self.counts['verified_releases'] += 1
        else:
            require(False, 'accion de pasaje desconocida')

    def permission(self, event, applied, prior_token=None):
        fields_present = any(field in event for field in TIME_FIELDS + ('passageReservationOrdinal', 'passageStopCreditSeconds'))
        if not fields_present:
            require(prior_token is None, 'CROSS omitio credito presente en GO')
            return None
        if event.get('action') == 'CROSS':
            require(prior_token is not None, 'CROSS agrego credito ausente en GO')
        data = self.descriptor(event)
        key = (event['vehicle'], integer(event, 'passageReservationOrdinal'))
        corridor = event.get('passageCorridor')
        link = event['link']; now = number(event, 'time')
        require(link in data['stop_links'], 'credito fuera de los conectores con giro')
        index = data['links'].index(link)
        next_link = data['links'][index + 1] if index + 1 < len(data['links']) else data['receipt']
        require(event.get('nextLink') == next_link, 'permiso para giro ajeno al pasaje')
        credit = number(event, 'passageStopCreditSeconds')
        require(abs(credit - data['stop_seconds'][data['stop_links'].index(link)]) <= EPSILON and
                abs(credit - applied) <= EPSILON, 'credito del enlace difiere de su parada aplicada')
        require(now >= data['authorized'] and now + EPSILON >= data['hold'] + data['total'], 'credito antes de autorizacion')
        token = (key, corridor, tuple(sorted((field, repr(value)) for field, value in data.items())), link, credit)
        if prior_token is not None:
            require(token == prior_token, 'CROSS cambio el credito autorizado en GO')
        else:
            current = self.active.get(key)
            require(current is not None and current['corridor'] == corridor and current['data'] == data and
                    self.locks.get(event['node']) == key, 'GO sin ACQUIRE y lock activos')
            require((key, link) not in self.spent, 'credito reutilizado tras cruzar el conector')
            self.counts['verified_permission_attempts'] += 1
        return token

    def crossed(self, token):
        if token is not None:
            self.spent.add((token[0], token[3]))
            self.counts['passage_crossings'] += 1
            self.counts['prepaid_stop_crossings'] += token[4] > 0

    def summary(self):
        return dict(policy='native_passage_prepaid_stop_v1', counts=dict(self.counts),
                    active_acquisitions=len(self.active), pending_unacquired_holds=len(self.holds),
                    note='Prepaid seconds require native HOLD plus active ACQUIRE at GO; head/ready clocks and native CROSS remain unchanged')
