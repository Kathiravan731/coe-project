"""
Pydantic schemas for input validation, API contracts, and domain types.
Ensures strict validation on every field and forbids free-text clinical notes.
"""

from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Literal, Dict, Any
from enum import Enum
import re

ALLOWED_WEAR_TAGS = {
    "clean_housing",
    "scratches_cosmetic",
    "strap_frayed",
    "port_dust",
    "screen_blemish",
    "sensor_scuff",
    "casing_crack",
    "label_faded"
}

class DeviceStatus(str, Enum):
    AVAILABLE = "available"
    ON_LOAN = "on_loan"
    IN_INTAKE = "in_intake"
    HOLD_CLEANING = "hold_cleaning"
    HOLD_MISSING_ACCESSORY = "hold_missing_accessory"
    ESCALATED_BIOMED = "escalated_biomed"
    WRITTEN_OFF = "written_off"

class ItemCondition(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    DAMAGED = "damaged"
    EVIDENCE_PENDING = "evidence_pending"

class ConditionCode(str, Enum):
    FUNCTIONAL = "functional"
    NEEDS_INSPECTION = "needs_inspection"
    DAMAGED = "damaged"
    NON_FUNCTIONAL = "non_functional"

class CleaningStage(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class DecisionType(str, Enum):
    APPROVED = "approved"
    OVERRIDDEN = "overridden"

class OverrideReasonCode(str, Enum):
    BIOMED_WAIVER = "BIOMED_WAIVER"
    EXPEDITED_CLINICAL_NEED = "EXPEDITED_CLINICAL_NEED"
    ACCESSORY_REPLACED_FROM_STOCK = "ACCESSORY_REPLACED_FROM_STOCK"
    MANUAL_DEEP_CLEAN_VERIFIED = "MANUAL_DEEP_CLEAN_VERIFIED"
    FALSE_DEFECT_FLAG = "FALSE_DEFECT_FLAG"
    OTHER = "OTHER"

class UserRole(str, Enum):
    COORDINATOR = "coordinator"
    TECHNICIAN = "technician"
    SUPERVISOR = "supervisor"
    AUDITOR = "auditor"

# Request Models
class ChecklistItemEntry(BaseModel):
    item_id: str
    condition: ItemCondition
    photo_ref: Optional[str] = None

class ChecklistSubmission(BaseModel):
    loan_id: str
    items: List[ChecklistItemEntry]
    recorded_by: str

class ConditionSubmission(BaseModel):
    loan_id: str
    condition_code: ConditionCode
    wear_tags: List[str] = Field(default_factory=list)
    recorded_by: str

    @field_validator("wear_tags")
    @classmethod
    def validate_tags(cls, tags: List[str]) -> List[str]:
        for tag in tags:
            if tag not in ALLOWED_WEAR_TAGS:
                raise ValueError(f"Tag '{tag}' is not an allowed wear tag. Only structured tags are permitted; no free-text notes.")
        return tags

class CleaningSubmission(BaseModel):
    loan_id: str
    stage: CleaningStage
    technician_id: str

class AcknowledgementSubmission(BaseModel):
    loan_id: str
    acknowledged: bool
    witness_staff_id: str

class RecommendationRequest(BaseModel):
    loan_id: str

class ConfirmationSubmission(BaseModel):
    rec_id: str
    decision: DecisionType
    confirmed_by: str
    override_reason_code: Optional[OverrideReasonCode] = None
    override_justification: Optional[str] = None

    @field_validator("override_justification")
    @classmethod
    def validate_override(cls, justification: Optional[str], info) -> Optional[str]:
        # If overridden, justification and reason code are mandatory
        data = info.data
        if data.get("decision") == DecisionType.OVERRIDDEN:
            if not justification or len(justification.strip()) < 5:
                raise ValueError("Mandatory typed override justification (minimum 5 chars) is required when overriding.")
            if not data.get("override_reason_code"):
                raise ValueError("Mandatory override reason code is required when overriding.")
        return justification

# Response Models
class RuleTrailResponse(BaseModel):
    recommendation: str
    confidence: float
    rule_trail: List[str]
    fallback_triggered: bool
    proposed_slot: Optional[str] = None
    next_action_route: Optional[str] = None

class DeviceOut(BaseModel):
    device_id: str
    model: str
    category: str
    serial_hash: str
    status: str
    last_status_change_at: str

class LoanLookupOut(BaseModel):
    loan_id: str
    device_id: str
    device_model: str
    device_category: str
    device_status: str
    patient_ref_id: str
    issued_at: str
    issued_accessory_manifest: List[Dict[str, Any]]
    returned_at: Optional[str] = None
    current_checklists: List[Dict[str, Any]] = []
    current_condition: Optional[Dict[str, Any]] = None
    current_cleaning: Optional[Dict[str, Any]] = None
    current_acknowledgement: Optional[Dict[str, Any]] = None
    latest_recommendation: Optional[Dict[str, Any]] = None
    latest_confirmation: Optional[Dict[str, Any]] = None
