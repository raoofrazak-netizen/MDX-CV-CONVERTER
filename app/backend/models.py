from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

ConfidenceBand = Literal["high", "medium", "low"]
ItemStatus = Literal["pending_review", "approved", "edited", "rejected"]
CVStatus = Literal[
    "uploaded", "processing", "extracted", "validation_required",
    "review", "approved", "generated", "downloaded", "failed",
]


class SourceRef(BaseModel):
    document: str
    raw_text: str
    page: Optional[int] = None
    char_offset: Optional[list[int]] = None


class EditHistoryEntry(BaseModel):
    at: str
    action: str
    previous_fields: Optional[dict[str, Any]] = None


class ExtractedItem(BaseModel):
    item_id: str
    cv_id: str
    section: str
    fields: dict[str, Any] = Field(default_factory=dict)
    source: SourceRef
    confidence: float
    confidence_band: ConfidenceBand
    validation_flags: list[str] = Field(default_factory=list)
    status: ItemStatus = "pending_review"
    edit_history: list[EditHistoryEntry] = Field(default_factory=list)


class ItemPatch(BaseModel):
    fields: Optional[dict[str, Any]] = None
    section: Optional[str] = None
    status: Optional[ItemStatus] = None


class CVRecord(BaseModel):
    cv_id: str
    original_filename: str
    stored_path: str
    status: CVStatus
    uploaded_at: str
    error_message: Optional[str] = None


class QualityReportSection(BaseModel):
    section: str
    label: str
    item_count: int
    approved_count: int
    flagged_count: int
    status: Literal["verified", "needs_review", "missing"]


class QualityReport(BaseModel):
    cv_id: str
    overall_confidence: float
    sections: list[QualityReportSection]
    duplicate_flags: list[str]
    formatting_status: Literal["ok", "issues_detected"]
    ready_to_download: bool
