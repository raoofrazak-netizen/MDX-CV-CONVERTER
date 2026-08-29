# Implementation Steps — Portal Enhancements (Phase 2)

A checklist for actually executing `BUILD_PLAN.md`. That file has the exact
code, endpoints, and file changes; this file is the **order of operations**
— what to do, in what sequence, and what to check before moving to the
next thing. Work through it top to bottom. Don't skip the checkpoints —
they're what makes this safe to do incrementally instead of all at once.

Two things this checklist assumes, both explained in `BUILD_PLAN.md`:

- **Nothing here touches** `rule_classifier.py`, `routing.py`,
  `extraction.py`, `template_engine.py`, `formatting.py`, `bio_draft.py`,
  `identifiers.py`, `commands.py`, `classifier.py`, or `photo.py`. If a step
  ever seems to require editing one of those, stop — that file isn't in
  this build.
- **The 34-CV regression corpus lives outside the project**, at
  `C:\Users\test\Downloads` (see `test_corpus.py`'s `CORPUS_DIRS`). Every
  verification step below that runs `test_corpus.py` has to run on the
  machine where that folder exists — it can't be checked any other way.

---

## Step 0 — Safety net

Do this before changing a single file.

- [ ] The project has no version control yet. Either:
  - `cd` into `MDX CV CONVERTER` and run:
    ```
    git init
    git add -A
    git commit -m "baseline before Phase 2 build"
    ```
  - or copy the whole `MDX CV CONVERTER` folder to a sibling
    `MDX CV CONVERTER - backup` folder.
- [ ] If using git, add a `.gitignore` so the commit history stays about
  code, not uploaded CVs and generated documents:
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
  cd "C:\Users\test\claude converter\MDX CV CONVERTER\app\backend"
  python -m uvicorn main:app --port 8000
  ```
  Open `http://localhost:8000`, confirm the upload page loads. Stop the
  server (Ctrl+C) once confirmed.

---

## Step 1 — Record the baseline

This is the number every later checkpoint gets compared against — capture
it before any code changes exist.

- [ ] Run the full regression suite:
  ```
  cd app\backend
  python test_corpus.py
  ```
- [ ] Write down: total pass count, and which files fail (should be
  exactly the two blank vendor templates — nothing else). If anything
  else fails right now, stop and resolve that first; it's a pre-existing
  problem, not something this build should inherit blame for.

---

## Step 2 — Phase 1: read-only foundations

**Builds:** `insights.py` (new file) and the `GET /api/cv/{cv_id}/audit-log`
endpoint. See `BUILD_PLAN.md` §3.1 and §3.5 for the exact code.

- [ ] Create `app/backend/insights.py` with the `summarize_unmapped_headings`
  function (§3.5).
- [ ] Add `list_unmapped_items_with_cv()` and `get_audit_log()` to
  `storage.py` (§2).
- [ ] Add the `audit-log` GET route and the `unmapped-headings-summary` GET
  route to `main.py` (§3.1, §3.5). Import `insights` at the top of
  `main.py`.
- [ ] Restart the server. It should start with no errors — these are pure
  additions with nothing yet calling them from the UI.
- [ ] Manually hit both new endpoints in a browser (or `curl`) against a CV
  that's already been processed:
  - `http://localhost:8000/api/cv/{a real cv_id}/audit-log` — should
    return a JSON list of log entries.
  - `http://localhost:8000/api/unmapped-headings-summary` — should return
    a JSON list (possibly empty if no CV has unmapped content yet).
- [ ] Run `python test_corpus.py` — pass count must match Step 1 exactly.

**If this step fails:** these are additive files and routes touching
nothing else, so a failure here almost certainly means a typo or import
error, not a design problem. Fix and re-run before moving on.

---

## Step 3 — Phase 2: the settings table

**Builds:** the `app_settings` table, `get_setting`/`set_setting` in
`storage.py`, `auto_approve_threshold()` in `validation.py`, and the two
`/api/settings/auto-approval-threshold` endpoints. See `BUILD_PLAN.md` §2
and §3.4.

- [ ] Add the `app_settings` `CREATE TABLE IF NOT EXISTS` to the `SCHEMA`
  string in `storage.py`, and the `get_setting`/`set_setting` functions.
- [ ] In `validation.py`, add `auto_approve_threshold()` and change
  `needs_human_review()` to call it instead of referencing
  `AUTO_APPROVE_MIN_CONFIDENCE` directly. Keep the constant itself as the
  fallback default — don't delete it.
- [ ] Add the two new endpoints to `main.py`. Double-check: **no**
  `storage.log_event()` call in the `PUT` endpoint (§3.4 explains why —
  the foreign-key constraint on `audit_log.cv_id`).
- [ ] Restart the server.
- [ ] Confirm `GET /api/settings/auto-approval-threshold` returns
  `{"threshold": 0.75}` with nothing set yet — this proves the fallback
  path works.
- [ ] `PUT` a new value (e.g. `{"threshold": 0.95}`), then `GET` again and
  confirm it comes back changed.
- [ ] Upload one CV from the corpus while the threshold is set high (0.95+)
  and confirm more of its items sit in `pending_review` than they did
  before this change (a higher bar means fewer auto-approvals).
- [ ] Set the threshold back to `0.75` before continuing, so the rest of
  this build proceeds against the same behaviour as the baseline.
- [ ] Run `python test_corpus.py` — pass count must still match Step 1.
  (It should: `test_corpus.py` never calls `storage.init_db()` with a
  pre-existing `app_settings` row, so `get_setting()` falls through to the
  same `0.75` default every time.)

---

## Step 4 — Phase 3: activity log panel + hard-to-parse banner

**Builds:** the collapsible activity log panel and the low-coverage
warning banner, both on `review.html`. See `BUILD_PLAN.md` §4.2 and §4.3.

- [ ] Add the `actionLabel()` helper to `app.js` (§4.2).
- [ ] Add the activity log panel to `review.html`, wired to the
  `audit-log` endpoint from Step 2.
- [ ] Add the coverage check inside `renderQuality()` in `review.html`
  (§4.3) — the two threshold constants (`0.6` coverage, `5` unmapped
  items) declared once near the top of the script, not inline.
- [ ] Restart the server, open a processed CV's review screen.
- [ ] Expand the activity log — confirm entries appear in the same order
  `pipeline.py` logs them (extraction → classification → auto-approval →
  …).
- [ ] Find or reconstruct a low-coverage CV (the two-column PDF example in
  `FIXLOG.md`'s 2026-08-26 entry is a known case) and confirm the banner
  shows. Open a clean, well-structured CV and confirm it does **not**
  show.
- [ ] Run `python test_corpus.py` — this step touches no backend logic, so
  the pass count should be unaffected, but run it anyway to be sure
  nothing was accidentally touched.

---

## Step 5 — Phase 4: batch upload

**Builds:** multi-file upload on `index.html`, with the single-file path
left exactly as it is today. See `BUILD_PLAN.md` §4.1.

- [ ] Add the `multiple` attribute to the file input.
- [ ] Change the `drop`/`change` handlers to call a new
  `handleUploadBatch(files)` instead of always taking `files[0]`.
- [ ] Implement `handleUploadBatch`: single file → call the existing
  `handleUpload()` unchanged; multiple files → upload with a concurrency
  cap of 3, no redirect, inline summary of successes/failures.
- [ ] Restart the server.
- [ ] **Regression check first:** upload exactly one file the normal way.
  Confirm it still redirects to `review.html` after ~900ms, exactly as
  before this change. This is the one behaviour that must not move.
- [ ] Drop 3+ files at once, including one deliberately invalid file (e.g.
  a `.txt` renamed with a CV-like name). Confirm the valid files appear
  in the history table and process independently, and the invalid one is
  reported without blocking the others.
- [ ] Run `python test_corpus.py` — frontend-only change, pass count
  should be unaffected.

---

## Step 6 — Phase 5: staff profile screen

**Builds:** `profiles.html` (new page), nav links on all three pages. See
`BUILD_PLAN.md` §4.4 — including the read-only-name design decision;
don't skip that part, it's there to prevent a real matching bug.

- [ ] Create `app/frontend/profiles.html`, following `index.html`'s
  structure (same header, same `styles.css`/`app.js` includes).
- [ ] Add the `Staff Profiles` nav link to `index.html`, `review.html`,
  and `profiles.html` itself.
- [ ] Build the list view (`GET /api/profiles`) and the edit form, with
  full name **read-only on an existing profile** and editable only when
  creating a new one.
- [ ] Restart the server.
- [ ] Create a new profile for a person already in the test corpus (fill
  in an MDX email, ORCID, etc.).
- [ ] Re-upload that person's CV and confirm the profile prefill still
  happens exactly as HANDOVER.md §4 describes (Camilla's CV is the
  documented example, if she's in your corpus).
- [ ] Open an existing profile's edit screen and confirm the name field is
  disabled/read-only.
- [ ] Delete the test profile you created, to leave the profile store
  clean.
- [ ] Run `python test_corpus.py` — no backend change in this step, pass
  count should be unaffected.

---

## Step 7 — Phase 6: unmapped-headings dashboard + name confirmation

**Builds:** the "frequently unmapped headings" card on `index.html` and the
filename/name-mismatch notice on `review.html`. See `BUILD_PLAN.md` §4
(dashboard UI, using the endpoint from Step 2) and §4.5.

- [ ] Add the dashboard card to `index.html`, reading
  `/api/unmapped-headings-summary`, reusing the same teach-row pattern
  already in `review.html`'s teach panel (heading text, section dropdown,
  "Teach this heading" button posting to `/api/heading-mappings`).
- [ ] Add the name-confirmation notice to `review.html` per §4.5's token
  comparison logic.
- [ ] Restart the server.
- [ ] Upload two CVs that share an unrecognized heading (or reuse two from
  the corpus that do). Confirm the heading appears on the dashboard with
  `cv_count: 2`. Teach it. Confirm it drops off the list on the next
  page load.
- [ ] Upload a CV with an obviously-mismatched filename (e.g.
  `CV_final_v2.docx`) — confirm the notice appears. Upload one properly
  named after the person — confirm it doesn't.
- [ ] Run `python test_corpus.py` — pass count should be unaffected.

---

## Step 8 — Final sign-off

- [ ] Stop the server. Delete `__pycache__` under `app/backend`.
- [ ] Restart the server clean:
  ```
  python -m uvicorn main:app --port 8000
  ```
- [ ] Run `python test_corpus.py` one last time. Compare the pass count
  and the failing-file list against Step 1, exactly. They must match.
- [ ] Full manual walkthrough on one real CV, start to finish: upload →
  review screen loads → approve/reject a few items → generate → download.
  Open the downloaded document and confirm it looks the same as it would
  have before this build (same sections, same content) — this build
  should have changed nothing about what a generated CV contains.
- [ ] If using git:
  ```
  git add -A
  git commit -m "Phase 2: batch upload, activity log, profile screen, configurable auto-approval, unmapped-headings dashboard, name confirmation"
  ```

---

## If something breaks partway through

- Each phase above is independent, so isolate the failure to the phase you
  were on when `test_corpus.py`'s pass count changed, or a manual check
  failed.
- If you committed after each phase (recommended even beyond Step 0):
  `git diff HEAD~1` shows exactly what that phase changed, and
  `git checkout -- .` reverts to before it if needed.
- If you didn't use git: go back to the `BUILD_PLAN.md` section for that
  phase and re-check the change against the exact code given there —
  most failures at this scale are a copy/paste mismatch (a missed import,
  a mismatched route path), not a design problem, since every phase here
  is additive and none of them touch the tuned classifier/routing code.

---

## Quick reference

| Action | Command |
|---|---|
| Start the server | `cd app\backend` then `python -m uvicorn main:app --port 8000` |
| Run the regression suite | `cd app\backend` then `python test_corpus.py` |
| Open the app | `http://localhost:8000` |
| Commit a checkpoint (if using git) | `git add -A && git commit -m "<phase name>"` |
