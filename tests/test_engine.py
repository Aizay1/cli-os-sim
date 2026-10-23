import os

from ossim import parse_text, simulate
from ossim.engine import SimConfig

EXAMPLES = os.path.join(os.path.dirname(__file__), os.pardir, "examples")


def load(name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as handle:
        return parse_text(handle.read(), source=name)


def rows(sim):
    return {row["name"]: row for row in sim.process_rows()}


def test_fcfs_metrics():
    program = parse_text("program P1\ncpu(3)\nend\nprogram P2\ncpu(2)\nend")
    sim = simulate(program, "fcfs")
    result = rows(sim)
    assert result["P1"]["finish"] == 3
    assert result["P2"]["finish"] == 5
    assert sim.metrics()["avg_turnaround"] == 4.0
    assert sim.metrics()["cpu_utilization"] == 1.0


def test_sjf_runs_shortest_first():
    program = parse_text("program P1\ncpu(3)\nend\nprogram P2\ncpu(2)\nend")
    sim = simulate(program, "sjf")
    result = rows(sim)
    assert result["P2"]["finish"] == 2
    assert result["P1"]["finish"] == 5
    assert sim.metrics()["avg_turnaround"] == 3.5


def test_round_robin_time_slices():
    program = parse_text("program P1\ncpu(3)\nend\nprogram P2\ncpu(2)\nend")
    sim = simulate(program, "rr", quantum=1)
    slices = [(s.start, s.end, s.label) for s in sim.timeline]
    assert slices == [
        (0.0, 1.0, "P1"),
        (1.0, 2.0, "P2"),
        (2.0, 3.0, "P1"),
        (3.0, 4.0, "P2"),
        (4.0, 5.0, "P1"),
    ]


def test_io_overlaps_with_cpu():
    program = parse_text(
        """
        program P1
            cpu(2)
            io(3)
            cpu(1)
            end
        program P2
            cpu(5)
            end
        """
    )
    sim = simulate(program, "fcfs")
    result = rows(sim)
    assert result["P1"]["finish"] == 8
    assert result["P2"]["finish"] == 7
    assert result["P1"]["waiting"] == 2


def test_arrival_times_are_respected():
    program = parse_text(
        "program P1 arrival=5\ncpu(2)\nend\nprogram P2 arrival=0\ncpu(1)\nend"
    )
    sim = simulate(program, "fcfs")
    result = rows(sim)
    assert result["P2"]["start"] == 0
    assert result["P1"]["start"] == 5
    # CPU is idle from t=1 to t=5, so utilisation is below 100%.
    assert sim.metrics()["cpu_utilization"] < 1.0


def test_deadlock_is_detected_and_resolved():
    sim = simulate(load("deadlock.txt"), "fcfs", config=SimConfig(verbose=False))
    assert sim.deadlocks >= 1
    assert all(row["finish"] is not None for row in sim.process_rows())
    assert sim.aborted is False


def test_banker_avoidance_prevents_deadlock():
    program = load("banker.txt")
    unsafe = simulate(program, "fcfs", config=SimConfig(verbose=False))
    assert unsafe.deadlocks >= 1

    safe = simulate(
        program, "fcfs", config=SimConfig(avoidance="banker", verbose=False)
    )
    assert safe.deadlocks == 0
    assert all(row["finish"] is not None for row in safe.process_rows())


def test_multi_instance_resource_is_shared():
    program = parse_text(
        """
        resources R1=2
        program P1
            resource(1, allocate)
            cpu(1)
            end
        program P2
            resource(1, allocate)
            cpu(1)
            end
        """
    )
    sim = simulate(program, "fcfs")
    # Both processes can hold R1 at the same time, so neither blocks.
    assert sim.events
    assert all(row["finish"] is not None for row in sim.process_rows())
    assert sim.metrics()["deadlocks"] == 0
