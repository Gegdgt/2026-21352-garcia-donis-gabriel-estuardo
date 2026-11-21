"""Explicit, source-bound local synthetic timing variant; never field timing."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2'
POLICY = BASE/'l18-local-v1.json'


def inspect_config(config):
    config = Path(config).resolve()
    if config.name != 'config-l18-local-v1.xml': return None
    if config != (BASE/'config-l18-local-v1.xml').resolve():
        raise ValueError('LOCAL_SIGNAL_VARIANT: source config must be the versioned variant')
    data = json.loads(POLICY.read_text(encoding='utf-8'))
    if data['policy'] != 'l18-local-synthetic-offsets-v1' or data['observed_timing'] is not False:
        raise ValueError('LOCAL_SIGNAL_VARIANT: missing synthetic identity')
    for name, expected in (data['source_hashes'] | data['variant_hashes']).items():
        if hashlib.sha256((BASE/name).read_bytes()).hexdigest() != expected:
            raise ValueError('LOCAL_SIGNAL_VARIANT: changed pinned input '+name)
    old = (BASE/data['source_control']).read_bytes().decode()
    changed, count = re.subn(r'(<signalSystem refId="333531372">.*?<offset sec=")0("/>)',r'\g<1>60\2',old,flags=re.S)
    if count != 1 or changed.encode() != (BASE/data['variant_control']).read_bytes():
        raise ValueError('LOCAL_SIGNAL_VARIANT: changes exceed the reviewed single offset')
    original = (BASE/data['source_config']).read_bytes()
    if original.replace(b'value="signalControl.xml"',b'value="signalControl-l18-local-v1.xml"') != config.read_bytes():
        raise ValueError('LOCAL_SIGNAL_VARIANT: unrelated source configuration changed')
    return dict(policy=data['policy'],observed_timing=False,policy_sha256=hashlib.sha256(POLICY.read_bytes()).hexdigest(),
        original_offsets={'579787032':0,'333531372':0},effective_offsets=data['selected_offsets'],
        source_control_sha256=data['source_hashes'][data['source_control']],
        effective_control_sha256=data['variant_hashes'][data['variant_control']],
        limitations=data['limitations'])
