"""Score the pipeline against samples/expected/*.json.

    uv run python eval/evaluate.py            # rules only (offline)
    uv run python eval/evaluate.py --llm      # rules + Claude (needs ANTHROPIC_API_KEY)

Reports field accuracy, hallucinations, line-item recall, and -- most
importantly for this task -- whether confidence is *calibrated*: do 0.9
fields turn out right ~90% of the time, and does review routing catch the
errors?
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from co_extract import run  # noqa: E402
from co_extract.pipeline import REVIEW_THRESHOLD  # noqa: E402
from co_extract.schema import SCALAR_FIELDS  # noqa: E402

BUCKETS = [(0.0, 0.5), (0.5, 0.8), (0.8, 0.95), (0.95, 1.01)]


def canon_id(s: str) -> str:
    s = re.sub(r"[^A-Z0-9]", "", str(s).upper())
    s = re.sub(r"^(PCO|COR|CO)(?=\d)", "", s)
    return s.lstrip("0") or "0"


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def match(field: str, kind: str, pred, gold) -> bool:
    if pred is None or gold is None:
        return pred is None and gold is None
    if kind in ("money", "number"):
        return abs(float(pred) - float(gold)) < 0.011
    if kind == "id":
        return canon_id(pred) == canon_id(gold)
    if kind == "text" and field == "description":
        g = _words(gold)
        return len(_words(pred) & g) / max(len(g), 1) >= 0.6  # paraphrase-tolerant
    if kind == "text":
        a, b = re.sub(r"[^a-z0-9 ]", "", str(pred).lower()), re.sub(r"[^a-z0-9 ]", "", str(gold).lower())
        return SequenceMatcher(None, a, b).ratio() >= 0.85
    return pred == gold


def evaluate(use_llm: bool, sample_dir: Path = ROOT / "samples") -> str:
    rows, obs = [], []  # obs: (confidence, correct) for every predicted non-null field
    tot = {"gold": 0, "correct": 0, "pred": 0, "pred_correct": 0, "halluc": 0, "items_gold": 0, "items_found": 0}
    wrong_flagged = wrong_total = 0
    for gold_path in sorted((sample_dir / "expected").glob("*.json")):
        gold = json.loads(gold_path.read_text())
        src = next(p for p in sample_dir.iterdir() if p.stem == gold_path.stem and p.is_file())
        res = run(src, use_llm=use_llm)
        d = {"gold": 0, "correct": 0, "halluc": 0, "wrong": []}
        for f, kind in SCALAR_FIELDS.items():
            fr = res.fields[f]
            g = gold.get(f)
            ok = match(f, kind, fr.value, g)
            if g is not None:
                d["gold"] += 1
                d["correct"] += ok
            if fr.value is not None:
                tot["pred"] += 1
                tot["pred_correct"] += ok
                obs.append((fr.confidence, ok))
                if g is None:
                    d["halluc"] += 1
                if not ok:
                    wrong_total += 1
                    wrong_flagged += (fr.confidence < REVIEW_THRESHOLD or f in res.needs_review)
                    d["wrong"].append(f"{f}={fr.value!r} (gold {g!r}, conf {fr.confidence:.2f})")
            elif g is not None:
                d["wrong"].append(f"{f} missing (gold {g!r})")
        gold_amounts = [round(i["amount"], 2) for i in gold.get("line_items", [])]
        pred_amounts = [round(li.fields["amount"].value, 2) for li in res.line_items if li.fields["amount"].value is not None]
        found = sum(1 for a in gold_amounts if a in pred_amounts)
        for li in res.line_items:
            obs.append((li.fields["amount"].confidence, round(li.fields["amount"].value, 2) in gold_amounts))
        tot["items_gold"] += len(gold_amounts)
        tot["items_found"] += found
        for k in ("gold", "correct"):
            tot[k] += d[k]
        tot["halluc"] += d["halluc"]
        rows.append((src.name, res.status, res.overall_confidence, d, found, len(gold_amounts), len(pred_amounts)))

    mode = "rules + LLM" if use_llm else "rules only (offline)"
    out = [f"# Evaluation: {mode} -- {sample_dir.relative_to(ROOT)}", "", f"{len(rows)} documents, {tot['gold']} gold fields, {tot['items_gold']} gold line items.", "",
           "| document | status | overall | fields correct | hallucinated | line items found |",
           "|---|---|---|---|---|---|"]
    for name, status, overall, d, found, n_gold, n_pred in rows:
        out.append(f"| {name} | {status} | {overall:.2f} | {d['correct']}/{d['gold']} | {d['halluc']} | {found}/{n_gold} (pred {n_pred}) |")
    out += ["", "## Headline metrics", "",
            f"- **Field recall** (gold fields extracted correctly): {tot['correct']}/{tot['gold']} = {tot['correct'] / tot['gold']:.1%}",
            f"- **Field precision** (predicted fields that are correct): {tot['pred_correct']}/{tot['pred']} = {tot['pred_correct'] / max(tot['pred'], 1):.1%}",
            f"- **Hallucinated fields** (value predicted, gold is empty): {tot['halluc']}",
            f"- **Line-item recall** (by amount): {tot['items_found']}/{tot['items_gold']} = {tot['items_found'] / tot['items_gold']:.1%}",
            f"- **Errors caught by review routing** (wrong values with confidence < {REVIEW_THRESHOLD} or listed in needs_review): "
            f"{wrong_flagged}/{wrong_total}" + (f" = {wrong_flagged / wrong_total:.0%}" if wrong_total else ""),
            "", "## Calibration (predicted scalar fields + line-item amounts)", "",
            "| confidence | n | accuracy | mean confidence |", "|---|---|---|---|"]
    ece = 0.0
    for lo, hi in BUCKETS:
        b = [(c, ok) for c, ok in obs if lo <= c < hi]
        if b:
            acc = sum(ok for _, ok in b) / len(b)
            mc = sum(c for c, _ in b) / len(b)
            ece += len(b) / len(obs) * abs(acc - mc)
            out.append(f"| {lo:.2f}-{min(hi, 1):.2f} | {len(b)} | {acc:.0%} | {mc:.2f} |")
    out += ["", f"Expected calibration error (ECE): **{ece:.3f}** (lower is better; 0 = perfectly calibrated)", "",
            "## Errors by document", ""]
    for name, _, _, d, *_ in rows:
        if d["wrong"]:
            out.append(f"**{name}**")
            out += [f"- {w}" for w in d["wrong"]]
            out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="enable the Claude extractor")
    ap.add_argument("--set", choices=["dev", "holdout"], default="dev",
                    help="dev = samples the rules were developed on; holdout = unseen during development")
    ap.add_argument("--write", action="store_true", help="also write eval/results_<set>_<mode>.md")
    a = ap.parse_args()
    report = evaluate(a.llm, ROOT / "samples" / ("holdout" if a.set == "holdout" else ""))
    print(report)
    if a.write:
        (ROOT / "eval" / f"results_{a.set}_{'llm' if a.llm else 'rules'}.md").write_text(report + "\n")
