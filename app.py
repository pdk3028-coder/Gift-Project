"""Employee information and gift delivery application."""
import hmac
import hashlib
import io
import os
from pathlib import Path
import re
import secrets
import sqlite3
import tempfile
import warnings
from datetime import timedelta
from time_utils import korea_now

import click
from flask import Flask, abort, flash, redirect, render_template, request, send_file, send_from_directory, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from openpyxl import Workbook
from PIL import Image, UnidentifiedImageError
from werkzeug.middleware.proxy_fix import ProxyFix

import database

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get('GIFT_UPLOAD_FOLDER', BASE_DIR / 'uploads')).resolve()
app = Flask(__name__, instance_path=str(Path(os.environ.get('GIFT_INSTANCE', BASE_DIR / 'instance')).resolve()))


def load_secret():
    configured = os.environ.get('GIFT_SECRET_KEY')
    if configured is not None:
        if len(configured) < 32 or configured == 'your_secret_key_here':
            raise RuntimeError('GIFT_SECRET_KEY must contain at least 32 random characters.')
        return configured
    folder = Path(app.instance_path)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / 'secret.key'
    # Exclusive creation keeps the key stable across restarts.
    try:
        with path.open('x', encoding='ascii') as file:
            os.chmod(path, 0o600)
            file.write(secrets.token_hex(32))
    except FileExistsError:
        pass
    key = path.read_text(encoding='ascii').strip()
    if len(key) < 32:
        raise RuntimeError('Invalid instance/secret.key; restore a valid key before starting.')
    return key


app.config.update(
    SECRET_KEY=load_secret(),
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('GIFT_HTTPS', '0') == '1',
    MAX_CONTENT_LENGTH=10 * 1024 * 1024,
    MAX_FORM_MEMORY_SIZE=256 * 1024,
    UPLOAD_FOLDER=str(UPLOAD_DIR),
    GIFT_IMAGE_FOLDER=str(UPLOAD_DIR / 'gift_images'),
)
Path(app.config['GIFT_IMAGE_FOLDER']).mkdir(parents=True, exist_ok=True)
# Only enable when the server is reachable exclusively through the configured proxy.
proxy_hops = int(os.environ.get('GIFT_TRUSTED_PROXY_HOPS', '0'))
if proxy_hops:
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxy_hops, x_proto=proxy_hops)
limiter = Limiter(key_func=get_remote_address, app=app, default_limits=[],
                  storage_uri=os.environ.get('GIFT_RATE_LIMIT_STORAGE', 'memory://'))
database.init_db()


def admin_version():
    return hashlib.sha256(database.get_setting('admin_password', '').encode()).hexdigest()


def csrf_token():
    if '_csrf' not in session:
        session['_csrf'] = secrets.token_urlsafe(32)
    return session['_csrf']


app.jinja_env.globals['csrf_token'] = csrf_token


@app.before_request
def protect_request():
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        expected = session.get('_csrf')
        provided = request.form.get('csrf_token', '')
        if not expected or not hmac.compare_digest(expected.encode(), provided.encode()):
            abort(400, description='요청이 만료되었거나 올바르지 않습니다. 페이지를 새로고침해주세요.')
    if session.get('is_admin') and session.get('admin_version') != admin_version():
        session.pop('is_admin', None)
        session.pop('admin_version', None)
    if session.get('user_id') and database.get_employee_by_id(session['user_id']) is None:
        session.pop('user_id', None)
        session.pop('user_name', None)


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if not request.path.startswith('/static/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(400)
@app.errorhandler(413)
@app.errorhandler(429)
def request_error(error):
    messages = {400: '요청을 확인할 수 없습니다. 페이지를 새로고침 후 다시 시도해주세요.',
                413: '업로드 파일을 포함한 요청 크기는 10MB 이하여야 합니다.',
                429: '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'}
    return render_template('error.html', message=messages[error.code]), error.code


def form_text(name, label, required=True, max_length=500):
    value = request.form.get(name)
    if value is None:
        raise ValueError(f'{label} 항목이 누락되었습니다.')
    value = value.strip()
    if (required and not value) or len(value) > max_length or any(ord(c) < 32 for c in value):
        raise ValueError(f'{label} 입력값을 확인해주세요.')
    return value


def address_form(prefix=''):
    main = 'gift_address' if prefix else 'address_main'
    detail = 'gift_address_detail' if prefix else 'address_main_detail'
    zipcode = prefix + 'zipcode'
    data = {main: form_text(main, '주소'), detail: form_text(detail, '상세 주소', False),
            zipcode: form_text(zipcode, '우편번호')}
    if not re.fullmatch(r'[0-9]{5}', data[zipcode]):
        raise ValueError('우편번호는 5자리 숫자여야 합니다.')
    return data


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return render_template('index.html')


@app.route('/login', methods=['POST'])
def login():
    # Employee-ID-only sign-in is intentionally retained.
    user = database.get_employee_by_id(request.form.get('emp_id', '').strip())
    if user and request.form.get('agree_privacy'):
        database.update_privacy_consent(user['emp_id'])
        session.clear()
        session.permanent = True
        session.update(user_id=user['emp_id'], user_name=user['name'])
        return redirect(url_for('dashboard'))
    flash('개인정보 이용 동의와 사번을 확인해주세요.', 'error')
    return redirect(url_for('index'))


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('dashboard.html', name=session['user_name'],
                           enable_info=database.get_setting('enable_info_update') == 'true',
                           enable_gift=database.get_setting('enable_gift_update') == 'true')


@app.route('/info_update', methods=['GET', 'POST'])
def info_update():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    if database.get_setting('enable_info_update') != 'true':
        flash('현재 이 기능은 비활성화되어 있습니다.', 'error')
        return redirect(url_for('dashboard'))
    user = database.get_employee_by_id(session['user_id'])
    if request.method == 'POST':
        try:
            data = {}
            if request.form.get('no_change') != 'on':
                data = address_form()
                data['phone'] = form_text('phone', '연락처', max_length=30)
                if not re.fullmatch(r'[0-9+() -]{7,30}', data['phone']):
                    raise ValueError('연락처 형식을 확인해주세요.')
            database.update_employee_info(user['emp_id'], data)
        except ValueError as error:
            flash(str(error), 'error')
            return redirect(url_for('info_update'))
        flash('인사 정보가 저장되었습니다.', 'success')
        return redirect(url_for('dashboard'))
    return render_template('info_update.html', user=user)


@app.route('/gift_update', methods=['GET', 'POST'])
def gift_update():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    if database.get_setting('enable_gift_update') != 'true':
        flash('현재 이 기능은 비활성화되어 있습니다.', 'error')
        return redirect(url_for('dashboard'))
    user = dict(database.get_employee_by_id(session['user_id']))
    gifts = database.get_gift_options()
    if request.method == 'POST':
        try:
            data = {}
            selected = request.form.get('selected_gift_id', '')
            if gifts or selected:
                if not selected.isdecimal() or int(selected) not in {g['id'] for g in gifts}:
                    raise ValueError('현재 제공되는 선물을 선택해주세요.')
                data['selected_gift_id'] = int(selected)
            if request.form.get('same_address') != 'on':
                data.update(address_form('gift_'))
                data['gift_receiver'] = form_text('gift_receiver', '수령인', max_length=100)
            elif not user.get('gift_address'):
                # The displayed default address must also be stored on first confirmation.
                if not user.get('address_main') or not user.get('zipcode'):
                    raise ValueError('저장된 배송지가 없습니다. 배송지를 입력해주세요.')
                data.update(gift_address=user['address_main'], gift_address_detail=user['address_main_detail'],
                            gift_zipcode=user['zipcode'], gift_receiver=user['name'])
            database.update_employee_info(user['emp_id'], data)
        except (ValueError, sqlite3.IntegrityError) as error:
            flash(str(error) if isinstance(error, ValueError) else '선물 목록이 변경되었습니다. 다시 선택해주세요.', 'error')
            return redirect(url_for('gift_update'))
        flash('선물 배송지 정보가 저장되었습니다.', 'success')
        return redirect(url_for('dashboard'))
    if not user.get('gift_address'):
        user.update(gift_address=user.get('address_main'), gift_address_detail=user.get('address_main_detail'),
                    gift_zipcode=user.get('zipcode'), gift_receiver=user['name'])
    return render_template('gift_update.html', user=user, gift_options=gifts)


@app.route('/admin/login', methods=['GET', 'POST'])
@limiter.limit('10 per minute', methods=['POST'])
def admin_login():
    if request.method == 'POST':
        if database.verify_admin_password(request.form.get('password')):
            session.clear()
            session.permanent = True
            session.update(is_admin=True, admin_version=admin_version())
            return redirect(url_for('admin'))
        flash('비밀번호가 올바르지 않습니다.', 'error')
        return redirect(url_for('admin_login'))
    return render_template('admin_login.html')


@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/admin')
def admin():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    return render_template('admin.html', enable_info=database.get_setting('enable_info_update') == 'true',
                           enable_gift=database.get_setting('enable_gift_update') == 'true',
                           last_upload_time=database.get_setting('last_upload_time', '-'))


@app.route('/admin/settings', methods=['POST'])
def update_settings():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    new_password = request.form.get('new_password', '')
    if new_password:
        try:
            database.set_admin_password(new_password)
        except ValueError as error:
            flash(str(error), 'error')
            return redirect(url_for('admin'))
        session['admin_version'] = admin_version()
    database.set_setting('enable_info_update', 'true' if request.form.get('enable_info') else 'false')
    database.set_setting('enable_gift_update', 'true' if request.form.get('enable_gift') else 'false')
    flash('설정이 저장되었습니다.', 'success')
    return redirect(url_for('admin'))


@app.route('/admin/upload', methods=['POST'])
def upload_excel():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    file = request.files.get('file')
    if not file or Path(file.filename or '').suffix.lower() not in {'.xls', '.xlsx'}:
        flash('xls 또는 xlsx 명부 파일을 선택해주세요.', 'error')
        return redirect(url_for('admin'))
    try:
        # Each request owns its temporary file; originals are never retained.
        with tempfile.TemporaryDirectory(prefix='gift_import_') as folder:
            path = Path(folder) / ('roster' + Path(file.filename).suffix.lower())
            file.save(path)
            count = database.upsert_employees_from_excel(path)
        flash(f'{count}명의 사원 정보가 업데이트되었습니다.', 'success')
    except ValueError as error:
        flash(str(error), 'error')
    except sqlite3.DatabaseError:
        app.logger.exception('Employee import database write failed')
        flash('명부를 읽었지만 데이터베이스에 저장하지 못했습니다. 서버 로그를 확인해주세요.', 'error')
    except Exception:
        app.logger.exception('Employee import failed')
        flash('명부 파일을 처리하지 못했습니다. 파일 형식과 내용을 확인해주세요.', 'error')
    return redirect(url_for('admin'))


@app.route('/admin/download')
def download_excel():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    df = database.get_all_employees()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Employees'
    sheet.append(list(df.columns))
    for row_number, record in enumerate(df.itertuples(index=False, name=None), start=2):
        sheet.append(list(record))
        for column, value in enumerate(record, start=1):
            if isinstance(value, str):
                sheet.cell(row_number, column).data_type = 's'  # Database text is never a formula.
    output = io.BytesIO()
    workbook.save(output)
    workbook.close()
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f'employees_updated_{korea_now():%Y%m%d%H%M%S}.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/admin/gifts')
def admin_gifts():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    return render_template('admin_gifts.html', gifts=database.get_gift_options())


def save_image(file):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(file.stream) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'} or source.width * source.height > 16000000:
                    raise ValueError('JPEG, PNG, WebP 이미지(최대 1,600만 화소)만 등록할 수 있습니다.')
                source.load()
                image = source.convert('RGB')
        name = secrets.token_hex(16) + '.jpg'
        path = Path(app.config['GIFT_IMAGE_FOLDER']) / name
        try:
            image.save(path, format='JPEG', quality=90)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        finally:
            image.close()
        return name
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('유효한 JPEG, PNG, WebP 이미지를 선택해주세요.') from error


@app.route('/admin/gifts/add', methods=['POST'])
def admin_add_gift():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    filename = None
    try:
        name = form_text('name', '선물 이름', max_length=100)
        description = form_text('description', '설명', False)
        file = request.files.get('image')
        if file and file.filename:
            filename = save_image(file)
        database.add_gift_option(name, description, f'uploads/gift_images/{filename}' if filename else '')
    except ValueError as error:
        flash(str(error), 'error')
        return redirect(url_for('admin_gifts'))
    except Exception:
        if filename:
            (Path(app.config['GIFT_IMAGE_FOLDER']) / filename).unlink(missing_ok=True)
        raise
    flash('선물이 추가되었습니다.', 'success')
    return redirect(url_for('admin_gifts'))


@app.route('/admin/gifts/delete/<int:gift_id>', methods=['POST'])
def admin_delete_gift(gift_id):
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    database.delete_gift_option(gift_id)
    flash('선물이 목록에서 제외되었습니다. 기존 선택 기록은 유지됩니다.', 'success')
    return redirect(url_for('admin_gifts'))


@app.route('/uploads/gift_images/<filename>')
def uploaded_gift_image(filename):
    if not re.fullmatch(r'[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)', filename, re.IGNORECASE):
        abort(404)
    return send_from_directory(app.config['GIFT_IMAGE_FOLDER'], filename)


@app.route('/admin/reset', methods=['POST'])
@limiter.limit('3 per minute')
def admin_reset():
    if not session.get('is_admin'):
        return redirect(url_for('admin_login'))
    if database.verify_admin_password(request.form.get('password')):
        database.reset_all_data()
        flash('사원·선물 데이터와 기능 설정을 초기화했습니다. 관리자 비밀번호는 유지됩니다.', 'success')
    else:
        flash('비밀번호가 일치하지 않아 초기화에 실패했습니다.', 'error')
    return redirect(url_for('admin'))


@app.cli.command('set-admin-password')
@click.password_option(confirmation_prompt=True)
def set_admin_password_command(password):
    """Set or recover the administrator password locally."""
    try:
        database.set_admin_password(password)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    click.echo('관리자 비밀번호를 설정했습니다.')


@app.cli.command('cleanup-uploads')
@click.option('--apply', is_flag=True, help='Delete listed files; default only lists candidates.')
def cleanup_uploads(apply):
    """Remove legacy spreadsheets and unreferenced gift images explicitly."""
    with database.transaction() as conn:
        referenced = {row[0] for row in conn.execute('SELECT image_path FROM gift_options')}
    root = Path(app.config['UPLOAD_FOLDER']).resolve()
    images = Path(app.config['GIFT_IMAGE_FOLDER']).resolve()
    candidates = [p for p in root.iterdir() if p.is_file() and p.suffix.lower() in {'.xls', '.xlsx'}]
    candidates += [p for p in images.iterdir() if p.is_file() and f'uploads/gift_images/{p.name}' not in referenced]
    for path in candidates:
        if path.is_symlink() or path.resolve().parent not in {root, images}:
            continue
        click.echo(path.name)
        if apply:
            path.unlink()
    click.echo('삭제 완료' if apply else '미리보기입니다. 삭제하려면 --apply를 지정하세요.')


if __name__ == '__main__':
    from waitress import serve
    serve(app, host=os.environ.get('GIFT_HOST', '127.0.0.1'), port=int(os.environ.get('GIFT_PORT', '5000')),
          max_request_body_size=app.config['MAX_CONTENT_LENGTH'])
