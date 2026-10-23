"""Human-readable and machine-readable reporting.

Everything the simulator produces - the per-process table, aggregate metrics,
the ASCII Gantt chart, the event trace - is rendered here. Reports can also be
exported as JSON or CSV for further analysis.
"""
from __future__ import annotations

import csv
import io
import json
from typing import Dict, List, Optional, Sequence, Union

from .engine import Simulation
from .models import Segment

Cell = Union[str, int, float, None]


# ---------------------------------------------------------------------- #
# Low-level table helper
# ---------------------------------------------------------------------- #
def table(headers: Sequence[str], rows: Sequence[Sequence[Cell]]) -> str:
    """Render a bordered ASCII table."""
    def fmt(value: Cell) -> str:
        if value is None:
            return "-"
        if isinstance(value, float):
            return f"{value:g}"
        return str(value)

    body = [[fmt(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    out.append("|" + "|".join(f" {h:<{widths[i]}} " for i, h in enumerate(headers)) + "|")
    out.append(sep)
    for row in body:
        out.append("|" + "|".join(f" {c:<{widths[i]}} " for i, c in enumerate(row)) + "|")
    out.append(sep)
    return "\n".join(out)


# ---------------------------------------------------------------------- #
# Gantt chart
# ---------------------------------------------------------------------- #
def render_gantt(timeline: List[Segment], width: int = 72) -> str:
    """Draw a proportional ASCII Gantt chart of CPU usage."""
    if not timeline:
        return "(no CPU activity recorded)"

    end = timeline[-1].end
    if end <= 0:
        return "(zero-length run)"

    # Allocate character cells proportional to each slice's duration.
    cells: List[int] = []
    for seg in timeline:
        cells.append(max(1, int(round(seg.duration / end * width))))

    # Trim or pad so the bar is exactly `width` characters wide.
    while sum(cells) > width:
        idx = max(range(len(cells)), key=lambda i: cells[i])
        if cells[idx] <= 1:
            break
        cells[idx] -= 1
    while sum(cells) < width:
        idx = max(range(len(cells)), key=lambda i: cells[i])
        cells[idx] += 1

    blocks = []
    labels = []
    for seg, c in zip(timeline, cells):
        label = seg.label[:c] if len(seg.label) > c else seg.label.center(c)
        blocks.append("|" + label)
        labels.append(c)
    top = "+" + "+".join("-" * c for c in labels) + "+"
    mid = "".join(blocks) + "|"
    bot = "+" + "+".join("-" * c for c in labels) + "+"

    # Time axis underneath.
    axis = [" "] * (width + 1)
    pos = 0
    for seg, c in zip(timeline, labels):
        tick = f"{seg.start:g}"
        for i, ch in enumerate(tick):
            if pos + i <= width:
                axis[pos + i] = ch
        pos += c + 1  # account for the '|' separators
    axis_line = "".join(axis).rstrip()
    end_label = f"{end:g}"
    tail = axis_line + "  end=" + end_label

    return "\n".join([top, mid, bot, "time: " + tail])


# ---------------------------------------------------------------------- #
# Full report
# ---------------------------------------------------------------------- #
def format_metrics(metrics: Dict[str, float]) -> str:
    lines = [
        f"  processes ............ {metrics['processes']:g}",
        f"  completed ............ {metrics['completed']:g}",
        f"  makespan ............. {metrics['makespan']:g} u",
        f"  avg turnaround ....... {metrics['avg_turnaround']:.3f} u",
        f"  avg waiting .......... {metrics['avg_waiting']:.3f} u",
        f"  avg response ......... {metrics['avg_response']:.3f} u",
        f"  cpu utilization ...... {metrics['cpu_utilization'] * 100:.1f}%",
        f"  throughput ........... {metrics['throughput']:.4f} proc/u",
        f"  context switches ..... {metrics['context_switches']:g}",
        f"  deadlocks detected ... {metrics['deadlocks']:g}",
        f"  force releases ....... {metrics['force_releases']:g}",
    ]
    return "\n".join(lines)


def format_report(sim: Simulation, algorithm: str = "", source: str = "") -> str:
    """Produce the complete textual report for a finished simulation."""
    out: List[str] = []
    title = "CLI OS SIMULATOR - SIMULATION REPORT"
    out.append("=" * len(title))
    out.append(title)
    out.append("=" * len(title))
    if source:
        out.append(f"Workload : {source}")
    if algorithm:
        out.append(f"Scheduler: {algorithm}")
    out.append("")

    out.append("Per-process results")
    rows = []
    for row in sim.process_rows():
        rows.append([
            row["name"],
            row["priority"],
            row["arrival"],
            row["start"],
            row["finish"],
            row["burst"],
            row["io"],
            row["turnaround"],
            row["waiting"],
            row["response"],
        ])
    out.append(table(
        ["Process", "Prio", "Arrival", "Start", "Finish", "Burst", "I/O",
         "Turnaround", "Waiting", "Response"],
        rows,
    ))
    out.append("")

    out.append("CPU timeline")
    out.append(render_gantt(sim.timeline, width=72))
    out.append("")

    out.append("Aggregate metrics")
    out.append(format_metrics(sim.metrics()))
    out.append("")

    if sim.force_released:
        out.append("Force-released resources")
        for rid, owner in sim.force_released:
            out.append(f"  R{rid} taken from {owner}")
        out.append("")

    out.append("Event trace")
    trace_rows = [
        [f"{e.time:g}", e.process, e.action,
         f"R{e.resource}" if e.resource is not None else "",
         e.detail or ""]
        for e in sim.events
    ]
    out.append(table(["Time", "Process", "Action", "Resource", "Detail"], trace_rows))

    if sim.aborted:
        out.append("")
        out.append("!! Simulation ended early (deadlock or step budget).")
    return "\n".join(out)


# ---------------------------------------------------------------------- #
# Machine-readable exports
# ---------------------------------------------------------------------- #
def to_dict(sim: Simulation, algorithm: str = "", source: str = "") -> dict:
    return {
        "workload": source,
        "algorithm": algorithm,
        "metrics": sim.metrics(),
        "processes": sim.process_rows(),
        "timeline": [
            {"start": s.start, "end": s.end, "label": s.label} for s in sim.timeline
        ],
        "force_released": [
            {"resource": f"R{rid}", "owner": owner} for rid, owner in sim.force_released
        ],
        "events": [e.as_dict() for e in sim.events],
    }


def to_json(sim: Simulation, algorithm: str = "", source: str = "",
            indent: int = 2) -> str:
    return json.dumps(to_dict(sim, algorithm, source), indent=indent)


def to_csv(sim: Simulation) -> str:
    """Per-process results as CSV."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "process", "priority", "arrival", "start", "finish",
        "burst", "io", "turnaround", "waiting", "response", "state",
    ])
    for row in sim.process_rows():
        writer.writerow([
            row["name"], row["priority"], row["arrival"], row["start"],
            row["finish"], row["burst"], row["io"], row["turnaround"],
            row["waiting"], row["response"], row["state"],
        ])
    return buffer.getvalue()


def comparison_table(results: Dict[str, Dict[str, float]],
                     display_names: Optional[Dict[str, str]] = None) -> str:
    """Compare several algorithms side by side."""
    if not results:
        return "(nothing to compare)"
    names = list(results.keys())
    metric_keys = [
        ("avg_turnaround", "Avg turnaround"),
        ("avg_waiting", "Avg waiting"),
        ("avg_response", "Avg response"),
        ("makespan", "Makespan"),
        ("cpu_utilization", "CPU util"),
        ("context_switches", "Ctx switches"),
        ("throughput", "Throughput"),
        ("deadlocks", "Deadlocks"),
    ]
    headers = ["Metric"] + [display_names.get(n, n) if display_names else n for n in names]
    rows = []
    for key, label in metric_keys:
        row = [label]
        for name in names:
            value = results[name].get(key, 0.0)
            if key == "cpu_utilization":
                row.append(f"{value * 100:.1f}%")
            elif key == "throughput":
                row.append(f"{value:.4f}")
            elif key in ("context_switches", "deadlocks"):
                row.append(f"{value:g}")
            else:
                row.append(f"{value:.3f}")
        rows.append(row)
    return table(headers, rows)
