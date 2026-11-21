"""Persisted synthetic offsets; never another controller clock."""
import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET


def stable_offset(system_id, seed, cycle):
    if type(seed) is not int or not -(2**63) <= seed < 2**63:
        raise ValueError('La semilla de offsets debe ser un entero de 64 bits')
    if type(cycle) is not int or cycle <= 0:
        raise ValueError('El ciclo debe ser un entero positivo')
    digest = hashlib.sha256(f'SimZ1-offset-v1:{seed}:{system_id}'.encode('utf-8')).digest()
    return int.from_bytes(digest, 'big') % cycle


def offset_policy(path, policy='preserve', seed=None, *, write=False):
    if policy not in ('preserve', 'zero', 'hash'):
        raise ValueError('Politica de offsets: preserve, zero o hash')
    if seed is not None and policy != 'hash':
        raise ValueError('--signal-offset-seed requiere --signal-offset-policy hash')
    tree = ET.parse(path)
    root = tree.getroot()
    ns = root.tag.split('}')[0]+'}' if '}' in root.tag else ''
    changes = []
    seen = set()
    for system in root.findall(ns+'signalSystem'):
        sid = system.get('refId')
        if not sid or sid in seen:
            raise ValueError('Sistema semaforico ausente o duplicado')
        seen.add(sid)
        plans = system.findall('.//'+ns+'signalPlan')
        if len(plans) != 1:
            raise ValueError(f'SimZ1 requiere un plan persistente por sistema: {sid}')
        for plan in plans:
            cycle_element, offset_element = plan.find(ns+'cycleTime'), plan.find(ns+'offset')
            if cycle_element is None or offset_element is None:
                raise ValueError(f'Falta cycleTime/offset en {sid}')
            cycle, before = int(cycle_element.get('sec')), int(offset_element.get('sec'))
            if cycle <= 0 or not 0 <= before < cycle:
                raise ValueError(f'Offset fuera de [0,cycle) en {sid}: {before}/{cycle}')
            after = before if policy == 'preserve' else 0 if policy == 'zero' else stable_offset(sid, seed, cycle)
            offset_element.set('sec', str(after))
            changes.append(dict(system_id=sid, plan_id=plan.get('id'), cycle=cycle, before=before, after=after))
    if not changes:
        raise ValueError('No hay planes semaforicos para aplicar offsets')
    if write and policy != 'preserve':
        if ns:
            ET.register_namespace('', ns[1:-1])
        tree.write(Path(path), encoding='utf-8', xml_declaration=True)
    return dict(policy=policy, seed=seed, algorithm='SHA-256 UTF-8 SimZ1-offset-v1:seed:systemId; unsigned modulo cycle',
                assumption='Synthetic offsets, not field timing or guaranteed green wave', plans=changes)
