from contextlib import closing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from migrate_utc_times import migrate
from time_utils import KST, korea_now


class TimeTests(unittest.TestCase):
    def test_korean_time_crosses_day_boundary(self):
        instant = datetime(2026, 10, 7, 18, 30, tzinfo=timezone.utc)
        with patch('time_utils.datetime') as clock:
            clock.now.return_value = instant.astimezone(KST)
            self.assertEqual(korea_now(), datetime(2026, 10, 8, 3, 30))
            clock.now.assert_called_once_with(KST)

    def test_migration_keeps_backup_and_runs_once(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'test.db'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.executescript('''
                    CREATE TABLE employees(id INTEGER PRIMARY KEY, last_updated TEXT, privacy_agreed_at TEXT);
                    CREATE TABLE gift_options(id INTEGER PRIMARY KEY, created_at TEXT);
                    CREATE TABLE system_settings(key TEXT PRIMARY KEY, value TEXT);
                    INSERT INTO employees VALUES(1,'2026-10-07 18:30:00',NULL);
                    INSERT INTO gift_options VALUES(1,'2026-10-07 08:30:00');
                    INSERT INTO system_settings VALUES('last_upload_time','2026-10-07 18:30');
                ''')
            migrate(path)
            migrate(path)
            with closing(sqlite3.connect(path)) as conn, conn:
                self.assertEqual(conn.execute('SELECT last_updated,privacy_agreed_at FROM employees').fetchone(),
                                 ('2026-10-08 03:30:00', None))
                self.assertEqual(conn.execute("SELECT value FROM system_settings WHERE key='last_upload_time'").fetchone()[0],
                                 '2026-10-08 03:30')
            with closing(sqlite3.connect(next(Path(folder).glob('*.before-kst-*')))) as backup:
                self.assertEqual(backup.execute('SELECT last_updated FROM employees').fetchone()[0], '2026-10-07 18:30:00')
