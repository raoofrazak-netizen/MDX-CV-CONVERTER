"""Ties extraction -> classification -> validation -> storage together for
one uploaded CV. Kept synchronous for Phase 1 (expected volume is low; see
build brief). Every step logs to the audit trail and updates cv status so
the frontend can show real progress, not a fake spinner.
"""
import uuid
from datetime import datetime, timezone
from pathlib import Path

import bio_draft
import profiles
import storage
import unmapped
from classifier import ClassificationError, classify
from config import PHOTOS_DIR
from extraction import ExtractionError, blocks_to_plain_text, extract
from photo import extract_photo
from validation import apply_auto_approval, confidence_band, validate_items


def process_cv(cv_id: str, stored_path: Path, original_filename: str) -> None:
    try:
        storage.update_cv_status(cv_id, "processing")
        storage.log_event(cv_id, "extraction_started")

        blocks = extract(stored_path)
        cv_text = blocks_to_plain_text(blocks)
        storage.update_cv_status(cv_id, "extracted")
        storage.log_event(cv_id, "extraction_complete", detail=f"{len(blocks)} text blocks")

        _extract_and_store_photo(cv_id, stored_path)

        raw_items = classify(cv_text, original_filename)
        storage.log_event(cv_id, "ai_classification_complete", detail=f"{len(raw_items)} items")

        items = _to_storage_items(cv_id, raw_items)
        items = validate_items(items)
        items = apply_auto_approval(items)

        bio_item = bio_draft.build_biography_item(cv_id, items)
        if bio_item:
            items.append(bio_item)
            storage.log_event(cv_id, "biography_drafted", detail="left pending for review")

        profile = profiles.find_profile_for_items(items, storage)
        if profile:
            items = profiles.apply_profile_prefill(cv_id, items, profile)
            storage.log_event(
                cv_id, "profile_prefill_applied",
                detail=f"profile={profile['profile_id']}",
            )

        # Runs last, and against the finished item set: anything the
        # classifier, the biography drafter and the profile store between
        # them did not account for is content that would otherwise be lost,
        # so it is carried into the UNMAPPED INFORMATION note for HR.
        unmapped_items = unmapped.build_unmapped_items(cv_id, cv_text, items)
        if unmapped_items:
            items.extend(unmapped_items)
            storage.log_event(
                cv_id, "unmapped_content_flagged",
                detail=f"{len(unmapped_items)} source lines mapped to no MDX section",
            )

        storage.save_items(cv_id, items)
        auto = sum(1 for i in items if i["status"] == "approved")
        storage.log_event(
            cv_id, "auto_approval_complete",
            detail=f"{auto} auto-approved, {len(items) - auto} need review",
        )

        storage.update_cv_status(cv_id, "validation_required")
        storage.log_event(cv_id, "validation_complete")
        storage.update_cv_status(cv_id, "review")

    except ExtractionError as exc:
        storage.update_cv_status(cv_id, "failed", error_message=str(exc))
        storage.log_event(cv_id, "extraction_failed", detail=str(exc))
    except ClassificationError as exc:
        storage.update_cv_status(cv_id, "failed", error_message=str(exc))
        storage.log_event(cv_id, "classification_failed", detail=str(exc))
    except Exception as exc:  # last-resort guard: never leak a raw traceback to HR
        storage.update_cv_status(
            cv_id, "failed",
            error_message="Something went wrong while processing this CV. Please try again or contact support.",
        )
        storage.log_event(cv_id, "unexpected_failure", detail=str(exc))


def _extract_and_store_photo(cv_id: str, stored_path: Path) -> None:
    """Best-effort headshot pull. Never fails the pipeline -- a CV without a
    detectable photo just generates without one, same as the manual process."""
    try:
        png_bytes = extract_photo(stored_path)
        if not png_bytes:
            storage.log_event(cv_id, "photo_not_found")
            return
        photo_path = PHOTOS_DIR / f"{cv_id}.png"
        photo_path.write_bytes(png_bytes)
        storage.set_cv_photo(cv_id, str(photo_path))
        storage.log_event(cv_id, "photo_extracted", detail=str(photo_path))
    except Exception as exc:
        storage.log_event(cv_id, "photo_extraction_failed", detail=str(exc))


def _to_storage_items(cv_id: str, raw_items: list[dict]) -> list[dict]:
    out = []
    for raw in raw_items:
        confidence = float(raw.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        out.append({
            "item_id": str(uuid.uuid4()),
            "cv_id": cv_id,
            "section": raw["section"],
            "fields": raw.get("fields", {}),
            "source": {
                "document": "",  # filled by caller context if needed later
                "raw_text": raw["source_text"],
                "page": None,
                "char_offset": None,
            },
            "confidence": confidence,
            "confidence_band": confidence_band(confidence),
            # Flags the classifier already set (e.g. "rerouted_by_content"
            # from routing.py or the résumé skills/awards reclassification)
            # must survive to storage, not be discarded here -- this was
            # silently dropping them, so a reviewer had no way to see WHY
            # an item was re-filed and capped below auto-approval, only
            # that it was. validate_items() below still adds its own
            # confidence-band flags on top of whatever is already present.
            "validation_flags": list(raw.get("validation_flags", [])),
            "status": "pending_review",
            "edit_history": [],
        })
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
