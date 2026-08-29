# Build Plan — Portal Enhancements (Phase 2)

Companion to `HANDOVER.md` and `FIXLOG.md`. Where those describe the system
as it stands and its history, this describes **what to build next, exactly
how, and how to prove it didn't break anything.** It covers the seven items
from `MDX_CV_Converter_Enhancement_Recommendations.docx` that don't require
authentication. Every file, function, and endpoint named below was checked
against the actual code, not proposed in the abstract.

**Every phase in this plan — backend and frontend — has since been built
and run for real in an isolated sandbox, not just written**: the backend
against real corpus CVs through direct API calls (one real bug found and
fixed — see the unmapped-headings summary section below), and the
frontend by scripting an actual Chromium browser against the running
server (batch upload, the new `profiles.html`, the activity log, the
hard-to-parse banner, the name-confirmation notice, and the
unmapped-headings dashboard's teach flow all exercised end to end — zero
bugs found there). `BUILD.md` is the up-to-date, single-file version of
this plan and carries the full verification write-up; this file is kept
as reference.

---

## 0. The one rule that matters most

**Every fix in `FIXLOG.md` was hard-won.** The classifier, router, and
extraction logic were tuned against a 34-CV corpus through dozens of
narrowly-scoped, individually-validated changes — several broad "obvious"
fixes were built, tested, and explicitly reverted because they broke a
different CV (see FIXLOG's "Trying, and rejecting, a fully general fix"
entry). None of that is in scope here, and none of it should be touched.

**Files this build must not modify:**

```
rule_classifier.py   routing.py        extraction.py
template_engine.py   formatting.py     bio_draft.py
identifiers.py        commands.py       classifier.py
photo.py
```

Everything in this plan lives in three places instead: a new, additive
database table; a small number of new, additive API endpoints; and frontend
files. Nothing here changes what gets extracted, how it's classified, or
what a generated document contains. If a step in this plan ever seems to
require touching one of the files above, stop and re-scope — that's a sign
the feature has drifted outside what was asked for.

**Definition of done, for every item below:** `cd app/backend && python
test_corpus.py` reports the same pass count and the same two pre-existing
failures (the blank vendor templates) as the baseline run before this build
started. If that number moves, the change is not done — it's a regression.

---

## 1. File manifest

| File | Change |
|---|---|
| `app/backend/storage.py` | Add one table (`app_settings`) and four small functions. No changes to existing tables or functions. |
| `app/backend/validation.py` | Replace one module-level constant lookup with a function that falls back to that same constant. |
| `app/backend/main.py` | Add four new endpoints. No changes to any existing endpoint. |
| `app/backend/insights.py` | **New file.** Pure functions for the cross-CV dashboard. Touches no other module's data. |
| `app/frontend/index.html` | Multi-file upload; new "Auto-approval setting" card; new "Frequently unmapped headings" card. |
| `app/frontend/review.html` | New "Activity Log" panel; new "layout may be hard to parse" banner; new "confirm detected name" notice. |
| `app/frontend/profiles.html` | **New file.** Staff profile list + edit screen. |
| `app/frontend/app.js` | One new shared helper (`actionLabel`), used by the activity log. |
| `app/frontend/styles.css` | A handful of additive classes (`.banner-warn`, `.audit-row`, `.settings-card`). No existing rules changed. |

Nothing in `app/backend/rule_classifier.py` and the other protected files
above appears in this table. That is the point.

---

## 2. Database change

One new table, appended to the existing `SCHEMA` string in `storage.py`.
Nothing else in the schema changes — no `ALTER TABLE` on `cvs`, `items`,
`staff_profiles`, `audit_log`, or `custom_heading_mappings`.

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Add alongside the other storage functions:

```python
def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with get_conn() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
            return row["value"] if row else default
    except sqlite3.OperationalError:
        # app_settings doesn't exist yet (e.g. a test harness that talks to
        # validation.py directly without calling storage.init_db() first).
        # Falling back to the caller's default here, rather than raising,
        # is what keeps this change invisible to every existing test and
        # every CV processed before a setting is ever written.
        return default


def set_setting(key: str, value: str) -> None:
    from datetime import datetime, timezone
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value, updated_at = excluded.updated_at""",
            (key, value, datetime.now(timezone.utc).isoformat()),
        )


def get_audit_log(cv_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, cv_id, at, action, detail FROM audit_log "
            "WHERE cv_id = ? ORDER BY at ASC",
            (cv_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_unmapped_items_with_cv() -> list[dict]:
    """Raw rows for the cross-CV dashboard. Returns fields as a JSON
    string -- decoding is insights.py's job, not storage's, matching how
    _row_to_item() is the only place that decodes elsewhere."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT cv_id, fields FROM items WHERE section = 'unmapped'"
        ).fetchall()
        return [dict(r) for r in rows]
```

That's the entire database change. It's additive, it's one table, and every
function above degrades to "act as if nothing changed" when the table or a
given key doesn't exist.

---

## 3. Backend changes, one feature at a time

### 3.1 Activity log (`GET /api/cv/{cv_id}/audit-log`)

The `audit_log` table already exists and is already populated —
`pipeline.py` and `main.py` log to it on every step (`extraction_started`,
`ai_classification_complete`, `auto_approval_complete`, `item_updated`,
`command_executed`, `generated`, `downloaded`, and a dozen more). This
feature adds a way to read it back. Nothing about what gets logged, or when,
changes.

```python
# main.py
@app.get("/api/cv/{cv_id}/audit-log")
def get_audit_log(cv_id: str):
    cv = storage.get_cv(cv_id)
    if not cv:
        raise _user_error("CV not found.", 404)
    return storage.get_audit_log(cv_id)
```

Place it near the other `/api/cv/{cv_id}/...` GET routes. Read-only, no
side effects, cannot fail in a way that touches anything else.

### 3.2 "Layout may be hard to parse" banner

No backend change. `GET /api/cv/{cv_id}/quality-report` already returns
`coverage` (see `quality.py`). This is a frontend-only read of an existing
field — see §4.3.

### 3.3 Staff profile screen

No backend change. `GET/PUT/DELETE /api/profiles/{id}`, `GET /api/profiles`,
and `POST /api/cv/{cv_id}/save-profile` already exist and already do
everything the screen needs. See §4.4 for the one real design decision this
feature has to get right.

### 3.4 Configurable auto-approval threshold

`validation.py` currently hardcodes:

```python
AUTO_APPROVE_MIN_CONFIDENCE = 0.75
```

Change to:

```python
AUTO_APPROVE_MIN_CONFIDENCE = 0.75  # fallback default -- unchanged behaviour

def auto_approve_threshold() -> float:
    """The live threshold, or the original hardcoded default if HR has
    never set one. This is the ONLY place the threshold is read from now
    on -- needs_human_review() below calls this instead of the constant
    directly, mirroring the pattern rule_classifier.py already uses for
    HR-taught heading mappings: inert (falls back to prior behaviour)
    until someone explicitly sets a value, and live immediately after."""
    import storage
    raw = storage.get_setting("auto_approve_min_confidence")
    if raw is None:
        return AUTO_APPROVE_MIN_CONFIDENCE
    try:
        return float(raw)
    except ValueError:
        return AUTO_APPROVE_MIN_CONFIDENCE


def needs_human_review(item: dict[str, Any]) -> bool:
    if item.get("confidence", 0.0) < auto_approve_threshold():
        return True
    return bool(set(item.get("validation_flags", [])) - ADVISORY_FLAGS)
```

`import storage` is placed **inside the function**, not at module level.
`validation.py` currently has no dependency on `storage.py` at all, and
several of its functions look like the kind a test would call directly
against fixture data with no database involved. A lazy import keeps that
property true, and the `sqlite3.OperationalError` fallback in
`get_setting()` (§2) means calling this function before `storage.init_db()`
has ever run behaves exactly as it does today.

New endpoints:

```python
# main.py
import validation

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
```

**Do not call `storage.log_event()` from this endpoint.** `audit_log.cv_id`
has a foreign-key reference to `cvs.cv_id` with `PRAGMA foreign_keys = ON`
(see `storage.py`'s `get_conn()`). A settings change isn't associated with
any one CV, so there's no valid `cv_id` to log it under, and inserting a
placeholder like `"system"` would violate that constraint the moment a real
`cvs` row doesn't exist with that id. `app_settings.updated_at` is already
the change record for this — that's sufficient and doesn't need a second,
schema-incompatible logging path invented for it.

**What this does and doesn't affect:** the new threshold applies to every
CV processed *after* the change (`apply_auto_approval()` runs inside
`pipeline.process_cv()`, per upload). It does not retroactively change items
on CVs already sitting in review — exactly the same "forward-looking, not
retroactive" behaviour HANDOVER.md §5g already describes for taught
headings, and worth saying in the UI copy for the same reason.

### 3.5 Cross-CV "frequently unmapped headings" dashboard

New file, `app/backend/insights.py`:

```python
"""Cross-CV, read-only aggregations for the operator-facing dashboard.

Pure functions over data that's already stored. This module never extracts,
classifies, or writes anything -- it only summarizes what unmapped.py
already produced for each CV individually. Nothing here can change what a
single CV's review screen shows or what a generated document contains.
"""
import json
from typing import Any


def summarize_unmapped_headings(
    rows: list[dict[str, Any]],
    taught_headings: set[str],
    limit: int = 30,
) -> list[dict[str, Any]]:
    """rows: [{cv_id, fields}] from storage.list_unmapped_items_with_cv().
    taught_headings: lowercased, stripped heading_text values already
    taught via /api/heading-mappings, so the dashboard doesn't keep
    recommending something HR already fixed.
    """
    by_context: dict[str, dict[str, Any]] = {}
    for row in rows:
        fields = json.loads(row["fields"])
        context = (fields.get("context") or "").strip()
        # "Top of document" is unmapped.py's default context for a line
        # with no heading above it at all -- not a heading anyone could
        # teach, so it has no place on a heading-teaching dashboard.
        if not context or context == "Top of document":
            continue
        entry = by_context.setdefault(context, {
            "context": context,
            "occurrences": 0,
            "cv_ids": set(),
            "example": fields.get("value", ""),
        })
        entry["occurrences"] += 1
        entry["cv_ids"].add(row["cv_id"])

    out = [
        {
            "context": v["context"],
            "occurrences": v["occurrences"],
            "cv_count": len(v["cv_ids"]),
            "example": v["example"],
        }
        for v in by_context.values()
        # Once HR has taught a heading it stops being something to act on:
        # dropped here rather than kept-and-flagged, otherwise a fixed
        # heading would sit at the top of this list (highest cv_count)
        # forever. Existing unmapped items on already-processed CVs are
        # untouched by this -- they still live in those CVs' own review
        # screens; teaching is forward-looking, same as everywhere else.
        if v["context"].casefold() not in taught_headings
    ]
    # Headings seen on the most DIFFERENT CVs first -- that's the signal
    # that teaching it once has the widest payoff, which is the whole
    # point of this dashboard over the existing per-CV teach panel.
    out.sort(key=lambda e: (-e["cv_count"], -e["occurrences"]))
    return out[:limit]
```

```python
# main.py
import insights

@app.get("/api/unmapped-headings-summary")
def unmapped_headings_summary():
    rows = storage.list_unmapped_items_with_cv()
    taught = {m["heading_text"].casefold() for m in storage.list_heading_mappings()}
    return insights.summarize_unmapped_headings(rows, taught)
```

**Known, accepted limitation:** the already-taught filter is an exact
case-folded string match against `custom_heading_mappings.heading_text`.
If HR teaches a heading with slightly different punctuation or spacing
than a later CV's exact wording, the dashboard may show it again even
though the underlying match in `rule_classifier.py` is more forgiving.
That's a display-only imperfection — not a data-integrity issue, and not
worth a more elaborate matcher for a dashboard whose only job is to point
a human at something worth a two-second look.

**Corrected after testing against real data:** the first version of this
function only flagged `already_taught: true` without removing the entry —
contradicting its own docstring, which promised the dashboard wouldn't
keep recommending something already fixed. Caught by actually running it
against a real CV, not by re-reading the code. Fixed to filter as shown
above.

### 3.6 Filename → detected-name confirmation

No backend change. The detected name is already in the `full_name` item
returned by `GET /api/cv/{cv_id}/items`, and the uploaded filename is
already in the `CVRecord` returned by `GET /api/cv/{cv_id}`. This is a
purely client-side, advisory comparison — see §4.5.

---

## 4. Frontend changes

### 4.1 Batch upload (`index.html`)

Current behaviour (`index.html`, lines ~46–76): a single file is picked or
dropped, uploaded, and the page redirects to `review.html` after 900ms.
**That exact behaviour must be preserved unchanged for the single-file
case** — it's the workflow every reviewer already knows.

Changes:

- `<input type="file" id="fileInput" accept=".docx,.pdf" multiple>` — add
  `multiple`.
- The `drop` and `change` handlers currently take `files[0]`; change them to
  pass the full `FileList` to a new `handleUploadBatch(files)`.
- `handleUploadBatch`:
  - If exactly one file: call the existing `handleUpload(file)` unchanged
    (same redirect-to-review behaviour as today).
  - If more than one: upload with a small concurrency cap (3 at a time is
    plenty) rather than firing every request at once — `pipeline.py` says
    outright that CV processing is "kept synchronous for Phase 1," so a
    dozen simultaneous background tasks would compete for the same
    resources it wasn't sized for. A simple queue of promises is enough;
    no need for a library.
  - Do **not** redirect on the multi-file path. Show a one-line summary
    ("Uploaded 12 of 14 files — 2 failed, see below") and let the existing
    auto-refreshing history table (`loadHistory()`, already polling every
    5 seconds) show each one's progress. Each CV still gets its own row
    and its own "Open" link, exactly as today.
  - Collect and display per-file failures (wrong extension, too large,
    empty) inline near the dropzone, reusing the existing `.error-banner`
    styling — one bad file in a batch must not silently drop or block the
    rest.

### 4.2 Activity log panel (`review.html`)

Add a collapsed-by-default panel (reuse the existing `.card` styling,
matching how the source-preview pane already collapses and remembers its
state per HANDOVER.md §3). On expand, call the new
`GET /api/cv/{cv_id}/audit-log` and render one row per entry: timestamp
(`fmtDate`, already in `app.js`), and a human-readable action label.

Add one small shared helper to `app.js`, next to `statusLabel`:

```js
function actionLabel(action) {
  return action.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
}
```

`extraction_started` → "Extraction started", `auto_approval_complete` →
"Auto approval complete", and so on — no lookup table to maintain, and it
degrades gracefully for any future action name `pipeline.py` or `main.py`
starts logging, without this panel needing an update.

### 4.3 "Layout may be hard to parse" banner (`review.html`)

Inside the existing `renderQuality(report, cvStatus)` function: if
`report.coverage < 0.6` **and** `report.unmapped_count > 5` (both
conditions — coverage alone can look low on a short, simple CV that just
doesn't have much content, which isn't a parsing problem), render a banner
above the quality summary:

> This CV's layout was hard to parse — expect more manual review than
> usual. {unmapped_count} items are in Unmapped Information below.

Both thresholds are constants declared once at the top of the script block,
not buried inline, so they're easy to tune later without hunting through
the render function. This is advisory only — it changes no data and blocks
nothing.

### 4.4 Staff profile screen (`profiles.html`, new file)

Follow `index.html`'s structure exactly: same `<header class="topbar">`,
same `styles.css`, same `app.js` include. Add the nav link to all three
pages:

```html
<nav>
  <a href="index.html">Upload &amp; History</a>
  <a href="profiles.html">Staff Profiles</a>
</nav>
```

List view: `GET /api/profiles`, one row per profile (name, job title,
email, last updated), Edit and Delete actions — same table styling as the
upload-history table on `index.html`.

Edit form fields, matching exactly what `PUT /api/profiles/{id}` accepts
(`main.py` lines ~406–421): full name, job title, MDX email, desk phone,
then the six link fields `profiles.py`'s `LINK_LABELS` already knows how to
label (ORCID, LinkedIn, Scopus, Google Scholar, Research Repository,
Website), then a repeatable list of membership lines (add/remove row).

**The one real design decision here, and the one to get right:**
`profiles.profile_id_for()` derives a profile's id by slugifying its
*name* — lowercased, honorific stripped, non-alphanumerics collapsed to
hyphens. Matching a future CV to a saved profile
(`profiles.find_profile_for_items()`) works by re-deriving that same slug
from the name found on the new CV and looking it up. But `PUT
/api/profiles/{profile_id}` writes to whatever `profile_id` is in the URL
— it does **not** recompute the id from a changed `full_name` in the
payload. So editing a profile's name in place, without also changing its
id, silently breaks future matching: the profile keeps living at its old
id, but a CV with the new name will never find it.

For this build, the correct and simplest fix is to **not allow editing the
name of an existing profile** — show it read-only on the edit screen, with
a short note ("to rename, delete this profile and create a new one"). Name
is only editable when creating a brand-new profile, where the id is
freshly derived client-side (mirror `profile_id_for()`'s logic in JS: strip
a leading honorific, lowercase, collapse non-alphanumerics to hyphens) and
sent as the `PUT` target. This avoids a whole class of silent-mismatch bugs
for the cost of one disabled input — worth it, and reversible later if a
proper rename-with-migration flow ever turns out to be worth building.

No backend changes are needed for this feature at all.

### 4.5 Filename → detected-name confirmation (`review.html`)

Purely client-side, in the same place `loadAll()` already has the CV record
and its items loaded. Compare the `full_name` item's value against
`cv.original_filename`: strip the extension, split both into lowercase word
tokens, and check whether most of the name's tokens appear somewhere in the
filename. If not, show a small, dismissible notice (not a blocking banner —
this is a hint, not a validation failure):

> Detected name: **{name}** — this doesn't obviously match the uploaded
> filename ({filename}). Worth a quick check against the Full Name item
> below.

This is intentionally loose (substring/token matching, not exact), because
the goal is catching the `CV_final_v2.docx` case HANDOVER.md §7 already
names, not flagging every reasonable filename variation. Nothing about
this notice affects processing, confidence, or approval status.

---

## 5. Build order

Each item is independent of the others — there's no dependency chain
forcing a specific order — but this sequencing keeps every step small and
separately verifiable, which matters more here than speed:

1. **`insights.py` + the `audit-log` endpoint** (§3.1, §3.5's backend half)
   — pure additions, zero UI yet, easiest to unit-test in isolation before
   anything depends on them.
2. **`app_settings` table + auto-approval endpoints** (§2, §3.4) — same
   reasoning; verify the fallback behaviour (§2's `OperationalError` catch,
   §3.4's "no setting written yet" path) before building UI on top of it.
3. **Activity log panel + hard-to-parse banner** (§4.2, §4.3) — smallest
   frontend changes, both read-only, both on `review.html`.
4. **Batch upload** (§4.1) — touches the upload flow directly; do this once
   everything above is stable so a regression is easy to attribute.
5. **Staff profile screen** (§4.4) — the biggest single frontend piece;
   build last so the shared patterns (nav, table styling, form layout) are
   already settled from the smaller pages.
6. **Frequently-unmapped-headings dashboard UI** (§4, using §3.5's
   endpoint) and **filename confirmation** (§4.5) — smallest remaining
   pieces, can go in either order, either can slot in earlier if convenient.

---

## 6. Verification checklist

Run after **every** numbered item above, not just at the end:

- [ ] `cd app/backend && python test_corpus.py` — same pass count, same two
      pre-existing failures, as the pre-build baseline.
- [ ] Upload one CV the normal way (single file, no batch): confirm it
      still redirects to `review.html` after upload, exactly as before.
- [ ] Full existing loop once, end to end, on one real CV: upload → review
      → approve/reject a few items → generate → download. Confirm the
      downloaded document is unchanged in content from what the same CV
      produced before this build started.

Per-feature checks:

- [ ] **Batch upload:** drop 3+ files at once (mix of valid and one
      intentionally-invalid file, e.g. a `.txt`). Confirm all valid ones
      appear in the history table and process independently; confirm the
      invalid one is reported without blocking the others.
- [ ] **Activity log:** open a freshly-processed CV's review screen, expand
      the log, confirm entries appear in the same order `pipeline.py` logs
      them (extraction → classification → auto-approval → …).
- [ ] **Hard-to-parse banner:** find or reconstruct a low-coverage CV (a
      two-column PDF from the corpus is the known example in `FIXLOG.md`'s
      2026-08-26 entry); confirm the banner shows. Confirm it does **not**
      show on a clean, high-coverage CV.
- [ ] **Profile screen:** create a profile, re-upload a CV with a matching
      name, confirm prefill still happens exactly as it does today
      (HANDOVER.md §4's Camilla example is a good one to replay). Attempt
      to edit an existing profile's name field and confirm it's read-only.
- [ ] **Auto-approval setting:** raise the threshold well above the
      default, upload a CV, confirm more items sit pending than the same
      CV produced at the default. Then confirm a *previously* uploaded
      CV's already-decided items are unaffected — the setting must not be
      retroactive.
- [ ] **Unmapped-headings dashboard:** upload two CVs that share an
      unrecognized heading; confirm it appears with `cv_count: 2`. Teach
      it; confirm it drops off the list on the next load.
- [ ] **Name confirmation notice:** upload a CV with an obviously-mismatched
      filename (e.g. `CV_final_v2.docx`); confirm the notice appears.
      Upload one named after the person; confirm it doesn't.

---

## 7. Explicitly out of scope for this build

- **Authentication and per-reviewer accounts.** The largest item from the
  recommendations doc, and a genuinely separate project — no auth library
  exists in `requirements.txt` today, and doing it well (not just a shared
  password) means a real user model, which touches how the audit log
  attributes actions. Worth scoping on its own once this tool moves from
  pilot to standard practice, not folded into a build whose whole premise
  is *not* increasing surface area.
- **Another attempt at multi-column PDF reading order.** Two structurally
  different approaches already failed on real files (`FIXLOG.md`,
  2026-08-26 entry) — the hard-to-parse banner in this build (§4.3) is the
  deliberate alternative: surface the hard cases rather than chase a third
  fix without new evidence one would work.
- **OCR.** Still out of scope per HANDOVER.md §7, unless scanned CVs turn
  out to be common in practice — not assumed here.
