# 모집 전 normal smoke-test 정리

기존 `cleanup-participation` 전체 초기화와 별개의 명령이다. 대상은
`visitors.is_test=0` AND `seed_participants`에 연결되지 않은 visitor 전체다.
실제 모집 전이라는 운영자 확인을 전제로 하며, 데이터만으로 smoke-test와 실제
사용자를 구별하지 않는다. 기간, 취소 여부, soft-delete 여부와 관계없이 대상
visitor의 모든 참여 이력을 제거한다.

삭제 순서는 requests → events → likes → replies → emoji_reactions → poll_votes
→ reviews → page_views → visitors다. 모두 visitor_id로 필터링하므로 normal이
seed review에 남긴 like/reply/exposure/event도 제거된다. seed_participants,
seed visitor의 short/full review 및 emoji/poll, test visitor와 소유 데이터,
books/book_contents/seed_invites는 수정하지 않는다. invite의 used_at도 유지된다.
다른 actor의 like/reply가 삭제 대상 review를 참조하거나 다른 actor의 event가
대상 page_view를 참조하면 자동 확장 삭제 대신 전체 작업을 거부한다.

기본은 dry-run이다. 삭제할 normal visitor 수와 각 참여 테이블 row 수,
보존할 seed visitor/review 및 test visitor 수, 보존 테이블 수, 차단 참조 수를
출력한다. execute도 동일한 계획을 삭제 전에 출력한다. seed review 수는
soft-delete된 것을 포함한 short/full 전체 row 수다.

production 환경변수가 이미 안전하게 설정된 운영자 터미널에서 실행한다.
명령은 DATABASE_URL이나 credential을 출력하지 않는다. 앱의 기존 production
설정 검증도 그대로 적용되며 `.env`를 자동 로드하도록 변경하지 않는다.

```powershell
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-normal-participation --dry-run

# dry-run에서 DELETE visitors: 1을 확인한 현재 상황의 실행 명령
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-normal-participation --execute --expect-normal-visitors 1 --confirm-no-real-users --confirm-production

# 실행 후 확인
.\.venv\Scripts\python.exe -m flask --app wsgi cleanup-normal-participation --dry-run
```

`--expect-normal-visitors N`은 dry-run의 정확한 대상 수를 사용한다. 1은 예시이며
코드의 고정값이 아니다. 개수만 비교하므로 동일한 수의 다른 visitor로 교체되는
상황은 감지하지 않는다. 모집 및 참여 요청을 멈춘 상태에서 확인하고 실행한다.
정리 후 일반 URL을 다시 방문하면 기존 cookie도 새 visitor로 발급될 수 있다.

execute는 하나의 transaction에서 count guard와 삭제를 처리한다. SQLite는
BEGIN IMMEDIATE, PostgreSQL은 기존 advisory lock 및 관련 테이블의
SHARE ROW EXCLUSIVE lock으로 동시 쓰기를 차단한다. 오류 시 전체 rollback한다.
remote DATABASE_URL, VERCEL 또는 LOCAL_DEVELOPMENT=False이면 execute에
`--confirm-production`이 반드시 필요하다. dry-run은 읽기 transaction을 rollback한다.
