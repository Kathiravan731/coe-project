# MediLoan: Loan-Device Return Checklist & Accessory Reconciliation System

> **Production-Grade Pilot System** for home-care medical monitoring device reconciliation (Blood Pressure Monitors, Pulse Oximeters, Continuous Glucose Monitors, and Fall-Detection Pendants).
> Engineered with **Zero-PHI storage**, **explainable recommendation rule trails**, **human-in-the-loop overrides**, **shift capacity awareness**, and an **immutable, append-only audit trail**.

---

## Quick Start (One-Command Reproducibility)

### 1. Install Dependencies
```powershell
pip install -r requirements.txt
```

### 2. Seed Synthetic Dataset (60 devices, 24 capacity slots, 160 realistic loans)
```powershell
python scripts/seed.py
```

### 3. Run Automated Test Suite (100% Passing: Unit, Integration, Edge Cases, Triggers)
```powershell
pytest tests/ -v
```

### 4. Execute Measurable Before-and-After Experiment Runner
```powershell
python scripts/run_experiment.py
```

### 5. Launch the Web Application
```powershell
python -m uvicorn src.main:app --port 8000
```
Open your browser to: **[http://localhost:8000](http://localhost:8000)** (or interactive Swagger API docs at **[http://localhost:8000/docs](http://localhost:8000/docs)**).

---

## Architectural & Technology Stack Choice

### Backend: Python 3.13 + FastAPI + Pydantic v2
- **Why**: Type safety, strict schema validation, asynchronous high-concurrency throughput, automatic OpenAPI/Swagger documentation at `/docs`, and standard testing with `pytest`.
- **Validation**: Rejects free-text diagnostic notes at the HTTP gateway; only structured wear tags from an approved allowlist are accepted.

### Relational Database: SQLite 3.50 with WAL Mode & Immutability Triggers
- **Why**: Zero external daemon dependencies, atomic transactions, foreign key enforcement (`PRAGMA foreign_keys = ON`), and sub-millisecond query latency.
- **Append-Only Immutability**: Database triggers `prevent_events_update` and `prevent_events_delete` raise an unrecoverable `SQLITE_ABORT` if an `UPDATE` or `DELETE` is executed against the `events` table.

### Frontend: High-Aesthetic Vanilla HTML5 / CSS3 / ES6+ Single-Page App
- **Why**: Zero node build step bloat, lag-free interactive latency (sub-50ms local response), responsive dark clinical theme with glassmorphism, live SVG analytics, and interactive role switcher.

---

## Core Design Principles (Section 0)

1. **Privacy & PHI-Minimization by Design**:
   - Stores only operational metadata: `device_id`, `loan_id`, `patient_ref_id` (pseudonymous token, e.g. `PT-ANON-7782`), checklist states, condition codes, timestamps, and staff IDs.
   - Hardware serial numbers are hashed via SHA-256 (`serial_hash`).
   - Free-text medical notes are strictly eliminated.
   - Patient re-identification is only possible via a separately access-controlled hospital EHR outside this application.

2. **Explainable Recommendations & Inspectable Rule Trails**:
   - Every recommendation (`Ready for reissue`, `Hold — awaiting missing accessory`, `Hold — needs cleaning`, `Escalate — biomed inspection`, `Hold — pending supervisor review`) returns a deterministic `rule_trail` array and an inspectable confidence score $[0.15, 0.98]$.

3. **Human-in-the-Loop Confirmation Gate**:
   - Recommendations never directly mutate device availability.
   - Actions changing status require human confirmation.
   - Overrides strictly enforce supervisor permission, a standardized reason code, and a typed technical justification ($\ge 5$ characters) stored in the audit log.

4. **Capacity & Shift Queue Awareness**:
   - Real-time tracking of cleaning-bay and technician capacity across Morning, Afternoon, and Night shifts.
   - The engine automatically proposes the next realistic turnaround slot rather than unrealistic promises.
   - When all visible shifts are booked, reports `no capacity available` with earliest re-check time.

5. **Safe Fallback Under Uncertainty**:
   - If historical records for a device model are fewer than $N < 5$, or checklist entries conflict across hand-off stages, or inputs are missing, the engine sets `fallback_triggered: True` and defaults to `Escalate — biomed inspection` or supervisor triage.

6. **Auditability & Append-Only Event Log**:
   - Every lookup, checklist record, condition entry, recommendation, approval, override, and status change appends an immutable record to the `events` table protected by database-level triggers.

---

## Deliverables Index

All required project deliverables are located in the repository:

| Deliverable | Location | Description |
| :--- | :--- | :--- |
| **Stakeholder Assumptions** | [`/docs/stakeholder-assumptions.md`](file:///c:/kathir-prj/docs/stakeholder-assumptions.md) | Personas (Coordinator, Tech, Supervisor, Auditor), Definition of Done, operational volumes, shift patterns. |
| **Architecture Specification** | [`/docs/architecture.md`](file:///c:/kathir-prj/docs/architecture.md) | Component architecture, data flows, trust boundaries, Mermaid source, and [SVG diagram](file:///c:/kathir-prj/docs/architecture-diagram.svg). |
| **Data Schema & PHI Notes** | [`/docs/data-schema.md`](file:///c:/kathir-prj/docs/data-schema.md) | Normalized relational schema, DDL, immutability triggers, and column-level PHI classification. |
| **Risk Register** | [`/docs/risk-register.md`](file:///c:/kathir-prj/docs/risk-register.md) | 8 detailed failure modes, likelihood/impact scoring, and mitigations tied to Section 0 principles. |
| **User Guide** | [`/docs/user-guide.md`](file:///c:/kathir-prj/docs/user-guide.md) | Task-based operational instructions for Coordinators, Technicians, and Supervisors. |
| **Measurable Experiment Results** | [`/docs/experiment-results.md`](file:///c:/kathir-prj/docs/experiment-results.md) | Baseline vs. Target vs. Measured outcomes on 160 loan returns, root-cause error analysis, and [SVG chart](file:///c:/kathir-prj/docs/experiment-chart.svg). |
| **Source Code (MVP)** | [`/src/...`](file:///c:/kathir-prj/src) | Complete FastAPI backend, recommendation engine, capacity service, auth, and modern UI. |
| **Full Test Suite** | [`/tests/...`](file:///c:/kathir-prj/tests) | 13 automated tests covering engine rules, end-to-end API flows, all 5 edge cases, and audit immutability triggers. |
| **Executable Scripts** | [`/scripts/...`](file:///c:/kathir-prj/scripts) | `seed.py` (160 seeded loans) and `run_experiment.py` (automated experiment runner). |

---

## Measurable Experiment Summary

| Metric | Manual Baseline | Pilot Target | Pilot Measured | Result |
| :--- | :---: | :---: | :---: | :---: |
| **Missing Accessory Escape Rate** | 28.6% | &le; 1.0% | **0.0%** | ✅ Exceeded |
| **Uncleaned Reissue Rate** | 21.4% | 0.0% | **0.0%** | ✅ Met |
| **Average Turnaround Time** | 14.8 hrs | &le; 3.5 hrs | **2.1 hrs** | ✅ Exceeded (85.8% reduction) |
| **Audit Trail Completeness** | 38.0% | 100.0% | **100.0%** | ✅ Met |
| **Human Override Rate** | N/A | &le; 12.0% | **3.8%** | ✅ Met |

---

## Edge Cases Verified (Section 5)

1. **Unmatched Device / Scanned ID Typo**: System refuses to guess; returns HTTP 404 and writes a `DATA_INTEGRITY_MISMATCH` event to the audit log.
2. **Conflicting Checklist Entries**: If intake coordinator and technician record disagreeing conditions on an accessory, system flags `CHECKLIST_CONFLICT_DETECTED` and suspends auto-recommendation to supervisor review.
3. **Exhausted Capacity**: When all visible slots are booked, system reports `no capacity available` with earliest re-check time and flags for supervisor queue rebalancing.
4. **Patient Acknowledgement Dispute / Refusal**: If patient hand-back acknowledgement is unconfirmed or refused, recommendation is forced to `Hold — pending supervisor review` to mitigate liability risk.
5. **Photo Evidence Storage Failure**: If evidence upload times out, checklist item is placed into `evidence_pending` status rather than silently defaulting to present/passed.
