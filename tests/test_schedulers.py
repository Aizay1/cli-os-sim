import pytest

from ossim.models import CmdType, Command, Process
from ossim.schedulers import build


def make(name, burst, arrival=0, seq=0, priority=0):
    return Process(
        name, [Command(CmdType.CPU, burst)], priority=priority,
        arrival=arrival, seq=seq,
    )


def test_fcfs_prefers_earlier_arrival():
    a = make("A", 5, arrival=3)
    b = make("B", 2, arrival=1)
    assert build("fcfs").pick([a, b], 0) is b


def test_sjf_prefers_short_jobs():
    a = make("A", 5)
    b = make("B", 2)
    assert build("sjf").pick([a, b], 0) is b


def test_priority_lower_number_wins():
    a = make("A", 5, priority=4)
    b = make("B", 2, priority=1)
    assert build("priority").pick([a, b], 0) is b


def test_priority_preemptive_is_marked_preemptive():
    assert build("priority-p").preemptive is True
    assert build("priority").preemptive is False


def test_round_robin_is_fifo():
    a = make("A", 5)
    b = make("B", 2)
    assert build("rr").pick([a, b], 0) is a


def test_unknown_algorithm_raises():
    with pytest.raises(ValueError):
        build("does-not-exist")
