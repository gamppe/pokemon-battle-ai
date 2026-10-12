"""배틀 처리 순서(phase) 테이블 + 특성/아이템/기술 규칙의 단계 연결.
출처: Showdown sim/battle-actions.ts (useMoveInner -> trySpreadMoveHit -> hitStepMoveHitLoop -> spreadMoveHit),
      sim/battle.ts. 한 번의 '기술 사용' 안에서의 순서는 아래 번호가 작을수록 먼저."""
import os, pymysql

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()

# (번호, 코드, 이름, 설명, Showdown 이벤트)
PHASES = [
    (0, "always", "상시", "단계와 무관하게 항상 적용되는 성질(무게 변경, 날씨 무효 등)", ""),
    (1, "turn_order", "행동 순서 결정", "우선도와 스피드로 이번 턴의 행동 순서를 정함", "ModifyPriority, Speed"),
    (2, "before_move", "행동 직전 판정", "잠듦/마비/풀죽음/혼란 등으로 행동이 막히는지 확인. 풀죽음 시 Steadfast 발동", "BeforeMove"),
    (3, "move_prepare", "기술 준비", "기술 타입 변환(스킨류, 웨더볼), 사용 조건 확인(속공 첫 턴 등), PP 소모(압박)", "ModifyType, ModifyMove, TryMove, PrepareHit"),
    (4, "target_check", "대상 확인·무효 판정", "방어, 마법반사, 흡수 특성(축전/저수), 타입 무효, 분말/Prankster 무효", "Invulnerability, TryHit, TypeImmunity, TryImmunity"),
    (5, "accuracy", "명중 판정", "명중/회피 보정(복안, 모래숨기 등)과 명중 굴림", "ModifyAccuracy, Accuracy"),
    (6, "base_power_calc", "위력·급소 계산", "기술 위력 계산(기술 고유 규칙 -> 특성/도구 보정), 급소율", "BasePower, ModifyCritRatio"),
    (7, "stat_calc", "공격/방어 스탯 보정", "공격·방어 스탯에 붙는 보정(옹골찬힘, 털가죽 등)", "ModifyAtk/SpA/Def/SpD"),
    (8, "damage_calc", "데미지 계산", "자속 보정, 타입 상성, 최종 데미지 보정(생명의구슬, 멀티스케일, 반감 열매 소모)", "ModifySTAB, ModifyDamage, SourceModifyDamage"),
    (9, "damage_apply", "데미지 적용", "HP를 깎음. 기합의띠/옹골참/미라클스킨 발동, 한 번에 쓰러지지 않게 막는 처리", "Damage"),
    (10, "move_effects", "기술 효과·부가효과", "기술 본래 효과(능력 변화, 상태이상), 자신 능력 변화, 확률 부가효과, 강제 교체", "Hit, Secondaries"),
    (11, "damaging_hit", "피격 반응", "맞은 쪽 반응: 접촉 특성/아이템(정전기, 울퉁불퉁한바위 헬멧), 약한갑옷, 스태미나, 에어 벌룬 터짐", "DamagingHit"),
    (12, "after_hit", "기술 후속 동작", "기술 자체의 사후 동작(탁쳐서떨구기 도구 제거 등)", "AfterHit"),
    (13, "update", "상태 갱신", "HP 조건 열매(자뭉열매, 오랭열매) 섭취와 먹은 뒤 효과", "Update"),
    (14, "after_move", "기술 종료 후 처리", "생명의구슬 반동, 조개껍질 방울 회복, 탈출버튼, 비상탈출, 버서크, 소매치기, 유턴 교체", "AfterMoveSecondary(Self)"),
    (15, "faint_check", "기절 처리", "기절 시 효과(유폭, Innards Out), 쓰러뜨렸을 때 효과(자기과신 등)", "Faint, KO"),
    (16, "turn_end", "턴 종료 처리", "날씨/필드 데미지와 회복, 먹다 남은 음식, 속도 상승 등 매 턴 종료 효과", "Residual"),
    (22, "substitute_check", "분신 확인", "명중 판정 뒤, 위력 계산 전에 분신이 대신 맞는지 확인(분신 통과 기술·특성은 건너뜀)", "TryPrimaryHit"),
    (20, "switch_in", "등장", "배틀에 나올 때(위협, 날씨/필드 특성, 도구 발동 등)", "SwitchIn"),
    (21, "switch_out", "교체", "배틀에서 빠질 때(자연회복, 재생력)", "SwitchOut"),
]
# hook 기본 단계
HOOK_PHASE = {
    "passive": 0, "modify_priority": 1, "modify_spe": 1, "before_move": 2, "on_flinch": 2,
    "modify_move_type": 3, "immunity": 4, "modify_acc": 5, "modify_evasion": 5,
    "modify_bp": 6, "modify_crit": 6, "modify_atk": 7, "modify_atk_foe": 7, "modify_def": 7, "modify_bp_foe": 6,
    "modify_stab": 8, "modify_dmg_dealt": 8, "modify_dmg_taken": 8,
    "modify_drain": 10, "on_hit_dealt": 10, "on_stat_drop": 10, "on_status": 10, "on_foe_stat_rise": 10,
    "on_hit_taken": 11, "on_crit_taken": 11,
    "on_item_use": 13, "on_damage_taken_hp": 14,
    "after_hit": 12, "on_ko": 15, "on_faint": 15, "turn_end": 16, "switch_in": 20, "switch_out": 21,
}
# 개별 예외: (테이블, 이름(영문), hook, 새 단계)
OVERRIDE = [
    ("item", "Life Orb", "on_hit_dealt", 14), ("item", "Shell Bell", "on_hit_dealt", 14),
    ("item", "Sitrus Berry", "on_damage_taken_hp", 13), ("item", "Oran Berry", "on_damage_taken_hp", 13),
    ("item", "Eject Button", "on_hit_taken", 14), ("item", "Red Card", "on_hit_taken", 14),
    ("item", "Focus Sash", "modify_dmg_taken", 9), ("item", "Focus Band", "modify_dmg_taken", 9),
    ("ability", "Sturdy", "modify_dmg_taken", 9), ("ability", "Disguise", "immunity", 9),
    ("ability", "Magician", "on_hit_dealt", 14), ("ability", "Emergency Exit", "on_damage_taken_hp", 14),
    ("ability", "Berserk", "on_damage_taken_hp", 14), ("ability", "Pickpocket", "on_hit_taken", 14),
    ("ability", "Pressure", "passive", 3), ("ability", "Parental Bond", "modify_bp", 10),
    ("item", "King's Rock", "on_hit_dealt", 10),
]
# 기술 규칙: rule_type 기본 단계
MOVE_RULE_PHASE = {"power_mult_if": 6, "power_formula": 6, "damage_formula": 8, "on_hit_effect": 12, "modify_target": 3,
                   "target_immunity": 4, "forced_move": 3, "sets_state": 10, "heal_move": 10, "stat_manipulation": 10, "field_manipulation": 10, "item_manipulation": 10, "type_change": 10,
                   "ability_change": 10, "switch_move": 14, "trap_move": 10, "protect_move": 4, "copy_move": 10, "doubles_only": 3,
                   "use_condition": 3, "fail_penalty": 14, "self_cost": 10, "charge_move": 3, "delayed_move": 3,
                   "type_by_condition": 3, "accuracy_by_condition": 5, "priority_by_condition": 1,
                   "effectiveness_mod": 8, "category_choice": 3, "boost_by_condition": 10, "extra_effect": 10}

cur.execute("""CREATE TABLE IF NOT EXISTS battle_phase (
  phase_no TINYINT UNSIGNED PRIMARY KEY, code VARCHAR(20) NOT NULL UNIQUE, name_ko VARCHAR(30) NOT NULL,
  description VARCHAR(300) NOT NULL, showdown_events VARCHAR(100) NOT NULL DEFAULT '',
  sort_order DECIMAL(5,2) NULL COMMENT '처리 순서(작을수록 먼저). phase_no는 식별용 번호')""")
try:
    cur.execute("ALTER TABLE battle_phase ADD COLUMN sort_order DECIMAL(5,2) NULL")
except pymysql.err.OperationalError as e:
    if e.args[0] != 1060:
        raise
cur.execute("""CREATE TABLE IF NOT EXISTS hook_phase (
  hook VARCHAR(24) PRIMARY KEY, phase_no TINYINT UNSIGNED NOT NULL, FOREIGN KEY (phase_no) REFERENCES battle_phase(phase_no))""")
for tbl in ("ability_effect", "item_effect", "move_rule", "battle_state_effect"):
    try:
        cur.execute(f"ALTER TABLE {tbl} ADD COLUMN phase_no TINYINT UNSIGNED NULL")
    except pymysql.err.OperationalError as e:
        if e.args[0] != 1060:
            raise
cur.execute("delete from hook_phase"); cur.execute("delete from battle_phase")
cur.executemany("insert into battle_phase (phase_no,code,name_ko,description,showdown_events,sort_order) values (%s,%s,%s,%s,%s,%s)",
                [(a, b, c, d, e, 5.5 if a == 22 else a) for a, b, c, d, e in PHASES])
cur.executemany("insert into hook_phase values (%s,%s)", sorted(HOOK_PHASE.items()))
for tbl in ("ability_effect", "item_effect", "battle_state_effect"):
    cur.execute(f"update {tbl} e join hook_phase h on h.hook=e.hook set e.phase_no=h.phase_no")
miss = {}
for kind, name, hook, ph in OVERRIDE:
    tbl, key = (("ability_effect", "ability_id"), ("item_effect", "item_id"))[kind == "item"]
    src = "ability" if kind == "ability" else "item"
    cur.execute(f"update {tbl} e join {src} s on s.{src}_id=e.{key} set e.phase_no=%s where s.name_en=%s and e.hook=%s", (ph, name, hook))
    if cur.rowcount == 0:
        miss[name] = hook
cur.execute("""update battle_state_effect e join battle_state s using(state_id) set e.phase_no=22
               where s.code='substitute' and e.hook='immunity'""")
for rt, ph in MOVE_RULE_PHASE.items():
    cur.execute("update move_rule set phase_no=%s where rule_type=%s", (ph, rt))
cur.execute("update move_rule set phase_no=json_extract(params,'$.phase_no') where json_extract(params,'$.phase_no') is not null")
cur.execute("""update move_rule r join move m using(move_id) set r.phase_no=6
               where m.name_en='Knock Off' and r.rule_type='power_mult_if'""")
db.commit()
for tbl in ("ability_effect", "item_effect", "move_rule", "battle_state_effect"):
    cur.execute(f"select count(*), sum(phase_no is null) from {tbl}")
    print(tbl, cur.fetchone())
print("override 미적용(이미 같은 값이면 정상):", miss)
