"""``co-extract FILE_OR_DIR [...]`` -- run the pipeline and write JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extractors.llm import DEFAULT_MODEL
from .pipeline import run

SUPPORTED = {".pdf", ".txt", ".md", ".eml"}


def _inputs(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in map(Path, paths):
        out.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED) if p.is_dir() else [p])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="co-extract", description=__doc__)
    ap.add_argument("inputs", nargs="+", help="PDF/text files or directories")
    ap.add_argument("-o", "--out", help="directory to write <name>.json results (default: stdout)")
    llm = ap.add_mutually_exclusive_group()
    llm.add_argument("--llm", dest="use_llm", action="store_true", default=None, help="force the Claude extractor on")
    llm.add_argument("--no-llm", dest="use_llm", action="store_false", help="rules extractor only (offline)")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--summary", action="store_true", help="print a one-line summary per document to stderr")
    args = ap.parse_args(argv)

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in _inputs(args.inputs):
        res = run(path, use_llm=args.use_llm, model=args.model)
        data = res.model_dump(mode="json")
        if out_dir:
            (out_dir / f"{path.stem}.json").write_text(json.dumps(data, indent=2) + "\n")
        else:
            results.append(data)
        if args.summary or out_dir:
            total = res.fields["total_change_amount"]
            print(f"{path.name:36s} {res.status:13s} overall={res.overall_confidence:.2f} "
                  f"total={total.value} ({total.confidence:.2f}) review={len(res.needs_review)} "
                  f"extractors={'+'.join(res.meta['extractors'])}", file=sys.stderr)
    if not out_dir:
        json.dump(results[0] if len(results) == 1 else results, sys.stdout, indent=2)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
