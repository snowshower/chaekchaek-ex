# 유입 채널 추적

`visitor_attributions(visitor_id PRIMARY KEY REFERENCES visitors, source CHECK(...))`를
두 DB schema에 추가했다. 새 visitor를 발급할 때만 source를 저장한다. 기존 visitor는
행을 만들거나 덮어쓰지 않으며 조회 시 direct로 표시한다. seed onboarding은 별개다.

허용값은 slack, everytime, dc, arca, threads, instagram, direct다. src는 앞뒤 공백을
제거하고 소문자로 변환한다. 누락·잘못된 값은 direct다. 반복 src는 Flask의 첫 값을
사용한다. URL, query string, referrer, UA는 attribution 테이블에 저장하지 않는다.

관리자 유입 채널 섹션은 기간 내 normal 이벤트만 사용한다. Landing UV는 landing_view
고유 visitor이며 Book View UV는 기존 전체 KPI와 같은 책별 자격 사용자 합집합이다.
Light Participation, Short Impression, Community Open, Others Reveal은 기존 지표
사용자 집합을 채널별로 분할한다. 분모는 해당 채널 Book View UV이고 0명은 N/A다.
seed/test를 제외하며 채널별 성공 판정을 하지 않는다.

페이지 bootstrap 이후 history.replaceState로 src만 제거한다. 추가 요청·redirect·event는
없으며 다른 query와 hash는 보존한다. 내부 링크에 src를 전달할 필요가 없다.

CSV는 기존 파일과 제외 정책을 유지한다. visitor_sources.csv는 normal visitor_id/source,
source_funnel.csv는 normal 채널 집계를 제공한다. events.csv에는 acquisition_source가
추가되며 기존 test 포함 정책은 그대로다. 새로운 source CSV에는 seed/test나 비밀정보가 없다.

device는 이번 변경에서 제외했다. UA에는 iPad desktop 모드 등 구분 불가능한 경우가 있어
네 가지 category를 신뢰할 수준으로 구현하려면 별도 parsing/추정 정책이 필요하다.

## 운영 적용

production에서는 아직 실행하지 않았다. 새 코드가 요청을 받기 전에 운영 환경변수와
DATABASE_URL을 설정한 신뢰할 수 있는 터미널에서 다음을 실행한다.

```sh
python -m flask --app wsgi init-db
```

SQLite와 PostgreSQL 모두 CREATE TABLE IF NOT EXISTS로 새 테이블만 추가하므로
반복 실행할 수 있다. 기존 visitor/seed/review/event/content를 삭제하거나 재분류하지 않는다.
기존 init-db의 콘텐츠 버전 검증은 유지된다. 배포는 schema 적용 후 새 트래픽을 받게 한다.

운영 도메인의 `/`에 `?src=slack`, `?src=everytime`, `?src=dc`, `?src=arca`,
`?src=threads`, `?src=instagram`을 붙인다. 이미 배포된 일반 Slack URL은 direct로 남는다.
