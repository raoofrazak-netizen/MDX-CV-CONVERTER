"""Extract a candidate profile photo from an uploaded CV (DOCX or PDF).

Heuristic, not AI: CVs commonly embed one headshot plus repeated letterhead
art (a logo/crest on every page, or in a header/footer). We pick the image
that looks like a headshot and discard anything that looks like decoration:
  * Any image whose exact bytes repeat across multiple pages/parts is
    treated as letterhead art, not a photo, and excluded.
  * Remaining candidates are ranked by pixel area (largest first) with a
    preference for portrait/near-square aspect ratios (roughly 0.6-1.4),
    since wide banner-shaped images are almost never a headshot.
  * Tiny images (under 80px in either dimension) are ignored as icons.

Returns PNG bytes (normalised so the caller/template engine never needs to
handle multiple source formats), or None if no suitable photo was found.
"""
import io
import zipfile
from collections import Counter
from pathlib import Path

from PIL import Image
from pypdf import PdfReader

MIN_DIMENSION = 80
GOOD_ASPECT_RANGE = (0.55, 1.6)
MAX_UPLOAD_PHOTO_MB = 10


class PhotoError(Exception):
    """Raised with a message safe to show to an HR user."""


def save_uploaded_photo(raw_bytes: bytes, dest_path: Path) -> None:
    """Validate and normalise a manually-uploaded profile photo to PNG at
    dest_path. Used when auto-detection from the source CV picks the wrong
    image, finds nothing, or the CV simply has no embedded photo at all --
    the HR reviewer can supply the correct one directly instead of being
    limited to whatever the automatic extractor found."""
    size_mb = len(raw_bytes) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_PHOTO_MB:
        raise PhotoError(f"Photo is too large ({size_mb:.1f} MB). Maximum allowed is {MAX_UPLOAD_PHOTO_MB} MB.")
    try:
        img = Image.open(io.BytesIO(raw_bytes))
        img.load()
    except Exception as exc:
        raise PhotoError("This file isn't a readable image. Please upload a JPG or PNG.") from exc
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest_path, format="PNG")


def _to_png_bytes(raw: bytes) -> bytes | None:
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except Exception:
        return None
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.mode else "RGB")
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _is_plausible_headshot_shape(width: int, height: int) -> bool:
    aspect = width / height if height else 0
    return GOOD_ASPECT_RANGE[0] <= aspect <= GOOD_ASPECT_RANGE[1]


def _pick_best(candidates: list[tuple[bytes, int, int]]) -> bytes | None:
    """candidates: list of (raw_bytes, width, height). Drops repeated images
    (letterhead/icons) and returns the best remaining one, as PNG bytes.

    Aspect ratio is a HARD filter, not a soft scoring penalty: a decorative
    design element (a thin banner strip, a tall sidebar gradient) can have
    far more raw pixels than an actual headshot -- e.g. a 74x2218 sidebar
    strip is >8x the area of a real 114x177 photo. A soft multiplier isn't
    steep enough to stop that from winning on area alone; excluding
    non-portrait shapes outright is what actually fixes it. Only fall back
    to the largest oddly-shaped image if literally nothing portrait-shaped
    survives, since a wrong guess is worse than surfacing nothing (the
    reviewer can add a photo manually either way)."""
    counts = Counter(raw for raw, _, _ in candidates)
    unique = [(raw, w, h) for raw, w, h in candidates if counts[raw] == 1]
    pool = unique or [c for c in candidates if counts[c[0]] == min(counts.values())]

    pool = [c for c in pool if c[1] >= MIN_DIMENSION and c[2] >= MIN_DIMENSION]
    if not pool:
        return None

    headshot_shaped = [c for c in pool if _is_plausible_headshot_shape(c[1], c[2])]
    final_pool = headshot_shaped or pool

    final_pool.sort(key=lambda c: c[1] * c[2], reverse=True)
    for raw, _, _ in final_pool:
        png = _to_png_bytes(raw)
        if png:
            return png
    return None


def _extract_from_docx(path: Path) -> list[tuple[bytes, int, int]]:
    candidates: list[tuple[bytes, int, int]] = []
    try:
        with zipfile.ZipFile(path) as z:
            for name in z.namelist():
                if not name.startswith("word/media/"):
                    continue
                raw = z.read(name)
                try:
                    img = Image.open(io.BytesIO(raw))
                    w, h = img.size
                except Exception:
                    continue
                candidates.append((raw, w, h))
    except Exception:
        return []
    return candidates


def _extract_from_pdf(path: Path) -> list[tuple[bytes, int, int]]:
    candidates: list[tuple[bytes, int, int]] = []
    try:
        reader = PdfReader(str(path))
        for page in reader.pages:
            for img in page.images:
                try:
                    w, h = img.image.size
                    buf = io.BytesIO()
                    img.image.save(buf, format="PNG")
                    candidates.append((buf.getvalue(), w, h))
                except Exception:
                    continue
    except Exception:
        return []
    return candidates


def extract_photo(path: Path) -> bytes | None:
    """Best-effort candidate headshot as PNG bytes, or None if none found.
    Never raises -- a missing/undetected photo is not a processing failure."""
    suffix = path.suffix.lower()
    if suffix == ".docx":
        candidates = _extract_from_docx(path)
    elif suffix == ".pdf":
        candidates = _extract_from_pdf(path)
    else:
        return None

    if not candidates:
        return None
    return _pick_best(candidates)
