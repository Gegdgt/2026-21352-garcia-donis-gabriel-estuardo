"""Choose browser probes from published native trips/SQLite, never synthetic traffic."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'python'))
from simz1_paged_replay import unpacked
from simz1_sqlite_source import checked_source, readonly_database, identity


def samples(run):
    _, source, database = checked_source(run/'webgl-source/sqlite-source')
    with gzip.open(run/'output/ITERS/it.0/0.simz1-trips.csv.gz', 'rt', encoding='utf-8') as stream:
        trips = list(csv.DictReader(stream))
    private = {kind: next(t['vehicle_id'] for t in trips if t['profile'] == profile)
               for kind, profile in [('car', 'Normal'), ('moto', 'Motociclista')]}
    result = dict(identity(source))
    manifest = json.loads((run/'run-manifest.json').read_text(encoding='utf-8'))
    result['private_persons'] = manifest['counts']['planned_persons']
    freight = manifest.get('freight_transport', {})
    if freight.get('enabled'):
        private['freight'] = freight['fleet_vehicle_ids'][0]
        result['freight_configured'] = freight['vehicles_configured']
    with readonly_database(database, identity(source)) as connection:
        journeys = [(key, json.loads(raw)) for key, raw in connection.execute('SELECT key,metadata FROM journeys')]
        for kind, vehicle in private.items():
            key, trip = next((key, t) for key, t in journeys if t.get('Person_ID') == vehicle)
            rows = [unpacked(r[0]) for r in connection.execute('SELECT payload FROM segments WHERE journey=? ORDER BY id', (key,))]
            row = next(r for r in rows if r['Distance_m'] > 10 and r['timestamps'][1]-r['timestamps'][0] >= 2)
            result[kind] = dict(vehicle=vehicle, key=key, time=sum(row['timestamps'])/2,
                                link=row['Link_ID'], interval=row['timestamps'], trip_id=trip['Trip_ID'])
        key, trip = next((key, t) for key, t in journeys if
            t.get('Transit', {}).get('vehicle_id') == 'ptbus_transmetro_L12_001' and
            t['Transit']['departure_id'].endswith('_d0001'))
        stop = next(s for s in trip['Transit']['activity_intervals'] if
                    s['link_id'] == 'transit_osm_1274975829_0_forward')
        rows = [unpacked(r[0]) for r in connection.execute('SELECT payload FROM segments WHERE journey=? ORDER BY id', (key,))]
        move = next(r for r in rows if r['timestamps'][0] >= stop['end'] and r['Distance_m'] > 1 and
                    r['timestamps'][1] > r['timestamps'][0])
        result['bus'] = dict(vehicle=trip['Transit']['vehicle_id'], key=key,
            time=(stop['start']+stop['end'])/2, move_time=sum(move['timestamps'])/2,
            arrival=trip['Arrival'], departure=trip['Departure'], driver=trip['Driver_ID'],
            trip_id=trip['Trip_ID'], stop=stop, moving_interval=move['timestamps'], moving_link=move['Link_ID'])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = samples(args.run_dir.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
