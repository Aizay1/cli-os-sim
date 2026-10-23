"""Core data models for the CLI OS Simulator.

The simulator uses a *discrete-event* model driven by a virtual clock: time
only advances when a process performs CPU work, waits on I/O, or when the
simulator jumps straight to the next scheduled event. Nothing sleeps on the
real wall clock, so every run is fast and fully deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class State(str, Enum):
    """Life-cycle state of a simulated process."""

    NEW = "NEW"
    READY = "READY"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    TERMINATED = "TERMINATED"


class CmdType(str, Enum):
    """The kinds of instructions a program block may contain."""

    CPU = "cpu"          # wait(n) / cpu(n): burn n units of CPU time
    IO = "io"            # io(n): block n units off the CPU
    ACQUIRE = "acquire"  # resource(r, allocate): take an instance of R<r>
    RELEASE = "release"  # resource(r, release): give an instance back
    END = "end"          # end: terminate and release everything


@dataclass
class Command:
    """A single instruction belonging to a process."""

    type: CmdType
    value: int = 0          # duration (cpu/io) or resource id (acquire/release)
    raw: str = ""           # original text, kept for error messages


@dataclass
class Process:
    """A simulated process together with its scheduling and resource state."""

    name: str
    commands: List[Command]
    priority: int = 0       # lower number == higher priority
    arrival: float = 0.0    # virtual arrival time
    seq: int = 0            # declaration order, used as a stable tie-breaker

    # ---- runtime state (managed by the engine) ----
    state: State = State.NEW
    pc: int = 0
    remaining: float = 0.0                     # time left on the current cpu/io command
    quantum_left: Optional[float] = None
    blocked_resource: Optional[int] = None     # resource id we are waiting for
    wake_time: Optional[float] = None          # when an I/O block finishes
    blocked_at: Optional[float] = None         # when we started blocking (FIFO fairness)
    dispatched: bool = False

    # ---- metrics ----
    start_time: Optional[float] = None         # first time this process got the CPU
    finish_time: Optional[float] = None
    cpu_time: float = 0.0
    ready_wait: float = 0.0                    # total time spent in the READY queue
    response_time: Optional[float] = None

    # ------------------------------------------------------------------ #
    # Derived metrics
    # ------------------------------------------------------------------ #
    @property
    def turnaround(self) -> Optional[float]:
        """Completion time relative to arrival."""
        if self.finish_time is None:
            return None
        return self.finish_time - self.arrival

    @property
    def waiting_time(self) -> float:
        """Total time the process spent waiting for the CPU."""
        return self.ready_wait

    @property
    def cpu_demand(self) -> float:
        """Total CPU time requested by the whole program (used by SJF)."""
        return float(sum(c.value for c in self.commands if c.type is CmdType.CPU))

    @property
    def io_demand(self) -> float:
        """Total I/O time requested by the whole program."""
        return float(sum(c.value for c in self.commands if c.type is CmdType.IO))

    def remaining_cpu_demand(self) -> float:
        """CPU time still to be executed (used by SRTF)."""
        total = 0.0
        for i in range(self.pc, len(self.commands)):
            cmd = self.commands[i]
            if cmd.type is CmdType.CPU:
                total += cmd.value
        # Discount whatever part of the current burst is already done.
        if self.pc < len(self.commands):
            cur = self.commands[self.pc]
            if cur.type is CmdType.CPU and self.remaining > 0:
                total -= cur.value - self.remaining
        return max(0.0, total)

    def max_need(self) -> Dict[int, int]:
        """Upper bound on how many instances of each resource this program may
        ever hold at once. Used by the Banker's-avoidance safety check."""
        need: Dict[int, int] = {}
        for cmd in self.commands:
            if cmd.type is CmdType.ACQUIRE:
                need[cmd.value] = need.get(cmd.value, 0) + 1
        return need

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return self.name


@dataclass
class Event:
    """A timestamped entry for the simulation trace / action log."""

    time: float
    process: str
    action: str
    resource: Optional[int] = None
    detail: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "time": round(self.time, 3),
            "process": self.process,
            "action": self.action,
            "resource": f"R{self.resource}" if self.resource is not None else None,
            "detail": self.detail,
        }


@dataclass
class Segment:
    """A contiguous slice of the CPU timeline, used to draw the Gantt chart."""

    start: float
    end: float
    label: str

    @property
    def duration(self) -> float:
        return self.end - self.start
