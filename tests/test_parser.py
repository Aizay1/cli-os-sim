import pytest

from ossim import ParseError, parse_text
from ossim.parser import resource_id


def test_parses_programs_resources_and_attributes():
    program = parse_text(
        """
        resources R1=2, R2=1

        program P1 priority=3 arrival=2
            cpu(4)
            resource(1, allocate)
            resource(R2, release)
            end
        """
    )
    assert program.resources == {1: 2, 2: 1}
    proc = program.processes[0]
    assert (proc.name, proc.priority, proc.arrival) == ("P1", 3, 2)
    assert [c.type.value for c in proc.commands] == ["cpu", "acquire", "release", "end"]
    assert [c.value for c in proc.commands] == [4, 1, 2, 0]


def test_resource_id_variants_are_stable():
    assert resource_id("R5") == 5
    assert resource_id("r5") == 5
    assert resource_id("5") == 5
    assert resource_id("printer") == resource_id("Printer")


def test_legacy_and_short_forms():
    program = parse_text("program P1\nwait(2)\nacquire(3)\nrelease(3)\nend")
    assert [c.type.value for c in program.processes[0].commands] == [
        "cpu", "acquire", "release", "end",
    ]


def test_command_before_program_is_rejected():
    with pytest.raises(ParseError):
        parse_text("cpu(1)")


def test_unknown_instruction_is_rejected():
    with pytest.raises(ParseError):
        parse_text("program P1\nfrobnicate(3)")


def test_validate_flags_unbalanced_release():
    program = parse_text("program P1\nrelease(2)\nend")
    assert any("without holding" in w for w in program.validate())
