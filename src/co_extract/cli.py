"""``co-extract FILE_OR_DIR [...]`` -- run the pipeline and write JSON."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .pipeline import run

SUPPORTED = {".pdf", ".txt", ".md", ".eml"}


def _inputs(paths: list[str]) -> list[Path]:
    """Expand the given files and directories into a list of supported input files."""
    out: list[Path] = []
    for p in map(Path, paths):
        out.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in SUPPORTED) if p.is_dir() else [p])
    return out


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=value lines from ./.env (git-ignored) without overriding the real environment."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            os.environ.setdefault(key.removeprefix("export ").strip(), value.strip().strip("'\""))


def main(argv: list[str] | None = None) -> int:
    """Entry point for the co-extract command: parse arguments, run the pipeline, print or save JSON."""
    _load_dotenv()
    ap = argparse.ArgumentParser(prog="co-extract", description=__doc__)
    ap.add_argument("inputs", nargs="+", help="PDF/text files or directories")
    ap.add_argument("-o", "--out", help="directory to write <name>.json results (default: stdout)")
    llm = ap.add_mutually_exclusive_group()
    llm.add_argument("--llm", dest="use_llm", action="store_true", default=None, help="force the LLM extractor on")
    llm.add_argument("--no-llm", dest="use_llm", action="store_false", help="rules extractor only (offline)")
    ap.add_argument("--provider", choices=["auto", "claude", "gemini"], default="auto",
                    help="LLM to use; auto picks Claude if ANTHROPIC_API_KEY is set, else Gemini if GEMINI_API_KEY is set")
    ap.add_argument("--model", help="override the provider's default model")
    ap.add_argument("--summary", action="store_true", help="print a one-line summary per document to stderr")
    args = ap.parse_args(argv)

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
    results = []
    for path in _inputs(args.inputs):
        res = run(path, use_llm=args.use_llm, model=args.model, provider=args.provider)
        if res.meta.get("llm_error"):
            print(f"  ! {res.meta['llm_provider']} failed, used rules only: {res.meta['llm_error']}", file=sys.stderr)
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
