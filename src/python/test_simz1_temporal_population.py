"""Read back the actual repaired private route with its persisted vehicle speed."""
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from simz1_effective_access import review
from simz1_run import checked_path, parameters
from simz1_temporal_passage import TemporalPassage, IMPOSSIBLE, COMPATIBLE
from simz1_population import write_population, verify_population
from test_simz1_temporal_passage import HISTORICAL, EVIDENCE, ROOT


def main():
    out=Path(tempfile.mkdtemp(prefix='temporal-population-',dir=ROOT/'runtime'));print('Evidence:',out,flush=True)
    manifest=json.loads((HISTORICAL/'run-manifest.json').read_text());contract=manifest['balanced_od'];config=parameters(HISTORICAL/'config-simz1.xml')
    model,rebuilt=review(checked_path(HISTORICAL,contract['source_network']),checked_path(HISTORICAL,contract['source_lanes']),
        checked_path(HISTORICAL,manifest['inputs']['network']),HISTORICAL/config['network.laneDefinitionsFile'],
        checked_path(HISTORICAL,manifest['inputs']['zone_boundary']),checked_path(HISTORICAL,manifest['inputs']['od_source_osm']),
        checked_path(HISTORICAL,contract['access_catalog']),(HISTORICAL/config['transit.transitScheduleFile']).parent,config['global.coordinateSystem'])
    recorded=json.loads(checked_path(HISTORICAL,contract['effective_access_review']).read_text())
    assert all(recorded.get(k)==v for k,v in rebuilt.items())
    model.temporal=TemporalPassage(HISTORICAL/'config-simz1.xml',HISTORICAL)
    focal=json.loads((EVIDENCE/'signal_fixture_input.json').read_text());ident=focal['vehicle'];attrs=focal['attributes'];trip=json.loads(attrs['simz1Trips'])[0]
    record=next(iter(json.loads(attrs['simz1SpatialOD']).values()));origin,dest=record['origin_link'],record['destination_link'];body=record['body_length_m'];speed=float(attrs['simz1MaximumVelocityMps'])
    old=model.route(origin,dest);fixed=model.temporal_route(origin,dest,body,speed)
    assert model.temporal.query(tuple(old),body,speed)[0]==IMPOSSIBLE
    assert model.temporal.query(tuple(fixed),body,speed)[0]==COMPATIBLE and old!=fixed
    updated=dict(record,route_link_ids=fixed);model.validate_metadata(updated,speed)
    person=ET.Element('person',id=ident);attributes=ET.SubElement(person,'attributes')
    for key,value in attrs.items():
        if key=='vehicles':continue # production writer binds the real vehicle.
        if key=='simz1SpatialOD':value=json.dumps({trip['id']:updated})
        ET.SubElement(attributes,'attribute',name=key,**{'class':'java.lang.String'}).text=value
    plan=ET.SubElement(person,'plan',selected='yes')
    ET.SubElement(plan,'activity',type='origin',link=origin,end_time=str(trip['planned_departure']))
    leg=ET.SubElement(plan,'leg',mode='car');legattrs=ET.SubElement(leg,'attributes')
    ET.SubElement(legattrs,'attribute',name='simz1TripId',**{'class':'java.lang.String'}).text=trip['id']
    route=ET.SubElement(leg,'route',type='links',start_link=origin,end_link=dest,vehicleRefId=ident);route.text=' '.join(fixed)
    ET.SubElement(plan,'activity',type='destination',link=dest)
    types=ROOT/'scenarios/zona1/od/balanced-gateway-v1/access-review-v2/vehicle-types.xml'
    write_population(out/'plans.xml',out/'vehicles.xml',[person],types,'one fixed historical OD, repaired route serialization fixture')
    result=verify_population(out/'plans.xml',out/'vehicles.xml',1,model.eligible_links,1,True,spatial_model=model)
    assert result['persons']==1 and result['spatial_metadata_valid']
    # An arbitrary different route must still fail after read-back; no relaxation
    # of the exact route/OD/XML contract is accepted.
    tree=ET.parse(out/'plans.xml');element=tree.find("person/attributes/attribute[@name='simz1SpatialOD']")
    element.text=json.dumps({trip['id']:dict(updated,route_link_ids=old)})
    negative=out/'nominal-impossible.xml';tree.write(negative,encoding='utf-8')
    try:verify_population(negative,out/'vehicles.xml',1,model.eligible_links,1,True,spatial_model=model)
    except ValueError:pass
    else:raise AssertionError('Impossible nominal route silently accepted')
    vehicles=ET.parse(out/'vehicles.xml');ns='{http://www.matsim.org/files/dtd}'
    profile=vehicles.find(ns+"vehicleType[@id='Normal']");profile.remove(profile.find(ns+'maximumVelocity'))
    missing=out/'missing-speed.xml';vehicles.write(missing,encoding='utf-8')
    try:verify_population(out/'plans.xml',missing,1,model.eligible_links,1,True,spatial_model=model)
    except ValueError as exc:assert 'serialized vehicle speed' in str(exc)
    else:raise AssertionError('Missing temporal physical parameter silently assumed')
    (out/'result.json').write_text(json.dumps(dict(status='PASS',old_links=len(old),repaired_links=len(fixed),identity=ident,serialized_speed_mps=speed,scope='one fixed OD; no full-service or massive approval'),indent=2))
    print('PASS repaired private route read-back and negative nominal route',flush=True)


if __name__=='__main__':main()
