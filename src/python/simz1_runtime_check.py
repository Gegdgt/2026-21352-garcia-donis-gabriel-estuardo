"""Check freshly compiled application bytecode and the project classpath. No simulation."""
import argparse
import json
from pathlib import Path
import os
import struct
import sys
import xml.etree.ElementTree as ET
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
TARGET_MAJOR = 61  # Java 17, supported by MATSim 15 / Guice 5.1 embedded ASM 9.2.
REQUIRED_CLASSES = (
    'gt/edu/uvg/sim/zona1/RunZona1Simulation.class',
    'gt/edu/uvg/sim/zona1/SimZ1TransitFleet.class',
    'gt/edu/uvg/sim/zona1/SimZ1TransitFleet$ExactTransitEngine.class',
    'gt/edu/uvg/sim/zona1/SimZ1FailureReport.class',
    'org/matsim/core/mobsim/qsim/pt/SimZ1BoundaryTransitDriver.class',
)
DEPENDENCY_CLASSES = (
    'org/matsim/core/mobsim/qsim/pt/TransitQSimEngine.class',
    'com/google/inject/Guice.class',
    'com/google/common/base/Equivalence$Wrapper.class',
)

def major(path):
    with Path(path).open('rb') as stream:
        header = stream.read(8)
    if len(header) != 8 or header[:4] != b'\xca\xfe\xba\xbe':
        raise ValueError(f'Invalid class header: {path}')
    minor, version = struct.unpack('>HH', header[4:])
    if minor == 65535:
        raise ValueError(f'Preview bytecode not permitted: {path}')
    return version

def verify(root, classpath_file=None):
    root = Path(root).resolve()
    ns = {'p': 'http://maven.apache.org/POM/4.0.0'}
    pom = ET.parse(root/'pom.xml')
    if pom.findtext('./p:properties/p:maven.compiler.release', namespaces=ns) != '17':
        raise ValueError('pom.xml must set maven.compiler.release=17')
    classes = root/'target/classes'
    missing = [name for name in REQUIRED_CLASSES if not (classes/name).is_file()]
    if missing:
        raise ValueError('Missing compiled classes: ' + ', '.join(missing))
    checked = []
    for directory in (classes, root/'target/test-classes'):
        if directory.exists():
            for path in directory.rglob('*.class'):
                version = major(path)
                if version > TARGET_MAJOR:
                    raise ValueError(f'Stale/incompatible Java class major={version}: {path}. Run prepare_simz1_runtime.ps1.')
                checked.append(path)
    resolved = {}
    if classpath_file is not None:
        value = Path(classpath_file).read_text(encoding='utf-8-sig').strip()
        paths = [Path(part) for part in value.split(os.pathsep) if part]
        if not paths or any(not p.is_file() for p in paths):
            raise ValueError('Incomplete dependency classpath: a JAR is absent')
        for path in paths:
            with zipfile.ZipFile(path) as jar:
                names = set(jar.namelist())
                for name in DEPENDENCY_CLASSES:
                    if name in names:
                        if name in resolved:
                            raise ValueError(f'Duplicate dependency class {name}: {resolved[name]} and {path}')
                        resolved[name] = str(path)
        if set(resolved) != set(DEPENDENCY_CLASSES):
            raise ValueError('Runtime dependency missing: ' + ', '.join(set(DEPENDENCY_CLASSES)-set(resolved)))
    return dict(status='runtime_files_checked', target_java=17, class_major=TARGET_MAJOR,
                checked_classes=len(checked), dependency_sources=resolved,
                qsim_executed=False)

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--project', type=Path, default=PROJECT)
    p.add_argument('--classpath-file', type=Path)
    a=p.parse_args(argv)
    try:
        print(json.dumps(verify(a.project,a.classpath_file), indent=2)); return 0
    except (OSError, ValueError, ET.ParseError, zipfile.BadZipFile) as e:
        print('Runtime check failed: '+str(e),file=sys.stderr); return 1
if __name__=='__main__': sys.exit(main())
