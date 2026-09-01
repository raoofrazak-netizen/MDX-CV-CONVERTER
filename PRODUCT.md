# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

HR staff at Middlesex University Dubai who process incoming faculty CVs. A
reviewer uploads a staff member's own CV (any format/layout) and works
through a review screen before a final document is produced — they are not
the CV's author, they are the person turning it into the university's
official record.

## Product Purpose

Converts a staff member's own CV (PDF or DOCX, arbitrary layout) into the
official MDX Faculty CV Word template. Success is a generated document that
matches the template's structure exactly and contains nothing the source CV
didn't actually say, with a mandatory human review step between automatic
classification and the final file.

## Positioning

Runs entirely offline: deterministic, rule-based text classification
(`rule_classifier.py`), no AI API key or internet connection required.
Classification matches section headings against the official template's own
heading text plus ~90 known synonyms, then re-files misheaded content by
what it actually says. An optional AI upgrade (Claude, via `ANTHROPIC_API_KEY`)
can be enabled for freeform/unlabelled CVs, but the product's core claim is
that it works without one. Every extracted fact is a verbatim quote from the
source CV — nothing that cannot be found as an exact substring survives
server-side validation. The two exceptions (a saved staff profile and an
auto-drafted biography fallback) are always labelled with their own
provenance and never presented as if they came from the CV.

## Operating Context

Upload → extract text + photo → classify into 20 MDX sections → re-route
misfiled content by meaning → validate → auto-approve high-confidence items
→ draft biography if needed → apply saved staff profile → HR review →
generate DOCX → download.

Runs locally via `uvicorn`, accessed through a browser at localhost — no
deployment target beyond that is planned currently. A reviewer works
primarily from the review screen: approving, editing, or rejecting
classified items, with a live quality report surfacing low-confidence or
suspicious content before generation is allowed.

## Capabilities and Constraints

- Accepts DOCX and PDF only, up to 25MB; scanned/image-only PDFs are not
  supported (no OCR).
- Classification is rule-based and deterministic by default; an optional
  Claude-backed path exists for harder freeform CVs.
- A document can never be generated until every item is approved, edited,
  or rejected — the review step is not skippable.
- Confidence-banded auto-approval, with the threshold configurable per
  deployment; a CV already in review is unaffected by a later threshold
  change.
- HR can teach the classifier new heading synonyms from the review screen,
  effective for every CV uploaded afterward.
- Batch upload and saved staff profiles (pre-fill from a previous
  submission) are supported.
- Full audit log per CV (extraction, classification, approval, generation
  events).
- Deployment target: local only, for now.
- Accessibility: no specific standard established yet.

## Brand Commitments

Generated documents must exactly match Middlesex University Dubai's
official MDX Faculty CV Word template — its structure, section headings,
and branding are not negotiable design surface for this product; they are
the deliverable's contract.

## Evidence on Hand

The official template file lives in the project root
(`MDX_Faculty_CV_Template July 2026.docx`). No fabricated testimonials,
customers, or benchmarks — none exist and none should be invented.

## Product Principles

- Never show HR a fact the source CV didn't actually contain — the
  verbatim-quote guard is not negotiable.
- A human always reviews before a document is generated; automation earns
  trust by being auditable, not by being invisible.
- Work without external dependencies by default; treat the AI path as an
  upgrade, never a requirement.
- When classification is uncertain, surface the uncertainty (confidence
  bands, quality report, unmapped-content notes) rather than guessing
  silently.

## Accessibility & Inclusion

No product-specific requirement established yet.
