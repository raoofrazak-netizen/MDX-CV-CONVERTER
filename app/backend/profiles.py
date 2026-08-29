"""Remembered per-staff details that no CV reliably contains.

Roughly a third of a finished MDX Faculty CV is information the source CV
simply does not carry: the person's MDX corporate email and desk phone (their
CV lists a personal or previous-institution address), their ORCID and LinkedIn
identifiers, and their professional body memberships. Extraction can never
recover these -- they are not in the document at all.

Rather than making a reviewer retype them for every CV, they are stored once
per staff member and re-applied automatically on every future upload.

Provenance is explicit: profile-sourced items are labelled as coming from the
saved staff profile, never presented as if they had been quoted out of the CV.
That keeps the system's core promise intact -- extracted content is always a
verbatim quote, and anything else says plainly where it came from.
"""
import re
import uuid
from typing import Any

PROFILE_SOURCE_LABEL = "Saved staff profile"
PROFILE_SOURCE_TEXT = "(from saved staff profile — not extracted from this CV)"

HONORIFIC_RE = re.compile(r"^(?:dr|prof|professor|mr|mrs|ms|miss|sir|dame)\.?\s+", re.IGNORECASE)

# Which profile field feeds which MDX section. Ordered so the letterhead
# fields are applied before the list sections.
LINK_LABELS = {
    "orcid": "ORCID",
    "linkedin": "LinkedIn",
    "scopus": "Scopus",
    "google_scholar": "Google Scholar",
    "repository": "Research Repository",
    "website": "Website",
}


def profile_id_for(full_name: str) -> str:
    """Stable key for a person: lowercased name, honorific removed.

    Names are the only identifier reliably present across CVs -- a staff
    member's CV usually carries a personal or previous-institution email, not
    the MDX one, so email cannot be the key.
    """
    name = HONORIFIC_RE.sub("", (full_name or "").strip())
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug


def find_profile_for_items(items: list[dict[str, Any]], storage_module: Any) -> dict[str, Any] | None:
    """Look up a saved profile using the name extracted from this CV."""
    name_item = next((i for i in items if i["section"] == "full_name"), None)
    if not name_item:
        return None
    value = (name_item.get("fields", {}) or {}).get("value") or ""
    pid = profile_id_for(value)
    if not pid:
        return None
    return storage_module.get_profile(pid)


def _profile_item(cv_id: str, section: str, fields: dict[str, Any], display: str) -> dict[str, Any]:
    from datetime import datetime, timezone

    return {
        "item_id": str(uuid.uuid4()),
        "cv_id": cv_id,
        "section": section,
        "fields": fields,
        "source": {
            "document": PROFILE_SOURCE_LABEL,
            "raw_text": f"{display}  {PROFILE_SOURCE_TEXT}",
            "page": None,
            "char_offset": None,
        },
        "confidence": 1.0,
        "confidence_band": "high",
        "validation_flags": [],
        "status": "approved",
        "edit_history": [
            {
                "at": datetime.now(timezone.utc).isoformat(),
                "action": "prefilled_from_profile",
                "previous_fields": None,
            }
        ],
    }


def build_prefill_items(cv_id: str, profile: dict[str, Any], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items to add from the saved profile.

    Letterhead fields (email, phone, job title) REPLACE what was extracted:
    an MDX Faculty CV must show the person's MDX contact details, and the
    address on their own CV is usually a personal or former-employer one.
    List sections (memberships, profile links) are only added when the CV
    did not already supply them, so a CV that does list them keeps its own
    wording.
    """
    have = {i["section"] for i in existing}
    out: list[dict[str, Any]] = []

    if profile.get("mdx_email"):
        out.append(_profile_item(
            cv_id, "email", {"value": profile["mdx_email"]}, profile["mdx_email"]))
    if profile.get("desk_phone"):
        out.append(_profile_item(
            cv_id, "contact_info", {"value": profile["desk_phone"]}, profile["desk_phone"]))
    if profile.get("job_title"):
        out.append(_profile_item(
            cv_id, "job_title", {"value": profile["job_title"]}, profile["job_title"]))

    if "profiles_links" not in have:
        for key, url in (profile.get("links") or {}).items():
            if not url:
                continue
            label = LINK_LABELS.get(key, key.replace("_", " ").title())
            out.append(_profile_item(
                cv_id, "profiles_links",
                {"platform": label, "url": url}, f"{label}: {url}"))

    if "associations" not in have:
        for membership in profile.get("memberships") or []:
            if membership.strip():
                out.append(_profile_item(
                    cv_id, "associations", {"description": membership.strip()}, membership.strip()))

    return out


def apply_profile_prefill(cv_id: str, items: list[dict[str, Any]], profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge profile-sourced items in, dropping any extracted letterhead field
    the profile authoritatively overrides."""
    additions = build_prefill_items(cv_id, profile, items)
    overridden = {i["section"] for i in additions if i["section"] in ("email", "contact_info", "job_title")}
    kept = [i for i in items if i["section"] not in overridden]
    return kept + additions


def profile_from_cv_items(items: list[dict[str, Any]], overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Seed a profile from what a reviewed CV already contains, so the first
    save is mostly pre-filled rather than typed from scratch."""
    def first(section: str) -> str:
        for i in items:
            if i["section"] == section:
                fields = i.get("fields", {}) or {}
                return (fields.get("value") or fields.get("title") or "").strip()
        return ""

    full_name = first("full_name")
    if not full_name:
        return None

    links: dict[str, str] = {}
    for i in items:
        if i["section"] != "profiles_links":
            continue
        fields = i.get("fields", {}) or {}
        platform = (fields.get("platform") or "").strip().lower().replace(" ", "_")
        url = (fields.get("url") or "").strip()
        if platform and url:
            links[platform] = url

    memberships = [
        (i.get("fields", {}) or {}).get("description")
        or i.get("source", {}).get("raw_text", "")
        for i in items if i["section"] == "associations"
    ]

    profile = {
        "profile_id": profile_id_for(full_name),
        "full_name": full_name,
        "job_title": first("job_title"),
        "mdx_email": first("email"),
        "desk_phone": first("contact_info"),
        "links": links,
        "memberships": [m.strip() for m in memberships if m and m.strip()],
    }
    if overrides:
        profile.update({k: v for k, v in overrides.items() if v is not None})
        profile["profile_id"] = profile_id_for(profile["full_name"])
    return profile
