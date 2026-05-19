import sqlite3
import pandas as pd
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_NAME = 'employees.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn

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
    else:
        # 기본 비밀번호 설정
        default_hash = generate_password_hash('admin1234')
        c.execute("INSERT INTO system_settings (key, value) VALUES ('admin_password', ?)", (default_hash,))
        print("V18 Migration: 기본 관리자 비밀번호(admin1234)를 해시로 저장했습니다.")

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
    hashed = generate_password_hash(new_password)
    set_setting('admin_password', hashed)

def verify_admin_password(input_password):
    """입력된 비밀번호가 저장된 해시와 일치하는지 확인합니다."""
    stored_hash = get_setting('admin_password', '')
    if not stored_hash:
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
    ''', (datetime.now(), emp_id))
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
    values.append(datetime.now())
    values.append(emp_id)
    
    query = f"UPDATE employees SET {','.join(updates)} WHERE emp_id = ?"
    
    c.execute(query, tuple(values))
    conn.commit()
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

def upsert_employees_from_excel(filepath):
    """
    Reads an Excel file and updates/inserts employees.
    Uses specific column indices based on user provided data layout (V7).
    - Zipcode: 55 -> 54 (Added in V8)
    V11 Update: Force read as string to preserve leading zeros.
    V17 Update: SSN 관련 로직 제거 (민감개인정보 미수집).
    """
    # V11: dtype=str to preserve leading zeros
    df = pd.read_excel(filepath, dtype=str)
    
    # Map by index
    # We create a new clean dataframe
    clean_df = pd.DataFrame()
    
    # Helper to safe access by iloc
    def get_col_data(col_idx):
        if col_idx < len(df.columns):
            return df.iloc[:, col_idx]
        return None

    # Function to clean typical Excel numeric artifacts (e.g. 1234.0 -> 1234)
    # V11: Since we read as str, .0 might not happen as often but still safe to keep
    def clean_str(series):
        if series is None:
            return pd.Series([''] * len(df))
            
        def convert_val(x):
            s = str(x).strip()
            if s.lower() in ['nan', 'none', '', 'nat']:
                return ''
            
            # V15 Fix: Only remove trailing .0 artifact. Do NOT cast to float/int
            # as that removes leading zeros (e.g. "0123" -> 123.0 -> "123")
            if s.endswith('.0'):
                return s[:-2]
            return s
                
        return series.apply(convert_val)

    clean_df['emp_id'] = clean_str(get_col_data(11))
    clean_df['name'] = clean_str(get_col_data(12))
    
    clean_df['phone'] = clean_str(get_col_data(52))
    clean_df['address_main'] = clean_str(get_col_data(53))
    clean_df['zipcode'] = clean_str(get_col_data(54))
    
    # Clean up NaNs (redundant but safe)
    clean_df = clean_df.replace({'nan': '', 'None': ''})

    conn = get_db_connection()
    c = conn.cursor()
    
    count = 0
    for _, row in clean_df.iterrows():
        # Check if employee exists
        c.execute('SELECT id FROM employees WHERE emp_id = ?', (row['emp_id'],))
        exists = c.fetchone()
        
        if exists:
            # V13 Update: Don't overwrite selected_gift_id on re-import
            c.execute('''
                UPDATE employees
                SET name = ?, address_main = ?, zipcode = ?, phone = ?, last_updated = ?
                WHERE emp_id = ?
            ''', (row['name'], row['address_main'], row['zipcode'], row['phone'], datetime.now(), row['emp_id']))
        else:
            c.execute('''
                INSERT INTO employees (name, emp_id, address_main, zipcode, phone, last_updated)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (row['name'], row['emp_id'], row['address_main'], row['zipcode'], row['phone'], datetime.now()))
        count += 1
        
    # Record upload time
    # deadlock fix: use same cursor instead of calling set_setting (which opens new conn)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    c.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', ('last_upload_time', now_str))

    conn.commit()
    conn.close()
    return count

def reset_all_data():
    """V11: Deletes all employee data and resets settings."""
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM employees")
    c.execute("DELETE FROM system_settings")
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
    ''', (name, description, image_path, datetime.now()))
    conn.commit()
    conn.close()

def get_gift_options():
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM gift_options WHERE is_active = 1').fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_gift_option(gift_id):
    conn = get_db_connection()
    conn.execute('DELETE FROM gift_options WHERE id = ?', (gift_id,))
    conn.commit()
    conn.close()

def get_gift_by_id(gift_id):
    conn = get_db_connection()
    row = conn.execute('SELECT * FROM gift_options WHERE id = ?', (gift_id,)).fetchone()
    conn.close()
    return dict(row) if row else None
    
    
if __name__ == '__main__':
    init_db()
