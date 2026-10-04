# 책의 한 장면 실험 앱

Python + Flask + SQLite(로컬) / PostgreSQL(운영) + HTML/CSS + Vanilla JavaScript 구현입니다. 정책 기준은 `docs/requirements.md`이며 두 실험 문서는 변경하지 않았습니다. 상황 설명과 발췌는 사용자가 이번 구현 요청에서 제공한 문구를 그대로 등록했습니다. 이미지와 임시 이미지는 없습니다.

## 현재 상태와 미확정 항목

핵심 참가자 흐름, 관리자, CSV, 정책 테스트를 구현했습니다. **운영 배포는 하지 않았습니다.** 다음 결정은 임의 확정하지 않았습니다.

- requirements 17절: 노출 정책은 EXPOSURE_POLICY=cards로 확정했습니다. 원문 문단/콘텐츠 카드, 이모지·투표 각각의 결과 블록, 개별 타인 감상 카드를 활성 탭에서 실제 면적 50% 이상 보았을 때 기록합니다. 제목·섹션 헤더·빈 상태·본인 감상은 제외합니다. 여러 카드를 보아도 visitor/도서 지표는 중복 집계하지 않습니다.
- 세 발췌의 출처, 번역본, 사용 가능 여부. `data/books.json`의 `source`, `translation`, `usage_status`가 미확정입니다. 사용자가 제공한 발췌를 로컬에서 확인할 수 있지만 실제 실험 전에 이 메타데이터를 확정해야 합니다.
- 실제 시작·종료 시각, 테스트 이외 오염 판단 기준, 참가자 수집 고지, 익명 ID·이벤트·본문 보관 기간, 삭제 본문 폐기 시점과 Export/백업 사본 범위, 배포·백업 정책.

운영 모드는 시작 시각·고지·관측 정책·운영 확정 플래그가 없으면 실행을 거부합니다. `OPERATIONS_CONFIRMED=1`은 운영자가 위 정책을 실제로 확정했다는 표시입니다.

## 구현 기능

- UUID 쿠키 30일, 쿠키 유지 확인 전 방문·참여 미수집, 브라우저 재방문 식별, 랜딩 도서 순서 무작위 배정·유지, 실제 랜딩 위치와 선택 연결.
- 상황 설명 → 원문 → 이모지 → 투표 → 한 줄 → 커뮤니티 → 좋아요·답글 → 자유 감상. 세 반응은 모두 선택 사항이며 커뮤니티 직접 진입에 참여를 요구하지 않습니다.
- 이모지/투표 선택·변경·명시적 취소, 종류별 독립 결과 공개, 현재 유효 분포, 취소 후 공개 자격 유지. 같은 선택을 다시 누르면 아무것도 변경하지 않습니다.
- 한 줄 150자 / 자유 감상 2,000자 / 답글 300자. Unicode 코드 포인트 기준, 내부 공백·줄바꿈 포함, 공백만 거부. 한 줄/자유 감상은 도서별 하나, 수정·논리 삭제·같은 ID 재작성 가능.
- 최초 제출 이력으로 공개 자격 유지. 커뮤니티 자동 복원은 새 `community_open`을 만들지 않습니다. 노출 정책 확정 후 `others_reveal`은 실제 타인 글이 50% 보일 때만 기록합니다. 빈 목록·본인 글·이모지/투표 분포는 대상이 아닙니다.
- 자신의 글 `내 감상` 표시, 감상 최신순·답글 오래된 순, 수정/재작성으로 최초 순서 유지, 타인 글 좋아요·취소·답글 여러 개·수정·삭제. 본인 글/다른 도서/삭제 글 상호작용은 서버에서 거부합니다.
- 저장·성공 이벤트 동일 트랜잭션, UUID 요청 재시도·다중 탭 중복 방지, 같은 ID 다른 요청은 409, 실패 시 입력 유지 및 같은 요청 재시도.
- 관리자 인증, 전체/도서 지표·표본 50명·판정, 직접 진입 C/V·실제 노출 E/V·상호작용 (L∪R)/E, 최초 성공과 현재 유효 수 분리, 노출/시작 누락 진단, 위치별 선택 및 공개 경로.
- 동일 DB 읽기 스냅샷 ZIP CSV, 테스트 원천·사유, 기간 밖 이력 구분, UTF-8·UTC·수식 실행 방지. 삭제 상태 본문은 운영자가 종료 후 명시적으로 폐기할 수 있습니다.
- SQL 바인딩, 외래키·유일 제약, 소유자·공개 조건 검증, CSRF 토큰·Origin 검사, HTML 이스케이프·textContent, no-store 및 보안 헤더.

## 구조

```text
app/
  __init__.py       앱 생성, 쿠키 유지 확인, CSRF, 보안 헤더
  config.py         환경변수
  db.py             DB 연결, init-db / mark-test / purge CLI
  schema.sql        제약과 인덱스
  queries.py        콘텐츠와 최초 성공 조회
  report_queries.py 기간 및 선후 관계
  routes/           books.py / events.py / admin.py
  services/         participation.py / event_logging.py / reporting.py
  templates/        참가자·관리자 HTML
  static/           css/style.css / js/client.js, landing.js, book.js
data/books.json     고정 콘텐츠, 버전, 추후 이미지 필드(null)
tests/              정책·집계 자동 테스트
instance/           비공개 영속 DB(버전 관리 제외)
docs/               원래 실험 문서
wsgi.py             WSGI 앱
requirements.txt    의존성 고정 버전
.env.example        실제 비밀값 없는 환경변수 예시
```

## 설치·로컬 실행 (PowerShell)

Python 3.12 이상을 권장합니다. 이 환경에서는 Python 3.14.4로 테스트했습니다. `python`이 잡혀 있으면:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

uv를 사용하는 경우:

```powershell
uv venv --python 3.14 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```

환경변수 설정과 실행:

```powershell
$env:LOCAL_DEVELOPMENT = "1"
$env:SECRET_KEY = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
$env:ADMIN_USERNAME = "usernamd"
$env:ADMIN_PASSWORD = "password"
$env:DATABASE = Join-Path (Get-Location) "instance/experiment.sqlite"
$env:EXPOSURE_POLICY = "cards"
.\.venv\Scripts\python.exe -m flask --app wsgi init-db
.\.venv\Scripts\python.exe -m flask --app wsgi run --host 127.0.0.1 --port 5000
```

참가자: `http://127.0.0.1:5000/`. **로컬 모드에서 새로 발급한 visitor는 자동 테스트 표시로 일반 집계와 일반 공개 결과에서 제외됩니다.** LOCAL_DEVELOPMENT=1의 test visitor는 테스트 전용 커뮤니티에서 서로의 한 줄·자유 감상, 좋아요·답글 및 테스트 이모지·투표 분포를 확인할 수 있습니다. 본인 글은 내 감상으로 표시합니다. 실제 visitor에게는 실제 데이터만 공개하며 두 집단의 결과를 합산하지 않습니다. 별도 브라우저 프로필 또는 일반 창과 시크릿 창으로 두 test visitor를 생성하여 검증하세요. 실제 사용자 공개 및 집계는 자동 테스트에서 독립된 참가자 fixture로 검증합니다. 운영 DB와 로컬 DB를 분리하세요.

`.env.example`은 설정 설명용입니다. 앱은 `.env`를 자동으로 읽지 않으므로 PowerShell 환경변수 또는 배포 플랫폼의 비밀 설정을 사용합니다. `SECRET_KEY`는 재시작 후에도 유지해야 쿠키 서명이 유지됩니다. 실제 값을 저장소에 넣지 않습니다.

## 환경변수와 운영

| 변수 | 의미 |
|---|---|
| SECRET_KEY | 필수, UUID 쿠키/확인 경로 서명용 비밀 |
| ADMIN_USERNAME / ADMIN_PASSWORD | 관리자 Basic 인증, 미설정이면 503으로 차단 |
| DATABASE | 로컬 SQLite 경로, 기본 `instance/experiment.sqlite`; DATABASE_URL이 있으면 사용하지 않음 |
| LOCAL_DEVELOPMENT | 로컬 전용 `1`, 운영 `0`; 운영에서 Secure 쿠키·HTTPS 관리자 강제 |
| EXPOSURE_POLICY | 기본값 `cards`: 원문 문단·결과 블록·개별 타인 감상 카드 |
| EXPERIMENT_START / EXPERIMENT_END | UTC ISO 8601, 시작 포함·종료 미포함. 종료는 운영자가 설정, 50명 도달로 자동 종료 안 함 |
| DISPLAY_TIMEZONE | 관리자 표시 시간대, 기본 Asia/Seoul. 원천 및 CSV 시각은 항상 UTC |
| DATA_RELIABLE / DATA_QUALITY_REASON | 운영자 신뢰 판단 및 사유. `0`이면 표본과 무관하게 판정 불가 |
| NOTICE_TEXT | 운영자가 확정한 수집·보관 고지 문구 |
| OPERATIONS_CONFIRMED | 운영 전 콘텐츠/수집/보관/기간/오염 정책 확인 후 `1` |

콘텐츠 원문은 외부에서 가져오거나 생성하지 않았습니다. 메타데이터·내용을 변경할 때 `version`을 새 값으로 바꾸고 UTC `effective_at`을 지정한 뒤 `init-db`를 실행합니다. 같은 버전의 내용을 덮어쓰면 오류로 거부합니다. 기존 콘텐츠/이벤트는 보존합니다. 변경 전 열린 페이지는 당시 버전으로 기록합니다. 운영 시작 전 출처·번역본을 채우고 사용 가능 여부를 확인하여 `usage_status`를 `approved`로 지정해야 합니다. 미확정 콘텐츠로 운영 모드를 시작하면 오류로 거부합니다.

운영은 `LOCAL_DEVELOPMENT=0`으로 설정하고 HTTPS 리버스 프록시 뒤에서 WSGI 서버를 사용합니다:

```powershell
.\.venv\Scripts\waitress-serve.exe --listen=127.0.0.1:8000 --trusted-proxy=127.0.0.1 --trusted-proxy-headers=x-forwarded-proto wsgi:app
```

프록시 실제 주소만 신뢰하도록 배포 환경에 맞게 지정하고 외부에서 Waitress 포트로 직접 접근하지 못하게 합니다. HTTPS 프록시가 X-Forwarded-Proto를 올바르게 전달해야 관리자 접근이 됩니다. 운영에서는 Flask 개발 서버를 사용하지 않습니다. 운영에서는 DATABASE_URL로 PostgreSQL을 사용하고 앱의 static 경로에는 DB·백업·비밀 파일을 두지 않습니다.

프록시 접근 로그는 쿼리·쿠키·Authorization·본문을 기록하지 않도록 설정합니다. 앱은 요청 본문을 운영 로그에 출력하지 않습니다. Flask의 CSRF 및 쿠키 보안 원칙은 [공식 보안 문서](https://flask.palletsprojects.com/en/stable/web-security/)를 참고했습니다.

## 관리자·CSV

`/admin/`에서 환경변수의 Basic 인증 정보를 입력합니다. 모든 `/admin/export` 다운로드도 동일 인증이 필요합니다. 관리자 접근은 visitor의 테스트 여부를 변경하지 않고 `admin_test` cookie를 발급하거나 읽지 않습니다. Production의 일반 URL에서 새 visitor는 실제 실험 visitor로 생성됩니다. LOCAL_DEVELOPMENT의 수동 방문자는 `is_test=1`로 격리하며, 자동화 테스트는 임시 DB에서 실제/테스트 cohort를 검증합니다.

대시보드 상단은 고유 도서 방문자 / 최소 표본 50명, 가벼운 참여율 / 목표 30%, 한 줄 감상 참여율 / 목표 10%, community_open, others_reveal을 표시합니다. 책별 카드의 수치는 기간 내 고유 사용자와 이벤트 횟수이며, 모든 상세 지표·공개 경로·현재 유효 상태는 펼쳐 볼 수 있습니다. 테스트 visitor 전용 집계 UI는 제공하지 않으며 기존 테스트 제외 계산식과 CSV는 유지합니다.

추가 개발 테스트 ID는 실제 참여 **전에** CLI로 제외합니다. 해당 ID는 DB/관리자 전용 CSV에서 확인할 수 있습니다. 공개 화면에는 UUID가 표시되지 않습니다.

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi mark-test VISITOR_UUID --reason "개발 테스트"
```

CSV는 원천 events, visitors(비밀 토큰 제외), 참여 상태, page_views, metrics, contents, conditions, paths, positions, quality를 ZIP으로 제공합니다. 기간 밖의 필요한 이력도 원천에 포함하고 `in_period`로 구분합니다. 테스트 표시·사유는 보존하되 요약은 제외합니다. Seed 작성자 행은 원천 CSV에서도 제외하며 normal이 seed 감상에 남긴 행동은 유지합니다. **모든 문자열 셀은 앞에 작은따옴표 하나를 붙입니다. 원문 복원 시 문자열 앞의 작은따옴표를 정확히 하나만 제거하세요.** 본문 내 쉼표·따옴표·줄바꿈·이모지를 보존합니다. Export에는 인증 비밀·CSRF 토큰·DB 경로가 없습니다.

분모가 0이면 N/A입니다. 주 분모는 전체 기간 내 도서 방문자 합집합이며 랜딩·선택만으로 늘어나지 않습니다. 주 성공 기준은 50명 이상, 신뢰 가능, 가벼운 참여율 ≥30% 및 한 줄 참여율 ≥10% 동시 충족입니다. 판정은 반올림 전 값입니다. 상호작용은 같은 visitor·도서의 기간 내 실제 `others_reveal` 이후 성공한 좋아요/답글 합집합입니다. 같은 페이지는 client_sequence, 다른 페이지는 서버 UTC 선후 관계를 확인합니다. 확인되지 않은 노출은 추정하지 않습니다.

## Seed participant 초대

[Schema·배포 순서·production에서 5개 생성 절차](docs/seed-onboarding.md)를 따릅니다. 새 코드 배포 전에 관리자가 `init-db`로 두 seed 테이블을 등록해야 합니다. 일회용 URL은 방문 시 ‘참여 시작’ 버튼으로 소비하며 처음 방문하는 브라우저만 사용할 수 있습니다. Seed 감상은 공개하되 실험 KPI·emoji/poll 분포·실험 CSV에서는 seed 작성자 행동을 제외합니다. 일반 실험 UI에는 seed 표시를 붙이지 않습니다.

```powershell
python -m flask --app wsgi create-seed-links --count 5 --base-url https://your-production-domain --confirm-production
```

Count는 1–100, 기본 만료는 72시간입니다. 자동 생성하지 않으며 production DB에서는 명시적 확인 옵션이 필수입니다. 이 개발 작업에서는 production migration과 링크 생성을 실행하지 않았습니다.

## 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest -q
node --test tests/client.test.mjs
```

쿠키 유지·차단, GET/프리페치 미집계, 순서·위치, 재시도/충돌/트랜잭션 롤백, 반응 변경·취소·독립 공개 유지, 한 줄/자유 작성·수정·삭제·같은 ID 복원, 자동 커뮤니티 복원, 직접 진입/실제 노출 구분, 50%·본인 글 제외, 좋아요 중복·취소, 답글 수정/삭제·소유권, 테스트 데이터 공개/집계 제외, 0·49·50명·30%·10% 경계, 합집합, 기간 경계, 같은 도서 선행 노출 상호작용, 관리자/CSV 인증과 본문 폐기를 검증합니다.

추가 Node 표준 테스트는 클라이언트의 50%·활성 탭·중복 관측 및 응답 유실 시 같은 요청 재시도를 검증합니다(Node 22 이상). Playwright/Chrome으로 관리자 desktop/mobile viewport와 기존 참여·노출 흐름을 검증합니다. 운영자는 아래 체크리스트의 키보드·실기기 동작도 확인합니다.

관리자 반응형 검증은 `node tests/browser_dashboard.cjs`로 실행합니다. Playwright 경로는 `PLAYWRIGHT_MODULE`, Chrome 경로는 `BROWSER_EXECUTABLE`로 지정할 수 있습니다. 테스트는 임시 SQLite DB만 사용하고 1440px / 390px / 320px의 접힘·펼침 상태에서 overflow와 집계 표시를 검증하며 `artifacts/dashboard/`에 스크린샷을 저장합니다.

## 모집 전 smoke-test 데이터 초기화

[cleanup 사용법과 삭제 범위](docs/cleanup-participation.md)를 따릅니다. `cleanup-participation`은 기본 dry-run이며 명시적 실행 옵션 없이는 데이터를 삭제하지 않습니다. 기존 `init-db`는 참여 데이터를 삭제하지 않습니다.

## 종료·폐기·백업/복구

운영자가 UTC 종료 시각을 `EXPERIMENT_END`에 설정하고 앱을 재시작합니다. 종료 이후 새 쓰기는 거부하고 관리자 집계는 종료 미포함으로 고정합니다. 최소 표본 도달과 종료는 별개입니다.

보관 정책 확정·실험 종료 후, 관련 Export/백업 사본 적용 정책을 확인한 운영자만 다음 명령을 실행합니다. `--before`는 확정된 삭제 시각 기준이고 현재보다 미래일 수 없습니다.

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi purge-deleted-bodies --before "2026-11-01T00:00:00Z" --confirm-copy-policy
```

삭제 상태의 reviews/replies 본문만 비우고 body_purged_at을 남깁니다. 유효 재작성 글은 대상이 아닙니다. ID·최초 제출·이벤트는 유지하고 새 참여 이벤트를 만들지 않습니다. 과거 Export/백업 파일은 이 명령으로 자동 변경되지 않으므로 확정된 사본 정책을 별도로 적용해야 합니다.

로컬 SQLite 백업은 `Connection.backup()`을 이용해 일관된 사본으로 만듭니다. 운영자가 확정한 위치·주기에 수행하며 DB 파일만 실행 중 단순 복사하지 않습니다. 최소 예:

```powershell
.\.venv\Scripts\python.exe -c "import os,sqlite3; source=sqlite3.connect(os.environ['DATABASE']); target=sqlite3.connect('instance/backup.sqlite'); source.backup(target); target.close(); source.close()"
```

복구는 앱을 중지한 상태에서 영속 DB와 WAL/SHM 상태를 확인하고 일관된 백업을 복원한 뒤 `PRAGMA integrity_check`와 `foreign_key_check`, 관리자 집계·최초 참여·삭제/복원·공개 자격·테스트 제외를 검증합니다. 폐기 전 백업 복구는 삭제 본문을 되살릴 수 있으므로 적용된 사본 정책과 폐기 기준을 복원 전에 다시 적용합니다. 복구 파일을 공개 static 디렉터리에 두지 않습니다.

## 실제 실험 전 직접 확인

1. 세 작품의 제공 발췌와 상황 설명을 대조하고 출처·번역본·사용 권한·콘텐츠 버전을 확정합니다.
2. 관측 영역을 확정하고 PC·모바일에서 실제 50% 진입에 따른 excerpt/results/short/others 이벤트를 DB·CSV에서 확인합니다. 매우 긴 카드/목록은 viewport 50%에 도달하지 못할 수 있습니다.
3. 운영 고지·익명 ID 및 이벤트 보관 기간·삭제 본문 폐기 시점·CSV/백업 사본 정책을 정합니다.
4. 운영 시작·종료 방식·시간대·오염/신뢰 불가 기준과 이전 실험 비교 조건을 확정합니다.
5. 별도 테스트 브라우저/ID에서 한 줄 없이 커뮤니티 진입, 새로고침 자동 복원, 취소·삭제 후 결과 유지, 빈 목록/내 글만 있을 때 노출 미발생, 저장 실패 재시도를 확인합니다.
6. 모바일 가로 넘침·본문 줄바꿈·키보드 포커스·이모지 의미·150/300/2000 Unicode 길이를 확인합니다.
7. 운영 HTTPS·Basic 인증·관리자/CSV 비공개·Secure 쿠키·CSRF 보호·영속 DB를 확인하고 비밀값을 유지합니다.
8. 백업/복구를 실제로 시험하고 테스트 visitor가 일반 결과와 지표에서 모두 제외되는지 확인합니다. 자동 테스트의 DB와 로컬 DB를 실험 DB에 합치지 않습니다.

이미지/삽화, 배포 플랫폼 설정 및 실제 운영 배포는 구현하지 않았습니다. 로그인·추천·랭킹·보상·진행률·CMS·중첩 답글 등 요구사항 밖 기능은 추가하지 않았습니다.

개발 이력과 현재 유효 상태는 자동화 테스트의 내부 test_report로 검증합니다. 관리자 /admin/에는 테스트 visitor 전용 집계가 없습니다. 테스트 데이터는 실험 지표·50명 표본·판정 및 실제 참가자 공개 결과/감상에 포함되지 않습니다. 로컬 test visitor끼리 community_open → 카드 50% 노출 others_reveal → 좋아요/답글 흐름을 검증할 수 있습니다.

### 로컬 노출 확인

노출 정책은 cards로 확정되어 이전 실행 설정의 EXPOSURE_POLICY=pending 또는 빈 값도 앱 시작 시 cards로 적용합니다. 설정·코드 변경 전 실행한 서버는 재시작한 뒤 참가자 페이지를 새로 여세요. .env.example을 수정해도 실행 중 서버나 이미 열린 페이지의 bootstrap 설정은 갱신되지 않습니다.

개발자 도구 Network의 Fetch/XHR에서 /api/actions 요청을 확인하세요. Payload의 operation=observe, event_type=others_reveal, target_id, visibility_ratio(0.5 이상), active_tab=true를 확인하고 Response의 HTTP 200과 ok=true를 확인합니다. 검증 실패는 HTTP 400/403/409 및 error로 표시됩니다. Response의 event_id는 요청 식별자입니다. 실제 저장 여부는 관리자 테스트 영역의 others_reveal 이벤트 수·고유 수로 확인합니다. 관측 중복 요청은 새 이벤트를 만들지 않습니다. 관리자 화면은 새로고침해야 갱신됩니다.

브라우저 회귀 테스트는 임시 DB와 독립된 두 브라우저 컨텍스트를 사용합니다. playwright를 설치한 환경에서 node tests/browser_exposure.cjs를 실행하세요. 필요하면 PLAYWRIGHT_MODULE과 BROWSER_EXECUTABLE로 설치 경로를 지정합니다. 기존 pending 설정에서 시작해 HTML의 cards 정책, 실제 DOM/IntersectionObserver, others_reveal HTTP 성공, 좋아요/답글, 관리자 테스트 집계와 실험 집계 격리를 검증합니다.
### 선택적인 장면 일러스트

각 책의 콘텐츠 객체에 다음과 같은 선택 필드를 추가할 수 있습니다. 필드가 없거나 null이거나 src가 비어 있으면 figure/img와 빈 공간을 렌더링하지 않습니다. 현재 세 작품의 PNG 삽화를 연결했으며 값이 없는 콘텐츠 버전에는 빈 placeholder를 표시하지 않습니다.

    "illustration": {
      "src": "images/books/little-prince.png",
      "alt": "어린 왕자와 여우의 장면을 표현한 삽화",
      "width": 1536,
      "height": 1024
    }

src는 app/static/ 기준의 상대 경로입니다. 세 작품 모두 상황 설명과 원문 읽기 사이에 최대 640px 너비로 원본 비율과 height:auto를 유지하며 원본 전체가 보이도록 contain을 사용합니다. width/height에는 원본 픽셀 크기를 기록하여 로딩 전에도 정확한 공간을 확보합니다. 콘텐츠 등록 시 기존 version을 덮어쓰지 않고 새 version/effective_at으로 init-db를 실행합니다. 일러스트는 excerpt_view 관측 대상에 포함되지 않습니다.

원문은 HTML 텍스트를 유지하며, 밝은 종이색 배경에 Noto Sans KR / Apple SD Gothic Neo / Malgun Gothic / 시스템 산세리프 순으로 로컬 글꼴을 사용합니다. 설치되지 않은 글꼴은 다음 글꼴로 대체하며 외부 폰트 요청은 발생하지 않습니다. 제목의 명조 스타일은 유지합니다.

## SQLite / PostgreSQL 선택과 초기화

`DATABASE_URL`이 비어 있으면 기존 `DATABASE` SQLite 경로를 사용합니다. 값이 있으면 psycopg 3 PostgreSQL을 사용하며 연결 실패 시 SQLite로 fallback하지 않습니다. DB 선택은 LOCAL_DEVELOPMENT와 무관합니다. 단, 운영 모드 또는 Vercel에서 URL이 없으면 시작 단계에서 오류가 발생합니다. PostgreSQL에서는 SQLite 파일/디렉터리를 만들지 않습니다.

초기화 명령은 두 DB에서 동일합니다.

```powershell
python -m flask --app wsgi init-db
```

미리 환경변수를 설정한 신뢰할 수 있는 터미널에서 실행합니다. DB/schema 객체와 콘텐츠 버전이 없으면 생성하며, 반복 실행해도 기존 데이터를 삭제하지 않습니다. 이미 저장된 동일 버전의 콘텐츠가 변경되면 거부합니다. 앱 시작과 Vercel 빌드에서 DB를 자동 초기화하지 않습니다. 기존 SQLite 데이터를 PostgreSQL로 자동 복사하는 기능은 없습니다.

DB별 차이는 `app/db_backend.py` 안에 있습니다. 서비스는 동일한 매개변수 SQL과 row 접근을 사용합니다. PostgreSQL은 원래의 정수 boolean, UTC 문자열, JSON 문자열을 유지하며 TEXT에 C collation을 적용합니다. 상태/이벤트/UUID 응답 저장은 한 transaction이며 PostgreSQL advisory lock으로 기존 단일 writer와 재시도 정책을 유지합니다. 관리자/CSV는 repeatable-read snapshot을 사용합니다. 자세한 SQL 전수 조사 결과는 [database-compatibility.md](docs/database-compatibility.md)에 있습니다.

## Vercel deployment

기존 `wsgi.py`의 Flask `app`을 사용합니다. [Vercel Flask 공식 안내](https://vercel.com/docs/frameworks/backend/flask)에 따라 `vercel.json`의 build command가 `app/static/`만 `public/static/`으로 복사합니다. CSS/JS/PNG URL은 `/static/...` 그대로이며 CDN에서 제공합니다. 템플릿, schema, books.json은 함수에 포함되고 instance/비밀 파일은 제외합니다. UI와 JavaScript 계측은 변경하지 않습니다.

1. GitHub repository를 Vercel에 Import하고 framework를 Flask로 확인합니다. 처음 자동 배포가 실패하더라도 다음 설정 후 다시 배포합니다.
2. PostgreSQL provider에서 운영 DB를 생성하고 backup/restore 기능을 확인합니다.
3. provider가 발급한 DATABASE_URL을 준비합니다. TLS 설정을 유지하고, serverless 연결 수 제한에 맞는 pooled endpoint 사용 여부를 provider 안내에서 확인합니다. init-db에는 DDL 권한이 있는 연결이 필요합니다.
4. Vercel Environment Variables에 아래 값을 Production 범위로 등록합니다. Preview는 별도 DB/비밀값으로 격리합니다. 운영 DB를 Preview 또는 테스트에 공유하지 않습니다.
5. production SECRET_KEY를 `python -c "import secrets; print(secrets.token_hex(32))"`로 생성하고 비밀 설정에 저장합니다. 재배포 시 값을 유지합니다.
6. ADMIN_USERNAME / ADMIN_PASSWORD를 안전한 실제 값으로 설정합니다.
7. LOCAL_DEVELOPMENT=0으로 설정합니다.
8. EXPOSURE_POLICY=cards로 설정합니다.
9. 운영자가 결정한 실제 UTC ISO 8601 EXPERIMENT_START를 설정합니다. EXPERIMENT_END는 확정된 경우에만 설정합니다.
10. 확정된 수집/보관 안내를 NOTICE_TEXT로 설정합니다.
11. 정책 검토 완료 후 운영자가 OPERATIONS_CONFIRMED=1을 설정합니다. 실제 실험 시작값과 이 플래그는 이 작업에서 임의로 확정하지 않았습니다.
12. 같은 운영 환경변수와 DATABASE_URL을 설정한 신뢰할 수 있는 터미널에서 `python -m flask --app wsgi init-db`를 실행합니다. 운영 콘텐츠 검증을 통과해야 합니다. HTTP 초기화 endpoint는 없습니다.
13. Deploy/Redeploy합니다. build command는 static 복사만 수행합니다.
14. HTTPS 참가자 페이지, 세 작품, PNG/CSS/JS, 쿠키 유지와 cards 노출 요청을 확인합니다.
15. HTTPS `/admin/` 인증, 집계, CSV 다운로드 및 test visitor 격리를 확인합니다.

필수 비밀/운영 환경변수: `DATABASE_URL`, `SECRET_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`, `LOCAL_DEVELOPMENT=0`, `EXPOSURE_POLICY=cards`, `EXPERIMENT_START`, `NOTICE_TEXT`, `OPERATIONS_CONFIRMED`. 추가 설정: `EXPERIMENT_END`, `DISPLAY_TIMEZONE=Asia/Seoul`, `DATA_RELIABLE`, `DATA_QUALITY_REASON`. DATABASE는 운영에서 사용하지 않습니다. `.env.example`은 빈 placeholder이며 앱이 자동으로 읽지 않습니다. URL/비밀번호/SECRET_KEY를 GitHub, 문서, 로그 또는 public 디렉터리에 넣지 않습니다.

**기존 운영 시작 검증은 유지됩니다.** 현재 콘텐츠 source/translation/usage_status 중 미확정 값이 있으면 LOCAL_DEVELOPMENT=0 시작이 차단됩니다. 실제 운영 전에 출처·번역·사용 가능 여부를 확정해야 하며, 저장된 콘텐츠 버전을 덮어쓰지 않는 기존 version 정책을 따릅니다. 이 DB 지원 작업은 콘텐츠 승인이나 실험 시작 승인이 아닙니다.

운영 PostgreSQL 백업/복구는 DB provider의 backup/restore 기능을 사용합니다. SQLite Connection.backup(), WAL/SHM 파일 복원, PRAGMA 검사는 PostgreSQL에 적용하지 않습니다. 복구 후 관리자 집계/최초 성공 이력/삭제 상태/공개 정책/test visitor 제외를 검증합니다. 위 기존 파일 백업 명령은 로컬 SQLite에만 해당합니다.

## PostgreSQL 통합 테스트

기존 Python/Node 테스트는 그대로 실행합니다. `TEST_DATABASE_URL`이 없으면 PostgreSQL 테스트는 이유와 함께 skip됩니다.

```powershell
# TEST_DATABASE_URL은 비밀 환경변수로 설정한 별도 테스트 DB URL
python -m pytest -q -rs
node --test tests/client.test.mjs
```

TEST_DATABASE_URL은 운영 DATABASE_URL과 달라야 하며 운영 데이터를 사용하지 않습니다. 테스트마다 임시 UUID schema를 CREATE/DROP하므로 전용 테스트 계정에 해당 권한이 필요합니다. 기존 HTTP 정책/관리자 테스트를 PostgreSQL에서도 재사용하며, 같은 fixture를 SQLite/PostgreSQL에 넣어 실제/테스트 집계 결과를 비교합니다. PostgreSQL URL이 없는 실행 결과만으로 실제 PostgreSQL 검증이 완료되었다고 판단하지 않습니다.
