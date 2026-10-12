#!/usr/bin/env python3
"""Download the Conference v3.0 Turtle datasets from the pinned upstream commit.

Alternative to scripts/setup_data.py (which uses the bundled archive
data/datasets.tar.gz). Files are fetched from

    https://framagit.org/IRIT_UT2J/conference-dataset-population
    commit 24b9f1af82791fb65e27fd682b64c804dc703fe4

written to data/datasets/, and accepted only if their SHA-256 matches.

    python scripts/fetch_data.py --dry-run   # print the URLs, download nothing
    python scripts/fetch_data.py             # download missing / mismatching files
    python scripts/fetch_data.py --force     # re-download everything

Only the Python standard library is used.
"""
import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / "data" / "datasets"
REPO = "https://framagit.org/IRIT_UT2J/conference-dataset-population"
COMMIT = "24b9f1af82791fb65e27fd682b64c804dc703fe4"
URL_TEMPLATE = REPO + "/-/raw/{commit}/{path}"

# local name -> (path in the upstream repository, SHA-256)
FILES = {
    "cmt_100.ttl": ("populated_datasets/data_100/cmt_100.ttl", "efb7e8c7f377ef2bd70c1a855945fe093ccd78f986c3055c1fcf9a87c5ea900b"),
    "cmt_eswc.ttl": ("populated_datasets/eswc/cmt_eswc.ttl", "0a7266f947fee4c728a578f891e4cf9745e33fb4d68bdce29fb02b484fe18f79"),
    "confOf_100.ttl": ("populated_datasets/data_100/confOf_100.ttl", "714650f583fe4df9d199aaecfc1e9092e1d138a4e79d7b9e2bb68f6013bcfed2"),
    "confOf_eswc.ttl": ("populated_datasets/eswc/confOf_eswc.ttl", "9cab64d89360dfee2a3a353e46281453946d425a3ec43546e5f2d40709458397"),
    "conference_100.ttl": ("populated_datasets/data_100/conference_100.ttl", "92bb1dad519a35a74d9430e4dddaf40397329acdcd22866b225a37d2e7cf8a5a"),
    "conference_eswc.ttl": ("populated_datasets/eswc/conference_eswc.ttl", "09640354e338ee254e2af3ed1d9cffc2c75bb49d7a92a47c2e10da90d0fa22d4"),
    "edas_100.ttl": ("populated_datasets/data_100/edas_100.ttl", "edde61de152ef35e85f98b0b259ea06be635f91fb2fc07b4859fe2e9bfe037bf"),
    "edas_eswc.ttl": ("populated_datasets/eswc/edas_eswc.ttl", "5c02be548fee2ed62c269bfcc894a069d2ba970c1e76858f11dc70d4311966d2"),
    "ekaw_100.ttl": ("populated_datasets/data_100/ekaw_100.ttl", "68892fab8fbf81c1a79125189fb2cc06dfb344b71c7bd0f41c5c32ff053161a9"),
    "ekaw_eswc.ttl": ("populated_datasets/eswc/ekaw_eswc.ttl", "9bc91a61a626b54c8d05511b4d8e454b8a3f189523c46815009919975c95249f"),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print URLs only")
    ap.add_argument("--force", action="store_true", help="download even if a valid file exists")
    ap.add_argument("--timeout", type=int, default=120, help="per-request timeout in seconds")
    args = ap.parse_args()
    DEST.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, (upath, want) in sorted(FILES.items()):
        url = URL_TEMPLATE.format(commit=COMMIT, path=upath)
        target = DEST / name
        if args.dry_run:
            print(f"{url} -> {target.relative_to(ROOT)}  sha256={want}")
            continue
        if not args.force and target.is_file() and sha256(target) == want:
            print(f"present  {target.relative_to(ROOT)}")
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            with urllib.request.urlopen(url, timeout=args.timeout) as r, open(tmp, "wb") as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
        except Exception as e:  # network / HTTP error
            print(f"FAILED   {name}: {e}", file=sys.stderr)
            if tmp.exists():
                tmp.unlink()
            failed += 1
            continue
        got = sha256(tmp)
        if got != want:
            print(f"MISMATCH {name}: got {got}, expected {want}", file=sys.stderr)
            tmp.unlink()
            failed += 1
            continue
        tmp.replace(target)
        print(f"wrote    {target.relative_to(ROOT)}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
