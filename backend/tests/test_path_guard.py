from __future__ import annotations

import os
import tempfile

import pytest

from app.utils.path_guard import PathGuard


@pytest.fixture
def guard():
    return PathGuard()


@pytest.mark.parametrize("path", [
    r"C:\Windows\System32\kernel32.dll",
    r"C:\Windows\explorer.exe",
    r"C:\Program Files\SomeApp\app.exe",
    r"C:\Program Files (x86)\SomeApp\app.exe",
    r"C:\ProgramData\Microsoft\config.dat",
    r"C:\Users\alice\AppData\Local\Temp\file.tmp",
    r"C:\Users\alice\AppData\Roaming\config.json",
    r"C:\Recovery\WindowsRE\winre.wim",
    r"C:\Boot\bcd",
    r"C:\Windows\Boot\EFI\bootmgfw.efi",
    r"C:\Windows System32\drivers\etc\hosts".replace(" System32", "\\System32\\drivers"),
])
def test_protected_directories_are_blocked(guard, path):
    result = guard.is_scannable(path)
    assert result.allowed is False


@pytest.mark.parametrize("filename", [
    "pagefile.sys", "hiberfil.sys", "swapfile.sys",
])
def test_protected_system_files_are_blocked(guard, filename):
    path = f"C:\\{filename}"
    result = guard.is_scannable(path)
    assert result.allowed is False


@pytest.mark.parametrize("path", [
    r"C:\Windows\System32\drivers\nvlddmkm.sys",
    r"C:\Windows\System32\ntdll.dll",
])
def test_protected_extensions_are_blocked(guard, path):
    result = guard.is_scannable(path)
    assert result.allowed is False


def test_normal_user_files_are_allowed(guard):
    for path in [
        r"C:\Users\alice\Documents\resume.pdf",
        r"C:\Users\alice\Desktop\notes.txt",
        r"C:\Users\alice\Downloads\photo.jpg",
    ]:
        result = guard.is_scannable(path)
        assert result.allowed is True, result.reason


def test_extra_excluded_dirs_are_respected():
    guard = PathGuard(extra_excluded_dirs=[r"C:\Users\alice\Secret"])
    result = guard.is_scannable(r"C:\Users\alice\Secret\notes.txt")
    assert result.allowed is False


def test_modifiable_inherits_never_touch_extension_protection(tmp_path):
    """.dll/.sys/.drv remain hard-blocked from ever being moved -- via the
    same NEVER_TOUCH_EXTENSIONS check is_scannable() already enforces
    (is_modifiable() always runs that check first). These are
    system-internal library/driver types, never something a user means
    by 'my duplicate files.'"""
    guard = PathGuard()
    fake_dll = tmp_path / "app.dll"
    fake_dll.write_bytes(b"fake binary")
    result = guard.is_modifiable(str(fake_dll))
    assert result.allowed is False
    assert "excluded extension" in result.reason


def test_duplicate_installers_can_be_moved_to_vault(tmp_path):
    """Regression test: .exe/.msi used to be hard-blocked from ever being
    moved, which silently broke the advertised 'duplicate installers'
    feature (ScanFilter enables installers by default; AI Recommendations
    has a dedicated 'duplicate installers' card) -- a confirmed-duplicate,
    not-currently-running installer must be movable to the Safe Vault.
    Moving to the vault is always reversible, so this isn't a safety
    regression; the separate lock-check still protects anything actually
    in use (see test_locked_installer_is_still_protected below)."""
    guard = PathGuard()
    for ext in (".exe", ".msi"):
        installer = tmp_path / f"OldInstaller{ext}"
        installer.write_bytes(b"fake installer bytes")
        result = guard.is_modifiable(str(installer))
        assert result.allowed is True, f"{ext} should be movable: {result.reason}"


def test_iso_disk_images_can_also_be_moved():
    """The third 'installers' category member -- same reasoning as exe/msi."""
    import tempfile
    guard = PathGuard()
    with tempfile.TemporaryDirectory() as tmp:
        iso = os.path.join(tmp, "disk.iso")
        with open(iso, "wb") as fh:
            fh.write(b"fake iso bytes")
        result = guard.is_modifiable(iso)
        assert result.allowed is True


def test_modifiable_allows_ordinary_file(tmp_path):
    guard = PathGuard()
    f = tmp_path / "duplicate.txt"
    f.write_text("hello")
    result = guard.is_modifiable(str(f))
    assert result.allowed is True


def test_modifiable_still_enforces_scannable_rules(tmp_path):
    guard = PathGuard(extra_excluded_dirs=[str(tmp_path)])
    f = tmp_path / "file.txt"
    f.write_text("hello")
    result = guard.is_modifiable(str(f))
    assert result.allowed is False


def test_modifiable_allows_a_directory_not_just_files():
    """Regression test: directories can never be opened via open(), which
    the old lock-check used to try -- meaning every directory used to be
    incorrectly treated as 'locked' and blocked from ever being moved.
    Needed for the Version Cleanup Agent, which moves whole version-named
    folders (e.g. 'Project (1)') to the Safe Vault, not just files."""
    guard = PathGuard()
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "Project (1)")
        os.mkdir(folder)
        with open(os.path.join(folder, "file.txt"), "w") as fh:
            fh.write("content")
        result = guard.is_modifiable(folder)
        assert result.allowed is True, result.reason
