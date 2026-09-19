#!/usr/bin/env python3
"""Synthesise wrong-glyph-mapping PDF fixtures for xberg issue #1696, byte for byte.

xberg-native-pdf's `best_mapping_provenance` treats any non-empty /ToUnicode CMap as an
authoritative decode, but no renderer reads /ToUnicode -- it only guides copy-paste and text
extraction. A CMap that decodes to the wrong letters is therefore invisible to any check that
renders the page, while every naive text extraction of it is silently wrong. This script builds
that exact fixture shape from a clean source: it rewrites every font's /ToUnicode CMap with a
ROT-3 letter substitution and leaves everything else -- content streams, embedded font programs,
/Encoding /Differences -- untouched, so the rendered page stays byte-identical while the decoded
text does not.

Each recipe is a (source path, output stem) pair. For each:

  1. `qpdf --qdf --object-streams=disable --stream-data=uncompress` the source into plain-text QDF.
  2. Walk the page tree to find every font used on every page; abort if any lacks /ToUnicode
     (that source is unsuitable -- pick another).
  3. Rewrite each distinct ToUnicode CMap stream's mapping body (corpus_tools.wrong_mapping.cmap).
  4. `fix-qdf` to repair cross-references, then `qpdf --deterministic-id` to the final path.

`--check` rebuilds every recipe into a temp directory and diffs the bytes against what's already
committed at pdf/wrong_mapping/<stem>.pdf, the same contract as build_diagram_pdfs.py --check.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from corpus_tools.hashing import sha256_file
from corpus_tools.paths import REPO_ROOT
from corpus_tools.wrong_mapping.qdf import (
    QdfDocument,
    UnsuitableSourceError,
    rewrite_to_unicode_streams,
    to_unicode_object_numbers,
)

# (source relative path, output stem) -- all three sources are readoc-github README PDFs,
# MIT-licensed, chosen because every font on every page already carries /ToUnicode. See
# pdf/wrong_mapping/PROVENANCE.md for why these three and not the FinTabNet/arXiv candidates.
RECIPES: dict[str, str] = {
    "pdf/177210299.pdf": "wrong_mapping_177210299",
    "pdf/276728418.pdf": "wrong_mapping_276728418",
    "pdf/290573779.pdf": "wrong_mapping_290573779",
}

OUTPUT_DIR = REPO_ROOT / "pdf" / "wrong_mapping"


def run(argv: list[str]) -> None:
    result = subprocess.run(argv, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"{argv[0]} failed (exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )


def build(stem: str, source: Path, workspace: Path) -> tuple[Path, int]:
    """Build one fixture; returns (finished path, count of ToUnicode streams rewritten)."""
    qdf_path = workspace / f"{stem}.qdf"
    run(["qpdf", "--qdf", "--object-streams=disable", "--stream-data=uncompress", str(source), str(qdf_path)])

    document = QdfDocument.parse(qdf_path.read_bytes())
    stream_objects = to_unicode_object_numbers(document)  # raises UnsuitableSourceError if incomplete
    rewritten = rewrite_to_unicode_streams(document, stream_objects)
    qdf_path.write_bytes(rewritten)

    fixed_path = workspace / f"{stem}.fixed.qdf"
    fix_result = subprocess.run(["fix-qdf"], stdin=qdf_path.open("rb"), capture_output=True)
    if fix_result.returncode != 0:
        raise RuntimeError(
            f"fix-qdf failed (exit {fix_result.returncode}): {fix_result.stderr.decode('latin-1', 'replace')}"
        )
    fixed_path.write_bytes(fix_result.stdout)

    finished = workspace / f"{stem}.pdf"
    run(["qpdf", "--deterministic-id", str(fixed_path), str(finished)])
    return finished, len(stream_objects)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="rebuild and compare, changing nothing on disk")
    parser.add_argument("--only", action="append", default=[], help="build one target stem (repeatable)")
    arguments = parser.parse_args(argv)

    for tool in ("qpdf", "fix-qdf"):
        if shutil.which(tool) is None:
            print(f"{tool} not found on PATH", file=sys.stderr)
            return 2

    targets = arguments.only or sorted(RECIPES.values())
    stem_to_source = {stem: source for source, stem in RECIPES.items()}
    unknown = [target for target in targets if target not in stem_to_source]
    if unknown:
        print(f"unknown target(s): {', '.join(unknown)}", file=sys.stderr)
        return 2

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = []
    for stem in targets:
        source = REPO_ROOT / stem_to_source[stem]
        with tempfile.TemporaryDirectory() as directory:
            try:
                finished, rewritten_count = build(stem, source, Path(directory))
            except (RuntimeError, FileNotFoundError, UnsuitableSourceError) as error:
                print(f"fail {stem}: {error}", file=sys.stderr)
                failures.append(stem)
                continue
            destination = OUTPUT_DIR / f"{stem}.pdf"
            if arguments.check:
                if not destination.is_file():
                    print(f"fail {stem}: not built yet", file=sys.stderr)
                    failures.append(stem)
                elif sha256_file(destination) != sha256_file(finished):
                    print(f"fail {stem}: rebuilt bytes differ from the committed file", file=sys.stderr)
                    failures.append(stem)
                else:
                    print(f"ok   {stem}  ({rewritten_count} ToUnicode stream(s) rewritten)")
            else:
                shutil.copyfile(finished, destination)
                print(
                    f"ok   {stem}  {sha256_file(destination)[:12]}  {destination.stat().st_size} bytes  ({rewritten_count} ToUnicode stream(s) rewritten)"
                )

    if failures:
        print(f"\n{len(failures)} of {len(targets)} failed", file=sys.stderr)
        return 1
    print(f"\n{len(targets)} of {len(targets)} ok", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
