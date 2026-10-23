import csv
import io
import json

from ossim import parse_text, simulate
from ossim.report import (
    comparison_table,
    format_report,
    render_gantt,
    table,
    to_csv,
    to_json,
)


def simple_sim():
    program = parse_text("program P1\ncpu(2)\nend\nprogram P2\ncpu(3)\nend")
    return simulate(program, "fcfs")


def test_table_rendering_is_bordered():
    text = table(["A", "B"], [[1, 2], [3, 4]])
    lines = text.splitlines()
    assert lines[0].startswith("+")
    assert "A" in lines[1] and "B" in lines[1]
    assert len(lines) == 6


def test_gantt_includes_labels_and_axis():
    text = render_gantt(simple_sim().timeline)
    assert "P1" in text and "P2" in text
    assert "time:" in text


def test_json_export_roundtrip():
    data = json.loads(to_json(simple_sim(), "FCFS", "memory"))
    assert data["algorithm"] == "FCFS"
    assert data["processes"][0]["name"] == "P1"
    assert data["metrics"]["makespan"] == 5
    assert len(data["timeline"]) == 2


def test_csv_export():
    reader = list(csv.DictReader(io.StringIO(to_csv(simple_sim()))))
    assert [row["process"] for row in reader] == ["P1", "P2"]


def test_full_report_has_sections():
    text = format_report(simple_sim(), "FCFS", "memory")
    for section in ["SIMULATION REPORT", "Per-process results", "CPU timeline",
                    "Aggregate metrics", "Event trace"]:
        assert section in text


def test_comparison_table_has_columns():
    metrics = {
        "fcfs": simple_sim().metrics(),
        "sjf": simple_sim().metrics(),
    }
    text = comparison_table(metrics, {"fcfs": "FCFS", "sjf": "SJF"})
    assert "Avg turnaround" in text
    assert "FCFS" in text and "SJF" in text
