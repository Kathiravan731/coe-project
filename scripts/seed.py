"""
Synthetic dataset generator for the Loan-Device Return Checklist system.
Seeds:
- 4 device models with 16 accessory catalog items
- 60 physical devices with hashed hardware serials
- 24 shift capacity slots across technicians and cleaning bays
- 160 realistic loan records (historical completed returns and active intake returns)
  covering normal returns, missing accessories, damaged units, cleaning holds, and acknowledgement disputes.
"""

import sqlite3
import hashlib
import json
import random
import os
import sys
from datetime import datetime, timezone, timedelta

# Ensure workspace root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Ensure correct DB path
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "reconciliation.db"))

MODELS_CATALOG = [
    {
        "model": "BP-DIG-100",
        "category": "Blood Pressure Monitor",
        "accessories": [
            ("ACC-BP-CUFF", "Standard Adult Arm Cuff", 1),
            ("ACC-BP-PWR", "AC Power Adapter", 1),
            ("ACC-BP-CASE", "Protective Carrying Case", 1),
            ("ACC-BP-CBL", "USB Data Transfer Cable", 0)
        ]
    },
    {
        "model": "POX-FING-200",
        "category": "Pulse Oximeter",
        "accessories": [
            ("ACC-POX-LNYD", "Neck Lanyard", 1),
            ("ACC-POX-SILC", "Silicone Protective Boot", 1),
            ("ACC-POX-CASE", "Padded Storage Pouch", 1),
            ("ACC-POX-BATC", "Rechargeable Li-Ion Battery Dock", 1)
        ]
    },
    {
        "model": "GLUC-CON-300",
        "category": "Continuous Glucose Monitor",
        "accessories": [
            ("ACC-GLUC-USB", "Micro-USB Charging Cable", 1),
            ("ACC-GLUC-WALL", "Medical Grade Wall Charger", 1),
            ("ACC-GLUC-CASE", "Zippered Travel Case", 1),
            ("ACC-GLUC-STR", "Calibration Test Strip Kit", 0)
        ]
    },
    {
        "model": "FALL-PEND-400",
        "category": "Fall-Detection Pendant",
        "accessories": [
            ("ACC-FALL-CRDL", "Magnetic Wireless Charging Cradle", 1),
            ("ACC-FALL-LNYD", "Breakaway Safety Lanyard", 1),
            ("ACC-FALL-CLIP", "Belt Holster Clip", 1),
            ("ACC-FALL-PWR", "USB-C Power Adapter", 1)
        ]
    }
]

WEAR_TAG_OPTIONS = [
    "clean_housing", "scratches_cosmetic", "strap_frayed",
    "port_dust", "screen_blemish", "sensor_scuff"
]

STAFF_COORDINATORS = ["STF-COORD-01", "STF-COORD-02", "STF-COORD-03"]
STAFF_TECHNICIANS = ["TECH-BIO-01", "TECH-BIO-02", "TECH-SAN-01"]
STAFF_SUPERVISORS = ["SUP-CLIN-01", "SUP-CLIN-02"]

def seed_database(db_path=None):
    target = db_path or DB_PATH
    os.makedirs(os.path.dirname(target), exist_ok=True)
    
    # Import and run init_db first
    from src.database import init_db, get_db
    init_db(target)

    with get_db(target) as conn:
        cursor = conn.cursor()
        
        # Clean existing data safely
        # Note: events table has trigger preventing DELETE; if re-seeding, drop tables or delete if empty
        cursor.execute("DROP TABLE IF EXISTS human_confirmations;")
        cursor.execute("DROP TABLE IF EXISTS recommendations;")
        cursor.execute("DROP TABLE IF EXISTS patient_acknowledgement;")
        cursor.execute("DROP TABLE IF EXISTS cleaning_status;")
        cursor.execute("DROP TABLE IF EXISTS return_condition;")
        cursor.execute("DROP TABLE IF EXISTS return_checklists;")
        cursor.execute("DROP TABLE IF EXISTS loans;")
        cursor.execute("DROP TABLE IF EXISTS capacity_slots;")
        cursor.execute("DROP TABLE IF EXISTS accessory_items;")
        cursor.execute("DROP TABLE IF EXISTS devices;")
        cursor.execute("DROP TABLE IF EXISTS events;")
        
    init_db(target)

    with get_db(target) as conn:
        cursor = conn.cursor()
        print(f"Seeding database at {target}...")
        now = datetime.now(timezone.utc)

        # 1. Seed Accessory Catalog
        for m in MODELS_CATALOG:
            for item_id, item_name, req in m["accessories"]:
                cursor.execute("""
                    INSERT INTO accessory_items (item_id, device_model, item_name, required)
                    VALUES (?, ?, ?, ?);
                """, (item_id, m["model"], item_name, req))

        # 2. Seed Devices (60 physical devices)
        device_ids = []
        for m_idx, m in enumerate(MODELS_CATALOG):
            for d_idx in range(1, 16):
                dev_id = f"DEV-{m['model'][:3]}-{100 + d_idx}"
                serial_raw = f"SN-MED-{m['model']}-{d_idx:04d}"
                serial_hash = hashlib.sha256(serial_raw.encode()).hexdigest()
                status = "on_loan" if d_idx <= 10 else "available"
                cursor.execute("""
                    INSERT INTO devices (device_id, model, category, serial_hash, status, last_status_change_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (dev_id, m["model"], m["category"], serial_hash, status, (now - timedelta(days=15)).isoformat()))
                device_ids.append((dev_id, m["model"]))

        # 3. Seed Capacity Slots (Next 4 days, 3 shifts/day, 2 roles = 24 slots)
        for d in range(4):
            slot_date = (now + timedelta(days=d)).strftime("%Y-%m-%d")
            for shift in ["Morning", "Afternoon", "Night"]:
                # Cleaning Bay: capacity 8 per shift
                booked_clean = random.randint(2, 6) if d < 2 else 1
                cursor.execute("""
                    INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
                    VALUES (?, ?, ?, 'cleaning_bay', ?, ?);
                """, (f"SLOT-CLN-{slot_date}-{shift}", slot_date, shift, 8, booked_clean))

                # Biomed Technician: capacity 5 per shift
                booked_tech = random.randint(1, 4) if d < 2 else 0
                cursor.execute("""
                    INSERT INTO capacity_slots (slot_id, shift_date, shift_name, role, capacity, booked)
                    VALUES (?, ?, ?, 'technician', ?, ?);
                """, (f"SLOT-TCH-{slot_date}-{shift}", slot_date, shift, 5, booked_tech))

        # 4. Seed 160 Loan Records (130 Historical + 30 Active/In-Intake)
        random.seed(42) # Deterministic reproducibility

        for loan_idx in range(1, 161):
            loan_id = f"LN-2026-{loan_idx:04d}"
            dev_id, model = random.choice(device_ids)
            patient_ref = f"PT-ANON-{random.randint(1000, 9999)}"
            
            # Find manifest for model
            model_info = next(m for m in MODELS_CATALOG if m["model"] == model)
            manifest_items = [acc[0] for acc in model_info["accessories"]]

            days_ago = random.randint(3, 45)
            issue_date = now - timedelta(days=days_ago)

            # Loans 131-160 are active returns waiting in intake for live user demonstration
            is_active_intake = (loan_idx > 130)

            if is_active_intake:
                # Active loan, ready for intake testing
                cursor.execute("""
                    INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
                    VALUES (?, ?, ?, ?, ?, NULL);
                """, (loan_id, dev_id, patient_ref, issue_date.isoformat(), json.dumps(manifest_items)))
                continue

            # Historical completed loan (1-130)
            returned_date = issue_date + timedelta(days=random.randint(2, 20))
            cursor.execute("""
                INSERT INTO loans (loan_id, device_id, patient_ref_id, issued_at, issued_accessory_manifest_json, returned_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (loan_id, dev_id, patient_ref, issue_date.isoformat(), json.dumps(manifest_items), returned_date.isoformat()))

            # Determine scenario category
            scenario_rand = random.random()
            if scenario_rand < 0.50:
                scenario = "normal"
            elif scenario_rand < 0.70:
                scenario = "missing_accessory"
            elif scenario_rand < 0.85:
                scenario = "damaged"
            elif scenario_rand < 0.93:
                scenario = "cleaning_hold"
            else:
                scenario = "ack_dispute"

            coordinator = random.choice(STAFF_COORDINATORS)
            technician = random.choice(STAFF_TECHNICIANS)
            supervisor = random.choice(STAFF_SUPERVISORS)

            # Checklist entries
            for acc_id in manifest_items:
                chk_id = f"CHK-{loan_idx}-{acc_id}"
                if scenario == "missing_accessory" and random.random() < 0.5:
                    cond = "missing"
                    photo = None
                elif scenario == "damaged" and random.random() < 0.3:
                    cond = "damaged"
                    photo = f"photos/evidence_{acc_id}_{loan_idx}.jpg"
                else:
                    cond = "present"
                    photo = None

                cursor.execute("""
                    INSERT INTO return_checklists (checklist_id, loan_id, item_id, condition, photo_ref, recorded_by, recorded_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, (chk_id, loan_id, acc_id, cond, photo, coordinator, returned_date.isoformat()))

            # Condition entry
            cond_id = f"CND-{loan_idx}"
            if scenario == "damaged":
                condition_code = random.choice(["needs_inspection", "damaged", "non_functional"])
                wear_tags = random.sample(["scratches_cosmetic", "strap_frayed", "screen_blemish"], k=2)
            else:
                condition_code = "functional"
                wear_tags = ["clean_housing"] if random.random() < 0.7 else ["scratches_cosmetic"]

            cursor.execute("""
                INSERT INTO return_condition (condition_id, loan_id, condition_code, wear_tags, recorded_by, recorded_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (cond_id, loan_id, condition_code, json.dumps(wear_tags), coordinator, returned_date.isoformat()))

            # Cleaning entry
            clean_id = f"CLN-{loan_idx}"
            if scenario == "cleaning_hold":
                clean_stage = random.choice(["not_started", "failed"])
                comp_at = returned_date.isoformat() if clean_stage == "failed" else None
            else:
                clean_stage = "completed"
                comp_at = (returned_date + timedelta(minutes=45)).isoformat()

            cursor.execute("""
                INSERT INTO cleaning_status (cleaning_id, loan_id, stage, technician_id, started_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?);
            """, (clean_id, loan_id, clean_stage, technician, returned_date.isoformat(), comp_at))

            # Patient acknowledgement entry
            ack_id = f"ACK-{loan_idx}"
            acknowledged = 0 if scenario == "ack_dispute" else 1
            cursor.execute("""
                INSERT INTO patient_acknowledgement (ack_id, loan_id, acknowledged, witness_staff_id, acknowledged_at)
                VALUES (?, ?, ?, ?, ?);
            """, (ack_id, loan_id, acknowledged, coordinator, returned_date.isoformat()))

            # Recommendations & Confirmations
            rec_id = f"REC-{loan_idx}"
            if scenario == "normal":
                rec_text = "Ready for reissue"
                conf = 0.94
                trail = [
                    f"Accessory checklist: {len(manifest_items)}/{len(manifest_items)} present (rule: all required items present)",
                    "Return condition: functional (rule: functional required for reissue)",
                    "Cleaning status: completed (rule: reissue blocked until cleaning=completed)",
                    "Patient acknowledgement: confirmed by staff witness"
                ]
                decision = "approved"
                override_code = None
                override_just = None
            elif scenario == "missing_accessory":
                rec_text = "Hold — awaiting missing accessory"
                conf = 0.88
                trail = [
                    "Missing required accessories identified (rule: all required items must be present)",
                    "Return condition: functional",
                    "Cleaning status: completed"
                ]
                # In 15% of missing accessory cases, supervisor overrides with ACCESSORY_REPLACED_FROM_STOCK
                if random.random() < 0.15:
                    decision = "overridden"
                    override_code = "ACCESSORY_REPLACED_FROM_STOCK"
                    override_just = "Stock replacement accessory issued from central reserve inventory to avoid patient reissue delay."
                else:
                    decision = "approved"
                    override_code = None
                    override_just = None
            elif scenario == "damaged":
                rec_text = "Escalate — biomed inspection"
                conf = 0.92
                trail = [
                    f"Return condition: {condition_code} (rule: needs_inspection or damaged requires biomedical overhaul)",
                    "Accessory checklist reconciled"
                ]
                decision = "approved"
                override_code = None
                override_just = None
            elif scenario == "cleaning_hold":
                rec_text = "Hold — needs cleaning"
                conf = 0.85
                trail = [
                    f"Cleaning status: {clean_stage} (rule: reissue blocked until cleaning=completed)"
                ]
                if random.random() < 0.10:
                    decision = "overridden"
                    override_code = "MANUAL_DEEP_CLEAN_VERIFIED"
                    override_just = "Supervisor personally re-sanitized unit following protocol B-4."
                else:
                    decision = "approved"
                    override_code = None
                    override_just = None
            else: # ack_dispute
                rec_text = "Hold — pending supervisor review"
                conf = 0.65
                trail = [
                    "Patient acknowledgement unconfirmed/refused (rule: unresolved liability requires supervisor review)"
                ]
                decision = "approved"
                override_code = None
                override_just = None

            cursor.execute("""
                INSERT INTO recommendations (rec_id, loan_id, recommendation, rule_trail_json, confidence_score, fallback_triggered, generated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?);
            """, (rec_id, loan_id, rec_text, json.dumps(trail), conf, returned_date.isoformat()))

            conf_id = f"CNF-{loan_idx}"
            cursor.execute("""
                INSERT INTO human_confirmations (confirm_id, rec_id, confirmed_by, decision, override_reason_code, override_justification, confirmed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, (conf_id, rec_id, supervisor, decision, override_code, override_just, (returned_date + timedelta(hours=1)).isoformat()))

            # Append immutable audit event
            evt_id = f"EVT-SEED-{loan_idx:04d}"
            cursor.execute("""
                INSERT INTO events (event_id, loan_id, event_type, payload_json, actor_id, occurred_at)
                VALUES (?, ?, 'STATUS_TRANSITIONED', ?, ?, ?);
            """, (evt_id, loan_id, json.dumps({"scenario": scenario, "decision": decision, "rec": rec_text}), supervisor, returned_date.isoformat()))

        print("Seeding successfully completed: 60 devices, 24 capacity slots, 160 loan records seeded.")

if __name__ == "__main__":
    seed_database()
