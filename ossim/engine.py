"""Discrete-event simulation engine.

The engine ties together a *scheduler* (who runs next), a *resource manager*
(who owns what) and a *virtual clock* (how time moves). It drives one CPU by
default and supports configurable arriving times, I/O blocking, resource
contention, and deadlock detection / resolution.

Nothing here touches the wall clock: time only advances when the simulation
says it does, which makes runs instant and reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .models import CmdType, Event, Process, Segment, State
from .resources import ResourceManager
from .schedulers import Scheduler

_EPS = 1e-9


@dataclass
class SimConfig:
    """Tuning knobs for a single simulation run."""

    #: What to do when a deadlock is found: ``manual`` | ``terminate`` | ``preempt``
    deadlock_policy: str = "terminate"
    #: Victim choice when auto-resolving: ``resources`` | ``priority`` | ``progress``
    victim_policy: str = "resources"
    #: Optional deadlock avoidance: ``None`` or ``banker``
    avoidance: Optional[str] = None
    #: Ask the user before resolving a deadlock (only for ``manual``)
    interactive: bool = False
    #: Hard stop to protect against pathological inputs
    max_steps: int = 200_000
    #: Hooks so the engine can be used in tests without touching stdin/stdout
    input_fn: Callable[[str], str] = input
    output_fn: Callable[[str], None] = print
    verbose: bool = True


class Simulation:
    """Runs one workload under one scheduling policy."""

    def __init__(self, processes: List[Process], scheduler: Scheduler,
                 resource_counts: Optional[Dict[int, int]] = None,
                 config: Optional[SimConfig] = None) -> None:
        self.processes = processes
        self.scheduler = scheduler
        self.config = config or SimConfig()
        self.res = ResourceManager(resource_counts or {})

        self.by_name: Dict[str, Process] = {p.name: p for p in processes}
        self.clock = 0.0
        self.ready: List[Process] = []
        self.blocked: List[Process] = []
        self.finished: List[Process] = []
        self.running: Optional[Process] = None

        self.pending: List[Process] = sorted(
            processes, key=lambda p: (p.arrival, p.seq)
        )

        self.events: List[Event] = []
        self.timeline: List[Segment] = []
        self.force_released: List[Tuple[int, str]] = []
        self.busy_time = 0.0
        self.dispatches = 0
        self.aborted = False
        self.deadlocks = 0

    # ------------------------------------------------------------------ #
    # Logging / timeline helpers
    # ------------------------------------------------------------------ #
    def event(self, process: str, action: str, resource: Optional[int] = None,
              detail: Optional[str] = None) -> None:
        self.events.append(Event(self.clock, process, action, resource, detail))

    def _push_segment(self, label: str, start: float, end: float) -> None:
        if end - start <= _EPS:
            return
        if self.timeline and self.timeline[-1].label == label and \
                abs(self.timeline[-1].end - start) <= _EPS:
            self.timeline[-1].end = end
        else:
            self.timeline.append(Segment(start, end, label))

    # ------------------------------------------------------------------ #
    # Time
    # ------------------------------------------------------------------ #
    def advance(self, dt: float, cpu: bool) -> None:
        if dt <= _EPS:
            return
        label = self.running.name if self.running else "IDLE"
        self._push_segment(label, self.clock, self.clock + dt)
        for proc in self.ready:
            proc.ready_wait += dt
        self.clock += dt
        if cpu:
            self.busy_time += dt

    def next_event_time(self) -> Optional[float]:
        candidates: List[float] = []
        if self.pending:
            candidates.append(self.pending[0].arrival)
        for proc in self.blocked:
            if proc.wake_time is not None:
                candidates.append(proc.wake_time)
        future = [t for t in candidates if t > self.clock + _EPS]
        return min(future) if future else None

    def sync(self) -> None:
        """Admit arrivals and wake up finished I/O blocks."""
        while self.pending and self.pending[0].arrival <= self.clock + _EPS:
            proc = self.pending.pop(0)
            proc.state = State.READY
            self.ready.append(proc)
            self.event(proc.name, "arrived")
        for proc in list(self.blocked):
            if proc.wake_time is not None and proc.wake_time <= self.clock + _EPS:
                proc.wake_time = None
                proc.state = State.READY
                self.blocked.remove(proc)
                self.ready.append(proc)
                self.event(proc.name, "io complete")

    # ------------------------------------------------------------------ #
    # CPU hand-off
    # ------------------------------------------------------------------ #
    def dispatch(self) -> None:
        proc = self.scheduler.pick(self.ready, self.clock)
        self.ready.remove(proc)
        proc.state = State.RUNNING
        if not proc.dispatched:
            proc.dispatched = True
            proc.start_time = self.clock
            proc.response_time = self.clock - proc.arrival
        proc.quantum_left = self.scheduler.quantum
        self.running = proc
        self.dispatches += 1
        self.event(proc.name, "dispatched")

    def preempt(self, proc: Process) -> None:
        proc.state = State.READY
        self.running = None
        self.ready.append(proc)
        self.event(proc.name, "preempted")

    def terminate(self, proc: Process) -> None:
        proc.state = State.TERMINATED
        proc.finish_time = self.clock
        if proc in self.ready:
            self.ready.remove(proc)
        if proc in self.blocked:
            self.blocked.remove(proc)
        self.res.drop_waiting(proc.name)
        released = self.res.release_all(proc.name)
        if self.running is proc:
            self.running = None
        if proc not in self.finished:
            self.finished.append(proc)
        self.event(proc.name, "terminated",
                   detail=f"released {', '.join('R'+str(r) for r in released) or 'nothing'}")
        for rid in released:
            self.wake_waiters(rid)

    def wake_waiters(self, rid: int) -> None:
        while self.res.free_instances(rid) > 0:
            name = self.res.next_waiter(rid)
            if name is None:
                break
            proc = self.by_name[name]
            self.res.acquire(rid, name)
            if proc in self.blocked:
                self.blocked.remove(proc)
            proc.blocked_resource = None
            proc.state = State.READY
            proc.pc += 1
            self.ready.append(proc)
            self.event(name, "acquired after wait", resource=rid)

    def _maybe_preempt(self, proc: Process) -> bool:
        if self.scheduler.preemptive and \
                self.scheduler.should_preempt(proc, self.ready, self.clock):
            self.preempt(proc)
            return True
        return False

    # ------------------------------------------------------------------ #
    # Resource acquisition (with optional Banker's avoidance)
    # ------------------------------------------------------------------ #
    def _acquire(self, proc: Process, rid: int) -> bool:
        if self.config.avoidance == "banker":
            self.res.ensure(rid)
            if self.res.free_instances(rid) <= 0:
                return False
            self.res.acquire(rid, proc.name)
            if self._banker_safe():
                return True
            self.res.release(rid, proc.name)
            return False
        return self.res.acquire(rid, proc.name)

    def _banker_safe(self) -> bool:
        unfinished = [p.name for p in self.processes if p.state is not State.TERMINATED]
        max_need = {p.name: p.max_need() for p in self.processes}
        return self.res.is_safe(max_need, unfinished)

    # ------------------------------------------------------------------ #
    # Instruction execution
    # ------------------------------------------------------------------ #
    def execute(self) -> None:
        proc = self.running
        assert proc is not None
        guard = 0
        while self.running is proc:
            guard += 1
            if guard > 10_000:
                self.event("SYSTEM", "aborted", detail="instruction guard exceeded")
                self.aborted = True
                self.running = None
                return

            if proc.pc >= len(proc.commands):
                self.terminate(proc)
                return

            cmd = proc.commands[proc.pc]

            # A time-sharing quantum limits *CPU* work only. Zero-time
            # instructions (acquire/release/end) may still be executed.
            if cmd.type is CmdType.CPU and proc.quantum_left is not None \
                    and proc.quantum_left <= _EPS:
                proc.quantum_left = 0.0
                self.preempt(proc)
                return

            if cmd.type is CmdType.CPU:
                if proc.remaining <= _EPS:
                    proc.remaining = float(cmd.value)
                limit = proc.remaining
                if proc.quantum_left is not None:
                    limit = min(limit, proc.quantum_left)
                nxt = self.next_event_time()
                if nxt is not None:
                    limit = min(limit, nxt - self.clock)
                if limit <= _EPS:
                    # An event is scheduled for *now*; sync and retry.
                    self.sync()
                    continue

                self.advance(limit, cpu=True)
                proc.remaining -= limit
                proc.cpu_time += limit
                if proc.quantum_left is not None:
                    proc.quantum_left = max(0.0, proc.quantum_left - limit)
                self.sync()

                if proc.remaining <= _EPS:
                    proc.remaining = 0.0
                    proc.pc += 1
                    self.event(proc.name, "cpu burst complete",
                               detail=f"{cmd.value} units")
                if self.running is proc and self._maybe_preempt(proc):
                    return

            elif cmd.type is CmdType.IO:
                proc.blocked_at = self.clock
                proc.wake_time = self.clock + cmd.value
                proc.state = State.BLOCKED
                proc.pc += 1
                self.blocked.append(proc)
                self.running = None
                self.event(proc.name, "io start", detail=f"{cmd.value} units")

            elif cmd.type is CmdType.ACQUIRE:
                if self._acquire(proc, cmd.value):
                    proc.pc += 1
                    self.event(proc.name, "acquired", resource=cmd.value)
                    if self.running is proc and self._maybe_preempt(proc):
                        return
                else:
                    proc.state = State.BLOCKED
                    proc.blocked_resource = cmd.value
                    proc.blocked_at = self.clock
                    self.res.enqueue_wait(cmd.value, proc.name)
                    self.blocked.append(proc)
                    self.running = None
                    self.event(proc.name, "blocked on resource", resource=cmd.value)

            elif cmd.type is CmdType.RELEASE:
                if self.res.release(cmd.value, proc.name):
                    proc.pc += 1
                    self.event(proc.name, "released", resource=cmd.value)
                    self.wake_waiters(cmd.value)
                    if self.running is proc and self._maybe_preempt(proc):
                        return
                else:
                    proc.pc += 1
                    self.event(proc.name, "release ignored",
                               resource=cmd.value, detail="instance not held")

            elif cmd.type is CmdType.END:
                self.terminate(proc)
                return

    # ------------------------------------------------------------------ #
    # Deadlock handling
    # ------------------------------------------------------------------ #
    def _choose_victim(self, victims: List[str]) -> str:
        policy = self.config.victim_policy
        if policy == "priority":
            # Kill the least important process (largest priority number).
            return max(victims, key=lambda n: (self.by_name[n].priority, self.by_name[n].seq))
        if policy == "progress":
            return min(victims, key=lambda n: (self.by_name[n].cpu_time, self.by_name[n].seq))
        # default: the process hogging the most resource instances
        return max(
            victims,
            key=lambda n: (sum(self.res.held_by(n).values()), self.by_name[n].seq),
        )

    def force_release(self, rid: int) -> bool:
        holders = self.res.holders(rid)
        if not holders:
            return False
        owner = holders[0]
        self.res.release(rid, owner)
        self.force_released.append((rid, owner))
        self.event("SYSTEM", "force released", resource=rid, detail=f"from {owner}")
        self.wake_waiters(rid)
        return True

    def handle_deadlock(self) -> bool:
        """Detect and (try to) resolve a deadlock. Returns True if resolved."""
        waits = {p.name: p.blocked_resource for p in self.blocked
                 if p.blocked_resource is not None}
        if not waits:
            return False
        victims = self.res.find_deadlocked(waits)
        if not victims:
            return False

        self.deadlocks += 1
        self.event("SYSTEM", "deadlock detected",
                   detail="involving " + ", ".join(sorted(victims)))
        if self.config.verbose:
            self.config.output_fn(
                f"\n[deadlock] detected at t={self.clock:g}: {', '.join(sorted(victims))}"
            )

        policy = self.config.deadlock_policy
        if policy == "manual" and self.config.interactive:
            if self._manual_resolve(victims):
                return True
            policy = "terminate"

        if policy == "preempt":
            for name in victims:
                for rid in list(self.res.held_by(name)):
                    if any(self.by_name[v].blocked_resource == rid for v in victims):
                        if self.force_release(rid):
                            return True
            policy = "terminate"

        victim = self._choose_victim(victims)
        self.event("SYSTEM", "terminating victim", detail=victim)
        if self.config.verbose:
            self.config.output_fn(f"[deadlock] terminating victim '{victim}' to recover")
        self.terminate(self.by_name[victim])
        return True

    def _manual_resolve(self, victims: List[str]) -> bool:
        options = sorted({
            rid
            for name in victims
            for rid in list(self.res.held_by(name))
        })
        if not options:
            return False
        self.config.output_fn(
            "  held resources in the cycle: " + ", ".join(f"R{r}" for r in options)
        )
        raw = self.config.input_fn(
            "  release which resource? (R id, blank = auto-resolve): "
        ).strip()
        if not raw:
            return False
        try:
            rid = int(raw.lstrip("Rr"))
        except ValueError:
            self.config.output_fn("  invalid input, falling back to auto-resolve")
            return False
        if rid not in options:
            self.config.output_fn("  resource not involved, falling back to auto-resolve")
            return False
        return self.force_release(rid)

    # ------------------------------------------------------------------ #
    # Main loop
    # ------------------------------------------------------------------ #
    def run(self) -> "Simulation":
        self.sync()
        steps = 0
        while True:
            steps += 1
            if steps > self.config.max_steps:
                self.aborted = True
                self.event("SYSTEM", "aborted", detail="step budget exceeded")
                break

            self.sync()
            if self.running is None:
                if self.ready:
                    self.dispatch()
                    continue
                nxt = self.next_event_time()
                if nxt is not None:
                    self.advance(nxt - self.clock, cpu=False)
                    continue
                if self.blocked:
                    if not self.handle_deadlock():
                        self.aborted = True
                        self.event("SYSTEM", "stalled",
                                   detail="blocked processes cannot make progress")
                        break
                    continue
                break

            self.execute()

        self._finalize()
        return self

    # ------------------------------------------------------------------ #
    # Results
    # ------------------------------------------------------------------ #
    def _finalize(self) -> None:
        self.end_time = self.clock

    @property
    def makespan(self) -> float:
        return getattr(self, "end_time", self.clock)

    def process_rows(self) -> List[Dict[str, object]]:
        rows = []
        for proc in self.processes:
            rows.append({
                "name": proc.name,
                "priority": proc.priority,
                "arrival": proc.arrival,
                "start": proc.start_time,
                "finish": proc.finish_time,
                "burst": proc.cpu_demand,
                "io": proc.io_demand,
                "turnaround": proc.turnaround,
                "waiting": proc.waiting_time,
                "response": proc.response_time,
                "state": proc.state.value,
            })
        return rows

    def metrics(self) -> Dict[str, float]:
        done = [p for p in self.processes if p.finish_time is not None]
        n = len(done)
        span = self.makespan
        def avg(values):
            return sum(values) / len(values) if values else 0.0

        return {
            "processes": float(len(self.processes)),
            "completed": float(n),
            "makespan": span,
            "avg_turnaround": avg([p.turnaround for p in done]),
            "avg_waiting": avg([p.waiting_time for p in done]),
            "avg_response": avg([p.response_time for p in done if p.response_time is not None]),
            "cpu_utilization": (self.busy_time / span) if span > _EPS else 0.0,
            "throughput": (n / span) if span > _EPS else 0.0,
            "dispatches": float(self.dispatches),
            "context_switches": float(max(0, self.dispatches - 1)),
            "deadlocks": float(self.deadlocks),
            "force_releases": float(len(self.force_released)),
        }
