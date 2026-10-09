"""Restore safeguards must reject real or nonempty databases before loading SQL."""
import pytest

from scripts.database_backup import restore_disposable


def test_restore_rejects_non_disposable_target_before_read(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTORE_DATABASE_URL", "mysql+pymysql://synthetic:synthetic@localhost/user_database")
    with pytest.raises(ValueError, match="disposable"):
        restore_disposable(tmp_path / "missing.sql", "user_database")


def test_restore_rejects_database_mismatch_before_read(monkeypatch, tmp_path):
    monkeypatch.setenv("RESTORE_DATABASE_URL", "mysql+pymysql://synthetic:synthetic@localhost/ayursage_test_a")
    with pytest.raises(ValueError, match="disposable"):
        restore_disposable(tmp_path / "missing.sql", "ayursage_test_b")
