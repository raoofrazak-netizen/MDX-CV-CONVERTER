import uuid
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import commands
import insights
import profiles
import storage
import template_engine
import validation
from config import (
    ALLOWED_EXTENSIONS, FRONTEND_DIR, GENERATED_DIR, MAX_UPLOAD_MB, PHOTOS_DIR, SECTION_KEYS, SECTIONS,
    UPLOADS_DIR,
)
from extraction import ExtractionError, blocks_to_plain_text, extract
from formatting import format_item
from models import ItemPatch
from photo import PhotoError, save_uploaded_photo
from pipeline import now_iso, process_cv
from quality import build_quality_report
from rule_classifier import load_custom_headings, register_custom_heading

storage.init_db()
# HR-taught headings apply from the moment the server starts, not just from
# the moment they're added -- otherwise a restart would silently forget
# every mapping until someone re-adds it.
load_custom_headings(storage.list_heading_mappings())

app = FastAPI(title="MDX Faculty CV Converter", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _user_error(message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(status_code=status_code, detail=message)


@app.post("/api/upload")
async def upload_cv(file: UploadFile, background_tasks: BackgroundTasks):
    if not file.filename:
        raise _user_error("No file was provided.")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise _user_error(
            f"Unsupported file type '{suffix}'. Please upload a DOCX or PDF file."
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        raise _user_error(f"File is too large ({size_mb:.1f} MB). Maximum allowed is {MAX_UPLOAD_MB} MB.")
    if size_mb == 0:
        raise _user_error("The uploaded file is empty.")

    cv_id = str(uuid.uuid4())
    stored_path = UPLOADS_DIR / f"{cv_id}{suffix}"
    stored_path.write_bytes(contents)

    storage.create_cv(cv_id, file.filename, str(stored_path), "uploaded", now_iso())
    storage.log_event(cv_id, "uploaded", detail=file.filename)

    background_tasks.add_task(process_cv, cv_id, stored_path, file.filename)

    return {"cv_id": cv_id, "status": "uploaded"}


@app.get("/api/cvs")
def list_cvs():
    return storage.list_cvs()


@app.get("/api/cv/{cv_id}")
def get_cv(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    return cv


@app.get("/api/cv/{cv_id}/items")
def get_items(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    items = storage.get_items(cv_id)
    for it in items:
        it["display_line"] = format_item(it["section"], it["fields"], it["source"]["raw_text"])
    grouped: dict[str, list[dict]] = {k: [] for k in SECTION_KEYS}
    for it in items:
        grouped.setdefault(it["section"], []).append(it)
    return grouped


@app.get("/api/sections")
def get_sections():
    return SECTIONS


@app.get("/api/heading-mappings")
def get_heading_mappings():
    """HR-taught heading -> section rules, most recent first."""
    return storage.list_heading_mappings()


@app.post("/api/heading-mappings")
def create_heading_mapping(payload: dict):
    """Teach the classifier that a specific heading text always means a
    specific section, from now on -- for every CV uploaded after this call,
    not just the one currently under review. This is how a new heading
    stops needing a code change: HR adds the mapping once, here."""
    heading_text = (payload.get("heading_text") or "").strip()
    section_key = payload.get("section_key")
    if not heading_text:
        raise _user_error("Heading text is required.")
    if section_key not in SECTION_KEYS:
        raise _user_error(f"'{section_key}' is not a valid section.")
    mapping = storage.add_heading_mapping(heading_text, section_key)
    register_custom_heading(heading_text, section_key)
    return mapping


@app.delete("/api/heading-mappings/{mapping_id}")
def remove_heading_mapping(mapping_id: str):
    storage.delete_heading_mapping(mapping_id)
    load_custom_headings(storage.list_heading_mappings())
    return {"deleted": True}


@app.post("/api/cv/{cv_id}/photo")
async def upload_photo(cv_id: str, file: UploadFile):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    contents = await file.read()
    if not contents:
        raise _user_error("The uploaded photo is empty.")

    dest_path = PHOTOS_DIR / f"{cv_id}.png"
    try:
        save_uploaded_photo(contents, dest_path)
    except PhotoError as exc:
        raise _user_error(str(exc))

    storage.set_cv_photo(cv_id, str(dest_path))
    storage.log_event(cv_id, "photo_uploaded_manually", detail=file.filename or "")
    return {"cv_id": cv_id, "photo_uploaded": True}


@app.delete("/api/cv/{cv_id}/photo")
def delete_photo(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    photo_path = cv.get("photo_path")
    if photo_path and Path(photo_path).exists():
        Path(photo_path).unlink()
    storage.set_cv_photo(cv_id, None)
    storage.log_event(cv_id, "photo_removed")
    return {"cv_id": cv_id, "photo_uploaded": False}


@app.get("/api/cv/{cv_id}/audit-log")
def get_audit_log(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    return storage.get_audit_log(cv_id)


@app.get("/api/unmapped-headings-summary")
def unmapped_headings_summary():
    rows = storage.list_unmapped_items_with_cv()
    taught = {m["heading_text"].casefold() for m in storage.list_heading_mappings()}
    return insights.summarize_unmapped_headings(rows, taught)


@app.get("/api/settings/auto-approval-threshold")
def get_auto_approval_threshold():
    return {"threshold": validation.auto_approve_threshold()}


@app.put("/api/settings/auto-approval-threshold")
def set_auto_approval_threshold(payload: dict):
    try:
        value = float(payload.get("threshold"))
    except (TypeError, ValueError):
        raise _user_error("threshold must be a number.")
    if value <= 0:
        raise _user_error("threshold must be greater than 0.")
    # HANDOVER.md §3 already documents that a value above 1.0 means "never
    # auto-approve anything" -- allowed deliberately, not a bug.
    storage.set_setting("auto_approve_min_confidence", str(value))
    return {"threshold": value}


@app.get("/api/cv/{cv_id}/photo")
def get_photo(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    photo_path = cv.get("photo_path")
    if not photo_path or not Path(photo_path).exists():
        raise _user_error("No photo set for this CV.", 404)
    return FileResponse(photo_path, media_type="image/png")


@app.post("/api/cv/{cv_id}/items")
def add_item(cv_id: str, payload: dict):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    section = payload.get("section")
    line = (payload.get("line") or "").strip()
    if section not in SECTION_KEYS:
        raise _user_error("Invalid section.")
    if not line:
        raise _user_error("Item text cannot be empty.")

    item = {
        "item_id": str(uuid.uuid4()),
        "cv_id": cv_id,
        "section": section,
        "fields": {"_line_override": line},
        "source": {"document": "HR entry", "raw_text": "(added manually by HR reviewer)", "page": None, "char_offset": None},
        "confidence": 1.0,
        "confidence_band": "high",
        "validation_flags": [],
        "status": "approved",
        "edit_history": [{"at": now_iso(), "action": "manually_added", "previous_fields": None}],
    }
    storage.insert_item(item)
    storage.log_event(cv_id, "item_added_manually", detail=section)
    return item


@app.post("/api/cv/{cv_id}/items/bulk")
def bulk_update_items(cv_id: str, payload: dict):
    """Apply one status to many items at once.

    Scope is either a section ("approve everything under Publications"), a
    confidence band, or every still-pending item. This is what turns review
    of a long CV from ~90 individual clicks into a handful of decisions.
    """
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)

    status = payload.get("status")
    if status not in ("approved", "rejected", "pending_review"):
        raise _user_error("Status must be one of: approved, rejected, pending_review.")

    items = storage.get_items(cv_id)
    section = payload.get("section")
    band = payload.get("confidence_band")
    only_pending = bool(payload.get("only_pending", True))

    if section is not None and section not in SECTION_KEYS:
        raise _user_error(f"'{section}' is not a valid section.")

    targets = [
        i for i in items
        if (section is None or i["section"] == section)
        and (band is None or i["confidence_band"] == band)
        and (not only_pending or i["status"] == "pending_review")
    ]

    changed = storage.bulk_update_status([i["item_id"] for i in targets], status)
    storage.log_event(
        cv_id, "items_bulk_updated",
        detail=f"{changed} -> {status} (section={section}, band={band})",
    )
    return {"updated": changed, "status": status}


@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    item = storage.get_item(item_id)
    if not item:
        raise _user_error("Item not found.", 404)
    storage.delete_item(item_id)
    storage.log_event(item["cv_id"], "item_deleted", detail=item_id)
    return {"deleted": item_id}


@app.patch("/api/items/{item_id}")
def patch_item(item_id: str, patch: ItemPatch):
    item = storage.get_item(item_id)
    if not item:
        raise _user_error("Item not found.", 404)

    updates: dict = {}
    history_entry = {"at": now_iso(), "action": "edit", "previous_fields": item["fields"]}

    if patch.fields is not None:
        updates["fields"] = patch.fields
        updates["status"] = "edited"
        updates["edit_history"] = item["edit_history"] + [history_entry]
    if patch.section is not None:
        if patch.section not in SECTION_KEYS:
            raise _user_error(f"'{patch.section}' is not a valid section.")
        updates["section"] = patch.section
        updates.setdefault("status", "edited")
    if patch.status is not None:
        updates["status"] = patch.status

    if not updates:
        raise _user_error("No changes supplied.")

    storage.update_item(item_id, **updates)
    storage.log_event(item["cv_id"], "item_updated", detail=f"{item_id}: {list(updates.keys())}")
    return storage.get_item(item_id)


@app.post("/api/cv/{cv_id}/command")
def run_command(cv_id: str, payload: dict):
    """Execute a typed plain-English review command."""
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)

    try:
        parsed = commands.parse(payload.get("text", ""))
    except commands.CommandError as exc:
        raise _user_error(str(exc))

    section = parsed.get("section")
    label = next((s["label"] for s in SECTIONS if s["key"] == section), section)
    result: dict = {**parsed, "section_label": label}

    if parsed["action"] == "bulk_status":
        items = storage.get_items(cv_id)
        targets = [
            i for i in items
            if i["status"] == "pending_review"
            and (section is None or i["section"] == section)
        ]
        result["updated"] = storage.bulk_update_status(
            [i["item_id"] for i in targets], parsed["status"])

    elif parsed["action"] == "add_item":
        storage.insert_item(_manual_item(cv_id, section, parsed["line"]))
        result["updated"] = 1

    elif parsed["action"] == "set_field":
        items = storage.get_items(cv_id)
        existing = [i for i in items if i["section"] == section]
        for old in existing:
            storage.delete_item(old["item_id"])
        storage.insert_item(_manual_item(cv_id, section, parsed["value"]))
        result["updated"] = 1

    storage.log_event(cv_id, "command_executed", detail=payload.get("text", "")[:200])
    result["message"] = commands.describe(result)
    return result


def _manual_item(cv_id: str, section: str, line: str) -> dict:
    """An item the reviewer created or corrected by hand. Approved on entry --
    a person typed it, so there is nothing left to verify."""
    return {
        "item_id": str(uuid.uuid4()),
        "cv_id": cv_id,
        "section": section,
        "fields": {"_line_override": line, "value": line},
        "source": {
            "document": "HR entry",
            "raw_text": f"{line}  (entered by reviewer)",
            "page": None,
            "char_offset": None,
        },
        "confidence": 1.0,
        "confidence_band": "high",
        "validation_flags": [],
        "status": "approved",
        "edit_history": [{"at": now_iso(), "action": "manually_added", "previous_fields": None}],
    }


@app.get("/api/cv/{cv_id}/source")
def get_source_document(cv_id: str):
    """Serve the originally uploaded file for the review screen's preview
    pane, so the reviewer can check an item against the real document
    without leaving the page or opening it separately.

    PDFs are served inline and render natively in the browser. DOCX has no
    native browser renderer, so `/source-text` below is used for those.
    """
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    path = Path(cv["stored_path"])
    if not path.exists():
        raise _user_error("The original file is no longer available on the server.", 404)

    media_type = "application/pdf" if path.suffix.lower() == ".pdf" else (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})


@app.get("/api/cv/{cv_id}/source-text")
def get_source_text(cv_id: str):
    """Plain extracted text of the source, used as the preview for DOCX
    uploads (browsers cannot render DOCX) and as a fallback for any PDF the
    viewer refuses to display."""
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    path = Path(cv["stored_path"])
    if not path.exists():
        raise _user_error("The original file is no longer available on the server.", 404)
    try:
        blocks = extract(path)
        return {"cv_id": cv_id, "text": blocks_to_plain_text(blocks)}
    except ExtractionError as exc:
        raise _user_error(str(exc))


@app.get("/api/profiles")
def get_profiles():
    return storage.list_profiles()


@app.get("/api/profiles/{profile_id}")
def get_profile(profile_id: str):
    profile = storage.get_profile(profile_id)
    if not profile:
        raise _user_error("Profile not found.", 404)
    return profile


@app.put("/api/profiles/{profile_id}")
def put_profile(profile_id: str, payload: dict):
    full_name = (payload.get("full_name") or "").strip()
    if not full_name:
        raise _user_error("A profile needs a full name.")
    profile = {
        "profile_id": profile_id,
        "full_name": full_name,
        "job_title": (payload.get("job_title") or "").strip() or None,
        "mdx_email": (payload.get("mdx_email") or "").strip() or None,
        "desk_phone": (payload.get("desk_phone") or "").strip() or None,
        "links": payload.get("links") or {},
        "memberships": [m for m in (payload.get("memberships") or []) if str(m).strip()],
    }
    storage.upsert_profile(profile)
    return storage.get_profile(profile_id)


@app.delete("/api/profiles/{profile_id}")
def remove_profile(profile_id: str):
    if not storage.get_profile(profile_id):
        raise _user_error("Profile not found.", 404)
    storage.delete_profile(profile_id)
    return {"deleted": profile_id}


@app.post("/api/cv/{cv_id}/save-profile")
def save_profile_from_cv(cv_id: str, payload: dict | None = None):
    """Seed or update this person's saved profile from the reviewed CV, so the
    details that no CV carries are only ever entered once."""
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    items = storage.get_items(cv_id)
    profile = profiles.profile_from_cv_items(items, (payload or {}).get("overrides"))
    if not profile:
        raise _user_error("This CV has no full name yet, so a profile can't be created from it.")
    storage.upsert_profile(profile)
    storage.log_event(cv_id, "profile_saved", detail=profile["profile_id"])
    return storage.get_profile(profile["profile_id"])


@app.get("/api/cv/{cv_id}/quality-report")
def quality_report(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    items = storage.get_items(cv_id)
    return build_quality_report(cv_id, items, has_photo=bool(cv.get("photo_path")))


@app.post("/api/cv/{cv_id}/generate")
def generate_cv(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)

    items = storage.get_items(cv_id)
    report = build_quality_report(cv_id, items, has_photo=bool(cv.get("photo_path")))
    if not report["ready_to_download"]:
        raise _user_error(
            "This CV isn't ready to generate yet -- every item must be approved, "
            "edited, or rejected, and no low-confidence items can remain unresolved."
        )

    approved = [i for i in items if i["status"] in ("approved", "edited")]
    items_by_section: dict[str, list[dict]] = {}
    for it in approved:
        items_by_section.setdefault(it["section"], []).append({
            "fields": it["fields"],
            "source_text": it["source"]["raw_text"],
        })

    photo_path = Path(cv["photo_path"]) if cv.get("photo_path") else None

    output_path = GENERATED_DIR / f"{cv_id}.docx"
    try:
        template_engine.populate(items_by_section, photo_path=photo_path, output_path=output_path)
    except template_engine.GenerationError as exc:
        storage.log_event(cv_id, "generation_failed", detail=str(exc))
        raise _user_error(str(exc), 500)

    storage.update_cv_status(cv_id, "generated")
    storage.log_event(cv_id, "generated")
    return {"cv_id": cv_id, "status": "generated"}


@app.get("/api/cv/{cv_id}/download")
def download_cv(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)

    output_path = GENERATED_DIR / f"{cv_id}.docx"
    if not output_path.exists():
        raise _user_error("This CV hasn't been generated yet.", 400)

    storage.update_cv_status(cv_id, "downloaded")
    storage.log_event(cv_id, "downloaded")

    safe_name = Path(cv["original_filename"]).stem
    return FileResponse(
        output_path,
        filename=f"{safe_name} - MDX CV.docx",
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
