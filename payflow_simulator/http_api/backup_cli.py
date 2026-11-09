"""Verify, back up, and restore SQLite databases without overwriting a target."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def backup(source: Path, target: Path) -> dict[str, object]:
    source = source.resolve(); target = target.resolve()
    if not source.is_file(): raise FileNotFoundError(f"source database does not exist: {source}")
    if source == target or target.exists(): raise FileExistsError("backup target must be a new path, separate from the source")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(temp_name, timeout=30)
        try:
            src.backup(dst, pages=256, sleep=.05)
            dst.commit()
            _integrity(dst)
        finally:
            dst.close(); src.close()
        os.replace(temp_name, target)
        metadata = {"created_at":_now(),"source_name":source.name,"size_bytes":target.stat().st_size,
                    "sha256":_sha256(target),"integrity":"ok","schema_version":_schema_version(target)}
        sidecar = target.with_suffix(target.suffix + ".json")
        sidecar.write_text(json.dumps(metadata, indent=2, sort_keys=True)+"\n", encoding="utf-8")
        return metadata
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)


def verify(path: Path) -> dict[str, object]:
    if not path.is_file(): raise FileNotFoundError(path)
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try: _integrity(db)
    finally: db.close()
    result: dict[str, object] = {"integrity":"ok","size_bytes":path.stat().st_size,"sha256":_sha256(path),"schema_version":_schema_version(path)}
    sidecar = path.with_suffix(path.suffix + ".json")
    if sidecar.exists():
        metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        result["checksum_matches"] = metadata.get("sha256") == result["sha256"]
        if not result["checksum_matches"]: raise ValueError("backup checksum does not match its manifest")
    return result


def restore(source: Path, target: Path) -> dict[str, object]:
    source = source.resolve(); target = target.resolve()
    verify(source)
    if source == target or target.exists():
        raise FileExistsError("restore destination must be a new path; active databases are never overwritten")
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=30)
    dst = sqlite3.connect(target, timeout=30)
    try:
        src.backup(dst, pages=256, sleep=.05)
        dst.commit(); _integrity(dst)
    except Exception:
        dst.close(); src.close()
        target.unlink(missing_ok=True)
        raise
    else:
        dst.close(); src.close()
    return verify(target)


def _integrity(db: sqlite3.Connection) -> None:
    result = db.execute("PRAGMA integrity_check").fetchone()
    if not result or result[0] != "ok": raise ValueError(f"SQLite integrity_check failed: {result[0] if result else 'no result'}")


def _schema_version(path: Path) -> int:
    db = sqlite3.connect(f"file:{path.resolve()}?mode=ro", uri=True)
    try:
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'").fetchone()
        return int(db.execute("SELECT COALESCE(MAX(version),0) FROM schema_migrations").fetchone()[0]) if exists else 0
    finally: db.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024), b""): digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z")


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    make=sub.add_parser("backup");make.add_argument("--database",type=Path,required=True);make.add_argument("--output",type=Path,required=True)
    check=sub.add_parser("verify");check.add_argument("--backup",type=Path,required=True)
    recover=sub.add_parser("restore");recover.add_argument("--backup",type=Path,required=True);recover.add_argument("--target",type=Path,required=True)
    args=parser.parse_args()
    result=backup(args.database,args.output) if args.command=="backup" else verify(args.backup) if args.command=="verify" else restore(args.backup,args.target)
    print(json.dumps(result,indent=2,sort_keys=True))


if __name__=="__main__":main()
