# Evaluation: rules only (offline) -- samples

8 documents, 101 gold fields, 20 gold line items.

| document | status | overall | fields correct | hallucinated | line items found |
|---|---|---|---|---|---|
| co_001_formal.pdf | auto_accept | 0.94 | 18/18 | 0 | 4/4 (pred 4) |
| co_002_email.txt | needs_review | 0.85 | 8/10 | 0 | 2/2 (pred 2) |
| co_003_ocr_scan.txt | needs_review | 0.74 | 17/17 | 0 | 3/3 (pred 3) |
| co_004_credit.pdf | auto_accept | 0.94 | 18/18 | 0 | 2/2 (pred 2) |
| co_005_inconsistent.txt | needs_review | 0.87 | 13/13 | 0 | 3/3 (pred 3) |
| co_006_twocolumn.pdf | needs_review | 0.83 | 11/11 | 0 | 3/3 (pred 3) |
| co_007_fieldnote.txt | needs_review | 0.55 | 3/4 | 0 | 1/1 (pred 1) |
| co_008_scanned.pdf | failed | 0.00 | 0/10 | 0 | 0/2 (pred 0) |

## Headline metrics

- **Field recall** (gold fields extracted correctly): 88/101 = 87.1%
- **Field precision** (predicted fields that are correct): 88/88 = 100.0%
- **Hallucinated fields** (value predicted, gold is empty): 0
- **Line-item recall** (by amount): 18/20 = 90.0%
- **Errors caught by review routing** (wrong values with confidence < 0.8 or listed in needs_review): 0/0

## Calibration (predicted scalar fields + line-item amounts)

| confidence | n | accuracy | mean confidence |
|---|---|---|---|
| 0.00-0.50 | 5 | 100% | 0.35 |
| 0.50-0.80 | 29 | 100% | 0.74 |
| 0.80-0.95 | 41 | 100% | 0.89 |
| 0.95-1.00 | 31 | 100% | 0.97 |

Expected calibration error (ECE): **0.154** (lower is better; 0 = perfectly calibrated)

## Errors by document

**co_002_email.txt**
- description missing (gold 'Add outlets in the kitchen island and move the fan box in unit 4B per tenant request.')
- reason missing (gold 'owner_request')

**co_007_fieldnote.txt**
- description missing (gold 'Extra rock removal at footing F-7; hit ledge ~4ft down, not in the geotech report.')

**co_008_scanned.pdf**
- change_order_number missing (gold '3')
- project_name missing (gold 'Pine Hollow Clubhouse Renovation')
- owner missing (gold 'Pine Hollow HOA')
- contractor missing (gold 'Oakridge Remodeling Co.')
- date_issued missing (gold '2025-05-12')
- description missing (gold 'Replace rotted rim joist found behind siding.')
- reason missing (gold 'unforeseen_condition')
- status missing (gold 'approved')
- total_change_amount missing (gold 1310.0)
- schedule_impact_days missing (gold 1)

