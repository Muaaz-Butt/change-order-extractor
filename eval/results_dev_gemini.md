# Evaluation: rules + LLM (gemini) -- samples

LLM calls that failed and fell back to rules only: **0/8**

8 documents, 101 gold fields, 20 gold line items.

| document | status | overall | fields correct | hallucinated | line items found |
|---|---|---|---|---|---|
| co_001_formal.pdf | auto_accept | 0.99 | 18/18 | 0 | 4/4 (pred 4) |
| co_002_email.txt | auto_accept | 0.95 | 10/10 | 0 | 2/2 (pred 2) |
| co_003_ocr_scan.txt | needs_review | 0.79 | 17/17 | 0 | 3/3 (pred 3) |
| co_004_credit.pdf | auto_accept | 0.99 | 18/18 | 0 | 2/2 (pred 2) |
| co_005_inconsistent.txt | needs_review | 0.98 | 13/13 | 0 | 3/3 (pred 3) |
| co_006_twocolumn.pdf | auto_accept | 0.98 | 11/11 | 0 | 3/3 (pred 3) |
| co_007_fieldnote.txt | needs_review | 0.72 | 2/4 | 0 | 1/1 (pred 1) |
| co_008_scanned.pdf | needs_review | 0.72 | 10/10 | 0 | 2/2 (pred 2) |

## Headline metrics

- **Field recall** (gold fields extracted correctly): 99/101 = 98.0%
- **Field precision** (predicted fields that are correct): 99/101 = 98.0%
- **Hallucinated fields** (value predicted, gold is empty): 0
- **Line-item recall** (by amount): 20/20 = 100.0%
- **Errors caught by review routing** (wrong values with confidence < 0.8 or listed in needs_review): 1/2 = 50%

## Calibration (predicted scalar fields + line-item amounts)

| confidence | n | accuracy | mean confidence |
|---|---|---|---|
| 0.00-0.50 | 1 | 0% | 0.38 |
| 0.50-0.80 | 30 | 100% | 0.76 |
| 0.80-0.95 | 9 | 89% | 0.88 |
| 0.95-1.00 | 81 | 100% | 0.98 |

Expected calibration error (ECE): **0.075** (lower is better; 0 = perfectly calibrated)

## Errors by document

**co_007_fieldnote.txt**
- description='extra rock removal at footing F-7.' (gold 'Extra rock removal at footing F-7; hit ledge ~4ft down, not in the geotech report.', conf 0.90)
- reason='other' (gold 'unforeseen_condition', conf 0.38)

