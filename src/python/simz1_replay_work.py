"""Cooperative, read-only replay work: cancellation and observed progress.

No deadline is imposed on a live request. SQLite's progress callback and the
Python assembly loops share the same control; cancellation never publishes a
partial window or alters the immutable evidence.
"""
from contextlib import contextmanager
import threading
import time


class WorkCancelled(Exception):
    pass


class ReadWork:
    def __init__(self, abandoned=lambda: False, observer=None):
        self.abandoned = abandoned
        self.cancelled = threading.Event()
        self.reason = None
        self.started = self.updated = time.monotonic()
        self.last_check = 0
        self.lock = threading.Lock()
        self.phase = 'starting'
        self.steps = 0
        self.details = {}
        self.observer, self.last_report = observer, 0

    def cancel(self, reason):
        self.reason = reason
        self.cancelled.set()

    def check(self, phase=None, **details):
        now = time.monotonic()
        if self.cancelled.is_set():
            raise WorkCancelled(self.reason)
        # Checking socket liveness on every decoded field is unnecessary.
        if now-self.last_check >= .1:
            self.last_check = now
            if self.abandoned():
                self.cancel('all_clients_disconnected')
                raise WorkCancelled(self.reason)
        with self.lock:
            self.steps += 1
            self.updated = now
            if phase is not None:
                self.phase = phase
            self.details.update(details)
        if self.observer is not None and now-self.last_report >= .2:
            self.last_report=now
            self.observer(self.snapshot())

    def sqlite_progress(self):
        try:
            self.check()
            return 0
        except WorkCancelled:
            return 1

    def snapshot(self):
        with self.lock:
            now = time.monotonic()
            return dict(phase=self.phase, checkpoints=self.steps, elapsed_seconds=now-self.started,
                        last_progress_age_seconds=now-self.updated, cancellation=self.reason, **self.details)


_local = threading.local()


@contextmanager
def work_scope(work):
    previous = getattr(_local, 'work', None)
    _local.work = work
    try:
        yield
    finally:
        _local.work = previous


def checkpoint(phase=None, **details):
    work = getattr(_local, 'work', None)
    if work is not None:
        work.check(phase, **details)


def cancellable_connection(connection):
    work = getattr(_local, 'work', None)
    if work is not None:
        try:
            work.check('sqlite')
            connection.set_progress_handler(work.sqlite_progress, 10000)
        except Exception:
            connection.close()
            raise
    return connection
