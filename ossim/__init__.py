"""CLI OS Simulator - a professional, educational operating-systems simulator.

Public API
----------
>>> from ossim import parse_file, simulate
>>> program = parse_file("program.txt")
>>> sim = simulate(program, algorithm="rr", quantum=2)
>>> print(sim.metrics()["avg_turnaround"])

See ``README.md`` for the full command-line interface and file format.
"""
from __future__ import annotations

from typing import Dict, Optional

from .engine import SimConfig, Simulation
from .models import CmdType, Command, Event, Process, Segment, State
from .parser import ParseError, Program, parse_file, parse_text
from .schedulers import REGISTRY, Scheduler, build

__version__ = "2.0.0"

__all__ = [
    "CmdType",
    "Command",
    "Event",
    "Process",
    "Segment",
    "State",
    "ParseError",
    "Program",
    "Simulation",
    "SimConfig",
    "Scheduler",
    "REGISTRY",
    "build",
    "parse_file",
    "parse_text",
    "simulate",
    "simulate_all",
    "compare",
    "__version__",
]


def simulate(
    program: Program,
    algorithm: str = "fcfs",
    quantum: float = 4,
    config: Optional[SimConfig] = None,
) -> Simulation:
    """Run ``program`` under a single scheduling ``algorithm``."""
    scheduler = build(algorithm, quantum=quantum)
    sim = Simulation(
        [Process(p.name, list(p.commands), p.priority, p.arrival, p.seq)
         for p in program.processes],
        scheduler,
        resource_counts=dict(program.resources),
        config=config,
    )
    return sim.run()


def simulate_all(
    program: Program,
    quantum: float = 4,
    config: Optional[SimConfig] = None,
) -> Dict[str, Simulation]:
    """Run ``program`` under every registered algorithm."""
    results: Dict[str, Simulation] = {}
    for name in REGISTRY:
        results[name] = simulate(program, algorithm=name, quantum=quantum, config=config)
    return results


def compare(
    program: Program,
    algorithms: Optional[list] = None,
    quantum: float = 4,
    config: Optional[SimConfig] = None,
) -> Dict[str, Dict[str, float]]:
    """Return the aggregate metrics for each algorithm (for comparison)."""
    names = algorithms or list(REGISTRY)
    out: Dict[str, Dict[str, float]] = {}
    for name in names:
        out[name] = simulate(program, algorithm=name, quantum=quantum, config=config).metrics()
    return out
