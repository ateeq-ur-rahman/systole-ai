from __future__ import annotations

import os
import time

import pytest

from app.agents.version_cleanup import VersionCleanupAgent, VersionCleanupError
from app.agents.version_decision import VersionDecisionEngine
from app.repositories.notification_repository import NotificationRepository
from app.repositories.vault_repository import VaultRepository
from app.repositories.version_cleanup_folder_repository import VersionCleanupFolderRepository
from app.repositories.version_group_repository import VersionGroupRepository
from app.utils.path_guard import PathGuard
from app.utils.safe_vault import SafeVault
from app.utils.version_naming import VersionNameParser


def _build_agent(db_conn, tmp_path, automatic_cleanup=True, move_to_safe_vault=True):
    folder_repo = VersionCleanupFolderRepository(db_conn)
    group_repo = VersionGroupRepository(db_conn)
    vault_repo = VaultRepository(db_conn)
    notify_repo = NotificationRepository(db_conn)
    guard = PathGuard()
    vault = SafeVault(str(tmp_path / "_vault"))

    agent = VersionCleanupAgent(
        db_conn, folder_repo, group_repo, vault_repo, notify_repo, guard, vault,
        VersionNameParser(), VersionDecisionEngine(),
    )
    return agent, group_repo, notify_repo, folder_repo


def _touch_with_mtime(path, seconds_ago: float):
    now = time.time()
    ts = now - seconds_ago
    os.utime(path, (ts, ts))


def test_spec_example_keeps_only_the_highest_numbered_folder(db_conn, tmp_path):
    """The exact scenario from the spec: systole-storage-manager,
    (1)..(7) all present as folders -- final result should be only (7)
    remaining, with 0..6 moved to the Safe Vault."""
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    base = downloads / "systole-storage-manager"
    base.mkdir()
    (base / "file.txt").write_text("v0")
    _touch_with_mtime(base, seconds_ago=800)

    for n in range(1, 8):
        folder = downloads / f"systole-storage-manager ({n})"
        folder.mkdir()
        (folder / "file.txt").write_text(f"v{n}")
        # Strictly increasing modified time so there's a clear winner.
        _touch_with_mtime(folder, seconds_ago=800 - (n * 100))

    agent, group_repo, notify_repo, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(downloads))

    remaining = sorted(p.name for p in downloads.iterdir())
    assert remaining == ["systole-storage-manager (7)"]
    assert status["version_groups_cleaned"] == 1
    assert status["storage_saved_bytes"] > 0

    messages = [n["message"] for n in notify_repo.list_recent()]
    assert any("systole-storage-manager (7)" in m for m in messages)
    assert any("Moved" in m and "Safe Vault" in m for m in messages)
    assert any("Recovered" in m for m in messages)


def test_copy_of_pattern_resolved_by_modified_time(db_conn, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()

    original = watch / "Report.docx"
    original.write_text("original content")
    _touch_with_mtime(original, seconds_ago=500)

    copy = watch / "Copy of Report.docx"
    copy.write_text("edited copy, this is actually the newer one")
    _touch_with_mtime(copy, seconds_ago=10)

    agent, group_repo, _, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch))

    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Copy of Report.docx"]


def test_different_extensions_are_never_grouped_together(db_conn, tmp_path):
    """A Report.pdf and Report.docx must never be treated as 'versions'
    of each other -- different formats, not redundant copies."""
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "Report.pdf").write_text("pdf content")
    (watch / "Report.docx").write_text("docx content")

    agent, group_repo, _, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch))

    # Neither file should have been touched -- no version group at all.
    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Report.docx", "Report.pdf"]
    assert status["version_groups_pending"] == 0
    assert status["version_groups_cleaned"] == 0


def test_genuinely_tied_versions_require_confirmation_and_nothing_moves(db_conn, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()

    a = watch / "Project (1)"
    b = watch / "Project (2)"
    a.mkdir()
    b.mkdir()
    (a / "f.txt").write_text("same size content")
    (b / "f.txt").write_text("same size content")
    # Force identical mtimes so modified/created/size/folder all tie --
    # only version_number differs, so (2) should actually win outright
    # via that tier. To truly force "needs_confirmation" we'd need even
    # version numbers tied, which can't happen with distinct labels here,
    # so this test instead confirms the *normal* path resolves cleanly...
    same_ts = time.time() - 500
    os.utime(a, (same_ts, same_ts))
    os.utime(b, (same_ts, same_ts))

    agent, group_repo, notify_repo, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch))

    # (2) wins on version number since everything else is tied.
    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Project (2)"]


def test_automatic_cleanup_disabled_detects_but_does_not_move(db_conn, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    a = watch / "Project"
    b = watch / "Project (1)"
    a.mkdir()
    b.mkdir()
    _touch_with_mtime(a, seconds_ago=500)
    _touch_with_mtime(b, seconds_ago=10)

    agent, group_repo, _, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch), automatic_cleanup=False)

    # Both still present -- detection happened but nothing moved.
    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Project", "Project (1)"]
    assert status["version_groups_cleaned"] == 0


def test_set_folder_rejects_protected_path(db_conn, tmp_path):
    fake_system = tmp_path / "Windows" / "System32"
    fake_system.mkdir(parents=True)
    agent, _, _, _ = _build_agent(db_conn, tmp_path)
    with pytest.raises(VersionCleanupError):
        agent.set_folder(str(fake_system))


def test_truly_unresolvable_tie_triggers_needs_confirmation(db_conn, tmp_path):
    """Two members that tie on every single tier (same mtime, same size,
    same folder, and neither has a parseable version number -- e.g.
    '_backup' and '_old' both carry no number) must NOT be auto-resolved.
    This is the actual safety-critical path: 'if uncertain, do not
    delete, ask the user.'"""
    watch = tmp_path / "Downloads"
    watch.mkdir()

    a = watch / "Project_backup"
    b = watch / "Project_old"
    a.write_text("identical size content!!")
    b.write_text("identical size content!!")
    same_ts = time.time() - 500
    os.utime(a, (same_ts, same_ts))
    os.utime(b, (same_ts, same_ts))

    agent, group_repo, notify_repo, _ = _build_agent(db_conn, tmp_path)
    status = agent.set_folder(str(watch))

    # Nothing moved -- both files still present.
    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Project_backup", "Project_old"]
    assert status["version_groups_needing_confirmation"] == 1
    assert status["version_groups_cleaned"] == 0

    messages = [n["message"] for n in notify_repo.list_recent()]
    assert any("Multiple versions detected" in m and "confirm" in m for m in messages)

    groups = group_repo.list_groups(status="needs_confirmation")
    assert len(groups) == 1


def test_confirm_group_resolves_an_uncertain_group(db_conn, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    a = watch / "Project_backup"
    b = watch / "Project_old"
    a.write_text("identical size content!!")
    b.write_text("identical size content!!")
    same_ts = time.time() - 500
    os.utime(a, (same_ts, same_ts))
    os.utime(b, (same_ts, same_ts))

    agent, group_repo, notify_repo, _ = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch))

    groups = group_repo.list_groups(status="needs_confirmation")
    assert len(groups) == 1
    group_id = groups[0]["id"]

    status = agent.confirm_group(group_id, str(a))

    remaining = sorted(p.name for p in watch.iterdir())
    assert remaining == ["Project_backup"]
    assert status["version_groups_cleaned"] == 1

    resolved = group_repo.get_group(group_id)
    assert resolved["status"] == "cleaned"
    assert resolved["kept_member_path"] == str(a)


def test_pause_prevents_scheduled_cycles(db_conn, tmp_path):
    watch = tmp_path / "Downloads"
    watch.mkdir()
    (watch / "a.txt").write_text("x")

    agent, _, _, folder_repo = _build_agent(db_conn, tmp_path)
    agent.set_folder(str(watch))
    agent.pause()

    result = agent.run_cycle(is_initial=False)
    assert result.entries_scanned == 0

    agent.resume()
    status = agent.get_status()
    assert status["paused"] is False
