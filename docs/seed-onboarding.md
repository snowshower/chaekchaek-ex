# Seed participant onboarding

Seed는 초기 공개 감상을 만드는 내부 참여자입니다. DB의 `seed_participants`에 visitor ID를 영구 연결합니다. 기존 `visitors.is_test`·exclusion_reason과 일반 URL의 생성 정책은 유지합니다. 기존 visitor를 seed로 전환하는 query parameter나 사후 지정 CLI는 제공하지 않습니다.

| Cohort | short/full 공개 | 실험 KPI | emoji/poll 공개 분포 | 실험 CSV 작성자 행 |
|---|---|---|---|---|
| normal | O | O | O | O |
| seed | O | X | X | X |
| test | Production X; 로컬 격리 유지 | X | Production X; 로컬 test 분포 유지 | 기존 test 원천/사유 유지 |

감상에는 seed 표시를 붙이지 않습니다. 일반 visitor가 seed 카드를 활성 탭에서 50% 이상 실제로 보면 그 **일반 visitor의** others_reveal은 기존 정책대로 집계합니다. 일반 visitor → seed 감상의 like/reply도 집계합니다. 기간·고유 사용자 합집합·분모·최초 성공·선행 노출·페이지별 중복 제거 정의는 변경하지 않습니다.

## Schema와 배포

기존 테이블을 ALTER하지 않고 SQLite/PostgreSQL schema에 두 테이블을 추가합니다.

- `seed_invites`: SHA-256 `token_hash` PK, `created_at`, `expires_at`, nullable `used_at`. Token 원문이나 credential은 저장하지 않습니다.
- `seed_participants`: `visitor_id` PK/FK → visitors, `created_at`. Visitor의 seed 여부를 정규화한 영구 상태입니다.

**새 코드가 요청을 받기 전에 테이블을 등록해야 합니다.** 관리자가 새 checkout과 production 환경변수로 직접 실행하고 그 후 배포합니다.

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi init-db
```

기존 `init-db`의 CREATE TABLE IF NOT EXISTS를 이용한 additive migration입니다. 반복해도 visitor·참여·콘텐츠 이력을 삭제하거나 cohort를 재분류하지 않습니다. 동일 콘텐츠 버전 덮어쓰기 거부와 운영 gate를 유지합니다. 요청/빌드에서 자동 실행하지 않습니다. DATABASE_URL·SECRET_KEY·시작 시각·고지·OPERATIONS_CONFIRMED 등 기존 운영 설정을 충족해야 합니다. 이 개발 작업에서는 production migration이나 링크 생성을 실행하지 않았습니다.

## 관리자 CLI: production에서 5개 생성

CLI는 서버/DB 접근 권한을 가진 관리자가 신뢰하는 터미널에서 사용합니다. 공개 HTTP 생성 endpoint나 일반 화면의 초대 링크는 없습니다. 기존 Basic 인증 관리자 화면과 별도로 CLI의 운영 권한은 서버/DB credential 접근 권한으로 제한합니다.

1. Production DB와 도메인에 맞는 환경변수를 보안 터미널에 설정합니다. 앱은 `.env`를 자동으로 읽지 않습니다.
2. 새 checkout에서 `init-db`를 실행하고 배포합니다.
3. `LOCAL_DEVELOPMENT=0`과 DB provider/project가 production인지 배포 환경 설정에서 확인합니다. 아래 도메인을 실제 도메인으로 바꿉니다.
4. 먼저 확인 옵션 없이 실행하면 환경 상태와 공개 origin만 출력한 뒤 **DB 쓰기 없이 거부**합니다.

```powershell
python -m flask --app wsgi create-seed-links --count 5 --base-url https://your-production-domain
```

5. 확인 후 명시적 production 옵션으로 생성합니다. PowerShell에서도 아래 한 줄을 그대로 사용할 수 있습니다.

```powershell
python -m flask --app wsgi create-seed-links --count 5 --base-url https://your-production-domain --confirm-production
```

6. 출력된 서로 다른 URL을 팀원에게 하나씩 비공개 전달합니다. 팀원은 실험 URL을 아직 열지 않은 브라우저 프로필로 접근합니다. URL은 bearer credential이므로 일반 안내·공개 채널·스크린샷·로그에 공유하지 않습니다.

`--count`는 1–100입니다. 기본 만료는 생성 후 **72시간**, `--expires-hours`는 1–168시간입니다. 예:

```powershell
python -m flask --app wsgi create-seed-links --count 5 --base-url https://your-production-domain --expires-hours 24 --confirm-production
```

로컬 SQLite에서는 확인 옵션 없이 `--base-url http://localhost:8000`을 사용할 수 있습니다. PostgreSQL이면 LOCAL_DEVELOPMENT=1이어도 `--confirm-production`을 요구합니다. Production/remote는 HTTPS origin만 허용하고 userinfo·path·query·fragment를 거부합니다.

CLI는 LOCAL_DEVELOPMENT, DB 종류, 공개 target_origin, 만료 시각, 완성 URL만 출력합니다. DATABASE_URL, SECRET_KEY, DB 이름/주소/credential은 출력하지 않습니다. Origin과 실제 DB의 대응은 관리자가 배포 설정으로 확인해야 하며 도메인으로 DB를 추정하지 않습니다. DB transaction이 commit된 뒤 URL을 출력합니다. 생성은 visitor·page_view·event·request·KPI를 만들지 않으며 앱 시작/배포 시 자동으로 5개를 생성하지 않습니다.

## 첫 진입과 일회용 보호

초대 URL GET → ‘참여 시작’ 화면 → 버튼 POST → token 소비와 seed visitor 생성 → 기존 cookie 확인 → 일반 랜딩 페이지.

GET/HEAD는 visitor를 만들거나 token을 소비하지 않습니다. 메신저/메일 미리보기와 프리페치를 고려한 방식입니다. POST는 10분짜리 서명 form과 브라우저 nonce cookie가 필수입니다. 다른 구체적 origin의 POST를 거부합니다. no-referrer 설정 때문에 Chrome이 Origin: null을 보낼 수 있으므로 null/미전송 origin도 동일한 서명·nonce 검증을 반드시 통과해야 합니다.

기존 visitor cookie가 있는 브라우저는 GET/POST 모두 거부합니다. Form을 연 뒤 다른 탭에서 normal visitor가 생성된 경우와 오래되거나 검증 불가능한 cookie도 전환하지 않습니다. 기존 normal URL에는 seed 처리 분기가 들어가지 않습니다.

256-bit 난수 token을 생성하며 DB에는 SHA-256 hash만 저장합니다. POST의 단일 write transaction에서 `used_at IS NULL AND expires_at > 현재 UTC` 조건으로 소비하고 visitor와 seed 연결을 함께 생성합니다. 동시 사용은 한 요청만 성공하고 생성 실패는 token 소비까지 rollback합니다. 사용한 URL을 다른 새 브라우저에서 다시 열어도 visitor를 만들지 않습니다. 만료는 링크에만 적용하고 이미 생성된 seed 상태를 해제하지 않습니다.

재방문은 기존 visitor cookie로 같은 visitor를 찾아 DB의 seed 연결을 적용합니다. 기존 익명 식별 정책(30일 cookie)을 유지합니다. Cookie 삭제·만료·브라우저 변경 시 동일인을 복구할 수 없으므로 최초 지정한 프로필을 계속 사용합니다. 응답 유실 등으로 cookie를 받지 못했다면 이미 소비된 링크를 복원하지 않으며 관리자에게 새 링크를 요청합니다.

초대 응답은 no-store / no-referrer이고 token을 일반 페이지 redirect에 남기지 않습니다. 호스팅·프록시 access log에서 `/seed/*` URL과 POST 본문을 기록/공유하지 않도록 운영 설정을 확인합니다.

## Query, CSV, cleanup

- `period_events`: is_test 필터와 별개로 seed 작성자 event를 제외합니다. `include_test=True` export에도 seed event를 포함하지 않습니다.
- `current_counts`: 참여 작성자를 기준으로 seed를 제외합니다. Like/reply 대상인 seed 감상 작성자를 제외하지 않으므로 normal → seed 상호작용을 집계합니다.
- 공개 감상·interaction 대상·exposure 대상: 기존 is_test 검증을 유지하고 seed는 공개합니다.
- Emoji/poll 공개 결과: seed 작성자 상태를 제외합니다. Seed 본인의 선택·수정·취소는 유지합니다.
- CSV: events, visitors, 참여 상태, page_views에서 seed 작성자 행을 제외합니다. Normal의 seed 대상 event와 like/reply는 유지합니다. 따라서 seed review ID를 참조하는 normal event가 있어도 해당 seed review 행 자체는 reviews.csv에 없습니다. Invite/seed 테이블이나 token hash를 export하지 않습니다.
- 모집 전 cleanup: seed_participants를 visitors보다 먼저 삭제합니다. seed_invites는 운영 metadata로 보존하여 사용한 링크가 cleanup 후 다시 유효해지지 않게 합니다. 미사용 링크도 기존 만료/사용 상태를 보존합니다.

## 검증

`tests/test_seed.py`는 첫 진입·재방문·hash-only 저장·CLI 범위/환경 확인·만료·cookie/CSRF·경쟁 사용·rollback·세 cohort의 공개/집계 분리·normal → seed 상호작용·CSV 제외·반복 init-db·이전 schema 보존을 검증합니다. 동일 테스트를 전용 PostgreSQL fixture에도 등록했습니다. `tests/browser_seed.cjs`는 임시 SQLite와 실제 Chrome에서 onboarding·카드 50% 관측·normal KPI를 검증합니다.
