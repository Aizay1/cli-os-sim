# CLI OS Simulator

A fast, deterministic **operating-systems simulator** written in Python.
It models how an OS schedules processes on a CPU, how processes share finite
resources, and how the kernel detects and recovers from **deadlocks**.
The command-line tool uses only the standard library; the optional GUI needs
`customtkinter` (installed automatically on first launch, or via `pip`).

![Python](https://img.shields.io/badge/python-3.8%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-32%20passing-brightgreen)

---

## Why it is useful

Whether you are a **student** revising for an OS exam or an **engineer**
comparing scheduling policies, this tool lets you describe a workload in a
small text file and immediately see the consequences:

- Which process runs when (an ASCII **Gantt chart**).
- Turnaround / waiting / response time for every process.
- What happens when processes fight over resources.
- Whether a policy avoids, detects, or recovers from deadlock.

Everything runs on a **virtual clock**, so a simulation that models "10 seconds"
of work finishes instantly and produces the **same result every time**.

---

## Table of contents

1. [Quick start](#quick-start)
2. [Getting help](#getting-help)
3. [The workload file](#the-workload-file)
4. [Scheduling algorithms](#scheduling-algorithms)
5. [Resources and deadlocks](#resources-and-deadlocks)
6. [Command-line reference](#command-line-reference)
7. [Understanding the output](#understanding-the-output)
8. [Using it from Python](#using-it-from-python)
9. [Project structure](#project-structure)
10. [Development and tests](#development-and-tests)
11. [Design notes and assumptions](#design-notes-and-assumptions)

---

## Quick start

**Requirements:** Python 3.8 or newer. No virtual environment is required.

### Install (recommended)

From the cloned repo this puts `ossim` and `ossim-ui` on your PATH:

```bash
python3 -m pip install --user .
```

If pip refuses because the environment is "externally managed" (Arch, recent
Debian/Ubuntu):

```bash
python3 -m pip install --user --break-system-packages .
```

Make sure `~/.local/bin` is on your `PATH`. Then:

```bash
ossim program.txt --algorithm sjf
ossim examples/timesharing.txt --all
ossim-ui
```

The GUI also needs Tk (`tkinter`). If Python cannot import `tkinter`:

```text
Arch:    sudo pacman -S tk
Debian:  sudo apt install python3-tk
Fedora:  sudo dnf install python3-tkinter
```

### Run from the repo without installing the package

The CLI needs nothing extra:

```bash
python3 -m ossim program.txt
python3 -m ossim program.txt --algorithm sjf
python3 -m ossim examples/timesharing.txt --all
python3 ps-runner.py program.txt
```

The GUI launcher installs `customtkinter` into your user site on first run if
it is missing:

```bash
python3 ossim-ui.py
# or
python3 -m ossim.ui
```

The graphical interface includes full parity with the CLI:
- **Built-in Workload Editor**: Open, create, edit, and save workload files (`program.txt`), with instant syntax validation and one-click example loaders.
- **Algorithm & Quantum Control**: Select from all 7 scheduling policies (FCFS, SJF, SRTF, RR, Priority, Priority Preemptive, HRRN) and tune Round Robin time quantum.
- **Deadlock Management**: Configure deadlock avoidance (Banker's Algorithm), recovery policies (`terminate`, `preempt`, `manual`), and victim selection rules (`resources`, `priority`, `progress`).
- **Side-by-side Comparison (`--all`)**: Compare all algorithms simultaneously with a single click.
- **Report Export**: Save simulation results to formatted Text, JSON, or CSV files.
- **Integrated OS Documentation**: Browse algorithm guides and workload grammar reference directly inside the GUI.

See the full option list with `python3 -m ossim --help`.

---

## Getting help

The tool ships with a built-in guide, so you never have to leave the terminal:

```bash
# The complete guide: every command, option and algorithm with examples
python3 -m ossim help

# A focused, worked example for one scheduling algorithm
python3 -m ossim help rr
python3 -m ossim help srtf
python3 -m ossim help hrrn

# Short lists
python3 -m ossim --list-algorithms     # just the algorithm names
python3 -m ossim --help                # short list of options
```

`python3 -m ossim help <algorithm>` accepts any of the names below and prints
what the policy does, whether it preempts, how it orders the ready queue, its
relevant options (e.g. `--quantum` for Round Robin), when to use it, and
copy-pasteable example commands.

| Algorithm | `help` command |
| --- | --- |
| First-Come, First-Served | `python3 -m ossim help fcfs` |
| Shortest Job First | `python3 -m ossim help sjf` |
| Shortest Remaining Time First | `python3 -m ossim help srtf` |
| Round Robin | `python3 -m ossim help rr` |
| Priority (non-preemptive) | `python3 -m ossim help priority` |
| Priority (preemptive) | `python3 -m ossim help priority-p` |
| Highest Response Ratio Next | `python3 -m ossim help hrrn` |

The same guide is available through the legacy entry point, e.g.
`python3 ps-runner.py help rr`.

---

## The workload file

A workload is a plain-text file describing the processes you want to simulate.
Blank lines and `#` comments are ignored.

```text
# Optional: declare how many instances of each resource exist (default = 1).
resources R1=1, R2=2

# Each process has an optional priority (lower = more important) and arrival time.
program writer priority=1 arrival=0
    cpu(6)                  # use the CPU for 6 units of time
    io(2)                   # block on I/O for 2 units (CPU can run someone else)
    resource(1, allocate)   # acquire one instance of R1
    cpu(2)
    resource(1, release)    # give R1 back
    end
```

### Instructions

| Instruction | Meaning |
| --- | --- |
| `cpu(n)` or `wait(n)` | Spend `n` units of CPU time. |
| `io(n)` | Block for `n` units on I/O; the CPU is free for other processes. |
| `resource(r, allocate)` | Acquire one instance of resource `R<r>`. |
| `resource(r, release)` | Release one instance of resource `R<r>`. |
| `acquire(r)` / `release(r)` | Shorter aliases for the two instructions above. |
| `end` | Terminate the process and release everything it still holds. |

A process that runs out of instructions is terminated automatically, so a
trailing `end` is optional.

### Header lines

| Header | Meaning |
| --- | --- |
| `resources R1=2, R2=1` | Declares resource instances (default is 1 per resource). |
| `program <name> priority=<p> arrival=<t>` | Starts a process block. `priority` and `arrival` are optional. |

Resource identifiers accept `1`, `R1` or `r1`. Unknown resources are created
automatically with a single instance the first time they are used.

---

## Scheduling algorithms

| Flag value | Algorithm | Preemptive | Notes |
| --- | --- | --- | --- |
| `fcfs` | First-Come, First-Served | No | Runs processes in arrival order. |
| `sjf` | Shortest Job First | No | Uses the process's total CPU demand. |
| `srtf` | Shortest Remaining Time First | Yes | Preemptive SJF; minimises average waiting time. |
| `rr` | Round Robin | Quantum-based | Time-slices every ready process. Set the slice with `--quantum`. |
| `priority` | Priority | No | Lower `priority` number wins. |
| `priority-p` | Priority (preemptive) | Yes | A higher-priority arrival takes the CPU immediately. |
| `hrrn` | Highest Response Ratio Next | No | Balances burst length with waiting time; avoids starvation. |

List them at any time with:

```bash
python3 -m ossim --list-algorithms
```

> **Tip:** `--all` runs every algorithm on the same workload and prints a
> side-by-side comparison so you can see the trade-offs (turnaround vs.
> responsiveness vs. context switches).

---

## Resources and deadlocks

Resources are modelled as **counting semaphores**: each resource has a fixed
number of identical instances. A process that requests a busy resource is
**blocked** and placed in a FIFO queue for that resource; it wakes up
automatically when an instance becomes free.

The simulator offers three levels of deadlock handling:

1. **Detection** — a wait-for analysis (the classic reduction algorithm, which
   is correct for single- *and* multi-instance resources) identifies the exact
   set of processes that can never make progress.

2. **Avoidance (optional)** — enable Banker's algorithm with
   `--avoidance banker`. A request that would move the system into an *unsafe*
   state is refused, so the deadlock never happens in the first place.

3. **Recovery** — when a deadlock is detected:
   - `--deadlock terminate` *(default)* terminates a victim process and releases
     its resources.
   - `--deadlock preempt` force-releases a contended resource instead.
   - `--deadlock manual` asks you which resource to release.

   The victim is chosen by `--victim {resources,priority,progress}`.

**Try it:**

```bash
# A genuine circular-wait deadlock, recovered automatically
python3 -m ossim examples/deadlock.txt

# The same workload, but avoid the deadlock entirely
python3 -m ossim examples/banker.txt --avoidance banker
```

---

## Command-line reference

```text
usage: ossim [workload] [options]
       ossim help [algorithm]
```

| Option / Command | Description |
| --- | --- |
| `workload` | Path to the workload file. |
| `help [algorithm]` | Print the full guide, or a worked example for one algorithm. |
| `-a`, `--algorithm NAME` | Scheduling algorithm (omit to choose interactively). |
| `--all` | Run every algorithm and compare them. |
| `-q`, `--quantum N` | Time quantum for Round Robin (default `4`). |
| `--deadlock {terminate,preempt,manual}` | Deadlock recovery policy (default `terminate`). |
| `--victim {resources,priority,progress}` | How the victim is chosen (default `resources`). |
| `--avoidance {none,banker}` | Optional deadlock avoidance (default `none`). |
| `-f`, `--format {text,json,csv}` | Report format (default `text`). |
| `-o`, `--output FILE` | Write the report to a file instead of the screen. |
| `--quiet` | Suppress warnings and progress messages. |
| `--list-algorithms` | Print the available algorithms and exit. |
| `--version` | Print the version and exit. |

**Exit codes:** `0` success, `1` no workload given, `2` workload could not be
parsed (or unknown `help` topic), `3` the run ended early (unrecoverable
deadlock or safety limit).

### Examples

```bash
# The built-in guide
python3 -m ossim help
python3 -m ossim help rr

# Round Robin with a 2-unit quantum
python3 -m ossim examples/timesharing.txt -a rr -q 2

# Export the full result as JSON for further analysis
python3 -m ossim program.txt -a srtf -f json -o result.json

# Get just the per-process table as CSV
python3 -m ossim program.txt -f csv -o processes.csv

# Recover from a deadlock by hand
python3 -m ossim examples/deadlock.txt --deadlock manual
```

---

## Understanding the output

Running `python3 -m ossim program.txt -a fcfs` produces a report like this
(abridged):

```text
====================================
CLI OS SIMULATOR - SIMULATION REPORT
====================================
Workload : program.txt
Scheduler: First-Come, First-Served

Per-process results
+---------+------+---------+-------+--------+-------+-----+------------+---------+----------+
| Process | Prio | Arrival | Start | Finish | Burst | I/O | Turnaround | Waiting | Response |
+---------+------+---------+-------+--------+-------+-----+------------+---------+----------+
| P1      | 0    | 0       | 0     | 2      | 2     | 0   | 2          | 0       | 0        |
| P2      | 0    | 0       | 2     | 4      | 2     | 0   | 4          | 2       | 2        |
+---------+------+---------+-------+--------+-------+-----+------------+---------+----------+

CPU timeline
+------------------+------------------+
|        P1        |        P2        |
+------------------+------------------+
time: 0                  2  end=4

Aggregate metrics
  processes ............ 4
  completed ............ 4
  makespan ............. 8 u
  avg turnaround ....... 5.000 u
  avg waiting .......... 3.000 u
  avg response ......... 3.000 u
  cpu utilization ...... 100.0%
  throughput ........... 0.5000 proc/u
  context switches ..... 3
  deadlocks detected ... 0
  force releases ....... 0
```

### What the metrics mean

| Metric | Definition |
| --- | --- |
| **Turnaround** | Finish time − arrival time. |
| **Waiting** | Total time spent in the ready queue. |
| **Response** | First time on the CPU − arrival time. |
| **Makespan** | Wall-clock length of the whole run (`u` = time units). |
| **CPU utilisation** | Busy CPU time ÷ makespan. |
| **Throughput** | Completed processes ÷ makespan. |
| **Context switches** | Times the CPU changed hands. |

The **event trace** at the end of the report is a timestamped log of every
scheduling decision and resource operation, which is invaluable for debugging
a workload.

---

## Using it from Python

```python
from ossim import parse_file, simulate

program = parse_file("examples/timesharing.txt")
sim = simulate(program, algorithm="rr", quantum=2)

print(sim.metrics()["avg_turnaround"])
for row in sim.process_rows():
    print(row["name"], row["finish"])
```

Other helpers:

- `simulate(program, algorithm, quantum)` — run one algorithm.
- `simulate_all(program)` — run every algorithm.
- `compare(program)` — return each algorithm's metrics for comparison.

The reporting helpers in `ossim.report` (`to_json`, `to_csv`, `format_report`)
let you build your own output.

---

## Project structure

```text
cli-os-sim/
├── ossim/                 # the simulator package
│   ├── models.py          # Process, Command, Event, state enums
│   ├── parser.py          # workload file parser + validation
│   ├── resources.py       # resource manager, deadlock detection, Banker's
│   ├── schedulers.py      # all scheduling policies
│   ├── engine.py          # discrete-event simulation engine
│   ├── report.py          # tables, Gantt chart, JSON/CSV export
│   ├── cli.py             # argparse command-line interface
│   └── __main__.py        # enables `python -m ossim`
├── examples/
│   ├── deadlock.txt       # circular wait that deadlocks
│   ├── banker.txt         # workload where Banker's avoidance prevents deadlock
│   └── timesharing.txt    # arrivals, priorities and I/O for comparing policies
├── tests/                 # pytest suite (32 tests)
├── program.txt            # small bundled sample workload
├── ps-runner.py           # backwards-compatible CLI entry point
├── ossim-ui.py            # GUI launcher (no venv needed)
├── requirements.txt       # GUI dependency (customtkinter)
├── pyproject.toml         # packaging + console-script definition
└── README.md
```

---

## Development and tests

The test suite uses [pytest](https://docs.pytest.org/). No project virtual
environment is required:

```bash
python3 -m pip install --user pytest
python3 -m pytest

# After `pip install --user .` the commands are also available:
ossim examples/timesharing.txt --all
ossim-ui
```

Tests cover the parser, every scheduler, the discrete-event engine (including
I/O overlap, arrival times, deadlock detection and Banker's avoidance) and the
report/export layer.

---

## Design notes and assumptions

- **Virtual, discrete-event clock.** Time only moves when the simulation says
  so. There is no `time.sleep`, so runs are instant and bit-for-bit
  reproducible.
- **Single CPU.** Exactly one process runs at a time; others are ready or
  blocked. This is the standard model for teaching scheduling.
- **Quantum limits CPU work only.** In Round Robin, zero-time instructions
  (`acquire`, `release`, `end`) are always executed when reached; the quantum
  only bounds `cpu(n)` bursts.
- **Concurrency is modelled through scheduling.** Because there is a single
  CPU, a process that never blocks or gets preempted runs to completion. To
  create the interleaving that produces a classic deadlock, give processes an
  `io(n)` (or use a preemptive policy) — see `examples/deadlock.txt`.
- **Banker's avoids using each program's maximum claim**, derived from how many
  instances of a resource the program acquires in total. This is an accurate
  upper bound for the included examples; a program that repeatedly acquires and
  releases the same resource is a deliberately out-of-scope edge case.
- **Deterministic ordering.** Ties are broken by arrival time and then by the
  order processes appear in the file, so results never depend on the
  interpreter's hash seed.

---

## License

Released for education under the MIT License. Fork it, extend it, and use it
in your OS course — contributions and feedback are welcome.

Originally a small teaching script; now a small but professional simulator.
