"""Resource manager, deadlock detection and optional Banker's avoidance.

Resources are modelled as counting semaphores: every resource ``R<id>`` has a
configurable number of identical instances (default 1). Processes acquire and
release instances; when no instance is free a process blocks and joins a FIFO
waiting queue for that resource.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional


class ResourceManager:
    """Tracks ownership of every resource instance."""

    def __init__(self, counts: Optional[Dict[int, int]] = None) -> None:
        self.total: Dict[int, int] = {}
        self.available: Dict[int, int] = {}
        self.allocation: Dict[int, Dict[str, int]] = defaultdict(dict)   # rid -> {proc: n}
        self.held: Dict[str, Dict[int, int]] = defaultdict(dict)         # proc -> {rid: n}
        self.wait_queue: Dict[int, Deque[str]] = defaultdict(deque)      # rid -> FIFO of procs

        for rid, count in (counts or {}).items():
            self._declare(rid, count)

    # ------------------------------------------------------------------ #
    # Declarations / simple queries
    # ------------------------------------------------------------------ #
    def _declare(self, rid: int, count: int) -> None:
        self.total[rid] = count
        self.available[rid] = count

    def ensure(self, rid: int) -> None:
        """Auto-declare a resource with a single instance if it is unknown."""
        if rid not in self.total:
            self._declare(rid, 1)

    def total_instances(self, rid: int) -> int:
        self.ensure(rid)
        return self.total[rid]

    def free_instances(self, rid: int) -> int:
        self.ensure(rid)
        return self.available[rid]

    def holders(self, rid: int) -> List[str]:
        return [name for name, n in self.allocation.get(rid, {}).items() if n > 0]

    def held_by(self, proc: str) -> Dict[int, int]:
        return dict(self.held.get(proc, {}))

    # ------------------------------------------------------------------ #
    # Acquire / release
    # ------------------------------------------------------------------ #
    def acquire(self, rid: int, proc: str) -> bool:
        """Try to give one instance of ``rid`` to ``proc``. Returns success."""
        self.ensure(rid)
        if self.available[rid] <= 0:
            return False
        self.available[rid] -= 1
        self.allocation[rid][proc] = self.allocation[rid].get(proc, 0) + 1
        self.held[proc][rid] = self.held[proc].get(rid, 0) + 1
        # The process is no longer waiting for this resource.
        self._drop_from_queue(rid, proc)
        return True

    def release(self, rid: int, proc: str, count: int = 1) -> bool:
        """Return ``count`` instances of ``rid`` owned by ``proc``."""
        owned = self.held.get(proc, {}).get(rid, 0)
        if owned <= 0:
            return False
        give = min(count, owned)
        self.held[proc][rid] = owned - give
        if self.held[proc][rid] == 0:
            del self.held[proc][rid]
        self.allocation[rid][proc] = self.allocation[rid].get(proc, 0) - give
        if self.allocation[rid][proc] <= 0:
            self.allocation[rid].pop(proc, None)
        self.available[rid] = self.available.get(rid, 0) + give
        return True

    def release_all(self, proc: str) -> List[int]:
        """Release every resource held by ``proc``; returns the resource ids."""
        released = []
        for rid, count in list(self.held.get(proc, {}).items()):
            self.release(rid, proc, count)
            released.append(rid)
        self.held.pop(proc, None)
        return released

    # ------------------------------------------------------------------ #
    # Waiting queue
    # ------------------------------------------------------------------ #
    def enqueue_wait(self, rid: int, proc: str) -> None:
        self.ensure(rid)
        if proc not in self.wait_queue[rid]:
            self.wait_queue[rid].append(proc)

    def _drop_from_queue(self, rid: int, proc: str) -> None:
        queue = self.wait_queue.get(rid)
        if queue and proc in queue:
            queue.remove(proc)

    def drop_waiting(self, proc: str) -> None:
        for queue in self.wait_queue.values():
            if proc in queue:
                queue.remove(proc)

    def next_waiter(self, rid: int) -> Optional[str]:
        queue = self.wait_queue.get(rid)
        return queue[0] if queue else None

    # ------------------------------------------------------------------ #
    # Deadlock detection
    # ------------------------------------------------------------------ #
    def find_deadlocked(self, waits: Dict[str, int]) -> List[str]:
        """Return the subset of blocked processes that can never make progress.

        ``waits`` maps a blocked process name to the resource id it is waiting
        for. The classic reduction algorithm is used, so it is correct for both
        single- and multi-instance resources.
        """
        candidates = list(waits.keys())
        work = dict(self.available)
        can_finish = set()
        progressed = True
        while progressed:
            progressed = False
            for name in candidates:
                if name in can_finish:
                    continue
                rid = waits[name]
                if work.get(rid, 0) > 0:
                    can_finish.add(name)
                    progressed = True
                    for r, count in self.held.get(name, {}).items():
                        work[r] = work.get(r, 0) + count
        return [name for name in candidates if name not in can_finish]

    # ------------------------------------------------------------------ #
    # Banker's algorithm (deadlock avoidance)
    # ------------------------------------------------------------------ #
    def is_safe(
        self,
        max_need: Dict[str, Dict[int, int]],
        unfinished: List[str],
    ) -> bool:
        """True if the current state admits a safe execution sequence."""
        work = dict(self.available)
        need: Dict[str, Dict[int, int]] = {}
        for name in unfinished:
            held = self.held.get(name, {})
            need[name] = {
                rid: max(0, total - held.get(rid, 0))
                for rid, total in max_need.get(name, {}).items()
            }
        finished = set()
        progressed = True
        while progressed:
            progressed = False
            for name in unfinished:
                if name in finished:
                    continue
                if all(work.get(rid, 0) >= count for rid, count in need[name].items()):
                    finished.add(name)
                    progressed = True
                    for rid, count in self.held.get(name, {}).items():
                        work[rid] = work.get(rid, 0) + count
        return len(finished) == len(unfinished)

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        """Serialisable view of the current allocation (rid -> owner -> count)."""
        return {
            f"R{rid}": dict(owners)
            for rid, owners in sorted(self.allocation.items())
        }
