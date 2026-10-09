"""Explicit MySQL logical backup and disposable-only restore with SHA-256 proof.

Requires mysql and mysqldump clients on PATH. URLs come only from environment;
credentials never appear in command arguments or logged errors.
"""
import argparse
import hashlib
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote

from sqlalchemy.engine import make_url


def connection(name):
    raw = os.environ.get(name)
    if not raw:
        raise ValueError(f"{name} is required")
    url = make_url(raw)
    if url.drivername != "mysql+pymysql" or not all((url.host, url.database, url.username, url.password)):
        raise ValueError(f"{name} must be a complete mysql+pymysql URL")
    return url


def args(url):
    return ["--host", url.host, "--port", str(url.port or 3306),
            "--user", url.username, "--default-character-set=utf8mb4"]


def safe_env(url):
    env = os.environ.copy()
    env["MYSQL_PWD"] = unquote(url.password)
    return env


def checksum(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup(path):
    url = connection("BACKUP_DATABASE_URL")
    path = Path(path)
    if path.exists() or path.with_suffix(path.suffix + ".sha256").exists():
        raise ValueError("Backup target already exists")
    if not path.parent.is_dir():
        raise ValueError("Backup parent directory must already exist")
    try:
        with path.open("xb") as stream:
            subprocess.run(["mysqldump", *args(url), "--single-transaction", "--routines", "--triggers",
                            "--set-gtid-purged=OFF", "--no-tablespaces", url.database],
                           stdout=stream, stderr=subprocess.DEVNULL, env=safe_env(url), check=True)
        path.with_suffix(path.suffix + ".sha256").write_text(checksum(path) + "\n", encoding="ascii")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def restore_disposable(path, expected_database):
    url = connection("RESTORE_DATABASE_URL")
    if not expected_database.startswith("ayursage_test_") or url.database != expected_database:
        raise ValueError("Restore requires an explicitly named disposable ayursage_test_ database")
    path = Path(path)
    expected = path.with_suffix(path.suffix + ".sha256").read_text(encoding="ascii").strip()
    if len(expected) != 64 or checksum(path) != expected:
        raise ValueError("Backup checksum mismatch")
    # A fresh database is mandatory: existing data must never be overwritten.
    with subprocess.Popen(["mysql", *args(url), "--batch", "--skip-column-names", url.database,
                           "-e", "SHOW TABLES"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          env=safe_env(url)) as probe:
        if probe.stdout.read().strip() or probe.wait() != 0:
            raise ValueError("Disposable restore database must exist and be empty")
    with path.open("rb") as stream:
        subprocess.run(["mysql", *args(url), url.database], stdin=stream,
                       stderr=subprocess.DEVNULL, env=safe_env(url), check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "restore-disposable"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--database", help="Exact disposable schema name for restore")
    options = parser.parse_args()
    try:
        if options.action == "backup":
            backup(options.path)
        else:
            restore_disposable(options.path, options.database or "")
    except Exception as error:
        print(f"Database operation failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
