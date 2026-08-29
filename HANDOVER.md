# MDX Faculty CV Converter — Status & Handover

Converts a staff member's own CV (PDF or DOCX) into the official MDX Faculty
CV template, with a human review step in between.

**Runs entirely offline. No AI, no API key, no internet connection required.**

---

## 1. Running it

```
cd "C:\Users\test\claude converter\MDX CV CONVERTER\app\backend"
python -m uvicorn main:app --port 8000
```

Then open <http://localhost:8000>.

First-time setup only:

```
pip install -r requirements.txt
```

### Where the project lives

`C:\Users\test\claude converter\MDX CV CONVERTER`

> The original location (`C:\Users\Claude projects\MDX CV CONVERTER`) is
> **read-only** for this Windows account — files there cannot be edited. All
> work was moved to the path above. If the project should live somewhere
> canonical, an administrator needs to fix permissions on the original folder
> first.

---

## 2. How it works

```
Upload → Extract text + photo → Classify into 20 MDX sections
       → Re-route items by meaning → Validate → Auto-approve confident items
       → Draft biography → Apply saved staff profile
       → HR review → Generate DOCX → Download
```

Classification is **deterministic and rule-based** (`backend/rule_classifier.py`).
It matches section headings in the source CV against the official template's own
heading text plus ~90 common synonyms, groups the content beneath each, and
pulls letterhead fields by anchoring on wherever the email/phone actually
appear in the document.

Extracted content is always a **verbatim quote** from the source CV. Anything
that isn't an exact substring is discarded server-side. The two things that
are *not* quotes — saved profile data and the drafted biography — are labelled
with their own provenance and never presented as if they came from the CV.

### Optional AI upgrade

If `ANTHROPIC_API_KEY` is set in `backend/.env`, classification and biography
drafting switch to Claude, which handles unlabelled/freeform CVs better. This
is **purely optional** — nothing requires it.

---

## 3. The review workflow

This is the part that changed most, and the part to understand before using it.

### Items are auto-approved unless they need attention

Items scoring **≥ 0.75 confidence with no data-quality flags** are approved
automatically on upload. Only genuinely uncertain or flagged items are left
pending. Review becomes exception handling rather than data entry.

| CV | Items extracted | Auto-approved | Left to review |
|---|---|---|---|
| Camilla (5-page academic CV) | 90 | 73 | **17** |
| Daphne (academic CV) | 77 | 68 | **9** |
| Dimo (MDX-format CV) | 57 | 45 | **12** |
| Raoof (IT support résumé) | 31 | 16 | **15** |
| Anujith (AV technician résumé) | 10 | 8 | **2** |

Camilla's review count is higher than the others because 10 of her items were
**re-routed by meaning** (§5a), and a re-routed item is deliberately held
below the auto-approval threshold. Moving an entry between sections is a
judgement call, so it always reaches a person.

> **This is a deliberate trade-off, and a change from the original design.**
> Items now reach the document without an explicit per-item human decision.
> The reviewer still sees everything and can reject or edit anything, and a
> CV still cannot be generated while flagged items remain unresolved — but if
> HR requires per-item sign-off, raise `AUTO_APPROVE_MIN_CONFIDENCE` in
> `backend/validation.py` (set it above 1.0 to restore the old behaviour).

### Three ways to clear the queue

1. **Keyboard** — `J`/`K` move, `A` approve, `R` reject, `E` edit, `Esc` exits
   the edit box. Focus advances automatically, so `A A A` flows continuously.
2. **Bulk buttons** — "Approve all remaining", or "Approve N pending" per section.
3. **Command bar** — plain English, e.g.
   `approve publications` · `reject teaching` ·
   `add Best Paper Award 2025 to awards` · `set email to a.b@mdx.ac.ae`

   The parser is deterministic, not an LLM — it works offline and instantly.
   An unrecognised command says what it didn't understand rather than guessing.

### Split-screen

The original CV sits alongside the review flow. PDFs render natively. DOCX
shows extracted text instead, because browsers cannot display `.docx` and
server-side conversion would require LibreOffice (not installed). The pane
collapses, and the preference is remembered.

---

## 4. The staff profile store

Solves the biggest structural gap: **information no CV contains.**

A staff member's own CV carries their personal or previous-institution email,
not their MDX one — and usually no ORCID, LinkedIn, or membership list at all.
These are stored once per person and re-applied automatically to every future
upload, matched on the person's name.

**Verified:** saving Camilla's profile and re-uploading her CV automatically
populated her MDX email, desk phone, job title, ORCID, LinkedIn and both
professional memberships — four sections that were previously impossible to
fill from the CV alone.

Manage profiles via the API (`/api/profiles`), or seed one from a reviewed CV
with `POST /api/cv/{id}/save-profile`, which pre-fills it from what was already
extracted so only the MDX-specific fields need typing.

Profile-sourced items are labelled **"Saved staff profile"** in the review
screen, so it is always clear what came from the CV and what did not.

---

## 5. Biography drafting

Most CVs have no biography section, and it was previously left blank for the
reviewer to write from scratch. A first draft is now assembled from facts
already extracted from the same CV (name, current title, highest qualification,
publication and project counts).

Safeguards, because this is the only generated prose in the system:

- Only already-extracted facts are used; a clause is **omitted** when the fact
  behind it is missing, never filled with a plausible guess.
- **Never auto-approved.** It always sits pending at low confidence with a
  `drafted_not_extracted` flag, so a person must read it before it can reach a
  document.
- Gender is never inferred — the person's name and neutral phrasing are used.
- Skipped entirely if the CV already has a biography.

---

## 5a. Meaning-based routing

CVs routinely gather unlike things under one heading. A real case: a single
**"SELECTED LEADERSHIP ROLES"** heading holding eleven entries that the
university's own HR reviewer distributed across **five** different MDX
sections. Heading-based classification cannot do that — all eleven share one
heading, so they all land in one section, leaving four sections empty and one
overfull.

Each item is now also examined for what it *says*, and re-filed accordingly
(`backend/routing.py`):

| Source line (all under one "Leadership Roles" heading) | Routed to |
|---|---|
| Associate Editor, Cambridge Journal of Education | Editorial Roles |
| Reviewer, Comparative Education Review | Editorial Roles |
| Member, Advisory Group, Parliamentarians Caucus | Committees |
| Co-convenor, CASES Seminar Series | Knowledge Exchange |
| Participant, *Mukalma* TV programme | Knowledge Exchange |
| Co-founder and Convenor, SAARE Network | Academic Leadership |

Measured against the HR-completed version of the same CV, Academic Leadership
went from **15 items to 2 — exactly HR's count** — and three previously empty
sections were populated. Every move matched HR's own judgement.

### Three rules that keep it safe on any CV

1. **It never overrides what the CV states.** If a document uses the
   template's own heading text (`AWARDS AND RECOGNITIONS`), everything under
   it stays put regardless of wording. Routing only corrects sections that
   were a *guess* from a generic or misspelled heading — exactly where the
   classifier had no real information. CVs already written in MDX format get
   **zero** re-routing, because nothing needs correcting.

2. **Only the role position is examined** (the first 60 characters). Scanning
   whole entries misfired badly in testing: *"Senior Lecturer… Head of Centre
   for Academic Success"* was filed under Centres of Excellence because
   "Centre" appears late in the job title.

3. **The earliest role word wins, not rule priority.** A CV entry leads with
   its primary role. This keeps `Lecturer/Examiner (PG)` in Teaching while
   sending `Examiner, MPhil in Architecture` to Editorial Roles — the same
   distinction the HR reviewer made.

Every moved item is flagged `rerouted_by_content` and capped below the
auto-approval threshold, so a re-filing decision always reaches a human.

---

## 5b. Regression testing — run this after every change

```
cd app\backend
python test_corpus.py
```

Runs every CV in the test corpus through the full pipeline and asserts the
invariants that must hold for **any** CV, whatever its layout or wording:

- text is extracted at all, and in meaningful volume
- a full name is found, and is a name — not a job title, organisation,
  section heading, contact string, or a fragment of the job title
- an email is found whenever the source contains one
- no orphaned date fragments (`2025-26` standing alone as an item)
- no body item that is just an echo of the person's name
- no employment line that renders as bare dates with no role
- no words welded together across a line break
- generation produces a valid, non-empty DOCX
- a section with approved content keeps its heading; an empty one does not
  appear at all — heading included (§5c)
- the UNMAPPED INFORMATION heading is never written into the generated
  document, for any CV (§5c)
- extracted profile links are followable addresses, not truncated fragments (§5d)
- structured qualification fields are self-consistent, and a rendered line
  never loses the degree it was built from (§5e)
- the verbatim-quote guard never has to fire — if it does, an item was built
  from non-adjacent source lines and silently discarded; that is a grouping
  bug, not a reason to relax the guard (§5f)

The corpus currently holds **25 CVs** — a mix of academic MDX-format CVs,
plain-language résumés, and converted/vendor-template files — plus two files
that are deliberately expected to be *refused* (damaged embedded fonts; see
§5f), which the harness checks produce a clear, human-readable message rather
than counting as a failure.

**Why it exists:** every fix to this pipeline was previously prompted by a
single CV failing, and fixing that one file in isolation is exactly how the
same class of bug kept reappearing in a new guise. This suite turns "it works
on the file in front of me" into "it works on all of them".

It caught five real defects on its first run, and three regressions
introduced by fixes made while it was being written.

**Fix history:** every defect found so far, its actual root cause, and what
changed is recorded in [`FIXLOG.md`](FIXLOG.md) — including approaches that
were tried and rejected, so they aren't retried.

---

## 5c. What appears in the generated document, and why

Two policies here reversed during this project, on direct, explicit HR
instruction each time. This section describes the **current** behaviour;
the history is in `FIXLOG.md` if you need to know why it changed twice.

### Empty sections are removed, not shown

A section with nothing approved does not appear in the generated document —
heading included.

**This is the second policy on this point.** The first version deleted empty
sections. That was reversed to show the heading with "Information not
provided.", on the reasoning that a visible gap proves the section was
checked, not skipped, and that quietly removing part of the official
template from a document meant to represent that template was itself a
problem. That version shipped and was then reversed back on direct
instruction: a document going to management should never carry a section
title with nothing behind it, full stop. **The current behaviour matches the
original: remove it entirely.** If this ever needs revisiting again, that
tension — auditability of "was this checked" vs. a clean, gap-free document —
is the actual tradeoff, not a bug in either direction.

### The UNMAPPED INFORMATION note exists only in the review screen

Reconciliation still runs exactly as before: every line of the source is
checked against every item produced, and a line nothing accounts for shows
up as its own item in the **Unmapped Information** section of the review
screen, so a reviewer can see it, move it to a real section, teach its
heading (§5g), or reject it as noise. Generation still requires every item —
unmapped ones included — to be explicitly approved or rejected before
"Generate" unlocks; nothing about that has changed.

**What changed:** the generated DOCX no longer carries an UNMAPPED
INFORMATION appendix at all. HR's instruction was direct: a management-
facing CV must never show a section titled "Unmapped Information." An item
still sitting in that category at generation time (approved there rather
than moved) simply does not appear anywhere in the downloaded file — the
review screen says this explicitly next to the section now, so approving an
unmapped item is understood as "reviewed", not "will be in the document."

This means the tool's data-integrity guarantee is now scoped to the **review
process**, not the final file: nothing is ever silently lost from what a
reviewer can see and act on, but a reviewer can choose — implicitly, by not
moving an item — to leave something out of the document HR actually sends.
That is now a deliberate, available outcome, not an accident.

### Coverage, reported separately from confidence

The review screen now reports both, because they answer different questions:

- **Confidence** — how sure the classifier is about what it filed.
- **Coverage** — how much of the extracted content reached a real MDX section
  rather than the unmapped note.

A CV can score high on one and low on the other. A two-column PDF extracts
cleanly and confidently but scrambles its reading order, so much of it ends
up unmapped. Low coverage is not a failure — nothing was lost either way —
but it tells the reviewer to expect hand-filing, and it is the honest signal
that a layout defeated the classifier.

### Skills and Language Proficiency: an explicit exception to "unmapped only"

Two categories of content are common enough on almost every CV that they get
their own real, labelled sections — **SKILLS** and **LANGUAGE
PROFICIENCY** — rather than landing in the generic unmapped note, even
though neither is one of the MDX template's 20 official sections.

This is a deliberate policy exception, made on explicit instruction after
being raised twice: HR does not want a management-facing document to show
"Unmapped Information" containing a candidate's technical skills or
languages — even though that followed the conversion spec's own §8 rule to
the letter, it read as broken rather than careful. The two new sections are
appended after the 20 official ones, styled identically to a real section by
cloning the template's own heading format, and present only when there is
content for them — an empty CV never gets a bare "SKILLS" heading with
nothing under it. (The UNMAPPED INFORMATION note itself no longer appears in
the generated document at all, for anything — see above.)

**What this is not:** a general licence to keep adding sections outside the
20. Skills and Language Proficiency were promoted because they are close to
universal on any CV and unambiguous to detect from their own heading text.
A one-off, CV-specific heading with no MDX equivalent still correctly lands
in UNMAPPED INFORMATION — see §5f and `FIXLOG.md` for what was tried, and
rejected, when attempting to generalise beyond curated exact-heading matches.

---

## 5g. HR-taught headings — no code change needed for the next new one

A real CV will always eventually use a heading nobody has seen before —
that's inherent to the problem (see §7's honest limitation), not something
one round of fixes closes off. The answer isn't a smarter algorithm; it's
making the fix something HR can do themselves, in seconds, from the review
screen.

**Where it lives:** the bottom of the **Unmapped Information** section, once
it has content. Every distinct source heading behind that CV's unmapped
items gets its own row — a dropdown of all 20 official sections plus Skills
and Language Proficiency, and a "Teach this heading" button.

**What happens on click:** the mapping is written to
`custom_heading_mappings` (`backend/storage.py`) and takes effect
**immediately** — `rule_classifier.register_custom_heading()` updates the
live, in-memory lookup table in the same call, no server restart. It applies
to every CV uploaded from that point on, not just the one currently open;
the CV in front of the reviewer still needs its *existing* unmapped items
moved by hand (the mapping is forward-looking, it doesn't retroactively
reclassify what's already been extracted).

**Why this, rather than a smarter classifier:** three separate attempts at a
general "detect any unrecognised heading" rule were built and rejected this
session (§5f, and the full experiment log in `FIXLOG.md`) — every version,
however narrowly scoped, ended up misclassifying something that had been
working on a different CV. A human glancing at "OTHER INFORMATION" or
"VOLUNTEER WORK" and saying where it belongs is a judgement call the
classifier cannot make safely on shape alone, but a person makes correctly
in about two seconds. This turns that two seconds into a permanent fix
instead of a one-off correction repeated on every future CV that uses the
same wording.

**API:** `GET/POST /api/heading-mappings`, `DELETE
/api/heading-mappings/{id}`. Priority in `_find_heading_key`: an exact
official template heading always wins first (so a mapping can never
accidentally override the template's own structure); a taught mapping wins
next, ahead of the built-in fuzzy/contained-phrase guesses.

---

## 5d. Reading the whole document

Three sources of content that were previously invisible are now read
(`backend/extraction.py`):

- **Headers and footers** — separate parts of the DOCX package, so walking
  `word/document.xml` never saw them. CVs commonly put the contact strip, an
  ORCID, or a running name line there.
- **Hyperlink targets** — a CV that writes "ORCID profile" as clickable text
  carries the address only in `document.xml.rels`. Reading `<w:t>` alone lost
  the identifier completely. A link whose visible text already contains the
  URL is not duplicated.
- **Scholarly identifiers anywhere in the document** (`backend/identifiers.py`)
  — ORCID, Scopus, Google Scholar, LinkedIn, ResearchGate, Publons, GitHub,
  Academia.edu, plus personal and centre websites. Almost no source CV has a
  "Profiles and Links" heading, so heading-based classification found none of
  them and the section came out empty on CVs that plainly contained the data.

A generic web address only counts as a profile when it appears in the
identifying part of the CV or under a profiles heading. Deeper in the
document an `http` link is overwhelmingly a citation or a blog post the
person wrote — one academic CV carried eleven, and treating them all as
profiles filled the section with publication URLs while saying nothing about
who the person is.

---

## 5e. Structured facts, with a safe fallback

Qualifications are parsed into **degree / subject / institution / country /
year** as separate fields, so a reviewer can correct the institution without
retyping the degree, and two degrees never collapse into one line.

The rule that keeps this safe: **a rebuilt line is only used when the parse is
demonstrably complete.** If the source states a year the parse didn't
capture, or the subject trails off mid-date, the item falls back to the
verbatim source text. A half-parsed line reads as finished while having
dropped a fact — worse than simply printing what the CV said. The structured
fields are still stored either way, because the reviewer's editor and the
profile store both use them.

Memberships and editorial roles additionally carry a `kind` field
distinguishing what the spec says must stay distinguishable — fellowship vs.
membership vs. visiting appointment; editor vs. editorial board member vs.
reviewer vs. external examiner. It is metadata, not display text: it is
excluded from the generated line, so an entry tagged `Membership` can never
be *replaced* by the word "Membership".

---

## 5f. Non-academic and converted résumés

The corpus originally validated only academic MDX-style CVs. Adding ordinary
converted résumés (`Downloads/*-converted.docx`, vendor templates) to the
regression suite immediately failed 5 of the first 15 added, and fixing them
found a further silent-loss bug. Full detail in `FIXLOG.md`; the headline
changes:

- **Biography synonyms widened.** A résumé's `Profile` / `Objective` /
  `About Me` paragraph is exactly the biography content the template wants,
  but none of those headings were recognised, so BIOGRAPHY printed
  "Information not provided" on a CV that had one written out in full.
- **List structure recognised without bullet glyphs.** Some converted files
  carry no bullet characters at all. Sentence-boundary grouping then merges
  an entire employment history into one paragraph — one CV welded three jobs,
  eighteen responsibilities, and two buried job titles with their date ranges
  into three giant blobs. A colon-terminated intro line followed by
  gerund-opening lines ("Answering...", "Organizing...") is now recognised as
  a list, split into one item per line, and closed the moment a capitalised
  non-gerund line appears.
- **Vendor template advertising filtered out.** Free résumé templates embed
  the publisher's own marketing ("Hire one of our certified professional
  resume writers…") addressed to the candidate, not written by them. It was
  being published as MDX employment history and their order page filed under
  Professional Profiles. Both are now recognised and excluded — not from the
  unmapped note either, since it is not the candidate's information at all.
- **Non-ASCII names fixed.** The name-shape pattern was ASCII-only, so
  **"César Cabal" was rejected outright** and an employer name was picked up
  instead — this affected any candidate whose name carries an accent.
- **Email now outweighs an uncorroborated name guess.** Where a Title-Case
  phrase on the page turned out to be a section label ("Risk Management",
  "Coursework Design"), the address sitting right next to it — a much
  stronger signal — was previously not consulted unless nothing else was
  found. The address now wins whenever it disagrees with an unconfirmed
  shape match.
- **Column layouts read correctly.** "John Smith␣␣␣␣␣␣Secondary Teacher
  History Department" is two fields separated by a wide gap (a collapsed
  tab or table cell), not one four-word phrase. Splitting on 3+ spaces
  recovers the name.

Name detection across the (now 25-CV) corpus: **19/23 correct → 22/23**. The
one miss is a blank vendor template whose contact literally reads
`youremail@gmail.com` — there is no person in it to find.

### 2026-08-29 additions — a global extraction bug, hyphenated names, résumé-style employment lines

Corpus is now 34 CVs. Full detail and every defect table in `FIXLOG.md`; the
two changes worth knowing about specifically because they are corpus-wide,
not per-file:

- **DOCX paragraph deduplication was silently deleting real content.**
  `_docx_paragraph_texts()` used to drop any paragraph whose text repeated
  verbatim anywhere earlier in the document — meant to catch a heading
  duplicated between a decorative shape and the body, but it fired on
  ordinary content too, most commonly a person's current job title (printed
  once in the letterhead, once again as the title of their most recent job).
  Now scoped to heading-shaped text only (short + ALL CAPS or
  colon-terminated); repeated ordinary content is kept.
- **Hyphenated and apostrophe'd names now work.** `"Al-Mansoori"`, `"O'Brien"`,
  `"D'Souza"` used to fail name-shape matching outright over the punctuation
  mark inside one word, falling back to a worse, email-derived guess.
- Employment-line field parsing (title vs. employer vs. location/dates) was
  reworked for several résumé-style layouts — a job title and its
  employer/city/state glued onto one line with different casing conventions,
  a title-only line followed by a separate employer/location/date line, and
  a corporate suffix (`Inc.`, `LLC`) carrying its own comma. See `FIXLOG.md`
  for the full defect list; a **known, deliberately unfixed** case is a bare
  `"City, ST"` line with no other context — a filter for it was tried and
  reverted because it also deletes real institution/employer names ending in
  a state abbreviation.

### Garbled text is now detected and refused

Two files in the corpus extract as text but not as **words**: a subsetted
font with a damaged character map turns `Orlando` into `zrlando`,
`example@email.com` into `ePample/email.com`, `NATIONALITY` into
`N AT I z N A 9 I T B`. The file is neither empty nor a scan, so nothing
previously caught it, and every later stage worked confidently on nonsense.

Detected by the share of whitespace-separated tokens that are a single stray
letter — real prose essentially never produces these, a broken font
character-map does. The two damaged files score 0.21–0.22; the highest
legitimate CV in the corpus (a design-heavy résumé with letter-spaced
headings) scores 0.049. Threshold is 0.12, comfortably clear of both.

```
This usually means the document was produced by a converter that
embedded a damaged font. Please re-save it as a PDF from the original
application, or upload the original file.
```

---

## 6. What else it does well

- **Section classification** across the 20 fixed MDX sections, including
  academic CVs headed "Selected Publications", "Research Projects",
  "Additional Work Experience", etc.
- **Funded projects** split into `Project Title` / `Role` / `Duration` /
  `Funding Agency`, parsed from the CV's own "(Funded by X, 2025–26)" pattern.
- **Publications** grouped into peer-reviewed journals / blogs and media /
  conference presentations, with the group headings preserved.
- **Editorial roles** sub-grouped in the generated document the same way —
  Editor / Editorial Board Member / Reviewer / Examiner each get their own
  sub-heading. Items are bucketed into a fixed print order rather than
  grouped only when adjacent, because a CV commonly interleaves them ("Guest
  Editor, Journal A" then "Reviewer, Journal B" then "Guest Editor, Journal
  C") — grouping strictly by proximity would otherwise print the same
  sub-heading three times. An item whose role doesn't resolve to one of the
  four kinds is still included, appended after the recognised groups with no
  sub-heading of its own, so nothing is dropped for not fitting.
- **Date normalisation** — `2025–26` → `2025–2026`, century-aware so
  `1999–02` correctly becomes `1999–2002`.
- **Profile photo** auto-detected (distinguishing a headshot from logos and
  banner art) and embedded into the template's photo cell; HR can upload or
  replace it manually.
- **Empty sections removed entirely**, heading included.
- **Template boilerplate stripped** — the template's own "While not all
  academics may have information to provide…" instruction never reaches the
  finished document.
- **Name detection: 9/9** across all test CVs, including two that have no
  letterhead at all (name found via the uploaded filename as a search anchor,
  then read back out of the document text).

---

## 7. Limitations — read this before setting expectations

### Still cannot be derived from a CV

The profile store and biography drafting closed most of this gap, but not all
of it. Comparing a reference "gold standard" MDX CV against the raw CV it came
from, these remain manual:

> Note on what "cannot be derived" now means. Content that exists in the CV
> but reaches no MDX section is no longer lost — it goes to the UNMAPPED
> INFORMATION note (§5c). What follows is content that is **not in the source
> at all**, or that requires a judgement no rule can make.

- **One-off awards and qualifications** not present in the source (e.g. an
  O'Levels entry, a prize the CV doesn't mention). Add them once via the
  command bar or the section "Add item" box.
- **Editorial judgement.** Meaning-based routing (§5a) now handles the
  largest slice of this — deciding that an "Associate Editor" entry belongs
  in Editorial Roles rather than Leadership. What remains still needs a
  person: a human resolved "OPM led" to *Oxford Policy Management*, expanded
  FCDO to *Foreign and Commonwealth Development Organisation*, collapsed
  eight project entries into four employment lines with spanning date ranges,
  inferred countries from institution names, and dropped non-academic roles
  as irrelevant to a faculty CV. No rule engine does that reliably.

- **Splitting one line into two facts.** HR pulled two awards out of the
  middle of a qualification line ("…Cambridge Trust & King's College Xu Zhimo
  Scholar"). Routing moves whole items between sections; it does not cut one
  item into several.

### Other constraints

- **A large unmapped count means the classifier struggled**, not that the
  tool broke. Résumé-style and heavily designed CVs can send 20–60 lines to
  the review screen's Unmapped Information section, and the coverage figure
  says so plainly. Nothing is lost from the *review* — but since the note no
  longer appears in the generated document (§5c), anything left unmapped
  when "Generate" is clicked simply is not in the download. That CV needs
  real review time, and the reviewer should expect to move real content into
  a proper section (or teach the heading, §5g) rather than leave it here.
- **No OCR.** Scanned or image-only PDFs are rejected with a clear message
  rather than producing garbage.
- **Multi-column PDFs extract out of visual order**, which can misfile content
  or merge a company and a role onto one line. Two proper fixes were tried and
  both failed on real files: pypdf's `layout` extraction mode returns nothing,
  and coordinate-based column reconstruction is impossible because the PDFs
  don't expose absolute text positions (see `FIXLOG.md`). Routing recovers most
  of it; the review step catches the rest, and such items are flagged as
  uncertain rather than silently accepted.
- **Résumé-style CVs need more review.** Raoof's leaves 15 of 31 items pending
  because unlabelled-block content genuinely scores low. That is the classifier
  being honest about uncertainty, not a defect.
- **A section heading this system has never seen before will misfile its
  content into the section above it**, rather than being recognised as its
  own topic. This was tested deliberately, not assumed: a general detector
  for "any unrecognised heading" was built and tried three times, and each
  version broke something that had been working — a real employer name, a
  bare job title, a person's own repeated name header, or a Publications
  sub-heading were each mistaken for a section boundary in turn (full detail,
  including why each attempt failed, in `FIXLOG.md`). No structural signal
  tried (capitalisation, colon-termination, length) reliably tells an unknown
  *section* heading apart from ordinary CV content shaped the same way, so
  none of the three shipped.
  **What holds regardless:** the content is never deleted from the *review
  process*. It is always a verbatim quote of the source, and it surfaces
  either in an adjacent section or in the review screen's Unmapped
  Information, visible and reviewable, rather than vanishing without a
  trace. (It does not follow that it reaches the final document — see §5c:
  an item still unmapped when "Generate" is clicked is not in the download,
  by explicit instruction. The guarantee is that a reviewer can always see
  and act on it before that point, not that inaction produces it anyway.)
  The fix for a specific new heading (as for `PROFESSIONAL
  DEVELOPMENT`, `LANGUAGE PROFICIENCY`, `SELECT PRACTICE OUTPUTS` this
  session) is a one-line addition to `SYNONYM_HEADINGS` once it's seen on a
  real upload, and it then applies to every future CV that uses the same
  wording — the list only grows, and carries zero regression risk since it
  fires on an exact match. Run `test_corpus.py` against any new upload that
  exposes one before adding it.
- **Filename matters.** Name detection uses the uploaded filename as a search
  anchor, so `Anuradha Vyas CV.docx` works well while `CV_final_v2.docx` falls
  back to weaker heuristics. **Ask staff to name files after the person.**
- **No authentication or access control.** Single implicit reviewer, local
  storage. Not yet suitable for multi-user or production HR deployment.
- **Processing is synchronous** — fine at pilot volume, revisit if volume grows.

---

## 8. How to position this to HR

> Gets you most of the way, in seconds, with every extracted item traceable
> back to the source CV — then a reviewer finishes it.

It is **not** a fully automatic converter and should not be sold as one. What
changed is *where* the effort goes: from clicking through 90+ obviously-correct
items, to checking a handful of uncertain ones. Realistically **~5–8 minutes of
review per CV is now under a minute** for a well-structured CV.

---

## 9. Where things are

| Path | What it is |
|---|---|
| `app/backend/rule_classifier.py` | Offline rule-based classification |
| `app/backend/routing.py` | Re-files items by meaning (§5a) |
| `app/backend/unmapped.py` | Reconciles source against items; UNMAPPED note (§5c) |
| `app/backend/identifiers.py` | ORCID / Scopus / Scholar / LinkedIn detection (§5d) |
| `app/backend/test_corpus.py` | End-to-end regression suite (§5b) |
| `app/backend/classifier.py` | Entry point; routes to rules or AI |
| `app/backend/validation.py` | Data checks, confidence bands, auto-approval |
| `app/backend/profiles.py` | Staff profile matching and prefill |
| `app/backend/bio_draft.py` | Biography drafting (offline template or AI) |
| `app/backend/commands.py` | Plain-English command parser |
| `app/backend/template_engine.py` | OOXML template population + photo embedding |
| `app/backend/photo.py` | Headshot detection and manual photo upload |
| `app/backend/formatting.py` | Turns structured fields into document lines |
| `app/backend/quality.py` | Quality report and generation gate |
| `app/frontend/review.html` | Split-screen review screen |
| `app/template/` | The official MDX template (never modified) |
| `app/data/` | Uploads, generated files, photos, SQLite database |
| `FIXLOG.md` | Defect history: cause, fix, and rejected approaches |

### Key API endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/upload` | Upload a CV; processing runs in background |
| `GET  /api/cv/{id}/items` | Extracted items grouped by section |
| `POST /api/cv/{id}/items/bulk` | Approve/reject many at once |
| `POST /api/cv/{id}/command` | Run a plain-English review command |
| `GET  /api/cv/{id}/source` | Original file (PDF preview) |
| `GET  /api/cv/{id}/source-text` | Extracted text (DOCX preview) |
| `POST /api/cv/{id}/photo` | Upload/replace profile photo |
| `GET/PUT/DELETE /api/profiles/{id}` | Manage saved staff profiles |
| `POST /api/cv/{id}/save-profile` | Seed a profile from a reviewed CV |
| `GET/POST /api/heading-mappings` | List/teach a heading -> section rule (§5g) |
| `DELETE /api/heading-mappings/{id}` | Remove a taught mapping |
| `POST /api/cv/{id}/generate` | Produce the MDX DOCX |
| `GET  /api/cv/{id}/download` | Download it |

---

## 10. Suggested next steps

1. **Decide the auto-approval policy** with HR — it is the one behavioural
   change that needs an explicit sign-off (see §3).
2. **Pilot with real CVs** and record where reviewers actually spend correction
   time; that tells you what to improve next, rather than guessing.
3. **Build a profile management screen.** Profiles currently have API endpoints
   but no UI — they must be seeded from a CV or managed via the API.
4. **Standardise filenames** (`Firstname Lastname CV.pdf`) to keep name
   detection reliable.
5. **Add authentication** before this handles real staff data beyond a pilot.
6. **Fix folder permissions** if the project should live at its original path.
