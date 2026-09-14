"""
Explainable Recommendation Engine with deterministic rule trails,
safe fallback under uncertainty, and capacity-aware turnaround slot proposals.
"""

import sqlite3
import json
from typing import Dict, Any, List
from src.capacity_service import CapacityService

MIN_HISTORICAL_BASELINE_COUNT = 5

class RecommendationEngine:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.capacity_service = CapacityService(conn)

    def evaluate_loan_return(self, loan_id: str) -> Dict[str, Any]:
        """
        Evaluates a loan return record against deterministic clinical/operations rules.
        Returns recommendation, confidence score, explicit rule trail, and fallback status.
        """
        cursor = self.conn.cursor()

        # 1. Fetch Loan & Device info
        cursor.execute("""
            SELECT l.loan_id, l.device_id, l.patient_ref_id, l.issued_accessory_manifest_json,
                   d.model as device_model, d.category as device_category, d.status as device_status
            FROM loans l
            JOIN devices d ON l.device_id = d.device_id
            WHERE l.loan_id = ?;
        """, (loan_id,))
        loan = cursor.fetchone()
        if not loan:
            raise ValueError(f"Loan record '{loan_id}' not found.")

        device_model = loan["device_model"]
        issued_manifest = json.loads(loan["issued_accessory_manifest_json"])

        rule_trail: List[str] = []
        fallback_triggered = False
        confidence = 1.00
        proposed_slot = None
        next_action_route = None

        # 2. Check Historical Baseline Sample Size for this Device Model
        cursor.execute("""
            SELECT COUNT(*) as history_count
            FROM loans l
            JOIN devices d ON l.device_id = d.device_id
            WHERE d.model = ? AND l.returned_at IS NOT NULL;
        """, (device_model,))
        history_count = cursor.fetchone()["history_count"]

        # Calculate historical defect rate
        cursor.execute("""
            SELECT COUNT(*) as defect_count
            FROM return_condition rc
            JOIN loans l ON rc.loan_id = l.loan_id
            JOIN devices d ON l.device_id = d.device_id
            WHERE d.model = ? AND rc.condition_code IN ('damaged', 'non_functional', 'needs_inspection');
        """, (device_model,))
        historical_defects = cursor.fetchone()["defect_count"]
        historical_defect_rate = (historical_defects / history_count) if history_count > 0 else 0.0

        if history_count < MIN_HISTORICAL_BASELINE_COUNT:
            fallback_triggered = True
            confidence = 0.45
            rule_trail.append(
                f"Historical baseline sample size ({history_count}/{MIN_HISTORICAL_BASELINE_COUNT}) "
                f"insufficient for '{device_model}': safe fallback triggered to biomed inspection."
            )
            slot_info = self.capacity_service.get_available_slot("technician")
            proposed_slot = slot_info["label"]
            return {
                "recommendation": "Escalate — biomed inspection",
                "confidence": round(confidence, 2),
                "rule_trail": rule_trail,
                "fallback_triggered": True,
                "proposed_slot": proposed_slot,
                "next_action_route": "Biomedical Inspection Queue"
            }

        # 3. Check Accessory Checklist Completeness and State
        cursor.execute("""
            SELECT rc.item_id, rc.condition, rc.photo_ref, ai.item_name, ai.required
            FROM return_checklists rc
            JOIN accessory_items ai ON rc.item_id = ai.item_id
            WHERE rc.loan_id = ?;
        """, (loan_id,))
        checklist_rows = cursor.fetchall()
        recorded_items = {row["item_id"]: dict(row) for row in checklist_rows}

        # Check for conflicting entries on the same item (edge case 2)
        cursor.execute("""
            SELECT item_id, COUNT(DISTINCT condition) as distinct_conditions
            FROM return_checklists
            WHERE loan_id = ?
            GROUP BY item_id
            HAVING distinct_conditions > 1;
        """, (loan_id,))
        conflict = cursor.fetchone()
        if conflict:
            fallback_triggered = True
            rule_trail.append(
                f"Conflicting checklist entries detected for accessory '{conflict['item_id']}': "
                f"recorded conditions disagree across intake stages. Safe fallback triggered to supervisor review."
            )
            return {
                "recommendation": "Hold — pending supervisor review",
                "confidence": 0.20,
                "rule_trail": rule_trail,
                "fallback_triggered": True,
                "proposed_slot": None,
                "next_action_route": "Supervisor Resolution Queue"
            }

        # Validate completeness against original issue manifest
        missing_required = []
        damaged_accessories = []
        pending_evidence = []
        total_required = len(issued_manifest)
        present_required = 0

        for item_id in issued_manifest:
            if item_id not in recorded_items:
                # Required input missing! Safe fallback
                fallback_triggered = True
                rule_trail.append(f"Checklist incomplete: item '{item_id}' from issue manifest has not been reconciled.")
            else:
                entry = recorded_items[item_id]
                cond = entry["condition"]
                if cond == "present":
                    present_required += 1
                elif cond == "missing":
                    missing_required.append(entry["item_name"])
                elif cond == "damaged":
                    damaged_accessories.append(entry["item_name"])
                elif cond == "evidence_pending":
                    pending_evidence.append(entry["item_name"])

        rule_trail.append(
            f"Accessory checklist: {present_required}/{total_required} present "
            f"(rule: all required items from issue manifest must be present)"
        )

        # 4. Check Return Condition & Wear Tags
        cursor.execute("""
            SELECT condition_code, wear_tags
            FROM return_condition
            WHERE loan_id = ?
            ORDER BY recorded_at DESC LIMIT 1;
        """, (loan_id,))
        cond_row = cursor.fetchone()

        if not cond_row:
            fallback_triggered = True
            rule_trail.append("Return condition not yet recorded: safe fallback triggered.")
            condition_code = None
            wear_tags = []
        else:
            condition_code = cond_row["condition_code"]
            wear_tags = json.loads(cond_row["wear_tags"])
            rule_trail.append(
                f"Return condition: {condition_code} "
                f"(rule: functional required for direct reissue; needs_inspection/damaged routes to biomed)"
            )
            if wear_tags:
                rule_trail.append(f"Visible wear tags: {', '.join(wear_tags)} (structured non-PHI rubric)")
                # Deduct confidence slightly for each wear tag
                confidence -= (0.02 * len(wear_tags))

        # 5. Check Cleaning Status
        cursor.execute("""
            SELECT stage, technician_id, completed_at
            FROM cleaning_status
            WHERE loan_id = ?
            ORDER BY started_at DESC LIMIT 1;
        """, (loan_id,))
        cleaning_row = cursor.fetchone()

        if not cleaning_row:
            cleaning_stage = "not_started"
            rule_trail.append("Cleaning status: not_started (rule: reissue blocked until cleaning=completed)")
        else:
            cleaning_stage = cleaning_row["stage"]
            rule_trail.append(
                f"Cleaning status: {cleaning_stage} "
                f"(rule: reissue strictly blocked until cleaning=completed by authorized technician)"
            )

        # 6. Check Patient Acknowledgement (Section 2 & Edge Case 4)
        cursor.execute("""
            SELECT acknowledged, witness_staff_id, acknowledged_at
            FROM patient_acknowledgement
            WHERE loan_id = ?
            ORDER BY acknowledged_at DESC LIMIT 1;
        """, (loan_id,))
        ack_row = cursor.fetchone()
        patient_acknowledged = ack_row["acknowledged"] if ack_row else None

        if patient_acknowledged is None or patient_acknowledged == 0:
            rule_trail.append(
                "Patient acknowledgement: unconfirmed/refused (rule: patient hand-back acknowledgement "
                "required to resolve condition/accessory liability; hold for supervisor review)"
            )

        # Adjust confidence for historical defect rate
        confidence -= (0.10 * historical_defect_rate)

        # 7. Synthesize Recommendation Hierarchy
        recommendation = ""

        # Priority 1: Damaged device, Non-functional, or Damaged accessories -> Escalate to Biomed
        if (condition_code in ["damaged", "non_functional"] or 
            len(damaged_accessories) > 0 or 
            condition_code == "needs_inspection"):
            
            recommendation = "Escalate — biomed inspection"
            next_action_route = "Biomedical Engineering Bay"
            if len(damaged_accessories) > 0:
                rule_trail.append(f"Damaged accessory identified ({', '.join(damaged_accessories)}): requires biomed inspection.")
            if condition_code in ["damaged", "non_functional"]:
                rule_trail.append(f"Device physical state '{condition_code}': blocks reissue until technician overhaul.")
            
            # Check technician capacity
            slot_info = self.capacity_service.get_available_slot("technician")
            proposed_slot = slot_info["label"]
            if not slot_info["available"]:
                rule_trail.append(f"Capacity check: {slot_info['label']}")
            else:
                rule_trail.append(f"Capacity check: Assigned next technician slot: {slot_info['label']}")

        # Priority 2: Incomplete inputs or photo evidence pending
        elif fallback_triggered or len(pending_evidence) > 0:
            if len(pending_evidence) > 0:
                recommendation = "Hold — awaiting missing accessory"
                rule_trail.append(f"Photo evidence pending for: {', '.join(pending_evidence)}.")
                next_action_route = "Intake Verification"
            else:
                recommendation = "Escalate — biomed inspection"
                rule_trail.append("Uncertain/missing inputs encountered: safe conservative fallback to biomed inspection.")
                next_action_route = "Biomedical Engineering Bay"
            confidence = min(confidence, 0.50)

        # Priority 3: Missing Required Accessories
        elif len(missing_required) > 0:
            recommendation = "Hold — awaiting missing accessory"
            rule_trail.append(f"Missing required accessories: {', '.join(missing_required)}. Reissue prohibited.")
            next_action_route = "Accessory Replenishment / Patient Follow-up"
            confidence -= (0.05 * len(missing_required))

        # Priority 4: Patient Acknowledgement Dispute / Refusal
        elif patient_acknowledged is None or patient_acknowledged == 0:
            recommendation = "Hold — pending supervisor review"
            rule_trail.append("Patient acknowledgement dispute: hold pending supervisor waiver or patient contact.")
            next_action_route = "Supervisor Review Queue"
            confidence = min(confidence, 0.70)

        # Priority 5: Cleaning Not Completed or Failed
        elif cleaning_stage in ["not_started", "in_progress", "failed"]:
            recommendation = "Hold — needs cleaning"
            next_action_route = "Sanitization Bay"
            slot_info = self.capacity_service.get_available_slot("cleaning_bay")
            proposed_slot = slot_info["label"]
            if not slot_info["available"]:
                rule_trail.append(f"Capacity check: {slot_info['label']}")
            else:
                rule_trail.append(f"Capacity check: Assigned next cleaning bay slot: {slot_info['label']}")

        # Priority 6: All rules satisfied -> Ready for reissue!
        elif (condition_code == "functional" and 
              cleaning_stage == "completed" and 
              present_required == total_required and 
              patient_acknowledged == 1):
            recommendation = "Ready for reissue"
            next_action_route = "Available Inventory Pool"
            rule_trail.append("All gates passed: accessories complete, condition functional, cleaning verified, patient acknowledged.")

        else:
            # Catch-all safe fallback
            recommendation = "Hold — pending supervisor review"
            rule_trail.append("Indeterminate state combination: conservative hold for supervisor triage.")
            next_action_route = "Supervisor Review Queue"

        # Bounding confidence
        final_confidence = max(0.15, min(0.98, confidence))

        return {
            "recommendation": recommendation,
            "confidence": round(final_confidence, 2),
            "rule_trail": rule_trail,
            "fallback_triggered": fallback_triggered,
            "proposed_slot": proposed_slot,
            "next_action_route": next_action_route
        }
