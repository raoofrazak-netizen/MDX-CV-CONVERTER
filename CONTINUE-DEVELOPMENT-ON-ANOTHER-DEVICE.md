# Moving this build to another device to continue development

This project already has a GitHub remote set up (`origin` →
`raoofrazak-netizen/MDX-CV-CONVERTER`), so the right way to continue
development on a second device is **git clone**, not copying the folder by
hand. Git gives you real version history across both devices, so changes
made on either one are never silently lost or overwritten by the other.

**Do not use `TESTING-ON-ANOTHER-DEVICE.md`'s "copy the folder" method for
this** — that's fine for a one-off look at the build, but it has no way to
sync changes back, so the two devices drift apart immediately.

---

## ⚠️ First: today's work is not on GitHub yet

Everything fixed in this session — the letter-spacing name detection, the
language-proficiency routing fix, the dual-title job-title splitting, the
whole optional AI layer (`app/backend/ai/`), the AI-suggested heading
mappings feature, and the accompanying docs — is sitting **uncommitted**
on this machine right now. None of it has been pushed to GitHub.

If you `git clone` on the other device before dealing with this, you will
get an **older build missing every fix from today**.

### Check what's uncommitted

```bash
cd "C:\Users\test\claude converter\MDX CV CONVERTER"
git status
```

### Commit and push it from THIS device first

```bash
git add -A
git commit -m "Session work: letter-spacing fixes, language routing, job-title cleanup, optional AI layer"
git push origin main
```

Only do this once you're ready — it's a real push to a real GitHub repo,
visible to anyone else with access to it. If you'd rather review the diff
first, run `git diff` before adding, or ask for a walkthrough of what
changed.

---

## On the new device

### 1. Clone the repo

```bash
git clone https://github.com/raoofrazak-netizen/MDX-CV-CONVERTER.git
cd MDX-CV-CONVERTER
```

(If the new device already has an older clone, `git pull origin main`
instead of cloning fresh.)

### 2. Install dependencies

Needs Python 3.10+ (developed and tested on 3.14):

```bash
cd app/backend
pip install -r requirements.txt
```

### 3. Verify the transferred build is intact

Run the full regression suite before touching any code — this confirms
the clone is complete and nothing broke in transit:

```bash
python test_corpus.py
python test_ai_two_stage.py
python test_ai_segmentation.py
python test_ai_knowledge_base.py
python test_ai_section_resolution.py
python test_heading_mapping_suggestions.py
python test_letterhead_and_language_routing.py
```

`test_corpus.py` needs real CV files to run against — it looks in
`C:\Users\test\Downloads` and two subfolders by default (see
`CORPUS_DIRS` near the top of `test_corpus.py`). Those sample CVs live
only on this machine; either point `CORPUS_DIRS` at wherever sample CVs
exist on the new device, or copy a few real/reconstructed CVs there. The
`test_ai_*` and `test_heading_mapping_suggestions.py` / `test_letterhead_and_language_routing.py`
files are fully self-contained and need no external files.

### 4. Start it

```bash
python -m uvicorn main:app --port 8000
```

Open `http://localhost:8000`.

---

## What does NOT come with `git clone` (by design)

| Left behind | Why | What to do about it |
|---|---|---|
| `app/data/uploads`, `app/data/generated`, `app/data/photos`, the SQLite database | Gitignored on purpose — real staff CVs and personal data have no business sitting in a GitHub repo | If the new device needs the actual CV history, copy `app/data/` across manually (USB/shared drive) — see `TESTING-ON-ANOTHER-DEVICE.md` §Option B |
| `backend/.env` (`ANTHROPIC_API_KEY`, if ever set) | Gitignored — a local secret, never committed | Set it again on the new device only if that AI path is wanted there |
| Ollama itself, and the `llama3.2` model | Not part of this repo at all — a separate local install | `winget install Ollama.Ollama` (or the Ollama installer for the new OS), then `ollama pull llama3.2`, if the local-AI features are wanted there too |
| The `impeccable` design skill | Installed outside this project; only its output (`PRODUCT.md`, `DESIGN.md`) is tracked in git and travels normally | Reinstall separately (`npx impeccable install`) only if actively authoring more design work with it |

---

## Picking up development on the new device

Read these two files first — they're the actual state of the project, not
just a static reference:

- **`HANDOVER.md`** — what the build does today, feature by feature,
  including the optional AI layer, and known limitations (§7) worth
  knowing before promising a fix is possible.
- **`FIXLOG.md`** — every real defect found so far and what actually
  caused it, so a new bug isn't mistaken for a repeat of an old one (or a
  fix isn't attempted for something already tried and reverted for a
  documented reason).

### The working method this project has used throughout — keep following it

1. **Never break the deterministic rule engine** while adding anything new
   — it's the part that works with zero configuration and no AI.
2. **Run the full regression suite before AND after every change**
   (`test_corpus.py` plus every `test_*.py` file) — a fix for one CV must
   never silently break another.
3. **Test live** — upload a real CV through the actual running app and
   check the actual generated `.docx`, not just unit test output.
4. **Write a permanent regression test for every real bug found**, in the
   relevant `test_*.py` file (or a new one, named for what it covers).
5. **Clean up test data afterward** — delete any CV/items created purely
   for testing, both from the SQLite database and `app/data/`. Don't leave
   synthetic test rows sitting in a database meant for real staff CVs.
6. **Update `HANDOVER.md` and `FIXLOG.md`** to reflect the real, current
   state after every change — these two files are what make it possible
   to hand this project to anyone (including a future you, on a third
   device) without re-deriving everything from the code.
7. **Commit and push** once a change is verified end to end, so the other
   device can `git pull` and stay in sync rather than drifting apart.

If continuing with an AI coding assistant on the new device, pointing it
at `HANDOVER.md` and `FIXLOG.md` first gives it the same context this
session had — it should not need to re-discover the project from scratch.
