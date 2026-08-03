from __future__ import annotations

from app.utils.scan_filter import ScanFilter, DEFAULT_ENABLED_CATEGORIES, DEFAULT_IGNORED_FOLDER_NAMES


def test_default_categories_include_common_user_file_types():
    sf = ScanFilter()
    for ext in [".pdf", ".docx", ".jpg", ".mp4", ".xlsx", ".zip", ".exe", ".msi", ".iso"]:
        assert sf.is_extension_included(ext), f"{ext} should be included by default"


def test_default_categories_exclude_source_code_and_system_files():
    sf = ScanFilter()
    for ext in [".py", ".js", ".dll", ".sys", ".log", ".json"]:
        assert not sf.is_extension_included(ext), f"{ext} should be excluded by default"


def test_unknown_extension_is_excluded_by_default_allowlist_behavior():
    sf = ScanFilter()
    assert not sf.is_extension_included(".xyz123")


def test_extension_matching_is_case_insensitive():
    sf = ScanFilter()
    assert sf.is_extension_included(".PDF")
    assert sf.is_extension_included(".Jpg")


def test_enabling_source_code_category_includes_its_extensions():
    sf = ScanFilter(enabled_categories={"source_code"})
    assert sf.is_extension_included(".py")
    assert not sf.is_extension_included(".pdf")  # documents no longer enabled


def test_default_ignored_folders_cover_dev_artifacts():
    sf = ScanFilter()
    for name in ["node_modules", ".git", "build", "dist", "bin", "obj", ".cache", "venv"]:
        assert sf.is_folder_ignored(name), f"{name} should be ignored by default"


def test_folder_ignore_check_is_case_insensitive():
    sf = ScanFilter()
    assert sf.is_folder_ignored("Node_Modules")
    assert sf.is_folder_ignored(".GIT")


def test_normal_user_folders_are_never_ignored_by_default():
    sf = ScanFilter()
    for name in ["Documents", "Photos 2024", "My Project", "Downloads"]:
        assert not sf.is_folder_ignored(name)


def test_minimum_size_filter():
    sf = ScanFilter(minimum_file_size_bytes=4096)
    assert not sf.passes_size_filter(100)
    assert sf.passes_size_filter(4096)
    assert sf.passes_size_filter(10_000)


def test_custom_ignored_folder_names_are_configurable():
    sf = ScanFilter(ignored_folder_names={"my_custom_ignore"})
    assert sf.is_folder_ignored("my_custom_ignore")
    assert not sf.is_folder_ignored("node_modules")  # replaced, not merged


def test_all_categories_lists_every_known_category():
    categories = ScanFilter.all_categories()
    for expected in ["documents", "pdfs", "images", "videos", "office",
                      "archives", "installers", "source_code", "system_files"]:
        assert expected in categories
