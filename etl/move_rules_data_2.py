"""기술 규칙 2단계: 타입·우선도·명중 변동, 사용 조건·실패 조건 (Showdown 소스 수작업).
move_rules_data.py 끝에서 RULES에 합쳐진다.

rule_type
  use_condition  : 사용 조건. params: requires / fails_if (조건 이름)
  fail_penalty   : 실패(빗나감 등) 시 자신이 입는 피해. params: hp_frac(최대HP 비율)
  self_cost      : 사용 시 자신이 치르는 대가
  charge_move    : 2턴 기술. params: invulnerable(충전 중 상태), charge_boost, skip_if
  delayed_move   : 지연 공격. params: hits_after_turns
  type_by_condition / accuracy_by_condition / priority_by_condition / effectiveness_mod /
  category_choice / boost_by_condition / extra_effect
params.phase_no 가 있으면 규칙 종류별 기본 단계 대신 그 번호를 쓴다 (battle_phase 참고)"""


def M(move, rule_type, note=None, **params):
    return dict(move=move, rule_type=rule_type, note=note, params=params)


def U(move, note, phase_no=3, **p):
    return M(move, "use_condition", note, phase_no=phase_no, **p)


INV_BYPASS = ["ability:No Guard (자신 또는 상대가 가짐)", "status:Lock-On/Mind Reader (사용한 쪽이 같은 상대를 공격할 때)"]  # 회피율 최대 상태만 뚫음. 방어(Protect)는 못 뚫음


def CH(move, inv, note, **p):
    return M(move, "charge_move", note, evasion_max=inv, phase_no=3, **p)


RULES2 = [
    # ── 사용 조건·실패 조건 ──
    U("Fake Out", "내보낸 뒤 첫 행동일 때만 성공(이후 턴은 실패). 풀죽음 부가효과는 기술 효과 표", requires="first_turn_after_switch_in"),
    U("First Impression", "내보낸 뒤 첫 행동일 때만 성공", requires="first_turn_after_switch_in"),
    U("Sucker Punch", "상대가 공격 기술을 선택했고 아직 행동하지 않았을 때만 성공 (변화 기술 선택 시 실패)",
      requires="target_will_use_attacking_move", target_not_moved=True),
    U("Upper Hand", "상대가 우선도 있는 공격 기술을 선택했고 아직 행동하지 않았을 때만 성공",
      requires="target_will_use_priority_attacking_move", target_not_moved=True),
    U("Last Resort", "기술을 2개 이상 알고, Last Resort를 제외한 모든 기술을 한 번씩 쓴 뒤에만 성공",
      requires="all_other_moves_used_since_switch_in", min_known_moves=2),
    U("Poltergeist", "상대가 도구를 지니고 있지 않으면 실패", requires="target_has_item"),
    U("Snore", "자신이 잠든 상태일 때만 사용 가능", requires="user_asleep"),
    U("Sleep Talk", "자신이 잠든 상태일 때만 사용, 무작위 다른 기술을 사용", requires="user_asleep"),
    U("Belch", "배틀 중 열매를 먹은 적이 있을 때만 사용 가능", requires="user_ate_berry"),
    U("Stuff Cheeks", "열매를 지니고 있을 때만 사용 (열매를 먹고 방어 +2)", requires="user_holds_berry"),
    U("Swallow", "비축(Stockpile)이 쌓여 있을 때만 사용", requires="stockpile_layers>=1"),
    U("Aurora Veil", "눈 상태일 때만 사용 가능", requires="weather:snow"),
    U("Steel Roller", "필드(테라인)가 깔려 있지 않으면 실패. 명중하면 필드를 지움", requires="terrain_active"),
    U("Burn Up", "자신이 불꽃 타입일 때만 사용 가능", requires="user_has_type:Fire"),
    U("Double Shock", "자신이 전기 타입일 때만 사용 가능", requires="user_has_type:Electric"),
    U("Attract", "서로 성별이 다른 수컷/암컷일 때만 성공 (성별 없음은 실패)", requires="opposite_gender"),
    U("Leech Seed", "풀 타입에게는 효과 없음", phase_no=4, fails_if="target_has_type:Grass"),
    U("Disable", "상대가 직전에 쓴 기술이 없거나 발버둥이면 실패", requires="target_has_last_move"),
    U("Electrify", "상대가 이번 턴 이미 행동했으면 실패", fails_if="target_already_moved"),
    U("Helping Hand", "대상 아군이 이미 행동했으면 실패 (더블 전용)", fails_if="ally_already_moved"),
    U("Follow Me", "더블 전용. 싱글에서는 실패", requires="doubles_battle"),
    U("Rage Powder", "더블 전용. 싱글에서는 실패", requires="doubles_battle"),
    U("Gastro Acid", "억제할 수 없는 특성이나 Ability Shield를 지닌 상대에게는 실패", fails_if="target_ability_unsuppressable"),
    U("Healing Wish", "교체할 아군이 없으면 실패", requires="can_switch"),
    U("Magnet Rise", "중력 상태나 앵커 효과(Smack Down, 뿌리박기)에서는 실패", fails_if="gravity|smack_down|ingrain"),
    U("No Retreat", "이미 걸려 있으면 실패", fails_if="already_active"),
    U("Octolock", "상대가 교체 불가가 되지 않는 타입(고스트)이면 실패", fails_if="target_immune_to_trapping"),
    U("Revival Blessing", "쓰러진 아군이 없으면 실패", requires="fainted_ally_exists"),
    U("Stockpile", "이미 비축이 3겹이면 실패", fails_if="stockpile_layers>=3"),
    U("Yawn", "상대가 상태이상이거나 잠에 면역이면 실패", fails_if="target_has_status|target_sleep_immune"),
    U("Clangorous Soul", "HP가 33% 이하면 실패", fails_if="user_hp_frac<=0.33"),
    U("Entrainment", "상대와 같은 특성이거나 복사 불가 특성이면 실패", fails_if="same_ability|ability_uncopyable"),
    U("Rest", "이미 잠들었거나 풀HP면 실패, 불면/의기양양 특성이면 실패", fails_if="user_asleep|user_full_hp|insomnia|vital_spirit"),
    U("Role Play", "상대와 같은 특성이거나 복사 불가 특성이면 실패", fails_if="same_ability|ability_uncopyable"),
    U("Shed Tail", "HP가 절반 이하이거나 교체할 아군이 없으면 실패", fails_if="user_hp_frac<=0.5|no_switch_target"),
    U("Simple Beam", "억제 불가/태만 특성이거나 단순 특성이면 실패", fails_if="ability_unsuppressable|target_truant|target_simple"),
    U("Worry Seed", "억제 불가/태만/불면 특성이면 실패", fails_if="ability_unsuppressable|target_truant|target_insomnia"),
    U("Trick", "상대가 끈적끈적 특성이면 실패", fails_if="target_sticky_hold"),
    U("Switcheroo", "상대가 끈적끈적 특성이면 실패", fails_if="target_sticky_hold"),
    U("Lock-On", "이미 락온 상태면 실패 (다음 기술 필중)", fails_if="already_locked_on"),
    U("Quick Guard", "이번 턴 아직 행동할 포켓몬이 없으면 실패 (우선도 기술 방어)", requires="someone_acts_after"),
    U("Wide Guard", "이번 턴 아직 행동할 포켓몬이 없으면 실패 (범위 기술 방어)", requires="someone_acts_after"),
    U("Substitute", "HP가 25% 이하이거나 이미 분신이 있으면 실패", fails_if="user_hp_frac<=0.25|substitute_exists"),
    U("Pollen Puff", "대상이 아군이면 데미지 대신 최대HP 50% 회복(더블 전용)", ally_target_effect="heal_0.5"),

    # ── 실패 대가 / 사용 대가 ──
    M("Axe Kick", "fail_penalty", "빗나가거나 실패하면 최대HP 1/2 손실", hp_frac=0.5, phase_no=14),
    M("High Jump Kick", "fail_penalty", "빗나가거나 실패하면 최대HP 1/2 손실", hp_frac=0.5, phase_no=14),
    M("Supercell Slam", "fail_penalty", "빗나가거나 실패하면 최대HP 1/2 손실", hp_frac=0.5, phase_no=14),
    M("Steel Beam", "self_cost", "사용하면 최대HP 1/2 손실(연속기가 아닐 때, 빗나가도 손실)", hp_frac=0.5, round="nearest", phase_no=14),
    M("Substitute", "self_cost", "최대HP 1/4를 소모해 분신 생성", hp_frac=0.25, phase_no=10),
    M("Clangorous Soul", "self_cost", "최대HP 33%를 소모하고 모든 능력 +1", hp_frac=0.33, phase_no=10),
    M("Shed Tail", "self_cost", "최대HP 1/2를 소모해 분신을 만들고 교체하며 분신을 넘겨줌", hp_frac=0.5, phase_no=10),
    M("Burn Up", "extra_effect", "사용 후 자신의 불꽃 타입이 사라짐", effect="remove_user_type", type="Fire", phase_no=10),
    M("Double Shock", "extra_effect", "사용 후 자신의 전기 타입이 사라짐", effect="remove_user_type", type="Electric", phase_no=10),
    M("Steel Roller", "extra_effect", "명중하면 깔려 있는 필드를 지움", effect="clear_terrain", phase_no=10),
    M("Brick Break", "extra_effect", "맞히기 전에 상대 진영의 리플렉터/빛의장막/오로라베일을 부숨(분신을 뚫고도)",
      effect="shatter_screens", phase_no=4),
    M("Psychic Fangs", "extra_effect", "맞히기 전에 상대 진영의 벽을 부숨", effect="shatter_screens", phase_no=4),
    M("Raging Bull", "extra_effect", "맞히기 전에 상대 진영의 벽을 부숨", effect="shatter_screens", phase_no=4),
    M("Uproar", "extra_effect", "사용 시 필드의 모든 포켓몬의 잠듦을 깨움, 3턴 연속 사용 고정",
      effect="wake_all_sleepers", lock_turns=3, phase_no=10),
    M("Swallow", "extra_effect", "비축 겹수에 따라 회복(1겹 25%, 2겹 50%, 3겹 100%)하고 비축 효과 해제",
      effect="heal_by_stockpile", table=[[1, 0.25], [2, 0.5], [3, 1.0]], phase_no=10),
    M("Rest", "extra_effect", "HP를 전부 회복하고 상태이상을 치료한 뒤 2턴 잠듦", effect="full_heal_and_sleep", sleep_turns=2, phase_no=10),
    M("Curse", "extra_effect",
      "고스트 타입 사용 시 최대HP 1/2를 소모해 상대를 저주(매 턴 최대HP 1/4 손실), 그 외 타입은 스피드 -1, 공격 +1, 방어 +1",
      effect="curse", ghost_cost=0.5, ghost_dot=0.25, other_boosts={"spe": -1, "atk": 1, "def": 1}, phase_no=10),

    # ── 2턴(충전) 기술 ──
    CH("Fly", "flying", "1턴째 충전, 하늘로 올라가 회피율 최대 상태(대부분 공격이 빗나감). 예외 기술과 노가드/록온에는 맞음. 중력이면 사용 불가이고 걸리면 취소",
       hit_by_moves=["Gust", "Twister", "Sky Uppercut", "Thunder", "Hurricane", "Smack Down", "Thousand Arrows"],
       damage_mult_from_moves={"Gust": 2.0, "Twister": 2.0}, bypassed_by=INV_BYPASS,
       cancelled_by=["Gravity"], unusable_under=["Gravity"], evasion_max_check_phase=4, protect_bypass=False),
    CH("Bounce", "flying", "1턴째 충전, 하늘로 올라가 회피율 최대 상태(대부분 공격이 빗나감)(Fly와 동일 예외). 중력이면 사용 불가이고 걸리면 취소",
       hit_by_moves=["Gust", "Twister", "Sky Uppercut", "Thunder", "Hurricane", "Smack Down", "Thousand Arrows"],
       damage_mult_from_moves={"Gust": 2.0, "Twister": 2.0}, bypassed_by=INV_BYPASS,
       cancelled_by=["Gravity"], unusable_under=["Gravity"], evasion_max_check_phase=4, protect_bypass=False),
    CH("Dig", "underground", "1턴째 충전, 땅속에 숨어 회피율 최대 상태(대부분 공격이 빗나감). 모래바람 피해도 받지 않음",
       hit_by_moves=["Earthquake", "Magnitude", "Fissure"], damage_mult_from_moves={"Earthquake": 2.0, "Magnitude": 2.0},
       hit_by_moves_note="Fissure(땅가르기)도 맞으며 일격필살이라 배율 변경 없음(그대로 기절). 출처: 사용자 확인, Showdown 소스에는 없음",
       immune_weather_damage=["sand", "snow"], bypassed_by=INV_BYPASS, evasion_max_check_phase=4, protect_bypass=False),
    CH("Dive", "underwater", "1턴째 충전, 물속에 숨어 회피율 최대 상태(대부분 공격이 빗나감). 모래바람 피해도 받지 않음",
       hit_by_moves=["Surf", "Whirlpool"], damage_mult_from_moves={"Surf": 2.0, "Whirlpool": 2.0},
       immune_weather_damage=["sand", "snow"], bypassed_by=INV_BYPASS, evasion_max_check_phase=4, protect_bypass=False),
    CH("Phantom Force", "shadow", "1턴째 충전, 모습을 감춰 회피율 최대 상태(예외 기술 없음). 이 기술 자체가 방어(Protect)를 무시하고 때림",
       hit_by_moves=[], ignores_protect=True, bypassed_by=INV_BYPASS, evasion_max_check_phase=4, protect_bypass=False),
    CH("Sky Attack", "none", "1턴째 충전(회피율 최대 상태 없음). 2턴째 공격"),
    CH("Meteor Beam", "none", "1턴째 충전하며 특수공격 +1. 2턴째 공격", charge_boost={"spa": 1}),
    CH("Electro Shot", "none", "1턴째 충전하며 특수공격 +1. 비 상태면 충전 없이 즉시 공격", charge_boost={"spa": 1}, skip_if="weather:rain"),
    M("Solar Beam", "charge_move", "1턴째 충전. 쾌청 상태면 충전 없이 즉시 공격", evasion_max="none", skip_if="weather:sun", phase_no=3),
    M("Solar Blade", "charge_move", "1턴째 충전. 쾌청 상태면 충전 없이 즉시 공격", evasion_max="none", skip_if="weather:sun", phase_no=3),
    M("Future Sight", "delayed_move", "사용 후 2턴 뒤 상대 위치에 공격(그 위치에 이미 지연 공격이 있으면 실패)",
      hits_after_turns=2, fails_if="slot_has_pending_future_move", phase_no=3),

    # ── 타입·위력·명중·우선도가 조건에 따라 변하는 기술 ──
    M("Weather Ball", "type_by_condition", "날씨에 따라 타입이 바뀜 (쾌청 불꽃, 비 물, 모래바람 바위, 눈 얼음)", by="weather",
      table={"sun": "Fire", "rain": "Water", "sand": "Rock", "snow": "Ice"}, phase_no=3),
    M("Weather Ball", "power_mult_if", "날씨가 있으면 위력 2배", mult=2.0, when=dict(weather_in="sun|rain|sand|snow")),
    M("Terrain Pulse", "type_by_condition", "필드에 따라 타입이 바뀜 (자신이 땅에 붙어 있을 때)", by="terrain", requires="user_grounded",
      table={"electric": "Electric", "grassy": "Grass", "misty": "Fairy", "psychic": "Psychic"}, phase_no=3),
    M("Terrain Pulse", "power_mult_if", "필드가 있고 자신이 땅에 붙어 있으면 위력 2배", mult=2.0, when=dict(terrain="any", user_grounded=True)),
    M("Aura Wheel", "type_by_condition", "모르페코(배부름) 전기, 배고픔 모드는 악 타입. 모르페코만 사용 가능", by="form",
      table={"Morpeko": "Electric", "Morpeko-Hangry": "Dark"}, requires="user_species:Morpeko", phase_no=3),
    M("Raging Bull", "type_by_condition", "켄타로스 폼에 따라 타입 변화 (컴뱃 격투, 블레이즈 불꽃, 아쿠아 물)", by="form",
      table={"Tauros-Paldea-Combat": "Fighting", "Tauros-Paldea-Blaze": "Fire", "Tauros-Paldea-Aqua": "Water"}, phase_no=3),
    M("Hurricane", "accuracy_by_condition", "비 상태면 필중, 쾌청 상태면 명중 50%", table={"rain": "always", "sun": 50}),
    M("Thunder", "accuracy_by_condition", "비 상태면 필중, 쾌청 상태면 명중 50%", table={"rain": "always", "sun": 50}),
    M("Blizzard", "accuracy_by_condition", "눈 상태면 필중", table={"snow": "always"}),
    M("Grassy Glide", "priority_by_condition", "그래스필드에서 자신이 땅에 붙어 있으면 우선도 +1", add=1,
      when=dict(terrain="grassy", user_grounded=True), phase_no=1),
    M("Flying Press", "effectiveness_mod", "격투와 비행 타입 상성을 곱해서 계산 (상대 타입마다 두 타입 상성을 합산)",
      extra_type="Flying", phase_no=8),
    M("Freeze-Dry", "effectiveness_mod", "물 타입에는 효과가 굉장함으로 취급 (x2)", vs_type="Water", force_multiplier=2.0, phase_no=8),
    M("Growth", "boost_by_condition", "기본 공격/특공 +1, 쾌청 상태면 공격/특공 +2", base={"atk": 1, "spa": 1},
      table={"sun": {"atk": 2, "spa": 2}}, phase_no=10),
    M("Shell Side Arm", "category_choice", "상대 방어/특방을 고려해 계산상 더 큰 쪽 분류로 공격 (물리면 접촉기). 같으면 50% 무작위",
      method="compare_physical_vs_special_damage", phase_no=3),
    M("Focus Punch", "use_condition", "행동 전에 공격받으면 집중이 흐트러져 기술이 실패 (우선도 -3)",
      fails_if="hit_before_moving", priority=-3, phase_no=2),
    M("Beak Blast", "use_condition", "행동 전 대기 중 접촉 공격을 받으면 상대를 화상 입힘 (우선도 -3)",
      on_contact_while_charging="burn_attacker", priority=-3, phase_no=2),
    M("Lock-On", "extra_effect", "다음 행동의 기술이 같은 상대에게 반드시 명중하고 회피율 최대 상태(공중날기 등)도 무시. 방어(Protect)는 못 뚫음",
      effect="lock_on", next_move_always_hits=True, ignores_invulnerability=True, duration_turns=1, same_target_only=True,
      phase_no=10),
    M("Mind Reader", "extra_effect", "다음 행동의 기술이 같은 상대에게 반드시 명중하고 회피율 최대 상태도 무시. 방어(Protect)는 못 뚫음",
      effect="lock_on", next_move_always_hits=True, ignores_invulnerability=True, duration_turns=1, same_target_only=True,
      phase_no=10),
    M("Chilly Reception", "extra_effect", "눈을 내리게 한 뒤 자신이 교체됨", effect="set_weather_then_switch", weather="snow", phase_no=10),
]
