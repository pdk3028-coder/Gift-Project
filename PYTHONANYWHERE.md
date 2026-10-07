# GiftPoongsan 계정 배포

GitHub에는 코드만 저장합니다. 사원 명부, DB, 업로드 파일, 서명 키와 로컬 가상환경은 포함하지 않습니다.

## 기존 프로젝트 백업

Web 탭에서 현재 Source code, Working directory, Virtualenv, Python 버전, WSGI 파일 경로, Static files 매핑을 기록합니다. 기존 프로젝트 폴더와 DB, `/var/www/`의 해당 WSGI 파일을 별도 백업 폴더에 복사합니다. 기존 웹앱의 설정을 변경해 새 프로젝트로 연결할 수 있으므로 웹앱 자체를 먼저 삭제할 필요는 없습니다. 정상 전환을 확인한 뒤 기존 프로젝트의 원래 폴더만 정리하고 백업은 보관하세요.

## 새 프로젝트 설치

Bash 콘솔에서 실행합니다. Python 3.11 이상이 필요하며 Web 탭과 가상환경의 Python 버전은 일치해야 합니다. 아래 예시는 Python 3.13입니다. 계정에 해당 버전이 없다면 제공되는 3.11 이상 버전으로 양쪽을 맞추세요.

```bash
cd /home/GiftPoongsan
git clone https://github.com/pdk3028-coder/Gift-Project.git
python3.13 -m venv /home/GiftPoongsan/.virtualenvs/gift-project
/home/GiftPoongsan/.virtualenvs/gift-project/bin/python -m pip install -r /home/GiftPoongsan/Gift-Project/requirements.txt
```

동일한 `Gift-Project` 폴더가 이미 있으면 먼저 기존 내용과 Git 상태를 확인하세요. 기존 파일 위에 무조건 덮어쓰거나 삭제하지 마세요.

## 관리자 비밀번호 설정

새 배포의 영구 데이터는 `/home/GiftPoongsan/gift-data/`에 생성됩니다. 로컬 PC의 DB는 자동으로 복사되지 않습니다. 다음 명령에서 새 관리자 비밀번호(8~128자)를 직접 입력하세요.

```bash
cd /home/GiftPoongsan/Gift-Project
/home/GiftPoongsan/.virtualenvs/gift-project/bin/python -m flask --app pythonanywhere_wsgi:app set-admin-password
```

웹과 CLI 모두 같은 영구 데이터 경로를 쓰도록 반드시 `pythonanywhere_wsgi:app`을 지정합니다. 비밀번호를 코드나 GitHub에 기록하지 마세요.

## Web 탭 설정

- Source code / Working directory: `/home/GiftPoongsan/Gift-Project`
- Virtualenv: `/home/GiftPoongsan/.virtualenvs/gift-project`
- Python version: 가상환경과 동일한 버전
- Static files: `/static/` → `/home/GiftPoongsan/Gift-Project/static`
- 기존 프로젝트의 나머지 Static files 매핑은 제거합니다. `/`, `/uploads/`, `/gift-data/`를 정적 매핑으로 공개하지 마세요.
- HTTPS 강제 사용(Force HTTPS)을 켭니다.

Web 탭의 WSGI configuration file을 열어 기존 내용을 백업한 뒤 다음으로 교체합니다.

```python
import sys

project_home = '/home/GiftPoongsan/Gift-Project'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

from pythonanywhere_wsgi import application
```

Reload를 누른 뒤 `https://giftpoongsan.pythonanywhere.com/`에서 로그인 화면을 확인합니다. PythonAnywhere에서는 `app.py`나 Windows 배치 파일로 서버를 따로 실행하지 않습니다. WSGI로 서비스됩니다.

관리자 로그인 후 명부·선물 이미지를 등록합니다. 명부 업로드, 사번 로그인, 수정 저장, 선물 선택 및 다운로드를 확인한 후 기존 프로젝트를 정리합니다. 문제가 생기면 백업한 WSGI 내용과 Web 탭 경로·가상환경·정적 매핑을 복원하고 Reload합니다.

## 이후 업데이트

```bash
cd /home/GiftPoongsan/Gift-Project
git pull --ff-only
/home/GiftPoongsan/.virtualenvs/gift-project/bin/python -m pip install -r requirements.txt
```

이후 Web 탭에서 Reload합니다. DB·이미지·서명 키는 코드 폴더 밖의 `gift-data`에 있으므로 코드 업데이트 때 유지됩니다. `gift-data`는 별도로 백업해야 합니다.

PythonAnywhere의 신뢰할 수 있는 `X-Real-IP`로 관리자 요청 제한을 계산합니다. 기본 메모리 제한 카운터는 프로세스마다 독립적이며 Reload하면 초기화됩니다. 여러 워커 사이의 엄격한 공유 제한이 필요하면 지원되는 공유 저장소를 별도로 설정하세요.

공식 문서: [Flask 배포](https://help.pythonanywhere.com/pages/Flask/), [클라이언트 IP](https://help.pythonanywhere.com/pages/WebAppClientIPAddresses/).
