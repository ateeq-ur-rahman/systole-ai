from __future__ import annotations

import sys

from app.logging_config import configure_logging


def test_configure_logging_works_normally_with_a_real_stderr(tmp_path):
    """Baseline: this is how `python run.py` always behaves in a normal
    terminal -- sys.stderr is a real stream."""
    configure_logging(str(tmp_path / "logs"))
    assert (tmp_path / "logs" / "systole.log").exists()


def test_configure_logging_does_not_crash_when_stderr_is_none(tmp_path, monkeypatch):
    """Regression test for a real crash: in a PyInstaller --noconsole
    build, Windows attaches no console to the process, so sys.stderr
    (along with stdout/stdin) is literally None -- not a closed or
    broken stream, the attribute itself is None. loguru.add(None) used
    to raise `TypeError: Cannot log to objects of type 'NoneType'`
    immediately on startup, crashing the entire background service
    before it ever got the chance to open its HTTP port. This is exactly
    what happened in the real, built .msi the first time anyone actually
    ran it -- entirely invisible in `python run.py` since a normal
    terminal always has a real stderr."""
    monkeypatch.setattr(sys, "stderr", None)

    # Must not raise.
    configure_logging(str(tmp_path / "logs"))

    # The file-based sink -- the one that actually matters when there's
    # no console to read stderr from anyway -- must still work.
    assert (tmp_path / "logs" / "systole.log").exists()


def test_configure_logging_does_not_crash_when_stdout_is_also_none(tmp_path, monkeypatch):
    """Same PyInstaller --noconsole condition also sets stdout to None;
    configure_logging itself only touches stderr directly, but this
    guards against any accidental future stdout usage in the same
    function regressing this fix."""
    monkeypatch.setattr(sys, "stderr", None)
    monkeypatch.setattr(sys, "stdout", None)

    configure_logging(str(tmp_path / "logs"))

    assert (tmp_path / "logs" / "systole.log").exists()
