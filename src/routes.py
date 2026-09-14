"""
FastAPI route handlers implementing the full loan return, accessory reconciliation,
recommendation engine, human confirmation gate, capacity checks, and audit log.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import uuid
import json

from src.database import get_db
from src.models import (
    ChecklistSubmission, ConditionSubmission, CleaningSubmission,
    AcknowledgementSubmission, RecommendationRequest, ConfirmationSubmission,
    RuleTrailResponse, UserRole, DecisionType, DeviceStatus
)
from src.recommendation_engine import RecommendationEngine
from src.capacity_service import CapacityService
from src.auth import get_current_user, require_roles

router = APIRouter()

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def record_event(conn, loan_id: Optional[str], event_type: str, payload: dict, actor_id: str):
    """Appends an immutable record to the events audit log."""
    event_id = f"EVT-{uuid.uuid4().hex[:12].upper()}"
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO events (event_id, loan_id, event_type, payload_json, actor_id, occurred_at)
        VALUES (?, ?, ?, ?, ?, ?);
    """, (event_id, loan_id, event_type, json.dumps(payload), actor_id, now_iso()))
    conn.commit()
    return event_id

# 1. Devices List
@router.get("/devices")
def list_devices(status_filter: Optional[str] = None):
    with get_db() as conn:
        cursor = conn.cursor()
        if status_filter:
            cursor.execute("SELECT * FROM devices WHERE status = ? ORDER BY device_id ASC;", (status_filter,))
        else:
            cursor.execute("SELECT * FROM devices ORDER BY device_id ASC;")
        return [dict(row) for row in cursor.fetchall()]

# 2. Loan Lookup
@router.get("/loans/lookup")
def lookup_loan(query: str = Query(..., description="Device ID or Loan ID to look up"), user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        clean_q = query.strip()
        
        # Search by loan_id or device_id
        cursor.execute("""
            SELECT l.loan_id, l.device_id, l.patient_ref_id, l.issued_at, 
                   l.issued_accessory_manifest_json, l.returned_at,
                   d.model as device_model, d.category as device_category, d.status as device_status
            FROM loans l
            JOIN devices d ON l.device_id = d.device_id
            WHERE l.loan_id = ? OR l.device_id = ?
            ORDER BY l.issued_at DESC LIMIT 1;
        """, (clean_q, clean_q))
        loan = cursor.fetchone()

        if not loan:
            # Edge Case 1: Device returned with no matching loan record
            # Refuse to guess, log data integrity mismatch event
            record_event(
                conn=conn,
                loan_id=None,
                event_type="DATA_INTEGRITY_MISMATCH",
                payload={"searched_query": clean_q, "error": "No matching active loan record found for scanned identifier."},
                actor_id=user["user_id"]
            )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No matching loan record found for identifier '{clean_q}'. A Data Integrity Mismatch event has been logged for supervisor review."
            )

        loan_id = loan["loan_id"]
        manifest = json.loads(loan["issued_accessory_manifest_json"])

        # Fetch accessory items details
        cursor.execute("""
            SELECT item_id, item_name, required FROM accessory_items
            WHERE device_model = ?;
        """, (loan["device_model"],))
        items_catalog = {row["item_id"]: dict(row) for row in cursor.fetchall()}

        manifest_with_names = []
        for item_id in manifest:
            cat = items_catalog.get(item_id, {"item_name": item_id, "required": 1})
            manifest_with_names.append({
                "item_id": item_id,
                "item_name": cat["item_name"],
                "required": bool(cat["required"])
            })

        # Fetch current checklists
        cursor.execute("""
            SELECT rc.checklist_id, rc.item_id, rc.condition, rc.photo_ref, rc.recorded_by, rc.recorded_at,
                   ai.item_name
            FROM return_checklists rc
            JOIN accessory_items ai ON rc.item_id = ai.item_id
            WHERE rc.loan_id = ?
            ORDER BY rc.recorded_at ASC;
        """, (loan_id,))
        checklists = [dict(row) for row in cursor.fetchall()]

        # Fetch current condition
        cursor.execute("""
            SELECT condition_id, condition_code, wear_tags, recorded_by, recorded_at
            FROM return_condition
            WHERE loan_id = ? ORDER BY recorded_at DESC LIMIT 1;
        """, (loan_id,))
        cond_row = cursor.fetchone()
        current_condition = None
        if cond_row:
            current_condition = dict(cond_row)
            current_condition["wear_tags"] = json.loads(cond_row["wear_tags"])

        # Fetch current cleaning
        cursor.execute("""
            SELECT cleaning_id, stage, technician_id, started_at, completed_at
            FROM cleaning_status
            WHERE loan_id = ? ORDER BY started_at DESC LIMIT 1;
        """, (loan_id,))
        clean_row = cursor.fetchone()
        current_cleaning = dict(clean_row) if clean_row else None

        # Fetch current acknowledgement
        cursor.execute("""
            SELECT ack_id, acknowledged, witness_staff_id, acknowledged_at
            FROM patient_acknowledgement
            WHERE loan_id = ? ORDER BY acknowledged_at DESC LIMIT 1;
        """, (loan_id,))
        ack_row = cursor.fetchone()
        current_ack = dict(ack_row) if ack_row else None

        # Fetch latest recommendation and confirmation
        cursor.execute("""
            SELECT rec_id, recommendation, rule_trail_json, confidence_score, fallback_triggered, generated_at
            FROM recommendations
            WHERE loan_id = ? ORDER BY generated_at DESC LIMIT 1;
        """, (loan_id,))
        rec_row = cursor.fetchone()
        latest_rec = None
        latest_conf = None
        if rec_row:
            latest_rec = dict(rec_row)
            latest_rec["rule_trail"] = json.loads(rec_row["rule_trail_json"])
            cursor.execute("""
                SELECT confirm_id, confirmed_by, decision, override_reason_code, override_justification, confirmed_at
                FROM human_confirmations
                WHERE rec_id = ? ORDER BY confirmed_at DESC LIMIT 1;
            """, (rec_row["rec_id"],))
            conf_row = cursor.fetchone()
            if conf_row:
                latest_conf = dict(conf_row)

        record_event(
            conn=conn,
            loan_id=loan_id,
            event_type="LOAN_LOOKUP",
            payload={"scanned_query": clean_q, "device_id": loan["device_id"]},
            actor_id=user["user_id"]
        )

        return {
            "loan_id": loan["loan_id"],
            "device_id": loan["device_id"],
            "device_model": loan["device_model"],
            "device_category": loan["device_category"],
            "device_status": loan["device_status"],
            "patient_ref_id": loan["patient_ref_id"],
            "issued_at": loan["issued_at"],
            "issued_accessory_manifest": manifest_with_names,
            "returned_at": loan["returned_at"],
            "current_checklists": checklists,
            "current_condition": current_condition,
            "current_cleaning": current_cleaning,
            "current_acknowledgement": current_ack,
            "latest_recommendation": latest_rec,
            "latest_confirmation": latest_conf
        }

# 3. Accessory Reconciliation Submission
@router.post("/returns/checklist")
def submit_checklist(submission: ChecklistSubmission, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Verify loan exists
        cursor.execute("SELECT loan_id, device_id FROM loans WHERE loan_id = ?;", (submission.loan_id,))
        loan = cursor.fetchone()
        if not loan:
            raise HTTPException(status_code=404, detail="Loan not found.")

        # Update device to in_intake status if it was on_loan
        cursor.execute("""
            UPDATE devices SET status = 'in_intake', last_status_change_at = ?
            WHERE device_id = ? AND status = 'on_loan';
        """, (now_iso(), loan["device_id"]))

        recorded_entries = []
        for item in submission.items:
            chk_id = f"CHK-{uuid.uuid4().hex[:10].upper()}"
            cursor.execute("""
                INSERT INTO return_checklists (checklist_id, loan_id, item_id, condition, photo_ref, recorded_by, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (chk_id, submission.loan_id, item.item_id, item.condition.value, item.photo_ref, submission.recorded_by, now_iso()))
            recorded_entries.append({
                "item_id": item.item_id,
                "condition": item.condition.value,
                "photo_ref": item.photo_ref
            })

        # Check for conflicts (Edge Case 2)
        cursor.execute("""
            SELECT item_id, COUNT(DISTINCT condition) as cond_count
            FROM return_checklists
            WHERE loan_id = ?
            GROUP BY item_id
            HAVING cond_count > 1;
        """, (submission.loan_id,))
        conflict_rows = cursor.fetchall()
        has_conflict = len(conflict_rows) > 0

        event_type = "CHECKLIST_CONFLICT_DETECTED" if has_conflict else "CHECKLIST_RECORDED"
        record_event(
            conn=conn,
            loan_id=submission.loan_id,
            event_type=event_type,
            payload={
                "entries": recorded_entries,
                "conflicts": [dict(r) for r in conflict_rows] if has_conflict else []
            },
            actor_id=user["user_id"]
        )

        return {
            "success": True,
            "recorded_count": len(recorded_entries),
            "conflict_detected": has_conflict
        }

# 4. Return Condition Capture
@router.post("/returns/condition")
def submit_condition(submission: ConditionSubmission, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT loan_id FROM loans WHERE loan_id = ?;", (submission.loan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Loan not found.")

        cond_id = f"CND-{uuid.uuid4().hex[:10].upper()}"
        cursor.execute("""
            INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (cond_id, submission.loan_id, submission.condition_code.value, json.dumps(submission.wear_tags), submission.recorded_by, now_iso()))

        record_event(
            conn=conn,
            loan_id=submission.loan_id,
            event_type="CONDITION_RECORDED",
            payload={"condition_code": submission.condition_code.value, "wear_tags": submission.wear_tags},
            actor_id=user["user_id"]
        )

        return {"success": True, "condition_id": cond_id}

# 5. Cleaning Status Capture
@router.post("/returns/cleaning")
def submit_cleaning(submission: CleaningSubmission, user: dict = Depends(get_current_user)):
    # Cleaning requires technician or coordinator role
    require_roles([UserRole.COORDINATOR, UserRole.TECHNICIAN, UserRole.SUPERVISOR])(user)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT loan_id FROM loans WHERE loan_id = ?;", (submission.loan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Loan not found.")

        clean_id = f"CLN-{uuid.uuid4().hex[:10].upper()}"
        now = now_iso()
        completed_at = now if submission.stage in ["completed", "failed"] else None
        
        cursor.execute("""
            INSERT INTO cleaning_status (cleaning_id, loan_id, stage, technician_id, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?);
        """, (clean_id, submission.loan_id, submission.stage.value, submission.technician_id, now, completed_at))

        record_event(
            conn=conn,
            loan_id=submission.loan_id,
            event_type="CLEANING_UPDATED",
            payload={"stage": submission.stage.value, "technician_id": submission.technician_id},
            actor_id=user["user_id"]
        )

        return {"success": True, "cleaning_id": clean_id}

# 6. Patient Acknowledgement
@router.post("/returns/acknowledgement")
def submit_acknowledgement(submission: AcknowledgementSubmission, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT loan_id FROM loans WHERE loan_id = ?;", (submission.loan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Loan not found.")

        ack_id = f"ACK-{uuid.uuid4().hex[:10].upper()}"
        cursor.execute("""
            INSERT INTO patient_acknowledgement (ack_id, loan_id, acknowledged, witness_staff_id, acknowledged_at)
            VALUES (?, ?, ?, ?, ?);
        """, (ack_id, submission.loan_id, 1 if submission.acknowledged else 0, submission.witness_staff_id, now_iso()))

        record_event(
            conn=conn,
            loan_id=submission.loan_id,
            event_type="ACKNOWLEDGEMENT_RECORDED",
            payload={"acknowledged": submission.acknowledged, "witness_staff_id": submission.witness_staff_id},
            actor_id=user["user_id"]
        )

        return {"success": True, "ack_id": ack_id}

# 7. Recommendation Engine
@router.post("/returns/recommend", response_model=RuleTrailResponse)
def generate_recommendation(req: RecommendationRequest, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT loan_id FROM loans WHERE loan_id = ?;", (req.loan_id,))
        if not cursor.fetchone():
            raise HTTPException(status_code=404, detail="Loan not found.")

        engine = RecommendationEngine(conn)
        res = engine.evaluate_loan_return(req.loan_id)

        rec_id = f"REC-{uuid.uuid4().hex[:10].upper()}"
        cursor.execute("""
            INSERT INTO recommendations (rec_id, loan_id, recommendation, rule_trail_json, confidence_score, fallback_triggered, generated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (rec_id, req.loan_id, res["recommendation"], json.dumps(res["rule_trail"]), res["confidence"], 1 if res["fallback_triggered"] else 0, now_iso()))

        record_event(
            conn=conn,
            loan_id=req.loan_id,
            event_type="RECOMMENDATION_GENERATED",
            payload={
                "rec_id": rec_id,
                "recommendation": res["recommendation"],
                "confidence": res["confidence"],
                "fallback_triggered": res["fallback_triggered"]
            },
            actor_id=user["user_id"]
        )

        return res

# 8. Human Confirmation Gate (Approve / Override)
@router.post("/returns/confirm")
def confirm_recommendation(submission: ConfirmationSubmission, user: dict = Depends(get_current_user)):
    # Human confirmation is restricted to supervisor and coordinator
    require_roles([UserRole.COORDINATOR, UserRole.SUPERVISOR])(user)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT r.rec_id, r.loan_id, r.recommendation, l.device_id
            FROM recommendations r
            JOIN loans l ON r.loan_id = l.loan_id
            WHERE r.rec_id = ?;
        """, (submission.rec_id,))
        rec = cursor.fetchone()
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation record not found.")

        loan_id = rec["loan_id"]
        device_id = rec["device_id"]
        rec_text = rec["recommendation"]

        confirm_id = f"CNF-{uuid.uuid4().hex[:10].upper()}"
        now = now_iso()

        # Insert human confirmation
        cursor.execute("""
            INSERT INTO human_confirmations (confirm_id, rec_id, confirmed_by, decision, override_reason_code, override_justification, confirmed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?);
        """, (
            confirm_id,
            submission.rec_id,
            submission.confirmed_by,
            submission.decision.value,
            submission.override_reason_code.value if submission.override_reason_code else None,
            submission.override_justification,
            now
        ))

        # Determine target device status
        if submission.decision == DecisionType.APPROVED:
            if rec_text == "Ready for reissue":
                new_status = DeviceStatus.AVAILABLE.value
            elif rec_text == "Hold — needs cleaning":
                new_status = DeviceStatus.HOLD_CLEANING.value
            elif rec_text == "Hold — awaiting missing accessory":
                new_status = DeviceStatus.HOLD_MISSING_ACCESSORY.value
            elif rec_text == "Escalate — biomed inspection":
                new_status = DeviceStatus.ESCALATED_BIOMED.value
            else:
                new_status = DeviceStatus.IN_INTAKE.value
        else:
            # Overridden: Check override reason
            if submission.override_reason_code in ["ACCESSORY_REPLACED_FROM_STOCK", "BIOMED_WAIVER"]:
                new_status = DeviceStatus.AVAILABLE.value
            elif submission.override_reason_code == "MANUAL_DEEP_CLEAN_VERIFIED":
                new_status = DeviceStatus.AVAILABLE.value
            else:
                new_status = DeviceStatus.ESCALATED_BIOMED.value

        # Update Device Status and Loan returned_at timestamp
        cursor.execute("""
            UPDATE devices
            SET status = ?, last_status_change_at = ?
            WHERE device_id = ?;
        """, (new_status, now, device_id))

        cursor.execute("""
            UPDATE loans
            SET returned_at = ?
            WHERE loan_id = ? AND returned_at IS NULL;
        """, (now, loan_id))

        event_type = "CONFIRMATION_OVERRIDDEN" if submission.decision == DecisionType.OVERRIDDEN else "CONFIRMATION_APPROVED"
        record_event(
            conn=conn,
            loan_id=loan_id,
            event_type=event_type,
            payload={
                "confirm_id": confirm_id,
                "rec_id": submission.rec_id,
                "decision": submission.decision.value,
                "override_reason_code": submission.override_reason_code.value if submission.override_reason_code else None,
                "override_justification": submission.override_justification,
                "resulting_device_status": new_status
            },
            actor_id=user["user_id"]
        )

        record_event(
            conn=conn,
            loan_id=loan_id,
            event_type="STATUS_TRANSITIONED",
            payload={"device_id": device_id, "new_status": new_status},
            actor_id=user["user_id"]
        )

        return {
            "success": True,
            "confirm_id": confirm_id,
            "decision": submission.decision.value,
            "new_device_status": new_status
        }

# 9. Shift Capacity & Slots
@router.get("/capacity")
def get_capacity():
    with get_db() as conn:
        svc = CapacityService(conn)
        return {
            "slots": svc.get_capacity_summary(),
            "next_cleaning_bay": svc.get_available_slot("cleaning_bay"),
            "next_technician": svc.get_available_slot("technician")
        }

# 10. Audit Events Query (Restricted to Supervisor and Auditor)
@router.get("/events")
def get_events(limit: int = 50, offset: int = 0, loan_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    require_roles([UserRole.SUPERVISOR, UserRole.AUDITOR])(user)
    with get_db() as conn:
        cursor = conn.cursor()
        if loan_id:
            cursor.execute("""
                SELECT * FROM events
                WHERE loan_id = ?
                ORDER BY occurred_at DESC
                LIMIT ? OFFSET ?;
            """, (loan_id, limit, offset))
        else:
            cursor.execute("""
                SELECT * FROM events
                ORDER BY occurred_at DESC
                LIMIT ? OFFSET ?;
            """, (limit, offset))
        rows = [dict(r) for r in cursor.fetchall()]
        for r in rows:
            r["payload"] = json.loads(r["payload_json"])
        return rows

# 11. Reporting Dashboard Metrics
@router.get("/reporting/dashboard")
def get_dashboard_metrics():
    with get_db() as conn:
        cursor = conn.cursor()

        # Total devices by status
        cursor.execute("SELECT status, COUNT(*) as count FROM devices GROUP BY status;")
        device_status_dist = {r["status"]: r["count"] for r in cursor.fetchall()}

        # Total loans
        cursor.execute("SELECT COUNT(*) as total_loans FROM loans;")
        total_loans = cursor.fetchone()["total_loans"]

        # Missing accessory trend by device model
        cursor.execute("""
            SELECT d.model, COUNT(rc.checklist_id) as missing_count
            FROM return_checklists rc
            JOIN loans l ON rc.loan_id = l.loan_id
            JOIN devices d ON l.device_id = d.device_id
            WHERE rc.condition = 'missing'
            GROUP BY d.model;
        """)
        missing_by_model = {r["model"]: r["missing_count"] for r in cursor.fetchall()}

        # Override rate
        cursor.execute("SELECT COUNT(*) as total_confirmations FROM human_confirmations;")
        total_confirmations = cursor.fetchone()["total_confirmations"]

        cursor.execute("SELECT COUNT(*) as override_count FROM human_confirmations WHERE decision = 'overridden';")
        override_count = cursor.fetchone()["override_count"]

        override_rate = round((override_count / total_confirmations * 100), 1) if total_confirmations > 0 else 0.0

        # Override reasons distribution
        cursor.execute("""
            SELECT override_reason_code, COUNT(*) as count
            FROM human_confirmations
            WHERE decision = 'overridden'
            GROUP BY override_reason_code;
        """)
        override_reasons = {r["override_reason_code"]: r["count"] for r in cursor.fetchall()}

        # Capacity utilization
        cursor.execute("""
            SELECT role, SUM(capacity) as total_cap, SUM(booked) as total_booked
            FROM capacity_slots
            GROUP BY role;
        """)
        cap_by_role = {}
        for r in cursor.fetchall():
            pct = round((r["total_booked"] / r["total_cap"] * 100), 1) if r["total_cap"] > 0 else 0.0
            cap_by_role[r["role"]] = {"capacity": r["total_cap"], "booked": r["total_booked"], "utilization_pct": pct}

        return {
            "total_devices": sum(device_status_dist.values()),
            "device_status_distribution": device_status_dist,
            "total_loans": total_loans,
            "missing_accessories_by_model": missing_by_model,
            "total_confirmations": total_confirmations,
            "override_count": override_count,
            "override_rate_pct": override_rate,
            "override_reasons_distribution": override_reasons,
            "capacity_by_role": cap_by_role
        }

# 12. Mock Photo Evidence Upload
@router.post("/returns/upload-evidence-mock")
def upload_photo_evidence_mock(
    item_id: str,
    simulate_failure: bool = False,
    user: dict = Depends(get_current_user)
):
    """
    Simulates photo evidence attachment. If simulate_failure is true,
    simulates network/storage failure as in Edge Case 5.
    """
    if simulate_failure:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Photo evidence upload failed: image storage connection timeout. Item marked evidence_pending."
        )
    photo_ref = f"photos/evidence_{item_id}_{uuid.uuid4().hex[:8]}.jpg"
    return {"success": True, "photo_ref": photo_ref}
