"""챔피언스 아이템 166개 효과 수치화 (Showdown 9세대 설명문 기준, 수작업).
행 형식과 어휘는 ability_effects_data.py 상단 주석과 같고, 추가로 single_use(1회용) 필드가 있다.
메가스톤은 mega_evolution 표에서 load_item_effects.py가 자동 생성한다."""


def R(hook, kind, value=None, code=None, target=None, chance=100, note=None, single_use=False, **cond):
    return dict(hook=hook, kind=kind, value=value, code=code, target=target, chance=chance, note=note,
                single_use=single_use, cond=cond or None)


TYPE_BOOST = {  # 지닌 포켓몬의 해당 타입 기술 위력 x1.2
    "Black Belt": "Fighting", "Black Glasses": "Dark", "Charcoal": "Fire", "Dragon Fang": "Dragon",
    "Fairy Feather": "Fairy", "Hard Stone": "Rock", "Magnet": "Electric", "Metal Coat": "Steel",
    "Miracle Seed": "Grass", "Mystic Water": "Water", "Never-Melt Ice": "Ice", "Poison Barb": "Poison",
    "Sharp Beak": "Flying", "Silk Scarf": "Normal", "Silver Powder": "Bug", "Soft Sand": "Ground",
    "Spell Tag": "Ghost", "Twisted Spoon": "Psychic",
}
RESIST_BERRY = {  # 효과가 굉장한 해당 타입 기술의 데미지를 절반으로 (1회용)
    "Occa Berry": "Fire", "Passho Berry": "Water", "Wacan Berry": "Electric", "Rindo Berry": "Grass",
    "Yache Berry": "Ice", "Chople Berry": "Fighting", "Kebia Berry": "Poison", "Shuca Berry": "Ground",
    "Coba Berry": "Flying", "Payapa Berry": "Psychic", "Tanga Berry": "Bug", "Charti Berry": "Rock",
    "Kasib Berry": "Ghost", "Haban Berry": "Dragon", "Babiri Berry": "Steel", "Colbur Berry": "Dark",
    "Roseli Berry": "Fairy",
}
SEEDS = {  # 필드가 맞으면 능력 +1 (1회용)
    "Electric Seed": ("electric", "def"), "Grassy Seed": ("grassy", "def"),
    "Misty Seed": ("misty", "spd"), "Psychic Seed": ("psychic", "spd"),
}
EXTEND = {  # 지속 턴 5 -> 8
    "Damp Rock": "rain", "Heat Rock": "sun", "Icy Rock": "snow", "Smooth Rock": "sand",
}

ITEMS = {
    "Air Balloon": [R("immunity", "immune", code="type:Ground", note="맞으면 터져서 효과 사라짐"),
                    R("on_hit_taken", "special", code="pop_balloon")],
    "Aspear Berry": [R("on_status", "cure_status", code="frz", target="self", single_use=True)],
    "Cheri Berry": [R("on_status", "cure_status", code="par", target="self", single_use=True)],
    "Chesto Berry": [R("on_status", "cure_status", code="slp", target="self", single_use=True)],
    "Pecha Berry": [R("on_status", "cure_status", code="psn|tox", target="self", single_use=True)],
    "Rawst Berry": [R("on_status", "cure_status", code="brn", target="self", single_use=True)],
    "Persim Berry": [R("on_status", "cure_status", code="confusion", target="self", single_use=True)],
    "Lum Berry": [R("on_status", "cure_status", code="any|confusion", target="self", single_use=True)],
    "Mental Herb": [R("on_status", "cure_status", code="attract|disable|encore|heal_block|taunt|torment",
                      target="self", single_use=True)],
    "Chilan Berry": [R("modify_dmg_taken", "mult", 0.5, single_use=True, move_type="Normal", note="효과가 굉장하지 않아도 발동")],
    "Big Root": [R("modify_drain", "mult", 1.3, note="흡수기/아쿠아링/뿌리박기/씨뿌리기 회복량")],
    "Binding Band": [R("passive", "special", code="trap_damage_frac", value=0.1667, note="속박 기술 턴당 1/6 (기본 1/8)")],
    "Normal Gem": [R("modify_bp", "mult", 1.3, single_use=True, move_type="Normal")],
    "Bright Powder": [R("modify_evasion", "mult", 0.9)],
    "Choice Scarf": [R("modify_spe", "mult", 1.5), R("passive", "special", code="choice_lock")],
    "Eject Button": [R("on_hit_taken", "special", code="self_switch_out", single_use=True)],
    "Red Card": [R("on_hit_taken", "special", code="force_attacker_switch", target="attacker", single_use=True)],
    "Expert Belt": [R("modify_dmg_dealt", "mult", 1.2, super_effective=True)],
    "Focus Band": [R("modify_dmg_taken", "special", code="survive_at_1hp", chance=10)],
    "Focus Sash": [R("modify_dmg_taken", "special", code="survive_at_1hp", single_use=True, hp_full=True)],
    "Iron Ball": [R("modify_spe", "mult", 0.5),
                  R("passive", "special", code="grounded", note="땅에 붙은 상태: 필드(그래스/일렉트릭/미스트/사이코)와 함정(독압정 등)의 영향을 받음"),
                  R("passive", "ignore", code="ground_immunity",
                    note="비행 타입/부유 특성/에어 벌룬의 땅 기술 무효를 해제. 비행 타입 부분은 땅 기술 상성을 1배로 계산")],
    "King's Rock": [R("on_hit_dealt", "volatile", code="flinch", target="foe", chance=10, note="풀죽음 확률이 없는 기술에 한정")],
    "Leek": [R("modify_crit", "crit_stage", 2, species="Farfetch'd|Sirfetch'd")],
    "Leftovers": [R("turn_end", "heal_frac", 0.0625, target="self")],
    "Leppa Berry": [R("passive", "special", code="restore_pp", value=10, single_use=True)],
    "Life Orb": [R("modify_dmg_dealt", "mult", 1.3), R("on_hit_dealt", "damage_frac", 0.1, target="self", note="공격 후 최대HP 1/10 손실")],
    "Light Ball": [R("modify_atk", "mult", 2, species="Pikachu", note="공격/특공 모두")],
    "Light Clay": [R("passive", "special", code="extend_screens", value=8)],
    "Metronome": [R("modify_dmg_dealt", "special", code="consecutive_use_boost", value=0.2, max_mult=2.0, max_stacks=5,
                    note="같은 기술을 연속 사용할 때마다 +0.2, 5회 누적 시 최대 x2.0")],
    "Muscle Band": [R("modify_bp", "mult", 1.1, move_category="physical")],
    "Wise Glasses": [R("modify_bp", "mult", 1.1, move_category="special")],
    "Oran Berry": [R("on_damage_taken_hp", "heal_fixed", 10, target="self", single_use=True, hp_frac_max=0.5)],
    "Sitrus Berry": [R("on_damage_taken_hp", "heal_frac", 0.25, target="self", single_use=True, hp_frac_max=0.5)],
    "Quick Claw": [R("modify_priority", "special", code="first_in_bracket", chance=20)],
    "Rocky Helmet": [R("on_hit_taken", "damage_frac", 0.1667, target="attacker", contact=True)],
    "Scope Lens": [R("modify_crit", "crit_stage", 1)],
    "Shed Shell": [R("immunity", "immune", code="trapped")],
    "Shell Bell": [R("on_hit_dealt", "heal_dmg_frac", 0.125, target="self", note="가한 데미지의 1/8 회복")],
    "Terrain Extender": [R("passive", "special", code="extend_terrain", value=8)],
    "White Herb": [R("on_stat_drop", "special", code="reset_negative_stages", single_use=True)],
    "Wide Lens": [R("modify_acc", "mult", 1.1)],
    "Zoom Lens": [R("modify_acc", "mult", 1.2, moves_after_target=True)],
}
for n, t in TYPE_BOOST.items():
    ITEMS[n] = [R("modify_bp", "mult", 1.2, move_type=t)]
for n, t in RESIST_BERRY.items():
    ITEMS[n] = [R("modify_dmg_taken", "mult", 0.5, single_use=True, move_type=t, super_effective=True,
                  note="Ripen 특성이면 x0.25")]
for n, (terr, stat) in SEEDS.items():
    ITEMS[n] = [R("switch_in", "stat_stage", 1, code=stat, target="self", single_use=True, terrain=terr)]
for n, w in EXTEND.items():
    ITEMS[n] = [R("passive", "special", code=f"extend_weather:{w}", value=8)]
