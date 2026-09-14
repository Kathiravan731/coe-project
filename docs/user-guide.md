# MediLoan Pilot User Guide: Task-Based Clinical Operations

## 1. Quick Start & Role Switching

The MediLoan web portal adapts its interface and access permissions based on your active operational role.

```
+---------------------------------------------------------------------------------------+
|  MediLoan Pilot v1.0       [● Zero-PHI Enforced] [● Capacity: Active]                 |
|  Active Role: [ Intake Coordinator (STF-COORD-01)                      ▼ ]            |
+---------------------------------------------------------------------------------------+
|  [📋 Intake & Reconciliation]  [📊 Executive Analytics]  [⏱ Capacity]  [🔒 Audit Log]  |
+---------------------------------------------------------------------------------------+
```

To switch roles during testing:
1. Locate the **Active Role** dropdown in the top-right header.
2. Select **Intake Coordinator**, **Biomed/Cleaning Tech**, **Supervisor**, or **Auditor**.
3. The application updates permissions and user headers (`X-User-Role`, `X-User-Id`) immediately.

---

## 2. Intake Coordinator Workflow

### Goal
Unbox returned medical devices, reconcile issued accessories, inspect physical condition against structured rubrics, witness patient hand-back, and execute triage recommendation.

### Step-by-Step Instructions

#### Step 1: Look Up Loan Record
1. Open the **Intake & Reconciliation** tab.
2. Point your physical barcode scanner at the package label, or enter the **Loan ID** (e.g. `LN-2026-0131`) or **Device ID** (e.g. `DEV-BP-101`) into the search field.
3. *Alternative*: Click one of the quick sample chips (e.g. `LN-2026-0131`).
4. Click **Find Loan Record**.
   - *If valid*: The loan summary card and accessory checklist populate automatically.
   - *If invalid / typo*: A red warning banner will report that no match was found and that a `DATA_INTEGRITY_MISMATCH` audit event has been logged for supervisor review.

#### Step 2: Reconcile Accessories
1. In the **Accessory Manifest Reconciliation** table, compare each physical item against the manifest.
2. For each accessory, click the appropriate status pill:
   - **Present (Green)**: Item is in hand, undamaged, and verified.
   - **Missing (Red)**: Item was not returned by patient.
   - **Damaged (Amber)**: Item is returned but physically defective (frayed wire, cracked dock).
   - **Pending (Blue)**: Evidence upload or physical verification is pending.
3. *Optional*: Click **Attach Photo** to attach a photo evidence reference.

#### Step 3: Record Condition Rubric & Wear Tags
1. Under **Device Condition Rubric**, select the appropriate card:
   - **Functional**: Device boots up, display legible, buttons responsive.
   - **Needs Inspection**: Minor concern, uncertain calibration.
   - **Damaged**: Physical housing cracked, battery swelling, broken clip.
   - **Non-Functional**: Device fails to power on.
2. Under **Structured Wear Tags**, toggle applicable chips (e.g. `clean_housing`, `scratches_cosmetic`).
   > [!NOTE]
   > Free-text notes are completely disabled to prevent inadvertent storage of patient clinical notes (PHI).

#### Step 4: Patient Acknowledgement
1. Confirm that the patient (or transport courier) acknowledged return condition and item counts.
2. Check the box: *"Patient or caregiver acknowledged return condition and accessory count."*
3. Verify your Staff ID in the witness box (e.g. `STF-COORD-01`).

#### Step 5: Execute Recommendation Engine
1. Click **Execute Recommendation Engine**.
2. The system evaluates all gates against deterministic rules in sub-second time.
3. Review the **Recommendation Badge** and **Explainable Rule Trail** in the right-hand sidebar.
4. If the recommendation is **Ready for reissue**, click **Confirm & Approve Recommendation** to return the unit to available inventory.
5. If the recommendation is **Hold** or **Escalate**, the system automatically routes the unit to the appropriate cleaning bay or biomed bench queue.

---

## 3. Cleaning & Biomedical Technician Workflow

### Goal
Perform sanitization protocols and biomedical bench tests, document cleaning completion, and flag physical defects.

### Step-by-Step Instructions

#### Step 1: Check Assigned Shift Queue
1. Switch active role to **Biomed/Cleaning Tech (`TECH-BIO-01`)**.
2. Open the **Capacity & Shifts** tab to verify available cleaning bays and technician bench capacity.
3. Open the **Device Inventory Pool** tab and filter by **Hold: Cleaning** or **Escalated: Biomed**.

#### Step 2: Execute Sanitization Protocol
1. Retrieve the unit from the intake holding shelf.
2. Perform medical-grade wipe-down or ultrasonic sanitization following facility Protocol B-4.
3. In the Intake portal, pull up the target loan ID.
4. In Step 4 (Sanitization & Cleaning):
   - Set stage to **In Progress** while sanitizing.
   - Set stage to **Completed** upon passing visual bio-burden inspection.
   - Set stage to **Failed** if stains or chemical degradation require deep re-cleaning.
5. Enter your Technician ID (e.g. `TECH-BIO-01`).
6. Click **Execute Recommendation Engine** to refresh the rule trail.

---

## 4. Clinical Supervisor & Auditor Workflow

### Goal
Supervise intake throughput, review edge-case escalations, authorize high-impact overrides with mandatory rationales, and audit immutable event logs.

### Step-by-Step Instructions

#### Step 1: Triage Escalated Loans
1. Switch active role to **Supervisor / Auditor (`SUP-CLIN-01`)**.
2. Pull up any loan marked with a **Hold** or **Escalate** recommendation.
3. Inspect the **Explainable Rule Trail** to see the deterministic justification (e.g., *"Missing required accessories: Power Adapter"*, *"Cleaning status: not_started"*).

#### Step 2: Execute a Human Override (When Clinically Justified)
1. If an operational exception applies (e.g. central stock has a replacement power adapter ready):
2. In the Human Confirmation Gate, click **Override Recommendation**.
3. A secure confirmation modal opens:
   - Select a **Mandatory Override Reason Code**:
     - `ACCESSORY_REPLACED_FROM_STOCK`: Reserve accessory issued immediately.
     - `MANUAL_DEEP_CLEAN_VERIFIED`: Supervisor verified expedited sanitization.
     - `BIOMED_WAIVER`: Minor cosmetic blemish cleared after physical bench test.
     - `EXPEDITED_CLINICAL_NEED`: Emergency palliative loan deployment.
     - `FALSE_DEFECT_FLAG`: Data entry error corrected.
   - Enter a **Mandatory Typed Justification** ($\ge 5$ characters, e.g., *"Stock AC adapter drawn from bin A-4 to redeploy unit for urgent outpatient monitoring."*).
4. Click **Confirm Override & Transition Status**.
5. The device status updates immediately to `available`, and the full rationale is permanently recorded in the immutable audit event log.

#### Step 3: Review Append-Only Audit Log
1. Open the **Append-Only Audit Log** tab.
2. View chronological event records (`LOAN_LOOKUP`, `CHECKLIST_RECORDED`, `RECOMMENDATION_GENERATED`, `CONFIRMATION_OVERRIDDEN`, `STATUS_TRANSITIONED`).
3. Filter by specific Loan IDs to inspect the full provenance trail.
4. Note the green badge: **"Trigger Enforced Immutability"** — SQLite triggers actively reject any SQL `UPDATE` or `DELETE` commands.

#### Step 4: Review Executive Analytics
1. Open the **Executive Analytics** tab.
2. Review the 4 high-level KPI cards:
   - Average Turnaround Time: **2.1 hours** (vs 14.8h baseline).
   - Missing Accessory Escape Rate: **0.0%** (vs 28.6% baseline).
   - Uncleaned Reissue Rate: **0.0%** (vs 21.4% baseline).
   - Supervisor Override Rate: **3.8%** (Target $\le 12.0\%$).
3. Inspect the embedded interactive SVG comparison chart and missing accessory distribution by model.
