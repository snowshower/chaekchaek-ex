# 모집 전 참여 데이터 초기화

실제 사용자 모집 전, DB에 개발 smoke-test 데이터만 있을 때 운영자가 직접 실행하는 명령입니다. Production DB cleanup은 이 개발 작업에서 실행하지 않았습니다.

대상 DB와 운영 환경변수는 신뢰하는 터미널에서 미리 설정합니다. 앱은 `.env`를 자동으로 읽지 않습니다. Production에서는 기존 DATABASE_URL·SECRET_KEY·시작 시각·고지·OPERATIONS_CONFIRMED 등 gate를 그대로 통과해야 합니다. 명령은 URL이나 credential을 출력하지 않습니다.

1. 참여 요청을 중지하고 모집 전 상태인지 확인합니다. 실행 후 새 요청이 오면 다시 데이터가 생성됩니다.
2. 아래 dry-run의 visitor 수와 테이블별 수를 검토합니다.
3. 실제 사용자 없음 확인과 dry-run의 정확한 visitor 수를 실행 옵션으로 전달합니다.
4. 다시 dry-run을 실행하여 참여 테이블이 0인지 확인합니다.

```powershell
# 기본 동작도 dry-run입니다.
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-participation --dry-run

# N을 dry-run에서 확인한 총 visitor 수(test + non-test)로 바꿉니다.
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-participation --execute --confirm-no-real-users --expect-visitors N

# 실행 후 확인
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-participation --dry-run
```

`--execute`만 전달하거나 확인 옵션이 빠지면 거부합니다. `--dry-run`과 `--execute`는 함께 사용할 수 없습니다. 실행 transaction에서 visitor 수가 달라졌으면 삭제 전에 거부하므로 dry-run을 다시 확인합니다. `--expect-visitors`는 같은 수의 다른 데이터로 교체된 상황까지 식별하는 fingerprint는 아닙니다. 실행 중 모집·참여를 중지해야 합니다.

실제 SQLite/PostgreSQL schema의 FK 순서대로 다음 9개 테이블의 **모든 행**을 삭제합니다. test/non-test visitor를 모두 포함하며 취소·삭제된 참여 상태와 이전 기간의 이력도 포함합니다.

| 삭제 순서 | 테이블 | 데이터 |
|---|---|---|
| 1 | requests | request/idempotency 응답 |
| 2 | events | 모든 행동 및 exposure 이력 |
| 3–4 | likes, replies | 좋아요·답글 |
| 5–6 | emoji_reactions, poll_votes | 이모지·투표 |
| 7 | reviews | 한 줄 감상·자유 감상 |
| 8 | page_views | 페이지·콘텐츠 버전 참조 |
| 9 | visitors | test/non-test visitor 및 식별 정보 |

`events`는 `page_views`, `likes/replies`는 `reviews`를 참조하고 참여 테이블은 `visitors`를 참조합니다. FK를 끄거나 CASCADE/TRUNCATE로 삭제 범위를 넓히지 않습니다. Schema와 인덱스, `books`와 `book_contents`의 모든 버전을 보존합니다. 현재 schema에는 별도 운영 설정 테이블이 없으며 환경변수 설정은 수정하지 않습니다.

삭제·개수 확인은 한 write transaction에서 수행합니다. PostgreSQL은 기존 advisory lock과 참여 테이블의 SHARE ROW EXCLUSIVE lock을 사용하고, SQLite는 BEGIN IMMEDIATE를 사용합니다. 실패 시 전부 rollback합니다. dry-run은 읽기 transaction에서 개수만 조회하고 rollback합니다. 기존 cookie는 삭제된 visitor를 찾지 못하면 새 visitor로 발급됩니다. 관리자 집계는 0 / N/A부터 시작하며 콘텐츠 재등록은 필요 없습니다.

dry-run 출력 예시(임시 테스트 fixture의 2명이며 production 측정값이 아닙니다):

```text
DRY RUN: no rows deleted
visitors: 2 (test=1, non_test=1)
requests: 11
events: 11
likes: 1
replies: 1
emoji_reactions: 1
poll_votes: 1
reviews: 2
page_views: 2
visitors: 2
PRESERVE books: 3
PRESERVE book_contents: 6
```
