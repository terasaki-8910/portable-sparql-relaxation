#!/usr/bin/env python3
"""Extract the Conference v3.0 Turtle datasets and verify their SHA-256.

    python scripts/setup_data.py            # extract data/datasets.tar.gz -> data/datasets/
    python scripts/setup_data.py --verify   # only verify files already in data/datasets/

Only the Python standard library is used. Files already present with the
expected hash are left untouched. Exit status 1 on any mismatch.
"""
import argparse
import hashlib
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE = ROOT / "data" / "datasets.tar.gz"
DEST = ROOT / "data" / "datasets"

# SHA-256 of the upstream files (Conference v3.0, https://framagit.org/IRIT_UT2J/conference-dataset-population
# commit 24b9f1af82791fb65e27fd682b64c804dc703fe4).
EXPECTED = {
    "cmt_100.ttl": "efb7e8c7f377ef2bd70c1a855945fe093ccd78f986c3055c1fcf9a87c5ea900b",
    "cmt_eswc.ttl": "0a7266f947fee4c728a578f891e4cf9745e33fb4d68bdce29fb02b484fe18f79",
    "confOf_100.ttl": "714650f583fe4df9d199aaecfc1e9092e1d138a4e79d7b9e2bb68f6013bcfed2",
    "confOf_eswc.ttl": "9cab64d89360dfee2a3a353e46281453946d425a3ec43546e5f2d40709458397",
    "conference_100.ttl": "92bb1dad519a35a74d9430e4dddaf40397329acdcd22866b225a37d2e7cf8a5a",
    "conference_eswc.ttl": "09640354e338ee254e2af3ed1d9cffc2c75bb49d7a92a47c2e10da90d0fa22d4",
    "edas_100.ttl": "edde61de152ef35e85f98b0b259ea06be635f91fb2fc07b4859fe2e9bfe037bf",
    "edas_eswc.ttl": "5c02be548fee2ed62c269bfcc894a069d2ba970c1e76858f11dc70d4311966d2",
    "ekaw_100.ttl": "68892fab8fbf81c1a79125189fb2cc06dfb344b71c7bd0f41c5c32ff053161a9",
    "ekaw_eswc.ttl": "9bc91a61a626b54c8d05511b4d8e454b8a3f189523c46815009919975c95249f",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify():
    bad = 0
    for name, want in sorted(EXPECTED.items()):
        p = DEST / name
        if not p.is_file():
            print(f"MISSING  {p.relative_to(ROOT)}")
            bad += 1
            continue
        got = sha256(p)
        ok = got == want
        bad += 0 if ok else 1
        print(f"{'OK      ' if ok else 'MISMATCH'} {p.relative_to(ROOT)}")
    return bad


def extract():
    if not ARCHIVE.is_file():
        print(f"archive not found: {ARCHIVE}", file=sys.stderr)
        return 1
    DEST.mkdir(parents=True, exist_ok=True)
    with tarfile.open(ARCHIVE, "r:gz") as tar:
        for m in tar.getmembers():
            name = m.name
            if not m.isfile() or "/" in name or "\\" in name or name not in EXPECTED:
                print(f"refusing unexpected archive member: {name!r}", file=sys.stderr)
                return 1
            target = DEST / name
            if target.is_file() and sha256(target) == EXPECTED[name]:
                print(f"present  {target.relative_to(ROOT)}")
                continue
            data = tar.extractfile(m).read()
            if hashlib.sha256(data).hexdigest() != EXPECTED[name]:
                print(f"hash mismatch inside archive for {name}", file=sys.stderr)
                return 1
            tmp = target.with_suffix(target.suffix + ".part")
            tmp.write_bytes(data)
            tmp.replace(target)
            print(f"wrote    {target.relative_to(ROOT)}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verify", action="store_true", help="only verify, do not extract")
    args = ap.parse_args()
    if not args.verify:
        rc = extract()
        if rc:
            return rc
    return 1 if verify() else 0


if __name__ == "__main__":
    sys.exit(main())
