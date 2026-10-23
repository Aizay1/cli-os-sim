"""Parser for ``program`` definition files.

A definition file is a plain-text description of the workload the simulated OS
has to run.  Grammar (blank lines and ``#`` comments are ignored)::

    # optional: declare how many instances of each resource exist
    resources R1=2, R2=1

    program P1 priority=2 arrival=0
        cpu(4)                 # burn 4 units of CPU  (alias: wait(4))
        resource(1, allocate)  # acquire one instance of R1
        io(3)                  # block for 3 units off the CPU
        resource(1, release)   # hand R1 back
        end

The parser is deliberately forgiving but produces precise error messages with
line numbers so the file is easy to fix.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

from .models import CmdType, Command, Process


class ParseError(ValueError):
    """Raised when a program file cannot be parsed."""


@dataclass
class Program:
    """The fully parsed workload."""

    processes: List[Process]
    resources: Dict[int, int] = field(default_factory=dict)
    source: str = "<memory>"

    def validate(self) -> List[str]:
        """Return a list of non-fatal warnings about the workload."""
        warnings: List[str] = []
        seen = set()
        for proc in self.processes:
            if proc.name in seen:
                warnings.append(f"duplicate process name '{proc.name}'")
            seen.add(proc.name)
            if not proc.commands:
                warnings.append(f"process '{proc.name}' has no commands")
            held: Dict[int, int] = {}
            for cmd in proc.commands:
                if cmd.type is CmdType.ACQUIRE:
                    held[cmd.value] = held.get(cmd.value, 0) + 1
                elif cmd.type is CmdType.RELEASE:
                    if held.get(cmd.value, 0) <= 0:
                        warnings.append(
                            f"process '{proc.name}' releases R{cmd.value} "
                            f"without holding a matching instance"
                        )
                    else:
                        held[cmd.value] -= 1
        return warnings


_PROGRAM_RE = re.compile(r"^program\s+(?P<name>\S+)(?P<attrs>.*)$", re.IGNORECASE)
_ATTR_RE = re.compile(r"(?P<key>\w+)\s*=\s*(?P<val>[^\s]+)")
_RESOURCES_RE = re.compile(r"(?P<name>\w+)\s*=\s*(?P<count>\d+)")
_FUNC_RE = re.compile(r"^(?P<fn>\w+)\s*\(\s*(?P<args>[^)]*)\s*\)\s*$", re.IGNORECASE)
_BARE_RE = re.compile(r"^(?P<fn>\w+)\s+(?P<arg>\S+)\s*$", re.IGNORECASE)

_ACQUIRE_WORDS = {"allocate", "acquire", "request", "lock", "take"}
_RELEASE_WORDS = {"release", "free", "unlock", "give"}


def resource_id(token: str) -> int:
    """Normalise a resource reference such as ``R3``, ``r3`` or ``3`` to ``3``."""
    token = token.strip()
    if not token:
        raise ParseError("empty resource identifier")
    if token[0] in "Rr" and token[1:].isdigit():
        return int(token[1:])
    if token.isdigit():
        return int(token)
    # Named resources: map the name to a stable id (>= 1000) so that runs are
    # reproducible regardless of the interpreter's hash seed.
    return 1000 + (sum((i + 1) * ord(ch) for i, ch in enumerate(token.lower())) % 1000)


def _parse_command(fn: str, args: str, line: str) -> Command:
    fn = fn.lower()
    args = args.strip()

    if fn in ("wait", "cpu", "compute", "burst"):
        if not args.isdigit():
            raise ParseError(f"'{line}': cpu/wait needs a numeric duration")
        return Command(CmdType.CPU, int(args), line)

    if fn in ("io", "sleep"):
        if not args.isdigit():
            raise ParseError(f"'{line}': io needs a numeric duration")
        return Command(CmdType.IO, int(args), line)

    if fn == "end":
        return Command(CmdType.END, 0, line)

    if fn == "resource":
        parts = [p.strip() for p in args.split(",")]
        if len(parts) != 2:
            raise ParseError(f"'{line}': expected resource(<id>, allocate|release)")
        rid = resource_id(parts[0])
        op = parts[1].lower()
        if op in _ACQUIRE_WORDS:
            return Command(CmdType.ACQUIRE, rid, line)
        if op in _RELEASE_WORDS:
            return Command(CmdType.RELEASE, rid, line)
        raise ParseError(f"'{line}': unknown resource operation '{parts[1]}'")

    if fn in ("acquire", "lock", "take"):
        return Command(CmdType.ACQUIRE, resource_id(args), line)

    if fn in ("release", "free", "unlock"):
        return Command(CmdType.RELEASE, resource_id(args), line)

    raise ParseError(f"'{line}': unknown instruction '{fn}'")


def parse_text(text: str, source: str = "<string>") -> Program:
    """Parse an in-memory definition file."""
    processes: List[Process] = []
    resources: Dict[int, int] = {}

    current: Process | None = None
    seq = 0

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        # Strip comments and surrounding whitespace.
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue

        program_match = _PROGRAM_RE.match(line)
        if program_match:
            name = program_match.group("name")
            attrs = program_match.group("attrs")
            priority = 0
            arrival = 0.0
            for attr in _ATTR_RE.finditer(attrs):
                key, val = attr.group("key").lower(), attr.group("val")
                if key in ("priority", "prio", "p"):
                    priority = int(float(val))
                elif key in ("arrival", "arrive", "at"):
                    arrival = float(val)
                else:
                    raise ParseError(
                        f"line {lineno}: unknown process attribute '{key}'"
                    )
            current = Process(
                name=name, commands=[], priority=priority, arrival=arrival, seq=seq
            )
            seq += 1
            processes.append(current)
            continue

        if line.lower().startswith("resources"):
            body = line[len("resources"):]
            for token in body.split(","):
                match = _RESOURCES_RE.search(token)
                if not match:
                    raise ParseError(
                        f"line {lineno}: malformed resource declaration '{token.strip()}'"
                    )
                resources[resource_id(match.group("name"))] = int(match.group("count"))
            continue

        # Everything else must be a command inside a program block.
        if current is None:
            raise ParseError(
                f"line {lineno}: '{line}' appears before any 'program' block"
            )

        try:
            func_match = _FUNC_RE.match(line)
            if func_match:
                cmd = _parse_command(func_match.group("fn"), func_match.group("args"), line)
            else:
                bare = _BARE_RE.match(line)
                if bare:
                    cmd = _parse_command(bare.group("fn"), bare.group("arg"), line)
                else:
                    cmd = _parse_command(line, "", line)
        except ParseError as exc:
            raise ParseError(f"line {lineno}: {exc}") from exc
        current.commands.append(cmd)

    if not processes:
        raise ParseError(f"{source}: no 'program' blocks found")

    return Program(processes=processes, resources=resources, source=source)


def parse_file(path: str) -> Program:
    """Parse a definition file from disk."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except FileNotFoundError as exc:
        raise ParseError(f"file not found: {path}") from exc
    return parse_text(text, source=path)
