"""코드로만 처리되던 기술 동작을 수치/구조로 정리 (Showdown data/moves.ts 소스를 읽고 수작업).

행 형식: M(기술영문명, rule_type, note, **params)
 rule_type
  power_mult_if   : 조건이 맞으면 위력에 mult를 곱함. params: mult, when(조건 dict) [, chance]
  power_formula   : 위력을 공식으로 계산. params: formula + 상수/표
  damage_formula  : 위력 대신 데미지를 공식으로 직접 계산(상성 무시). params: formula 등
  on_hit_effect   : 명중 후 부가 동작 (Knock Off의 아이템 제거 등)
  modify_target   : 조건부 대상 변경
 조건 키(when): user_item_none, target_hurt_this_turn, user_hit_by_target_this_turn, target_status(any|psn|tox..),
   user_status_not_sleep, user_stats_lowered_this_turn, user_moves_after_target, last_move_failed,
   terrain(+grounded), pseudo_weather, weather_in, target_has_removable_item
 공식(formula): hp_ratio / hp_tiers48 / speed_ratio_table / gyro_ball / target_hp_ratio / positive_boost_count /
   fainted_allies / times_attacked / party_atk / weight_tiers / weight_ratio_tiers / stockpile_layers / hit_index
 damage formula: user_current_hp / half_target_hp / target_hp_minus_user_hp / reflect_last_damage"""


def M(move, rule_type, note=None, **params):
    return dict(move=move, rule_type=rule_type, note=note, params=params)


def mult_if(move, mult, note=None, **when):
    return M(move, "power_mult_if", note, mult=mult, when=when)


RULES = [
    # ── 조건이 맞으면 위력 배율 ──
    mult_if("Acrobatics", 2.0, "지닌 도구가 없으면 위력 2배", user_item_none=True),
    mult_if("Assurance", 2.0, "이번 턴 상대가 이미 데미지를 입었으면 2배", target_hurt_this_turn=True),
    mult_if("Avalanche", 2.0, "이번 턴 상대에게 먼저 맞았으면 2배", user_hit_by_target_this_turn=True),
    mult_if("Barb Barrage", 2.0, "상대가 독/맹독 상태면 2배", target_status="psn|tox"),
    mult_if("Venoshock", 2.0, "상대가 독/맹독 상태면 2배", target_status="psn|tox"),
    mult_if("Facade", 2.0, "자신이 잠듦 외의 상태이상이면 2배 (화상 공격력 감소도 무시)", user_status_not_sleep=True),
    mult_if("Hex", 2.0, "상대가 상태이상이면 2배", target_status="any"),
    mult_if("Infernal Parade", 2.0, "상대가 상태이상이면 2배", target_status="any"),
    mult_if("Lash Out", 2.0, "이번 턴 자신의 능력이 하락했다면 2배", user_stats_lowered_this_turn=True),
    mult_if("Payback", 2.0, "상대가 먼저 행동을 끝낸 뒤(자신이 나중에 움직임)면 2배", user_moves_after_target=True),
    mult_if("Stomping Tantrum", 2.0, "직전 턴에 자신의 기술이 실패했으면 2배", last_move_failed=True),
    mult_if("Temper Flare", 2.0, "직전 턴에 자신의 기술이 실패했으면 2배", last_move_failed=True),
    mult_if("Rising Voltage", 2.0, "일렉트릭필드에서 상대가 땅에 붙어 있으면 2배", terrain="electric", target_grounded=True),
    mult_if("Expanding Force", 1.5, "사이코필드에서 자신이 땅에 붙어 있으면 1.5배(대상도 상대 전체로 확대)",
            terrain="psychic", user_grounded=True),
    mult_if("Misty Explosion", 1.5, "미스트필드에서 자신이 땅에 붙어 있으면 1.5배", terrain="misty", user_grounded=True),
    mult_if("Grav Apple", 1.5, "중력 상태면 1.5배", pseudo_weather="gravity"),
    M("Knock Off", "power_mult_if", "상대가 떼어낼 수 있는 도구를 지니면 1.5배 (위력 계산 시점의 도구 기준)",
      mult=1.5, when=dict(target_has_removable_item=True), phase="base_power_calc"),
    mult_if("Solar Beam", 0.5, "비/모래바람/눈에서는 위력 절반 (쾌청이면 충전 없이 즉시 발동은 별도)",
            weather_in="rain|sand|snow"),
    mult_if("Solar Blade", 0.5, "비/모래바람/눈에서는 위력 절반", weather_in="rain|sand|snow"),
    M("Fickle Beam", "power_mult_if", "30% 확률로 위력 2배", mult=2.0, when={}, chance=0.3),

    # ── 위력을 공식으로 계산 ──
    M("Eruption", "power_formula", "150 x 현재HP/최대HP", formula="hp_ratio", base=150, user="self"),
    M("Water Spout", "power_formula", "150 x 현재HP/최대HP", formula="hp_ratio", base=150, user="self"),
    M("Flail", "power_formula", "자신 HP가 적을수록 강함. ratio=max(floor(HP*48/최대HP),1)",
      formula="hp_tiers48", tiers=[[1, 200], [4, 150], [9, 100], [16, 80], [32, 40], [999, 20]],
      note_tiers="ratio<2:200, <5:150, <10:100, <17:80, <33:40, 그 외 20"),
    M("Reversal", "power_formula", "자신 HP가 적을수록 강함 (Flail과 동일 표)",
      formula="hp_tiers48", tiers=[[1, 200], [4, 150], [9, 100], [16, 80], [32, 40], [999, 20]]),
    M("Hard Press", "power_formula", "100 x 상대 현재HP/최대HP, 최소 1", formula="target_hp_ratio", base=100, min=1),
    M("Electro Ball", "power_formula", "floor(자신 스피드/상대 스피드)=ratio, 표 [40,60,80,120,150][min(ratio,4)]",
      formula="speed_ratio_table", table=[40, 60, 80, 120, 150], ratio="user/target"),
    M("Gyro Ball", "power_formula", "floor(25 x 상대 스피드/자신 스피드)+1, 최대 150",
      formula="gyro_ball", factor=25, add=1, cap=150),
    M("Stored Power", "power_formula", "20 + 20 x 자신의 능력 상승 단계 합(양수만)",
      formula="positive_boost_count", base=20, per=20),
    M("Power Trip", "power_formula", "20 + 20 x 자신의 능력 상승 단계 합(양수만)",
      formula="positive_boost_count", base=20, per=20),
    M("Last Respects", "power_formula", "50 + 50 x 지금까지 쓰러진 아군 수", formula="fainted_allies", base=50, per=50),
    M("Rage Fist", "power_formula", "50 + 50 x 맞은 횟수, 최대 350", formula="times_attacked", base=50, per=50, cap=350),
    M("Beat Up", "power_formula", "파티의 건강한 포켓몬(자신 포함)마다 1타. 각 타 위력 = 5 + floor(그 포켓몬 기본 공격/10)",
      formula="party_atk", base=5, div=10, hits="healthy_party_members"),
    M("Low Kick", "power_formula", "상대 몸무게(0.1kg 단위)가 클수록 강함",
      formula="weight_tiers", target="target", tiers=[[2000, 120], [1000, 100], [500, 80], [250, 60], [100, 40], [0, 20]]),
    M("Grass Knot", "power_formula", "상대 몸무게가 클수록 강함 (Low Kick과 동일 표)",
      formula="weight_tiers", target="target", tiers=[[2000, 120], [1000, 100], [500, 80], [250, 60], [100, 40], [0, 20]]),
    M("Heavy Slam", "power_formula", "자신 몸무게/상대 몸무게 배수가 클수록 강함",
      formula="weight_ratio_tiers", tiers=[[5, 120], [4, 100], [3, 80], [2, 60], [0, 40]]),
    M("Heat Crash", "power_formula", "자신 몸무게/상대 몸무게 배수가 클수록 강함 (Heavy Slam과 동일 표)",
      formula="weight_ratio_tiers", tiers=[[5, 120], [4, 100], [3, 80], [2, 60], [0, 40]]),
    M("Spit Up", "power_formula", "100 x 비축한 단계(최대 3). 비축이 없으면 실패",
      formula="stockpile_layers", per=100, fails_if="no_stockpile"),
    M("Triple Axel", "power_formula", "1타 20, 2타 40, 3타 60 (타마다 명중 판정)", formula="hit_index", per=20, hits=3),
    M("Round", "power_mult_if", "같은 턴에 다른 Round가 먼저 쓰였으면 2배 (더블 전용)", mult=2.0,
      when=dict(another_round_used_this_turn=True)),
    M("Water Shuriken", "power_formula", "기본 15 (Ash-Greninja 전용 +5는 무시)", formula="constant", base=15),

    # ── 데미지를 공식으로 직접 계산 (타입 상성 무시) ──
    M("Final Gambit", "damage_formula", "자신의 현재 HP만큼 데미지를 주고 자신은 기절", formula="user_current_hp", user_faints=True),
    M("Super Fang", "damage_formula", "상대 현재 HP의 절반 (최소 1)", formula="half_target_hp", min=1),
    M("Endeavor", "damage_formula", "상대 HP를 자신의 HP와 같게 만듦. 자신 HP >= 상대 HP면 실패",
      formula="target_hp_minus_user_hp", fails_if="user_hp>=target_hp"),
    M("Counter", "damage_formula", "이번 턴 받은 물리 데미지의 2배를 상대에게 돌려줌. 없으면 실패",
      formula="reflect_last_damage", multiplier=2.0, category="physical", fails_if="no_damage_this_turn"),
    M("Mirror Coat", "damage_formula", "이번 턴 받은 특수 데미지의 2배를 상대에게 돌려줌. 없으면 실패",
      formula="reflect_last_damage", multiplier=2.0, category="special", fails_if="no_damage_this_turn"),
    M("Metal Burst", "damage_formula", "이번 턴 마지막으로 받은 데미지의 1.5배. 없으면 실패",
      formula="reflect_last_damage", multiplier=1.5, category="any", fails_if="no_damage_this_turn"),
    M("Comeuppance", "damage_formula", "이번 턴 마지막으로 받은 데미지의 1.5배. 없으면 실패",
      formula="reflect_last_damage", multiplier=1.5, category="any", fails_if="no_damage_this_turn"),

    # ── 명중 후 동작 ──
    M("Knock Off", "on_hit_effect",
      "AfterHit 단계(12)에서 아직 남은 도구를 제거. 데미지 계산/적용 중에 이미 소모된 도구(반감 열매, 기합의띠)는 없어서 제거되지 않음. "
      "HP 조건 열매(자뭉열매 등)는 갱신 단계(13)가 AfterHit(12)보다 뒤라서 먹기 전에 제거됨. "
      "메가스톤(해당 포켓몬)/끈적끈적 특성/Substitute 등은 제거 불가",
      effect="remove_target_item", phase="after_hit", only_if="item_still_held",
      consumed_before=["resist_berry", "focus_sash", "focus_band", "air_balloon_pop"],
      removed_before_use=["hp_threshold_berry"], blocked_by="sticky_hold|own_mega_stone|substitute"),
]


from move_rules_data_2 import RULES2  # noqa: E402
RULES += RULES2


from move_rules_data_3 import RULES3  # noqa: E402
RULES += RULES3


from move_rules_data_4 import RULES4  # noqa: E402
RULES += RULES4


# 위력 배율이 적용되는 시점 (Showdown: basePowerCallback / onModifyMove / onBasePower)
STAGE_OF = {"Acrobatics": "callback", "Assurance": "callback", "Avalanche": "callback", "Hex": "callback", "Infernal Parade": "callback",
            "Payback": "callback", "Rising Voltage": "callback", "Stomping Tantrum": "callback", "Temper Flare": "callback",
            "Round": "callback", "Weather Ball": "move", "Terrain Pulse": "move"}
for _r in RULES:
    if _r["rule_type"] == "power_mult_if":
        _r["params"].setdefault("stage", STAGE_OF.get(_r["move"], "chain"))
