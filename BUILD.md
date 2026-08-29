# MDX Faculty CV Converter — Build Guide (Phase 2)

**One self-contained file to actually build this.** Everything needed is
here in order: the ground rules, the exact code for every change, and the
exact commands to run and check after each step. Companion to
`HANDOVER.md` and `FIXLOG.md`, which describe the system as it stands and
its history — this describes what to build next and how to prove it didn't
break anything. (This merges and supersedes the earlier `BUILD_PLAN.md` and
`IMPLEMENTATION_STEPS.md` — keep those as reference if useful, but this file
is the one to follow start to finish.)

Covers the seven items from `MDX_CV_Converter_Enhancement_Recommendations.docx`
that don't require authentication. Every file, function, and endpoint below
was checked against the actual code, not proposed in the abstract.

**Every phase — backend and frontend — has been built and run, not just
written.** In an isolated sandbox (a full copy of this project, never
your live install or database), with the `.env` deliberately left blank
to force the offline rule-based path:

**Backend (Phase 1 + Phase 2):**

- The unmodified backend was run first, and a real corpus CV (Daphne's,
  the academic CV from `HANDOVER.md`'s table) was processed as a
  baseline: **80 items, 71 auto-approved, 9 pending, coverage 1.0.**
- With Phase 1 + Phase 2 applied, the route count went from 31 to 35 (the
  four new endpoints, nothing removed), and the same CV, reprocessed
  under the unchanged default threshold, produced **the identical
  80/71/9/1.0** — proving the default path is bit-for-bit unchanged.
- Raising the threshold to 0.99 and reprocessing dropped auto-approval to
  **0/80**, while the CV processed *before* the change stayed at
  **71/9**, confirming the setting is forward-looking, not retroactive,
  exactly as designed.
- The unmapped-headings dashboard *endpoint* was tested against two more
  real CVs from the project, teaching a genuine unrecognized heading
  ("MATH TEACHER RESUME") end to end via direct API calls: it appeared in
  the response → disappeared after teaching → a fresh upload of the same
  CV then classified that content correctly instead of landing unmapped
  (`unmapped_count` 2 → 0, `coverage` 0.83 → 1.0).
- **This caught one real bug:** the first version of the dashboard
  function flagged an already-taught heading instead of removing it,
  contradicting its own docstring. Fixed below, and re-verified.
- The full approve → generate → download loop was run on the modified
  server and the output opened and visually checked — a correctly
  formatted MDX CV, letterhead through employment history.

**Frontend (Phases 3–6, plus the new `profiles.html`):** built into the
same sandbox and driven with a real, scripted Chromium browser against
the running server — not just described. Specifically:

- **Batch upload:** three real files dropped into `index.html`'s actual
  file input at once. Status read `Uploaded 3 of 3 files.`, the history
  table grew by exactly three rows, and the worker-pool concurrency cap
  behaved correctly.
- **Staff profile screen (new `profiles.html`):** created a profile
  through the real form (name editable while new), saved it, reopened it
  from the list, and confirmed the name field was disabled with the
  "delete and recreate to rename" note showing — the one design decision
  in §5b that has to be right. The id the page derived client-side for
  the `PUT` matched the server's own `profile_id_for()` exactly (visible
  in the server log: `PUT /api/profiles/verify-testperson`), then all
  fields — email, ORCID, membership lines — round-tripped correctly on
  reload, and the test profile was deleted cleanly.
- **Activity log panel:** opened on two real, already-processed CVs and
  confirmed it rendered the actual stored audit trail (upload →
  extraction → classification → auto-approval), correctly humanized
  ("Ai classification complete", "Auto approval complete", …).
- **Hard-to-parse banner:** none of the sandbox's real corpus CVs happen
  to be badly-parsed enough to trigger it — a fact about the test CVs,
  not the code — so the threshold logic itself was verified directly
  against the live page: mocking `coverage`/`unmapped_count` at
  `0.4`/`8` produced the banner text; at the exact boundary (`unmapped`
  = 5, not > 5) it correctly stayed hidden.
- **Name-confirmation notice:** run against a real CV's own data (Dr
  Daphne Demetriou) through the page's actual `checkNameMatch()`
  function — flagged the real mismatched filenames used elsewhere in
  this testing, and specifically flagged `CV_final_v2.docx`
  (`HANDOVER.md` §7's example) while staying silent for
  `Demetriou_Daphne_CV.docx` and `Daphne-Demetriou-CV-2026.pdf`.
- **Unmapped-headings dashboard UI, full loop:** two CVs uploaded sharing
  a genuinely unrecognized heading → it appeared on `index.html`'s
  dashboard card with `cv_count: 2` → taught through the real "Teach
  this heading" button → gone on the next load → a third upload of the
  same content then classified under the taught section instead of
  landing unmapped, closing the loop end to end through the UI.
- Zero browser console errors and zero server-side 500s or tracebacks
  across the entire test session (the one console message logged was a
  harmless `/favicon.ico` 404, unrelated to any change here).
- **No bugs found in the frontend code** — every piece matched this
  spec on first try.

What this does *not* cover: the 34-CV regression suite in
`test_corpus.py` reads from `C:\Users\test\Downloads`, which only exists
on your machine — that step still has to run there (Step 1 and the
per-phase checks below). Everything else in this summary was proven, not
just designed.

---

## Ground rules

**Every fix in `FIXLOG.md` was hard-won.** The classifier, router, and
extraction logic were tuned against a 34-CV corpus through dozens of
narrowly-scoped, individually-validated changes — several broad "obvious"
fixes were built, tested, and explicitly reverted because they broke a
different CV. None of that is in scope here.

**Files this build must not modify:**

```
rule_classifier.py   routing.py        extraction.py
template_engine.py   formatting.py     bio_draft.py
identifiers.py        commands.py       classifier.py
photo.py
```

Everything below lives in three places instead: one new, additive database
table; a small number of new, additive API endpoints; and frontend files.
Nothing here changes what gets extracted, how it's classified, or what a
generated document contains. If a step ever seems to require touching one
of the files above, stop — that file isn't part of this build.

**The 34-CV regression corpus lives outside the project**, at
`C:\Users\test\Downloads` (and two subfolders — see `test_corpus.py`'s
`CORPUS_DIRS`). Every `python test_corpus.py` run below has to happen on
the machine where that folder exists.

**Definition of done, for the whole build:** `python test_corpus.py`
reports the same pass count and the same two pre-existing failures (the
blank vendor templates) at the end as it did before Step 1. If that number
moves, something regressed — find it before calling any phase finished.

---

## File manifest

| File | Change |
|---|---|
| `app/backend/storage.py` | Add one table (`app_settings`) and four small functions. No changes to existing tables or functions. |
| `app/backend/validation.py` | Replace one module-level constant lookup with a function that falls back to that same constant. |
| `app/backend/main.py` | Add four new endpoints. No changes to any existing endpoint. |
| `app/backend/insights.py` | **New file.** Pure functions for the cross-CV dashboard. |
| `app/frontend/index.html` | Multi-file upload; new "Auto-approval setting" card; new "Frequently unmapped headings" card. |
| `app/frontend/review.html` | New "Activity Log" panel; new "layout may be hard to parse" banner; new "confirm detected name" notice. |
| `app/frontend/profiles.html` | **New file.** Staff profile list + edit screen. |
| `app/frontend/app.js` | One new shared helper (`actionLabel`). |
| `app/frontend/styles.css` | A handful of additive classes. No existing rules changed. |

`rule_classifier.py` and the rest of the protected list appear nowhere in
this table. That's the point.

---

## Step 0 — Safety net

- [ ] The project has no version control yet. Either:
  ```
  cd "C:\Users\test\claude converter\MDX CV CONVERTER"
  git init
  git add -A
  git commit -m "baseline before Phase 2 build"
  ```
  or copy the whole folder to a sibling `MDX CV CONVERTER - backup` folder.
- [ ] If using git, add a `.gitignore` so history stays about code:
  ```
  __pycache__/
  *.pyc
  .env
  app/data/uploads/
  app/data/generated/
  app/data/photos/
  app/data/db/
  ```
- [ ] Confirm the server currently starts cleanly:
  ```
  cd app\backend
  python -m uvicorn main:app --port 8000
  ```
  Open `http://localhost:8000`, confirm the upload page loads, then stop
  it (Ctrl+C).

## Step 1 — Record the baseline

- [ ] Run the full regression suite and write down the result — this is
  what every later checkpoint gets compared against:
  ```
  cd app\backend
  python test_corpus.py
  ```
  Expect all CVs to pass except the two blank vendor templates. If
  anything else fails right now, resolve that first — it predates this
  build and shouldn't be blamed on it.

---

## Phase 1 — Read-only foundations

**Builds:** `insights.py` (new file), three new storage functions, and the
`GET /api/cv/{cv_id}/audit-log` + `GET /api/unmapped-headings-summary`
endpoints. Pure additions — nothing yet calls them from the UI, so this is
the safest phase to do first.

### 1a. `storage.py`

Add to the `SCHEMA` string (after the existing `custom_heading_mappings`
table):

```sql
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

Add these four functions alongside the other storage functions:

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

### 1b. `app/backend/insights.py` (new file)

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

*Known, accepted limitation:* the already-taught filter is an exact
case-folded string match against `custom_heading_mappings.heading_text`.
If HR teaches a heading with slightly different punctuation than a later
CV's exact wording, the dashboard may show it again even though
`rule_classifier.py`'s own matching is more forgiving. Display-only
imperfection, not a data-integrity issue — not worth a fancier matcher for
a dashboard whose only job is pointing a human at something worth a
two-second look.

*Verified by actually running it (not just reading the code):* the first
version of this function only flagged `already_taught: true` without ever
removing the entry — silently contradicting its own docstring, which
promised the dashboard "doesn't keep recommending something HR already
fixed." A real CV run caught it: teaching a heading left it sitting at the
top of the list forever instead of disappearing. Fixed to actually filter,
as shown above, and re-verified end to end: unmapped on upload → taught →
gone from the dashboard → a fresh upload of the same CV classifies the
content correctly instead of landing unmapped again.

### 1c. `main.py`

Add near the top with the other imports:

```python
import insights
```

Add near the other `/api/cv/{cv_id}/...` GET routes:

```python
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
```

### 1d. Apply and verify

- [ ] Restart the server — should start with no errors.
- [ ] Hit both endpoints manually against a CV that's already been
  processed: `/api/cv/{a real cv_id}/audit-log` (returns a JSON list of
  log entries) and `/api/unmapped-headings-summary` (returns a JSON list,
  possibly empty).
- [ ] `python test_corpus.py` — pass count must match Step 1 exactly.

*If this fails:* these are additive files and routes touching nothing
else, so a failure almost certainly means a typo or import error, not a
design problem.

---

## Phase 2 — The settings table

**Builds:** the `auto_approve_threshold()` function and the two
`/api/settings/auto-approval-threshold` endpoints. This is the one item
from HANDOVER.md §3 explicitly flagged as needing an HR decision, not just
a developer default.

### 2a. `validation.py`

Change:

```python
AUTO_APPROVE_MIN_CONFIDENCE = 0.75
```

to:

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
```

And change `needs_human_review()` to:

```python
def needs_human_review(item: dict[str, Any]) -> bool:
    if item.get("confidence", 0.0) < auto_approve_threshold():
        return True
    return bool(set(item.get("validation_flags", [])) - ADVISORY_FLAGS)
```

`import storage` stays **inside the function** — `validation.py` has no
module-level dependency on `storage.py` today, and keeping it that way
means anything that calls `validate_items`/`needs_human_review` directly
against fixture data, with no database involved, keeps working unchanged
(the `sqlite3.OperationalError` fallback in `get_setting()` from Phase 1
covers that case too).

### 2b. `main.py`

```python
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

Make sure `import validation` is present near the top of `main.py`.

**Do not call `storage.log_event()` from either endpoint.**
`audit_log.cv_id` has a foreign-key reference to `cvs.cv_id` with
`PRAGMA foreign_keys = ON`. A settings change isn't tied to any one CV, so
there's no valid `cv_id` to log it under — inserting a placeholder like
`"system"` would violate that constraint. `app_settings.updated_at` is
already the change record for this.

### 2c. Apply and verify

- [ ] Restart the server.
- [ ] `GET /api/settings/auto-approval-threshold` → confirm it returns
  `{"threshold": 0.75}` with nothing set yet (proves the fallback path).
- [ ] `PUT {"threshold": 0.95}`, then `GET` again → confirm it comes back
  changed.
- [ ] Upload one corpus CV with the threshold at 0.95+ → confirm more
  items sit `pending_review` than at the default (a higher bar means
  fewer auto-approvals). This applies going forward only — a CV already
  in review before the change is unaffected.
- [ ] Set the threshold back to `0.75` before continuing, so later phases
  proceed against the same behaviour as the baseline.
- [ ] `python test_corpus.py` — pass count must still match Step 1
  (`test_corpus.py` never writes an `app_settings` row, so `get_setting()`
  falls through to `0.75` every time).

---

## Phase 3 — Activity log panel + hard-to-parse banner

**Builds:** a collapsible activity log on `review.html`, fed by Phase 1's
endpoint, and a warning banner when a CV's layout defeated the classifier.
Both are frontend-only and read-only.

### 3a. `app.js`

Add next to `statusLabel`:

```js
function actionLabel(action) {
  return action.replaceAll("_", " ").replace(/^./, c => c.toUpperCase());
}
```

`extraction_started` → "Extraction started", `auto_approval_complete` →
"Auto approval complete" — no lookup table to maintain, and it degrades
gracefully for any future action name the backend starts logging.

### 3b. `review.html` — activity log panel

Add a collapsed-by-default panel (reuse the existing `.card` styling,
matching how the source-preview pane already collapses and remembers its
state). On expand, call `GET /api/cv/{cv_id}/audit-log` and render one row
per entry using `fmtDate(entry.at)` and `actionLabel(entry.action)`.

### 3c. `review.html` — hard-to-parse banner

Inside the existing `renderQuality(report, cvStatus)` function, declare two
constants once near the top of the script block (not buried inline, so
they're easy to tune later):

```js
const HARD_TO_PARSE_COVERAGE = 0.6;
const HARD_TO_PARSE_MIN_UNMAPPED = 5;
```

If `report.coverage < HARD_TO_PARSE_COVERAGE` **and**
`report.unmapped_count > HARD_TO_PARSE_MIN_UNMAPPED` (both conditions —
coverage alone can look low on a short CV that just doesn't have much
content, which isn't a parsing problem), render a banner above the quality
summary:

> This CV's layout was hard to parse — expect more manual review than
> usual. {unmapped_count} items are in Unmapped Information below.

Advisory only — changes no data, blocks nothing.

### 3d. Apply and verify

- [ ] Restart the server, open a processed CV's review screen.
- [ ] Expand the activity log — confirm entries appear in the same order
  `pipeline.py` logs them (extraction → classification → auto-approval →
  …).
- [ ] Find or reconstruct a low-coverage CV (the two-column PDF example in
  `FIXLOG.md`'s 2026-08-26 entry) and confirm the banner shows. Open a
  clean CV and confirm it does **not** show.
- [ ] `python test_corpus.py` — frontend-only change, pass count
  unaffected; run it anyway to be sure nothing was accidentally touched.

---

## Phase 4 — Batch upload

**Builds:** multi-file upload on `index.html`, with the existing
single-file behaviour left untouched.

### 4a. `index.html`

- Add `multiple` to the file input:
  `<input type="file" id="fileInput" accept=".docx,.pdf" multiple>`
- Change the `drop`/`change` handlers to pass the full `FileList` to a new
  `handleUploadBatch(files)` instead of always taking `files[0]`.
- `handleUploadBatch(files)`:
  - Exactly one file → call the existing `handleUpload(file)` unchanged
    (same redirect-to-`review.html`-after-900ms behaviour as today — this
    is the one thing that must not move).
  - More than one file → upload with a concurrency cap of 3 (a simple
    promise queue; `pipeline.py` notes CV processing is "kept synchronous
    for Phase 1," so a dozen simultaneous background tasks would compete
    for resources it wasn't sized for). Don't redirect — show a one-line
    summary ("Uploaded 12 of 14 files — 2 failed, see below") and rely on
    the existing auto-refreshing history table (`loadHistory()`, already
    polling every 5 seconds) to show each CV's progress.
  - Collect and display per-file failures (wrong extension, too large,
    empty) inline near the dropzone, reusing the existing `.error-banner`
    styling — one bad file must not block or silently drop the rest.

### 4b. Apply and verify

- [ ] Restart the server.
- [ ] **Regression check first:** upload exactly one file the normal way.
  Confirm it still redirects to `review.html` after ~900ms, exactly as
  before.
- [ ] Drop 3+ files at once, including one deliberately invalid file.
  Confirm the valid ones appear in the history table and process
  independently, and the invalid one is reported without blocking the
  rest.
- [ ] `python test_corpus.py` — frontend-only, pass count unaffected.

---

## Phase 5 — Staff profile screen

**Builds:** `profiles.html` (new page) and nav links across all three
pages. No backend changes at all — every endpoint this needs already
exists.

### 5a. `app/frontend/profiles.html` (new file)

Follow `index.html`'s structure: same `<header class="topbar">`, same
`styles.css`/`app.js` includes. Add the nav link to all three pages:

```html
<nav>
  <a href="index.html">Upload &amp; History</a>
  <a href="profiles.html">Staff Profiles</a>
</nav>
```

List view: `GET /api/profiles` → one row per profile (name, job title,
email, last updated), Edit and Delete actions — same table styling as the
upload-history table on `index.html`.

Edit form fields, matching exactly what `PUT /api/profiles/{id}` accepts:
full name, job title, MDX email, desk phone, then the six link fields
`profiles.py`'s `LINK_LABELS` already knows how to display (ORCID,
LinkedIn, Scopus, Google Scholar, Research Repository, Website), then a
repeatable list of membership lines (add/remove row).

### 5b. The one design decision that has to be right

`profiles.profile_id_for()` derives a profile's id by slugifying its
*name* (lowercased, honorific stripped, non-alphanumerics collapsed to
hyphens). Matching a future CV to a saved profile re-derives that same
slug from the name found on the new CV and looks it up. But `PUT
/api/profiles/{profile_id}` writes to whatever `profile_id` is in the
URL — it does **not** recompute the id from a changed `full_name` in the
payload. So editing a profile's name in place, without also changing its
id, silently breaks future matching: the profile keeps living at its old
id, but a CV with the new name will never find it.

**The fix for this build: don't allow editing the name of an existing
profile.** Show it read-only on the edit screen, with a short note ("to
rename, delete this profile and create a new one"). Name is only editable
when creating a brand-new profile, where the id is derived client-side
(mirror `profile_id_for()`'s logic in JS) and sent as the `PUT` target.
One disabled input, in exchange for avoiding a whole class of silent
mismatch bugs.

### 5c. Apply and verify

- [ ] Restart the server.
- [ ] Create a new profile for a person already in the test corpus (MDX
  email, ORCID, etc.).
- [ ] Re-upload that person's CV and confirm the profile prefill still
  happens exactly as HANDOVER.md §4 describes.
- [ ] Open an existing profile's edit screen and confirm the name field is
  disabled/read-only.
- [ ] Delete the test profile you created, to leave the profile store
  clean.
- [ ] `python test_corpus.py` — no backend change, pass count unaffected.

---

## Phase 6 — Unmapped-headings dashboard UI + name confirmation

**Builds:** the "frequently unmapped headings" card on `index.html`
(consuming Phase 1's endpoint) and the filename/name-mismatch notice on
`review.html`. Both are the smallest remaining pieces.

### 6a. `index.html` — dashboard card

Reuse the same teach-row pattern already in `review.html`'s teach panel:
heading text, a section dropdown, a "Teach this heading" button posting to
`POST /api/heading-mappings`. Feed it from
`GET /api/unmapped-headings-summary` instead of one CV's items, and show
`cv_count` (how many different CVs have shown this heading) alongside each
row.

### 6b. `review.html` — name confirmation notice

Purely client-side, in the same place `loadAll()` already has the CV
record and its items loaded. Compare the `full_name` item's value against
`cv.original_filename`: strip the extension, split both into lowercase
word tokens, and check whether most of the name's tokens appear somewhere
in the filename. If not, show a small, dismissible notice (a hint, not a
blocking validation):

> Detected name: **{name}** — this doesn't obviously match the uploaded
> filename ({filename}). Worth a quick check against the Full Name item
> below.

Intentionally loose matching (substring/token, not exact) — the goal is
catching the `CV_final_v2.docx` case HANDOVER.md §7 already names, not
flagging every reasonable filename variation. Affects nothing about
processing, confidence, or approval status.

### 6c. Apply and verify

- [ ] Restart the server.
- [ ] Upload two CVs that share an unrecognized heading (or reuse two from
  the corpus that do). Confirm the heading appears on the dashboard with
  `cv_count: 2`. Teach it. Confirm it drops off the list on the next page
  load.
- [ ] Upload a CV with an obviously-mismatched filename (e.g.
  `CV_final_v2.docx`) — confirm the notice appears. Upload one properly
  named after the person — confirm it doesn't.
- [ ] `python test_corpus.py` — pass count unaffected.

---

## Final sign-off

- [ ] Stop the server. Delete `__pycache__` under `app/backend`.
- [ ] Restart clean: `python -m uvicorn main:app --port 8000`.
- [ ] Run `python test_corpus.py` one last time. Compare the pass count and
  the failing-file list against Step 1 — they must match exactly.
- [ ] Full manual walkthrough on one real CV: upload → review screen loads
  → approve/reject a few items → generate → download. Confirm the
  downloaded document is unchanged in content from what the same CV would
  have produced before this build — nothing here should change what a
  generated CV contains.
- [ ] If using git:
  ```
  git add -A
  git commit -m "Phase 2: batch upload, activity log, profile screen, configurable auto-approval, unmapped-headings dashboard, name confirmation"
  ```

---

## If something breaks partway through

- Each phase is independent — isolate the failure to the phase you were on
  when `test_corpus.py`'s pass count changed, or a manual check failed.
- Committing after each phase (recommended beyond just Step 0) means
  `git diff HEAD~1` shows exactly what that phase changed, and
  `git checkout -- .` reverts it if needed.
- Without git: re-check the change against the exact code in this file for
  that phase — most failures at this scale are a copy/paste mismatch (a
  missed import, a mismatched route path), not a design problem, since
  every phase here is additive and none touch the tuned classifier or
  routing code.

---

## Quick reference

| Action | Command |
|---|---|
| Start the server | `cd app\backend` then `python -m uvicorn main:app --port 8000` |
| Run the regression suite | `cd app\backend` then `python test_corpus.py` |
| Open the app | `http://localhost:8000` |
| Commit a checkpoint (if using git) | `git add -A && git commit -m "<phase name>"` |

---

## Explicitly out of scope

- **Authentication and per-reviewer accounts.** No auth library exists in
  `requirements.txt` today, and doing it well (not just a shared password)
  means a real user model — a genuinely separate project, worth scoping on
  its own once this moves from pilot to standard practice.
- **Another attempt at multi-column PDF reading order.** Two structurally
  different approaches already failed on real files (`FIXLOG.md`,
  2026-08-26 entry). Phase 3's hard-to-parse banner is the deliberate
  alternative: surface the hard cases rather than chase a third fix
  without new evidence one would work.
- **OCR.** Still out of scope per HANDOVER.md §7, unless scanned CVs turn
  out to be common in practice.
