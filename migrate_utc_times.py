"""One-time conversion for a database previously written on a UTC server.

Run only for known UTC data, before starting the KST application version.
Usage: python migrate_utc_times.py /absolute/path/employees.db
"""
from contextlib import closing
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path


def migrate(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        marker = 'utc_to_kst_migrated'
        if conn.execute('SELECT 1 FROM system_settings WHERE key=?', (marker,)).fetchone():
            print('Already migrated; no changes.')
            return
        # A separate reader backs up the committed state while writes are locked.
        backup = path.with_name(path.name + '.before-kst-' + datetime.now().strftime('%Y%m%d%H%M%S'))
        with closing(sqlite3.connect(path)) as source, closing(sqlite3.connect(backup)) as target:
            source.backup(target)
        for table, columns in (('employees', ('last_updated', 'privacy_agreed_at')),
                               ('gift_options', ('created_at',))):
            for column in columns:
                for row_id, value in conn.execute(f'SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL'):
                    if value:
                        converted = datetime.fromisoformat(value) + timedelta(hours=9)
                        conn.execute(f'UPDATE {table} SET {column}=? WHERE id=?',
                                     (converted.isoformat(sep=' ', timespec='seconds'), row_id))
        row = conn.execute("SELECT value FROM system_settings WHERE key='last_upload_time'").fetchone()
        if row and row[0] and row[0] != '-':
            converted = datetime.fromisoformat(row[0]) + timedelta(hours=9)
            conn.execute("UPDATE system_settings SET value=? WHERE key='last_upload_time'",
                         (converted.strftime('%Y-%m-%d %H:%M'),))
        conn.execute('INSERT INTO system_settings(key,value) VALUES(?,?)', (marker, 'true'))
    print(f'Converted UTC timestamps to KST. Backup: {backup}')


if __name__ == '__main__':
    migrate(sys.argv[1])
