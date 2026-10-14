# 정적 검증 (Showdown 데이터 vs 우리 DB)

도구: `node verify/sd_dump.js showdown verify/out/sd_dump.json` → `python -m verify.static_diff` (기술/종 필드 비교, `verify/out/static_diff.csv`) → `python -m verify.hook_diff` (특성/도구 훅 대조, `verify/out/hook_diff.csv`).

## 1단계: 기술·종 필드 비교 — 차이 15건 (기술 약 500개, 종 전체)
기술 위력/명중/PP/우선도/분류/타입/급소/연속/반동/흡수/회복/교체/자폭/flags/부가효과를 전수 비교했고 거의 일치한다. 남은 차이:
- 표현 차이(실제 동작은 별도 확인 필요): 삼격(Tri Attack), 저주(Curse), 혼 가르기(Spirit Shackle), 인후베기(Throat Chop), 질투의불꽃(Burning Jealousy), 디아클로(Dire Claw), 홀리는보이스(Alluring Voice)는 우리 쪽에만 효과 행이 있고 Showdown은 condition/hook 로 처리.
- 되살리기(Revival Blessing) `self_switch`: 의도적 수정 (manual_fixes).
- 클랭잉스케일(Clanging Scales): Showdown 은 사용 후 방어 -1, 우리에는 없음 → **실제 누락 후보**.
- 클랭고소울(Clangorous Soul) 명중 255 vs 필중: 동작 동일.
- 우리 `game_move`(챔피언스)에 없고 Showdown 에는 있는 기술: Pound, Soft-Boiled, Spore, Power Shift (Struggle 은 엔진이 주입). 습득 가능 여부(learnset)는 미확인.

## 2단계: 특성·도구 훅 대조 — 106건 (메타 등장 기준), 노이즈 많음
Showdown 핸들러 이름을 우리 훅 분류로 매핑해 비교했다 (`MAP` in hook_diff.py). 열매(Berry)처럼 `modify_dmg_taken` 등 다른 훅으로 구현된 것이 오탐으로 잡히므로 **수동 검토용 목록**이다. 구현 흔적(코드 문자열) 없는 56건 중 우선 확인할 것 (메타 가중치 순): 시트러스열매, 열교환, 심안(Scrappy), 페어리오라, 우의(Defiant), 승부욕(Competitive), 두꺼운지방(Thick Fat), 순한맛(Oblivious), 이너프(Innards Out) 등. 전체는 CSV 참고.

## 후속 조치 (확인 결과)
- 클랭잉스케일: `etl/manual_fixes.py` 에 스케일샷과 함께 자기 방어 -1 효과 추가 (적용 완료).
- 훅 목록의 우선 항목을 시뮬레이션으로 확인: `verify/focus_cases.py abil` (신규 카테고리: 열교환/스크래피/페어리오라/우의/승부욕/두꺼운지방/순한맛/이너프/열매·씨앗 등) 700개 x 100회 → 불일치 1건뿐이었고 **정화의소금 + 잠자기(Rest)가 잠들던 버그**를 수정 (`ai/battle.py`). 재실행 0건. 즉 훅 대조 목록 106건은 대부분 다른 훅으로 구현된 오탐이다.

## 3단계: 사건 순서 추적 비교 (`verify/trace_cmp.py`)
1턴 동안의 사건(피해/회복/상태이상/능력변화/교체)의 **순서열 분포**를 Showdown(프로토콜 로그, SD_LOG=2 로 |split| 유지) 과 우리 엔진(`st.trace`, `Engine._tr`)에서 비교한다. 연속 중복·연속 능력변화(서로 독립)·열매 소비/회복 순서는 정규화, 도구 소모 토큰은 제외(엔진 여러 곳에서 직접 비워 추적이 불완전).
- 800 시나리오 x 100회 → 순서열 불일치 14개(정규화 전 129개). 남은 것은 대부분 순서만 다른 무해한 차이:
  - 몸에 닿는 반격(울퉁불퉁멧/까칠한피부) 피해 vs 기술의 자기 능력 변화: Showdown 은 자기 변화가 먼저, 우리는 반격이 먼저.
  - 드래곤테일의 끌어내기 vs 생명의구슬 반동: Showdown 은 반동이 먼저.
  - 추적 누락(직접 HP/상태를 바꾸는 곳: 잠자기, 생명의구슬 반동 등).
- 실제로 동작을 바꾸던 순서 버그 수정:
  - 잔여 효과 순서: 가속(Speed Boost)/변덕쟁이/악몽 특성은 Showdown order 28 로 먹다남은음식(5)보다 늦다 (`ai/battle.py` turn_end 정렬).
  - HP 열매(오렌/자뭉열매 등) 소비 시점: Showdown 은 잔여 효과 하나가 끝날 때마다 Update 로 열매를 먹는다 -> 모래바람 피해 직후 시트러스를 먹고 그래스필드 회복이 그 뒤에 온다. 우리는 턴 끝에 한 번만 판정해서 (HP 102 -> 모래바람 90 -> 필드 회복 102) 같은 경우 열매를 놓쳤다. 모래바람/그래스필드/도구·특성 잔여 효과/독·화상 뒤에 판정하도록 수정.
  - 기습(Sucker Punch): 상대가 발버둥(Struggle)을 쓸 때도 성공해야 한다 (봉인으로 기술이 막힌 경우).
  - 정화의소금 + 잠자기(Rest) 실패 (1단계 후속).
- 수정 후 회귀: `verify_turns` 1턴 1000개/2턴 600개/3턴 800개 모두 불일치 0, `focus_cases all/abil` 0.

## 한계와 다음 단계
- 정적 비교는 데이터와 훅 존재 여부만 본다. 처리 순서·상태 상호작용은 3단계(이벤트 추적 비교)가 필요.
- 다음: 추적 누락 지점(직접 HP/상태 변경)에 `_tr` 보강, 2턴 이상 추적, 남은 순서 차이(자기 변화 vs 반격, 끌어내기 vs 반동) 정리.
