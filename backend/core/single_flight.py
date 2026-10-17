"""Single-flight: identical requests arriving together wait for one portal call instead
of each sending their own. Nothing is kept once the call finishes — callers that come
later make a fresh call (or hit whatever cache the caller wraps around it)."""
import threading

_lock = threading.Lock()
_inflight: dict = {}


class _Call:
    __slots__ = ("event", "result", "exc")

    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.exc = None


def single_flight(key: tuple, work):
    with _lock:
        call = _inflight.get(key)
        leader = call is None
        if leader:
            call = _inflight[key] = _Call()
    if not leader:
        call.event.wait()
        if call.exc is not None:
            raise call.exc
        return call.result
    try:
        call.result = work()
        return call.result
    except BaseException as exc:
        call.exc = exc
        raise
    finally:
        with _lock:
            _inflight.pop(key, None)
        call.event.set()
