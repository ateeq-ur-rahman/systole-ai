from __future__ import annotations

from app.agents.version_intelligence import VersionIntelligenceAgent
from app.database.models import FileRecord


def _f(**kwargs) -> FileRecord:
    defaults = dict(
        id=None, drive_id=1, full_path="C:\\file.txt", filename="file.txt",
        extension=".txt", folder="C:\\", size_bytes=100,
        created_time="2024-01-01T00:00:00", modified_time="2024-01-01T00:00:00",
        accessed_time="2024-01-01T00:00:00",
    )
    defaults.update(kwargs)
    return FileRecord(**defaults)


def test_single_candidate_is_trivially_survivor():
    agent = VersionIntelligenceAgent()
    f = _f(id=1)
    decision = agent.select_survivor([f])
    assert decision.survivor.id == 1
    assert decision.reason == "only_copy"


def test_latest_modified_wins():
    agent = VersionIntelligenceAgent()
    older = _f(id=1, full_path="C:\\a.txt", modified_time="2024-01-01T00:00:00")
    newer = _f(id=2, full_path="C:\\b.txt", modified_time="2024-06-01T00:00:00")
    decision = agent.select_survivor([older, newer])
    assert decision.survivor.id == 2
    assert decision.reason == "latest_modified"


def test_falls_through_to_created_time_when_modified_tied():
    agent = VersionIntelligenceAgent()
    a = _f(id=1, full_path="C:\\a.txt", modified_time="2024-01-01T00:00:00",
           created_time="2023-01-01T00:00:00")
    b = _f(id=2, full_path="C:\\b.txt", modified_time="2024-01-01T00:00:00",
           created_time="2023-06-01T00:00:00")
    decision = agent.select_survivor([a, b])
    assert decision.survivor.id == 2
    assert decision.reason == "latest_created"


def test_falls_through_to_accessed_time_when_modified_and_created_tied():
    agent = VersionIntelligenceAgent()
    a = _f(id=1, full_path="C:\\a.txt", modified_time="2024-01-01T00:00:00",
           created_time="2023-01-01T00:00:00", accessed_time="2024-02-01T00:00:00")
    b = _f(id=2, full_path="C:\\b.txt", modified_time="2024-01-01T00:00:00",
           created_time="2023-01-01T00:00:00", accessed_time="2024-05-01T00:00:00")
    decision = agent.select_survivor([a, b])
    assert decision.survivor.id == 2
    assert decision.reason == "latest_accessed"


def test_falls_through_to_preferred_folder_when_all_timestamps_tied():
    agent = VersionIntelligenceAgent()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                    accessed_time="2024-01-01T00:00:00")
    downloads = _f(id=1, full_path="C:\\Users\\a\\Downloads\\file.txt",
                    folder="C:\\Users\\a\\Downloads", **same_ts)
    documents = _f(id=2, full_path="C:\\Users\\a\\Documents\\file.txt",
                    folder="C:\\Users\\a\\Documents", **same_ts)
    decision = agent.select_survivor([downloads, documents])
    assert decision.survivor.id == 2
    assert "preferred_folder" in decision.reason
    assert "Documents" in decision.reason


def test_folder_priority_order_documents_beats_desktop_beats_downloads():
    agent = VersionIntelligenceAgent()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                    accessed_time="2024-01-01T00:00:00")
    desktop = _f(id=1, full_path="C:\\Desktop\\f.txt", folder="C:\\Desktop", **same_ts)
    documents = _f(id=2, full_path="C:\\Documents\\f.txt", folder="C:\\Documents", **same_ts)
    downloads = _f(id=3, full_path="C:\\Downloads\\f.txt", folder="C:\\Downloads", **same_ts)

    decision = agent.select_survivor([desktop, documents, downloads])
    assert decision.survivor.id == 2  # Documents wins over Desktop and Downloads


def test_falls_through_to_shortest_path_when_folder_tier_tied():
    agent = VersionIntelligenceAgent()
    same_ts = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                    accessed_time="2024-01-01T00:00:00")
    long_path = _f(id=1, full_path="C:\\Documents\\nested\\deep\\folder\\file.txt",
                    folder="C:\\Documents\\nested\\deep\\folder", **same_ts)
    short_path = _f(id=2, full_path="C:\\Documents\\file.txt", folder="C:\\Documents", **same_ts)

    decision = agent.select_survivor([long_path, short_path])
    assert decision.survivor.id == 2
    assert decision.reason == "shortest_path"


def test_fully_tied_files_are_still_deterministic():
    agent = VersionIntelligenceAgent()
    same = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                accessed_time="2024-01-01T00:00:00", folder="C:\\Other")
    a = _f(id=1, full_path="C:\\Other\\a.txt", **same)
    b = _f(id=2, full_path="C:\\Other\\b.txt", **same)

    d1 = agent.select_survivor([a, b])
    d2 = agent.select_survivor([b, a])  # order-independence check
    assert d1.survivor.id == d2.survivor.id == 1  # "a.txt" sorts before "b.txt"


def test_custom_folder_priority_order_is_respected():
    agent = VersionIntelligenceAgent(folder_priority_order=["projects", "documents"])
    same = dict(modified_time="2024-01-01T00:00:00", created_time="2024-01-01T00:00:00",
                accessed_time="2024-01-01T00:00:00")
    documents = _f(id=1, full_path="C:\\Documents\\f.txt", folder="C:\\Documents", **same)
    projects = _f(id=2, full_path="C:\\Projects\\f.txt", folder="C:\\Projects", **same)

    decision = agent.select_survivor([documents, projects])
    assert decision.survivor.id == 2  # projects ranked above documents in custom order
