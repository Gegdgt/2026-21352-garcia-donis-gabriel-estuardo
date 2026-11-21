"""Reserve isolated SimZ1 run directories without consuming the demand RNG."""
from pathlib import Path
import os
import uuid


def check_new_directory(path):
    """Check an explicit destination, including empty folders and dangling links."""
    requested = Path(path).absolute()
    # lexists also sees dangling Windows junctions; exists/is_symlink alone do
    # not, and resolving such an entry would silently select its missing target.
    if os.path.lexists(requested):
        raise ValueError(f'Usar una carpeta nueva para preservar corridas: {requested}')
    resolved = requested.resolve()
    if resolved.exists():
        raise ValueError(f'Usar una carpeta nueva para preservar corridas: {resolved}')
    return resolved


def create_run_directory(explicit=None, *, parent):
    """Atomically claim a new leaf; only automatic UUID collisions are retried.

    A failed/interrupted generation keeps its directory for diagnosis. It is
    never reused. An explicit path is never renamed or accepted if it exists.
    """
    if explicit is not None:
        directory = check_new_directory(explicit)
        try:
            directory.mkdir(parents=True, exist_ok=False)
        except FileExistsError as exc:
            # Another process may have claimed it since the initial check.
            raise ValueError(f'Usar una carpeta nueva para preservar corridas: {directory}') from exc
        return directory

    parent = Path(parent).resolve()
    parent.mkdir(parents=True, exist_ok=True)
    for _ in range(128):
        directory = parent / f'run-{uuid.uuid4().hex}'
        try:
            directory.mkdir(exist_ok=False)
        except FileExistsError:
            continue
        return directory
    raise RuntimeError(f'No se pudo reservar una carpeta unica de corrida en {parent}')
