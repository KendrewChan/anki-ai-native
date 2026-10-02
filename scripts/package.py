#!/usr/bin/env python3
"""Build dist/anki_ai.ankiaddon — a zip of addon/'s contents, without caches, the user's meta.json or user_files."""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "addon")
OUT = os.path.join(ROOT, "dist", "anki_ai.ankiaddon")
SKIP_FILES = {"meta.json"}
SKIP_DIRS = {"__pycache__", "user_files"}  # user_files: what this machine learned; Anki keeps it on update

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in sorted(filenames):
            if name in SKIP_FILES or name.endswith(".pyc"):
                continue
            path = os.path.join(dirpath, name)
            z.write(path, os.path.relpath(path, SRC))  # files at the zip root, as Anki expects
    names = z.namelist()
print(f"{OUT}\n  " + "\n  ".join(names))
