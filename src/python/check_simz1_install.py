"""Read-only installation checks; no downloads, generators, Maven or servers."""
import sys
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
SOURCE_HASH = 'f18296d0479d0efd095a5b6534f9685928fbd2be9d90705b9200864b3a697a0a'


def command_version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=15)
        return result.returncode == 0, (result.stdout + result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=PROJECT, help='Tree to inspect')
    parser.add_argument('--git', action='store_true', help='Also fail on required files absent from Git index')
    parser.add_argument('--tests', action='store_true', help='Require pytest and Node >=22')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    failures = []

    def report(ok, name, detail=''):
        print(f"{'OK' if ok else 'FALTA/ERROR'} {name}" + (f': {detail}' if detail else ''))
        if not ok:
            failures.append(name)

    manifest = root / 'scripts/installation/simz1-required-files.json'
    try:
        required = json.loads(manifest.read_text(encoding='utf-8'))['required_files']
    except (OSError, ValueError, KeyError) as exc:
        report(False, str(manifest), str(exc))
        return 1
    missing = [name for name in required if not (root / name).is_file()]
    report(not missing, 'Archivos del flujo SimZ1', f'{len(required)} requeridos')
    for name in missing:
        print(f'  AUSENTE {name}')
    if args.git:
        try:
            tracked = set(subprocess.check_output(
                ['git', '-C', str(root), 'ls-files', '-z'], text=True).split('\0'))
            unpublished = sorted(set(required) - tracked)
            report(not unpublished, 'Entrega Git', f'{len(unpublished)} archivos requeridos sin seguimiento')
            for name in unpublished:
                print(f'  NO VERSIONADO {name}')
            changed = subprocess.check_output(
                ['git', '-C', str(root), 'diff', 'HEAD', '--name-only', '--', *required], text=True).splitlines()
            if changed:
                print('AVISO: cambios requeridos presentes solo en el arbol/indice; un clon de HEAD no los incluye:')
                for name in changed:
                    print(f'  MODIFICADO {name}')
                failures.append('Cambios pendientes de publicacion')
        except (OSError, subprocess.CalledProcessError) as exc:
            report(False, 'Git', str(exc))

    report(sys.version_info >= (3, 10), 'Python >=3.10', sys.version.split()[0])
    for distribution, module in [('numpy', 'numpy'), ('pandas', 'pandas'), ('matplotlib', 'matplotlib'),
                                 ('pyproj', 'pyproj'), ('pydeck', 'pydeck'), ('Pillow', 'PIL'),
                                 ('openpyxl', 'openpyxl')] + ([('pytest', 'pytest')] if args.tests else []):
        try:
            version = importlib.metadata.version(distribution)
            report(importlib.util.find_spec(module) is not None, distribution, version)
        except (importlib.metadata.PackageNotFoundError, ValueError):
            report(False, distribution, 'Instalar requirements-test.txt' if args.tests else 'Instalar requirements.txt')

    java_home = os.environ.get('JAVA_HOME')
    report(bool(java_home), 'JAVA_HOME', java_home or 'Definir la carpeta de un JDK >=17 (bytecode objetivo 17)')
    for executable in ('java', 'javac'):
        binary = str(Path(java_home) / 'bin' / (executable + ('.exe' if os.name == 'nt' else ''))) if java_home else executable
        ok, version = command_version([binary, '-version'])
        found = re.search(r'(?:version\s+"|javac\s+)(\d+)', version)
        report(ok and found is not None and int(found.group(1)) >= 17, executable + ' >=17; target 17', version)
    node = shutil.which('node')
    ok, version = command_version([node, '--version']) if node else (False, 'No instalado')
    major = re.match(r'v(\d+)', version)
    node_ok = ok and major is not None and int(major[1]) >= 22
    if args.tests:
        report(node_ok, 'Node >=22', version)
    else:
        print(f'INFO Node (opcional para servir WebGL): {version}')
    print(f'INFO Maven instalado: {shutil.which("mvn.cmd" if os.name == "nt" else "mvn") or "no encontrado; usar wrapper"}')
    properties = root / '.mvn/wrapper/maven-wrapper.properties'
    try:
        values = dict(line.split('=', 1) for line in properties.read_text().splitlines() if '=' in line and not line.startswith('#'))
        report('@@' not in values.get('wrapperUrl', '@@') and values.get('wrapperSha256Sum') is not None,
               'Bootstrap wrapper fijado', values.get('wrapperUrl', 'ausente'))
        jar = root / '.mvn/wrapper/maven-wrapper.jar'
        if jar.exists():
            report(hashlib.sha256(jar.read_bytes()).hexdigest() == values.get('wrapperSha256Sum'), 'SHA256 wrapper local')
        else:
            print('INFO wrapper.jar se descarga al ejecutar mvnw.cmd -version; no es insumo privado.')
    except (OSError, ValueError) as exc:
        report(False, 'Wrapper', str(exc))

    scenario = root / 'scenarios/zona1'
    try:
        raw = (scenario / 'map.osm').read_bytes()
        actual = hashlib.sha256(raw.replace(b'\r\n', b'\n')).hexdigest()
        report(actual == SOURCE_HASH, 'OSM SHA256 normalizado LF', actual)
        osm = ET.fromstring(raw)
        report(osm.tag == 'osm' and osm.get('version') == '0.6', 'OSM XML 0.6')
        config = ET.parse(scenario / 'config-simz1.xml')
        inputs = {('network', 'inputNetworkFile'), ('network', 'laneDefinitionsFile'),
                  ('plans', 'inputPlansFile'), ('facilities', 'inputFacilitiesFile'),
                  ('vehicles', 'vehiclesFile'), ('signalsystems', 'signalsystems'),
                  ('signalsystems', 'signalgroups'), ('signalsystems', 'signalcontrol')}
        for module, key in sorted(inputs):
            item = config.find(f"./module[@name='{module}']/param[@name='{key}']")
            value = item.get('value') if item is not None else None
            report(bool(value) and (scenario / value).is_file(), f'{module}.{key}', value or 'Sin referencia')
        for name in ('network.xml', 'lanes.xml', 'vehicle-types.xml', 'signalSystems.xml', 'signalGroups.xml', 'signalControl.xml'):
            ET.parse(scenario / name)
        report(True, 'XML maestros bien formados')
    except (OSError, ValueError, ET.ParseError) as exc:
        report(False, 'Insumos del escenario', str(exc))
    print('INFO CDN deck.gl 9.1.14 y WebGL: comprobar en el navegador; este diagnostico no usa red.')
    print('INFO No valida rutas ni ejecuta QSim. pip check y la compilacion son pasos separados.')
    print(f'Resultado: {len(failures)} comprobaciones pendientes.')
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
