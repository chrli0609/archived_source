#!/usr/bin/env python3
"""
Extract files and directories from the archive text file created by archive_dir.py.

Usage:
    python extract_archive.py /path/to/archive.txt /path/to/output_dir

Safety:
- Paths in the archive are treated as relative paths and are protected from path-traversal;
  attempts to write outside the output directory will raise an error.
- The script will create directories as needed, restore symlinks (if supported), and set file modes and mtime.
"""
import argparse
import base64
import json
import os
import stat
import sys
import time
from pathlib import Path

MAGIC = "FILE_ARCHIVE_V1"

def safe_join_and_check(base: Path, rel_posix: str) -> Path:
    # Convert posix path into Path and ensure it stays inside base when resolved.
    candidate = base.joinpath(*Path(rel_posix).parts)
    try:
        resolved = candidate.resolve()
    except FileNotFoundError:
        # If parent doesn't exist yet, resolve the parent
        resolved = (candidate.parent.resolve() / candidate.name)
    if not str(resolved).startswith(str(base.resolve())):
        raise RuntimeError(f"Path traversal detected for entry: {rel_posix}")
    return candidate

def set_stat(path: Path, mode: int = None, mtime: float = None):
    if mode is not None:
        try:
            os.chmod(path, stat.S_IMODE(mode))
        except OSError:
            # ignore chmod failures on some platforms
            pass
    if mtime is not None:
        try:
            os.utime(path, (mtime, mtime), follow_symlinks=False)
        except OSError:
            pass

def main():
    p = argparse.ArgumentParser(description="Extract archive text file into directory")
    p.add_argument("archive_file", help="Text archive file produced by archive_dir.py")
    p.add_argument("output_dir", help="Directory to create and populate")
    args = p.parse_args()

    archive = Path(args.archive_file)
    outdir = Path(args.output_dir).resolve()
    if not archive.is_file():
        raise SystemExit(f"Archive file {archive} does not exist")

    outdir.mkdir(parents=True, exist_ok=True)

    with archive.open("r", encoding="utf-8") as fh:
        first = fh.readline().rstrip("\n")
        if first != MAGIC:
            # Allow both header-present and header-absent formats by treating first as data if parseable
            try:
                # try to parse first JSON line as an entry; if it fails we'll raise.
                entry = json.loads(first)
                entries_iter = ( (entry,) + tuple(json.loads(line) for line in fh if line.strip()) )
                # But building a giant tuple is memory-inefficient; instead re-open.
                fh.close()
                fh = archive.open("r", encoding="utf-8")
                # We'll skip magic-check and iterate normally
                lines_iter = fh
            except Exception:
                raise SystemExit("Archive header missing or invalid and first line is not JSON; aborting.")
        # Normal case when header matches: iterate rest of lines
        if first == MAGIC:
            lines_iter = fh

        # Process entries line by line
        for raw in lines_iter:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError as e:
                print(f"Skipping invalid JSON line: {e}", file=sys.stderr)
                continue

            typ = entry.get("type")
            rel = entry.get("path", ".")
            try:
                target_path = safe_join_and_check(outdir, rel)
            except RuntimeError as e:
                print(f"Security error: {e}", file=sys.stderr)
                continue

            if typ == "dir":
                target_path.mkdir(parents=True, exist_ok=True)
                set_stat(target_path, entry.get("mode"), entry.get("mtime"))
            elif typ == "symlink":
                # create parent dir if needed
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target = entry.get("target", "")
                try:
                    # If there's already something at that path, remove it first
                    if target_path.exists() or target_path.is_symlink():
                        try:
                            if target_path.is_dir() and not target_path.is_symlink():
                                os.rmdir(target_path)
                            else:
                                target_path.unlink()
                        except Exception:
                            pass
                    os.symlink(target, target_path)
                except OSError as e:
                    print(f"Failed to create symlink {target_path} -> {target}: {e}", file=sys.stderr)
                set_stat(target_path, entry.get("mode"), entry.get("mtime"))
            elif typ == "file":
                content_b64 = entry.get("content", "")
                try:
                    data = base64.b64decode(content_b64)
                except Exception as e:
                    print(f"Failed to decode content for {rel}: {e}", file=sys.stderr)
                    data = b""
                # ensure parent dir exists
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with target_path.open("wb") as wf:
                        wf.write(data)
                except OSError as e:
                    print(f"Failed to write file {target_path}: {e}", file=sys.stderr)
                    continue
                set_stat(target_path, entry.get("mode"), entry.get("mtime"))
            else:
                print(f"Unknown entry type '{typ}' for path {rel}; skipping", file=sys.stderr)

    print(f"Extraction complete to {outdir}")

if __name__ == "__main__":
    main()
