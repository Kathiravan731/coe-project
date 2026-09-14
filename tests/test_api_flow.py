"""
End-to-end integration test for the full loan return workflow via FastAPI TestClient:
Lookup -> Checklist -> Condition -> Cleaning -> Acknowledgement -> Recommendation -> Confirmation -> Device Status Update.
"""

import pytest
import os
import sys
from fastapi.testclient import TestClient

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.main import app
from src.database import init_db, get_db

@pytest.fixture
def api_client(tmp_path, monkeypatch):
    """Sets up an isolated test database and FastAPI TestClient."""
    db_file = str(tmp_path / "integration_test.db")
    monkeypatch.setenv("DB_PATH", db_file)
    init_db(db_file)

    # Seed initial entities
    with get_db(db_file) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO accessory_items (item_id, device_model, item_name, required)
            VALUES 
                ('ACC-BP-CUFF', 'BP-DIG-100', 'Arm Cuff', 1),
                ('ACC-BP-PWR', 'BP-DIG-100', 'Power Adapter', 1);
        """)
        cursor.execute("""
            INSERT INTO devices (device_id, model, category, serial_hash, status, last_status_change_at)
            VALUES ('DEV-BP-INT', 'BP-DIG-100', 'Blood Pressure Monitor', 'hashint', 'on_loan', '2026-09-01T00:00:00');
        """)
        # Seed 6 baseline records
        for i in range(1, 7):
            l_id = f"LN-BASE-{i}"
            cursor.execute("""
                INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
                VALUES (?, 'DEV-BP-INT', 'PT-ANON-001', '2026-08-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', '2026-08-10T00:00:00');
            """, (l_id,))
            cursor.execute("""
                INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
                VALUES (?, ?, 'functional', '[]', 'STF-01', '2026-08-10T00:00:00');
            """, (f"CND-B-{i}", l_id))

        # Seed active target loan
        cursor.execute("""
            INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
            VALUES ('LN-INT-001', 'DEV-BP-INT', 'PT-ANON-7788', '2026-09-01T00:00:00', '["ACC-BP-CUFF", "ACC-BP-PWR"]', NULL);
        """)

        # Seed capacity slot
        cursor.execute("""
            INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
            VALUES ('SLOT-CLN-TEST', '2026-09-15', 'Morning', 'cleaning_bay', 10, 2);
        """)

    client = TestClient(app)
    return client

def test_full_return_lifecycle_happy_path(api_client):
    headers_coord = {"X-User-Role": "coordinator", "X-User-Id": "STF-COORD-01"}
    headers_super = {"X-User-Role": "supervisor", "X-User-Id": "SUP-01"}

    # 1. Lookup Loan
    resp = api_client.get("/api/loans/lookup?query=LN-INT-001", headers=headers_coord)
    assert resp.status_code == 200
    data = resp.json()
    assert data["loan_id"] == "LN-INT-001"
    assert data["device_id"] == "DEV-BP-INT"
    assert len(data["issued_accessory_manifest"]) == 2

    # 2. Submit Checklist (both present)
    chk_payload = {
        "loan_id": "LN-INT-001",
        "items": [
            {"item_id": "ACC-BP-CUFF", "condition": "present", "photo_ref": None},
            {"item_id": "ACC-BP-PWR", "condition": "present", "photo_ref": None}
        ],
        "recorded_by": "STF-COORD-01"
    }
    resp = api_client.post("/api/returns/checklist", json=chk_payload, headers=headers_coord)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 3. Submit Condition with valid wear tags
    cond_payload = {
        "loan_id": "LN-INT-001",
        "condition_code": "functional",
        "wear_tags": ["clean_housing"],
        "recorded_by": "STF-COORD-01"
    }
    resp = api_client.post("/api/returns/condition", json=cond_payload, headers=headers_coord)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # Test wear tag rejection on free-text clinical notes (privacy enforcement)
    invalid_cond_payload = {
        "loan_id": "LN-INT-001",
        "condition_code": "functional",
        "wear_tags": ["patient had high blood pressure yesterday"], # FORBIDDEN
        "recorded_by": "STF-COORD-01"
    }
    resp = api_client.post("/api/returns/condition", json=invalid_cond_payload, headers=headers_coord)
    assert resp.status_code == 422 # Pydantic validation rejected free-text note

    # 4. Submit Cleaning Status
    clean_payload = {
        "loan_id": "LN-INT-001",
        "stage": "completed",
        "technician_id": "TECH-01"
    }
    resp = api_client.post("/api/returns/cleaning", json=clean_payload, headers=headers_coord)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 5. Submit Patient Acknowledgement
    ack_payload = {
        "loan_id": "LN-INT-001",
        "acknowledged": True,
        "witness_staff_id": "STF-COORD-01"
    }
    resp = api_client.post("/api/returns/acknowledgement", json=ack_payload, headers=headers_coord)
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    # 6. Generate Recommendation
    rec_payload = {"loan_id": "LN-INT-001"}
    resp = api_client.post("/api/returns/recommend", json=rec_payload, headers=headers_coord)
    assert resp.status_code == 200
    rec_data = resp.json()
    assert rec_data["recommendation"] == "Ready for reissue"
    assert rec_data["confidence"] >= 0.90
    assert rec_data["fallback_triggered"] is False
    assert len(rec_data["rule_trail"]) >= 4

    # Fetch latest recommendation ID
    lookup_after_rec = api_client.get("/api/loans/lookup?query=LN-INT-001", headers=headers_coord).json()
    rec_id = lookup_after_rec["latest_recommendation"]["rec_id"]

    # 7. Human Confirmation Gate: Approve
    conf_payload = {
        "rec_id": rec_id,
        "decision": "approved",
        "confirmed_by": "SUP-01"
    }
    resp = api_client.post("/api/returns/confirm", json=conf_payload, headers=headers_super)
    assert resp.status_code == 200
    assert resp.json()["new_device_status"] == "available"

    # 8. Check Device status is now 'available'
    dev_resp = api_client.get("/api/devices?status_filter=available")
    assert dev_resp.status_code == 200
    avail_devices = [d["device_id"] for d in dev_resp.json()]
    assert "DEV-BP-INT" in avail_devices

    # 9. Verify Audit Events Log
    evt_resp = api_client.get("/api/events?loan_id=LN-INT-001", headers=headers_super)
    assert evt_resp.status_code == 200
    event_types = [e["event_type"] for e in evt_resp.json()]
    assert "LOAN_LOOKUP" in event_types
    assert "CHECKLIST_RECORDED" in event_types
    assert "CONDITION_RECORDED" in event_types
    assert "CLEANING_UPDATED" in event_types
    assert "ACKNOWLEDGEMENT_RECORDED" in event_types
    assert "RECOMMENDATION_GENERATED" in event_types
    assert "CONFIRMATION_APPROVED" in event_types
    assert "STATUS_TRANSITIONED" in event_types
