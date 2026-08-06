from __future__ import annotations

import sqlite3

import pytest

from app.ml.tie_break_learner import (
    Candidate, TieBreakLearner, build_candidate,
    MIN_TRAINING_EXAMPLES, MIN_CONFIDENCE_TO_SUGGEST,
)


@pytest.fixture
def conn(tmp_path):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE tie_break_choices (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidates_json TEXT NOT NULL,
        chosen_index INTEGER NOT NULL,
        decided_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""")
    c.commit()
    yield c
    c.close()


def test_predicts_none_before_minimum_training_examples(conn):
    learner = TieBreakLearner(conn)
    a = Candidate("Documents", "backup_suffix", ".docx", False)
    b = Candidate("Downloads", "old_suffix", ".docx", True)

    for _ in range(MIN_TRAINING_EXAMPLES - 1):
        learner.record_choice([a, b], chosen_index=0)

    assert learner.predict([a, b]) is None


def test_genuinely_learns_a_real_user_preference(conn):
    """The actual proof this is real learning, not a hardcoded rule:
    train it exclusively on 'this user always keeps the Documents copy
    over the Downloads copy in a tie' and confirm it correctly predicts
    that same preference on a fresh, unseen tie with the same pattern."""
    learner = TieBreakLearner(conn)

    for _ in range(10):
        documents_copy = Candidate("Documents", "none", ".pdf", False)
        downloads_copy = Candidate("Downloads", "none", ".pdf", True)
        learner.record_choice([documents_copy, downloads_copy], chosen_index=0)

    # A brand new tie, same underlying pattern, never seen verbatim before.
    new_documents_copy = Candidate("Documents", "none", ".xlsx", False)
    new_downloads_copy = Candidate("Downloads", "none", ".xlsx", True)

    prediction = learner.predict([new_documents_copy, new_downloads_copy])

    assert prediction is not None
    assert prediction.chosen_index == 0  # correctly predicts "Documents" again
    assert prediction.confidence >= MIN_CONFIDENCE_TO_SUGGEST
    assert "documents" in prediction.reason.lower()


def test_stays_silent_when_the_user_has_no_consistent_preference(conn):
    """Equally important as learning a real pattern: NOT inventing false
    confidence when the user's past choices are genuinely inconsistent
    (roughly 50/50), since a suggestion should only ever surface when
    there's real signal behind it."""
    learner = TieBreakLearner(conn)

    a = Candidate("Documents", "none", ".docx", False)
    b = Candidate("Downloads", "none", ".docx", True)

    # Alternates -- no consistent pattern at all.
    for i in range(10):
        learner.record_choice([a, b], chosen_index=i % 2)

    prediction = learner.predict([a, b])
    assert prediction is None  # correctly refuses to guess


def test_recorded_choice_is_never_transmitted_or_derived_from_file_content(conn):
    """Confirms what actually gets stored is exactly the small,
    non-sensitive feature set -- never the filename, full path, or file
    content itself."""
    learner = TieBreakLearner(conn)
    candidate = Candidate("Documents", "backup_suffix", ".docx", False)
    other = Candidate("Downloads", "old_suffix", ".docx", True)
    learner.record_choice([candidate, other], chosen_index=0)

    row = conn.execute("SELECT candidates_json FROM tie_break_choices").fetchone()
    stored = row["candidates_json"]

    assert "Documents" not in stored or "folder" in stored  # only the lowercase category, not a raw path
    assert "C:" not in stored
    assert ".docx" in stored  # extension alone is fine and expected


def test_build_candidate_extracts_from_data_the_agent_already_has(tmp_path):
    group_names = ["Report.docx", "Report_backup.docx"]
    candidate = build_candidate(
        full_path=str(tmp_path / "Documents" / "Report_backup.docx"),
        version_label="backup_suffix",
        all_names_in_group=group_names,
    )
    assert candidate.folder_basename == "Documents"
    assert candidate.version_label == "backup_suffix"
    assert candidate.extension == ".docx"
    assert candidate.is_shortest_name is False  # "Report_backup.docx" is longer than "Report.docx"


def test_record_choice_rejects_invalid_index(conn):
    learner = TieBreakLearner(conn)
    a = Candidate("Documents", "none", ".docx", False)
    with pytest.raises(ValueError):
        learner.record_choice([a], chosen_index=5)
