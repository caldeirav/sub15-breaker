"""Optional, suite-neutral live observations. No observer means no side effects."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter_ns, time_ns

_observer = ContextVar("agent_observer", default=None)


@contextmanager
def observing(callback):
    token = _observer.set(callback)
    try:
        yield
    finally:
        _observer.reset(token)


def emit(stage, phase, **facts):
    callback = _observer.get()
    if callback is not None:
        callback(dict(stage=stage, phase=phase, monotonic_ns=perf_counter_ns(), timestamp_ns=time_ns(), **facts))
