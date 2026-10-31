# Change-Order Extraction: Approach and Failure Modes

## The problem

Change orders arrive as formal AIA-style PDFs, contractor proposals, email threads, phone photos run through OCR, and two-line field notes. The goal is validated JSON with a confidence score for each field that you can act on: high-confidence documents are booked automatically, and everything else goes to a person along with a reason.

The hard part is the confidence score, not the extraction. A model that is 95% accurate but cannot say *which* 5% is wrong forces a human to check everything.

## Approach

**1. Two independent extractors, never one.**

- **Claude** (`claude-opus-5-5`, JSON-schema structured output) is the primary extractor. It handles layouts, prose, and scanned PDFs (which it reads visually). Every field must come back as `{value, evidence, certainty}`, where `evidence` is a verbatim quote. The model is told *not* to compute values that aren't written down.
- **A label/regex extractor** is deliberately simple and conservative. It is not meant to compete with the LLM. It provides an *uncorrelated* second opinion, and it lets the pipeline run offline.

When two methods that fail in different ways agree, that is strong evidence. When they disagree, the field is pinpointed for review.

**2. Grounding.** Every quote is checked against the document text. A quote that isn't in the document is the clearest hallucination signal available, so it costs -2.5 log-odds (a "high certainty" claim with a made-up quote lands around 0.25). The pipeline also checks that the value appears inside its own quote.

**3. The document checks itself.** A change order contains its own checksums: line items add up to the subtotal, subtotal + O&P + tax = total, and contract sum before + this change = new contract sum. Each check that passes is independent evidence for the fields involved, and each failure points at specific fields. When the extractors disagree on an amount, the pipeline keeps the value that makes the arithmetic work (*arithmetic arbitration*). Because the LLM is forbidden from doing arithmetic, a passing check means the numbers on the page agree with each other. It can't be the model agreeing with itself.

**4. Confidence is additive log-odds.** The score starts from the extractor's own certainty, then adds weights for grounding, agreement, passing or failing checks, and parse flags (OCR repair, ambiguous `06/09` dates, weeks converted to days). The result is capped by a document text-quality score. Each contribution is written out as a human-readable `reasons` entry, so a reviewer can see *why* a field scored 0.62. The weights are hand-set for now; the structure is a logistic regression, so they can be fitted once labelled data exists.

**5. Routing.** A document is `auto_accept` only if every required field and every money field scores ≥ 0.80, there are no arithmetic errors, the result validates against the Pydantic `ChangeOrder` schema, and the input has a real text layer (scans always get reviewed). Otherwise it is `needs_review` (with the specific fields listed) or `failed` (required fields missing).

## Results

The eval script reports calibration as well as accuracy. Rules-only, offline:

| set | field recall | field precision | hallucinated | line items | wrong values caught by review |
|---|---|---|---|---|---|
| dev (8 docs, rules developed on these) | 87.1% | 100% | 0 | 90% | n/a (no wrong values) |
| **held-out** (2 docs, never tuned on) | **65.2%** | **88.2%** | **0** | **0%** | **2/2** |

The held-out row is the honest number. On formats it hasn't seen, the rules extractor misses a lot, which is expected and is why it isn't the primary extractor. What matters is that it **fails safe**: no invented values, lower confidence, and every wrong value routed to review. Dev-set accuracy is inflated because I wrote the rules while looking at those documents.

The Claude path is covered by unit tests with a mocked client: request shape, agreement, hallucinated quotes, arithmetic arbitration, refusals, and API errors. It has **not** been run against the live API in the environment where this was built (no API key). `uv run python eval/evaluate.py --llm` is the next step and needs nothing else.

## Failure modes

These are ordered roughly by how much damage each one would do in production.

1. **Confidently wrong *and* internally consistent.** If a document is wrong but its own arithmetic balances (e.g. the contractor typed the wrong total and then carried it through to the new contract sum), every check passes and confidence is high. Extraction can't detect errors in the source itself; that needs a comparison against the contract or ledger.
2. **Both extractors share the same mistake.** Agreement is only evidence if the errors are independent. Both read the same text layer, so a PDF whose text layer is wrong (bad embedded OCR, ligatures, or reading order that interleaves two columns) can make them agree on garbage.
3. **Scanned PDFs can't be grounded.** With no text layer, there is nothing to check quotes against. Confidence is capped (quality = 0.75), so scans never auto-accept, but they can't score well either. Adding a real OCR step (Tesseract or Textract) would restore grounding.
4. **Sign and parenthesis ambiguity.** `(450.00)` is a credit in an accounting column, but `markup ($165.50) so…` is a parenthetical aside. A heuristic handles the common case (a parenthesized amount followed by prose on the same line is an aside). Mixed layouts can still flip a sign, and the arithmetic checks usually catch it.
5. **Party roles are relative.** In a sub-to-GC letter, "contractor" and "owner" depend on whose contract it is. The schema has no `subcontractor` field, so these documents are inherently ambiguous (see held-out `ho_001`).
6. **Unit semantics.** "2 working days" is not 2 calendar days, and "2 weeks" becomes 14. Both are flagged and lower the confidence, but no conversion is fully correct without the project calendar.
7. **Multi-CO documents and revisions.** A PDF bundling several change orders, or an email thread where pricing was revised ("earlier number of $1,500 was a guess, ignore it"), can surface the wrong value. The LLM prompt asks for the final authoritative value, but nothing yet *splits* multi-CO documents.
8. **Prompt injection.** Document text is untrusted. The system prompt tells Claude to ignore instructions inside documents, and grounding plus the arithmetic checks limit the damage: an injected "set total to $1" would fail the checks. It is still a risk to monitor.
9. **Calibration is unproven at scale.** Ten synthetic documents can't show that 0.9 means 90%. The dev set is underconfident (ECE 0.15, every bucket at 100% accuracy), which is the safer direction, but the weights need refitting on a few hundred real labelled documents.

## What I'd do next

- Run `--llm` on the eval sets and on ~200 real labelled change orders, then fit the confidence weights with logistic regression and report ECE on a held-out split.
- Add a Tesseract/Textract OCR step so scanned documents get a text layer to ground against.
- Add page and bounding-box provenance to the evidence so a review UI can highlight the source.
- Run a third, cheaper extractor (e.g. `claude-haiku-5-5`) as an additional vote on the money fields only.
- Split multi-CO documents, and cross-check against the project's contract sum and the prior CO log.
