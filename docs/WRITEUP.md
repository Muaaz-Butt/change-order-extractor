# Change-Order Extraction: Approach and Failure Modes

## The problem

Change orders arrive as formal AIA-style PDFs, contractor proposals, email threads, phone photos run through OCR, and two-line field notes. The goal is validated JSON with a confidence score for each field that you can act on: high-confidence documents are booked automatically, and everything else goes to a person along with a reason.

The hard part is the confidence score, not the extraction. A model that is 95% accurate but cannot say *which* 5% is wrong forces a human to check everything.

## Approach

**1. Two independent extractors, never one.**

- **An LLM** is the primary extractor: Gemini (`gemini-3.6-flash`, which produced the results below) or Claude (`claude-opus-5-5`). Both use JSON-schema structured output with the same prompt. It handles layouts, prose, and scanned PDFs (which it reads visually). Every field must come back as `{value, evidence, certainty}`, where `evidence` is a verbatim quote. The model is told *not* to compute values that aren't written down.
- **A label/regex extractor** is deliberately simple and conservative. It is not meant to compete with the LLM. It provides an *uncorrelated* second opinion, and it lets the pipeline run offline.

When two methods that fail in different ways agree, that is strong evidence. When they disagree, the field is pinpointed for review.

**2. Grounding.** Every quote is checked against the document text. A quote that isn't in the document is the clearest hallucination signal available, so it costs -2.5 log-odds (a "high certainty" claim with a made-up quote lands around 0.25). The pipeline also checks that the value appears inside its own quote.

**3. The document checks itself.** A change order contains its own checksums: line items add up to the subtotal, subtotal + O&P + tax = total, and contract sum before + this change = new contract sum. Each check that passes is independent evidence for the fields involved, and each failure points at specific fields. When the extractors disagree on an amount, the pipeline keeps the value that makes the arithmetic work (*arithmetic arbitration*). Because the LLM is forbidden from doing arithmetic, a passing check means the numbers on the page agree with each other. It can't be the model agreeing with itself.

**4. Confidence is additive log-odds.** The score starts from the extractor's own certainty, then adds weights for grounding, agreement, passing or failing checks, and parse flags (OCR repair, ambiguous `06/09` dates, weeks converted to days). The result is capped by a document text-quality score. Each contribution is written out as a human-readable `reasons` entry, so a reviewer can see *why* a field scored 0.62. The weights are hand-set for now; the structure is a logistic regression, so they can be fitted once labelled data exists.

**5. Routing.** A document is `auto_accept` only if every required field and every money field scores ≥ 0.80, every other extracted field scores ≥ 0.60, there are no arithmetic errors, the result validates against the Pydantic `ChangeOrder` schema, and the input has a real text layer (scans always get reviewed). Otherwise it is `needs_review` (with the specific fields listed) or `failed` (required fields missing).

## Results

The eval script reports calibration as well as accuracy. All numbers below are from live runs of the code in this repo.

| set | mode | field recall | field precision | hallucinated | line items | ECE |
|---|---|---|---|---|---|---|
| dev (8 docs, rules developed on these) | rules only | 87.1% | 100% | 0 | 90% | 0.154 |
| dev | **Gemini + rules** | **98.0%** | **98.0%** | **0** | **100%** | **0.075** |
| **held-out** (2 docs, never tuned on) | rules only | 65.2% | 88.2% | 0 | 0% | 0.140 |
| **held-out** | **Gemini + rules** | **91.3%** | **95.5%** | **0** | **100%** | 0.123 |

Full reports: [dev, Gemini](../eval/results_dev_gemini.md), [held-out, Gemini](../eval/results_holdout_gemini.md), [dev, rules](../eval/results_dev_rules.md), [held-out, rules](../eval/results_holdout_rules.md).

What the numbers say:

- **The LLM does the heavy lifting on unseen formats.** On the held-out documents, rules alone found no line items; with Gemini, all 5 were found and recall rose from 65% to 91%. The dev-set rules numbers are inflated because I wrote the rules while looking at those documents.
- **Nothing was invented** in any run. Every wrong value was either incomplete (a shortened description) or a missed field, not a made-up one.
- **Routing is conservative.** With Gemini, 4 of 8 dev documents were auto-accepted, all 100% correct. The rest went to review: the OCR scan, the document with inconsistent arithmetic (flagged on purpose), the image-only PDF (scans always go to review), and the field note. Both held-out documents went to review.
- **Calibration** improves with the LLM (ECE 0.154 → 0.075), mostly because agreement between the two extractors pushes correct values into the 0.95+ bucket, where accuracy was 100%.
- Gemini's free tier was intermittently overloaded (503). The extractor times out after 60 s, retries 3 times with backoff, and otherwise falls back to the rules result and records the error. The eval reports how many documents fell back (0/10 in the runs above), so a degraded run can't pass for a real one.

The Claude path uses the same prompt, schema and downstream logic. It is covered by unit tests with a mocked client but was not run live (no Anthropic key in the build environment).

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
9. **Confident but incomplete text.** On the two-line field note, Gemini shortened the description to its first clause. Both the quote and the value check pass, so it scored 0.90. Grounding proves a value is *real*; it doesn't prove it is *complete*. A length or sentence-boundary check against the quote would catch this.
10. **Optional fields used to slip through.** Auto-accept originally checked only required and money fields. In an earlier run, the field note was auto-accepted with a wrong owner name scored 0.52. Now any extracted field below 0.60 blocks auto-accept. The cost is that in rules-only mode, one fully correct document now goes to review because its `reason` was only guessed from keywords.
11. **Table structure leaking into text fields.** On the markdown pipe-table document, the final description was the rules extractor's capture of raw table text. It scored only 0.60 and the document went to review, but text fields should reject candidates that are mostly table syntax (`|`, `---`) before reconciliation.
12. **Calibration is unproven at scale.** Ten synthetic documents can't show that 0.9 means 90%. ECE is 0.075 on dev with Gemini, and most mid-range buckets are underconfident (100% accuracy at a mean confidence of 0.76), which is the safer direction. The weights still need refitting on a few hundred real labelled documents.

## What I'd do next

- Label ~200 real change orders, fit the confidence weights with logistic regression, and report ECE on a held-out split.
- Run the Claude path live and compare it with Gemini on the same set.
- Add a Tesseract/Textract OCR step so scanned documents get a text layer to ground against.
- Add page and bounding-box provenance to the evidence so a review UI can highlight the source.
- Run a third, cheaper extractor (e.g. `claude-haiku-5-5`) as an additional vote on the money fields only.
- Split multi-CO documents, and cross-check against the project's contract sum and the prior CO log.
