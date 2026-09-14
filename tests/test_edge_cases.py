"""
Explicit unit and integration tests for Section 5 edge and failure cases:
1. Unmatched device/loan ID typo -> no guess, log DATA_INTEGRITY_MISMATCH
2. Conflicting checklist entries -> surface conflict, block auto-recommendation
3. Capacity exhausted for all visible shifts -> no fabricated slot, return earliest recheck time
4. Patient acknowledgement missing/refused -> force hold for supervisor review
5. Photo evidence upload failure -> evidence_pending state, never defaults to present
"""

import pytest
import os
import sys
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import app
from src.database import init_db, get_db
from src.capacity_service import CapacityService
from src.recommendation_engine import RecommendationEngine

@pytest.fixture
def edge_db(tmp_path, monkeypatch):
    db_file = str(tmp_path / "edge_cases.db")
    monkeypatch.setenv("DB_PATH", db_file)
    init_db(db_file)

    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accessory_items (item_id, device_model, item_name, required)
            VALUES 
                ('ACC-GLUC-USB', 'GLUC-CON-300', 'USB Cable', 1),
                ('ACC-GLUC-WALL', 'GLUC-CON-300', 'Wall Charger', 1);
        """)
        cursor.execute("""
            INSERT INTO devices (device_id, model, category, serial_hash, status, last_status_change_at)
            VALUES ('DEV-GLUC-01', 'GLUC-CON-300', 'Continuous Glucose Monitor', 'hashgluc', 'on_loan', '2026-09-01T00:00:00');
        """)
        # Seed 6 baseline records
        for i in range(1, 7):
            l_id = f"LN-EDGE-BASE-{i}"
            cursor.execute("""
                INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
                VALUES (?, 'DEV-GLUC-01', 'PT-ANON-001', '2026-08-01T00:00:00', '["ACC-GLUC-USB", "ACC-GLUC-WALL"]', '2026-08-10T00:00:00');
            """, (l_id,))
            cursor.execute("""
                INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
                VALUES (?, ?, 'functional', '[]', 'STF-01', '2026-08-10T00:00:00');
            """, (f"CND-EB-{i}", l_id))

        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES ('LN-EDGE-01', 'DEV-GLUC-01', 'PT-ANON-999', '2026-09-01T00:00:00', '["ACC-GLUC-USB", "ACC-GLUC-WALL"]', NULL);
        """)

    client = TestClient(app)
    return client, db_file

def test_edge_case_1_unmatched_device_lookup(edge_db):
    """Device returned with no matching loan record -> 404, log DATA_INTEGRITY_MISMATCH event."""
    client, db_file = edge_db
    headers = {"X-User-Role": "coordinator", "X-User-Id": "STF-COORD-01"}

    # Query with a non-existent device ID typo
    resp = client.get("/api/loans/lookup?query=DEV-TYPO-UNKNOWN-999", headers=headers)
    assert resp.status_code == 404
    assert "No matching loan record found" in resp.json()["detail"]

    # Verify DATA_INTEGRITY_MISMATCH event was written to audit log
    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM events WHERE event_type = 'DATA_INTEGRITY_MISMATCH';")
        event = cursor.fetchone()
        assert event is not None
        assert "DEV-TYPO-UNKNOWN-999" in event["payload_json"]

def test_edge_case_2_conflicting_checklist_entries(edge_db):
    """Conflicting checklist entries (e.g. intake present vs tech missing) -> blocks auto-recommendation, triggers supervisor fallback."""
    client, db_file = edge_db
    headers = {"X-User-Role": "coordinator", "X-User-Id": "STF-COORD-01"}

    # Stage 1: Coordinator marks USB Cable as 'present'
    payload1 = {
        "loan_id": "LN-EDGE-01",
        "items": [
            {"item_id": "ACC-GLUC-USB", "condition": "present", "photo_ref": None},
            {"item_id": "ACC-GLUC-WALL", "condition": "present", "photo_ref": None}
        ],
        "recorded_by": "STF-COORD-01"
    }
    client.post("/api/returns/checklist", json=payload1, headers=headers)

    # Stage 2: Technician at second stage discovers USB Cable is actually 'missing' (conflict!)
    payload2 = {
        "loan_id": "LN-EDGE-01",
        "items": [
            {"item_id": "ACC-GLUC-USB", "condition": "missing", "photo_ref": None}
        ],
        "recorded_by": "TECH-01"
    }
    resp = client.post("/api/returns/checklist", json=payload2, headers={"X-User-Role": "technician", "X-User-Id": "TECH-01"})
    assert resp.status_code == 200
    assert resp.json()["conflict_detected"] is True

    # Check that recommendation engine detects this conflict
    with get_db(db_file) as conn:
        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return("LN-EDGE-01")

        assert res["recommendation"] == "Hold — pending supervisor review"
        assert res["fallback_triggered"] is True
        assert any("Conflicting checklist entries detected" in step for step in res["rule_trail"])

def test_edge_case_3_capacity_exhausted(edge_db):
    """Capacity exhausted for all shifts in window -> does not fabricate slot, reports earliest re-check time."""
    client, db_file = edge_db

    # In database, add fully booked capacity slots
    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
            VALUES 
                ('SLOT-FULL-1', '2026-09-15', 'Morning', 'cleaning_bay', 4, 4),
                ('SLOT-FULL-2', '2026-09-15', 'Afternoon', 'cleaning_bay', 4, 4);
        """)
        svc = CapacityService(conn)
        slot_info = svc.get_available_slot("cleaning_bay")

        assert slot_info["available"] is False
        assert slot_info["slot_id"] is None
        assert "No capacity available in visible scheduling window" in slot_info["label"]
        assert "Queue Overloaded" in slot_info["earliest_recheck"]

def test_edge_case_4_patient_acknowledgement_refused(edge_db):
    """Patient acknowledgement missing or refused -> forces hold for supervisor review."""
    client, db_file = edge_db
    headers = {"X-User-Role": "coordinator", "X-User-Id": "STF-COORD-01"}

    # Checklist complete
    client.post("/api/returns/checklist", json={
        "loan_id": "LN-EDGE-01",
        "items": [
            {"item_id": "ACC-GLUC-USB", "condition": "present", "photo_ref": None},
            {"item_id": "ACC-GLUC-WALL", "condition": "present", "photo_ref": None}
        ],
        "recorded_by": "STF-COORD-01"
    }, headers=headers)

    # Functional condition
    client.post("/api/returns/condition", json={
        "loan_id": "LN-EDGE-01",
        "condition_code": "functional",
        "wear_tags": [],
        "recorded_by": "STF-COORD-01"
    }, headers=headers)

    # Cleaning completed
    client.post("/api/returns/cleaning", json={
        "loan_id": "LN-EDGE-01",
        "stage": "completed",
        "technician_id": "TECH-01"
    }, headers=headers)

    # Patient acknowledgement refused: acknowledged = False
    client.post("/api/returns/acknowledgement", json={
        "loan_id": "LN-EDGE-01",
        "acknowledged": False,
        "witness_staff_id": "STF-COORD-01"
    }, headers=headers)

    # Generate recommendation
    resp = client.post("/api/returns/recommend", json={"loan_id": "LN-EDGE-01"}, headers=headers)
    assert resp.status_code == 200
    rec = resp.json()
    assert rec["recommendation"] == "Hold — pending supervisor review"
    assert any("Patient acknowledgement: unconfirmed/refused" in step for step in rec["rule_trail"])

def test_edge_case_5_photo_evidence_upload_failure(edge_db):
    """Photo evidence upload failure -> item kept in evidence_pending state rather than defaulting to present."""
    client, db_file = edge_db
    headers = {"X-User-Role": "coordinator", "X-User-Id": "STF-COORD-01"}

    # Mock upload with simulate_failure = True
    resp = client.post("/api/returns/upload-evidence-mock?item_id=ACC-GLUC-USB&simulate_failure=true", headers=headers)
    assert resp.status_code == 502
    assert "Item marked evidence_pending" in resp.json()["detail"]

    # Now record the item condition explicitly as 'evidence_pending'
    chk_resp = client.post("/api/returns/checklist", json={
        "loan_id": "LN-EDGE-01",
        "items": [
            {"item_id": "ACC-GLUC-USB", "condition": "evidence_pending", "photo_ref": None},
            {"item_id": "ACC-GLUC-WALL", "condition": "present", "photo_ref": None}
        ],
        "recorded_by": "STF-COORD-01"
    }, headers=headers)
    assert chk_resp.status_code == 200

    # Ensure recommendation blocks reissue
    with get_db(db_file) as conn:
        engine = RecommendationEngine(conn)
        rec = engine.evaluate_loan_return("LN-EDGE-01")
        assert rec["recommendation"] != "Ready for reissue"
        assert any("Photo evidence pending" in step for step in rec["rule_trail"])
