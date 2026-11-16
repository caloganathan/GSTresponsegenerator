# CLAUDE.md — working notes for the Compliance Panel and the general council

What a future session needs before it changes anything here: why each part is built the way it is, and which of the invariants were learned the hard way.

## Compliance Panel (GST) — the primary product

A second mode alongside the generic council, for Indian GST notice work.

### THE ONE THING TO UNDERSTAND FIRST: a notice is N defects, not one dispute

A GST notice is a parameter-wise list of defects, and the department raises and
disposes of them **one at a time**. In the matter this product was rebuilt
against — a Tamil Nadu ASMT-10 attachment for a GSTR-9C filer — the
adjudication order says *"Hence this defect is dropped"* eight separate times.
Seven of eight limbs were dropped; the eighth went to a show cause notice.

Everything in the architecture below follows from that. `defects.py` holds the
unit of work; the panel argues only the limbs that turn on law; the export
assembles the reply limb by limb. The first version of this product modelled a
notice as one dispute with one amount and one confidence rating, and every
defect in its output traced back to that single modelling error.

**Why the eighth limb was lost matters more than why seven were won.** The
officer's own findings record it: the taxpayer argued the e-invoicing mandate
date correctly and was understood, but had *"not provided first e-invoice for
the month of august 2023 for verification."* A correct legal position lost a
limb because one system report was not attached. That is why `evidence_gap` is
a first-class output, why `gst_defects.py` names the artefact rather than the
category, and why `evidence_gap_catch` is the number to watch in the evals.

### Architecture

- **`defects.py`** — the defect record, the five postures, triage and validation. Also `residuary_defect()`, for the notice that does not segment, and `client_response`, the one input no notice and no model can supply — see the two sections on both below. Postures are not a severity scale; they are the five different things a reply can say about a limb, each producing different drafting. `explained` / `contested` / `agreed_paid` / `paid_under_protest` / `partial`, with `undecided` as the honest default. Only `contested`, `partial` and `undecided` convene counsel.
- **`notice_tables.py`** — reads head-wise figures off the department's annexure using the checksum the table carries for free: four component amounts that sum to their own printed total. A run that fails its own arithmetic is discarded. **Returns None rather than a guess** — a blank the reviewer can see is safe, a wrong figure they cannot see is not.
- **`domains/gst_defects.py`** — the defect catalogue: heading patterns, provisions engaged, default posture, the evidence list, and the questions an officer puts on that limb at the hearing. **The evidence lists are the product.** Each entry names the artefact an officer asks for before dropping that limb. On the patterns, see "Catalogue patterns are load-bearing" below.
- **`ocr.py`** — optional local OCR for scanned notices, behind `available()`. Cloud OCR is refused on principle: a page image cannot be anonymised before upload, so it would break the draft tier's guarantee. Provenance travels with the text — an OCR-read field carries an `-ocr` source and is shown in the must-confirm state.
- **`calculators.py`** — s.50 interest, the 73/74 penalty stages with their concession deadlines, s.107/112 pre-deposit, appeal limitation, s.128A eligibility. **Python, never a prompt**, for the same reason the reconciliation buckets are: it is arithmetic with a statutory rule attached, and every figure carries its own working so it can be checked line by line. Internal document only — a penalty computation shown to the officer volunteers an admission nobody asked for.
- **`deadlines.py`** — days remaining, urgency bands, worst-first sort, iCalendar export. A missed reply date is the single largest source of avoidable loss in SME practice: it turns a reply into an appeal with a 10% pre-deposit.
- **`pricing.py`** — run cost in rupees, estimated from the firm's OWN completed matters rather than a model price table. A table keyed to model IDs goes stale silently, which is the failure this codebase has already been through once.
- **`domains/gst_authorities.py`** — curated authorities indexed by defect type. See "On case citations" below.
- **`roles.py`** — the four adversarial counsel + chairman. Organised by ROLE IN THE ARGUMENT (Revenue's Advocate / Assessee's Advocate / Procedural / Risk & Ethics), NOT by statute. This is deliberate: a notice concerns one law, so law-specialist panels emit three empty opinions. **These prompts are the product**; everything else is plumbing.
- **`domains/gst.py`** — domain pack. Stable anchors: sections, the full notice-form registry, procedural doctrines, State→High Court map.
- **`panel.py`** — 5 stages: grounding → parallel openings → cross-examination → chairman JSON → citation verification. `merge_determination()` folds the chairman's per-defect answer onto the defects read from the notice; **the notice stays authoritative on heading, numbering and figures**, the chairman only on what we say about them.
- **`verification.py`** — extracts authorities from every defect's list AND from filed text (a citation reaching the reply but not the list is the dangerous one). Each carries its `defect_index`. **Never silently upgrades**: checker failure, unparseable output, or panel-flagged `certainty: to_verify` all resolve to UNVERIFIED.
- **`sanitizer.py`** — draft-tier anonymisation. `IDENTIFIER_RULES` order matters: GSTIN before PAN, or the embedded PAN leaks as a fragment. `audit_leaks()` runs as a pre-flight assertion and the panel ABORTS if anything survives.
- **`users.py` / `auth.py`** — partner/manager/staff with PBKDF2 + session tokens. Legacy `APP_ACCESS_TOKEN` still works and maps to partner. `redact_for_role` strips `analyses`/`cross_exams` for staff.
- **`export.py`** — **two documents, never one.** See below.
- **`reconciliation.py`** — 2A/2B vs 3B workbook ingestion. Parses xlsx/csv/docx/pdf, detects columns by alias, classifies each row into a `RECONCILIATION_BUCKETS` entry, aggregates by bucket.

### export.py produces TWO documents and they must never merge

`build_filing_reply()` goes to the proper officer, on the **client's**
letterhead over its authorised signatory, in the A-to-O framework — cause
title, Disputes at a Glance, issue-wise reply, consolidated payments,
evidentiary index, prayer with one relief per defect, signature block.

`build_file_note()` stays in the office and carries everything the other must
not: postures and why, filing blockers, evidence gaps, exposure, unverified
authorities, panel disagreements, board summary. Stamped
**INTERNAL — NOT FOR SUBMISSION** on every page.

This split exists because a single combined pack was produced and read by a
practising partner. Its "Points for Reviewer Attention" section carried *"worst
realistic monetary exposure … approx. Rs. 2.02 lakh"* and its file note
recorded that the firm's confidence was *"defensible, not strong, because … the
team has not yet verified line-by-line"* — in the same file as the text
intended for the department. `TestTheWallBetweenDocuments` asserts every class
of that leak from both sides. Do not merge these builders.

Related: the chairman prompt used to forbid a signature block ("the firm
supplies those"). It should not have to. That single instruction is why every
exported document needed manual surgery before it could be filed.

### On case citations — a documented rule that was reversed

`domains/gst.py` used to carry "never hardcode case citations", on the
reasoning that case law is volatile and mis-citing it is the core professional
risk. The reasoning holds; the conclusion did not. A panel told to generate its
own authorities, with a verifier that downgrades anything doubtful, produced a
reply carrying nine authorities of which eight were bare statutory sections and
one was an off-point case marked *to be confirmed*. A reply with no law is not
the safe outcome, only a worse one.

The rule that replaced it, enforced in `export.py`:

1. The curated library is a starting point, never an output.
2. Every entry is verified against live sources on every run, exactly as a
   model-generated citation is.
3. **An authority that does not come back VERIFIED never reaches the filing
   document.** It goes to the file note with a confirm-before-filing flag.

`_is_filable()` gates this. If verification did not run at all the index is
empty and nothing is filable — the correct failure direction.

### Reconciliations arrive in whatever the client's accountant had to hand

xlsx and csv only meant re-keying thousands of rows before the panel could see
any figures — which meant, in practice, that it did not see them. `.docx` is
read for its tables (real structure, so exact; the WIDEST table is taken and
the rest reported, because a Word export usually carries a summary beside the
detail and stacking the two double-counts every bucket). `.pdf` is split on
runs of two or more spaces and then **checks its own work** — the rows must
agree on a column count, and one that cannot produce a consistent grid raises
and names the formats that will work.

A scanned reconciliation is refused outright. OCR is offered for notices
because a misread word in a notice is visible to the reviewer reading it; a
misread digit in row 4,000 of a reconciliation is not, and a bucket total
computed from a misaligned grid arrives looking exactly like a correct one.

### The reconciliation rows never reach a model
A real 2A/3B reconciliation is thousands of invoice lines — roughly 500k tokens, and third-party supplier data the client has no business disclosing. Bucketing is deterministic arithmetic, so it happens in Python. Only `reconciliation_brief()` (a ~200–700 token aggregate: bucket, count, amount, share, legal position) is put in front of the panel. Do not "improve" this by passing rows to a model. `tests/test_reconciliation.py::TestBriefing` asserts both halves: no invoice-level data travels, and briefing size is independent of row count.

Each bucket carries its own legal position and strength — `strong` (RCM/import IGST/ISD, excluded at the threshold; timing), `defensible` (amendment, supplier error, clerical), `weak` (non-filer — the s.16(2)(c) exposure), `concede` (ineligible). `UNRECONCILED` is named so it cannot be read as benign. Supplier GSTINs are masked on the anonymising tier.

### Stage 2 is cross-examination, NOT ranking
The generic council ranks because every model answers the same question. Panel counsel answer *different* questions, so ranking is meaningless. Do not reintroduce it here.

### Triage: most limbs do not need a panel
On the reference eight-defect notice, six limbs are answered by reconciliation,
documents or a payment and two turn on law. Convening four counsel on all eight
produces prose where a table was wanted and pays four models to write it.
`defects.triage()` splits them; the role prompts tell counsel where their effort
belongs. **Conceding a limb is a positive recommendation**, not a failure — the
prompts say so explicitly, because on the reference matter three limbs were
correctly conceded and paid, and that is what made the contested limbs credible.

### Two tiers = risk tiers
`draft` forces anonymisation and watermarks every exported page; `pro` sends
full facts with ZDR routing (`provider: {"data_collection": "deny"}`).
Identifiers are restored locally after the run so the partner reads real names
the model never saw.

There was a `free` tier on OpenRouter's `:free` endpoints. Every ID in it went
stale and the tier failed silently in production — **including notice reading**,
because `intake.extract_fields_assisted` borrows the tier's grounding model.
One root cause, two symptoms that looked unrelated. `TIER_ALIASES` maps stored
`tier="free"` matters to `draft`, never falling through to `pro`, which would
send real identifiers on a re-run of work the user chose to anonymise.

### Adding the Income Tax pack
New file in `domains/` with the same interface (including `DEFECT_TYPES` and
the authorities helpers), registered in `domains/__init__.py`. No change to
`panel.py`, `roles.py`, `verification.py`, `export.py` or the UI.

### A notice that does not segment still has to produce a limb

`segment()` returns `[]` when it finds nothing defect-shaped, and its docstring
has always said the caller must read that as *"this notice needs manual
decomposition"* rather than *"this notice has no defects"*. No caller did.

The consequence was total and silent, because **every defect-wise section of
both documents is gated on the defect list**. A Tamil Nadu ASMT-10 whose
annexure was a head-wise summary with no parameter-wise list produced a filing
reply consisting of a cause title, a particulars table, two paragraphs of
boilerplate and a prayer for a hearing — sections B, C, D and E simply absent —
over a file note missing its Defect Register and its hearing brief, which
reported **"No structural blockers were identified"**, because
`validate_all([])` was `[]`.

Nothing on the face of either document said so. It read as a short reply, not
as a reply to nothing.

Three rules now hold that shut, and all three matter because a single-issue
notice is perfectly ordinary and must not fail the run:

1. `intake.extract_defects` falls back to `defects.residuary_defect()` — ONE
   undecided limb carrying the operative region, `needs_decomposition=True`.
   The reviewer confirms it answers the single discrepancy, or splits it.
2. `validate_all([])` returns a blocker rather than `[]`. An empty list is the
   most dangerous possible clean bill of health: it is returned precisely when
   the reply is emptiest.
3. `build_filing_reply` stamps `NO_DEFECTS_STAMP` on every page and prints
   "NO LIMB OF THE NOTICE HAS BEEN ANSWERED" where section C would be.

### The client's factual response is an input, not an output

`facts` is the Noticee's account of what it did, filed over the Noticee's own
signature. Nothing in the notice contains it and no model can derive it — and
a model asked for facts it has not been given writes plausible ones.

For a long time there was no field for it anywhere in the codebase. The
chairman prompt asked for "the factual answer to this limb" and the panel
answered from the department's allegation.

`defects.client_response` (with `client_documents_held`) is now a first-class
per-defect input, collected in the defect review UI, rendered to counsel and
the chairman as **"THE CLIENT SAYS"**, and scrubbed on the draft tier like
every other free text — it is the most identifying prose in the matter,
because it names the trade name and the suppliers in the ordinary course of
explaining what happened.

Where it is absent the chairman is told, in terms, to leave `facts` empty and
fill `client_input_required` instead. `export._client_input_missing` then
prints the gap where the facts would have gone and stamps the page. A limb
that is `agreed_paid` or `paid_under_protest` is exempt — its DRC-03 reference
is the answer to it and it states no factual case. Keep
`_client_input_missing` and the `clientInputMissing` badge in `DefectList.jsx`
in step.

### A limb answered with its neighbour's answer

A model working through eight limbs in one response drifts into answering the
later ones by restating the earlier ones. It reads fluently and it is wrong in
the most expensive way available: limb N is answered on limb N-1's facts, so
the officer is told the wrong thing about a discrepancy that was never
addressed, and confirms it.

`panel._strip_copied_limbs` **removes** the copied prose rather than
annotating it, and records `duplicate_of`. A reviewer scanning a forty-page
reply will not notice that two paragraphs match; they will notice a limb with
its factual position missing and a blocker naming it. The failure has to be
louder than the text it replaces.

Only exact matches on normalised prose over 120 characters count. Two limbs of
the same defect type legitimately share phrasing, and a false positive costs a
limb exactly as a false negative does.

### The chairman gets a second attempt

The chairman is the only stage whose failure empties the entire deliverable —
the counsel analyses survive it, but every defect-wise section of both
documents is built from its JSON.

Its commonest failure does not look like a failure. A nine-limb determination
is a long JSON object, and a model that runs out of room mid-object returns a
perfectly good answer with the closing braces missing. That arrived
indistinguishable from a model that could not do the job, and both went
straight to `_fallback_determination`.

`ask_model` now returns `finish_reason`. On `length`, the chairman is retried
at double the ceiling; on any other parse failure it is asked once more for the
object alone. Only then does it degrade — and the degraded message names
`MAX_TOKENS_CHAIRMAN`, so the operator knows which knob to turn. Unanswered
limbs are now a filing blocker as well as a risk flag: risk flags are read as
things to weigh, and this is a thing to fix.

### Catalogue patterns are load-bearing, and they fail in both directions

A limb that does not segment is never answered, and an unanswered limb is
confirmed unopposed. A pattern that matches too much invents a limb and hands
it a neighbour's figures. Both have happened, and the golden set exists mainly
to catch them:

- `e[\s-]?invoic` with no leading `\b` matched the ordinary phrase **"the
  invoice"**, so nearly every notice grew a phantom e-invoicing limb.
- A bare `refund` matched the s.73 boilerplate *"tax not paid or short paid or
  erroneously refunded"*, so every s.73 demand grew a refund limb.
- A bare `interest under section 50` matched the demand boilerplate carried by
  almost every notice. **Do not add it back.**
- Conversely, `excess ITC availed` required those words adjacent, so the
  department's own standard wording — *"Input tax credit availed in excess of
  that appearing in GSTR-2B"*, the most common defect in Indian GST practice —
  matched nothing at all.

Rule of thumb: a pattern must match **heading language**, not statutory prose
that appears in every notice. Add one, then run
`uv run pytest tests/test_golden_set.py`.

Heading detection has three signals in priority order — the department's own
`Defect -N` numbering, bulleted parameter headings, then plain numbered
headings (`1.`, `2.`) where the heading text ALSO matches the catalogue. The
last resort is a loose catalogue scan that can only ever produce **one limb per
defect type**, which is why the numbered signal matters: an RFD-08 objecting to
a refund on two grounds came back as one limb with both figures.

### Gotchas
1. `_extract_json` handles fenced/prose-wrapped chairman output; failure produces `_fallback_determination` with a "must not be filed" risk flag — never a silent empty result.
2. Matters live in `data/matters/`, conversations in `data/conversations/`. Both atomic-write.
3. Model IDs churn on OpenRouter. Startup validation reports stale IDs — check `/api/health` and the Admin > Panel configuration tab first when a tier silently fails.
4. The sanitizer leak test is sacred. A failure there is a confidentiality breach, not a bug.
5. **Departmental PDFs do not emit in reading order.** The first limb's table is extracted ABOVE its own bullet heading, which is why `segment()` gives the FIRST defect a `preamble` and only the first — so no later limb can be handed a figure belonging to its neighbour.
6. **Bound the last defect.** Without `ANNEXURE_BOUNDARY_RE` the final limb absorbs every annexure in the document; a Rs. 44 interest limb once read Rs. 1.24 crore. **`operative_region()` must scan every candidate boundary, not just the first.** One of the patterns is the repeated `GSTIN : … Name : …` block heading an annexure — which is also the shape of the notice's OWN header, printed in the first few lines. Testing only the first match found the header at ~1%, declined to trim on the "would gut the document" guard, and returned the whole notice, so the real boundary below was never reached and the bound silently did nothing on any notice with a standard portal header. The whole path had no test; it has four now, in `TestTheAnnexureBoundary`.
7. Extraction that cannot read a figure must report it unread. `amount_unread` surfaces in the UI as an empty field to fill. Never fill it with a zero — not in the UI, not in either exported document, not in the matter total. An unread limb is a filing blocker, and the filing document quotes the department's own declared total rather than our short sum.
8. **The scrub covers the defect text, and the leak probe is the rendered prompt.** `sanitize_matter` scrubs `defects[*]` headings and contentions — the notice's own prose, where the GSTIN and trade name actually live — and `run_panel_stream` audits `format_matter()` output rather than a hand-listed field subset. A probe narrower than the prompt cannot see the leak it exists to catch.
9. **An unknown tier resolves to `draft`, never to the default.** `pro` is the non-anonymising tier, so a typo or a stale stored value must never land there (`config.FAILSAFE_TIER`). The API rejects unknown names outright.
10. **Session tokens are stored hashed and die with a password change.** A plaintext token is a live credential the moment the store is readable.
11. **A citation inside filed PROSE cannot be withheld the way a table entry can.** It becomes a filing blocker and stamps the exported reply until a reviewer confirms or strikes it — `panel.filed_text_blockers`, `export._prose_citation_gaps`.
12. **Section 74A is not Section 74.** `startswith("74")` matches "74A", and routing a 74A notice through the 74 table gets the concession deadline wrong by thirty days. Match 74A first, everywhere.
13. **Limitation runs in calendar months**, not 90+30 days — s.3(35), General Clauses Act. Day counts are for display only.
14. **Redaction is per reader, never per matter.** The stored record is always complete; `redact_for_role` AND the live SSE stream strip the deliberation and the cost for roles without the grant.
15. **The s.50(3) rate is 18%, not 24%.** The section says "not exceeding twenty-four per cent"; that is a ceiling. The notified rate is 18% w.e.f. 01.07.2017 (Notification 13/2017-CT as amended by s.116 and the Sixth Schedule of the Finance Act 2022). `calculators.py` carried 24.0 until September 2026. Do not restore it from the section text.
16. **Notified dates are not timeless.** s.128A closed on 30.06.2025; the GSTAT backlog date is 31.07.2026 for orders communicated before 01.05.2026 (S.O. 3502(E) moved both the date and the cohort); the penalty-only 10% pre-deposit runs from 01.10.2025. `calculators.py` holds these as named constants with the notification behind each. Re-check them whenever a notification lands, and never report a closed window as "available". Only a DRC-01 dates the s.73(8)/74(8)/74A(8) window; a DRC-01A, ASMT-10 or ADT-02 means the before-notice stage is still open.
17. **Pre-deposit caps are per Act.** Rs. 20 crore each under CGST and SGST, Rs. 40 crore under IGST. Use `predeposit_by_head`; one cap on a combined total understates large demands.
18. **A guest is anyone on the internet, and matters are not scoped per user.** `POST /api/auth/guest` asks for no credential, so a guest session is admitted only to `auth.GUEST_ROUTES` — an ALLOWlist of stateless routes — and refused everywhere else by `require_auth`, which is the router-level dependency. The first cut of guest mode let an anonymous caller list and read every stored matter. A new route is closed to guests until it is added to the list; add one only if it stores nothing and reads nothing stored. Public self-registration is off unless `ALLOW_SELF_REGISTRATION` is set, for the same reason: the account it creates is `staff` and sees every matter. `TestGuestsReachNothingStored` walks the route table.

### Frontend
Design tokens in `theme.css` (light/dark via `data-theme` on `<html>`); components never hardcode colours. `format.js` holds helpers/constants separately from `shared.jsx` so React Fast Refresh works — `POSTURES` and friends live there for the same reason. Views: Dashboard, PanelWorkspace (multi-file intake + defect review + live deliberation), DefectList, MatterList, MatterDetail (two separate downloads), AdminPanel, GeneralCouncil.

### Evals — two harnesses, and the free one runs on every push

`evals/golden/` holds nine committed cases across ASMT-10, DRC-01 (s.73 and
s.74), DRC-01B, DRC-01C, ADT-02, RFD-08, REG-17 and MOV-07. Every case is
**synthetic** and carries a provenance note; a test enforces both, because
these ship in a public repository and a golden case built from a client matter
must never be committed. `gst-asmt10-multilimb-fy2324` mirrors the reference
matter: eight limbs, and an e-invoicing limb that is lost on a missing IRP
acknowledgement despite a correct legal position.

**A real client matter goes in `evals/golden/private/`, which is gitignored.**
That directory IS the boundary. The ignore rule was once `evals/golden/*.json`,
which kept client matters out and the synthetic cases with them: a fresh clone
got no golden set, `test_golden_set.py` skipped itself in full, and three tests
in `test_api_practice.py` failed outright on a file that had never been
committed — so the harness guarding every catalogue pattern ran only on the
machine that wrote it. `TestTheGoldenSetBoundary` in `tests/test_deployment.py`
now holds both sides: the private directory stays ignored, the synthetic set
stays committed and stays marked `synthetic`. `evals/run.py` reads both
directories; the free scorer reads only the committed top level.

**`tests/test_golden_set.py` — free, runs on every push** (really: CI is
`.github/workflows/test.yml`, which runs `uv sync --extra ocr && uv run
pytest` plus the frontend lint and build on every push and pull request. For a
long time this claim was aspirational and nothing enforced it). Segmentation and
figure reading are decided in Python, so they are scored without a single model
call: every limb must be found, every head-wise amount must match the annexure,
and the limbs must reconcile to the notice's own printed total. This is where
six silent extraction bugs were caught, none of which the paid harness would
have found, because nobody runs the paid harness on every change.

**`evals/run.py` — costs money, run before shipping a prompt change.** The two
numbers that matter are `defect_coverage` (a limb the panel never finds cannot
be answered, and an unanswered limb is confirmed unopposed) and
`evidence_gap_catch` (scored against a limb that was argued correctly and lost
anyway). No prompt change should ship without running these.

---

## The general council

The general council is a three-part deliberation: several models answer the same question, referee one another's answers blind, and a chair settles it. The idea is Andrej Karpathy's (see `NOTICE`). The referees never see model names, and never see or place their own answer. The app supports multi-turn conversations, quick vs full deliberation modes, web-search grounding, cost accounting, and private cloud deployment behind a bearer token.

## Architecture

### Backend modules (`backend/`)

**`config.py`**
- Every setting is env-overridable (loaded via `.env`); see `.env.example` for the full list
- `COUNCIL_MODELS` (comma-separated env or default list), `CHAIRMAN_MODEL`, `TITLE_MODEL`
- `REASONING_EFFORT` (low/medium/high/none), `REQUEST_TIMEOUT`, `MAX_RETRIES`, `HISTORY_MAX_TURNS`
- `APP_ACCESS_TOKEN`: shared secret; empty = auth disabled (local dev only)
- The API listens on **port 8001** unless `PORT` says otherwise; the Vite dev proxy targets it and the Dockerfile exposes it

**`openrouter.py`**
- `ask_model()`: single async model query. Returns `{'ok': True, 'content', 'reasoning_details', 'usage'}` or `{'ok': False, 'error'}` — never None
- Retries transient failures (network errors, 408/409/429/5xx) with exponential backoff (2s, 4s); non-retryable statuses fail fast
- If a model rejects the `reasoning` parameter with HTTP 400, the parameter is stripped and the call retried without consuming retry budget
- Requests `usage: {include: true}` so OpenRouter returns token counts and dollar cost
- `web_search=True` adds the OpenRouter web plugin (`plugins: [{"id": "web"}]`)
- Treats 200-with-error-body and empty-content responses as failures

**`council.py`** — the three-stage deliberation
- `build_history_messages()`: converts stored conversation messages into chat history (user turns + prior rulings), capped at `HISTORY_MAX_TURNS` exchanges. Passed to the opening and the ruling as real message turns; the referees get a truncated text snippet via `format_history_snippet()`
- `collect_answers()`: parallel queries; returns `(answers, failures)` — failures carry per-model error strings surfaced in the UI
- `collect_reviews()`:
  - Labels "Answer A/B/C..." assigned in the order the answers came back; the `authors` mapping (label → model) de-anonymises them afterwards
  - **Each referee gets its own prompt with its own answer left out** — different referees see different subsets, so per-referee `valid_labels` are tracked
  - A referee left with fewer than 2 answers to order is skipped
  - Returns `(reviews, authors, failures)`; each review carries `assessment`, `order`, `own_label`, `parse_complete`
- `chair_ruling()`: the chair receives the answers, the reviews, **the `authors` mapping and the standings** so it can connect a verdict to the answer it was about; the prompt instructs it to resolve disagreements explicitly rather than averaging
- `read_order_of_merit(reply, valid_labels)`: takes the LAST header in `RANKING_HEADERS` ("ORDER OF MERIT:" is what the prompt asks for), prefers the numbered-list format, deduplicates labels (first occurrence wins), and drops labels not in `valid_labels`
- `tally_standings()`: positions are **normalized to [0,1] within each review** (referees order different subset sizes because each one's own answer is withheld), then averaged; output sorted by `score` ascending (lower = better) and includes raw `mean_position` + `reviews_counted`
- `run_council_stream()`: async generator yielding the events; single source of truth for orchestration. `run_council()` consumes it for the non-streaming endpoint. Modes: `"full"` (answers → reviews → ruling) and `"quick"` (skips the reviews)
- `_sum_usage()`: aggregates tokens/cost across answers, reviews and ruling into `metadata.usage`

**`auth.py`**
- `require_auth` dependency: constant-time comparison of `Authorization: Bearer <token>` against `APP_ACCESS_TOKEN`; no-op when unset

**`storage.py`**
- Conversations are JSON files under `data/conversations/` (env-overridable `DATA_DIR` — read dynamically via `config.DATA_DIR` so tests can monkeypatch it)
- **Atomic writes** (tempfile + `os.replace`) — a crash can't corrupt conversation files
- Corrupt files are skipped in listings and return None on read, never crash the app
- Assistant messages persist `{role, answers, reviews, ruling, metadata}` — metadata (`authors`, `standings`, failures, usage) IS persisted, so reloaded conversations render fully
- **Conversations written before November 2026 are on disk in an older shape** (`stage1` / `stage2` / `stage3`, `label_to_model`, `aggregate_rankings`). `read_conversation()` upgrades them on the way in, so nothing above storage ever sees the old keys; `python -m backend.cli migrate-conversations --apply` rewrites the files. See "The general council's vocabulary" below
- `delete_conversation()` supported

**`main.py`**
- All `/api` routes on an APIRouter behind `require_auth`; `/healthz` is unauthenticated (hosting platform health checks)
- `POST /api/conversations/{id}/message/stream` (SSE) is the primary path; events: `answers_start/complete`, `reviews_start/complete`, `ruling_start/complete`, `summary` (authoritative metadata incl. usage), `conversation_titled`, `complete`, `error`. `answers_complete`/`reviews_complete` also carry `failures`
- `CouncilQuestion`: `question`, `mode` ("full"/"quick"), `web_search` (bool)
- Startup hook validates configured model IDs against OpenRouter's catalog (best-effort, non-fatal); results in `GET /api/health`
- Serves `frontend/dist` as static files when present (single-container deployment); mounted after API routes so `/api` wins

### Frontend modules (`frontend/src/`)

**`api.js`**
- Relative URLs only (`/api/...`): Vite dev server proxies to :8001 (see `vite.config.js`); production is same-origin
- Bearer token stored in localStorage (`llm_council_token`); `ApiError` carries `.status` so the app can detect 401 and show the login screen
- SSE parsing buffers across chunks (events can span reads)

**`App.jsx`**
- Auth gate: `checkAuth` on mount → login screen on 401; any later 401 clears the token and re-gates
- `updateLastMessage` helper immutably updates the in-flight assistant message per SSE event
- Stream errors mark the message with an inline error instead of deleting the exchange
- Conversation delete with confirm dialog

**`components/GeneralCouncil.jsx`** — the whole heritage chat surface: input
always visible (multi-turn), per-message Full/Quick and web-search options,
per-model failure notices, and the cost line. Off unless
`ENABLE_GENERAL_COUNCIL` is set.

(Earlier revisions of this file documented `ChatInterface.jsx`, `Stage2.jsx`,
`Stage3.jsx` and an `index.css`. None of them exist — the chat surface was
consolidated into `GeneralCouncil.jsx` and styling moved to `theme.css` plus
`components/components.css`. See the `### Frontend` section above, which is
the accurate one.)

## Why the general council works the way it does

### No seat reviews its own answer
Models reliably recognize their own writing style, so letting a seat place its own answer biased the standings. Each referee now sees only its peers' answers. Consequence: referees order different subset sizes (a seat that failed to answer still reviews ALL the answers, since none is its own), so the standings use within-review normalization, not raw average positions.

### The referee's closing block
The prompt asks for an "ORDER OF MERIT:" header followed by a strict numbered list, because that is what can be parsed. The parser prefers the numbered format, falls back to bare "Answer X" mentions, dedupes, and validates against the labels that referee was actually shown.

### What the chair is given
The chair previously couldn't connect "Answer A is best" to any model. It now receives the `authors` mapping and the standings, with explicit instructions to exercise judgment (not blindly follow first place) and to resolve disagreements explicitly.

### The general council's vocabulary

The general council began as a fork, and for a long time it kept the upstream
project's names: functions called `stage1_…`, `stage2_…`, `stage3_…`, records
keyed `stage1` / `stage2` / `stage3`, labels reading "Response A". Those were
that author's choices, not something a library imposed, and the project's
licence notes had to say so. In November 2026 they were replaced with this
project's own: the three parts of an exchange are its **answers**, its
**reviews** and its **ruling**, and everything is named after those.

Two consequences worth knowing before touching this code:

1. **Old records are upgraded on read, in one place.**
   `storage.upgrade_conversation` translates the old keys to the current ones
   and is called from `read_conversation`, so the old names exist nowhere else
   in the application. Do not add a second reader that opens the JSON
   directly, and do not teach `council.py` or the UI the old keys — a record
   that reaches them un-upgraded renders as a thread whose every answer is
   missing, with no error.
2. **Only keys are translated, never labels.** An old record's assessments
   say "Response B" in the referee's own words, and its `authors` map is what
   says who Response B was. Relabelling one without the other would cut the
   stored reviews loose from the answers they were about, so a record keeps
   the labels it was written with. `TestConversationsWrittenBeforeTheRename`
   holds both.

The compliance panel's own stream still uses `stage1_complete` and friends
for its five stages. That is a separate wire protocol with its own clients
and was deliberately left alone.

### How failures are handled
- A seat that fails does not stop the deliberation: the council carries on with the answers it has, and **every failure is shown to the user** (per-model error notices in the UI)
- Transient failures are retried before a seat is counted as failed
- A failed chair returns an explicit error message, and the answers and reviews remain viewable

### Cost Transparency
Every model call requests usage accounting; totals are aggregated per exchange and persisted, so the user always knows what a deliberation cost.

## General-council gotchas

1. **`ImportError` on start**: the backend is a package with relative imports, so start it from the repository root as `python -m backend.main` (or `uvicorn main:app`), never by running a file inside `backend/`
2. **An incomplete order**: `parse_complete: false` on a review means the referee didn't place everything it was shown — the parser keeps whatever was valid
3. **Different label sets per referee**: don't assume every referee placed every label; that's why the standings use normalized scores
4. **Auth in dev**: unset `APP_ACCESS_TOKEN` disables auth entirely — never deploy that way
5. **`config.DATA_DIR` is read at call time** in storage.py (via `config.DATA_DIR`), not import time — keep it that way for testability
6. **SSE events can span TCP chunks** — the frontend buffers; don't regress to per-chunk parsing

## Testing

```bash
uv run pytest
```

`tests/test_council.py`: parser edge cases (duplicates, invalid labels, repeated headers, fallbacks), standings normalization, history building/truncation.
`tests/test_storage.py`: atomic writes, corrupt-file resilience, metadata persistence, deletion, and the upgrade of conversations stored in the old shape.

Startup logs and `GET /api/health` report model IDs missing from OpenRouter's catalog — check there first when a model silently fails.

## Deployment

- **Docker**: multi-stage build (Node → Python via uv); container serves API + built frontend on :8001; conversation data at `/app/data` (mount a volume)
- **Render**: `render.yaml` blueprint — Docker runtime, persistent disk at `/app/data`, `OPENROUTER_API_KEY` set manually, `APP_ACCESS_TOKEN` auto-generated
- `/healthz` is the unauthenticated health check endpoint

## How a question flows

```
User Query (+ conversation history, mode, web_search)
    ↓
Answers: parallel queries (history-aware, optional web search) → [answers + failures]
    ↓ (mode=full and ≥2 answers)
Reviews: label the answers, withhold each seat's own → parallel refereeing → [assessments + orders]
    ↓
Standings (normalized positions) → [sorted by score]
    ↓
Ruling: the chair (history + answers + reviews + authors + standings)
    ↓
summary event: {answers, reviews, ruling, metadata: {authors, standings, failures, usage, mode}}
    ↓
Persisted to storage (metadata included) + streamed to frontend via SSE
```
