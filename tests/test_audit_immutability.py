"""
Tests verifying database-level immutability of the audit events log.
Confirms SQLite triggers strictly abort any UPDATE or DELETE operations on events.
"""

import pytest
import sqlite3
import os
import sys

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import init_db, get_db

@pytest.fixture
def audit_db(tmp_path):
    db_file = str(tmp_path / "audit_test.db")
    init_db(db_file)
    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (event_id, loan_id, event_type, payload_json, actor_id, occurred_at)
            VALUES ('EVT-IMMUTABLE-01', 'LN-001', 'TEST_EVENT', '{"data": 1}', 'ACTOR-01', '2026-09-14T12:00:00');
        """)
    return db_file

def test_events_disallow_update(audit_db):
    """Any attempt to UPDATE an event record must raise an ABORT exception."""
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        with get_db(audit_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE events
                SET payload_json = '{"tampered": true}'
                WHERE event_id = 'EVT-IMMUTABLE-01';
            """)
    assert "Events table is strictly immutable and append-only: UPDATE disallowed." in str(exc_info.value)

def test_events_disallow_delete(audit_db):
    """Any attempt to DELETE an event record must raise an ABORT exception."""
    with pytest.raises(sqlite3.IntegrityError) as exc_info:
        with get_db(audit_db) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM events
                WHERE event_id = 'EVT-IMMUTABLE-01';
            """)
    assert "Events table is strictly immutable and append-only: DELETE disallowed." in str(exc_info.value)

def test_events_allow_insert(audit_db):
    """Appending a new event record must succeed smoothly."""
    with get_db(audit_db) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (event_id, loan_id, event_type, payload_json, actor_id, occurred_at)
            VALUES ('EVT-IMMUTABLE-02', 'LN-002', 'NEW_EVENT', '{"data": 2}', 'ACTOR-02', '2026-09-14T12:01:00');
        """)
        cursor.execute("SELECT COUNT(*) as count FROM events;")
        assert cursor.fetchone()["count"] == 2
