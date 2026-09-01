from pathlib import Path
import os

from dotenv import load_dotenv

load_dotenv()

APP_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = APP_DIR / "data"
UPLOADS_DIR = DATA_DIR / "uploads"
GENERATED_DIR = DATA_DIR / "generated"
PHOTOS_DIR = DATA_DIR / "photos"
DB_PATH = DATA_DIR / "db" / "cv_converter.sqlite3"
TEMPLATE_PATH = APP_DIR / "template" / "MDX_Faculty_CV_Template.docx"
FRONTEND_DIR = APP_DIR / "frontend"

for d in (UPLOADS_DIR, GENERATED_DIR, PHOTOS_DIR, DB_PATH.parent):
    d.mkdir(parents=True, exist_ok=True)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5")

# Optional local, offline "Analyze with AI" review-screen action (see
# ai/provider.py). AI_PROVIDER=none is the default -- nothing about upload,
# classification, or generation changes unless a reviewer explicitly opts
# in per item. This is unrelated to the ANTHROPIC_* whole-document AI path
# above; the two can be configured independently.
AI_PROVIDER = os.getenv("AI_PROVIDER", "none")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
# The build spec's own example config uses 120 (§4); measured directly: once
# prompts were enriched with the §15 knowledge base (per-section
# descriptions, examples, exclusion rules -- ai/knowledge_base.py), a
# 60s default was too tight and real requests against a small local model
# (llama3.2) started timing out around 64s. 120 leaves real headroom above
# the observed worst case rather than trimming the prompt to fit an
# arbitrary budget.
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "120"))

MAX_UPLOAD_MB = 25
ALLOWED_EXTENSIONS = {".docx", ".pdf"}

# The 20 canonical MDX Faculty CV sections, in fixed template order.
# `heading_text` must match the template's exact heading string so the
# generator can locate the paragraph by direct text match (the template's
# section headers are NOT Word heading styles -- see build brief).
SECTIONS = [
    {"key": "profile_photo", "heading_text": None, "label": "Profile Photo"},
    {"key": "full_name", "heading_text": "FULL NAME", "label": "Full Name"},
    {"key": "job_title", "heading_text": None, "label": "Job Title"},
    {"key": "contact_info", "heading_text": None, "label": "Contact Information"},
    {"key": "email", "heading_text": None, "label": "Email"},
    {"key": "biography", "heading_text": "BIOGRAPHY", "label": "Biography"},
    {"key": "qualifications", "heading_text": "QUALIFICATIONS", "label": "Qualifications"},
    {"key": "associations", "heading_text": "PROFESSIONAL ASSOCIATION MEMBERSHIPS AND FELLOWSHIPS",
     "label": "Professional Association Memberships and Fellowships"},
    {"key": "present_employment", "heading_text": "CAREER DETAILS – PRESENT EMPLOYMENT",
     "label": "Career Details – Present Employment"},
    {"key": "previous_employment", "heading_text": "CAREER DETAILS – PREVIOUS EMPLOYMENT",
     "label": "Career Details – Previous Employment"},
    {"key": "teaching_learning", "heading_text": "TEACHING AND LEARNING", "label": "Teaching and Learning"},
    {"key": "committees", "heading_text": "INTERNAL/EXTERNAL COMMITTEES AND ADVISORY ROLES",
     "label": "Internal/External Committees and Advisory Roles"},
    {"key": "academic_leadership", "heading_text": "INTERNAL AND EXERNAL ACADEMIC LEADERSHIP",
     "label": "Internal and External Academic Leadership"},
    {"key": "knowledge_exchange", "heading_text": "KNOWLEDGE EXCHANGE AND PROFESSIONAL PRACTICE",
     "label": "Knowledge Exchange and Professional Practice"},
    {"key": "awards", "heading_text": "AWARDS AND RECOGNITIONS", "label": "Awards and Recognitions"},
    {"key": "centres_of_excellence", "heading_text": "CONTRIBUTION TO MDX CENTRES OF EXCELLENCE/RESEARCH LAB",
     "label": "Contribution to MDX Centres of Excellence/Research Lab"},
    {"key": "grants", "heading_text": "RESEARCH GRANTS, FUNDING AND CONSULTANCY PROJECTS",
     "label": "Research Grants, Funding and Consultancy Projects"},
    {"key": "editorial_roles", "heading_text": "EDITORIAL BOARD MEMBERSHIPS, REVIEW, AND EXAMINER ROLES",
     "label": "Editorial Board Memberships, Review and Examiner Roles"},
    {"key": "publications", "heading_text": "SELECT RESEARCH PUBLICATIONS", "label": "Select Research Publications"},
    {"key": "profiles_links", "heading_text": "PROFESSIONAL PROFILES, LINKS, AND IDENTIFIERS",
     "label": "Professional Profiles, Links and Identifiers"},
    # None of the three below are official template sections. Appended after
    # them, in this order, only when there is content for them.
    # heading_text is None so the generator never tries to locate them in the
    # template; they are written in by _append_synthetic_sections instead.
    #
    # Skills and Language Proficiency: not one of the 20 MDX sections, but
    # common and specific enough on a CV that HR asked for these to read as
    # their own real, labelled sections rather than being folded into the
    # generic unmapped note.
    {"key": "skills", "heading_text": None, "label": "Skills", "synthetic": True},
    {"key": "language_proficiency", "heading_text": None, "label": "Language Proficiency",
     "synthetic": True},
    # The remaining safety net: content that fits neither an official section
    # nor Skills/Language Proficiency. Ensures "nothing is silently lost"
    # stays true even for the content no curated category yet covers.
    {"key": "unmapped", "heading_text": None, "label": "Unmapped Information",
     "synthetic": True},
]

SECTION_KEYS = [s["key"] for s in SECTIONS]

# Sections that exist in the official template. Everything else is generated
# by this tool and must not be treated as part of the template's structure.
TEMPLATE_SECTION_KEYS = [s["key"] for s in SECTIONS if not s.get("synthetic")]

# An empty official section keeps its heading and carries this line, rather
# than being deleted. Locked project decision: a missing section must be
# visibly missing so a reviewer can see the gap was considered, not silently
# absent so they cannot tell whether it was checked.
EMPTY_SECTION_TEXT = "Information not provided."

# NOTE: heading_text values were transcribed verbatim from the template's
# OOXML (including its typo "EXERNAL"). Do not "fix" the typo here -- the
# generator must match the template's actual text or section location fails.
