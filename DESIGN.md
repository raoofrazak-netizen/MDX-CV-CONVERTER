---
name: MDX Faculty CV Converter
description: A registrar's tool for turning any staff CV into the official Middlesex University Dubai Faculty CV record.
colors:
  primary: "#E30613"
  primary-deep: "#B8050F"
  neutral-ink: "#1A1A1A"
  neutral-grey-light: "#E5E3E0"
  bg: "#FAFAF9"
  surface: "#FFFFFF"
  border: "#DEDCD8"
  text: "#1A1A1A"
  text-soft: "#5C5955"
  good: "#1E7A3E"
  good-bg: "#E7F5EC"
  warn: "#9A6B00"
  warn-bg: "#FDF2DA"
  bad: "#B8050F"
  bad-bg: "#FBE7E8"
  edited: "#1E5A9A"
  edited-bg: "#E5EEF9"
typography:
  body:
    fontFamily: "Arial, 'Helvetica Neue', Helvetica, sans-serif"
    fontSize: "0.9rem"
    fontWeight: 400
    lineHeight: 1.5
  title:
    fontFamily: "Arial, 'Helvetica Neue', Helvetica, sans-serif"
    fontSize: "1.6rem"
    fontWeight: 700
    lineHeight: 1.2
  label:
    fontFamily: "Arial, 'Helvetica Neue', Helvetica, sans-serif"
    fontSize: "0.78rem"
    fontWeight: 700
    letterSpacing: "0.03em"
rounded:
  sm: "4px"
  md: "6px"
  lg: "8px"
  pill: "20px"
spacing:
  xs: "0.3rem"
  sm: "0.6rem"
  md: "1rem"
  lg: "1.6rem"
  xl: "2.6rem"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#FFFFFF"
    rounded: "{rounded.md}"
    padding: "0.55rem 1.1rem"
  button-primary-hover:
    backgroundColor: "{colors.primary-deep}"
  button-secondary:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.text}"
    rounded: "{rounded.md}"
    padding: "0.55rem 1.1rem"
  button-danger:
    backgroundColor: "#FFFFFF"
    textColor: "{colors.bad}"
    rounded: "{rounded.md}"
    padding: "0.55rem 1.1rem"
  pill-verified:
    backgroundColor: "{colors.good-bg}"
    textColor: "{colors.good}"
    rounded: "{rounded.pill}"
    padding: "0.18rem 0.55rem"
  pill-needs-review:
    backgroundColor: "{colors.warn-bg}"
    textColor: "{colors.warn}"
    rounded: "{rounded.pill}"
    padding: "0.18rem 0.55rem"
  pill-missing:
    backgroundColor: "{colors.bad-bg}"
    textColor: "{colors.bad}"
    rounded: "{rounded.pill}"
    padding: "0.18rem 0.55rem"
  card:
    backgroundColor: "{colors.surface}"
    rounded: "{rounded.lg}"
    padding: "1.4rem 1.6rem"
---

# Design System: MDX Faculty CV Converter

## Overview

**Creative North Star: "The Registrar's Ledger"**

This is an internal tool for turning someone else's CV into an official university record — not a product being sold, not a brand being expressed. Every visual decision already in the code serves legibility and trust over personality: a single utilitarian sans-serif throughout, no shadows anywhere, containment done with 1px borders instead of elevation, and one saturated color — Middlesex University's own red — held in reserve for the handful of moments that are actually decisions (primary actions, live focus, the currently-reviewed item, error states). The palette otherwise stays in warm paper neutrals, and status is read through color+shape (pill badges), never decoration.

Nothing here should read as designed for its own sake. The Registrar's Ledger commits to institutional plainness as an aesthetic choice, not an absence of one: red means "this is the one true action or the one real problem on this screen," borders mean "this is a distinct record," and a pill means "this is this item's status, stated once, unambiguously."

**Key Characteristics:**
- One accent color, spent deliberately, never decoratively.
- Flat by default — no shadows anywhere in the incumbent system.
- Status is communicated through color-coded pills, consistently, everywhere it appears.
- A single utilitarian type family; hierarchy comes from size and weight, not font choice.

## Colors

Warm paper neutrals carrying almost the whole interface, with the university's own red held back for the moments that are actually decisions.

### Primary
- **Institutional Red** (`#E30613`): Middlesex University Dubai's own brand red. Links, primary buttons, the active progress step, focus rings on the command bar and the item currently under keyboard review. Used for interactive/active state, never for decoration or backgrounds of passive content.
- **Institutional Red, Deep** (`#B8050F`): the hover state for primary actions. Identical value to Bad/Error red below — the system doesn't distinguish "a pressed action" from "a real problem" by hue, only by context, which is a real, observed choice worth preserving rather than "fixing" into two different reds.

### Neutral
- **Paper** (`#FAFAF9`): page background, section headers, the source-text preview pane's background.
- **Card White** (`#FFFFFF`): cards, the source pane, secondary buttons.
- **Soft Line** (`#DEDCD8`): every border in the system — cards, tables, inputs, dropzone, section dividers. The system's only containment device; it has no shadow vocabulary.
- **Ink** (`#1A1A1A`): primary text, and the top bar's background (the one place ink inverts to become a surface).
- **Soft Ink** (`#5C5955`): secondary/muted text — labels, helper copy, timestamps, table headers.
- **Pale Grey** (`#E5E3E0`): disabled button fill, keyboard-shortcut key caps, placeholder photo background, and the neutral/inactive family of status pills (generated, processing, uploaded).

### Named Rules
**The One Red Rule.** Institutional Red appears only on the interactive/active/erroneous elements of a screen — never as a background, a decorative accent, or a passive label color. If red shows up somewhere, it's telling the reviewer to look or act.

## Typography

**Body Font:** Arial, "Helvetica Neue", Helvetica, sans-serif
**Character:** One utilitarian sans stack for the entire interface — headings, body, labels, even the command bar. Hierarchy is built entirely from size, weight, and the deliberate uppercase+letterspaced treatment on labels, not from a second typeface.

### Hierarchy
- **Title** (700, 1.6rem, 1.2 line-height): page-level `h1`. Appears once per screen.
- **Headline** (default bold, 1.2rem): `h2`, section-level headings within a page.
- **Body** (400, 0.9–0.92rem, 1.5 line-height): the default reading size for everything — item text, table cells, buttons, form fields.
- **Label** (700, 0.72–0.85rem, 0.03em letter-spacing, uppercase where used): table headers, pills, flags, and the audit log's key-cap styling. Small, loud, and always uppercase when it's naming a category rather than showing content.

### Named Rules
**The One Typeface Rule.** No second font family is introduced anywhere, including for numbers, code-like content (the item IDs in the footer), or emphasis. Weight and size carry all hierarchy.

## Layout

A single centered column (`max-width: 1080px`) for most screens; the review screen breaks into a two-pane workspace (source CV on the left, ~38% width with a collapse toggle; the review flow on the right, flexible width), collapsing to a single stacked column below 1000px. Spacing is loose and rem-based rather than a strict formal scale, but recurring steps cluster around 0.3rem / 0.6rem / 1rem / 1.6rem / 2.6rem — tight gaps inside a control, generous gaps between page-level blocks. The source pane is sticky-positioned so the original CV stays visible while the reviewer scrolls the classified items beside it.

## Elevation & Depth

Flat. There is no shadow vocabulary anywhere in the incumbent system — every surface (card, pane, banner, dropdown) sits at the same visual depth as its neighbors, and separation is done entirely with a 1px border in Soft Line. This reads as a deliberate choice for a records tool: nothing floats above anything else because nothing here is meant to feel more or less authoritative than anything else on the page.

### Named Rules
**The No-Shadow Rule.** Depth is never simulated. A border marks a boundary; nothing is ever lifted, layered, or given a drop shadow to imply hierarchy.

## Shapes

Two radii do all the work: 6px on interactive controls (buttons, inputs, textareas) and 8px on containers (cards, section blocks, banners, the photo preview). Status pills break from both and go fully round (20px, i.e. pill-shaped) — the one place the system uses a distinct silhouette, reserved entirely for status communication. Corners are otherwise soft but restrained; nothing is sharp-cornered or fully rounded except that one status-pill exception.

## Components

Plain and trustworthy: every component reads as exactly what it is, with no ornamentation beyond what states require.

### Buttons
- **Shape:** 6px radius, 1px transparent border by default.
- **Primary:** Institutional Red background, white text, 0.55rem/1.1rem padding. The one loud control per screen.
- **Hover / Focus:** primary darkens to Institutional Red Deep; disabled states fall back to Pale Grey background with Soft Ink text and a not-allowed cursor.
- **Secondary:** white background, Ink text, Soft Line border — used for every non-primary action.
- **Danger:** white background, Bad-red text and border; only darkens to a light red wash (Bad-bg) on hover, never fills solid. Destructive actions stay visually quiet until touched.

### Pills (status badges)
- **Style:** fully rounded (20px), bold uppercase label text at 0.72rem, no border.
- **State families:** good (approved/verified/high), warn (needs-review/pending), bad (rejected/failed/low/missing), edited (a distinct blue, `#1E5A9A` on `#E5EEF9` — the only status family that isn't red/amber/green, because "a human changed this" is a different kind of fact than a confidence level), and neutral (generated/processing/uploaded, in Pale Grey). This is the system's primary way of communicating state anywhere a status exists.

### Cards / Containers
- **Corner Style:** 8px.
- **Background:** Card White on Paper page background.
- **Shadow Strategy:** none — see Elevation & Depth.
- **Border:** 1px Soft Line, always.
- **Internal Padding:** 1.4rem vertical / 1.6rem horizontal.

### Inputs / Fields
- **Style:** 1px Soft Line border, 6px radius, white/inherited background.
- **Focus:** the command-bar input and any item under active keyboard review get a 2px Institutional Red outline — the system's only focus treatment, applied consistently rather than varying per component.

### Navigation
- **Style:** dark Ink top bar, white text at reduced opacity (0.85) that goes fully opaque and underlines on hover. No dropdowns or nested navigation currently exist.

### Source-Pane Split View (signature component)
The review screen's defining structural device: the original CV (rendered or extracted text) pinned in a sticky, collapsible left pane while the classified items scroll independently on the right. This is the component that makes "verify before you trust it" physically possible on screen, and it's the most distinctive thing in the system — any new full-page surface in this app should consider whether it needs the same "evidence beside decision" layout rather than defaulting to a single column.

## Do's and Don'ts

### Do:
- **Do** keep Institutional Red reserved for actionable/active/erroneous elements only (The One Red Rule).
- **Do** use a 1px Soft Line border for every container boundary; never introduce a shadow (The No-Shadow Rule).
- **Do** use the pill component for any new status concept, joining the existing good/warn/bad/edited/neutral family rather than inventing a new visual pattern.
- **Do** keep the source-pane split-view pattern for any future screen where a reviewer needs to verify a decision against original evidence.

### Don't:
- **Don't** introduce a second typeface or a display/serif font anywhere — hierarchy comes from size and weight only (The One Typeface Rule).
- **Don't** add drop shadows, glows, or elevation layering to imply importance — use a border, or size/weight, instead.
- **Don't** use Institutional Red for decoration, large fills, or passive/informational content — it must always mean "act here" or "problem here."
- **Don't** invent a sharp-cornered or fully-square component; the system's only hard-edged shapes are the pills' complete opposite (full round) and everything else stays softly rounded.
