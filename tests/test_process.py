"""A failed command must never become successful-looking output."""

from __future__ import annotations

import sys

import pytest

from filmkit import process


def _python(code: str) -> list[str]:
    return [sys.executable, "-c", code]


def test_a_successful_command_keeps_its_output():
    result = process.run(_python("print('hi')"))
    assert result.ok and result.stdout.strip() == "hi"


def test_a_failing_command_raises_with_the_tool_s_own_words():
    with pytest.raises(process.CommandError) as raised:
        process.run(_python("import sys; sys.stderr.write('boom'); sys.exit(3)"))
    assert "boom" in str(raised.value)
    assert "(3)" in str(raised.value)


def test_check_false_returns_the_failure_instead_of_raising():
    result = process.run(_python("import sys; sys.exit(3)"), check=False)
    assert not result.ok and result.returncode == 3


def test_a_timeout_is_a_result_with_an_exit_code():
    """Whatever the tool managed to say before it hung is usually the reason."""
    result = process.run(_python("import time; time.sleep(5)"), timeout=0.3, check=False)
    assert result.returncode == process.TIMED_OUT
    assert "timed out" in result.stderr


def test_a_timeout_still_fails_the_build_when_checked():
    with pytest.raises(process.CommandError):
        process.run(_python("import time; time.sleep(5)"), timeout=0.3)


def test_a_log_is_written_only_when_there_is_somewhere_to_put_it(tmp_path):
    result = process.run(_python("print('x')"), log_name="job", log_dir=tmp_path / "logs")
    assert result.log_path is not None
    assert "--- stdout ---" in result.log_path.read_text()

    plain = process.run(_python("print('x')"), log_name="job")
    assert plain.log_path is None


def test_env_additions_reach_the_child():
    result = process.run(
        _python("import os; print(os.environ['FILMKIT_TEST'])"), env={"FILMKIT_TEST": "yes"}
    )
    assert result.stdout.strip() == "yes"


def test_cwd_is_honoured(tmp_path):
    result = process.run(_python("import os; print(os.getcwd())"), cwd=tmp_path)
    assert result.stdout.strip().endswith(tmp_path.name)


def test_a_missing_binary_has_no_version():
    assert process.tool_version("a-binary-that-is-not-installed-anywhere") is None
    assert process.which("a-binary-that-is-not-installed-anywhere") is None


def test_a_present_binary_reports_its_first_line(runner):
    runner.stdout = "Python 3.12.0\nextra\n"
    assert process.tool_version(sys.executable, "--version", runner=runner) == "Python 3.12.0"


def test_a_binary_that_says_nothing_is_recorded_as_unknown(runner):
    runner.stdout = "   "
    assert process.tool_version(sys.executable, "--version", runner=runner) is None
