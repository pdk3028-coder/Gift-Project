import sqlite3
import os
import re
from pathlib import Path
from contextlib import contextmanager
import pandas as pd
from time_utils import korea_now
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = str(Path(os.environ.get('GIFT_DATABASE', Path(__file__).resolve().parent / 'employees.db')).resolve())

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def transaction():
    conn = get_db_connection()
    try:
        with conn:
            yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database with the employees table and migrates if needed."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Create employees table
    c.execute('''
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            emp_id TEXT NOT NULL UNIQUE,
            ssn TEXT DEFAULT '',  -- V17: SSN no longer required
            address_main TEXT,
            address_main_detail TEXT,  -- Added in V2
            phone TEXT,
            emergency_contact TEXT,
            gift_address TEXT,
            gift_address_detail TEXT,  -- Added in V2
            gift_receiver TEXT,
            privacy_agreed INTEGER DEFAULT 0, -- Added in V3
            privacy_agreed_at TIMESTAMP,      -- Added in V3
            zipcode TEXT,                     -- Added in V8
            gift_zipcode TEXT,                -- Added in V8
            last_updated TIMESTAMP
        )
    ''')
    
    # Create system_settings table (V5)
    c.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')
    
    # Migration for V2 & V3 & V8: Check if new columns exist
    cursor = c.execute("PRAGMA table_info(employees)")
    columns = [row[1] for row in cursor.fetchall()]
    
    if 'address_main_detail' not in columns:
        print("Migrating: Adding address_main_detail column")
        c.execute("ALTER TABLE employees ADD COLUMN address_main_detail TEXT")
        
    if 'gift_address_detail' not in columns:
        print("Migrating: Adding gift_address_detail column")
        c.execute("ALTER TABLE employees ADD COLUMN gift_address_detail TEXT")

    if 'privacy_agreed' not in columns:
        print("Migrating: Adding privacy_agreed column")
        c.execute("ALTER TABLE employees ADD COLUMN privacy_agreed INTEGER DEFAULT 0")

    if 'privacy_agreed_at' not in columns:
        print("Migrating: Adding privacy_agreed_at column")
        c.execute("ALTER TABLE employees ADD COLUMN privacy_agreed_at TIMESTAMP")
        
    if 'zipcode' not in columns:
        print("Migrating: Adding zipcode column")
        c.execute("ALTER TABLE employees ADD COLUMN zipcode TEXT")
        
    if 'gift_zipcode' not in columns:
        print("Migrating: Adding gift_zipcode column")
        c.execute("ALTER TABLE employees ADD COLUMN gift_zipcode TEXT")

    # V13 Migration: selected_gift_id
    if 'selected_gift_id' not in columns:
        print("Migrating: Adding selected_gift_id column")
        c.execute("ALTER TABLE employees ADD COLUMN selected_gift_id INTEGER")
        
    # V13: Create gift_options table
    c.execute('''
        CREATE TABLE IF NOT EXISTS gift_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            image_path TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP
        )
    ''')

    # V17 Migration: SSN 데이터 완전 제거 (민감개인정보 삭제)
    if 'ssn' in columns:
        cleared = c.execute("UPDATE employees SET ssn = '' WHERE ssn != ''").rowcount
        if cleared > 0:
            print(f"V17 Migration: {cleared}건의 SSN 데이터를 삭제했습니다.")

    # V18 Migration: 관리자 비밀번호 평문 -> 해시 변환
    pw_row = c.execute("SELECT value FROM system_settings WHERE key = 'admin_password'").fetchone()
    if pw_row:
        stored_pw = pw_row[0]
        # Werkzeug 해시는 'scrypt:' 또는 'pbkdf2:' 등으로 시작
        if not (stored_pw.startswith('scrypt:') or stored_pw.startswith('pbkdf2:')):
            hashed = generate_password_hash(stored_pw)
            c.execute("UPDATE system_settings SET value = ? WHERE key = 'admin_password'", (hashed,))
            print("V18 Migration: 관리자 비밀번호를 해시로 변환했습니다.")
    # A new database has no default password. Use the local set-admin-password command.

    # Repair legacy dangling selections and protect future writes, including races.
    c.execute('''UPDATE employees SET selected_gift_id = NULL
                 WHERE selected_gift_id IS NOT NULL AND selected_gift_id NOT IN
                 (SELECT id FROM gift_options)''')
    for operation in ('INSERT', 'UPDATE OF selected_gift_id'):
        trigger = 'employee_gift_' + operation.split()[0].lower()
        c.execute(f'''CREATE TRIGGER IF NOT EXISTS {trigger} BEFORE {operation} ON employees
            WHEN NEW.selected_gift_id IS NOT NULL AND NOT EXISTS
            (SELECT 1 FROM gift_options WHERE id = NEW.selected_gift_id AND is_active = 1)
            BEGIN SELECT RAISE(ABORT, 'invalid gift'); END''')

    conn.commit()
    conn.close()
    print(f"Database {DB_NAME} initialized/checked successfully.")

def get_setting(key, default='true'):
    """Retrieves a system setting."""
    conn = get_db_connection()
    row = conn.execute('SELECT value FROM system_settings WHERE key = ?', (key,)).fetchone()
    conn.close()
    return row['value'] if row else default

def set_admin_password(new_password):
    """관리자 비밀번호를 해시하여 저장합니다."""
    if not isinstance(new_password, str) or not 8 <= len(new_password) <= 128:
        raise ValueError('관리자 비밀번호는 8~128자로 입력해주세요.')
    hashed = generate_password_hash(new_password)
    set_setting('admin_password', hashed)

def verify_admin_password(input_password):
    """입력된 비밀번호가 저장된 해시와 일치하는지 확인합니다."""
    stored_hash = get_setting('admin_password', '')
    if not stored_hash or not isinstance(input_password, str) or not input_password or len(input_password) > 128:
        return False
    return check_password_hash(stored_hash, input_password)

def set_setting(key, value):
    """Sets a system setting."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
    conn.commit()
    conn.close()

def update_privacy_consent(emp_id):
    """Records that the user has agreed to the privacy policy."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        UPDATE employees
        SET privacy_agreed = 1,
            privacy_agreed_at = ?
        WHERE emp_id = ?
    ''', (korea_now().isoformat(sep=' ', timespec='seconds'), emp_id))
    conn.commit()
    conn.close()

def get_employee_by_id(emp_id):
    """사번만으로 사원을 조회합니다."""
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM employees WHERE emp_id = ?', (emp_id,)).fetchone()
    conn.close()
    return user



def update_employee_info(emp_id, data):
    """Updates employee information. Handles partial updates."""
    conn = get_db_connection()
    c = conn.cursor()
    
    # Construct dynamic query based on provided keys
    # This allows updating only Info or only Gift sections
    valid_keys = [
        'address_main', 'address_main_detail', 'zipcode', 'phone',
        'gift_address', 'gift_address_detail', 'gift_zipcode', 'gift_receiver',
        'selected_gift_id' # V13
    ]
    
    updates = []
    values = []
    
    for key in valid_keys:
        if key in data:
            updates.append(f"{key} = ?")
            values.append(data[key])
            
    updates.append("last_updated = ?")
    values.append(korea_now().isoformat(sep=' ', timespec='seconds'))
    values.append(emp_id)
    
    query = f"UPDATE employees SET {','.join(updates)} WHERE emp_id = ?"
    
    try:
        with conn:
            c.execute(query, tuple(values))
    finally:
        conn.close()


def get_all_employees():
    """Returns all employees as a pandas DataFrame (for admin export)."""
    conn = get_db_connection()
    # V13 Join for export
    query = '''
    SELECT e.*, g.name as gift_name 
    FROM employees e
    LEFT JOIN gift_options g ON e.selected_gift_id = g.id
    '''
    df = pd.read_sql_query(query, conn)
    conn.close()
    return df

# Header names are validated instead of relying on column positions.
IMPORT_COLUMNS = {
    'emp_id': ('사번', '사원번호', 'emp_id'),
    'name': ('성명', '이름', '사원명', 'name'),
    'phone': ('휴대폰', '휴대폰번호', '휴대전화', '휴대전화번호', '핸드폰', '핸드폰번호', '연락처', '전화번호', 'phone'),
    'address_main': ('주소', '자택주소', '현주소', '현거주지', 'address_main'),
    'zipcode': ('우편번호', '우편번호-현', 'zipcode'),
    'registered_address': ('주민등록주소지', '주민등록주소', '주민등록상주소'),
    'registered_zipcode': ('우편번호-주', '주민등록우편번호', '주민등록주소지우편번호', '주민등록주소우편번호'),
}


def upsert_employees_from_excel(filepath):
    """Validate the entire workbook before committing a single transaction."""
    df = pd.read_excel(filepath, dtype=str, keep_default_na=False)
    if df.empty or len(df) > 20000:
        raise ValueError('명부는 1~20,000행이어야 합니다.')
    normalize = lambda value: ''.join(str(value).split()).lower()
    mapped = {}
    for field, aliases in IMPORT_COLUMNS.items():
        # pandas suffixes duplicate headers with .1, .2, ...; reject those too.
        matches = [column for column in df.columns
                   if re.sub(r'\.\d+$', '', normalize(column)) in aliases]
        if len(matches) > 1 or (not matches and field in ('emp_id', 'name', 'phone')):
            raise ValueError(f'필수 열을 확인해주세요: {aliases[0]} (중복 없이 1개 필요)')
        if matches:
            mapped[field] = matches[0]
    if not any(field in mapped for field in ('address_main', 'registered_address')):
        raise ValueError('주소 열을 확인해주세요: 현거주지 또는 주민등록주소지 필요')
    if 'address_main' in mapped and 'zipcode' not in mapped:
        raise ValueError('현거주지 우편번호 열을 확인해주세요: 우편번호-현')
    # Preserve older single-address files with a generic postal-code header.
    if 'address_main' not in mapped and 'registered_zipcode' not in mapped and 'zipcode' in mapped:
        if normalize(mapped['zipcode']) in ('우편번호', 'zipcode'):
            mapped['registered_zipcode'] = mapped['zipcode']
    records = []
    seen = set()
    for index, row in df.iterrows():
        item = {field: str(row[column]).strip() for field, column in mapped.items()}
        current_address = item.get('address_main', '')
        registered_address = item.pop('registered_address', '')
        registered_zipcode = item.pop('registered_zipcode', '')
        if not current_address and registered_address:
            if 'registered_zipcode' not in mapped:
                raise ValueError(f'{index + 2}행: 주민등록주소지 우편번호 열을 확인해주세요: 우편번호-주')
            item['address_main'] = registered_address
            item['zipcode'] = registered_zipcode
        else:
            item['address_main'] = current_address
            item.setdefault('zipcode', '')
        if not item['emp_id'] or not item['name']:
            raise ValueError(f'{index + 2}행: 사번과 성명은 필수입니다.')
        if item['emp_id'] in seen:
            raise ValueError(f'{index + 2}행: 중복 사번이 있습니다.')
        if any(len(value) > 500 or any(ord(char) < 32 for char in value) for value in item.values()):
            raise ValueError(f'{index + 2}행: 값이 너무 길거나 제어 문자가 있습니다.')
        # HR exports can retain legacy six-digit postal codes. Preserve them;
        # converting to a current code requires looking up the actual address.
        if re.fullmatch(r'[0-9]{3}-[0-9]{3}', item['zipcode']):
            item['zipcode'] = item['zipcode'].replace('-', '')
        if item['zipcode'] and not re.fullmatch(r'[0-9]{5,6}', item['zipcode']):
            raise ValueError(f'{index + 2}행: 우편번호는 5자리 또는 기존 6자리 숫자여야 합니다.')
        seen.add(item['emp_id'])
        records.append(item)
    with transaction() as conn:
        for item in records:
            # Older databases require ssn with no default. Explicitly store an
            # empty value for compatibility; never import sensitive ID data.
            conn.execute('''
                INSERT INTO employees (emp_id, name, phone, address_main, zipcode, last_updated, ssn)
                VALUES (?, ?, ?, ?, ?, ?, '')
                ON CONFLICT(emp_id) DO UPDATE SET
                    name = excluded.name,
                    phone = COALESCE(NULLIF(excluded.phone, ''), employees.phone),
                    address_main = COALESCE(NULLIF(excluded.address_main, ''), employees.address_main),
                    zipcode = CASE WHEN excluded.address_main != '' THEN excluded.zipcode
                                   ELSE COALESCE(NULLIF(excluded.zipcode, ''), employees.zipcode) END,
                    last_updated = excluded.last_updated
            ''', (item['emp_id'], item['name'], item['phone'], item['address_main'], item['zipcode'], korea_now().isoformat(sep=' ', timespec='seconds')))
        conn.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)',
                     ('last_upload_time', korea_now().strftime('%Y-%m-%d %H:%M')))
    return len(records)


def reset_all_data():
    """V11: Deletes all employee data and resets settings."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM employees")
    c.execute("DELETE FROM system_settings WHERE key != 'admin_password'")
    c.execute("DELETE FROM gift_options") # V13
    # Restore default settings if needed, or leave empty
    conn.commit()
    conn.close()

# V13: Gift CRUD
def add_gift_option(name, description, image_path):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute('''
        INSERT INTO gift_options (name, description, image_path, created_at)
        VALUES (?, ?, ?, ?)
    ''', (name, description, image_path, korea_now().isoformat(sep=' ', timespec='seconds')))
    conn.commit()
    conn.close()

def get_gift_options():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM gift_options WHERE is_active = 1').fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_gift_option(gift_id):
    # Preserve the gift name for historical selections and exports.
    with transaction() as conn:
        conn.execute('UPDATE gift_options SET is_active = 0 WHERE id = ?', (gift_id,))

def get_gift_by_id(gift_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM gift_options WHERE id = ?', (gift_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
    
    
if __name__ == '__main__':
    init_db()
