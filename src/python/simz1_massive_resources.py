"""Read-only memory preflight using the launcher's actual JVM heap policy."""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

from ejecutar_simz1 import heap_para_ram, memoria_fisica_bytes

GIB = 1024**3


def check():
    class MemoryStatus(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
            (name, ctypes.c_ulonglong) for name in
            ('total_phys', 'available_phys', 'total_commit', 'available_commit',
             'total_virtual', 'available_virtual', 'available_extended')]
    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise OSError('GlobalMemoryStatusEx failed; memory budget cannot be checked')
    installed = memoria_fisica_bytes()
    heap = heap_para_ram(installed)
    # Planning reserves, not measured future maxima. JVM native memory, Maven,
    # OS and other apps remain outside the Java heap.
    process_commit = (heap + 2 + 2) * GIB
    physical_budget = process_commit + 4 * GIB
    command = "$c=Get-CimInstance Win32_ComputerSystem; $p=@(Get-CimInstance Win32_PageFileUsage | Select-Object Name,AllocatedBaseSize); @{automatic=$c.AutomaticManagedPagefile;files=$p} | ConvertTo-Json -Compress -Depth 4"
    pagefiles = json.loads(subprocess.run(
        ['powershell.exe', '-NoProfile', '-Command', command], check=True,
        capture_output=True, text=True).stdout)
    project_volume = Path(__file__).resolve().anchor
    disk = shutil.disk_usage(project_volume)
    allocated = sum(p['AllocatedBaseSize']*1024**2 for p in pagefiles['files']
                    if Path(p['Name']).anchor.lower() == project_volume.lower())
    deficit = max(0, process_commit-status.available_commit)
    # System-managed growth is existing OS behavior, not a settings change.
    # Reserve the entire missing commit on this same volume in the disk budget.
    maximum_pagefile = min(max(3*status.total_phys, 4*GIB), disk.total//8)
    growth_possible = (pagefiles['automatic'] is True and allocated > 0 and
                       maximum_pagefile-allocated >= deficit and disk.free >= deficit+4*GIB)
    reasons = []
    if status.total_phys < physical_budget:
        reasons.append('physical RAM below JVM + Maven + native + OS planning budget')
    if deficit and not growth_possible:
        reasons.append('available system commit below JVM + Maven + native planning budget')
    return dict(schema_version=1, checked_utc=datetime.now(timezone.utc).isoformat(),
                status='blocked' if reasons else 'planning_budget_pass', reasons=reasons,
                installed_bytes=installed, physical_bytes=status.total_phys,
                available_physical_bytes=status.available_phys,
                available_commit_bytes=status.available_commit, qsim_heap_gib=heap,
                pagefiles=pagefiles, automatic_growth_planned=bool(deficit and growth_possible),
                pagefile_growth_reserve_gib=math.ceil(deficit/GIB) if growth_possible else 0,
                pagefile_documentation='https://learn.microsoft.com/en-us/troubleshoot/windows-client/performance/how-to-determine-the-appropriate-page-file-size-for-64-bit-versions-of-windows',
                maven_heap_gib=2, native_reserve_gib=2, os_reserve_gib=4,
                paging_possible=status.available_phys < process_commit,
                note='Planning check only; automatic pagefile growth can be delayed. No OS settings changed and no claim of measured peak RAM or runtime scalability.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = check()
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))
    return 1 if result['status'] == 'blocked' else 0


if __name__ == '__main__':
    sys.exit(main())
