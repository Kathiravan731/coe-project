# MediLoan Data Schema & PHI-Minimization Specification

## 1. Schema Design Principles
The data model is engineered to satisfy HIPAA Safe Harbor de-identification standards and the principle of data minimization:
1. **Zero Direct Patient Identifiers**: No patient names, dates of birth, street addresses, medical record numbers (MRNs), or contact numbers exist in any table.
2. **Pseudonymous Linking Only**: The `loans` table maintains only an opaque `patient_ref_id` (e.g. `PT-ANON-7782`), which can only be joined to patient records within a separate, access-restricted Electronic Health Record (EHR) system outside this application.
3. **Hardware Serial Hashing**: Device hardware serial numbers are converted to SHA-256 hashes (`serial_hash`) before storage to prevent serial-number-based correlation attacks.
4. **Structured Rubrics Only**: Free-text clinical diagnostic fields are completely eliminated; physical conditions are stored as controlled enum codes and validated wear tags.
5. **Database-Level Immutability**: The `events` table is protected by SQLite database triggers that abort any `UPDATE` or `DELETE` commands.

---

## 2. Table Schemas with Column-Level PHI Classification

### Table: `devices`
Tracks physical equipment instances in the lending fleet.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `device_id` | TEXT | No | **PK** | **Non-PHI**: Internal facility equipment identifier (e.g., `DEV-BP-101`). |
| `model` | TEXT | No | - | **Non-PHI**: Equipment model name (e.g., `BP-DIG-100`). |
| `category` | TEXT | No | - | **Non-PHI**: General clinical equipment category (e.g., `Blood Pressure Monitor`). |
| `serial_hash` | TEXT | No | - | **Protected Identifier**: Raw hardware serial numbers can theoretically correlate with manufacturer RMA records. **Hashed via SHA-256** at registration; raw serial is never stored. |
| `status` | TEXT | No | - | **Non-PHI**: Operational status enum (`available`, `on_loan`, `in_intake`, `hold_cleaning`, `hold_missing_accessory`, `escalated_biomed`, `written_off`). |
| `last_status_change_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp of last status transition. |

---

### Table: `accessory_items`
Standard catalog of components issued with each device model.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `item_id` | TEXT | No | **PK** | **Non-PHI**: Accessory catalog identifier (e.g., `ACC-BP-CUFF`). |
| `device_model` | TEXT | No | - | **Non-PHI**: Target device model reference. |
| `item_name` | TEXT | No | - | **Non-PHI**: Descriptive name of accessory (e.g., `Standard Adult Arm Cuff`). |
| `required` | INTEGER | No | - | **Non-PHI**: Boolean flag (1=Mandatory for reissue, 0=Optional comfort item). |

---

### Table: `loans`
Records active and historical lending episodes.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `loan_id` | TEXT | No | **PK** | **Non-PHI**: Operational transaction identifier (e.g., `LN-2026-0131`). |
| `device_id` | TEXT | No | **FK** &rarr; `devices(device_id)` | **Non-PHI**: Borrowed hardware unit. |
| `patient_ref_id` | TEXT | No | - | **Pseudonymous Token (PHI-Minimized)**: Opaque pseudonymous identifier (e.g., `PT-ANON-7782`). Real patient identity, clinical diagnosis, and home address are **strictly excluded** from this database. Re-identification requires separate EHR access. |
| `issued_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC issuance timestamp. |
| `issued_accessory_manifest_json` | TEXT | No | - | **Non-PHI**: JSON array of item IDs issued with this specific loan. |
| `returned_at` | TEXT | Yes | - | **Non-PHI**: ISO 8601 UTC return timestamp (NULL while active). |

---

### Table: `return_checklists`
Item-by-item reconciliation entries recorded during package intake.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `checklist_id` | TEXT | No | **PK** | **Non-PHI**: Reconciliation row identifier. |
| `loan_id` | TEXT | No | **FK** &rarr; `loans(loan_id)` | **Non-PHI**: Associated loan record. |
| `item_id` | TEXT | No | **FK** &rarr; `accessory_items(item_id)` | **Non-PHI**: Reconciled accessory catalog ID. |
| `condition` | TEXT | No | - | **Non-PHI**: Physical state enum (`present`, `missing`, `damaged`, `evidence_pending`). |
| `photo_ref` | TEXT | Yes | - | **Opaque Reference**: URI to local photo evidence blob (`photos/evidence_*.jpg`). Stored as an opaque reference; **biometric, facial, or document OCR processing is strictly prohibited**. |
| `recorded_by` | TEXT | No | - | **Non-PHI**: Staff operator ID (e.g., `STF-COORD-01`). |
| `recorded_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. |

---

### Table: `return_condition`
Device physical condition evaluation recorded against a fixed clinical rubric.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `condition_id` | TEXT | No | **PK** | **Non-PHI**: Condition record identifier. |
| `loan_id` | TEXT | No | **FK** &rarr; `loans(loan_id)` | **Non-PHI**: Associated loan record. |
| `condition_code` | TEXT | No | - | **Non-PHI**: Rubric enum (`functional`, `needs_inspection`, `damaged`, `non_functional`). |
| `wear_tags` | TEXT | No | - | **Non-PHI (Controlled Allowlist)**: JSON array of approved mechanical wear tags (e.g., `["clean_housing", "scratches_cosmetic"]`). **Free-text clinical notes are rejected by schema validators** to prevent accidental diagnostic note leakage. |
| `recorded_by` | TEXT | No | - | **Non-PHI**: Staff operator ID. |
| `recorded_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. |

---

### Table: `cleaning_status`
Disinfection and sanitization verification records.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `cleaning_id` | TEXT | No | **PK** | **Non-PHI**: Sanitization event identifier. |
| `loan_id` | TEXT | No | **FK** &rarr; `loans(loan_id)` | **Non-PHI**: Associated loan record. |
| `stage` | TEXT | No | - | **Non-PHI**: Sanitization stage enum (`not_started`, `in_progress`, `completed`, `failed`). |
| `technician_id` | TEXT | Yes | - | **Non-PHI**: Certified technician identifier (e.g., `TECH-BIO-01`). |
| `started_at` | TEXT | Yes | - | **Non-PHI**: ISO 8601 UTC start timestamp. |
| `completed_at` | TEXT | Yes | - | **Non-PHI**: ISO 8601 UTC completion timestamp. |

---

### Table: `patient_acknowledgement`
Hand-back condition and accessory count verification.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `ack_id` | TEXT | No | **PK** | **Non-PHI**: Acknowledgement event identifier. |
| `loan_id` | TEXT | No | **FK** &rarr; `loans(loan_id)` | **Non-PHI**: Associated loan record. |
| `acknowledged` | INTEGER | No | - | **Non-PHI**: Boolean flag (1=Confirmed, 0=Refused/Disputed). |
| `witness_staff_id` | TEXT | No | - | **Non-PHI**: Staff witness identifier (e.g., `STF-COORD-01`). |
| `acknowledged_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. **Biometric signature images are completely excluded** to eliminate biometric PHI risk. |

---

### Table: `recommendations`
Output generated by the explainable recommendation engine.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `rec_id` | TEXT | No | **PK** | **Non-PHI**: Recommendation identifier. |
| `loan_id` | TEXT | No | **FK** &rarr; `loans(loan_id)` | **Non-PHI**: Associated loan record. |
| `recommendation` | TEXT | No | - | **Non-PHI**: Triage recommendation enum (`Ready for reissue`, `Hold — awaiting missing accessory`, `Hold — needs cleaning`, `Escalate — biomed inspection`, `Hold — pending supervisor review`). |
| `rule_trail_json` | TEXT | No | - | **Non-PHI**: JSON array of explicit deterministic rules and clinical evidence strings. |
| `confidence_score` | REAL | No | - | **Non-PHI**: Deterministic confidence metric $[0.15, 0.98]$. |
| `fallback_triggered` | INTEGER | No | - | **Non-PHI**: Boolean flag indicating conservative fallback activation under uncertainty. |
| `generated_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. |

---

### Table: `human_confirmations`
Human-in-the-loop gate confirmations and overrides.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `confirm_id` | TEXT | No | **PK** | **Non-PHI**: Confirmation transaction identifier. |
| `rec_id` | TEXT | No | **FK** &rarr; `recommendations(rec_id)` | **Non-PHI**: Evaluated recommendation. |
| `confirmed_by` | TEXT | No | - | **Non-PHI**: Authorized staff/supervisor ID. |
| `decision` | TEXT | No | - | **Non-PHI**: Gate decision (`approved` or `overridden`). |
| `override_reason_code` | TEXT | Yes | - | **Non-PHI**: Standardized reason enum (`ACCESSORY_REPLACED_FROM_STOCK`, `MANUAL_DEEP_CLEAN_VERIFIED`, `BIOMED_WAIVER`, `EXPEDITED_CLINICAL_NEED`, `FALSE_DEFECT_FLAG`, `OTHER`). |
| `override_justification` | TEXT | Yes | - | **Non-PHI (Staff Rationale)**: Technical or logistics justification authored by clinical supervisor. Mandatory if decision is `overridden`. Patient clinical details are strictly prohibited by operational policy. |
| `confirmed_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. |

---

### Table: `capacity_slots`
Tracks shift queues and facility throughput limits.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `slot_id` | TEXT | No | **PK** | **Non-PHI**: Scheduling slot identifier. |
| `shift_date` | TEXT | No | - | **Non-PHI**: Scheduled date (`YYYY-MM-DD`). |
| `shift_name` | TEXT | No | - | **Non-PHI**: Shift name (`Morning`, `Afternoon`, `Night`). |
| `role` | TEXT | No | - | **Non-PHI**: Resource role (`cleaning_bay` or `technician`). |
| `capacity` | INTEGER | No | - | **Non-PHI**: Maximum units serviceable in shift. |
| `booked` | INTEGER | No | - | **Non-PHI**: Current units booked in queue. |

---

### Table: `events` (Append-Only Event Store)
Immutable audit log capturing all system transitions.

| Column Name | SQL Type | Nullable | Primary / Foreign Key | PHI Classification & Protection Rationale |
| :--- | :--- | :---: | :---: | :--- |
| `event_id` | TEXT | No | **PK** | **Non-PHI**: Immutable event identifier. |
| `loan_id` | TEXT | Yes | - | **Non-PHI**: Associated loan reference (if applicable). |
| `event_type` | TEXT | No | - | **Non-PHI**: Event taxonomy code (`LOAN_LOOKUP`, `CHECKLIST_RECORDED`, `RECOMMENDATION_GENERATED`, `STATUS_TRANSITIONED`, `DATA_INTEGRITY_MISMATCH`, etc.). |
| `payload_json` | TEXT | No | - | **Non-PHI**: Structured JSON payload. Free-text patient notes are stripped at the API boundary before ingestion. |
| `actor_id` | TEXT | No | - | **Non-PHI**: Staff ID who triggered the event. |
| `occurred_at` | TEXT | No | - | **Non-PHI**: ISO 8601 UTC timestamp. |

---

## 3. SQLite DDL & Immutability Triggers

```sql
-- Enforce Foreign Keys and WAL Mode
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Immutability Triggers on Events Table
CREATE TRIGGER IF NOT EXISTS prevent_events_update
BEFORE UPDATE ON events
BEGIN
    SELECT RAISE(ABORT, 'Events table is strictly immutable and append-only: UPDATE disallowed.');
END;

CREATE TRIGGER IF NOT EXISTS prevent_events_delete
BEFORE DELETE ON events
BEGIN
    SELECT RAISE(ABORT, 'Events table is strictly immutable and append-only: DELETE disallowed.');
END;
```
