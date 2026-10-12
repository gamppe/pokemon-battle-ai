# 진행 상황 (2026-10-12 저장)

## 완료
- Smogon 메타 수집(`etl/collect_meta_smogon.py`) + `build_all.py` 통합(`SKIP_META=1` 로 건너뜀). 재빌드/비교 통과.
- 턴 엔진 v1: `ai/battle.py` (특성/도구 효과는 DB hook 행 `ability_effect`/`item_effect` 를 읽어 적용), `ai/meta.py`(세트 샘플러), `ai/policy.py`(휴리스틱 + 몬테카를로 승률), `ai/bench.py`.
  - MC(30롤아웃) vs 휴리스틱 79:21, 휴리스틱끼리 좌우 대칭 ≈ 50:50.
- 엔진 검증 하네스: `verify/sd_turns.js`(Showdown 시나리오 실행) + `verify/verify_turns.py`(분포 비교: KS/카이제곱) + `verify/dbg_turn.py <시나리오id>`(우리/Showdown 로그 나란히).
  - 실행: `python -X utf8 verify/verify_turns.py --n 300 --runs 100 [--turns 2] [--show]`
  - 불일치 시나리오: 98/300 → 37 → 17/300 (1턴 기준)

## 현재 검증 결과 (엔진 v1.2, Showdown 분포 대조)
| 시드 | 시나리오 | 턴 | 불일치 |
|---|---|---|---|
| 1 | 300 | 1 | 98 → 2 |
| 5 | 1000 | 1 | 22 → 4 |
| 11 | 1000 | 1 | 4 (0.4%) — 그중 2개는 변신(Ditto) |
| 3 | 500 | 2 | 44 → 3 |
| 12 | 600 | 2 | 16 (2.7%) |
- 데미지 계산기 회귀(`verify_damage.py --n 3000`): 불일치 없는 규칙 100/100
- DB 재빌드 일치(`SKIP_META=1 build_all.py pokemon_check` + `compare_db.py`): 차이 0

## 이번에 구현한 것
도발, 안개제거, 아픔나누기, 죽기살기, 대검돌격, 막말내뱉기, 배턴터치, 꼬리자르기, 프리즈드라이(효과 배수 규칙),
비축하기, 트릭(메가스톤 예외), 하품, 앵콜, 메멘토, 카운터류, 버티기, 대타출동, 충전 기술(솔라빔/전자포 등, 반무적 상태 포함),
희망사항/치유소원, 저주, 속박, 힐블록, 난동(아웃레이지), 안전모(탈), 스탠스체인지, 프로틴/리베로, 낙오카드/탈출버튼 지연 발동,
저항 열매/젬 소비, 진행 상태 의존 위력(Avalanche/Assurance/Payback/Lash Out/Stomping Tantrum/Rage Fist/Last Respects/Supreme Overlord),
사이코필드 선공기 차단, 등장 직후 1회 기술(Fake Out 등)의 선택 불가 처리(Showdown과 동일).
- 데이터 보정(`etl/manual_fixes.py`): 스케일샷 부가효과(방어 -1/스피드 +1) 추가, 되살리기의 self_switch 오표기 수정

## 남은 불일치
- 변신/Imposter(Ditto) 미구현 — 해당 시나리오 전부가 여기에서 나옴
- 삼연축(Triple Axel) 접촉 특성 타수별 처리, 탈출버튼 분포, 일부 2턴 교체 후 효과(위 표의 시드 12 상세는 `verify/out/turns_mismatch.json`)
- Poison Touch 가 Showdown 에서 Indeedee 에게는 걸리지 않는 현상 (원인 미확인)
- 미지원 효과 집계는 `eng.unsupported` (도감 외 효과)

## 다음 단계
1. 위 불일치 해결 → `--turns 2` 로 확장 → 다른 스냅샷(`--snap`)으로도 검증
2. 2단계: 상대 세트 추론기(베이즈, 메타 prior, 티어 파라미터)
3. 3단계: 승률 평가 개선(탐색 속도, 상대 응답 모델), 선출/파티 선택
4. 리플레이 수집기(Showdown 공개 리플레이) — 사용자 확인 후
- 커밋/푸시는 사용자가 요청할 때만 (현재 미커밋 변경 다수: ai/, verify/, etl/build_all.py 등)
