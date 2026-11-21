"""Read-only launch preflight for the existing balanced OD generator. No QSim."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import xml.etree.ElementTree as ET

from simz1_balanced_od import VARIANT, ORIGIN_POLICY, input_options, load_model, digest, evidence, ACCESS_SCHEMA
from simz1_od_policy import percentage_document


def identity(boundary, access, mix_file):
    """Pin reviewed files and the exact synthetic hypothesis, independently of N."""
    if not mix_file or not Path(mix_file).is_file():
        raise ValueError('Falta -OdMixFile: JSON explicito de cuatro porcentajes; no existe mezcla por defecto')
    raw = Path(mix_file).read_text(encoding='utf-8-sig')
    input_options(boundary, access, raw)
    document = json.loads(Path(access).read_text(encoding='utf-8-sig'))
    if document.get('schema_version') != ACCESS_SCHEMA:
        raise ValueError('Catalogo de accesos ausente/incompatible: '+str(access))
    for label, review in (('Catalogo de accesos',document.get('review')), ('Perimetro',document.get('perimeter'))):
        evidence(review,label)
        if any(marker in json.dumps(review).lower() for marker in ('unit test','unit-test','synthetic-test','fixture','example','pendiente')):
            raise ValueError(label+': datos de ejemplo/prueba no habilitan una corrida real')
    for path in (boundary, access):
        if 'fixtures' in Path(path).parts or '.example.' in Path(path).name:
            raise ValueError('Una fixture/plantilla no es insumo de lanzamiento real: '+str(path))
    hypothesis = dict(version=VARIANT, empirical_calibration=False, percentages=percentage_document(raw))
    hypothesis_hash = hashlib.sha256(json.dumps(hypothesis, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(od_mode=VARIANT, origin_policy=ORIGIN_POLICY, boundary_sha256=digest(boundary),
                access_sha256=digest(access), hypothesis_sha256=hypothesis_hash)


def manifest_identity(manifest):
    spatial = manifest.get('spatial_demand') or {}
    if spatial.get('mode') != VARIANT:
        return dict(od_mode=spatial.get('mode', 'network'), origin_policy=manifest.get('origin_policy'))
    return dict(od_mode=VARIANT, origin_policy=manifest['origin_policy'],
                boundary_sha256=manifest['inputs']['zone_boundary']['sha256'],
                access_sha256=manifest['balanced_od']['access_catalog']['sha256'],
                hypothesis_sha256=spatial['hypothesis']['sha256'])


def check(config, catalog, total, boundary, access, mix_file, seed=20261023, *,
          transit_service=None, transit_service_date='2026-10-23', accept_transit_route_assumptions=True,
          experiment_spec=None, experiment_scenario=None, iterations=1):
    """Consume the SAME scheduled OD iterator without saving population/run files.

    This checks every selected origin/hour budget; it is not a QSim throughput
    prediction. No rescheduling, smaller N, alternate mix or network fallback.
    """
    from simz1_run import parameters
    from simz1_balanced_od_audit import check_config
    from simz1_agent_types import load_catalog
    from simz1_demand_composition import split
    from simz1_temporal import temporal_spec
    from simz1_od_policy import validate_osm_turns
    from simz1_lane_validation import audit_configuration
    from simz1_gateway_od import normalize_shares
    from generate_montecarlo_z1 import gateway_people, SCENARIO
    pinned = identity(boundary, access, mix_file)
    from simz1_scale_contract import require_scale
    require_scale(total, seed, iterations, experiment_spec, experiment_scenario)
    from simz1_scale_contract import experiment
    selected=experiment(experiment_spec,experiment_scenario) if experiment_spec else None
    config = Path(config).resolve(strict=True)
    from simz1_local_signal_variant import inspect_config
    signal_variant = inspect_config(config)
    values = parameters(config)
    # Match only the explicit launch overrides on the isolated copy.
    overrides = {'qsim.numberOfThreads':'1', 'controler.firstIteration':'0',
        'controler.lastIteration':str(iterations-1), 'global.randomSeed':'20261023',
        'simz1Admission.wholeVehicleReservation':'true', 'simz1Admission.storagePolicy':'strict-receiver-v1'}
    effective = dict(values, **overrides)
    from simz1_scale_contract import origin_policy_for_selection, LEGACY_ORIGIN_POLICY
    origin_admission = origin_policy_for_selection(selected)
    if values.get('simz1Admission.originPolicy', LEGACY_ORIGIN_POLICY) not in (LEGACY_ORIGIN_POLICY, origin_admission):
        raise ValueError('Source origin admission policy conflicts with selected experiment')
    overrides['simz1Admission.originPolicy'] = origin_admission
    effective['simz1Admission.originPolicy'] = origin_admission
    check_config(effective,iterations=iterations,origin_admission_policy=origin_admission)
    if selected:
        end=selected.get('native_qsim_end_seconds',selected['observation_end_seconds'])
        overrides.update({'qsim.endTime':str(end),'travelTimeCalculator.maxTime':str(selected['observation_end_seconds'])})
        if selected.get('observation_policy'):
            overrides.update({'simz1Observation.policy':selected['observation_policy'],'qsim.timeStepSize':'1'})
        if not signal_variant or signal_variant['policy']!=selected['signal_variant']:
            raise ValueError('Experiment must retain the selected L18 signal variant')
    if values.get('signalsystems.useSignalsystems') != 'true':
        raise ValueError('Se requieren los semaforos de la fuente sin cambiar ciclos/offsets')
    for key in ('qsim.flowCapacityFactor','qsim.storageCapacityFactor'):
        if float(values.get(key,'1.0')) != 1.:
            raise ValueError('No se altera capacidad fisica: '+key)
    source = load_catalog(catalog)
    if source != load_catalog(SCENARIO/'agent-types-balanced-v1.json'):
        raise ValueError('El catalogo debe conservar exactamente la composicion, dimensiones y horarios balanceados')
    network = (config.parent/values['network.inputNetworkFile']).resolve(strict=True)
    lanes = (config.parent/values['network.laneDefinitionsFile']).resolve(strict=True)
    osm = config.parent/'map.osm'
    # Same structural gate as generar(), before model construction or demand
    # iteration. No population or run directory is needed for this audit.
    lane_audit = audit_configuration(config, osm_path=osm)
    from simz1_effective_access import prepare as prepare_effective_access
    from simz1_weekday_transit import DEFAULT
    from simz1_balanced_od_audit import check_effective_network
    composition = split(total, source)
    private = composition['private_vehicles']
    # Temporary service inputs are discarded; no population or run is published.
    # This is the same attach/review function used before generar's OD iterator.
    with tempfile.TemporaryDirectory(prefix='simz1-effective-preflight-') as temporary:
        root = ET.parse(config).getroot()
        # The derived service and temporal proof must consume the same actual
        # launch overrides, not just the dictionary checked above.
        for key, value in overrides.items():
            module, name = key.split('.', 1)
            group = root.find(f"module[@name='{module}']")
            if group is None: group = ET.SubElement(root, 'module', name=module)
            parameter = group.find(f"param[@name='{name}']")
            if parameter is None: parameter = ET.SubElement(group, 'param', name=name)
            parameter.set('value', value)
        model, access_review, transit, effective_audit = prepare_effective_access(
            root, config.parent, Path(temporary)/'transit-weekday', private,
            transit_service or DEFAULT, transit_service_date, accept_transit_route_assumptions,
            boundary, osm, access)
        raw = Path(mix_file).read_text(encoding='utf-8-sig')
        shares = normalize_shares(input_options(boundary, access, raw))
        temporal=temporal_spec(None,None,1,selected['observation_end_seconds']-86400 if selected else 0,'montecarlo')
        if selected:temporal['observation_policy']=selected.get('observation_policy',selected['freight_completion_policy'])
        people, report, _ = gateway_people(model, seed,
            dict(mode='montecarlo', kind='fixed', minimum=private, maximum=private), shares,
            temporal, catalog=source,
            flow_factor=float(values.get('qsim.flowCapacityFactor', '1.0')),
            balanced_composition=composition, balanced_percentages=raw)
        count = sum(1 for _ in people)
        if count != private:
            raise ValueError('Preflight OD no conserva el numero de particulares')
        check_effective_network(model, Path(temporary)/'transit-weekday/network.xml',
                                Path(temporary)/'transit-weekday/lanes.xml')
        return dict(status='preflight_pass', identity=pinned, composition=composition,
            experiment=selected,iterations=iterations,temporal_demand=temporal,
            signal_variant=signal_variant,
            report=report['balanced_od_audit'], hypothesis=report['spatial_demand']['hypothesis'],
            restriction_preflight=access_review['restriction_preflight'],
            source_lane_configuration_validation=lane_audit, lane_configuration_validation=effective_audit,
            effective_access_review=access_review, public_transport=transit,
            population_files_written=0, simulation_started=False,
            note='Muestreo determinista completo en memoria; no acredita flujo, entrada ni llegada QSim')



def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--boundary', type=Path, required=True)
    p.add_argument('--access', type=Path, required=True)
    p.add_argument('--mix-file', type=Path, required=True)
    a = p.parse_args()
    try:
        print(json.dumps(identity(a.boundary, a.access, a.mix_file), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print('Balanced launch blocked: '+str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
