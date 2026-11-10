# 백엔드 실행 (Plan 1)

## 개발 서버
    uv run uvicorn timeable.api.main:app --reload
- API 문서(자동): http://127.0.0.1:8000/docs
- 헬스체크: GET /health

## 엔드포인트 (Plan 1, 그룹은 'dummy' 하나)
- GET /groups/{id}/field?min_duration=1        히트맵/지형 스칼라 필드
- GET /groups/{id}/availability?min_free=&min_duration=1   수위 블록 목록
- GET /groups/{id}/candidates?min_free=&k=3    상위 후보

## 테스트
    uv run python -m unittest discover -s tests

## 다음 (Plan 2)
db.load_group() 을 Supabase 조회로 교체하면 라우트는 그대로 동작한다.
