#!/usr/bin/env python3
"""zune-batch — add several album folders to the Zune HD in one run.

Usage: zune_batch.py <folder1> <folder2> ...  [-- passthrough zune_add args]
Any args after `--` are forwarded to zune_add.py (e.g. --yes --replace).
"""
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ADD = os.path.join(HERE, "zune_add.py")


def main():
    argv = sys.argv[1:]
    passthrough = []
    if "--" in argv:
        i = argv.index("--")
        passthrough = argv[i + 1:]
        argv = argv[:i]
    if not argv:
        sys.exit("Usage: zune_batch.py <folder>... [-- --yes --replace ...]")
    if "--yes" not in passthrough:
        passthrough.append("--yes")   # batch mode shouldn't block on prompts

    results = []
    for folder in argv:
        print("\n" + "=" * 70)
        print(f"ALBUM: {folder}")
        print("=" * 70)
        rc = subprocess.run([sys.executable, ADD, folder, *passthrough]).returncode
        results.append((folder, rc))

    print("\n" + "=" * 70 + "\nBATCH SUMMARY")
    for folder, rc in results:
        print(f"  [{'OK ' if rc == 0 else 'FAIL'}] {os.path.basename(folder)}")
    sys.exit(0 if all(rc == 0 for _, rc in results) else 1)


if __name__ == "__main__":
    main()
