"""
Database connection and schema initialization for the Loan-Device Return Checklist
and Accessory Reconciliation system.
Enforces foreign keys, WAL mode, and immutable append-only triggers on the audit log.
"""

import sqlite3
import os
from contextlib import contextmanager

def get_db_path():
    return os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reconciliation.db"))

def get_db_connection(db_path=None):
    target = db_path or get_db_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    # Enforce SQLite foreign key constraints and WAL mode for high concurrency & speed
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    return conn

@contextmanager
def get_db(db_path=None):
    conn = get_db_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db(db_path=None):
    """Initialize database tables, indexes, and immutability triggers."""
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        
        # 1. Devices table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id TEXT PRIMARY KEY,
            model TEXT NOT NULL,
            category TEXT NOT NULL,
            serial_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN (
                'available', 'on_loan', 'in_intake', 'hold_cleaning',
                'hold_missing_accessory', 'escalated_biomed', 'written_off'
            )),
            last_status_change_at TEXT NOT NULL
        );
        """)

        # 2. Accessory items catalog
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS accessory_items (
            item_id TEXT PRIMARY KEY,
            device_model TEXT NOT NULL,
            item_name TEXT NOT NULL,
            required INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0, 1))
        );
        """)

        # 3. Loans table (Zero PHI: pseudonymous patient_ref_id only)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            loan_id TEXT PRIMARY KEY,
            device_id TEXT NOT NULL REFERENCES devices(device_id),
            patient_ref_id TEXT NOT NULL,
            issued_at TEXT NOT NULL,
            issued_accessory_manifest_json TEXT NOT NULL,
            returned_at TEXT
        );
        """)

        # 4. Return checklists table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS return_checklists (
            checklist_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL REFERENCES loans(loan_id),
            item_id TEXT NOT NULL REFERENCES accessory_items(item_id),
            condition TEXT NOT NULL CHECK (condition IN ('present', 'missing', 'damaged', 'evidence_pending')),
            photo_ref TEXT,
            recorded_by TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        """)

        # 5. Return condition table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS return_condition (
            condition_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL REFERENCES loans(loan_id),
            condition_code TEXT NOT NULL CHECK (condition_code IN ('functional', 'needs_inspection', 'damaged', 'non_functional')),
            wear_tags TEXT NOT NULL DEFAULT '[]',
            recorded_by TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        """)

        # 6. Cleaning status table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS cleaning_status (
            cleaning_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL REFERENCES loans(loan_id),
            stage TEXT NOT NULL CHECK (stage IN ('not_started', 'in_progress', 'completed', 'failed')),
            technician_id TEXT,
            started_at TEXT,
            completed_at TEXT
        );
        """)

        # 7. Patient acknowledgement table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_acknowledgement (
            ack_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL REFERENCES loans(loan_id),
            acknowledged INTEGER NOT NULL CHECK (acknowledged IN (0, 1)),
            witness_staff_id TEXT NOT NULL,
            acknowledged_at TEXT NOT NULL
        );
        """)

        # 8. Recommendations table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recommendations (
            rec_id TEXT PRIMARY KEY,
            loan_id TEXT NOT NULL REFERENCES loans(loan_id),
            recommendation TEXT NOT NULL,
            rule_trail_json TEXT NOT NULL,
            confidence_score REAL NOT NULL,
            fallback_triggered INTEGER NOT NULL DEFAULT 0 CHECK (fallback_triggered IN (0, 1)),
            generated_at TEXT NOT NULL
        );
        """)

        # 9. Human confirmations table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS human_confirmations (
            confirm_id TEXT PRIMARY KEY,
            rec_id TEXT NOT NULL REFERENCES recommendations(rec_id),
            confirmed_by TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'overridden')),
            override_reason_code TEXT,
            override_justification TEXT,
            confirmed_at TEXT NOT NULL
        );
        """)

        # 10. Capacity slots table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS capacity_slots (
            slot_id TEXT PRIMARY KEY,
            shift_date TEXT NOT NULL,
            shift_name TEXT NOT NULL CHECK (shift_name IN ('Morning', 'Afternoon', 'Night')),
            role TEXT NOT NULL CHECK (role IN ('technician', 'cleaning_bay')),
            capacity INTEGER NOT NULL,
            booked INTEGER NOT NULL DEFAULT 0
        );
        """)

        # 11. Immutable events audit table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            loan_id TEXT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            occurred_at TEXT NOT NULL
        );
        """)

        # Triggers enforcing append-only immutability on events table
        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_events_update
        BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, 'Events table is strictly immutable and append-only: UPDATE disallowed.');
        END;
        """)

        cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS prevent_events_delete
        BEFORE DELETE ON events
        BEGIN
            SELECT RAISE(ABORT, 'Events table is strictly immutable and append-only: DELETE disallowed.');
        END;
        """)

        # Indexes for fast querying
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_loans_device ON loans(device_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_checklists_loan ON return_checklists(loan_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_loan ON events(loan_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_capacity_lookup ON capacity_slots(shift_date, role);")
