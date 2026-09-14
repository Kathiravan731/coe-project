# Stakeholder Assumptions & Operational Baseline Document

## 1. Document Overview
This document formalizes the stakeholder personas, operational assumptions, volume metrics, and acceptance criteria ("Definition of Done") for the **MediLoan Pilot System** — a Loan-Device Return Checklist & Accessory Reconciliation platform designed for a home-care medical equipment provider.

---

## 2. Stakeholder Personas & Access Boundaries

| Role | Primary User Persona | Responsibilities in Pilot | Least-Privilege Access Permissions |
| :--- | :--- | :--- | :--- |
| **Intake Coordinator** | Front-line clinical reception & logistics staff | • Scans incoming package barcodes<br>• Reconciles physical accessories against issued manifest<br>• Records device condition against fixed rubric<br>• Selects structured wear tags (no free text)<br>• Witnesses patient/caregiver hand-back acknowledgement | • Read loan issue manifest<br>• Submit accessory checklist<br>• Submit condition rubric & wear tags<br>• Submit patient acknowledgement<br>• Request recommendation<br>• Confirm standard approvals |
| **Cleaning / Biomed Tech** | Sterilization specialist & biomedical engineer | • Executes sanitization protocol B-4<br>• Updates cleaning stage (`in_progress`, `completed`, `failed`)<br>• Performs electrical safety & sensor calibration bench tests<br>• Reports accessory defects or housing cracks | • Read assigned triage queues<br>• Submit cleaning stages<br>• Submit biomedical bench test notes<br>• Read equipment technical manifests |
| **Clinical Supervisor** | Equipment manager & clinical lead | • Triage escalations & conflicting checklist entries<br>• Reviews explainable rule trails<br>• Authorizes high-impact decisions (reissue, write-off, quarantine)<br>• Executes overrides with mandatory typed justification | • Full approval and override authority<br>• Manage shift capacity & re-allocation<br>• Resolve checklist conflict flags<br>• Access operational reports |
| **Compliance Auditor & IT** | Quality assurance & data protection officer | • Audits immutable event log for regulatory compliance<br>• Verifies Zero-PHI minimization safeguards<br>• Reviews override distributions and error root causes | • Read-only access to immutable audit log<br>• Read-only access to executive analytics<br>• Zero update/delete privileges |

---

## 3. Definition of "Done" for Pilot Acceptance

The pilot system is formally considered **"Done"** and ready for clinical deployment when the following criteria are satisfied:
1. **100% Structured Reconciliation**: Every returned device must be reconciled against its original issue manifest before status can transition out of `in_intake`.
2. **Zero Missing-Accessory Reissue**: Measured escape rate of missing accessories on reissued equipment is $\le 1.0\%$ (empirical pilot achieved **0.0%**).
3. **Zero Uncleaned Deployments**: Reissue is programmatically impossible without documented, timestamped cleaning verification (`stage = 'completed'`).
4. **Mandatory Human Confirmation Gate**: Automated recommendations never directly mutate device availability; every transition requires explicit human confirmation.
5. **Mandatory Typed Overrides**: Any override of a recommendation requires a standardized override reason code and typed technical justification ($\ge 5$ characters).
6. **Zero-PHI Persistence**: No patient names, dates of birth, addresses, phone numbers, or free-text diagnostic notes are stored anywhere in the database, logs, or analytics. Only pseudonymous references (`patient_ref_id`, e.g. `PT-ANON-7782`) and SHA-256 hashed hardware serials are maintained.
7. **Immutable Audit Trail**: 100% of state transitions, lookups, conflicts, and overrides are recorded in an append-only event log protected by database-level triggers.
8. **Capacity Awareness**: Turnaround recommendations reflect actual shift queue depths; when capacity is exhausted, the system proposes the next realistic slot rather than false promises.

---

## 4. Operational & Volume Assumptions

### 4.1 Device Catalog & Fleet Size
The pilot fleet covers 4 representative home-care monitoring device families:
- **Digital Blood Pressure Monitor (`BP-DIG-100`)**: 15 units (Accessories: Adult Arm Cuff, AC Adapter, Carrying Case, USB Cable).
- **Fingertip Pulse Oximeter (`POX-FING-200`)**: 15 units (Accessories: Neck Lanyard, Silicone Boot, Padded Pouch, Li-Ion Dock).
- **Continuous Glucose Monitor Reader (`GLUC-CON-300`)**: 15 units (Accessories: Micro-USB Cable, Wall Charger, Travel Case, Strip Kit).
- **Emergency Fall-Detection Pendant (`FALL-PEND-400`)**: 15 units (Accessories: Magnetic Charging Cradle, Breakaway Lanyard, Belt Clip, USB-C Adapter).
- **Total Pilot Fleet**: 60 physical units with hardware serials securely hashed via SHA-256.

### 4.2 Intake Volume & Throughput
- **Daily Intake Rate**: 15 to 30 returned loan packages per facility per 24-hour cycle.
- **Average Loan Duration**: 14 to 30 days per patient home-monitoring episode.
- **Target Turnaround Time**: $\le 3.5$ hours from intake receipt to re-stocked available inventory (legacy manual baseline was 14.8 hours).

### 4.3 Shift Patterns & Facility Capacity
Facilities operate around the clock across 3 standardized 8-hour shifts:
- **Morning Shift (`07:00 – 15:00`)**: Full staffing (2 Sanitization Bays, 1 Biomed Tech). Max capacity: 8 cleanings, 5 bench inspections.
- **Afternoon Shift (`15:00 – 23:00`)**: Standard staffing (2 Sanitization Bays, 1 Biomed Tech). Max capacity: 8 cleanings, 5 bench inspections.
- **Night Shift (`23:00 – 07:00`)**: Reduced staffing (1 Sanitization Bay, on-call Biomed). Max capacity: 4 cleanings, 2 bench inspections.

### 4.4 Data Retention & Privacy Boundaries
- **Active Operational Database**: Retains loan state, checklist entries, and condition rubrics for the duration of the pilot (90 days).
- **Append-Only Event Store**: Retained indefinitely (minimum 7 years) to satisfy ISO 13485 and FDA 21 CFR Part 820 medical device traceability regulations.
- **Network Boundaries**: API served over TLS 1.3; database encrypted at rest; zero third-party telemetry scripts.
