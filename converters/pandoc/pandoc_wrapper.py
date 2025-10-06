#!/usr/bin/env python3
"""
A very thin wrapper so every converter in the pipeline can be invoked with
`python <script> …`.  It simply shells out to the real `pandoc` binary.

Usage
-----
python pandoc_wrapper.py [extra pandoc flags] INPUT_FILE

The last argument is treated as the input file; everything before that is
forwarded verbatim to pandoc.  The output is placed in:

    <input_dir>/pandoc-output/<input_stem>.docx
"""
from __future__ import annotations
import subprocess, sys, pathlib


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        sys.exit("Usage: pandoc_wrapper.py [pandoc flags] INPUT")

    *pandoc_flags, input_path = argv
    inp = pathlib.Path(input_path).expanduser().resolve()
    if not inp.exists():
        sys.exit(f"[pandoc-wrapper] Input file not found: {inp}")

    # Output folder: alongside input, under `pandoc-output/`
    out_dir = inp.parent / "pandoc-output"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"{inp.stem}.docx"

    # Optional reference doc (ship one with your repo if desired)
    ref_doc = pathlib.Path(__file__).parent / "static" / "referenceDoc.docx"
    ref_flag = ["--reference-doc", str(ref_doc)] if ref_doc.exists() else []

    cmd = [
        "pandoc",
        str(inp),
        *pandoc_flags,         # user-supplied args (e.g. --strip-comments)
        *ref_flag,
        "-o", str(out_file),
    ]

    print("[pandoc-wrapper] ⮕", " ".join(cmd))
    subprocess.check_call(cmd)
    print(f"[pandoc-wrapper] ✔︎  wrote {out_file}")


if __name__ == "__main__":
    main(sys.argv[1:])
