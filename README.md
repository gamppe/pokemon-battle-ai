# pokemon-battle-ai

포켓몬 **챔피언스(Reg M-C) 싱글 배틀 AI**(파티 구성 + 선출 + 배틀)를 만드는 프로젝트입니다.
현재는 AI의 기반이 되는 **MySQL 데이터베이스와 구축·검증 스크립트**가 들어 있고, AI 코드는 이어서 추가합니다.
도감·기술·특성·아이템을 모으고, 배틀 AI가 바로 쓸 수 있도록 **효과를 수치/규칙으로 구조화**했으며,
[Pokémon Showdown](https://github.com/smogon/pokemon-showdown) 시뮬레이터 값과 자동 대조 검증합니다.

*English: a battle-AI project for Pokémon Champions (Reg M-C, singles). It currently contains the MySQL database and ETL/verification
scripts — dex/moves/abilities/items plus machine-readable battle rules, cross-checked against Pokémon Showdown. AI code is coming next.*

> 비공식 팬 프로젝트입니다. 포켓몬 관련 명칭·데이터의 권리는 Nintendo / Creatures / GAME FREAK / The Pokémon Company에 있으며,
> 이 저장소는 공식 자료가 아닙니다. 제3자 원본 데이터(PokeAPI, Showdown 등)는 저장소에 포함하지 않고 스크립트로 내려받습니다.

## 들어 있는 것
| 영역 | 내용 |
|---|---|
| 기본 도감 | 포켓몬(폼 포함 1,170여 종), 기술 919, 특성 374, 아이템, 한글/영문 이름, 종족값, 타입 상성 |
| 게임별 존재 여부 | SwSh · SV · ZA · Champions 별 포켓몬/기술/아이템/습득 기술/특성 |
| 챔피언스 기준 | Reg M-C 허용 목록(약 350종), 티어, 메가진화, 레벨 50·SP 66점 규칙, 싱글 6 중 3 선출 |
| 기술 수치화 | 대상/급소/연속/흡수/반동, 플래그, 부가효과, 챔피언스 전용 변경, 위력 공식·사용 조건·충전·방어/분신 상호작용 |
| 특성·아이템 수치화 | 특성 215개, 아이템 166개를 hook/조건/배율의 규칙 행으로 정리 |
| 이름/몸무게 | 한글·영문·**일본어** 이름(`name_ja`, 폼은 `form_name_ja`), 포켓몬 몸무게(`weight_kg`) |
| 배틀 규칙 | 날씨·필드·방·진영·상태이상(`battle_state`), 처리 순서(`battle_phase`), 전역 상호작용(`battle_rule`) |

## 요구 사항
- MySQL 8.0 (`mysql` CLI가 PATH에 있어야 함), Python 3.11+, Node.js 20+ (Showdown), git
- `pip install -r requirements.txt`

## 빠른 시작
```bash
# 1) 접속 정보는 환경변수로 (코드에 비밀번호가 없습니다)
export DB_PASSWORD='...'          # 필요하면 DB_USER(기본 root), DB_HOST(기본 localhost)

# 2) 정답 비교용 Showdown 설치 (저장소 바깥 자료이므로 직접 받습니다)
git clone --depth 1 https://github.com/smogon/pokemon-showdown.git showdown
(cd showdown && npm install --ignore-scripts && node build)

# 3) DB 전체 구축 (스키마 -> 외부 원본 다운로드 -> 적재 -> 규칙 구조화)
cd etl
python -X utf8 build_all.py pokemon          # 새 DB 이름. 기존 같은 이름 DB는 삭제 후 재생성됩니다
```
처음 실행은 PokeAPI 캐시(수백 MB)와 pokemondb ZA 습득 기술 수집(예의상 요청 간격 2초, 약 15분) 때문에 오래 걸립니다.
수집한 원본은 `etl/cache*`에 저장되고 `.gitignore`로 제외됩니다.

## 검증
```bash
node verify/sd_dump.js showdown verify/out/sd_champions.json      # Showdown(챔피언스 모드) 정답 덤프
python -I -X utf8 verify/verify_static.py --db pokemon              # DB vs Showdown 정적 데이터 비교
python -X utf8 etl/compare_db.py pokemon_check                      # 두 DB를 행 단위 비교 (재현성 확인)
```
```bash
python -X utf8 verify/verify_damage.py --n 8000 --seed 1   # DB 데미지 계산기(ai/damage_calc.py) vs Showdown 데미지 비교
```
`verify_damage.py`는 무작위 시나리오(포켓몬·특성·도구·SP·날씨·필드·벽·상태·급소)를 만들어 양쪽의 16단계 난수 데미지를 비교하고,
불일치가 많은 규칙을 단계별로(위력/타입/최종 보정) 분류해 보여 줍니다.

`verify_static.py`는 허용 포켓몬, 종족값, 타입, 특성, 습득 기술, 기술 수치/플래그/부가효과, 아이템·특성 목록,
상성표, 성격을 비교합니다. 비교 도구의 한계로 생기는 오탐은 코드에 사유와 함께 명시했습니다.

## 폴더
```
schema.sql            전체 테이블 정의
etl/                  원본 다운로드 · 적재 · 규칙 데이터(수작업) · build_all.py
  ability_effects_data.py  item_effects_data.py  move_rules_data*.py  battle_state_data*.py   ← 직접 정리한 규칙
verify/               Showdown 대조 검증 (sd_dump.js, verify_static.py)
ai/                   데미지 계산기(damage_calc.py), DB 로더(gamedata.py) / (예정) 에이전트, 파티 구성/선출
docs/                 AI 설계 노트(요구 사항, 구조, 메타 수집원 조사)
```

## 한계 (솔직하게)
- 특성·아이템·기술 규칙은 Showdown 소스를 읽고 **사람이/AI가 수작업으로 옮긴 값**입니다. 정적 데이터(목록·수치·플래그)는 Showdown과 일치하지만,
  **실제 배틀 동작(데미지 계산, 처리 순서)을 시뮬레이터와 대조하는 검증은 아직 없습니다.**
- `special` 종류 규칙(트레이스, 일루전 등)은 데이터가 아니라 엔진 코드가 구현해야 하는 항목의 이름표입니다.
- 챔피언스 Reg M-C 한 가지만 다룹니다(더블/다른 레귤레이션은 미반영).
- PokeAPI·Showdown의 값에 오류가 있을 수 있고, 일부 한글명(예: 신규 특성)은 공식 표기가 확인되지 않았습니다.

## 데이터 출처
[PokeAPI](https://pokeapi.co) · [Pokémon Showdown](https://github.com/smogon/pokemon-showdown) · [Serebii](https://www.serebii.net) ·
[pokemondb](https://pokemondb.net) · [포켓몬 위키](https://pokemon.fandom.com/ko) · OP.GG 포켓몬 챔피언스.
각 사이트의 이용 약관을 따르며(robots.txt 요청 간격 준수), 원본 데이터는 재배포하지 않습니다.

## 라이선스
미정 — 올리기 전에 정합니다. (코드와 직접 작성한 규칙 데이터에 적용할 라이선스를 선택해야 하며, 제3자 데이터에는 각 출처의 조건이 적용됩니다.)
