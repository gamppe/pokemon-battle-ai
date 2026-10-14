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

## 한계와 다음 단계
- 정적 비교는 데이터와 훅 존재 여부만 본다. 처리 순서·상태 상호작용은 3단계(이벤트 추적 비교)가 필요.
- 다음: `battle-actions.ts`/`battle.ts` 처리 순서 체크리스트 → Showdown/우리 엔진 양쪽에 이벤트 추적 기록 → 첫 어긋남 지점 비교.
