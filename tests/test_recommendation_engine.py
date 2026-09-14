"""
Unit tests for the Recommendation Engine:
Validates clinical rules, confidence score computations, and safe fallback under uncertainty.
"""

import pytest
import sqlite3
import json
import os
import sys

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.database import init_db, get_db
from src.recommendation_engine import RecommendationEngine

@pytest.fixture
def test_db(tmp_path):
    """Creates an isolated temporary SQLite database for testing."""
    db_file = str(tmp_path / "test_reconciliation.db")
    init_db(db_file)
    
    # Seed baseline catalog
    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accessory_items (item_id, device_model, item_name, required)
            VALUES 
                ('ACC-BP-CUFF', 'BP-DIG-100', 'Arm Cuff', 1),
                ('ACC-BP-PWR', 'BP-DIG-100', 'Power Adapter', 1),
                ('ACC-BP-CASE', 'BP-DIG-100', 'Case', 0);
        """)
        cursor.execute("""
            INSERT INTO devices (device_id, model, category, serial_hash, status, last_status_change_at)
            VALUES ('DEV-BP-999', 'BP-DIG-100', 'Blood Pressure Monitor', 'hash123', 'on_loan', '2026-09-01T00:00:00');
        """)
        # Seed at least 6 historical loans so sample size >= 5
        for i in range(1, 7):
            l_id = f"LN-HIST-{i}"
            cursor.execute("""
                INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
                VALUES (?, 'DEV-BP-999', 'PT-ANON-001', '2026-08-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', '2026-08-10T00:00:00');
            """, (l_id,))
            cursor.execute("""
                INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
                VALUES (?, ?, 'functional', '[]', 'STF-01', '2026-08-10T00:00:00');
            """, (f"CND-H-{i}", l_id))

        # Add capacity slot
        cursor.execute("""
            INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
            VALUES ('SLOT-CLN-1', '2026-09-15', 'Morning', 'cleaning_bay', 5, 1);
        """)
        cursor.execute("""
            INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
            VALUES ('SLOT-TCH-1', '2026-09-15', 'Morning', 'technician', 5, 1);
        """)

    return db_file

def test_ready_for_reissue_when_all_rules_met(test_db):
    """When accessories complete, functional, cleaned, and acknowledged -> Ready for reissue."""
    with get_db(test_db) as conn:
        cursor = conn.cursor()
        loan_id = "LN-TEST-001"
        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES (?, 'DEV-BP-999', 'PT-ANON-100', '2026-09-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', NULL);
        """, (loan_id,))
        # Checklists: both present
        cursor.execute("""
            INSERT INTO return_checklists (checklist_id, loan_id, item_id, condition, photo_ref, recorded_by, recorded_at)
            VALUES 
                ('CHK-1', ?, 'ACC-BP-CUFF', 'present', NULL, 'STF-01', '2026-09-14T10:00:00'),
                ('CHK-2', ?, 'ACC-BP-PWR', 'present', NULL, 'STF-01', '2026-09-14T10:00:00');
        """, (loan_id, loan_id))
        # Condition: functional
        cursor.execute("""
            INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
            VALUES ('CND-1', ?, 'functional', '["clean_housing"]', 'STF-01', '2026-09-14T10:05:00');
        """, (loan_id,))
        # Cleaning: completed
        cursor.execute("""
            INSERT INTO cleaning_status (cleaning_id, loan_id, stage, technician_id, started_at, completed_at)
            VALUES ('CLN-1', ?, 'completed', 'TECH-01', '2026-09-14T10:10:00', '2026-09-14T10:30:00');
        """, (loan_id,))
        # Acknowledgement: confirmed
        cursor.execute("""
            INSERT INTO patient_acknowledgement (ack_id, loan_id, acknowledged, witness_staff_id, acknowledged_at)
            VALUES ('ACK-1', ?, 1, 'STF-01', '2026-09-14T10:35:00');
        """, (loan_id,))

        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return(loan_id)

        assert res["recommendation"] == "Ready for reissue"
        assert res["fallback_triggered"] is False
        assert res["confidence"] >= 0.90
        assert any("All gates passed" in step for step in res["rule_trail"])

def test_missing_accessory_triggers_hold(test_db):
    """Missing required accessory must recommend 'Hold — awaiting missing accessory'."""
    with get_db(test_db) as conn:
        cursor = conn.cursor()
        loan_id = "LN-TEST-MISSING"
        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES (?, 'DEV-BP-999', 'PT-ANON-101', '2026-09-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', NULL);
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO return_checklists (checklist_id, loan_id, item_id, condition, photo_ref, recorded_by, recorded_at)
            VALUES 
                ('CHK-M1', ?, 'ACC-BP-CUFF', 'present', NULL, 'STF-01', '2026-09-14T10:00:00'),
                ('CHK-M2', ?, 'ACC-BP-PWR', 'missing', NULL, 'STF-01', '2026-09-14T10:00:00');
        """, (loan_id, loan_id))
        cursor.execute("""
            INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
            VALUES ('CND-M1', ?, 'functional', '[]', 'STF-01', '2026-09-14T10:05:00');
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO cleaning_status (cleaning_id, loan_id, stage, technician_id, started_at, completed_at)
            VALUES ('CLN-M1', ?, 'completed', 'TECH-01', '2026-09-14T10:10:00', '2026-09-14T10:30:00');
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO patient_acknowledgement (ack_id, loan_id, acknowledged, witness_staff_id, acknowledged_at)
            VALUES ('ACK-M1', ?, 1, 'STF-01', '2026-09-14T10:35:00');
        """, (loan_id,))

        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return(loan_id)

        assert res["recommendation"] == "Hold — awaiting missing accessory"
        assert res["fallback_triggered"] is False
        assert any("Missing required accessories: Power Adapter" in step for step in res["rule_trail"])

def test_cleaning_not_completed_triggers_hold(test_db):
    """Incomplete cleaning must block reissue and suggest cleaning bay capacity slot."""
    with get_db(test_db) as conn:
        cursor = conn.cursor()
        loan_id = "LN-TEST-CLEAN"
        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES (?, 'DEV-BP-999', 'PT-ANON-102', '2026-09-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', NULL);
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO return_checklists (checklist_id, loan_id, item_id, condition, photo_ref, recorded_by, recorded_at)
            VALUES 
                ('CHK-C1', ?, 'ACC-BP-CUFF', 'present', NULL, 'STF-01', '2026-09-14T10:00:00'),
                ('CHK-C2', ?, 'ACC-BP-PWR', 'present', NULL, 'STF-01', '2026-09-14T10:00:00');
        """, (loan_id, loan_id))
        cursor.execute("""
            INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
            VALUES ('CND-C1', ?, 'functional', '[]', 'STF-01', '2026-09-14T10:05:00');
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO cleaning_status (cleaning_id, loan_id, stage, technician_id, started_at, completed_at)
            VALUES ('CLN-C1', ?, 'not_started', 'TECH-01', '2026-09-14T10:10:00', NULL);
        """, (loan_id,))
        cursor.execute("""
            INSERT INTO patient_acknowledgement (ack_id, loan_id, acknowledged, witness_staff_id, acknowledged_at)
            VALUES ('ACK-C1', ?, 1, 'STF-01', '2026-09-14T10:35:00');
        """, (loan_id,))

        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return(loan_id)

        assert res["recommendation"] == "Hold — needs cleaning"
        assert res["fallback_triggered"] is False
        assert any("Cleaning status: not_started" in step for step in res["rule_trail"])
        assert res["proposed_slot"] is not None

def test_safe_fallback_when_historical_baseline_insufficient(test_db):
    """If device model has fewer than N=5 historical records, trigger safe fallback to biomed."""
    with get_db(test_db) as conn:
        cursor = conn.cursor()
        # Add brand new model with 0 history
        cursor.execute("""
            INSERT INTO accessory_items (item_id, device_model, item_name, required)
            VALUES ('ACC-NEW-1', 'NEW-MODEL-XYZ', 'Sensor', 1);
        """)
        cursor.execute("""
            INSERT INTO devices (device_id, model, category, serial_hash, status, last_status_change_at)
            VALUES ('DEV-NEW-01', 'NEW-MODEL-XYZ', 'New Category', 'hashxyz', 'on_loan', '2026-09-01T00:00:00');
        """)
        loan_id = "LN-NEW-MODEL"
        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES (?, 'DEV-NEW-01', 'PT-ANON-NEW', '2026-09-01T00:00:00', '["ACC-NEW-1"]', NULL);
        """, (loan_id,))

        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return(loan_id)

        assert res["fallback_triggered"] is True
        assert res["recommendation"] == "Escalate — biomed inspection"
        assert any("insufficient for 'NEW-MODEL-XYZ': safe fallback triggered" in step for step in res["rule_trail"])
        assert res["confidence"] <= 0.50
