"""Windows handle operations for an explicitly approved purge.

Importing this module performs no filesystem or process operations. The caller
owns path containment, approval, inventory, activity policy, journaling and
bottom-up deletion order. Deletion is not transactional.
"""
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import hashlib
import os
import re


class SafetyError(OSError):
    """A required native safety check failed."""


_INVALID_HANDLE = ctypes.c_void_p(-1).value
_GENERIC_READ, _DELETE = 0x80000000, 0x00010000
_SHARE_READ, _OPEN_EXISTING = 1, 3
_OPEN_REPARSE, _BACKUP_SEMANTICS = 0x00200000, 0x02000000
_READONLY, _DIRECTORY, _REPARSE, _DEVICE = 1, 0x10, 0x400, 0x40
_EPOCH_100NS = 116444736000000000
_RUNTIME = re.compile(r"(?:javaw?|pythonw?(?:\d+(?:\.\d+)*)?|node)(?:\.exe)?", re.I)


class _FileInformation(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
        ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
        ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
        ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
        ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD),
    ]


class _Disposition(ctypes.Structure):
    # Windows BOOLEAN is one byte; BOOL is a different, four-byte type.
    _fields_ = [("DeleteFile", ctypes.c_ubyte)]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD), ("szExeFile", wintypes.WCHAR * 260),
    ]


def _fail(action):
    code = ctypes.get_last_error()
    raise SafetyError(code, f"{action}: {ctypes.FormatError(code).strip()}")


class _Api:
    def __init__(self):
        if os.name != "nt":
            raise SafetyError("Native purge operations require Windows; no fallback backend")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        H, D, B, P = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL, wintypes.LPVOID
        self.CreateFile = self.bind("CreateFileW", [wintypes.LPCWSTR, D, D, P, D, D, H], H)
        self.Information = self.bind("GetFileInformationByHandle", [H, ctypes.POINTER(_FileInformation)], B)
        self.FileType = self.bind("GetFileType", [H], D)
        self.Seek = self.bind("SetFilePointerEx", [H, ctypes.c_longlong, ctypes.POINTER(ctypes.c_longlong), D], B)
        self.Read = self.bind("ReadFile", [H, P, D, ctypes.POINTER(D), P], B)
        self.Disposition = self.bind("SetFileInformationByHandle", [H, ctypes.c_int, P, D], B)
        self.Close = self.bind("CloseHandle", [H], B)
        self.Snapshot = self.bind("CreateToolhelp32Snapshot", [D, D], H)
        self.First = self.bind("Process32FirstW", [H, ctypes.POINTER(_ProcessEntry)], B)
        self.Next = self.bind("Process32NextW", [H, ctypes.POINTER(_ProcessEntry)], B)
        self.OpenProcess = self.bind("OpenProcess", [D, B, D], H)
        self.Image = self.bind("QueryFullProcessImageNameW", [H, D, wintypes.LPWSTR, ctypes.POINTER(D)], B)

    def bind(self, name, arguments, result):
        function = getattr(self.kernel, name)
        function.argtypes, function.restype = arguments, result
        return function


@dataclass(eq=False)
class _Token:
    owner: object
    handle: int
    path: str
    can_delete: bool
    directory: bool
    closed: bool = False
    delete_pending: bool = False


class WindowsLocks:
    """Retain checked handles; guard handles can never be deleted through this API."""
    def __init__(self):
        self._api = None
        self._tokens = []
        self._closed = False

    def _backend(self):
        if self._closed:
            raise SafetyError("WindowsLocks is already closed")
        if self._api is None:
            self._api = _Api()
        return self._api

    def __enter__(self):
        self._backend()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()
        return False

    def _checked(self, token):
        if not isinstance(token, _Token) or token.owner is not self or token.closed:
            raise SafetyError("Unknown, foreign or closed native handle")
        self._backend()
        return token

    def open(self, path, *, delete=False, directory=False):
        api = self._backend()
        name = os.fspath(path)
        if not isinstance(name, str) or "\0" in name or not os.path.isabs(name):
            raise SafetyError("Native handles require an absolute Unicode path without NUL")
        access = _GENERIC_READ | (_DELETE if delete else 0)
        share = _SHARE_READ if directory or not delete else 0
        flags = _OPEN_REPARSE | (_BACKUP_SEMANTICS if directory else 0)
        handle = api.CreateFile(name, access, share, None, _OPEN_EXISTING, flags, None)
        if handle in (None, _INVALID_HANDLE):
            _fail(f"Cannot retain handle for {name}")
        token = _Token(self, handle, name, bool(delete), bool(directory))
        self._tokens.append(token)
        try:
            self.describe(token)
        except BaseException:
            self._close_token(token)
            raise
        return token

    def describe(self, token):
        token = self._checked(token)
        api, info = self._api, _FileInformation()
        if api.FileType(token.handle) != 1:  # FILE_TYPE_DISK
            raise SafetyError(f"Not a disk file/directory: {token.path}")
        if not api.Information(token.handle, ctypes.byref(info)):
            _fail(f"Cannot inspect retained handle for {token.path}")
        attributes = int(info.attributes)
        is_directory = bool(attributes & _DIRECTORY)
        if attributes & (_REPARSE | _DEVICE):
            raise SafetyError(f"Reparse point or device rejected: {token.path}")
        if is_directory != token.directory:
            raise SafetyError(f"Object kind changed or mismatched: {token.path}")
        if not is_directory and (attributes & _READONLY or info.links != 1):
            raise SafetyError(f"Readonly file or non-single-link file rejected: {token.path}")
        ticks = (int(info.write.dwHighDateTime) << 32) | int(info.write.dwLowDateTime)
        return dict(size=(int(info.size_high) << 32) | int(info.size_low),
                    mtime_ns=(ticks - _EPOCH_100NS) * 100,
                    file_id=(int(info.index_high) << 32) | int(info.index_low),
                    volume_id=int(info.volume), links=int(info.links),
                    attributes=attributes, kind="dir" if is_directory else "file")

    def sha256(self, token):
        token = self._checked(token)
        before = self.describe(token)
        if token.directory:
            raise SafetyError("Cannot hash a directory handle")
        if not self._api.Seek(token.handle, 0, None, 0):  # FILE_BEGIN
            _fail(f"Cannot rewind retained handle for {token.path}")
        digest, total = hashlib.sha256(), 0
        buffer = ctypes.create_string_buffer(1024 * 1024)
        received = wintypes.DWORD()
        while True:
            if not self._api.Read(token.handle, buffer, len(buffer), ctypes.byref(received), None):
                _fail(f"Cannot read retained handle for {token.path}")
            if not received.value:
                break
            digest.update(buffer.raw[:received.value])
            total += received.value
            if total > before["size"]:
                raise SafetyError(f"File grew while hashing: {token.path}")
        if total != before["size"] or self.describe(token) != before:
            raise SafetyError(f"File changed or read was incomplete: {token.path}")
        return digest.hexdigest()

    def delete(self, token):
        token = self._checked(token)
        if not token.can_delete:
            raise SafetyError("A read-only guard handle cannot authorize deletion")
        self.describe(token)
        disposition = _Disposition(1)
        if not self._api.Disposition(token.handle, 4, ctypes.byref(disposition), ctypes.sizeof(disposition)):
            _fail(f"Cannot mark retained object for deletion: {token.path}")
        token.delete_pending = True
        self._close_token(token)

    def _close_token(self, token):
        if not token.closed:
            if not self._api.Close(token.handle):
                _fail(f"Cannot close retained handle for {token.path}")
            token.closed = True

    def close(self):
        if self._closed:
            return
        errors = []
        for token in reversed(self._tokens):
            try:
                self._close_token(token)
            except OSError as error:
                errors.append(str(error))
        self._closed = True
        if errors:
            raise SafetyError("Native handle cleanup failed: " + "; ".join(errors))


def running_runtimes():
    """Snapshot relevant processes; inaccessible images remain None, with no exemptions."""
    api = _Api()
    snapshot = api.Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
    if snapshot in (None, _INVALID_HANDLE):
        _fail("Cannot enumerate running processes")
    found, entry = [], _ProcessEntry()
    entry.dwSize = ctypes.sizeof(entry)
    try:
        more = api.First(snapshot, ctypes.byref(entry))
        while more:
            exe = str(entry.szExeFile)
            if _RUNTIME.fullmatch(exe):
                image = None
                process = api.OpenProcess(0x1000, False, entry.th32ProcessID)
                if process:
                    try:
                        buffer = ctypes.create_unicode_buffer(32768)
                        size = wintypes.DWORD(len(buffer))
                        if api.Image(process, 0, buffer, ctypes.byref(size)):
                            image = buffer.value
                    finally:
                        if not api.Close(process):
                            _fail("Cannot close process inspection handle")
                found.append(dict(pid=int(entry.th32ProcessID), exe=exe,
                                  parent_pid=int(entry.th32ParentProcessID), image=image))
            more = api.Next(snapshot, ctypes.byref(entry))
        if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
            _fail("Process enumeration was incomplete")
    finally:
        if not api.Close(snapshot):
            _fail("Cannot close process snapshot handle")
    return sorted(found, key=lambda item: item["pid"])
