# Evaluation: rules + LLM (gemini) -- samples/holdout

LLM calls that failed and fell back to rules only: **0/2**

2 documents, 23 gold fields, 5 gold line items.

| document | status | overall | fields correct | hallucinated | line items found |
|---|---|---|---|---|---|
| ho_001_letter.txt | needs_review | 0.92 | 10/11 | 0 | 3/3 (pred 3) |
| ho_002_pipes.md | needs_review | 0.77 | 11/12 | 0 | 2/2 (pred 2) |

## Headline metrics

- **Field recall** (gold fields extracted correctly): 21/23 = 91.3%
- **Field precision** (predicted fields that are correct): 21/22 = 95.5%
- **Hallucinated fields** (value predicted, gold is empty): 0
- **Line-item recall** (by amount): 5/5 = 100.0%
- **Errors caught by review routing** (wrong values with confidence < 0.8 or listed in needs_review): 1/1 = 100%

## Calibration (predicted scalar fields + line-item amounts)

| confidence | n | accuracy | mean confidence |
|---|---|---|---|
| 0.50-0.80 | 15 | 93% | 0.76 |
| 0.80-0.95 | 4 | 100% | 0.89 |
| 0.95-1.00 | 8 | 100% | 0.97 |

Expected calibration error (ECE): **0.123** (lower is better; 0 = perfectly calibrated)

## Errors by document

**ho_001_letter.txt**
- status missing (gold 'pending')

**ho_002_pipes.md**
- description='| Qty | Unit | Unit Price | Amount | |---|---|---|---|---|---| | 1 | Frameless glass partition | 42 | LF | 310.00 | 13,020.00 | | 2 | Glass door with hardware | 2 | EA | 2,450.00 | 4,900.00 |' (gold 'Upgraded glass partitions in conference rooms 3 and 4.', conf 0.60)

