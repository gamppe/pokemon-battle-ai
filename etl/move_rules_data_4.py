"""지속 상태를 일으키는 기술 -> battle_state 연결, 던지기(Fling) 도구별 위력.
move_rules_data.py 끝에서 RULES에 합쳐진다."""
import json, os, re

HERE = os.path.dirname(os.path.abspath(__file__))


def M(move, rule_type, note=None, **params):
    return dict(move=move, rule_type=rule_type, note=note, params=params)


# 기술 -> battle_state.code (state 상세는 battle_state / battle_state_effect)
SETS_STATE = {
    "Aqua Ring": "aqua_ring", "Charge": "charge", "Destiny Bond": "destiny_bond", "Dragon Cheer": "dragon_cheer",
    "Electric Terrain": "electric_terrain", "Grassy Terrain": "grassy_terrain", "Misty Terrain": "misty_terrain",
    "Psychic Terrain": "psychic_terrain", "Encore": "encore", "Fairy Lock": "fairy_lock", "Focus Energy": "focus_energy",
    "Glaive Rush": "glaive_rush", "Gravity": "gravity", "Imprison": "imprison", "Ingrain": "ingrain",
    "Light Screen": "light_screen", "Reflect": "reflect", "Magic Room": "magic_room", "Wonder Room": "wonder_room",
    "Trick Room": "trick_room", "Minimize": "minimize", "Power Trick": "power_trick", "Roost": "roost_state",
    "Safeguard": "safeguard", "Salt Cure": "salt_cure", "Smack Down": "smack_down", "Spikes": "spikes",
    "Stealth Rock": "stealth_rock", "Sticky Web": "sticky_web", "Toxic Spikes": "toxic_spikes", "Syrup Bomb": "syrup_bomb",
    "Tailwind": "tailwind", "Taunt": "taunt", "Throat Chop": "throat_chop", "Torment": "torment", "Wish": "wish",
}
EXTRA = {  # 상태 외에 기술 자체가 더 하는 일
    "Roost": "최대HP 1/2 회복 후 그 턴 비행 타입을 잃음(heal은 기술 효과 표)",
    "Salt Cure": "맞힌 상대에게 소금절임 상태(데미지 기술)",
    "Smack Down": "맞힌 상대를 땅에 붙게 함(데미지 기술)",
    "Syrup Bomb": "맞힌 상대에게 4턴간 매 턴 스피드 -1(데미지 기술)",
    "Throat Chop": "맞히면 2턴간 소리 기술 봉인(데미지 기술)",
    "Glaive Rush": "사용 후 다음 자신의 행동까지 받는 데미지 2배, 필중 상태(데미지 기술)",
    "Charge": "특방 +1과 함께 다음 전기 기술 위력 2배",
    "Wish": "사용 다음 턴 종료 시 그 자리 포켓몬을 사용자 최대HP 1/2 회복",
}
STRUGGLE = M("Struggle", "forced_move",
             "사용 가능한 기술이 하나도 없을 때(모든 기술의 PP가 0이거나 사용 불가) 자동으로 나가는 기술. 타입 없음(???), 필중, 위력 50 물리·접촉. "
             "반동은 준 데미지가 아니라 사용자 최대HP의 1/4(반올림, 최소 1). 락 특성(바위머리)이나 매직가드로도 막을 수 없음",
             used_when="no_usable_move", typeless=True, accuracy="always", power=50, category="physical",
             recoil=dict(basis="user_max_hp", frac=0.25, round="nearest", min=1),
             not_prevented_by=["Rock Head", "Magic Guard"], always_available=True,
             not_in_game_move=True, phase_no=3)
RULES4 = [STRUGGLE]
RULES4 += [M(mv, "sets_state", EXTRA.get(mv), state=code, phase_no=10) for mv, code in SETS_STATE.items()]

# 던지기(Fling): 지닌 도구에 따라 위력/추가 효과 (챔피언스 사용 가능 도구만)
try:
    items = json.load(open(os.path.join(HERE, "cache_sd_items.json"), encoding="utf-8"))
    champ = set(json.load(open(os.path.join(HERE, "champ_items_effective.json"), encoding="utf-8")))
    table, extra = {}, {}
    for k in champ:
        f = items.get(k, {}).get("fling")
        if f:
            table[items[k]["name"]] = f.get("basePower")
            e = {x: f[x] for x in ("status", "volatileStatus") if x in f}
            if e:
                extra[items[k]["name"]] = e
    RULES4.append(M("Fling", "power_formula", "던진 도구의 Fling 위력으로 공격하고 그 도구는 소모됨. 도구가 없거나 던질 수 없으면 실패",
                    formula="item_fling_power", table=table, effects_by_item=extra, consumes_item=True,
                    fails_if="no_item|item_unthrowable|klutz|embargo|magic_room", phase_no=6))
except FileNotFoundError:
    pass
