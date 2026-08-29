"""Populate the real MDX Faculty CV template without breaking its formatting.

Verified facts this module relies on (see build brief -- do not "simplify"
these assumptions without re-checking the actual template XML):
  * Only "CURRICULUM VITAE" and "FULL NAME" use a real Word Heading1 style.
    All other 18 section titles are plain paragraphs with direct formatting
    (Calibri, bold, colour #E42313, red bottom border) -- so sections are
    located by exact heading TEXT, never by style name.
  * The letterhead (photo, name, job title, contact, email) lives in a
    single 1x2 table, not in body paragraphs.
  * There is no structural marker for the template's instructional/example
    text -- it is removed by replacing everything between one heading and
    the next with the approved content for that section.

This module edits document.xml as a string (paragraph-level regex, as the
docx-editing playbook recommends for existing files) rather than fully
reparsing with an XML tree, to avoid renumbering/namespace churn that could
invalidate the file.
"""
import re
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from PIL import Image

from config import SECTIONS, TEMPLATE_PATH
from formatting import (
    EDITORIAL_KIND_ORDER, EDITORIAL_SUBGROUP_LABELS, PUBLICATION_SUBGROUP_LABELS,
    format_item,
)

PARA_RE = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.DOTALL)
RUN_RE = re.compile(r"<w:r(?:\s[^>]*)?>.*?</w:r>", re.DOTALL)
TEXT_RE = re.compile(r"<w:t(?:\s[^>]*)?>([^<]*)</w:t>")
PPR_RE = re.compile(r"<w:pPr>.*?</w:pPr>", re.DOTALL)
RPR_RE = re.compile(r"<w:rPr>.*?</w:rPr>", re.DOTALL)
TC_RE = re.compile(r"<w:tc>.*?</w:tc>", re.DOTALL)

PHOTO_MEDIA_NAME = "word/media/profile_photo.png"
PHOTO_REL_ID = "rIdProfilePhoto"
EMU_PER_PIXEL_96DPI = 9525
PHOTO_MAX_WIDTH_EMU = 1_100_000   # ~1.2in, fits the letterhead's photo column
PHOTO_MAX_HEIGHT_EMU = 1_500_000  # ~1.64in


class GenerationError(Exception):
    """Raised with a message safe to show to an HR user."""


def _para_text(para_xml: str) -> str:
    return "".join(TEXT_RE.findall(para_xml)).strip()


def _para_ppr(para_xml: str) -> str:
    m = PPR_RE.search(para_xml)
    return m.group(0) if m else ""


def _first_content_run_rpr(para_xml: str) -> str:
    """rPr of the first run that actually contains text, so cloned content
    keeps the template's font/colour/size instead of the paragraph mark's."""
    for run in RUN_RE.findall(para_xml):
        if "<w:t" in run:
            m = RPR_RE.search(run)
            return m.group(0) if m else ""
    return ""


def _build_paragraph(ppr_xml: str, rpr_xml: str, text: str) -> str:
    escaped = xml_escape(text)
    run = f'<w:r>{rpr_xml}<w:t xml:space="preserve">{escaped}</w:t></w:r>'
    return f"<w:p>{ppr_xml}{run}</w:p>"


NUMPR_RE = re.compile(r"<w:numPr>.*?</w:numPr>", re.DOTALL)
IND_RE = re.compile(r"<w:ind\b[^>]*/>|<w:ind\b.*?</w:ind>", re.DOTALL)
CONTINUATION_INDENT_TWIPS = 720  # aligns under the bullet's text, not its glyph


def _continuation_ppr(ppr_xml: str) -> str:
    """Paragraph formatting for the follow-on lines of a multi-line item:
    the same font and spacing, but no bullet of its own, indented to sit
    under the text of the line above.

    A funded project is one entry made of four labelled facts. Giving each
    of those facts its own bullet turns nine projects into thirty-six
    free-floating points and destroys the grouping -- the reader can no
    longer see which Role and Funding Agency belong to which Project Title.
    """
    without_bullet = NUMPR_RE.sub("", ppr_xml)
    without_bullet = IND_RE.sub("", without_bullet)
    indent = f'<w:ind w:left="{CONTINUATION_INDENT_TWIPS}"/>'
    if "<w:pPr>" in without_bullet:
        return without_bullet.replace("<w:pPr>", f"<w:pPr>{indent}", 1)
    return f"<w:pPr>{indent}</w:pPr>"


def _replace_first_run_text(para_xml: str, new_text: str) -> str:
    """Rebuild a paragraph keeping its pPr and first content run's rPr, but
    with a single run containing new_text. Used for letterhead fields where
    the template paragraph is a single logical line (name/title/contact/email).
    """
    ppr = _para_ppr(para_xml)
    rpr = _first_content_run_rpr(para_xml)
    return _build_paragraph(ppr, rpr, new_text)


INSTRUCTIONAL_PARAGRAPH_PREFIX = "While not all academics may have information to provide"


def _strip_instructional_boilerplate(doc_xml: str) -> str:
    """Remove the template's own "how to fill this in" guidance paragraph
    (sits right after the CURRICULUM VITAE heading, meant for whoever is
    manually completing the template) from the machine-generated output --
    it is not part of anyone's actual CV and has no business appearing in a
    finished document handed to HR."""
    for para in PARA_RE.findall(doc_xml):
        if _para_text(para).startswith(INSTRUCTIONAL_PARAGRAPH_PREFIX):
            return doc_xml.replace(para, "", 1)
    return doc_xml


def populate(items_by_section: dict[str, list[dict]], photo_path: Path | None, output_path: Path) -> None:
    """items_by_section: section_key -> list of {"fields":..., "source_text":...}
    already filtered to APPROVED items only, in display order.
    """
    if not TEMPLATE_PATH.exists():
        raise GenerationError("The official MDX CV template is missing from the server. Contact an administrator.")

    working_path = output_path
    shutil.copy(TEMPLATE_PATH, working_path)

    with zipfile.ZipFile(working_path, "r") as zin:
        names = zin.namelist()
        contents = {n: zin.read(n) for n in names}

    doc_xml = contents["word/document.xml"].decode("utf-8")

    doc_xml = _strip_instructional_boilerplate(doc_xml)
    doc_xml = _populate_letterhead(doc_xml, items_by_section)
    doc_xml = _populate_sections(doc_xml, items_by_section)
    doc_xml = _append_plain_section(doc_xml, "skills", "SKILLS", items_by_section.get("skills", []))
    doc_xml = _append_plain_section(
        doc_xml, "language_proficiency", "LANGUAGE PROFICIENCY",
        items_by_section.get("language_proficiency", []),
    )
    # No UNMAPPED INFORMATION appendix in the generated document -- HR's
    # explicit instruction: a management-facing CV should never carry a
    # section whose heading doesn't correspond to something real. The
    # safety net this used to render still exists in the REVIEW screen
    # (unmapped.py's reconciliation is unchanged, and generation still
    # requires every item -- unmapped ones included -- to be explicitly
    # approved or rejected before "Generate" unlocks). What's removed is
    # only the appendix at the end of the finished document; nothing about
    # what the reviewer sees or can act on during review has changed.

    if photo_path and photo_path.exists():
        doc_xml, contents, names = _populate_photo(doc_xml, contents, names, photo_path)

    contents["word/document.xml"] = doc_xml.encode("utf-8")

    with zipfile.ZipFile(working_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name in names:
            zout.writestr(name, contents[name])

    _validate_output(working_path)


def _populate_letterhead(doc_xml: str, items_by_section: dict[str, list[dict]]) -> str:
    table_match = re.search(r"<w:tbl>.*?</w:tbl>", doc_xml, re.DOTALL)
    if not table_match:
        return doc_xml
    table_xml = table_match.group(0)

    full_name = _first_line(items_by_section.get("full_name"))
    job_title = _first_line(items_by_section.get("job_title"))
    contact = _first_line(items_by_section.get("contact_info"))
    email = _first_line(items_by_section.get("email"))

    paras = PARA_RE.findall(table_xml)
    new_table_xml = table_xml
    replacements_made = 0
    field_order = [full_name, job_title, contact, email]
    field_labels = ["", "Job title: ", "Contact: ", "Email: "]
    idx = 0
    for para in paras:
        text = _para_text(para)
        if text == "FULL NAME" and full_name:
            new_para = _replace_first_run_text(para, full_name)
            new_table_xml = new_table_xml.replace(para, new_para, 1)
            idx = 1
            continue
        # Each of these three fields replaces the template's own "how to
        # fill this in" placeholder text ("Job title: List each title
        # individually, with Professor...") whether or not a real value was
        # found -- clearing to a blank line when nothing was classified,
        # never leaving that guidance text in a document handed to HR. Only
        # the presence check moved; which value fills the line still comes
        # from the classifier exactly as before.
        if idx == 1 and text.lower().startswith("job title"):
            new_text = f"Job title: {job_title}" if job_title else ""
            new_para = _replace_first_run_text(para, new_text)
            new_table_xml = new_table_xml.replace(para, new_para, 1)
            idx = 2
            continue
        if idx == 2 and text.lower().startswith("contact"):
            new_text = f"Contact: {contact}" if contact else ""
            new_para = _replace_first_run_text(para, new_text)
            new_table_xml = new_table_xml.replace(para, new_para, 1)
            idx = 3
            continue
        if idx == 3 and text.lower().startswith("email"):
            new_text = f"Email: {email}" if email else ""
            new_para = _replace_first_run_text(para, new_text)
            new_table_xml = new_table_xml.replace(para, new_para, 1)
            idx = 4
            continue

    return doc_xml.replace(table_xml, new_table_xml, 1)


def _populate_photo(
    doc_xml: str, contents: dict[str, bytes], names: list[str], photo_path: Path
) -> tuple[str, dict[str, bytes], list[str]]:
    """Replace the letterhead's dashed 'PHOTO / Profile Photo' placeholder
    cell with an actual embedded image, sized to fit the column."""
    table_match = re.search(r"<w:tbl>.*?</w:tbl>", doc_xml, re.DOTALL)
    if not table_match:
        return doc_xml, contents, names
    table_xml = table_match.group(0)

    photo_cell = None
    for tc in TC_RE.findall(table_xml):
        if "<w:t>PHOTO</w:t>" in tc:
            photo_cell = tc
            break
    if photo_cell is None:
        return doc_xml, contents, names

    png_bytes = photo_path.read_bytes()
    with Image.open(photo_path) as img:
        width_px, height_px = img.size

    width_emu = width_px * EMU_PER_PIXEL_96DPI
    height_emu = height_px * EMU_PER_PIXEL_96DPI
    scale = min(PHOTO_MAX_WIDTH_EMU / width_emu, PHOTO_MAX_HEIGHT_EMU / height_emu, 1.0)
    cx, cy = int(width_emu * scale), int(height_emu * scale)

    drawing = (
        '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:rPr><w:noProof/></w:rPr>'
        '<w:drawing>'
        f'<wp:inline distT="0" distB="0" distL="0" distR="0">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        '<wp:docPr id="9001" name="ProfilePhoto"/>'
        '<wp:cNvGraphicFramePr>'
        '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
        '</wp:cNvGraphicFramePr>'
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:nvPicPr><pic:cNvPr id="9001" name="ProfilePhoto.png"/><pic:cNvPicPr/></pic:nvPicPr>'
        f'<pic:blipFill><a:blip r:embed="{PHOTO_REL_ID}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        '</pic:pic></a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>'
    )

    tcpr_match = re.search(r"<w:tcPr>.*?</w:tcPr>", photo_cell, re.DOTALL)
    tcpr_xml = tcpr_match.group(0) if tcpr_match else ""
    new_cell = f"<w:tc>{tcpr_xml}{drawing}</w:tc>"

    new_table_xml = table_xml.replace(photo_cell, new_cell, 1)
    doc_xml = doc_xml.replace(table_xml, new_table_xml, 1)

    contents = dict(contents)
    names = list(names)
    contents[PHOTO_MEDIA_NAME] = png_bytes
    if PHOTO_MEDIA_NAME not in names:
        names.append(PHOTO_MEDIA_NAME)

    rels_name = "word/_rels/document.xml.rels"
    rels_xml = contents[rels_name].decode("utf-8")
    new_rel = (
        f'<Relationship Id="{PHOTO_REL_ID}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/profile_photo.png"/>'
    )
    rels_xml = rels_xml.replace("</Relationships>", new_rel + "</Relationships>")
    contents[rels_name] = rels_xml.encode("utf-8")

    return doc_xml, contents, names


def _first_line(items: list[dict] | None) -> str:
    if not items:
        return ""
    it = items[0]
    fields = it.get("fields", {}) or {}
    return (fields.get("value") or "").strip() or it.get("source_text", "").strip()


HEADING_SECTIONS = [s for s in SECTIONS if s["heading_text"] and s["key"] not in ("full_name",)]


def _grouped_by_kind(items: list[dict]) -> list[dict]:
    """Reorder editorial-role items into EDITORIAL_KIND_ORDER, stable within
    each bucket. An item with no recognised kind keeps its verbatim text and
    is not lost -- it is simply appended after every recognised bucket, with
    no sub-heading of its own, rather than being dropped for not fitting."""
    buckets: dict[str, list[dict]] = {k: [] for k in EDITORIAL_KIND_ORDER}
    unclassified: list[dict] = []
    for it in items:
        kind = (it.get("fields") or {}).get("kind")
        (buckets[kind] if kind in buckets else unclassified).append(it)
    return [it for kind in EDITORIAL_KIND_ORDER for it in buckets[kind]] + unclassified


def _populate_sections(doc_xml: str, items_by_section: dict[str, list[dict]]) -> str:
    paras = PARA_RE.findall(doc_xml)
    heading_indices: dict[str, int] = {}
    for i, para in enumerate(paras):
        text = _para_text(para)
        for section in HEADING_SECTIONS:
            if text == section["heading_text"] and section["key"] not in heading_indices:
                heading_indices[section["key"]] = i

    ordered_keys = sorted(heading_indices, key=lambda k: heading_indices[k])

    for pos, key in enumerate(ordered_keys):
        start = heading_indices[key] + 1
        end = heading_indices[ordered_keys[pos + 1]] if pos + 1 < len(ordered_keys) else len(paras)
        body_paras = paras[start:end]
        if not body_paras:
            continue

        items = items_by_section.get(key, [])

        if not items:
            # A section with nothing approved is removed entirely, heading
            # included, rather than left showing "Information not
            # provided." HR's explicit instruction: a section whose title
            # doesn't match anything real in the source CV should not
            # appear in a document going to management at all. (An earlier
            # version of this tool showed the placeholder line instead, on
            # the reasoning that a visibly-empty section proves the gap was
            # checked rather than missed -- reversed here on direct
            # instruction, not by accident; see FIXLOG.md.)
            heading_para = paras[heading_indices[key]]
            old_block = heading_para + "".join(body_paras)
            doc_xml = doc_xml.replace(old_block, "", 1)
            continue

        template_para = body_paras[0]
        ppr = _para_ppr(template_para)
        rpr = _first_content_run_rpr(template_para)

        if key == "editorial_roles":
            # Unlike Publications, editorial items are NOT reliably contiguous
            # by kind in the source -- a CV commonly interleaves "Reviewer,
            # Journal A" and "Editorial Board Member, Journal B" in whatever
            # order it lists them. Printing a sub-heading only when the kind
            # changes would then print "Reviewer" / "Editorial Board Member" /
            # "Reviewer" again. Bucketing into a fixed order first (an editor,
            # then editorial board members, then reviewers, then examiners --
            # regardless of source order) gives one clean sub-heading per kind,
            # matching how Publications already groups journal vs. conference
            # entries.
            items = _grouped_by_kind(items)

        rendered: list[str] = []
        last_subgroup: str | None = None
        for it in items:
            fields = it.get("fields", {}) or {}

            # Publications arrive tagged with the sub-group they were listed
            # under in the source CV; reprinting that divider keeps journal
            # articles, media pieces and conference papers visually separated
            # instead of running them together as one undifferentiated list.
            # Editorial roles are grouped the same way, but by `kind` (an
            # editor vs. an editorial board member vs. a reviewer vs. an
            # examiner) rather than by a subgroup tag.
            subgroup_key = None
            subgroup_labels = None
            if key == "publications":
                subgroup_key, subgroup_labels = fields.get("subgroup"), PUBLICATION_SUBGROUP_LABELS
            elif key == "editorial_roles":
                subgroup_key, subgroup_labels = fields.get("kind"), EDITORIAL_SUBGROUP_LABELS

            if subgroup_key and subgroup_key != last_subgroup:
                label = subgroup_labels.get(subgroup_key) if subgroup_labels else None
                if label:
                    rendered.append(_build_paragraph(ppr, rpr, label))
                last_subgroup = subgroup_key

            line = format_item(key, fields, it.get("source_text", ""))
            # A formatter may return several labelled lines for one item
            # (funded projects do). Only the first carries the bullet; the
            # rest are indented continuations, so one entry reads as one
            # grouped block rather than as several unrelated bullets.
            parts = [p for p in line.split("\n") if p.strip()]
            for position, part in enumerate(parts):
                para_ppr = ppr if position == 0 else _continuation_ppr(ppr)
                rendered.append(_build_paragraph(para_ppr, rpr, part))

        new_paras_xml = "".join(rendered)

        old_block = "".join(body_paras)
        doc_xml = doc_xml.replace(old_block, new_paras_xml, 1)

    return doc_xml


SECTBREAK_RE = re.compile(r"<w:sectPr\b.*?</w:sectPr>|<w:sectPr\b[^>]*/>", re.DOTALL)


def _heading_and_body_style(doc_xml: str) -> tuple[str, str, str, str]:
    """(heading_ppr, heading_rpr, bullet_ppr, body_rpr) cloned from a real
    section heading already in the document, so anything appended after the
    template's own 20 sections inherits its formatting (Calibri bold, MDX
    red, bottom border) instead of being styled by hand -- which would drift
    the moment the template itself is updated."""
    paras = PARA_RE.findall(doc_xml)
    heading_template = body_template = None
    for i, para in enumerate(paras):
        text = _para_text(para)
        if any(text == s["heading_text"] for s in HEADING_SECTIONS):
            heading_template = para
            if i + 1 < len(paras):
                body_template = paras[i + 1]
            break
    if heading_template is None:
        return "", "", "", ""
    return (
        _para_ppr(heading_template),
        _first_content_run_rpr(heading_template),
        _para_ppr(body_template) if body_template else "",
        _first_content_run_rpr(body_template) if body_template else "",
    )


def _insert_before_final_sectpr(doc_xml: str, new_xml: str) -> str:
    """Insert appended content immediately before the document's final
    sectPr, which carries page setup for the last section and must stay
    last in the body."""
    body_close = doc_xml.rfind("</w:body>")
    if body_close == -1:
        return doc_xml
    tail = doc_xml[:body_close]
    sect_match = None
    for sect_match in SECTBREAK_RE.finditer(tail):
        pass
    insert_at = sect_match.start() if sect_match else body_close
    return doc_xml[:insert_at] + new_xml + doc_xml[insert_at:]


def _append_plain_section(doc_xml: str, section_key: str, heading_text: str, items: list[dict]) -> str:
    """Append a simple, flatly-bulleted section (Skills, Language
    Proficiency) at the end of the document, present only when there is
    content for it -- the same "never show an empty appendix" rule the
    UNMAPPED INFORMATION note follows.

    Unlike the 20 official sections, these have no template paragraph of
    their own to populate; they are new headings this tool writes in,
    because HR asked that this specific, common CV content read as its own
    labelled section rather than being folded into the generic unmapped
    note.
    """
    if not items:
        return doc_xml
    heading_ppr, heading_rpr, bullet_ppr, body_rpr = _heading_and_body_style(doc_xml)
    if not heading_ppr:
        return doc_xml

    blocks = [_build_paragraph(heading_ppr, heading_rpr, heading_text)]
    for item in items:
        fields = item.get("fields", {}) or {}
        line = format_item(section_key, fields, item.get("source_text", ""))
        if line.strip():
            blocks.append(_build_paragraph(bullet_ppr, body_rpr, line.strip()))

    return _insert_before_final_sectpr(doc_xml, "".join(blocks))


def _validate_output(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as z:
            bad = z.testzip()
            if bad:
                raise GenerationError(f"Generated file is corrupted (bad entry: {bad}).")
            if "word/document.xml" not in z.namelist():
                raise GenerationError("Generated file is missing its main document part.")
    except zipfile.BadZipFile as exc:
        raise GenerationError("Generated file failed integrity validation.") from exc
