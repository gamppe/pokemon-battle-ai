"""지속 상태(날씨·필드·방·벽·함정·개별 포켓몬 상태·상태이상) 구조화.
출처: Showdown data/moves.ts(각 기술의 condition 블록), data/conditions.ts. 수작업.

S(code, name_ko, scope, category, set_by, duration, ext, effects, note)
  scope    : field / side / pokemon / slot
  category : weather / terrain / pseudo_weather / side_condition / volatile / status / slot_condition
  duration : 지속 턴 수(NULL = 해제될 때까지)
  ext      : 지속 연장 {"아이템/특성": 턴수}
E(hook, kind, ...): 특성/아이템과 같은 어휘. order_no = 턴 종료 처리 순서(작을수록 먼저, 소스의 onResidualOrder)
"""


def E(hook, kind, value=None, code=None, target=None, chance=100, order_no=None, note=None, **cond):
    return dict(hook=hook, kind=kind, value=value, code=code, target=target, chance=chance,
                order_no=order_no, note=note, cond=cond or None)


def S(code, name_ko, scope, category, set_by, duration, ext, effects, note=None):
    return dict(code=code, name_ko=name_ko, scope=scope, category=category, set_by=set_by,
                duration=duration, ext=ext, effects=effects, note=note)


PERSIST = {"Persistent(특성)": None}  # 참고용: 일부 방/필드는 특정 특성으로 +2턴

STATES = [
    # ───── 날씨 ─────
    S("rain", "비", "field", "weather", "Rain Dance / Drizzle", 5, {"Damp Rock": 8}, [
        E("modify_dmg_dealt", "mult", 1.5, move_type="Water", note="날씨 데미지 보정(방어 쪽 날씨 기준)"),
        E("modify_dmg_dealt", "mult", 0.5, move_type="Fire"),
        E("turn_end", "special", code="weather_residual", order_no=1)], "특성으로 발동한 날씨도 5턴(9세대)"),
    S("sun", "쾌청", "field", "weather", "Sunny Day / Drought", 5, {"Heat Rock": 8}, [
        E("modify_dmg_dealt", "mult", 1.5, move_type="Fire"),
        E("modify_dmg_dealt", "mult", 0.5, move_type="Water"),
        E("modify_dmg_dealt", "mult", 1.5, move="Hydro Steam", note="워터스팀은 쾌청에서 오히려 1.5배"),
        E("immunity", "immune", code="status:frz", target="all"),
        E("turn_end", "special", code="weather_residual", order_no=1)]),
    S("sand", "모래바람", "field", "weather", "Sandstorm / Sand Stream", 5, {"Smooth Rock": 8}, [
        E("modify_def", "mult", 1.5, move_category="special", target_type="Rock", note="바위 타입의 특방 x1.5"),
        E("turn_end", "damage_frac", 0.0625, target="all", order_no=1, immune_types="Rock|Ground|Steel",
          note="바위/땅/강철 타입 외 최대HP 1/16 피해. 모래숨기·모래의힘·모래헤치기·방진·매직가드 특성 등은 면역")]),
    S("snow", "눈", "field", "weather", "Snowscape / Snow Warning", 5, {"Icy Rock": 8}, [
        E("modify_def", "mult", 1.5, move_category="physical", target_type="Ice", note="얼음 타입의 방어 x1.5"),
        E("turn_end", "special", code="weather_residual", order_no=1)], "9세대는 우박 대신 눈. 피해 없음"),

    # ───── 필드(테라인) : 땅에 붙어 있는(grounded) 포켓몬만 영향 ─────
    S("electric_terrain", "일렉트릭필드", "field", "terrain", "Electric Terrain / Electric Surge", 5, {"Terrain Extender": 8}, [
        E("immunity", "immune", code="status:slp", target="all", grounded=True, note="잠듦(하품 포함) 방지"),
        E("modify_bp", "mult", 1.3, move_type="Electric", user_grounded=True),
        E("turn_end", "special", code="terrain_end", order_no=27)], "회피율 최대 상태(구멍파기 등) 중에는 영향 없음"),
    S("grassy_terrain", "그래스필드", "field", "terrain", "Grassy Terrain / Grassy Surge / Seed Sower", 5, {"Terrain Extender": 8}, [
        E("modify_bp", "mult", 0.5, move="Earthquake|Bulldoze|Magnitude", target_grounded=True),
        E("modify_bp", "mult", 1.3, move_type="Grass", user_grounded=True),
        E("turn_end", "heal_frac", 0.0625, target="all", order_no=5, grounded=True),
        E("turn_end", "special", code="terrain_end", order_no=27)]),
    S("misty_terrain", "미스트필드", "field", "terrain", "Misty Terrain", 5, {"Terrain Extender": 8}, [
        E("immunity", "immune", code="status:any|volatile:confusion", target="all", grounded=True),
        E("modify_bp", "mult", 0.5, move_type="Dragon", target_grounded=True),
        E("turn_end", "special", code="terrain_end", order_no=27)]),
    S("psychic_terrain", "사이코필드", "field", "terrain", "Psychic Terrain / Psychic Surge", 5, {"Terrain Extender": 8}, [
        E("immunity", "immune", code="priority_moves", target="all", grounded=True, note="우선도 1 이상(자신 대상 제외) 기술이 땅에 붙은 상대에게 무효"),
        E("modify_bp", "mult", 1.3, move_type="Psychic", user_grounded=True),
        E("turn_end", "special", code="terrain_end", order_no=27)]),

    # ───── 필드(방 효과) ─────
    S("trick_room", "트릭룸", "field", "pseudo_weather", "Trick Room", 5, {"Persistent(특성)": 7}, [
        E("modify_priority", "special", code="reverse_speed_order", note="같은 우선도 안에서 스피드가 느린 쪽이 먼저. 다시 쓰면 해제"),
        E("turn_end", "special", code="room_end", order_no=27)], "사용 시 우선도 -7"),
    S("gravity", "중력", "field", "pseudo_weather", "Gravity", 5, {"Persistent(특성)": 7}, [
        E("modify_acc", "mult", 1.6667, note="모든 기술 명중률 x5/3"),
        E("passive", "special", code="ground_everyone", target="all", note="모든 포켓몬이 땅에 붙음(비행·부유 무효화)"),
        E("before_move", "immune", code="move_flag:gravity", target="all", note="gravity 플래그 기술(공중날기, 바운스, 플라잉프레스 등) 사용 불가"),
        E("switch_in", "special", code="cancel_airborne", note="발동 시 공중날기/바운스/자석부유/텔레키네시스 해제하고 그 기술 취소"),
        E("turn_end", "special", code="room_end", order_no=27)]),
    S("magic_room", "매직룸", "field", "pseudo_weather", "Magic Room", 5, {"Persistent(특성)": 7}, [
        E("passive", "special", code="items_suppressed", target="all", note="모든 지닌 도구 효과 정지"),
        E("turn_end", "special", code="room_end", order_no=27)]),
    S("wonder_room", "원더룸", "field", "pseudo_weather", "Wonder Room", 5, {"Persistent(특성)": 7}, [
        E("passive", "special", code="swap_def_spd", target="all", note="방어와 특방이 서로 바뀜"),
        E("turn_end", "special", code="room_end", order_no=27)]),
    S("fairy_lock", "요정의 족쇄", "field", "pseudo_weather", "Fairy Lock", 2, None, [
        E("passive", "trap", target="all", note="다음 턴 모든 포켓몬이 교체 불가")]),

    # ───── 진영(사이드) 상태 ─────
    S("reflect", "리플렉터", "side", "side_condition", "Reflect", 5, {"Light Clay": 8}, [
        E("modify_dmg_taken", "mult", 0.5, move_category="physical", not_crit=True, not_infiltrates=True,
          note="더블에서는 x2/3"),
        E("turn_end", "special", code="side_end", order_no=26)]),
    S("light_screen", "빛의장막", "side", "side_condition", "Light Screen", 5, {"Light Clay": 8}, [
        E("modify_dmg_taken", "mult", 0.5, move_category="special", not_crit=True, not_infiltrates=True, note="더블에서는 x2/3"),
        E("turn_end", "special", code="side_end", order_no=26)]),
    S("aurora_veil", "오로라베일", "side", "side_condition", "Aurora Veil (눈일 때만 사용)", 5, {"Light Clay": 8}, [
        E("modify_dmg_taken", "mult", 0.5, move_category="physical|special", not_crit=True, not_infiltrates=True,
          note="더블에서는 x2/3. 물리·특수 모두 경감"),
        E("turn_end", "special", code="side_end", order_no=26)], "리플렉터/빛의장막과 중복 불가가 아님: 별개 상태"),
    S("safeguard", "신비의부적", "side", "side_condition", "Safeguard", 5, {"Persistent(특성)": 7}, [
        E("immunity", "immune", code="status:any|volatile:confusion|volatile:yawn", target="ally",
          note="상대가 거는 상태이상/혼란/하품 방지 (Infiltrator 기술은 통과)"),
        E("turn_end", "special", code="side_end", order_no=26)]),
    S("tailwind", "순풍", "side", "side_condition", "Tailwind", 4, {"Persistent(특성)": 6}, [
        E("modify_spe", "mult", 2.0, target="ally"),
        E("turn_end", "special", code="side_end", order_no=26)]),
    S("spikes", "압정뿌리기", "side", "side_condition", "Spikes", None, None, [
        E("switch_in", "damage_frac", code="by_layers", target="switching_in", grounded=True,
          table="1:0.125|2:0.1667|3:0.25", max_layers=3, note="최대HP 대비 1겹 1/8, 2겹 1/6, 3겹 1/4. 땅에 붙은 포켓몬만")]),
    S("toxic_spikes", "독압정", "side", "side_condition", "Toxic Spikes", None, None, [
        E("switch_in", "status", code="by_layers", target="switching_in", grounded=True, table="1:psn|2:tox", max_layers=2,
          note="독타입이 땅에 붙은 채 들어오면 독압정이 사라짐. 강철 타입은 면역")]),
    S("stealth_rock", "스텔스록", "side", "side_condition", "Stealth Rock", None, None, [
        E("switch_in", "damage_frac", code="rock_effectiveness", target="switching_in", base=0.125,
          note="최대HP x 1/8 x 바위 타입 상성(0.25~4배). 땅에 붙어있지 않아도 받음")]),
    S("sticky_web", "끈적끈적네트", "side", "side_condition", "Sticky Web", None, None, [
        E("switch_in", "stat_stage", -1, code="spe", target="switching_in", grounded=True)]),
    S("wish", "희망사항", "slot", "slot_condition", "Wish", 2, None, [
        E("turn_end", "heal_frac", 0.5, target="slot_holder", order_no=4,
          note="사용 다음 턴 종료 시, 사용자의 최대HP 1/2를 그 자리 포켓몬이 회복")]),

    # ───── 개별 포켓몬 상태(volatile) ─────
    S("aqua_ring", "아쿠아링", "pokemon", "volatile", "Aqua Ring", None, None, [
        E("turn_end", "heal_frac", 0.0625, target="self", order_no=6)]),
    S("ingrain", "뿌리박기", "pokemon", "volatile", "Ingrain", None, None, [
        E("turn_end", "heal_frac", 0.0625, target="self", order_no=7),
        E("passive", "trap", target="self"), E("immunity", "immune", code="forced_switch"),
        E("passive", "special", code="grounded", note="땅에 붙음")]),
    S("charge", "충전", "pokemon", "volatile", "Charge / Electromorphosis", None, None, [
        E("modify_bp", "mult", 2.0, move_type="Electric", note="다음 전기 기술 위력 2배, 전기 기술을 쓰면 해제"),
        E("passive", "special", code="special_defense_up_on_charge", value=1, note="Charge 기술 사용 시 특방 +1")]),
    S("destiny_bond", "길동무", "pokemon", "volatile", "Destiny Bond", None, None, [
        E("on_faint", "special", code="faint_attacker", note="상대의 기술로 쓰러지면 공격한 상대도 쓰러짐 (미래예지 제외). 다음에 기술을 쓰면 해제")]),
    S("dragon_cheer", "용의함성", "pokemon", "volatile", "Dragon Cheer", None, None, [
        E("modify_crit", "crit_stage", 1, note="용 타입이면 +2. Focus Energy와 중복 불가", dragon_type_value=2)]),
    S("focus_energy", "기술을 모으고", "pokemon", "volatile", "Focus Energy", None, None, [
        E("modify_crit", "crit_stage", 2, note="Dragon Cheer와 중복 불가")]),
    S("encore", "앵콜", "pokemon", "volatile", "Encore", 3, None, [
        E("passive", "special", code="lock_last_move", note="마지막으로 쓴 기술만 사용 가능. PP가 다하면 해제", order_no=16)]),
    S("glaive_rush", "글레이브러시", "pokemon", "volatile", "Glaive Rush", None, None, [
        E("modify_dmg_taken", "mult", 2.0, note="다음 자신의 행동까지 받는 데미지 2배"),
        E("modify_evasion", "special", code="always_hit_target", note="다음 자신의 행동까지 맞는 기술이 필중")]),
    S("imprison", "봉인", "pokemon", "volatile", "Imprison", None, None, [
        E("passive", "special", code="foes_cannot_use_my_moves", target="foe", note="자신이 아는 기술을 상대는 사용할 수 없음")]),
    S("minimize", "작아지기", "pokemon", "volatile", "Minimize", None, None, [
        E("modify_dmg_taken", "mult", 2.0, move_flag="minimize", note="minimize 플래그 기술(짓밟기 등)에 받는 데미지 2배"),
        E("modify_evasion", "special", code="minimize_flag_moves_always_hit")]),
    S("power_trick", "파워트릭", "pokemon", "volatile", "Power Trick", None, None, [
        E("passive", "special", code="swap_atk_def", note="공격과 방어의 실수치가 서로 바뀜. 다시 쓰면 원상복구")]),
    S("salt_cure", "소금절임", "pokemon", "volatile", "Salt Cure", None, None, [
        E("turn_end", "damage_frac", 0.125, target="self", order_no=13, note="물/강철 타입은 1/4")]),
    S("smack_down", "떨어뜨리기(상태)", "pokemon", "volatile", "Smack Down / Thousand Arrows", None, None, [
        E("passive", "special", code="grounded", note="땅에 붙음(비행/부유도 땅 기술을 받음). 공중날기 중이면 취소")]),
    S("syrup_bomb", "시럽폭탄", "pokemon", "volatile", "Syrup Bomb", 4, None, [
        E("turn_end", "stat_stage", -1, code="spe", target="self", order_no=14, note="사용자가 필드를 떠나면 해제")]),
    S("taunt", "도발", "pokemon", "volatile", "Taunt", 3, {"Oblivious": None}, [
        E("before_move", "immune", code="status_moves", target="self", order_no=15, note="변화 기술 사용 불가 (3턴, 첫 턴 아직 안 움직였으면 +1)")]),
    S("throat_chop", "인후공격(상태)", "pokemon", "volatile", "Throat Chop", 2, None, [
        E("before_move", "immune", code="move_flag:sound", target="self", order_no=22, note="소리 기술 사용 불가 (2턴)")]),
    S("torment", "트집", "pokemon", "volatile", "Torment", None, None, [
        E("before_move", "immune", code="repeat_last_move", target="self", note="같은 기술을 연속으로 사용할 수 없음")]),
    S("roost_state", "날개쉬기(상태)", "pokemon", "volatile", "Roost", 1, None, [
        E("passive", "special", code="lose_flying_type", note="그 턴 동안 비행 타입이 사라짐(땅 기술을 받음)", order_no=25)]),
    S("fling_state", "던지기(상태)", "pokemon", "volatile", "Fling", None, None, [
        E("after_hit", "special", code="consume_item", note="던진 도구가 소모됨")]),

    # ───── 상태이상(major) ─────
    S("brn", "화상", "pokemon", "status", "화염구슬/화염방사 등", None, None, [
        E("turn_end", "damage_frac", 0.0625, target="self", order_no=10),
        E("modify_dmg_dealt", "mult", 0.5, move_category="physical", note="물리 공격 데미지 절반 (근성 특성, Facade는 예외)", ignored_by="Guts|Facade"),
        E("immunity", "immune", code="type:Fire")]),
    S("par", "마비", "pokemon", "status", "전기자석파 등", None, None, [
        E("modify_spe", "mult", 0.5, note="스피드 절반 (속보 특성은 무시)", ignored_by="Quick Feet"),
        E("before_move", "special", code="full_paralysis", chance=25, note="25% 확률로 움직이지 못함"),
        E("immunity", "immune", code="type:Electric")]),
    S("slp", "잠듦", "pokemon", "status", "수면가루 등", None, None, [
        E("before_move", "special", code="sleep_counter", value=3, note="1~3턴 동안 행동 불가(잠들 때 카운트 2~4를 정하고 행동 시도마다 -1, 0이 되면 깨어나 그 턴에 행동). 조기상승 특성은 -2씩",
          min_turns=1, max_turns=3),
        E("immunity", "immune", code="usable_moves:Snore|Sleep Talk")]),
    S("frz", "얼음", "pokemon", "status", "눈보라/냉동빔 등", None, None, [
        E("before_move", "special", code="thaw", chance=20, note="행동 시도마다 20% 확률로 녹음. 해동 기술(defrost 플래그)을 쓰면 확정 해동"),
        E("on_hit_taken", "cure_status", target="self", move_type="Fire", note="불꽃 타입 공격을 받으면 녹음"),
        E("immunity", "immune", code="type:Ice"), E("immunity", "immune", code="weather:sun")]),
    S("psn", "독", "pokemon", "status", "독침 등", None, None, [
        E("turn_end", "damage_frac", 0.125, target="self", order_no=9),
        E("immunity", "immune", code="type:Poison|Steel")]),
    S("tox", "맹독", "pokemon", "status", "맹독 등", None, None, [
        E("turn_end", "damage_frac", 0.0625, target="self", order_no=9, scales_with="turns", max_stage=15,
          note="최대HP x 1/16 x 경과 턴 수(최대 15). 교체하면 단계가 1로 돌아감"),
        E("immunity", "immune", code="type:Poison|Steel")]),
    S("confusion", "혼란", "pokemon", "volatile", "혼란 기술 등", None, None, [
        E("before_move", "special", code="confusion_self_hit", chance=33, value=40,
          note="행동 시도마다 -1, 0이 되면 해제. 그 전까지 33% 확률로 위력 40의 타입 없는 물리 공격으로 자신을 때림. 지속 2~5회(앞차기 부작용은 최소 3)",
          min_attempts=2, max_attempts=5)]),
    S("flinch", "풀죽음", "pokemon", "volatile", "페이크 아웃 등", 1, None, [
        E("before_move", "special", code="cannot_move", note="그 턴 행동 불가 (먼저 움직인 쪽만 유발 가능)")]),
    S("partially_trapped", "속박", "pokemon", "volatile", "조이기/감아붙이기 등", None, {"Grip Claw": 8}, [
        E("turn_end", "damage_frac", 0.125, target="self", order_no=13, note="Binding Band 지닌 쪽이면 1/6. 5~7턴"),
        E("passive", "trap", target="self", note="사용자가 필드에 있는 동안 교체 불가")]),
]


from battle_state_data_2 import STATES2  # noqa: E402
STATES += STATES2
