from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from payflow_simulator.http_api.backup_cli import backup, restore, verify
from payflow_simulator.http_api.security import AuthStore, initialize_database


class Stage10PersistenceTests(unittest.TestCase):
    def setUp(self): self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()

    def test_versioned_bootstrap_preserves_preexisting_stage_data(self):
        path=self.root/"legacy.sqlite"; db=sqlite3.connect(path)
        db.execute("CREATE TABLE processed_events(event_id TEXT PRIMARY KEY,payload TEXT NOT NULL,processed_at TEXT NOT NULL)")
        db.execute("INSERT INTO processed_events VALUES('evt-1','{}','2025-01-01T00:00:00Z')");db.commit();db.close()
        initialize_database(path)
        self.assertEqual(AuthStore(path).list_users(), [])
        db=sqlite3.connect(path)
        self.assertEqual(db.execute("SELECT event_id FROM processed_events").fetchone()[0],"evt-1")
        self.assertEqual(db.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0],1)
        db.close()

    def test_backup_verify_restore_to_new_target_and_refuse_overwrite(self):
        original=self.root/"active.sqlite"; copy=self.root/"backup.sqlite"; recovered=self.root/"restored.sqlite"
        db=sqlite3.connect(original);db.execute("CREATE TABLE retained(id TEXT PRIMARY KEY)");db.execute("INSERT INTO retained VALUES('history-1')");db.commit();db.close()
        manifest=backup(original,copy)
        self.assertEqual(manifest["integrity"],"ok")
        self.assertTrue(verify(copy)["checksum_matches"])
        result=restore(copy,recovered)
        self.assertEqual(result["integrity"],"ok")
        db=sqlite3.connect(recovered);self.assertEqual(db.execute("SELECT id FROM retained").fetchone()[0],"history-1");db.close()
        with self.assertRaises(FileExistsError): restore(copy,original)
        db=sqlite3.connect(original);self.assertEqual(db.execute("SELECT id FROM retained").fetchone()[0],"history-1");db.close()


if __name__=="__main__":unittest.main()
