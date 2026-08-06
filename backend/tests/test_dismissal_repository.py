from __future__ import annotations

from app.repositories.dismissal_repository import DismissalRepository


def test_dismiss_and_is_dismissed(db_conn):
    repo = DismissalRepository(db_conn)
    assert repo.is_dismissed("archive") is False

    repo.dismiss("archive")
    assert repo.is_dismissed("archive") is True


def test_permanent_dismissal_has_no_expiry(db_conn):
    repo = DismissalRepository(db_conn)
    repo.dismiss("installer")

    row = db_conn.execute(
        "SELECT expires_at FROM dismissed_recommendations WHERE category='installer'"
    ).fetchone()
    assert row["expires_at"] is None


def test_snoozed_dismissal_expires_and_stops_being_active(db_conn):
    repo = DismissalRepository(db_conn)
    # Snooze in the past by directly backdating, simulating time having passed.
    repo.dismiss("presentation", snooze_days=7)
    db_conn.execute(
        "UPDATE dismissed_recommendations SET expires_at=datetime('now', '-1 day') WHERE category='presentation'"
    )
    db_conn.commit()

    assert repo.is_dismissed("presentation") is False  # expired snooze no longer counts
    assert "presentation" not in [r["category"] for r in repo.list_active()]


def test_redismissing_increments_times_dismissed(db_conn):
    repo = DismissalRepository(db_conn)
    repo.dismiss("archive")
    repo.dismiss("archive")
    repo.dismiss("archive")

    row = db_conn.execute(
        "SELECT times_dismissed FROM dismissed_recommendations WHERE category='archive'"
    ).fetchone()
    assert row["times_dismissed"] == 3


def test_undismiss_removes_it_entirely(db_conn):
    repo = DismissalRepository(db_conn)
    repo.dismiss("archive")
    assert repo.is_dismissed("archive") is True

    repo.undismiss("archive")
    assert repo.is_dismissed("archive") is False


def test_list_active_excludes_expired_but_includes_permanent_and_future_snoozes(db_conn):
    repo = DismissalRepository(db_conn)
    repo.dismiss("permanent_one")
    repo.dismiss("future_snooze", snooze_days=30)
    repo.dismiss("expired_one", snooze_days=1)
    db_conn.execute(
        "UPDATE dismissed_recommendations SET expires_at=datetime('now', '-1 day') WHERE category='expired_one'"
    )
    db_conn.commit()

    active_categories = {r["category"] for r in repo.list_active()}
    assert active_categories == {"permanent_one", "future_snooze"}
