"""
Version Name Parser

Recognizes Windows-style "multiple versions of the same thing" naming
patterns and extracts a normalized base name + version marker from a
file or folder name. This is deliberately name-pattern-based -- unlike
duplicate detection elsewhere in Systole (which uses SHA-256 content hash
exclusively), the Version Cleanup Agent's whole purpose is to catch
things that are named like sequential versions of a project, which may
genuinely have different content between versions.

Recognized patterns (checked in order, first match wins):
    Project (7)              -> base="Project", numbered
    Project_v2                -> base="Project", numbered
    Copy of Project            -> base="Project", unnumbered "copy" marker
    Project - Copy              -> base="Project", unnumbered "copy" marker
    Project Copy                -> base="Project", unnumbered "copy" marker
    Project_Final                -> base="Project", unnumbered "final" marker
    Project_Final (1)             -> base="Project", numbered (Final variant)
    Project_backup / _old / _new   -> base="Project", unnumbered marker
    Project (bare, no suffix)       -> base="Project", the baseline/version-0 item

The pattern list is intentionally data (a plain list of dataclasses), not
hardcoded control flow, so it's configurable: pass a custom `patterns`
list to VersionNameParser() to add, remove, or reorder recognized forms
without touching the matching logic itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Pattern


@dataclass(frozen=True)
class VersionPattern:
    name: str
    regex: Pattern[str]
    base_group: str = "base"
    number_group: Optional[str] = "num"


@dataclass
class ParsedName:
    base_name: str
    version_label: str
    version_number: Optional[int]


def _default_patterns() -> list[VersionPattern]:
    flags = re.IGNORECASE
    return [
        VersionPattern("final_numbered", re.compile(r"^(?P<base>.+?)_final\s*\((?P<num>\d+)\)$", flags)),
        VersionPattern("final", re.compile(r"^(?P<base>.+?)_final$", flags), number_group=None),
        VersionPattern("parenthetical_number", re.compile(r"^(?P<base>.+?)\s*\((?P<num>\d+)\)$", flags)),
        VersionPattern("v_number", re.compile(r"^(?P<base>.+?)[_\s]v(?P<num>\d+)$", flags)),
        VersionPattern("copy_of_prefix", re.compile(r"^copy of (?P<base>.+)$", flags), number_group=None),
        VersionPattern("dash_copy_suffix", re.compile(r"^(?P<base>.+?)\s*-\s*copy$", flags), number_group=None),
        VersionPattern("copy_suffix", re.compile(r"^(?P<base>.+?)\s+copy$", flags), number_group=None),
        VersionPattern("backup_suffix", re.compile(r"^(?P<base>.+?)_backup$", flags), number_group=None),
        VersionPattern("old_suffix", re.compile(r"^(?P<base>.+?)_old$", flags), number_group=None),
        VersionPattern("new_suffix", re.compile(r"^(?P<base>.+?)_new$", flags), number_group=None),
    ]


class VersionNameParser:
    def __init__(self, patterns: Optional[list[VersionPattern]] = None):
        self._patterns = patterns if patterns is not None else _default_patterns()

    def parse(self, name: str) -> ParsedName:
        """Parse a single path component (file stem or folder name -- the
        caller is responsible for stripping any file extension first, see
        VersionCleanupAgent._group_key). Returns the bare name itself as
        the base with an empty label/None version if nothing matches --
        every name is parseable, it just might not carry a version
        marker."""
        stripped = name.strip()
        for pattern in self._patterns:
            match = pattern.regex.match(stripped)
            if not match:
                continue
            base = match.group(pattern.base_group).strip()
            version_number = None
            if pattern.number_group:
                num_str = match.groupdict().get(pattern.number_group)
                if num_str is not None:
                    version_number = int(num_str)
            base_start, base_end = match.span(pattern.base_group)
            label = (stripped[:base_start] + stripped[base_end:]).strip()
            return ParsedName(base_name=base, version_label=label, version_number=version_number)

        return ParsedName(base_name=stripped, version_label="", version_number=None)
