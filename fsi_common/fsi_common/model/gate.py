"""A first-come, first-served cap on concurrent headless calls, shared by threads and loops."""

from __future__ import annotations

import asyncio
import threading
from collections import deque
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from fsi_common.model.errors import ModelConfigError

PROCESS_CAP = 4
"""The most headless calls one process may run at once, however many models it builds."""


class _ThreadWaiter:
    def __init__(self) -> None:
        self.event = threading.Event()

    def grant(self) -> None:
        self.event.set()


class _LoopWaiter:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self.future: asyncio.Future[None] = loop.create_future()

    def grant(self) -> None:
        self.loop.call_soon_threadsafe(self._resolve)

    def _resolve(self) -> None:
        if not self.future.done():
            self.future.set_result(None)


class ConcurrencyGate:
    """Admit at most `capacity` holders at once, in arrival order, from any thread or loop."""

    def __init__(self, capacity: int) -> None:
        """Build a gate.

        Args:
            capacity: The most holders admitted at once.

        Raises:
            ModelConfigError: If the capacity is below 1.
        """
        if capacity < 1:
            raise ModelConfigError(f"A gate's capacity must be at least 1, not {capacity}.")
        self.capacity = capacity
        self._lock = threading.Lock()
        self._waiters: deque[_ThreadWaiter | _LoopWaiter] = deque()
        self.in_use = 0
        self.peak = 0
        self.granted = 0

    def _admit_locked(self) -> None:
        self.in_use += 1
        self.granted += 1
        self.peak = max(self.peak, self.in_use)

    def release(self) -> None:
        """Give a slot back, handing it straight to the longest waiter if there is one."""
        with self._lock:
            if self._waiters:
                waiter = self._waiters.popleft()
                self.granted += 1
                waiter.grant()
            else:
                self.in_use -= 1

    def acquire(self) -> int:
        """Block the calling thread until a slot is free; return the holders including this one."""
        with self._lock:
            if self.in_use < self.capacity and not self._waiters:
                self._admit_locked()
                return self.in_use
            waiter = _ThreadWaiter()
            self._waiters.append(waiter)
        waiter.event.wait()
        return self.in_use

    async def aacquire(self) -> int:
        """Wait on the event loop until a slot is free; return the holders including this one."""
        with self._lock:
            if self.in_use < self.capacity and not self._waiters:
                self._admit_locked()
                return self.in_use
            waiter = _LoopWaiter(asyncio.get_running_loop())
            self._waiters.append(waiter)
        try:
            await waiter.future
        except asyncio.CancelledError:
            with self._lock:
                still_waiting = waiter in self._waiters
                if still_waiting:
                    self._waiters.remove(waiter)
            if not still_waiting:
                self.release()
            raise
        return self.in_use

    @contextmanager
    def slot(self) -> Iterator[int]:
        """Hold a slot for the length of a `with` block; yield the holders at entry."""
        holders = self.acquire()
        try:
            yield holders
        finally:
            self.release()

    @asynccontextmanager
    async def aslot(self) -> AsyncIterator[int]:
        """Hold a slot for the length of an `async with` block; yield the holders at entry."""
        holders = await self.aacquire()
        try:
            yield holders
        finally:
            self.release()


_PROCESS_GATE = ConcurrencyGate(PROCESS_CAP)


def process_gate() -> ConcurrencyGate:
    """Return the one gate every model in this process passes through."""
    return _PROCESS_GATE
