# Clinical & Operational Risk Register

## 1. Overview & Risk Methodology
This Risk Register catalogs failure modes, clinical risks, and data governance hazards associated with medical monitoring device return and accessory reconciliation. Every risk is evaluated for **Likelihood** (1–5) and **Clinical/Operational Impact** (1–5), resulting in a **Risk Priority Score (RPN = Likelihood &times; Impact)**.

All mitigations directly trace back to the core design principles established in **Section 0** of the system specifications:
- **P0.1**: Privacy / Zero-PHI Minimization by Design
- **P0.2**: Explainable Recommendations & Inspectable Rule Trails
- **P0.3**: Human-in-the-Loop for High-Impact Actions
- **P0.4**: Capacity & Scheduling Queue Awareness
- **P0.5**: Safe Fallback Under Uncertainty
- **P0.6**: Tamper-Evident Auditability

---

## 2. Risk Matrix Summary

| Risk ID | Failure Mode / Threat | Pre-Mitigation RPN | Section 0 Principle | Post-Mitigation RPN | Mitigation Status |
| :---: | :--- | :---: | :---: | :---: | :---: |
| **RSK-01** | Accidental PHI / Clinical Data Leakage | 12 (Med &times; High) | **P0.1** (Zero-PHI) | **2 (Low &times; Low)** | ✅ Implemented |
| **RSK-02** | False "Ready for Reissue" Status | 20 (High &times; Crit) | **P0.2, P0.5** (Rules & Fallback) | **2 (Low &times; Low)** | ✅ Implemented |
| **RSK-03** | Sanitization Bay & Technician Queue Overload | 16 (High &times; High) | **P0.4** (Capacity Awareness) | **3 (Low &times; Med)** | ✅ Implemented |
| **RSK-04** | Patient Acknowledgement Refusal / Liability Dispute | 12 (Med &times; High) | **P0.3, P0.5** (Gate & Fallback) | **2 (Low &times; Low)** | ✅ Implemented |
| **RSK-05** | Device Mix-ups & Scanned Identifier Typos | 15 (High &times; Med) | **P0.5, P0.6** (Fallback & Audit) | **2 (Low &times; Low)** | ✅ Implemented |
| **RSK-06** | Conflicting Checklist Entries Across Multi-Stage Hand-offs | 12 (Med &times; High) | **P0.5** (Safe Fallback) | **2 (Low &times; Low)** | ✅ Implemented |
| **RSK-07** | Supervisor Override Abuse / Hasty Reissue | 16 (High &times; High) | **P0.3, P0.6** (Human Gate & Audit) | **3 (Low &times; Med)** | ✅ Implemented |
| **RSK-08** | Audit Trail Tampering or Retroactive Record Alteration | 15 (Med &times; Crit) | **P0.6** (Auditability) | **1 (Low &times; Low)** | ✅ Implemented |

---

## 3. Detailed Risk Characterization & Technical Mitigations

### RSK-01: Accidental PHI / Clinical Data Leakage
- **Hazard**: Free-text notes entered by staff contain patient names, home addresses, or diagnostic health details, violating HIPAA/HITECH regulations.
- **Likelihood**: Medium (3) | **Impact**: High (4) | **Initial RPN**: 12
- **Design Principle**: **P0.1 (Zero-PHI Minimization by Design)**
- **Implemented Mitigations**:
  - `loans.patient_ref_id` stores only pseudonymous opaque tokens (`PT-ANON-xxxx`).
  - Hardware serial numbers are hashed via SHA-256 (`serial_hash`) upon registration.
  - Free-text medical diagnostic notes fields are completely eliminated from the DOM and API models.
  - Device wear is restricted to an enumerated allowlist of mechanical wear tags (`clean_housing`, `scratches_cosmetic`, `strap_frayed`, etc.). Inputs containing unapproved strings are rejected with HTTP 422.
  - Photo attachments are stored as opaque filesystem references and never analyzed for facial/biometric data.
- **Residual Risk**: Low (1 &times; 2 = 2)

---

### RSK-02: False "Ready for Reissue" Status
- **Hazard**: A device is redeployed to a vulnerable home-care patient missing a critical charging cable, blood pressure cuff, or without documented sanitization, causing treatment interruption or cross-infection.
- **Likelihood**: High (4) | **Impact**: Critical (5) | **Initial RPN**: 20
- **Design Principle**: **P0.2 (Explainable Rules)** & **P0.5 (Safe Fallback Under Uncertainty)**
- **Implemented Mitigations**:
  - Deterministic rules hierarchy: Reissue requires 100% of required accessories present, condition = `functional`, cleaning = `completed`, and patient acknowledgement confirmed.
  - If any input is missing, contradictory, or historical baseline sample size $N < 5$, system automatically sets `fallback_triggered: True` and forces `Escalate — biomed inspection`.
  - Automated recommendations never directly mutate status; a human gate must approve.
  - Empirical pilot demonstrated **0.0% missing accessory escape** and **0.0% uncleaned reissue**.
- **Residual Risk**: Low (1 &times; 2 = 2)

---

### RSK-03: Sanitization Bay & Technician Queue Overload
- **Hazard**: Front-line intake promises an unrealistic 2-hour turnaround time to dispatch coordinators when all sanitization bays or technicians are fully booked for that shift.
- **Likelihood**: High (4) | **Impact**: High (4) | **Initial RPN**: 16
- **Design Principle**: **P0.4 (Capacity & Scheduling Queue Awareness)**
- **Implemented Mitigations**:
  - `CapacityService` tracks shift slots (`capacity` vs `booked`) in real time for `cleaning_bay` and `technician`.
  - When recommending cleaning or inspection, the engine checks queue depths and automatically proposes the earliest realistic slot (e.g. Next Afternoon Shift).
  - If all visible shifts in the scheduling window are exhausted, the system returns `no capacity available`, reports the earliest queue re-check time, and flags supervisor escalation.
- **Residual Risk**: Low (1 &times; 3 = 3)

---

### RSK-04: Patient Acknowledgement Refusal / Liability Dispute
- **Hazard**: A patient returns damaged equipment or missing chargers and disputes liability, claiming the condition existed prior to loan hand-back.
- **Likelihood**: Medium (3) | **Impact**: High (4) | **Initial RPN**: 12
- **Design Principle**: **P0.3 (Human Gate)** & **P0.5 (Safe Fallback)**
- **Implemented Mitigations**:
  - Mandatory patient acknowledgement witness capture (`acknowledged`, `witness_staff_id`, `acknowledged_at`).
  - If acknowledgement is refused (`acknowledged == 0`) or unconfirmed, recommendation is forced to `Hold — pending supervisor review`, blocking reissue until clinical resolution.
  - Staff witness ID is appended to the immutable event log.
- **Residual Risk**: Low (1 &times; 2 = 2)

---

### RSK-05: Device Mix-ups & Scanned Identifier Typos
- **Hazard**: Intake coordinator scans a barcode with a missing/corrupted character or scans an unrelated package, causing incorrect manifest assignment.
- **Likelihood**: High (5) | **Impact**: Medium (3) | **Initial RPN**: 15
- **Design Principle**: **P0.5 (Safe Fallback)** & **P0.6 (Auditability)**
- **Implemented Mitigations**:
  - When a query fails to match an active loan, the system **strictly refuses to guess or approximate**.
  - Returns HTTP 404 and immediately writes a `DATA_INTEGRITY_MISMATCH` event to the append-only audit log with the exact scanned query.
  - Halts workflow and forces manual supervisor verification.
- **Residual Risk**: Low (1 &times; 2 = 2)

---

### RSK-06: Conflicting Checklist Entries Across Multi-Stage Hand-offs
- **Hazard**: Intake staff marks an accessory as Present during unboxing, but the sanitization technician at the cleaning bay notices the cable is missing or severed.
- **Likelihood**: Medium (3) | **Impact**: High (4) | **Initial RPN**: 12
- **Design Principle**: **P0.5 (Safe Fallback Under Uncertainty)**
- **Implemented Mitigations**:
  - System checks for distinct recorded conditions on the same accessory (`distinct_conditions > 1`).
  - Upon detecting disagreement, system logs `CHECKLIST_CONFLICT_DETECTED`, sets `fallback_triggered: True`, and suspends auto-recommendation to `Hold — pending supervisor review`.
- **Residual Risk**: Low (1 &times; 2 = 2)

---

### RSK-07: Supervisor Override Abuse / Hasty Reissue
- **Hazard**: Supervisors under pressure bypass safety holds without physical verification to meet operational quotas.
- **Likelihood**: High (4) | **Impact**: High (4) | **Initial RPN**: 16
- **Design Principle**: **P0.3 (Human Confirmation Gate)** & **P0.6 (Auditability)**
- **Implemented Mitigations**:
  - Overrides strictly require the `supervisor` role.
  - Every override enforces a mandatory standardized reason code (`ACCESSORY_REPLACED_FROM_STOCK`, `MANUAL_DEEP_CLEAN_VERIFIED`, `BIOMED_WAIVER`, `EXPEDITED_CLINICAL_NEED`, etc.).
  - Enforces a typed justification ($\ge 5$ chars) authored by the supervisor.
  - Full override payload and supervisor identity are permanently stored in immutable audit logs.
  - Executive dashboard surfaces override rates and reason code distributions for QA audit.
- **Residual Risk**: Low (1 &times; 3 = 3)

---

### RSK-08: Audit Trail Tampering or Retroactive Record Alteration
- **Hazard**: Malicious or negligent modification of historical return records to conceal equipment damage or missing audit evidence during regulatory inspections.
- **Likelihood**: Medium (3) | **Impact**: Critical (5) | **Initial RPN**: 15
- **Design Principle**: **P0.6 (Auditability & Tamper Evidence)**
- **Implemented Mitigations**:
  - SQLite database triggers `prevent_events_update` and `prevent_events_delete` raise an unrecoverable `SQLITE_ABORT` on any `UPDATE` or `DELETE` against the `events` table.
  - Role-based access disallows delete/update endpoints.
  - Read-only auditor view exposes chronological event stream with actor IDs, timestamps, and payload digests.
- **Residual Risk**: Low (1 &times; 1 = 1)
