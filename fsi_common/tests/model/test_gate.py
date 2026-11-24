"""Tests for the process-wide cap on concurrent headless calls."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest

from fsi_common.model.errors import ModelConfigError
from fsi_common.model.gate import ConcurrencyGate


def _hold(gate: ConcurrencyGate, seconds: float) -> None:
    with gate.slot():
        time.sleep(seconds)


def test_threads_never_exceed_the_capacity() -> None:
    gate = ConcurrencyGate(4)
    threads = [threading.Thread(target=_hold, args=(gate, 0.05)) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert gate.peak == 4
    assert gate.in_use == 0
    assert gate.granted == 10


def test_async_tasks_never_exceed_the_capacity() -> None:
    gate = ConcurrencyGate(4)

    async def one() -> None:
        async with gate.aslot():
            await asyncio.sleep(0.05)

    async def main() -> None:
        await asyncio.gather(*(one() for _ in range(10)))

    asyncio.run(main())
    assert gate.peak == 4
    assert gate.in_use == 0
    assert gate.granted == 10


def test_threads_and_the_event_loop_share_one_cap() -> None:
    gate = ConcurrencyGate(4)

    async def one() -> None:
        async with gate.aslot():
            await asyncio.sleep(0.05)

    async def main() -> None:
        await asyncio.gather(*(one() for _ in range(6)))

    threads = [threading.Thread(target=_hold, args=(gate, 0.05)) for _ in range(6)]
    for thread in threads:
        thread.start()
    asyncio.run(main())
    for thread in threads:
        thread.join()
    assert gate.peak == 4
    assert gate.granted == 12


def test_a_cancelled_waiter_gives_its_slot_back() -> None:
    gate = ConcurrencyGate(1)

    async def main() -> None:
        async with gate.aslot():
            waiter = asyncio.ensure_future(gate.aslot().__aenter__())
            await asyncio.sleep(0.01)
            waiter.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiter
        async with gate.aslot():
            assert gate.in_use == 1

    asyncio.run(main())
    assert gate.in_use == 0


def test_an_error_inside_the_slot_releases_it() -> None:
    gate = ConcurrencyGate(1)
    with pytest.raises(RuntimeError, match="boom"), gate.slot():
        raise RuntimeError("boom")
    assert gate.in_use == 0


@pytest.mark.parametrize("capacity", [0, -1])
def test_capacity_must_be_positive(capacity: int) -> None:
    with pytest.raises(ModelConfigError, match="at least 1"):
        ConcurrencyGate(capacity)
