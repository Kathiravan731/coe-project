/**
 * MediLoan Pilot Application Controller
 * Handles zero-PHI intake workflow, explainable recommendation rendering,
 * human confirmation/override gate, live capacity, dashboard metrics, and audit log.
 */

let currentRole = "coordinator";
let currentUserId = "STF-COORD-01";
let activeLoan = null;
let latestRecommendation = null;
let currentChecklistState = {}; // item_id -> { condition, photo_ref }

// Role mapping
const ROLE_USER_MAP = {
  coordinator: "STF-COORD-01",
  technician: "TECH-BIO-01",
  supervisor: "SUP-CLIN-01",
  auditor: "AUD-REG-01"
};

// Standard Fetch Helper injecting RBAC headers
async function apiFetch(endpoint, options = {}) {
  const headers = options.headers || {};
  headers["X-User-Role"] = currentRole;
  headers["X-User-Id"] = currentUserId;
  headers["Content-Type"] = headers["Content-Type"] || "application/json";

  const response = await fetch(endpoint, { ...options, headers });
  if (!response.ok) {
    const errorData = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(errorData.detail || `Request failed with status ${response.status}`);
  }
  return response.json();
}

// Initialization
document.addEventListener("DOMContentLoaded", () => {
  initRoleSelector();
  initNavigation();
  initLookupHandlers();
  initWearTags();
  initRecommendationHandlers();
  initConfirmationModal();
  initDashboard();
  initCapacityView();
  initAuditLog();
  initDevicePool();

  // Load default sample loan on launch
  lookupLoan("LN-2026-0131");
});

// Role Switcher
function initRoleSelector() {
  const roleSelect = document.getElementById("roleSelect");
  roleSelect.addEventListener("change", (e) => {
    currentRole = e.target.value;
    currentUserId = ROLE_USER_MAP[currentRole] || "STF-ANON";
    console.log(`Switched role to: ${currentRole} (${currentUserId})`);
    
    // Refresh views that have role restrictions
    if (document.getElementById("auditTab").classList.contains("active")) {
      loadAuditLog();
    }
  });
}

// Navigation Tabs
function initNavigation() {
  const navTabs = document.querySelectorAll(".nav-tab");
  navTabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      navTabs.forEach((t) => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

      tab.classList.add("active");
      const targetId = tab.getAttribute("data-tab");
      const targetContent = document.getElementById(targetId);
      if (targetContent) {
        targetContent.classList.add("active");
      }

      // Trigger refreshes
      if (targetId === "dashboardTab") loadDashboardMetrics();
      if (targetId === "capacityTab") loadCapacitySlots();
      if (targetId === "auditTab") loadAuditLog();
      if (targetId === "devicesTab") loadDevicePool();
    });
  });
}

// 1. Lookup Handlers
function initLookupHandlers() {
  const searchInput = document.getElementById("loanSearchInput");
  const lookupBtn = document.getElementById("lookupSubmitBtn");
  const scanBtn = document.getElementById("scanMockBtn");
  const sampleChips = document.querySelectorAll(".sample-chip");

  lookupBtn.addEventListener("click", () => {
    const query = searchInput.value.trim();
    if (query) lookupLoan(query);
  });

  searchInput.addEventListener("keypress", (e) => {
    if (e.key === "Enter") {
      const query = searchInput.value.trim();
      if (query) lookupLoan(query);
    }
  });

  sampleChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      const query = chip.getAttribute("data-query");
      searchInput.value = query;
      lookupLoan(query);
    });
  });

  scanBtn.addEventListener("click", () => {
    scanBtn.disabled = true;
    scanBtn.innerHTML = "Scanning Barcode...";
    setTimeout(() => {
      scanBtn.disabled = false;
      scanBtn.innerHTML = `
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 7V5a2 2 0 012-2h2M17 3h2a2 2 0 012 2v2M21 17v2a2 2 0 01-2 2h-2M7 21H5a2 2 0 01-2-2v-2M7 8h10M7 12h10M7 16h6"/></svg>
        Scan Barcode
      `;
      const randomLoans = ["LN-2026-0131", "LN-2026-0132", "LN-2026-0133", "LN-2026-0134"];
      const scanned = randomLoans[Math.floor(Math.random() * randomLoans.length)];
      searchInput.value = scanned;
      lookupLoan(scanned);
    }, 600);
  });
}

async function lookupLoan(query) {
  const alertBox = document.getElementById("lookupAlert");
  const workflowArea = document.getElementById("loanWorkflowArea");
  alertBox.classList.add("hidden");
  alertBox.className = "alert-box hidden";

  try {
    const data = await apiFetch(`/api/loans/lookup?query=${encodeURIComponent(query)}`);
    activeLoan = data;
    renderLoanSummary(data);
    renderAccessoryChecklist(data);
    workflowArea.classList.remove("hidden");
    resetRecommendationArea();
  } catch (err) {
    workflowArea.classList.add("hidden");
    alertBox.textContent = err.message;
    alertBox.className = "alert-box alert-danger";
    alertBox.classList.remove("hidden");
  }
}

function renderLoanSummary(loan) {
  document.getElementById("summaryLoanId").textContent = loan.loan_id;
  document.getElementById("summaryDevice").textContent = `${loan.device_id} (${loan.device_model})`;
  document.getElementById("summaryCategory").textContent = loan.device_category;
  document.getElementById("summaryPatientRef").textContent = loan.patient_ref_id;
  document.getElementById("summaryIssueDate").textContent = new Date(loan.issued_at).toLocaleDateString();

  const statusBadge = document.getElementById("summaryDeviceStatus");
  statusBadge.textContent = loan.device_status.toUpperCase().replace("_", " ");
  statusBadge.className = `badge badge-${getStatusBadgeClass(loan.device_status)}`;
}

function getStatusBadgeClass(status) {
  switch (status) {
    case "available": return "success";
    case "on_loan": return "info";
    case "in_intake": return "warning";
    case "hold_cleaning": return "info";
    case "hold_missing_accessory": return "warning";
    case "escalated_biomed": return "danger";
    default: return "info";
  }
}

// 2. Accessory Checklist Rendering
function renderAccessoryChecklist(loan) {
  const tbody = document.getElementById("accessoryTableBody");
  tbody.innerHTML = "";
  currentChecklistState = {};

  loan.issued_accessory_manifest.forEach((acc) => {
    currentChecklistState[acc.item_id] = { condition: "present", photo_ref: null };

    const tr = document.createElement("tr");
    tr.id = `row-${acc.item_id}`;

    tr.innerHTML = `
      <td>
        <strong>${acc.item_name}</strong>
        <div style="font-size:0.75rem; color:var(--text-subtle); font-family:'JetBrains Mono';">${acc.item_id}</div>
      </td>
      <td>
        ${acc.required ? '<span class="badge badge-info">Required</span>' : '<span class="badge" style="background:#334155;color:#94a3b8;">Optional</span>'}
      </td>
      <td>
        <div class="status-button-group" data-item="${acc.item_id}">
          <button type="button" class="status-opt-btn active present" data-cond="present">Present</button>
          <button type="button" class="status-opt-btn missing" data-cond="missing">Missing</button>
          <button type="button" class="status-opt-btn damaged" data-cond="damaged">Damaged</button>
          <button type="button" class="status-opt-btn evidence_pending" data-cond="evidence_pending">Pending</button>
        </div>
      </td>
      <td>
        <div class="photo-evidence-cell" id="photoCell-${acc.item_id}">
          <button type="button" class="btn-photo-upload" onclick="mockAttachPhoto('${acc.item_id}')">
            📷 Attach Photo
          </button>
        </div>
      </td>
    `;

    tbody.appendChild(tr);
  });

  // Attach button group listeners
  document.querySelectorAll(".status-opt-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      const group = btn.parentElement;
      const itemId = group.getAttribute("data-item");
      const cond = btn.getAttribute("data-cond");

      group.querySelectorAll(".status-opt-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      currentChecklistState[itemId].condition = cond;
    });
  });

  // Edge case 2: simulate conflict button
  document.getElementById("btnConflictSim").onclick = async () => {
    if (!activeLoan) return;
    const firstItem = activeLoan.issued_accessory_manifest[0].item_id;
    try {
      // Stage 1: mark present
      await apiFetch("/api/returns/checklist", {
        method: "POST",
        body: JSON.stringify({
          loan_id: activeLoan.loan_id,
          items: [{ item_id: firstItem, condition: "present", photo_ref: null }],
          recorded_by: "STF-COORD-01"
        })
      });
      // Stage 2: mark missing by tech
      const res = await apiFetch("/api/returns/checklist", {
        method: "POST",
        headers: { "X-User-Role": "technician", "X-User-Id": "TECH-BIO-01" },
        body: JSON.stringify({
          loan_id: activeLoan.loan_id,
          items: [{ item_id: firstItem, condition: "missing", photo_ref: null }],
          recorded_by: "TECH-BIO-01"
        })
      });
      alert(`Conflict Simulated! System detected checklist disagreement on '${firstItem}'. Conflict flag: ${res.conflict_detected}.`);
      triggerRecommendationRun();
    } catch (err) {
      alert("Simulation error: " + err.message);
    }
  };

  // Edge case 5: simulate upload failure
  document.getElementById("btnUploadFailSim").onclick = async () => {
    if (!activeLoan) return;
    const firstItem = activeLoan.issued_accessory_manifest[0].item_id;
    try {
      await apiFetch(`/api/returns/upload-evidence-mock?item_id=${firstItem}&simulate_failure=true`, { method: "POST" });
    } catch (err) {
      alert(`Edge Case 5 Triggered: ${err.message}`);
      // Set to evidence pending
      const row = document.getElementById(`row-${firstItem}`);
      if (row) {
        row.querySelectorAll(".status-opt-btn").forEach((b) => b.classList.remove("active"));
        const pendingBtn = row.querySelector('.status-opt-btn.evidence_pending');
        if (pendingBtn) pendingBtn.classList.add("active");
        currentChecklistState[firstItem].condition = "evidence_pending";
      }
    }
  };
}

window.mockAttachPhoto = async function(itemId) {
  try {
    const res = await apiFetch(`/api/returns/upload-evidence-mock?item_id=${itemId}`, { method: "POST" });
    currentChecklistState[itemId].photo_ref = res.photo_ref;
    const cell = document.getElementById(`photoCell-${itemId}`);
    cell.innerHTML = `
      <span style="font-size:0.75rem; color:var(--success); font-weight:600;">✅ Uploaded</span>
      <span style="font-size:0.65rem; color:var(--text-subtle); font-family:'JetBrains Mono';">${res.photo_ref.split("/").pop()}</span>
    `;
  } catch (err) {
    alert("Upload error: " + err.message);
  }
};

// 3. Wear Tags Cloud
function initWearTags() {
  const tagChips = document.querySelectorAll(".tag-chip");
  tagChips.forEach((chip) => {
    chip.addEventListener("click", () => {
      chip.classList.toggle("active");
    });
  });

  // Edge case 4: patient dispute simulator
  document.getElementById("btnSimulateRefusal").onclick = () => {
    const chk = document.getElementById("patientAckCheckbox");
    chk.checked = false;
    alert("Patient acknowledgement dispute simulated: Hand-back acknowledgement unchecked.");
  };
}

function getSelectedWearTags() {
  const activeTags = [];
  document.querySelectorAll(".tag-chip.active").forEach((chip) => {
    activeTags.push(chip.getAttribute("data-tag"));
  });
  return activeTags;
}

// 6. Recommendation Engine Execution
function initRecommendationHandlers() {
  const btn = document.getElementById("btnGenerateRec");
  btn.addEventListener("click", () => {
    triggerRecommendationRun();
  });
}

async function triggerRecommendationRun() {
  if (!activeLoan) return;
  const btn = document.getElementById("btnGenerateRec");
  btn.disabled = true;
  btn.innerHTML = "Evaluating Clinical Rules...";

  try {
    // 1. Submit current checklist
    const checklistItems = Object.keys(currentChecklistState).map((id) => ({
      item_id: id,
      condition: currentChecklistState[id].condition,
      photo_ref: currentChecklistState[id].photo_ref
    }));

    await apiFetch("/api/returns/checklist", {
      method: "POST",
      body: JSON.stringify({
        loan_id: activeLoan.loan_id,
        items: checklistItems,
        recorded_by: currentUserId
      })
    });

    // 2. Submit Condition
    const conditionCode = document.querySelector('input[name="conditionRubric"]:checked').value;
    const wearTags = getSelectedWearTags();
    await apiFetch("/api/returns/condition", {
      method: "POST",
      body: JSON.stringify({
        loan_id: activeLoan.loan_id,
        condition_code: conditionCode,
        wear_tags: wearTags,
        recorded_by: currentUserId
      })
    });

    // 3. Submit Cleaning
    const cleaningStage = document.getElementById("cleaningStageSelect").value;
    const techId = document.getElementById("technicianIdInput").value.trim() || "TECH-BIO-01";
    await apiFetch("/api/returns/cleaning", {
      method: "POST",
      body: JSON.stringify({
        loan_id: activeLoan.loan_id,
        stage: cleaningStage,
        technician_id: techId
      })
    });

    // 4. Submit Acknowledgement
    const acknowledged = document.getElementById("patientAckCheckbox").checked;
    const witnessId = document.getElementById("witnessStaffIdInput").value.trim() || "STF-COORD-01";
    await apiFetch("/api/returns/acknowledgement", {
      method: "POST",
      body: JSON.stringify({
        loan_id: activeLoan.loan_id,
        acknowledged: acknowledged,
        witness_staff_id: witnessId
      })
    });

    // 5. Execute Recommendation Engine
    const recResponse = await apiFetch("/api/returns/recommend", {
      method: "POST",
      body: JSON.stringify({ loan_id: activeLoan.loan_id })
    });

    // Re-fetch loan to get newly assigned recommendation ID
    const updatedLoan = await apiFetch(`/api/loans/lookup?query=${activeLoan.loan_id}`);
    latestRecommendation = updatedLoan.latest_recommendation;

    renderRecommendation(recResponse);
  } catch (err) {
    alert("Recommendation execution error: " + err.message);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>
      Execute Recommendation Engine
    `;
  }
}

function resetRecommendationArea() {
  document.getElementById("recResultArea").classList.remove("hidden");
  document.getElementById("recContentBox").classList.add("hidden");
  document.getElementById("gateStatusMsg").classList.add("hidden");
}

function renderRecommendation(data) {
  document.getElementById("recResultArea").classList.add("hidden");
  const contentBox = document.getElementById("recContentBox");
  contentBox.classList.remove("hidden");

  // Badge
  const badge = document.getElementById("recBadge");
  badge.textContent = data.recommendation;
  badge.className = "rec-badge";

  if (data.recommendation === "Ready for reissue") {
    badge.classList.add("ready");
  } else if (data.recommendation.includes("cleaning")) {
    badge.classList.add("cleaning");
  } else if (data.recommendation.includes("missing")) {
    badge.classList.add("missing");
  } else {
    badge.classList.add("escalate");
  }

  // Confidence
  const pct = Math.round(data.confidence * 100);
  document.getElementById("confidenceVal").textContent = `${pct}%`;

  // Fallback badge
  const fallbackBadge = document.getElementById("fallbackBadge");
  if (data.fallback_triggered) {
    fallbackBadge.classList.remove("hidden");
  } else {
    fallbackBadge.classList.add("hidden");
  }

  // Proposed capacity slot
  const slotText = document.getElementById("proposedSlotText");
  slotText.textContent = data.proposed_slot || "No turnaround queue slot required (Ready for immediate redeployment).";

  // Rule Trail List
  const list = document.getElementById("ruleTrailList");
  list.innerHTML = "";
  data.rule_trail.forEach((rule) => {
    const li = document.createElement("li");
    li.textContent = rule;
    list.appendChild(li);
  });
}

// 7. Human Confirmation & Override
function initConfirmationModal() {
  const btnApprove = document.getElementById("btnApproveRec");
  const btnOverride = document.getElementById("btnOverrideRec");
  const modal = document.getElementById("overrideModal");
  const btnClose = document.getElementById("btnCloseModal");
  const btnCancel = document.getElementById("btnCancelOverride");
  const btnSubmitOverride = document.getElementById("btnSubmitOverride");

  // One-click Approve
  btnApprove.addEventListener("click", async () => {
    if (!latestRecommendation) return;
    try {
      const res = await apiFetch("/api/returns/confirm", {
        method: "POST",
        body: JSON.stringify({
          rec_id: latestRecommendation.rec_id,
          decision: "approved",
          confirmed_by: currentUserId
        })
      });
      showGateSuccess(`Confirmed & Approved! Device status successfully updated to '${res.new_device_status}'. Event appended to immutable log.`);
      lookupLoan(activeLoan.loan_id);
    } catch (err) {
      alert("Approval error: " + err.message);
    }
  });

  // Open Override Modal
  btnOverride.addEventListener("click", () => {
    if (!latestRecommendation) return;
    if (currentRole !== "supervisor" && currentRole !== "coordinator") {
      alert("Role Permission Restriction: Only supervisors or coordinators may perform recommendation overrides.");
      return;
    }
    modal.classList.remove("hidden");
  });

  const closeModal = () => modal.classList.add("hidden");
  btnClose.addEventListener("click", closeModal);
  btnCancel.addEventListener("click", closeModal);

  // Submit Override
  btnSubmitOverride.addEventListener("click", async () => {
    const reasonCode = document.getElementById("overrideReasonCodeSelect").value;
    const justification = document.getElementById("overrideJustificationInput").value.trim();

    if (!justification || justification.length < 5) {
      alert("Mandatory Field: Please provide a specific typed technical/administrative justification (minimum 5 characters).");
      return;
    }

    try {
      const res = await apiFetch("/api/returns/confirm", {
        method: "POST",
        body: JSON.stringify({
          rec_id: latestRecommendation.rec_id,
          decision: "overridden",
          confirmed_by: currentUserId,
          override_reason_code: reasonCode,
          override_justification: justification
        })
      });
      closeModal();
      showGateSuccess(`Recommendation Overridden! New device status: '${res.new_device_status}'. Reason code and justification stored in audit event.`);
      lookupLoan(activeLoan.loan_id);
    } catch (err) {
      alert("Override submission error: " + err.message);
    }
  });
}

function showGateSuccess(msg) {
  const gateMsg = document.getElementById("gateStatusMsg");
  gateMsg.textContent = msg;
  gateMsg.className = "gate-status-msg alert-box alert-success";
  gateMsg.classList.remove("hidden");
}

// Executive Dashboard
function initDashboard() {
  loadDashboardMetrics();
}

async function loadDashboardMetrics() {
  try {
    const data = await apiFetch("/api/reporting/dashboard");
    
    // Override Rate
    const overrideRateElem = document.getElementById("dashOverrideRate");
    if (overrideRateElem) {
      overrideRateElem.textContent = `${data.override_rate_pct}%`;
    }

    // Missing by model bars
    const chartContainer = document.getElementById("missingAccessoriesChart");
    if (chartContainer && data.missing_accessories_by_model) {
      chartContainer.innerHTML = "";
      const models = Object.keys(data.missing_accessories_by_model);
      const maxCount = Math.max(...Object.values(data.missing_accessories_by_model), 1);

      models.forEach((model) => {
        const count = data.missing_accessories_by_model[model];
        const pct = Math.round((count / maxCount) * 100);

        const row = document.createElement("div");
        row.className = "bar-row";
        row.innerHTML = `
          <div class="bar-header">
            <span>${model}</span>
            <span style="color:var(--primary); font-family:'JetBrains Mono';">${count} items</span>
          </div>
          <div class="bar-track">
            <div class="bar-fill" style="width: ${pct}%;"></div>
          </div>
        `;
        chartContainer.appendChild(row);
      });
    }
  } catch (err) {
    console.error("Dashboard error:", err);
  }
}

// Capacity Planning
function initCapacityView() {
  const refreshBtn = document.getElementById("btnRefreshCapacity");
  if (refreshBtn) refreshBtn.addEventListener("click", loadCapacitySlots);
}

async function loadCapacitySlots() {
  const grid = document.getElementById("capacityCardsGrid");
  if (!grid) return;
  grid.innerHTML = '<div style="color:var(--text-muted);">Loading capacity slots...</div>';

  try {
    const data = await apiFetch("/api/capacity");
    grid.innerHTML = "";

    data.slots.forEach((slot) => {
      const card = document.createElement("div");
      card.className = "capacity-slot-card";
      const roleClass = slot.role === "cleaning_bay" ? "role-cleaning" : "role-tech";
      const roleLabel = slot.role === "cleaning_bay" ? "Sanitization Bay" : "Biomed Technician";
      const remaining = slot.capacity - slot.booked;

      card.innerHTML = `
        <div class="slot-card-header">
          <span class="slot-role-badge ${roleClass}">${roleLabel}</span>
          <span style="font-size:0.8rem; font-weight:700; color:var(--text-muted);">${slot.shift_name}</span>
        </div>
        <div style="font-size:0.95rem; font-weight:700; margin-bottom:0.75rem;">${slot.shift_date}</div>
        <div class="slot-metrics">
          <span>Booked: <strong>${slot.booked}/${slot.capacity}</strong></span>
          <span style="color:${remaining > 0 ? 'var(--success)' : 'var(--danger)'};"><strong>${remaining} slots left</strong></span>
        </div>
        <div class="bar-track">
          <div class="bar-fill" style="width: ${slot.utilization_pct}%; background: ${slot.utilization_pct > 80 ? 'var(--danger)' : 'var(--primary)'};"></div>
        </div>
      `;
      grid.appendChild(card);
    });

    // Update Header Pill
    const pill = document.getElementById("capacityStatusText");
    if (pill && data.next_cleaning_bay) {
      pill.textContent = `Bays: ${data.next_cleaning_bay.remaining_capacity || 0} Avail`;
    }
  } catch (err) {
    grid.innerHTML = `<div class="alert-box alert-danger">${err.message}</div>`;
  }
}

// Audit Log Viewer
function initAuditLog() {
  const filterBtn = document.getElementById("btnFilterAudit");
  const clearBtn = document.getElementById("btnClearAudit");
  const input = document.getElementById("auditLoanFilter");

  if (filterBtn) filterBtn.addEventListener("click", () => loadAuditLog(input.value.trim()));
  if (clearBtn) clearBtn.addEventListener("click", () => { input.value = ""; loadAuditLog(); });
}

async function loadAuditLog(loanIdFilter = "") {
  const tbody = document.getElementById("auditTableBody");
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">Fetching append-only events...</td></tr>';

  try {
    const url = loanIdFilter ? `/api/events?loan_id=${encodeURIComponent(loanIdFilter)}` : "/api/events?limit=40";
    const events = await apiFetch(url);

    tbody.innerHTML = "";
    if (events.length === 0) {
      tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">No events found matching criteria.</td></tr>';
      return;
    }

    events.forEach((evt) => {
      const tr = document.createElement("tr");
      const shortPayload = JSON.stringify(evt.payload).slice(0, 50) + "...";

      tr.innerHTML = `
        <td style="font-family:'JetBrains Mono'; font-size:0.75rem; color:var(--primary);">${evt.event_id}</td>
        <td style="font-size:0.78rem; color:var(--text-muted);">${new Date(evt.occurred_at).toLocaleTimeString()}</td>
        <td><span class="pill-tag blue-tag">${evt.event_type}</span></td>
        <td style="font-family:'JetBrains Mono'; font-size:0.8rem;">${evt.loan_id || "N/A"}</td>
        <td style="font-size:0.78rem; font-weight:600;">${evt.actor_id}</td>
        <td style="font-family:'JetBrains Mono'; font-size:0.72rem; color:var(--text-subtle);" title='${JSON.stringify(evt.payload, null, 2)}'>
          ${shortPayload}
        </td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="alert-box alert-danger">${err.message}</td></tr>`;
  }
}

// Device Inventory Pool
function initDevicePool() {
  const pills = document.querySelectorAll(".device-filter-pills .filter-chip");
  pills.forEach((chip) => {
    chip.addEventListener("click", () => {
      pills.forEach((p) => p.classList.remove("active"));
      chip.classList.add("active");
      const filter = chip.getAttribute("data-filter");
      loadDevicePool(filter);
    });
  });
}

async function loadDevicePool(statusFilter = "") {
  const tbody = document.getElementById("deviceTableBody");
  if (!tbody) return;
  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:var(--text-muted);">Loading devices...</td></tr>';

  try {
    const url = statusFilter ? `/api/devices?status_filter=${encodeURIComponent(statusFilter)}` : "/api/devices";
    const devices = await apiFetch(url);

    tbody.innerHTML = "";
    devices.forEach((dev) => {
      const tr = document.createElement("tr");
      const shortHash = dev.serial_hash.slice(0, 10) + "...";

      tr.innerHTML = `
        <td style="font-family:'JetBrains Mono'; font-weight:700; color:var(--primary);">${dev.device_id}</td>
        <td><strong>${dev.model}</strong></td>
        <td>${dev.category}</td>
        <td style="font-family:'JetBrains Mono'; font-size:0.75rem; color:var(--text-subtle);">${shortHash}</td>
        <td><span class="badge badge-${getStatusBadgeClass(dev.status)}">${dev.status.toUpperCase().replace("_", " ")}</span></td>
        <td style="font-size:0.78rem; color:var(--text-muted);">${new Date(dev.last_status_change_at).toLocaleString()}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="alert-box alert-danger">${err.message}</td></tr>`;
  }
}
