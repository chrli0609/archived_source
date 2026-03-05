#!/usr/bin/env python3
"""
Archive a directory into a single text file.

Usage:
    python archive_dir.py /path/to/source_dir /path/to/archive.txt

The archive format:
- First line is a magic header: "FILE_ARCHIVE_V1"
- Each following line is a JSON object (one per line) describing an item:
  - directory:
      { "type": "dir", "path": "relative/path", "mode": <int>, "mtime": <float> }
  - file:
      { "type": "file", "path": "relative/path", "mode": <int>, "mtime": <float>, "content": "<base64 str>" }
  - symlink:
      { "type": "symlink", "path": "relative/path", "target": "<link-target>", "mode": <int>, "mtime": <float> }

Paths use POSIX-style forward slashes and are relative to the source directory.
"""
import argparse
import base64
import json
import os
import stat
from pathlib import Path

MAGIC = "FILE_ARCHIVE_V1"

def posix_rel_path(base: Path, path: Path) -> str:
    return Path(path).relative_to(base).as_posix() or "."

def should_skip_path(abs_path: Path, out_file: Path) -> bool:
    try:
        return out_file.resolve() == abs_path.resolve()
    except Exception:
        return False

def main():
    p = argparse.ArgumentParser(description="Archive directory to a single text file")
    p.add_argument("source_dir", help="Directory to archive")
    p.add_argument("output_file", help="Output text archive")
    args = p.parse_args()

    src = Path(args.source_dir).resolve()
    out = Path(args.output_file).resolve()

    if not src.is_dir():
        raise SystemExit(f"Source {src} is not a directory")

    # If the output is inside source, we'll still create the archive but we must avoid including the archive file itself.
    # We'll check each file's path and skip if it equals the output file.
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(MAGIC + "\n")

        # Walk directories top-down so directories can be written before their contents.
        for root, dirnames, filenames in os.walk(src, topdown=True, followlinks=False):
            root_path = Path(root)

            # Write the directory record for this root (including root itself).
            rel_dir = posix_rel_path(src, root_path)
            st = root_path.lstat()
            dir_entry = {
                "type": "dir",
                "path": rel_dir,
                "mode": st.st_mode,
                "mtime": st.st_mtime
            }
            fh.write(json.dumps(dir_entry, ensure_ascii=False) + "\n")

            # Handle directories that are symlinks in dirnames: os.walk normally lists symlinked dirs in dirnames but doesn't traverse if followlinks=False
            # We'll convert any symlinked directories into a symlink entry and remove them from dirnames to avoid descending into them.
            for d in list(dirnames):  # copy because we might modify dirnames
                pth = root_path / d
                if pth.is_symlink():
                    # replace the dir record with a symlink record
                    rel = posix_rel_path(src, pth)
                    try:
                        target = os.readlink(pth)
                    except OSError:
                        target = ""
                    st = pth.lstat()
                    symlink_entry = {
                        "type": "symlink",
                        "path": rel,
                        "target": target,
                        "mode": st.st_mode,
                        "mtime": st.st_mtime
                    }
                    fh.write(json.dumps(symlink_entry, ensure_ascii=False) + "\n")
                    # prevent descending into it
                    dirnames.remove(d)

            # Files
            for fname in filenames:
                fpath = root_path / fname
                if should_skip_path(fpath, out):
                    # skip writing the archive file into itself
                    continue
                rel = posix_rel_path(src, fpath)
                try:
                    st = fpath.lstat()
                except FileNotFoundError:
                    # file disappeared between listing and reading
                    continue

                if fpath.is_symlink():
                    # record symlink target
                    try:
                        target = os.readlink(fpath)
                    except OSError:
                        target = ""
                    symlink_entry = {
                        "type": "symlink",
                        "path": rel,
                        "target": target,
                        "mode": st.st_mode,
                        "mtime": st.st_mtime
                    }
                    fh.write(json.dumps(symlink_entry, ensure_ascii=False) + "\n")
                    continue

                # Regular file: read bytes and base64-encode
                try:
                    with fpath.open("rb") as rf:
                        b = rf.read()
                except OSError as e:
                    print(f"Warning: cannot read {fpath}: {e}")
                    continue

                content_b64 = base64.b64encode(b).decode("ascii")
                file_entry = {
                    "type": "file",
                    "path": rel,
                    "mode": st.st_mode,
                    "mtime": st.st_mtime,
                    "content": content_b64
                }
                fh.write(json.dumps(file_entry, ensure_ascii=False) + "\n")

    print(f"Archive written to {out}")

if __name__ == "__main__":
    main()
