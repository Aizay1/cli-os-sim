"""Pluggable CPU scheduling policies.

Every policy shares one small interface so the engine can swap algorithms
without any special-casing:

* ``pick(ready, clock)``              -> choose the next process to run
* ``should_preempt(running, ready)``  -> may an arriving process steal the CPU?
* ``quantum``                         -> time slice for time-sharing policies

``sort_key`` returns an ascending tuple: the smallest key wins.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .models import Process


class Scheduler:
    """Base class implementing the common "smallest key wins" policy."""

    name = "base"
    display = "Base"
    description = ""
    preemptive = False
    quantum: Optional[float] = None

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        raise NotImplementedError

    def pick(self, ready: List[Process], clock: float) -> Process:
        return min(
            ready,
            key=lambda p: (self.sort_key(p, clock), p.arrival, p.seq),
        )

    def should_preempt(self, running: Process, ready: List[Process], clock: float) -> bool:
        if not self.preemptive or not ready:
            return False
        best = self.pick(ready, clock)
        best_key = (self.sort_key(best, clock), best.arrival, best.seq)
        run_key = (self.sort_key(running, clock), running.arrival, running.seq)
        return best_key < run_key


class FCFS(Scheduler):
    name = "fcfs"
    display = "First-Come, First-Served"
    description = "Runs processes in arrival order; non-preemptive."

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        return (proc.arrival, proc.seq)


class SJF(Scheduler):
    name = "sjf"
    display = "Shortest Job First"
    description = "Picks the process with the smallest total CPU demand; non-preemptive."

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        return (proc.cpu_demand, proc.arrival, proc.seq)


class SRTF(Scheduler):
    name = "srtf"
    display = "Shortest Remaining Time First"
    description = "Preemptive SJF: always runs the process with the least remaining CPU work."
    preemptive = True

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        return (proc.remaining_cpu_demand(), proc.arrival, proc.seq)


class Priority(Scheduler):
    name = "priority"
    display = "Priority (non-preemptive)"
    description = "Runs the highest-priority process (lower number = higher priority)."

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        return (proc.priority, proc.arrival, proc.seq)


class PriorityPreemptive(Priority):
    name = "priority-p"
    display = "Priority (preemptive)"
    description = "Like Priority, but a higher-priority arrival immediately preempts."
    preemptive = True


class HRRN(Scheduler):
    name = "hrrn"
    display = "Highest Response Ratio Next"
    description = "Balances burst length with waiting time to avoid starvation."

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        burst = max(proc.cpu_demand, 1e-9)
        waiting = max(0.0, clock - proc.arrival)
        ratio = (waiting + burst) / burst
        return (-ratio, proc.arrival, proc.seq)


class RoundRobin(Scheduler):
    name = "rr"
    display = "Round Robin"
    description = "Time-slices every ready process with a fixed quantum."

    def __init__(self, quantum: float = 4) -> None:
        self.quantum = float(quantum)

    def pick(self, ready: List[Process], clock: float) -> Process:
        return ready[0]

    def sort_key(self, proc: Process, clock: float) -> Tuple:
        return (proc.arrival, proc.seq)


#: Registry used by the CLI and the comparison runner.
REGISTRY = {
    "fcfs": FCFS,
    "sjf": SJF,
    "srtf": SRTF,
    "rr": RoundRobin,
    "priority": Priority,
    "priority-p": PriorityPreemptive,
    "hrrn": HRRN,
}


def build(name: str, quantum: float = 4) -> Scheduler:
    """Instantiate a scheduler by its short name."""
    key = name.lower()
    if key not in REGISTRY:
        raise ValueError(
            f"unknown algorithm '{name}' (available: {', '.join(sorted(REGISTRY))})"
        )
    factory = REGISTRY[key]
    if factory is RoundRobin:
        return RoundRobin(quantum)
    return factory()
