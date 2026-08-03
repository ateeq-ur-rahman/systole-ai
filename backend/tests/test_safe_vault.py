from __future__ import annotations

from app.utils.safe_vault import SafeVault


def test_move_to_vault_preserves_content(tmp_path):
    vault_dir = tmp_path / "vault"
    vault = SafeVault(str(vault_dir))

    source = tmp_path / "original.txt"
    source.write_text("important content")

    result = vault.move_to_vault(str(source))

    assert result.success is True
    assert not source.exists()  # moved, not copied
    assert result.destination_path is not None
    from pathlib import Path
    assert Path(result.destination_path).read_text() == "important content"


def test_move_to_vault_fails_gracefully_for_missing_file(tmp_path):
    vault = SafeVault(str(tmp_path / "vault"))
    result = vault.move_to_vault(str(tmp_path / "does_not_exist.txt"))
    assert result.success is False
    assert "does not exist" in result.error


def test_restore_moves_file_back_to_original_location(tmp_path):
    vault = SafeVault(str(tmp_path / "vault"))
    source = tmp_path / "docs" / "file.txt"
    source.parent.mkdir()
    source.write_text("restore me")

    move_result = vault.move_to_vault(str(source))
    assert move_result.success

    restore_result = vault.restore(move_result.destination_path, str(source))
    assert restore_result.success is True
    assert source.exists()
    assert source.read_text() == "restore me"


def test_restore_does_not_overwrite_existing_file_at_original_path(tmp_path):
    vault = SafeVault(str(tmp_path / "vault"))
    source = tmp_path / "file.txt"
    source.write_text("version A")

    move_result = vault.move_to_vault(str(source))
    assert move_result.success

    # Something new now occupies the original path.
    source.write_text("version B (new file)")

    restore_result = vault.restore(move_result.destination_path, str(source))
    assert restore_result.success is True
    assert restore_result.destination_path != str(source)
    assert source.read_text() == "version B (new file)"  # untouched


def test_purge_permanently_removes_vault_file(tmp_path):
    vault = SafeVault(str(tmp_path / "vault"))
    source = tmp_path / "file.txt"
    source.write_text("delete me eventually")

    move_result = vault.move_to_vault(str(source))
    assert move_result.success

    purge_result = vault.purge(move_result.destination_path)
    assert purge_result.success is True

    from pathlib import Path
    assert not Path(move_result.destination_path).exists()


def test_two_files_with_same_basename_do_not_collide_in_vault(tmp_path):
    vault = SafeVault(str(tmp_path / "vault"))
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    f1 = dir_a / "duplicate.txt"
    f2 = dir_b / "duplicate.txt"
    f1.write_text("from a")
    f2.write_text("from b")

    r1 = vault.move_to_vault(str(f1))
    r2 = vault.move_to_vault(str(f2))

    assert r1.success and r2.success
    assert r1.destination_path != r2.destination_path
    from pathlib import Path
    assert Path(r1.destination_path).read_text() == "from a"
    assert Path(r2.destination_path).read_text() == "from b"
