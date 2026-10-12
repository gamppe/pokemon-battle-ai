"""기술·특성·아이템·필드 사이의 전역 상호작용 규칙 -> battle_rule.
출처: Showdown sim/battle-actions.ts(hitStep 순서), data/conditions.ts, data/moves.ts, data/abilities.ts (수작업 정리).
목록형 값(방어를 무시하는 기술, 몰드브레이커가 무시하는 특성)은 DB/소스에서 자동으로 채운다."""
import os, json, pymysql

HERE = os.path.dirname(os.path.abspath(__file__))
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS battle_rule (
  rule_id  SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  rule_key VARCHAR(40) NOT NULL UNIQUE,
  name_ko  VARCHAR(60) NOT NULL,
  phase_no TINYINT UNSIGNED NULL,
  params   JSON NOT NULL,
  note     VARCHAR(400) NULL)""")
cur.execute("delete from battle_rule")
cur.execute("ALTER TABLE battle_rule AUTO_INCREMENT = 1")

# 방어(Protect)를 무시하는 기술: 대상이 있는 기술 중 protect 플래그가 없는 것 (챔피언스)
cur.execute("""select m.name_en from game_move g join move m using(move_id)
  where g.game_id=4 and m.target not in ('self','allySide','foeSide','all','allyTeam','adjacentAlly','allies','adjacentAllyOrSelf')
  and m.move_id not in (select move_id from move_flag where flag='protect' and game_id=0) order by 1""")
no_protect_flag = [r[0] for r in cur.fetchall()]
cur.execute("""select m.name_en from game_move g join move m using(move_id)
  where g.game_id=4 and json_extract(m.extra,'$.breaksProtect') is not null""")
breaks_protect = [r[0] for r in cur.fetchall()]
breakable = json.load(open(os.path.join(HERE, "breakable_abilities.json"), encoding="utf-8"))

RULES = [
    ("evasion_max", "회피율 최대 상태(공중·땅속·물속·그림자)", 4, dict(
        states=["flying", "underground", "underwater", "shadow"],
        order="행동 순서상 가장 먼저 확인(방어·타입무효·명중보다 앞)",
        bypassed_by_abilities=["No Guard"], bypassed_by_status=["Lock-On", "Mind Reader"],
        also_bypassed_by="충전 기술별 예외 기술(move_rule의 hit_by_moves)",
        not_the_same_as="protect"),
     "노가드·록온은 이 상태를 뚫고 필중이 된다. 방어(Protect)와는 완전히 별개의 처리다."),
    ("protect", "방어(Protect, Detect 등)", 4, dict(
        order="회피율 최대 확인 다음(2단계 TryHit), 명중 판정보다 앞",
        blocks_if="기술에 protect 플래그가 있음",
        bypass_moves_by_missing_flag=no_protect_flag, bypass_moves_breaks_protect=breaks_protect,
        bypass_abilities=[{"ability": "Unseen Fist", "when": "contact"},
                          {"ability": "Piercing Drill", "when": "contact", "damage_mult": 0.25}],
        not_bypassed_by=["No Guard", "Lock-On/Mind Reader", "필중 기술", "Mold Breaker"],
        consecutive_use="연속 사용 시 성공률이 1/3씩 감소(stall 카운터, 3)",
        kings_shield_style=["King's Shield", "Silk Trap", "Burning Bulwark", "Obstruct"],
        kings_shield_blocks="공격 기술만 막고 변화 기술은 통과(move_interaction.kings_shield_blocks)",
        see="move_interaction 표(기술별 protect 열)"),
     "필중이나 회피율 최대 무시와 방어 무시는 서로 다른 개념. 노가드·록온은 방어를 못 뚫는다."),
    ("substitute", "분신(Substitute)과 기술의 관계", 22, dict(
        order="방어(Protect) 확인 -> 타입/분말 무효 -> 명중 판정 -> 분신 확인(여기) -> 위력·데미지 계산",
        applies_to="상대(또는 상대 진영 안의 대상)를 노리는 기술. 자신·아군·필드·진영 대상 기술은 해당 없음",
        passes_if=["기술에 bypasssub 플래그(소리 기술, 앵콜/도발/트집/저주/날씨 변화 기술 등)", "사용자가 Infiltrator 특성"],
        attack_move="데미지를 분신이 대신 받음. 부가효과·상태이상·onHit 효과(도구 뺏기 등)는 본체에 적용되지 않음",
        status_move="분신에 막혀 실패",
        still_applies=["사용자 쪽 반동·흡수", "기술이 분신을 맞혀도 이어지는 후속 효과(move_interaction.sub_after_effects: 압정 설치, 필드 제거 등)"],
        sub_hp="생성 시 최대HP 1/4. 분신 HP가 0이 되면 사라짐", see="move_interaction 표(기술별 계산됨)"),
     "기술별 결과는 move_interaction(protect/substitute 열)을 보면 된다. 다단히트에서 분신이 깨진 뒤의 처리는 시뮬레이터로 확인 필요"),
    ("grounded", "땅에 붙은 상태 판정", 0, dict(
        not_grounded_if=["type:Flying", "ability:Levitate", "ability:Eelevate", "item:Air Balloon", "volatile:Magnet Rise", "volatile:Telekinesis"],
        forced_grounded_if=["item:Iron Ball", "field:Gravity", "volatile:Ingrain", "volatile:Smack Down", "hit_by:Thousand Arrows"],
        priority="forced_grounded가 not_grounded보다 우선",
        roost="날개쉬기를 쓴 턴에는 비행 타입으로 보지 않음(그 턴 접지)",
        affects=["필드(테라인) 효과", "압정/독압정/끈적네트", "땅 기술 무효 여부"]),
     "회피율 최대 상태 중(공중날기 등)에는 필드 효과를 받지 않는다(is_evasion_max)."),
    ("priority_block", "우선도 기술 차단", 4, dict(
        by_abilities=["Queenly Majesty", "Armor Tail"], by_field="Psychic Terrain (땅에 붙은 대상)",
        blocks="우선도 1 이상(0.1 초과)인 상대 기술이 자신·아군을 노릴 때",
        exceptions=["자신 대상 기술", "아군이 쓴 기술(Psychic Terrain)", "회피율 최대 상태 대상(Psychic Terrain)", "Mold Breaker가 특성을 무시하는 경우"]),
     "Prankster로 올린 우선도도 차단 대상이 된다."),
    ("prankster_dark", "Prankster 변화 기술 vs 악 타입", 4, dict(
        rule="Prankster 때문에 우선도가 오른 변화 기술은 악 타입 대상에게 무효(대상이 자신인 경우 제외)"),
     None),
    ("mold_breaker", "몰드브레이커 계열", 4, dict(
        users=["Mold Breaker"], ignores_abilities=breakable,
        note="상대 필드의 모든 포켓몬의 해당 특성을 무시. 방어/회피율 최대/명중에는 영향 없음"),
     "챔피언스에서 쓸 수 있는 몰드브레이커 계열은 Mold Breaker뿐이다."),
    ("powder_immunity", "분말 기술 무효", 4, dict(
        immune=["type:Grass (type_immunity의 powder)", "ability:Overcoat"], move_flag="powder",
        applies_to="powder 플래그 기술(수면가루·독가루·저리가루·목화포자·마법가루·분노가루 등)",
        note_doubles="분노가루의 리다이렉트도 풀 타입/방진 특성에는 통하지 않음"),
     "9세대(6세대 이후)부터 풀 타입은 분말 기술 면역. type_immunity와 move_rule(target_immunity)로 기술별 연결됨"),
    ("status_move_type_rule", "변화 기술과 타입 상성", 4, dict(
        default="변화 기술은 타입 상성표(0배 무효)를 무시한다(ignoreImmunity=true)",
        exceptions={"Thunder Wave": "타입 상성표 적용(땅 타입에 무효)"},
        status_conditions_by_type="type_immunity 표의 par/brn/psn/tox/frz 키(전기·불꽃·독·강철·얼음 타입이 해당 상태이상에 면역)",
        custom_checks={"Leech Seed": "풀 타입 무효", "Forest's Curse": "풀 타입이면 실패", "Trick-or-Treat": "고스트 타입이면 실패",
                       "Octolock": "고스트 타입이면 실패"}),
     "예: 씨뿌리기·수면가루는 풀 타입에 안 통하고, 전기자석파는 땅 타입에 안 통하지만 독가루는 땅 타입에 통한다"),
    ("struggle", "발버둥(Struggle) 자동 사용", 3, dict(
        trigger="사용 가능한 기술이 없음(PP 0 또는 전부 사용 불가)", move="Struggle", typeless=True, accuracy="always",
        recoil=dict(basis="user_max_hp", frac=0.25, round="nearest", min=1)),
     "행동 선택 단계에서 기술 선택지가 사라지고 Struggle만 남는다"),
    ("sound_moves", "소리 기술 규칙", 4, dict(
        immune_abilities=["Soundproof"], bypasses_substitute=True, move_flag="sound",
        modified_by=["Liquid Voice(물 타입화)", "Punk Rock(위력 x1.3, 받는 소리 데미지 절반)", "Throat Chop(사용 봉인)"]), None),
    ("reflectable_status", "마법반사 대상", 4, dict(
        ability="Magic Bounce", move_flag="reflectable",
        note="reflectable 플래그를 가진 변화 기술을 사용자에게 되돌림. 같은 기술은 한 번만 반사"), None),
    ("status_move_immunity", "변화 기술 무효", 4, dict(
        ability="Good as Gold", exceptions="자신을 대상으로 하는 변화 기술"), None),
    ("weather_damage_immunity", "날씨 피해 면역", 16, dict(
        sand=dict(types=["Rock", "Ground", "Steel"], abilities=["Sand Veil", "Sand Rush", "Sand Force", "Overcoat", "Magic Guard"],
                  states=["underground(Dig)", "underwater(Dive)"]),
        snow="피해 없음"),
     None),
    ("trapping", "교체 불가 / 탈출", 20, dict(
        trap_sources=["Shadow Tag", "Mean Look", "Block", "Octolock", "Ingrain", "속박(조이기 등)", "Fairy Lock"],
        immune_to_trapping=["type:Ghost"], escape=["item:Shed Shell", "교체 기술(U-turn, Parting Shot, Baton Pass 등은 가능)"],
        shadow_tag_exceptions=["Ghost 타입", "Shed Shell", "같은 Shadow Tag"]), None),
    ("ability_suppression", "특성 억제", 4, dict(
        sources=["Gastro Acid"], blocked_by=["Ability Shield(챔피언스에서는 사용 불가 아이템)"],
        protected_abilities="cantsuppress 플래그 특성은 억제 불가"), None),
    ("secondary_effect_block", "부가효과 차단", 10, dict(
        blockers=["Shield Dust"], removed_by_user=["Sheer Force"],
        affects="기술의 확률 부가효과(확률 100%도 포함). 도구(King's Rock 등)가 붙이는 효과도 포함"), None),
    ("item_suppression", "아이템 정지", 0, dict(
        sources=["Magic Room", "Klutz", "Embargo"], not_affected=["Mega Stone(메가진화는 별도)"]), None),
]

n = 0
for key, name, phase, params, note in RULES:
    cur.execute("insert into battle_rule (rule_key,name_ko,phase_no,params,note) values (%s,%s,%s,%s,%s)",
                (key, name, phase, json.dumps(params, ensure_ascii=False), note))
    n += 1
db.commit()
print("battle_rule", n, "| 방어 무시(플래그 없음)", len(no_protect_flag), "| breaksProtect", breaks_protect,
      "| 몰드브레이커 대상 특성", len(breakable))
