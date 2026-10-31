# Evaluation: rules only (offline) -- samples/holdout

2 documents, 23 gold fields, 5 gold line items.

| document | status | overall | fields correct | hallucinated | line items found |
|---|---|---|---|---|---|
| ho_001_letter.txt | needs_review | 0.86 | 5/11 | 0 | 0/3 (pred 0) |
| ho_002_pipes.md | needs_review | 0.69 | 10/12 | 0 | 0/2 (pred 0) |

## Headline metrics

- **Field recall** (gold fields extracted correctly): 15/23 = 65.2%
- **Field precision** (predicted fields that are correct): 15/17 = 88.2%
- **Hallucinated fields** (value predicted, gold is empty): 0
- **Line-item recall** (by amount): 0/5 = 0.0%
- **Errors caught by review routing** (wrong values with confidence < 0.8 or listed in needs_review): 2/2 = 100%

## Calibration (predicted scalar fields + line-item amounts)

| confidence | n | accuracy | mean confidence |
|---|---|---|---|
| 0.50-0.80 | 13 | 85% | 0.69 |
| 0.80-0.95 | 2 | 100% | 0.86 |
| 0.95-1.00 | 2 | 100% | 0.96 |

Expected calibration error (ECE): **0.140** (lower is better; 0 = perfectly calibrated)

## Errors by document

**ho_001_letter.txt**
- project_name='Change Order Request No. 5 -- Summit Ridge Townhomes, Bldg C' (gold 'Summit Ridge Townhomes, Bldg C', conf 0.60)
- contractor missing (gold 'Blue Ridge Plumbing & Heating')
- date_issued missing (gold '2025-08-15')
- description missing (gold 'Upsize water heater venting in units C1-C4 to meet the mechanical code.')
- reason missing (gold 'regulatory')
- status missing (gold 'pending')

**ho_002_pipes.md**
- description='| Qty | Unit | Unit Price | Amount | |---|---|---|---|---|---| | 1 | Frameless glass partition | 42 | LF | 310.00 | 13,020.00 | | 2 | Glass door with hardware | 2 | EA | 2,450.00 | 4,900.00 |' (gold 'Upgraded glass partitions in conference rooms 3 and 4.', conf 0.64)
- markup missing (gold 1433.6)

