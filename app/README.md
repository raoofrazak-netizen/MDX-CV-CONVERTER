# MDX Faculty CV Converter — Phase 1 (core pipeline POC)

Upload → Extract → Classify → Validate → Flat-form HR Review → Generate real
MDX template DOCX → Quality report → Download.

**Fully self-contained by default — no AI, no API key, no internet connection
required.** Classification runs entirely locally via a deterministic,
heading-based rule engine (`backend/rule_classifier.py`): it matches section
headings in the source CV against the official template's own heading text,
groups the content underneath, and extracts letterhead fields (name, title,
contact, email) by anchoring on wherever the email/phone actually appear in
the document. Nothing leaves the machine, there's no per-CV cost, and it
works the moment the server starts.

An Anthropic API key is entirely optional. If `ANTHROPIC_API_KEY` is set in
`backend/.env`, the app automatically upgrades to LLM-based classification
instead (better at freeform, unlabelled CVs) — but this is a pure enhancement
layered on top, never a requirement. The portal runs and produces complete
output with zero configuration beyond installing dependencies.

Scope is Phase 1 only, per the build brief: DOCX/text-PDF input (no OCR), single
reviewer, no auth, local file/SQLite storage. See the brief for what Phase 2/3 add.

## Setup

1. **Python dependencies** (already installed in this environment):
   ```
   pip install -r backend/requirements.txt
   ```

2. **(Optional) upgrade to AI classification.** Only if you want it — the app
   works fully without this step. Copy the example env file and fill it in:
   ```
   cp backend/.env.example backend/.env
   ```
   Then edit `backend/.env` and set `ANTHROPIC_API_KEY=sk-ant-...`.

3. **Run the server:**
   ```
   cd backend
   python -m uvicorn main:app --reload --port 8000
   ```
   Open http://localhost:8000 in a browser.

## What's implemented

- Upload (DOCX/PDF), with clear errors for wrong file type, empty file,
  corrupted file, password-protected PDF, or scanned/image-only PDF (OCR is
  Phase 2).
- Text extraction preserving per-block source text (page number for PDF).
- Classification into the 20 fixed MDX Faculty CV sections, self-contained by
  default via a deterministic rule engine (heading matching + letterhead
  anchoring on email/phone position) — or via LLM forced tool-calling
  (structured JSON, not free text) if an API key is configured. Either path
  enforces the same rule: every returned item must quote real, verbatim text
  from the source CV; anything that isn't an exact substring of the source is
  discarded server-side, not just prompted against.
- Rule-based validation independent of classification: confidence banding
  (High ≥90%, Medium ≥70%, Low <70%), overlapping employment dates, duplicate
  publications, malformed email/URL, mandatory fields (Full Name, Email).
- Flat-form review UI: approve / edit / reject / move between sections / add
  missing items / delete incorrect items, with confidence and source text
  visible for every item.
- Generation gate: a CV cannot be generated while any item is still
  `pending_review` or is Low-confidence and unresolved.
- Real template population via direct OOXML editing (not python-docx's
  style API — the template's 18 non-Heading1 section titles have no style
  hook, see `backend/template_engine.py` for the verified structural facts
  this relies on). The master template file is never opened for writing;
  every generation copies it first.
- Quality report with per-section ✓ Verified / ⚠ Needs review / ✕ Missing
  status and overall confidence, shown before download.
- Audit log of upload / edit / generate / download events (`audit_log` table).

## Known Phase 1 limitations (by design, not oversight)

- **No OCR / scanned PDFs.** Image-only documents are rejected with a clear
  message rather than silently producing garbage.
- **Profile photo**: auto-detected from the source CV (picks the headshot,
  excludes repeated logos/decorative art) and embedded into the letterhead's
  photo cell via real OOXML image embedding. HR can also upload or replace
  the photo manually from the review screen if auto-detection is wrong or
  finds nothing.
- **Sections with no approved content are omitted entirely** (heading
  included) from the generated document, rather than left as a bare heading
  with nothing under it — matching what a human filling the template by hand
  would do, and what the template's own instructions say ("add or delete
  sections as applicable").
- **No auth, RBAC, Entra ID SSO, or retention automation** — single implicit
  reviewer, local storage. These are Phase 3 per the brief.
- **Processing is synchronous** (a request blocks until classification
  finishes) — fine at expected pilot volume; revisit if volume grows.
- **Biography drafting is not implemented** — Phase 1 extracts an existing
  bio if the source CV has one; it does not synthesize a new one. That's
  deliberately deferred until the extraction pipeline itself is trusted.

## Brand note carried over from the build brief

The web app UI uses the official MDX Red (`#E30613`) per the brand
guidelines PDF. The **generated CV document** intentionally uses the
template's own colours (`#E42313` red, `#2E74B5` blue) instead, because that
is what the real template file contains — this pipeline does not "correct"
HR's template to match brand guidelines; that's a decision for whoever owns
the template.
