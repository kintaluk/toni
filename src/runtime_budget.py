"""Bound request waiting and upstream concurrency without unbounded work queues."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed


class BoundedExecutor:
    def __init__(self, max_workers=24):
        self._slots = threading.BoundedSemaphore(max_workers)
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="upstream")

    def submit(self, fn, *args, **kwargs):
        if not self._slots.acquire(blocking=False):
            return None
        try:
            future = self._pool.submit(fn, *args, **kwargs)
        except BaseException:
            self._slots.release()
            raise
        future.add_done_callback(lambda _: self._slots.release())
        return future


UPSTREAM_EXECUTOR = BoundedExecutor()


def remaining(deadline):
    return max(0.0, deadline - time.monotonic())


def completed_until(futures, deadline):
    pending = {f for f in futures if f is not None}
    try:
        if pending and remaining(deadline) > 0:
            yield from as_completed(pending, timeout=remaining(deadline))
    except TimeoutError:
        pass
    finally:
        for future in pending:
            future.cancel()


def call_until(wait_deadline, fn, *args, **kwargs):
    if remaining(wait_deadline) <= 0:
        raise TimeoutError("Request budget exhausted")
    future = UPSTREAM_EXECUTOR.submit(fn, *args, **kwargs)
    if future is None:
        raise TimeoutError("Upstream capacity is busy")
    try:
        return future.result(timeout=remaining(wait_deadline))
    finally:
        future.cancel()
