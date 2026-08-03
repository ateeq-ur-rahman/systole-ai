from __future__ import annotations

from app.agents.version_decision import VersionDecisionEngine
from app.database.models import VersionMember


def _m(**kwargs) -> VersionMember:
    defaults = dict(
        full_path="C:\\Downloads\\Project", is_folder=True, base_name="Project",
        version_label="", version_number=None, size_bytes=1000,
        modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
    )
    defaults.update(kwargs)
    return VersionMember(**defaults)


def test_single_member_is_trivially_kept():
    engine = VersionDecisionEngine()
    m = _m()
    decision = engine.decide([m])
    assert decision.kept is m
    assert decision.reason == "only_version"
    assert decision.needs_confirmation is False


def test_latest_modified_wins():
    engine = VersionDecisionEngine()
    older = _m(full_path="C:\\Downloads\\Project", modified_time="2024-01-01T00:00:00")
    newer = _m(full_path="C:\\Downloads\\Project (7)", modified_time="2024-06-01T00:00:00")
    decision = engine.decide([older, newer])
    assert decision.kept is newer
    assert decision.reason == "latest_modified"
    assert decision.needs_confirmation is False


def test_falls_through_to_created_time():
    engine = VersionDecisionEngine()
    same_mtime = "2024-01-01T00:00:00"
    a = _m(full_path="a", modified_time=same_mtime, created_time="2023-01-01T00:00:00")
    b = _m(full_path="b", modified_time=same_mtime, created_time="2023-06-01T00:00:00")
    decision = engine.decide([a, b])
    assert decision.kept is b
    assert decision.reason == "latest_created"


def test_falls_through_to_version_number_per_spec_example():
    """The spec's own example: keep only (7) out of a 0..7 sequence.
    With every timestamp genuinely tied (e.g. extracted from a bulk
    re-copy), version number is the deciding tier."""
    engine = VersionDecisionEngine()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00")
    members = [_m(full_path=f"systole-storage-manager ({n})" if n else "systole-storage-manager",
                   version_number=n or None, **same_ts) for n in range(8)]
    decision = engine.decide(members)
    assert decision.kept.version_number == 7
    assert decision.reason == "highest_version_number"


def test_falls_through_to_largest_size():
    engine = VersionDecisionEngine()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00")
    small = _m(full_path="a", size_bytes=100, **same_ts)
    large = _m(full_path="b", size_bytes=99999, **same_ts)
    decision = engine.decide([small, large])
    assert decision.kept is large
    assert decision.reason == "largest_size"


def test_falls_through_to_folder_priority():
    engine = VersionDecisionEngine()
    same = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00", size_bytes=100)
    in_downloads = _m(full_path="C:\\Downloads\\Project", **same)
    in_documents = _m(full_path="C:\\Documents\\Project", **same)
    decision = engine.decide([in_downloads, in_documents])
    assert decision.kept is in_documents
    assert decision.reason == "preferred_folder"


def test_genuinely_tied_group_requires_confirmation_not_a_guess():
    """The critical safety behavior: if every single tier is tied, the
    engine must refuse to pick one rather than falling back to an
    arbitrary deterministic tiebreaker (unlike VersionIntelligenceAgent,
    which is safe to always decide because it only ever runs on
    hash-confirmed-identical files)."""
    engine = VersionDecisionEngine()
    same = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                size_bytes=100, full_path="C:\\Downloads\\Project")
    a = _m(**same)
    b = _m(**same)
    decision = engine.decide([a, b])
    assert decision.kept is None
    assert decision.needs_confirmation is True
    assert decision.reason == "uncertain"


def test_version_number_none_ranks_below_any_numbered_sibling():
    engine = VersionDecisionEngine()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00")
    bare = _m(full_path="Project", version_number=None, **same_ts)
    numbered = _m(full_path="Project (1)", version_number=1, **same_ts)
    decision = engine.decide([bare, numbered])
    assert decision.kept is numbered
    assert decision.reason == "highest_version_number"
