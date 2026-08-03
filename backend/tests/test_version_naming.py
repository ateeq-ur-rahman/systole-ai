from __future__ import annotations

import re

from app.utils.version_naming import VersionNameParser, VersionPattern


def test_bare_name_has_no_version_marker():
    result = VersionNameParser().parse("Project")
    assert result.base_name == "Project"
    assert result.version_label == ""
    assert result.version_number is None


def test_parenthetical_number_pattern():
    parser = VersionNameParser()
    for n in range(1, 8):
        result = parser.parse(f"systole-storage-manager ({n})")
        assert result.base_name == "systole-storage-manager"
        assert result.version_number == n


def test_v_number_pattern():
    parser = VersionNameParser()
    assert parser.parse("Project_v2").version_number == 2
    assert parser.parse("Project_v3").base_name == "Project"
    assert parser.parse("Project v10").version_number == 10


def test_copy_of_prefix_pattern():
    result = VersionNameParser().parse("Copy of Project")
    assert result.base_name == "Project"
    assert result.version_number is None
    assert "copy" in result.version_label.lower()


def test_dash_copy_and_copy_suffix_patterns():
    parser = VersionNameParser()
    assert parser.parse("Project - Copy").base_name == "Project"
    assert parser.parse("Project Copy").base_name == "Project"


def test_final_and_final_numbered_patterns():
    parser = VersionNameParser()
    plain = parser.parse("Project_Final")
    assert plain.base_name == "Project"
    assert plain.version_number is None

    numbered = parser.parse("Project_Final (1)")
    assert numbered.base_name == "Project"
    assert numbered.version_number == 1


def test_backup_old_new_suffixes():
    parser = VersionNameParser()
    assert parser.parse("Project_backup").base_name == "Project"
    assert parser.parse("Project_old").base_name == "Project"
    assert parser.parse("Project_new").base_name == "Project"


def test_matching_is_case_insensitive():
    parser = VersionNameParser()
    assert parser.parse("PROJECT_V2").base_name == "PROJECT"
    assert parser.parse("copy of Project").base_name == "Project"


def test_unrelated_names_do_not_share_a_base():
    parser = VersionNameParser()
    a = parser.parse("Budget_2024")
    b = parser.parse("Roadmap_2024")
    assert a.base_name != b.base_name


def test_parser_is_configurable_with_custom_patterns():
    """The naming engine must be data-driven, not hardcoded -- a caller
    can supply their own pattern list entirely."""
    custom_patterns = [
        VersionPattern("draft_number", re.compile(r"^(?P<base>.+?)_draft(?P<num>\d+)$", re.IGNORECASE)),
    ]
    parser = VersionNameParser(patterns=custom_patterns)

    result = parser.parse("Contract_draft3")
    assert result.base_name == "Contract"
    assert result.version_number == 3

    # A pattern this custom parser doesn't know about just falls through
    # to "no version marker" rather than erroring.
    fallback = parser.parse("Project (1)")
    assert fallback.base_name == "Project (1)"
    assert fallback.version_number is None
