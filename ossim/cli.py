"""Command-line interface for the CLI OS Simulator."""
from __future__ import annotations

import argparse
import sys
from typing import Dict, List, Optional, Tuple

from . import __version__
from .engine import SimConfig
from .parser import ParseError, Program, parse_file
from .report import (
    comparison_table,
    format_report,
    to_csv,
    to_dict,
    to_json,
)
from .schedulers import REGISTRY, build

#: Preferred order for menus and the comparison table.
ORDER = ["fcfs", "sjf", "srtf", "rr", "priority", "priority-p", "hrrn"]

#: Extra per-algorithm guidance shown by ``ossim help <algorithm>``.
ALGORITHM_NOTES: Dict[str, Dict[str, object]] = {
    "fcfs": {
        "order": "arrival time (ties broken by the order in the file)",
        "options": [],
        "example": "python3 -m ossim program.txt --algorithm fcfs",
        "best_for": (
            "Simple batch workloads. Fair by arrival order, but a single long "
            "job at the front delays every process behind it (the convoy effect)."
        ),
    },
    "sjf": {
        "order": "total CPU demand, shortest first",
        "options": [],
        "example": "python3 -m ossim program.txt --algorithm sjf",
        "best_for": (
            "Minimising average waiting time when burst lengths are known up "
            "front. Long jobs can starve."
        ),
    },
    "srtf": {
        "order": "remaining CPU demand, shortest first",
        "options": [],
        "example": "python3 -m ossim program.txt --algorithm srtf",
        "best_for": (
            "The best possible average waiting time; a newly arrived short job "
            "preempts the running one."
        ),
    },
    "rr": {
        "order": "arrival order, rotated after each quantum",
        "options": ["-q, --quantum N   time slice in units (default 4)"],
        "example": "python3 -m ossim program.txt --algorithm rr --quantum 2",
        "best_for": (
            "Time-sharing and interactive systems: every process is guaranteed "
            "CPU time and long jobs cannot hog the CPU. A smaller quantum "
            "improves responsiveness but adds context switches."
        ),
    },
    "priority": {
        "order": "priority number (lower number = higher priority)",
        "options": ["set a per-process priority in the workload: program NAME priority=1"],
        "example": "python3 -m ossim program.txt --algorithm priority",
        "best_for": (
            "Workloads with a clear importance ordering (e.g. system vs. batch "
            "jobs). Low-priority processes can starve."
        ),
    },
    "priority-p": {
        "order": "priority number (lower number = higher priority)",
        "options": ["set a per-process priority in the workload: program NAME priority=1"],
        "example": "python3 -m ossim program.txt --algorithm priority-p",
        "best_for": (
            "Like Priority, but a higher-priority arrival immediately takes the "
            "CPU -- good for responsive, priority-driven systems."
        ),
    },
    "hrrn": {
        "order": "highest response ratio (waiting + burst) / burst",
        "options": [],
        "example": "python3 -m ossim program.txt --algorithm hrrn",
        "best_for": (
            "Avoiding starvation while still favouring short jobs: waiting "
            "longer steadily raises a process's priority."
        ),
    },
}


def display_name(name: str) -> str:
    factory = REGISTRY.get(name)
    if factory is None:
        return name
    try:
        return build(name).display
    except Exception:  # pragma: no cover - defensive
        return name


def _scheduler_kind(sched) -> str:
    """Human label for a scheduler's preemption behaviour."""
    if sched.quantum is not None:
        return "preemptive, quantum-based"
    return "preemptive" if sched.preemptive else "non-preemptive"


def _algorithm_summary() -> str:
    """One short block per algorithm, used by the general help."""
    blocks = []
    for name in ORDER:
        sched = build(name)
        line = f"  {name:<12} {sched.display}"
        if "preemptive" not in sched.display.lower():
            line += f"  ({_scheduler_kind(sched)})"
        blocks.append(line)
        blocks.append(f"      $ {ALGORITHM_NOTES[name]['example']}")
    return "\n".join(blocks)


def general_help() -> str:
    """The full guide printed by ``ossim help``."""
    return f"""\
CLI OS Simulator {__version__} - help
{"=" * 34}

This tool simulates CPU scheduling, resource sharing and deadlock handling on
a fast virtual clock. Point it at a workload file and it prints which process
runs when, plus timing metrics.

USAGE
  python3 -m ossim <workload> [options]
  python3 -m ossim help [algorithm]     this guide, or one algorithm
  python3 -m ossim --list-algorithms    list algorithm names only
  python3 -m ossim --help               short list of options
  python3 ps-runner.py <workload>       same tool, legacy entry point

STEP BY STEP
  1. Write a workload file (see WORKLOAD FILE below) or use a bundled one.
  2. Run:  python3 -m ossim examples/timesharing.txt --algorithm rr
  3. Read the report: per-process table, Gantt chart, metrics, event trace.
  4. Add flags to change the algorithm, deadlock policy or output format.

OPTIONS
  -a, --algorithm NAME   pick a scheduling algorithm (see below); omit it to
                         choose interactively
  --all                  run every algorithm and print a comparison table
  -q, --quantum N        time slice for Round Robin (default 4)
  --deadlock POLICY      recovery policy: terminate | preempt | manual
                         (default terminate)
  --victim POLICY        victim choice: resources | priority | progress
                         (default resources)
  --avoidance MODE       deadlock avoidance: none | banker (default none)
  -f, --format FMT       report format: text | json | csv (default text)
  -o, --output FILE      write the report to FILE instead of the screen
  --quiet                suppress warnings and progress messages
  --list-algorithms      list algorithm names and exit
  --version              print the version and exit
  -h, --help             show this short help and exit

SCHEDULING ALGORITHMS
{_algorithm_summary()}

COMMON EXAMPLES
  # default run (choose the algorithm interactively when possible)
  python3 -m ossim program.txt

  # compare every policy on one workload
  python3 -m ossim examples/timesharing.txt --all

  # Round Robin with a 2-unit quantum
  python3 -m ossim examples/timesharing.txt --algorithm rr --quantum 2

  # export JSON for further analysis
  python3 -m ossim program.txt --algorithm srtf --format json -o result.json

  # deadlock: detect and recover automatically
  python3 -m ossim examples/deadlock.txt

  # deadlock: avoid it entirely with Banker's algorithm
  python3 -m ossim examples/banker.txt --avoidance banker

DEADLOCK HANDLING
  Detection  a wait-for analysis finds processes that can never progress.
  Avoidance  --avoidance banker refuses requests that would be unsafe.
  Recovery   on a deadlock: terminate (default), preempt, or manual.

WORKLOAD FILE
  resources R1=2, R2=1                  # optional instance counts (default 1)
  program writer priority=1 arrival=0   # start a process (priority/arrival optional)
      cpu(6)                            # use the CPU for 6 units
      io(2)                             # block on I/O for 2 units
      resource(1, allocate)             # acquire one instance of R1
      resource(1, release)              # release it
      end
  Bare forms cpu(n)/wait(n) and aliases acquire(r)/release(r) are accepted.

EXIT CODES
  0 success | 1 no workload given | 2 file could not be parsed | 3 run ended early

TIP
  Run 'python3 -m ossim help <algorithm>' for a worked example of one policy,
  e.g.  python3 -m ossim help rr
"""


def algorithm_help(name: str) -> str:
    """Detailed, example-driven help for a single algorithm."""
    sched = build(name)
    notes = ALGORITHM_NOTES[name]
    kind = _scheduler_kind(sched)
    if notes["options"]:
        options = "\n".join(f"                {opt}" for opt in notes["options"])
    else:
        options = "                none"
    return f"""\
{sched.display} ({name})
{"=" * (len(sched.display) + len(name) + 3)}

What it does : {sched.description}
Kind         : {kind}
Ready order  : {notes['order']}
Options      : {options.strip()}
Best for     : {notes['best_for']}

Example
  $ {notes['example']}
  $ python3 -m ossim examples/timesharing.txt -a {name}

Run 'python3 -m ossim help' to see every command and algorithm.
"""


HELP_TOPICS = ORDER


def print_help(topic: Optional[str]) -> int:
    """Print general help, or per-algorithm help when a topic is given."""
    if topic is None or topic.lower() in ("all", "help"):
        print(general_help())
        return 0
    key = topic.lower()
    if key in REGISTRY:
        print(algorithm_help(key))
        return 0
    print(f"error: unknown help topic '{topic}'", file=sys.stderr)
    print("Available topics: " + ", ".join(HELP_TOPICS), file=sys.stderr)
    print("Run 'python3 -m ossim help' for the full guide.", file=sys.stderr)
    return 2


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ossim",
        description=(
            "Simulate CPU scheduling, resource allocation and deadlock "
            "handling using a fast, deterministic virtual clock."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  ossim program.txt\n"
            "  ossim program.txt --algorithm rr --quantum 2\n"
            "  ossim program.txt --all\n"
            "  ossim program.txt -a sjf --format json -o results.json\n"
            "  ossim examples/deadlock.txt --deadlock manual\n"
            "  ossim help                 the full guide\n"
            "  ossim help rr              a worked example of one algorithm\n"
        ),
    )
    parser.add_argument(
        "workload", nargs="?",
        help="program definition file to run (or 'help' for the full guide)",
    )
    parser.add_argument(
        "-a", "--algorithm", choices=sorted(REGISTRY),
        help="scheduling algorithm (omit to choose interactively)",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="run every algorithm and print a comparison table",
    )
    parser.add_argument(
        "-q", "--quantum", type=float, default=4.0,
        help="time quantum for Round Robin (default: 4)",
    )
    parser.add_argument(
        "--deadlock", choices=["terminate", "preempt", "manual"], default="terminate",
        help="how to recover from a deadlock (default: terminate)",
    )
    parser.add_argument(
        "--victim", choices=["resources", "priority", "progress"], default="resources",
        help="how to pick the victim when auto-resolving (default: resources)",
    )
    parser.add_argument(
        "--avoidance", choices=["none", "banker"], default="none",
        help="optional deadlock avoidance (default: none)",
    )
    parser.add_argument(
        "-f", "--format", choices=["text", "json", "csv"], default="text",
        help="report format (default: text)",
    )
    parser.add_argument(
        "-o", "--output", help="write the report to this file instead of stdout",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress progress messages")
    parser.add_argument(
        "--list-algorithms", action="store_true", help="list algorithms and exit",
    )
    parser.add_argument("--version", action="version", version=f"ossim {__version__}")
    return parser


def _interactive_choice(stdin) -> Optional[str]:
    """Prompt the user for an algorithm when none was given on the CLI."""
    if not stdin.isatty():
        return None
    print("Choose a scheduling algorithm:")
    for i, name in enumerate(ORDER, start=1):
        print(f"  {i}. {display_name(name)}")
    print("  (press Enter for FCFS)")
    raw = input("Enter choice [1-7]: ").strip()
    if not raw:
        return "fcfs"
    try:
        idx = int(raw) - 1
    except ValueError:
        print("Unrecognised choice, defaulting to FCFS.")
        return "fcfs"
    if 0 <= idx < len(ORDER):
        return ORDER[idx]
    print("Out of range, defaulting to FCFS.")
    return "fcfs"


def _load(path: Optional[str], parser: argparse.ArgumentParser,
          quiet: bool) -> Tuple[Optional[Program], int]:
    """Load and validate a workload file. Returns ``(program, exit_code)``."""
    if not path:
        parser.print_help()
        return None, 1
    try:
        program = parse_file(path)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None, 2
    warnings = program.validate()
    if warnings and not quiet:
        for warning in warnings:
            print(f"warning: {warning}", file=sys.stderr)
    return program, 0


def _emit(text: str, output: Optional[str]) -> None:
    if output:
        with open(output, "w", encoding="utf-8") as handle:
            handle.write(text)
            if not text.endswith("\n"):
                handle.write("\n")
        print(f"report written to {output}")
    else:
        print(text)


def main(argv: Optional[List[str]] = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)

    # ``ossim help [algorithm]`` or ``ossim guide`` / ``the full guide``
    if raw and (raw[0].lower() in ("help", "guide") or "guide" in " ".join(raw).lower()):
        topic = raw[1] if len(raw) > 1 and raw[0].lower() in ("help", "guide") else None
        return print_help(topic)

    parser = build_arg_parser()
    args = parser.parse_args(raw)

    if args.list_algorithms:
        print("Available scheduling algorithms:")
        for name in ORDER:
            print(f"  {name:<12} {display_name(name)}")
        return 0

    program, code = _load(args.workload, parser, args.quiet)
    if program is None:
        return code

    config = SimConfig(
        deadlock_policy=args.deadlock,
        victim_policy=args.victim,
        avoidance=None if args.avoidance == "none" else args.avoidance,
        interactive=(args.deadlock == "manual" and sys.stdin.isatty()),
        verbose=not args.quiet,
    )

    # ---- comparison mode ------------------------------------------------ #
    if args.all:
        from . import simulate

        runs: Dict[str, Dict[str, float]] = {}
        sims = {}
        for name in ORDER:
            sim = simulate(program, algorithm=name, quantum=args.quantum, config=config)
            runs[name] = sim.metrics()
            sims[name] = sim
        names = {n: display_name(n) for n in ORDER}
        if args.format == "json":
            payload = {
                "workload": program.source,
                "comparison": runs,
                "runs": {n: to_dict(sims[n], names[n], program.source) for n in ORDER},
            }
            import json as _json

            _emit(_json.dumps(payload, indent=2), args.output)
        elif args.format == "csv":
            _emit(to_csv(sims[ORDER[0]]), args.output)  # primary algorithm's detail
        else:
            header = f"Algorithm comparison for {program.source}"
            text = header + "\n" + "=" * len(header) + "\n" + comparison_table(runs, names)
            _emit(text, args.output)
        return 0

    # ---- single-algorithm mode ----------------------------------------- #
    algorithm = args.algorithm
    quantum = args.quantum
    if algorithm is None:
        chosen = _interactive_choice(sys.stdin)
        algorithm = chosen or "fcfs"
    if algorithm == "rr" and quantum <= 0:
        quantum = 4.0

    from . import simulate

    sim = simulate(program, algorithm=algorithm, quantum=quantum, config=config)

    if args.format == "json":
        _emit(to_json(sim, display_name(algorithm), program.source), args.output)
    elif args.format == "csv":
        _emit(to_csv(sim), args.output)
    else:
        _emit(format_report(sim, display_name(algorithm), program.source), args.output)
    return 0 if not sim.aborted else 3


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
