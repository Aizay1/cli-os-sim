from ossim.cli import main


def write(tmp_path, text):
    path = tmp_path / "workload.txt"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_list_algorithms(capsys):
    assert main(["--list-algorithms"]) == 0
    out = capsys.readouterr().out
    assert "fcfs" in out
    assert "Round Robin" in out


def test_single_run_text_report(tmp_path, capsys):
    path = write(tmp_path, "program P1\ncpu(2)\nend")
    assert main([path, "-a", "fcfs"]) == 0
    assert "SIMULATION REPORT" in capsys.readouterr().out


def test_single_run_json_to_file(tmp_path, capsys):
    path = write(tmp_path, "program P1\ncpu(2)\nend")
    out = tmp_path / "result.json"
    assert main([path, "-a", "fcfs", "-f", "json", "-o", str(out)]) == 0
    assert '"metrics"' in out.read_text(encoding="utf-8")


def test_compare_all(tmp_path, capsys):
    path = write(tmp_path, "program P1\ncpu(2)\nend\nprogram P2\ncpu(1)\nend")
    assert main([path, "--all"]) == 0
    assert "comparison" in capsys.readouterr().out.lower()


def test_missing_workload_prints_help(capsys):
    assert main([]) == 1
    assert "usage" in capsys.readouterr().out.lower()


def test_bad_file_reports_error(tmp_path, capsys):
    assert main([str(tmp_path / "nope.txt")]) == 2
    assert "error" in capsys.readouterr().err.lower()


def test_help_shows_guide(capsys):
    assert main(["help"]) == 0
    out = capsys.readouterr().out
    assert "USAGE" in out
    assert "SCHEDULING ALGORITHMS" in out
    assert "Round Robin" in out


def test_help_algorithm_topic(capsys):
    assert main(["help", "rr"]) == 0
    out = capsys.readouterr().out
    assert "Round Robin (rr)" in out
    assert "--quantum" in out
    assert "quantum-based" in out


def test_help_unknown_topic(capsys):
    assert main(["help", "bogus"]) == 2
    assert "unknown help topic" in capsys.readouterr().err.lower()
