"""Find scholarly profiles and identifiers anywhere in a CV.

The MDX template has a section for these (ORCID, Scopus, Google Scholar,
LinkedIn, personal and centre websites), but almost no source CV has a
matching heading. They turn up in the letterhead, in a footer, beside the
email address, or only as the target of a Word hyperlink whose visible text
reads "ORCID". Heading-based classification therefore finds none of them and
the section comes out empty on a CV that plainly contains the data.

This scans the whole text stream instead, which is what §6 of the conversion
spec requires: confirm a section is empty by reading the entire document, not
by failing to find a heading for it.

Identifiers are recognised by their platform's own address shape, so a bare
ORCID number is matched as readily as a full orcid.org URL, and each platform
is reported once -- a CV that repeats its LinkedIn in the header, the footer
and the contact block yields one entry, not three.
"""
import re

# (platform label, pattern). Order matters only for readability; each
# platform is matched independently.
PLATFORM_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ORCID", re.compile(r"\b(?:https?://)?(?:www\.)?orcid\.org/(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])", re.I)),
    ("Scopus", re.compile(r"\b(?:https?://)?(?:www\.)?scopus\.com/\S*?authorId=(\d+)", re.I)),
    ("Scopus", re.compile(r"\b(?:https?://)?(?:www\.)?scopus\.com/(\S+)", re.I)),
    ("Google Scholar", re.compile(r"\b(?:https?://)?scholar\.google\.[a-z.]+/\S*?user=([A-Za-z0-9_-]+)", re.I)),
    ("Google Scholar", re.compile(r"\b(?:https?://)?scholar\.google\.[a-z.]+/(\S+)", re.I)),
    ("LinkedIn", re.compile(r"\b(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/([A-Za-z0-9\-_%]+)", re.I)),
    ("ResearchGate", re.compile(r"\b(?:https?://)?(?:www\.)?researchgate\.net/profile/([A-Za-z0-9\-_%]+)", re.I)),
    ("Web of Science / Publons", re.compile(r"\b(?:https?://)?(?:www\.)?(?:publons\.com|webofscience\.com)/\S*?/([A-Za-z0-9\-/]+)", re.I)),
    ("GitHub", re.compile(r"\b(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9\-_]+)", re.I)),
    ("Academia.edu", re.compile(r"\b(?:https?://)?(?:[a-z]+\.)?academia\.edu/([A-Za-z0-9\-_]+)", re.I)),
]

# A bare ORCID with no surrounding URL, e.g. "ORCID: 0000-0002-1825-0097".
BARE_ORCID_RE = re.compile(
    r"\bORCID\b[^0-9]{0,12}(\d{4}-\d{4}-\d{4}-\d{3}[\dXx])", re.I
)

# Any other web address. Used for personal and centre websites, which the
# template asks for by name but which have no recognisable shape.
GENERIC_URL_RE = re.compile(r"\bhttps?://[^\s,;<>()\[\]\"']+", re.I)

# Addresses that are never a personal profile: publication DOIs, journal and
# repository sites, and file-sharing links.
GENERIC_URL_EXCLUDE = re.compile(
    r"doi\.org|dx\.doi|/doi/|springer|elsevier|wiley|tandfonline|sciencedirect"
    r"|jstor|researchsquare|arxiv|ssrn|pubmed|ncbi\.nlm|plos\.org|journals\."
    r"|biomedcentral|frontiersin|mdpi\.com|sagepub|emerald|inderscience"
    r"|/article|/articles/|/chapters/|/hub/|/blog/|/publication"
    r"|drive\.google|docs\.google|dropbox|zoom\.us|teams\.microsoft"
    r"|youtube\.com|youtu\.be|twitter\.com|x\.com|facebook\.com|instagram\.com"
    # The résumé template vendor's own order page, embedded in the file by
    # the template rather than written by the candidate.
    r"|resumethatworks|money-zine|resume\.io|zety\.com|novoresume"
    r"|myperfectresume|resumegenius|/order\.php"
    r"|\.pdf$",
    re.I,
)

# A generic web address only counts as the person's own site when it sits in
# the identifying part of the CV. Deeper into the document, an http link is
# overwhelmingly a citation, a blog post they wrote, or a conference page --
# content that belongs to the item it appears in, not to Profiles and
# Identifiers. One academic CV carried eleven such links; treating them all
# as profiles filled the section with the person's own publication URLs and
# said nothing about who they are.
LETTERHEAD_SCAN_LINES = 25
PROFILE_HEADING_RE = re.compile(
    r"\b(?:profiles?|links?|identifiers?|online presence|social media|web)\b", re.I
)
# A URL broken across a line by a PDF exporter ends mid-word on a hyphen or
# underscore and is not a usable address. A trailing "/" is deliberately NOT
# included here -- that is just the normal way to write a root-domain URL
# ("https://www.pointacademy.com/"), not a truncation artifact, and treating
# it as one silently dropped a real, complete profile link.
TRUNCATED_URL_RE = re.compile(r"[-_]$")
MIN_URL_LENGTH = 12


def _canonical_url(platform: str, value: str, whole: str) -> str:
    """A followable address, preferring the CV's own wording.

    CVs routinely write a profile as a bare domain -- "linkedin.com/in/name",
    "scholar.google.com/citations?user=..." -- which is not a usable link in
    a Word document. The scheme is added, since it is the only part that can
    be supplied without inventing anything: the address itself is always the
    one the CV gave.
    """
    cleaned = whole.strip().rstrip(".,;)")
    if cleaned.lower().startswith(("http://", "https://")):
        return cleaned
    if cleaned.lower().startswith("www.") or "." in cleaned.split("/")[0]:
        return "https://" + cleaned
    if platform == "ORCID":
        return f"https://orcid.org/{value}"
    return cleaned


def find_identifiers(text: str) -> list[dict[str, str]]:
    """[{platform, url, source_text}] for every distinct profile in the CV.

    `source_text` is the line the identifier was found on, so the verbatim-
    quote invariant holds for these items exactly as it does for every other
    item in the system.
    """
    found: list[dict[str, str]] = []
    seen_platforms: set[str] = set()
    seen_urls: set[str] = set()

    lines = text.splitlines()

    for line in lines:
        for platform, pattern in PLATFORM_PATTERNS:
            if platform in seen_platforms:
                continue
            match = pattern.search(line)
            if not match:
                continue
            url = _canonical_url(platform, match.group(1), match.group(0))
            seen_platforms.add(platform)
            seen_urls.add(url.rstrip("/").casefold())
            found.append({"platform": platform, "url": url, "source_text": line.strip()})

    if "ORCID" not in seen_platforms:
        for line in lines:
            match = BARE_ORCID_RE.search(line)
            if match:
                url = f"https://orcid.org/{match.group(1)}"
                seen_platforms.add("ORCID")
                seen_urls.add(url.rstrip("/").casefold())
                found.append({"platform": "ORCID", "url": url, "source_text": line.strip()})
                break

    # Personal / institutional websites: whatever is left that isn't a
    # publisher link or a platform already captured above, and only from the
    # part of the CV that is about the person rather than about their work.
    in_profile_block = False
    for index, line in enumerate(lines):
        if PROFILE_HEADING_RE.search(line) and len(line.split()) <= 6:
            in_profile_block = True
        elif line.strip() and line.strip() == line.strip().upper() and len(line.split()) <= 8:
            in_profile_block = False  # a new all-caps heading ends the block

        if index >= LETTERHEAD_SCAN_LINES and not in_profile_block:
            continue

        for match in GENERIC_URL_RE.finditer(line):
            url = match.group(0).rstrip(".,;)")
            key = url.rstrip("/").casefold()
            if key in seen_urls or GENERIC_URL_EXCLUDE.search(url):
                continue
            if len(url) < MIN_URL_LENGTH or TRUNCATED_URL_RE.search(url):
                continue
            if any(p.search(url) for _, p in PLATFORM_PATTERNS):
                continue
            seen_urls.add(key)
            found.append({"platform": "Website", "url": url, "source_text": line.strip()})

    return found
