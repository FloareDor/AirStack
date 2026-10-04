#!/usr/bin/env python3
"""Refuse to compare cells that were not flown on the same build.

Every flight writes provenance.json. Two cells are comparable only when the
worker image and both source trees match across all of their attempts. A
workspace rebuilds the worker image even at an identical git commit, so cells
from different workspaces are not comparable by default, and a cell flown
against a working tree with uncommitted edits is different again.

Usage:
    python3 check_provenance.py artifacts/pilot9/cell_*
"""
import argparse
import json
import pathlib
import sys

EMPTY_DIFF = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"

FIELDS = ("worker_image", "AirStack.head", "AirStack.diff_sha256",
          "mononav.head", "mononav.diff_sha256")


def dotted(record, path):
    value = record
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def build_of(provenance):
    record = json.loads(provenance.read_text())
    return tuple(str(dotted(record, field)) for field in FIELDS)


def builds_in(cell):
    found = {}
    for provenance in sorted(cell.rglob("provenance.json")):
        found.setdefault(build_of(provenance), []).append(provenance)
    return found


def short(value):
    if value.startswith("sha256:"):
        value = value[7:]
    return value[:8] if value not in ("None", "") else value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("cells", nargs="+", type=pathlib.Path)
    args = parser.parse_args(argv)

    everything = {}
    for cell in args.cells:
        if not cell.is_dir():
            print("not a directory: %s" % cell, file=sys.stderr)
            return 2
        found = builds_in(cell)
        if not found:
            print("%-42s no provenance.json found" % cell.name)
            return 2
        if len(found) > 1:
            print("%-42s SPLIT ACROSS %d BUILDS" % (cell.name, len(found)))
        for build, files in found.items():
            everything.setdefault(build, []).append((cell.name, len(files)))

    print()
    print("%-42s %-10s %-10s %-10s" % ("build", "worker", "airstack", "mononav"))
    print("-" * 74)
    for index, (build, cells) in enumerate(sorted(everything.items()), 1):
        worker, _, airstack_diff, _, mononav_diff = build
        label = "build %d" % index
        notes = []
        if airstack_diff != EMPTY_DIFF:
            notes.append("AirStack tree DIRTY")
        if mononav_diff != EMPTY_DIFF:
            notes.append("MonoNav tree DIRTY")
        print("%-42s %-10s %-10s %-10s %s"
              % (label, short(worker), short(airstack_diff), short(mononav_diff),
                 "  ".join(notes)))
        for name, count in cells:
            print("    %-38s %d flights" % (name, count))

    print()
    if len(everything) == 1:
        only = next(iter(everything))
        dirty = [name for name, value in zip(FIELDS, only)
                 if name.endswith("diff_sha256") and value != EMPTY_DIFF]
        if dirty:
            print("ONE BUILD, BUT THE TREE IS DIRTY: %s" % ", ".join(dirty))
            print("These cells compare to each other, but the run cannot be reproduced.")
            return 1
        print("ONE BUILD, CLEAN TREES. These cells are comparable.")
        return 0

    print("%d DIFFERENT BUILDS. These cells are NOT comparable." % len(everything))
    print("Do not quote a p-value across them. Fly a clean control in the same")
    print("workspace as the attack cells instead.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
