"""기술 규칙 3단계: 추가 동작(회복·교체·아이템·필드·스탯 조작 등) + 방어 계열 (Showdown 소스 수작업).
move_rules_data.py 끝에서 RULES에 합쳐진다.

rule_type 추가
  heal_move        : 회복 기술. params: formula/table
  stat_manipulation: 능력 단계/수치를 조작하는 기술
  field_manipulation: 필드·진영 상태를 건드리는 기술
  item_manipulation: 도구를 뺏거나 소모시키는 기술
  type_change      : 타입을 바꾸는 기술
  ability_change   : 특성을 바꾸는 기술
  switch_move      : 교체와 관련된 기술
  trap_move        : 교체 못 하게 하는 기술
  protect_move     : 방어 계열(Protect 등)
  copy_move        : 다른 기술/상태를 복사하는 기술
  doubles_only     : 더블 전용으로 싱글에서는 실패하는 기술
params.phase_no 가 있으면 규칙 종류별 기본 단계 대신 그 번호를 쓴다 (battle_phase 참고)"""


def M(move, rule_type, note=None, **params):
    return dict(move=move, rule_type=rule_type, note=note, params=params)


def D(move, note, **p):
    return M(move, "doubles_only", note, singles="fails", phase_no=3, **p)


WEATHER_HEAL = {"default": 0.5, "sun": 0.667, "rain": 0.25, "sand": 0.25, "snow": 0.25}
CONTACT_PUNISH_PHASE = 4

RULES3 = [
    # ── 회복 ──
    M("Moonlight", "heal_move", "최대HP 회복: 기본 1/2, 쾌청 2/3, 비/모래바람/눈 1/4", base="max_hp", table=WEATHER_HEAL, phase_no=10),
    M("Morning Sun", "heal_move", "최대HP 회복: 기본 1/2, 쾌청 2/3, 비/모래바람/눈 1/4", base="max_hp", table=WEATHER_HEAL, phase_no=10),
    M("Synthesis", "heal_move", "최대HP 회복: 기본 1/2, 쾌청 2/3, 비/모래바람/눈 1/4", base="max_hp", table=WEATHER_HEAL, phase_no=10),
    M("Heal Pulse", "heal_move", "대상의 최대HP 1/2 회복 (메가런처 특성이면 3/4)", base="target_max_hp", frac=0.5,
      mega_launcher_frac=0.75, phase_no=10),
    M("Strength Sap", "heal_move", "대상의 현재 공격 스탯(단계 반영)만큼 회복한 뒤 대상의 공격 -1. 대상 공격이 -6이면 실패",
      base="target_attack_stat", then_target_stage={"atk": -1}, fails_if="target_atk_stage<=-6", phase_no=10),
    M("Pain Split", "heal_move", "사용자와 대상의 현재 HP를 평균으로 맞춤 (평균 = floor((합)/2), 최소 1)",
      formula="average_current_hp", phase_no=10),
    M("Heal Bell", "heal_move", "파티 전체의 상태이상을 치료 (소리무효/Good as Gold 아군은 제외)", effect="cure_party_status",
      excluded_allies=["Soundproof", "Good as Gold"], phase_no=10),
    M("Teatime", "item_manipulation", "필드의 모든 포켓몬이 지닌 열매를 먹음(방어 상태 등으로 막힌 포켓몬은 제외)", effect="all_eat_berry", phase_no=10),
    M("Sparkling Aria", "extra_effect", "맞은 포켓몬의 화상을 치료(다중 대상일 때만, Sheer Force 제외)", effect="cure_burn_of_targets", phase_no=14),

    # ── 능력 단계 / 스탯 조작 ──
    M("Acupressure", "stat_manipulation", "+6이 아닌 능력 하나를 무작위로 골라 +2. 모두 +6이면 실패", effect="random_stat_boost", amount=2,
      fails_if="all_stats_at_max", phase_no=10),
    M("Belly Drum", "stat_manipulation", "최대HP 1/2를 소모하고 공격을 최대(+6)로. HP가 절반 이하이거나 공격이 +6이면 실패",
      effect="set_stat_max", stat="atk", cost_frac=0.5, fails_if="hp<=0.5|atk_stage>=6", phase_no=10),
    M("Clear Smog", "stat_manipulation", "맞은 상대의 모든 능력 변화를 초기화", effect="reset_target_stages", phase_no=10),
    M("Haze", "stat_manipulation", "필드의 모든 포켓몬의 능력 변화를 초기화", effect="reset_all_stages", phase_no=10),
    M("Psych Up", "stat_manipulation", "상대의 능력 변화(와 급소율 상승 상태)를 복사", effect="copy_target_stages",
      also_copies=["Focus Energy", "Dragon Cheer", "Laser Focus"], phase_no=10),
    M("Topsy-Turvy", "stat_manipulation", "상대의 모든 능력 변화의 부호를 반대로. 변화가 없으면 실패", effect="invert_target_stages",
      fails_if="no_stages", phase_no=10),
    M("Guard Swap", "stat_manipulation", "사용자와 대상의 방어/특방 단계를 서로 교환", effect="swap_stages", stats=["def", "spd"], phase_no=10),
    M("Power Swap", "stat_manipulation", "사용자와 대상의 공격/특공 단계를 서로 교환", effect="swap_stages", stats=["atk", "spa"], phase_no=10),
    M("Guard Split", "stat_manipulation", "사용자와 대상의 방어/특방 실수치를 평균으로 맞춤", effect="average_stats", stats=["def", "spd"], phase_no=10),
    M("Power Split", "stat_manipulation", "사용자와 대상의 공격/특공 실수치를 평균으로 맞춤", effect="average_stats", stats=["atk", "spa"], phase_no=10),
    M("Speed Swap", "stat_manipulation", "사용자와 대상의 스피드 실수치를 서로 교환", effect="swap_stat_values", stats=["spe"], phase_no=10),
    M("Fell Stinger", "stat_manipulation", "이 기술로 상대를 쓰러뜨리면 공격 +3", effect="boost_on_ko", boosts={"atk": 3}, phase_no=14),
    M("Tidy Up", "field_manipulation", "모든 분신과 압정류를 제거하고 자신의 공격과 스피드 +1", effect="clear_hazards_and_substitutes",
      self_boosts={"atk": 1, "spe": 1}, hazards=["spikes", "toxic_spikes", "stealth_rock", "sticky_web"], phase_no=10),

    # ── 필드·진영 조작 ──
    M("Defog", "field_manipulation", "상대 회피 -1. 상대 진영의 리플렉터/빛의장막/오로라베일/신비의부적을 제거하고 양쪽 진영의 압정류를 제거, 필드(테라인)도 제거",
      effect="defog", target_evasion=-1, remove_target_side=["reflect", "light_screen", "aurora_veil", "safeguard"],
      remove_both_sides=["spikes", "toxic_spikes", "stealth_rock", "sticky_web"], clear_terrain=True, phase_no=10),
    M("Court Change", "field_manipulation", "양쪽 진영의 상태를 서로 교환(압정, 벽, 순풍, 신비의부적 등)", effect="swap_side_conditions",
      conditions=["mist", "light_screen", "reflect", "spikes", "safeguard", "tailwind", "toxic_spikes", "stealth_rock", "sticky_web",
                  "aurora_veil", "lucky_chant"], phase_no=10),
    M("Rapid Spin", "field_manipulation", "맞힌 뒤 자신의 속박/씨뿌리기/압정류를 제거(Sheer Force 시 제외). 스피드 +1 부가효과는 기술 효과 표",
      effect="clear_user_side", remove=["leech_seed", "partially_trapped", "spikes", "toxic_spikes", "stealth_rock", "sticky_web"], phase_no=12),
    M("Mortal Spin", "field_manipulation", "맞힌 뒤 자신의 속박/씨뿌리기/압정류를 제거하고 독 부가효과(Sheer Force 시 제외)",
      effect="clear_user_side", remove=["leech_seed", "partially_trapped", "spikes", "toxic_spikes", "stealth_rock", "sticky_web"], phase_no=12),
    M("Ice Spinner", "field_manipulation", "맞힌 뒤 필드(테라인)를 지움", effect="clear_terrain", phase_no=12),
    M("Ceaseless Edge", "field_manipulation", "맞힌 뒤 상대 진영에 압정 1겹(Sheer Force 시 제외)", effect="set_hazard", hazard="spikes", layers=1, phase_no=12),
    M("Stone Axe", "field_manipulation", "맞힌 뒤 상대 진영에 스텔스록(Sheer Force 시 제외)", effect="set_hazard", hazard="stealth_rock", phase_no=12),

    # ── 도구 ──
    M("Bug Bite", "item_manipulation", "상대의 열매를 빼앗아 사용자가 먹음 (열매일 때만)", effect="eat_target_berry", phase_no=10),
    M("Pluck", "item_manipulation", "상대의 열매를 빼앗아 사용자가 먹음 (열매일 때만)", effect="eat_target_berry", phase_no=10),
    M("Corrosive Gas", "item_manipulation", "상대의 도구를 제거(소멸)", effect="remove_target_item", phase_no=10),
    M("Covet", "item_manipulation", "사용자가 도구가 없으면 상대의 도구를 빼앗음", effect="steal_item", requires="user_no_item", phase_no=12),
    M("Thief", "item_manipulation", "사용자가 도구가 없으면 상대의 도구를 빼앗음", effect="steal_item", requires="user_no_item", phase_no=12),
    M("Recycle", "item_manipulation", "마지막으로 소모한 자신의 도구를 되살림. 이미 도구를 지니면 실패", effect="restore_used_item",
      fails_if="user_has_item|no_used_item", phase_no=10),
    M("Spite", "stat_manipulation", "상대가 마지막으로 쓴 기술의 PP를 4 줄임", effect="reduce_pp", amount=4, phase_no=10),

    # ── 타입 / 특성 변화 ──
    M("Forest's Curse", "type_change", "대상에게 풀 타입을 추가. 이미 풀 타입이면 실패", effect="add_type", type="Grass", phase_no=10),
    M("Trick-or-Treat", "type_change", "대상에게 고스트 타입을 추가. 이미 고스트 타입이면 실패", effect="add_type", type="Ghost", phase_no=10),
    M("Soak", "type_change", "대상의 타입을 물 단일 타입으로 바꿈. 이미 물 단일이면 실패", effect="set_type", type="Water", phase_no=10),
    M("Magic Powder", "type_change", "대상의 타입을 에스퍼 단일 타입으로 바꿈 (분말 기술)", effect="set_type", type="Psychic", phase_no=10),
    M("Reflect Type", "type_change", "사용자의 타입을 대상과 같게 바꿈", effect="copy_target_types", phase_no=10),
    M("Skill Swap", "ability_change", "사용자와 대상의 특성을 서로 교환 (교환 불가 특성은 실패)", effect="swap_abilities", phase_no=10),
    M("Transform", "copy_move", "대상으로 변신(타입, 종족값 제외한 스탯, 특성, 기술, 능력 단계를 복사)", effect="transform", phase_no=10),
    M("Copycat", "copy_move", "마지막으로 사용된 기술을 그대로 사용 (복사 불가 기술이면 실패)", effect="use_last_move", phase_no=10),

    # ── 교체 / 속박 ──
    M("Baton Pass", "switch_move", "교체하면서 능력 단계와 일부 상태(씨뿌리기 등)를 다음 포켓몬에게 넘김. 복사 불가 상태는 제외",
      effect="switch_copy_volatiles", passes=["stat_stages", "substitute", "leech_seed", "focus_energy", "aqua_ring", "ingrain"], phase_no=14),
    M("Parting Shot", "switch_move", "상대의 공격/특공 -1 후 자신이 교체. 능력이 내려가지 않으면(미러아머 제외) 교체 안 함",
      effect="debuff_then_switch", target_boosts={"atk": -1, "spa": -1}, phase_no=14),
    M("Mean Look", "trap_move", "대상을 교체 불가로 만듦(사용자가 필드에 있는 동안). 고스트 타입은 면역", effect="trap_target", immune_types=["Ghost"], phase_no=10),
    M("Block", "trap_move", "대상을 교체 불가로 만듦. 고스트 타입은 면역", effect="trap_target", immune_types=["Ghost"], phase_no=10),
    M("Jaw Lock", "trap_move", "사용자와 대상이 서로 교체 불가가 됨(둘 중 하나가 쓰러질 때까지)", effect="trap_both", phase_no=10),
    M("Perish Song", "extra_effect", "필드의 모든 포켓몬에게 4턴 카운트를 걸어, 카운트가 0이 되면 기절. 교체하면 해제",
      effect="set_perish_count", count=4, phase_no=10),

    # ── 더블 전용 (싱글에서는 실패) ──
    D("After You", "대상을 이번 턴 다음에 바로 행동하게 함", effect="prioritize_target"),
    D("Quash", "대상을 이번 턴 가장 마지막에 행동하게 함", effect="delay_target"),
    D("Instruct", "대상이 방금 쓴 기술을 다시 쓰게 함", effect="repeat_target_move"),
    D("Ally Switch", "아군과 위치를 바꿈 (연속 사용 성공률 1/3씩 감소)", effect="swap_position", priority=2),
    D("Magnetic Flux", "플러스/마이너스 특성의 아군 방어·특방 +1", effect="boost_plus_minus", boosts={"def": 1, "spd": 1}),

    # ── 방어 계열 ──
    M("Protect", "protect_move", "이번 턴 모든 기술(protect 플래그 있는)을 막음. 연속 사용 시 성공률 1/3씩 감소", priority=4, blocks_status_moves=True,
      contact_punish=None, uses_stall_counter=True, phase_no=4),
    M("Detect", "protect_move", "Protect와 동일", priority=4, blocks_status_moves=True, contact_punish=None, uses_stall_counter=True, phase_no=4),
    M("Baneful Bunker", "protect_move", "막은 뒤 접촉한 상대를 독 상태로", priority=4, blocks_status_moves=True,
      contact_punish={"status": "psn"}, uses_stall_counter=True, phase_no=4),
    M("Spiky Shield", "protect_move", "막은 뒤 접촉한 상대에게 최대HP 1/8 피해", priority=4, blocks_status_moves=True,
      contact_punish={"damage_frac": 0.125}, uses_stall_counter=True, phase_no=4),
    M("King's Shield", "protect_move", "공격 기술만 막음(변화 기술은 통과). 접촉한 상대의 공격 -1", priority=4, blocks_status_moves=False,
      contact_punish={"stat_stage": {"atk": -1}}, uses_stall_counter=True, phase_no=4),
    M("Silk Trap", "protect_move", "공격 기술만 막음. 접촉한 상대의 스피드 -1", priority=4, blocks_status_moves=False,
      contact_punish={"stat_stage": {"spe": -1}}, uses_stall_counter=True, phase_no=4),
    M("Burning Bulwark", "protect_move", "공격 기술만 막음. 접촉한 상대를 화상 상태로", priority=4, blocks_status_moves=False,
      contact_punish={"status": "brn"}, uses_stall_counter=True, phase_no=4),
    M("Obstruct", "protect_move", "공격 기술만 막음. 접촉한 상대의 방어 -2", priority=4, blocks_status_moves=False,
      contact_punish={"stat_stage": {"def": -2}}, uses_stall_counter=True, phase_no=4),
    M("Endure", "protect_move", "이번 턴 기술 데미지로 쓰러지지 않고 HP 1로 버팀. Protect류와 연속 사용 카운터를 공유", priority=4,
      effect="survive_at_1hp", uses_stall_counter=True, phase_no=9),
    M("Substitute", "extra_effect", "분신 생성 (HP = 최대HP 1/4). 분신 상세는 battle_state의 substitute 참고", effect="create_substitute",
      state="substitute", phase_no=10),
    M("Leech Seed", "extra_effect", "대상에게 씨를 심음. 상세는 battle_state의 leech_seed 참고", effect="apply_state", state="leech_seed", phase_no=10),
]
