"""챔피언스에서 쓰이는 특성 215개의 효과를 수치 행으로 정리 (Showdown 9세대 설명문 기준, 수작업).

행 형식: R(hook, kind, value, code, target, chance, note, **cond)
  hook   : 효과가 끼어드는 시점
           switch_in / switch_out / turn_end / before_move
           modify_bp(자신 기술 위력) / modify_atk(자신 공격 스탯) / modify_def(자신 방어 스탯)
           modify_dmg_dealt(최종 가한 데미지) / modify_dmg_taken(최종 받는 데미지)
           modify_spe / modify_acc(자신 기술 명중) / modify_evasion(상대 기술 명중에 곱함)
           modify_priority / modify_move_type / modify_crit / modify_stab
           on_hit_taken / on_hit_dealt / on_ko / on_faint / on_stat_drop / on_flinch / on_crit_taken
           on_damage_taken_hp / on_item_use / on_status / on_foe_stat_rise
           immunity(무효/흡수) / passive(상시)
  kind   : mult(배율) / stat_stage(code=스탯, value=단계) / heal_frac / damage_frac(최대HP 비율)
           status(code=brn/par/slp/psn/tox/frz, chance) / volatile(code) / cure_status
           immune(code) / absorb(code=타입, value=회복 비율) / set_weather / set_terrain(value=턴)
           add_priority / crit_stage / always_crit / set_stab / ignore(code) / trap / special(code) / info / none
  target : self / attacker(나를 때린 상대) / foe / ally / foe_side / all
  cond   : JSON 조건. move_type, move_flag, move_category, bp_max, hp_frac_max, hp_full, weather, terrain,
           status_any, super_effective, contact, is_crit, moves_last 등
  weather code: sun/rain/sand/snow, terrain code: electric/grassy/psychic/misty"""


def R(hook, kind, value=None, code=None, target=None, chance=100, note=None, **cond):
    return dict(hook=hook, kind=kind, value=value, code=code, target=target, chance=chance, note=note, cond=cond or None)


def contact_status(code, chance=30):
    return R("on_hit_taken", "status", code=code, target="attacker", chance=chance, contact=True)


def weather_speed(w):
    return R("modify_spe", "mult", 2, weather=w)


def pinch(t):
    return R("modify_atk", "mult", 1.5, move_type=t, hp_frac_max=0.3333)


def absorb(t, heal=0.25):
    return R("immunity", "absorb", heal, code=t)


def absorb_stat(t, stat, n=1):
    return [R("immunity", "immune", code=f"type:{t}"), R("on_hit_taken", "stat_stage", n, code=stat, target="self", move_type=t)]


def convert(t, bp=1.2):
    return [R("modify_move_type", "special", code=f"Normal>{t}", note="Normal 기술이 타입 변환"),
            R("modify_bp", "mult", bp, converted_move=True)]


def keen_eye():
    return [R("on_stat_drop", "immune", code="acc", note="상대가 명중 단계를 낮추지 못함"),
            R("passive", "ignore", code="foe_evasion_stages")]


def no_status(code):
    return R("immunity", "immune", code=f"status:{code}", note="걸리지 않음(이미 걸린 상태도 치료)")


def no_intimidate():
    return R("immunity", "immune", code="ability:intimidate")


def stat_lock(stat=None):
    return R("on_stat_drop", "immune", code=stat or "all", note="상대에 의한 능력 하락 방지")


def ds(frac, w):
    return R("turn_end", "heal_frac", frac, target="self", weather=w)


ABILITIES = {
    "Stench": [R("on_hit_dealt", "volatile", code="flinch", target="foe", chance=10, note="풀죽음 확률이 없는 기술에 한정")],
    "Drizzle": [R("switch_in", "set_weather", 5, code="rain")],
    "Speed Boost": [R("turn_end", "stat_stage", 1, code="spe", target="self")],
    "Battle Armor": [R("immunity", "immune", code="crit")],
    "Sturdy": [R("immunity", "immune", code="ohko"), R("modify_dmg_taken", "special", code="survive_at_1hp", hp_full=True)],
    "Damp": [R("passive", "immune", code="flag:explosive", target="all", note="자폭/대폭발/미스트버스트/Mind Blown/Aftermath 불발")],
    "Limber": [no_status("par")],
    "Sand Veil": [R("modify_evasion", "mult", 0.8, weather="sand"), R("immunity", "immune", code="weather_damage:sand")],
    "Static": [contact_status("par")],
    "Volt Absorb": [absorb("Electric")],
    "Water Absorb": [absorb("Water")],
    "Oblivious": [R("immunity", "immune", code="volatile:attract"), R("immunity", "immune", code="volatile:taunt"), no_intimidate()],
    "Cloud Nine": [R("passive", "special", code="negate_weather", target="all")],
    "Compound Eyes": [R("modify_acc", "mult", 1.3)],
    "Insomnia": [no_status("slp")],
    "Immunity": [no_status("psn"), no_status("tox")],
    "Flash Fire": [R("immunity", "absorb", 0, code="Fire", note="불꽃 무효, 이후 자신의 불꽃 기술 강화"),
                   R("modify_atk", "mult", 1.5, move_type="Fire", flash_fire_active=True)],
    "Shield Dust": [R("immunity", "immune", code="secondary_effects")],
    "Own Tempo": [R("immunity", "immune", code="volatile:confusion"), no_intimidate()],
    "Suction Cups": [R("immunity", "immune", code="forced_switch")],
    "Intimidate": [R("switch_in", "stat_stage", -1, code="atk", target="foe")],
    "Shadow Tag": [R("passive", "trap", target="foe", note="고스트타입/먼저 교체 불가 해제 도구/같은 특성은 예외")],
    "Rough Skin": [R("on_hit_taken", "damage_frac", 0.125, target="attacker", contact=True)],
    "Levitate": [R("immunity", "immune", code="type:Ground"), R("passive", "immune", code="ground_hazards")],
    "Effect Spore": [R("on_hit_taken", "status", code="random:slp|par|psn", target="attacker", chance=30, contact=True,
                       note="풀타입/방진 상대 제외")],
    "Synchronize": [R("on_status", "special", code="reflect_status:brn|par|psn|tox", target="attacker")],
    "Clear Body": [stat_lock()],
    "Natural Cure": [R("switch_out", "cure_status", target="self")],
    "Lightning Rod": absorb_stat("Electric", "spa") + [R("passive", "special", code="redirect:Electric")],
    "Swift Swim": [weather_speed("rain")],
    "Chlorophyll": [weather_speed("sun")],
    "Illuminate": keen_eye(),
    "Trace": [R("switch_in", "special", code="copy_foe_ability")],
    "Huge Power": [R("modify_atk", "mult", 2, move_category="physical")],
    "Poison Point": [contact_status("psn")],
    "Inner Focus": [R("immunity", "immune", code="volatile:flinch"), no_intimidate()],
    "Magma Armor": [no_status("frz")],
    "Soundproof": [R("immunity", "immune", code="flag:sound")],
    "Rain Dish": [ds(0.0625, "rain")],
    "Sand Stream": [R("switch_in", "set_weather", 5, code="sand")],
    "Pressure": [R("passive", "special", code="extra_pp_cost", value=1)],
    "Thick Fat": [R("modify_dmg_taken", "mult", 0.5, move_type="Fire"), R("modify_dmg_taken", "mult", 0.5, move_type="Ice")],
    "Early Bird": [R("passive", "special", code="sleep_counter_x2")],
    "Flame Body": [contact_status("brn")],
    "Run Away": [R("passive", "none", note="배틀 효과 없음")],
    "Keen Eye": keen_eye(),
    "Hyper Cutter": [stat_lock("atk")],
    "Pickup": [R("turn_end", "special", code="pickup_item")],
    "Hustle": [R("modify_atk", "mult", 1.5, move_category="physical"), R("modify_acc", "mult", 0.8, move_category="physical")],
    "Cute Charm": [R("on_hit_taken", "volatile", code="attract", target="attacker", chance=30, contact=True, opposite_gender=True)],
    "Plus": [R("modify_atk", "mult", 1.5, move_category="special", ally_ability="Plus|Minus", note="더블에서만")],
    "Minus": [R("modify_atk", "mult", 1.5, move_category="special", ally_ability="Plus|Minus", note="더블에서만")],
    "Forecast": [R("passive", "special", code="castform_forecast", weather_types="sun:Fire|rain:Water|snow:Ice", species="Castform")],
    "Sticky Hold": [R("immunity", "immune", code="item_removal")],
    "Shed Skin": [R("turn_end", "cure_status", target="self", chance=33)],
    "Guts": [R("modify_atk", "mult", 1.5, move_category="physical", status_any=True), R("passive", "ignore", code="burn_attack_drop")],
    "Marvel Scale": [R("modify_def", "mult", 1.5, move_category="physical", status_any=True)],
    "Liquid Ooze": [R("on_hit_taken", "special", code="invert_drain", target="attacker")],
    "Overgrow": [pinch("Grass")],
    "Blaze": [pinch("Fire")],
    "Torrent": [pinch("Water")],
    "Swarm": [pinch("Bug")],
    "Rock Head": [R("immunity", "immune", code="recoil")],
    "Drought": [R("switch_in", "set_weather", 5, code="sun")],
    "Vital Spirit": [no_status("slp")],
    "White Smoke": [stat_lock()],
    "Pure Power": [R("modify_atk", "mult", 2, move_category="physical")],
    "Shell Armor": [R("immunity", "immune", code="crit")],
    "Tangled Feet": [R("modify_evasion", "mult", 0.5, confused=True)],
    "Motor Drive": absorb_stat("Electric", "spe"),
    "Rivalry": [R("modify_bp", "mult", 1.25, same_gender=True), R("modify_bp", "mult", 0.75, opposite_gender=True)],
    "Steadfast": [R("on_flinch", "stat_stage", 1, code="spe", target="self")],
    "Snow Cloak": [R("modify_evasion", "mult", 0.8, weather="snow")],
    "Gluttony": [R("passive", "special", code="berry_threshold", value=0.5)],
    "Anger Point": [R("on_crit_taken", "stat_stage", 12, code="atk", target="self", note="최대(+6)까지")],
    "Unburden": [R("modify_spe", "mult", 2, item_lost=True)],
    "Heatproof": [R("modify_dmg_taken", "mult", 0.5, move_type="Fire"), R("passive", "special", code="burn_damage_mult", value=0.5)],
    "Dry Skin": [absorb("Water"), R("modify_dmg_taken", "mult", 1.25, move_type="Fire"),
                 R("turn_end", "heal_frac", 0.125, target="self", weather="rain"),
                 R("turn_end", "damage_frac", 0.125, target="self", weather="sun")],
    "Iron Fist": [R("modify_bp", "mult", 1.2, move_flag="punch")],
    "Poison Heal": [R("turn_end", "heal_frac", 0.125, target="self", status="psn|tox", note="독 데미지 대신 회복")],
    "Adaptability": [R("modify_stab", "set_stab", 2.0)],
    "Skill Link": [R("passive", "special", code="multihit_always_max")],
    "Hydration": [R("turn_end", "cure_status", target="self", weather="rain")],
    "Solar Power": [R("modify_atk", "mult", 1.5, move_category="special", weather="sun"),
                    R("turn_end", "damage_frac", 0.125, target="self", weather="sun")],
    "Quick Feet": [R("modify_spe", "mult", 1.5, status_any=True), R("passive", "ignore", code="par_speed_drop")],
    "Sniper": [R("modify_dmg_dealt", "mult", 1.5, is_crit=True)],
    "Magic Guard": [R("immunity", "immune", code="indirect_damage")],
    "No Guard": [R("passive", "special", code="always_hit", target="all", ignores_invulnerability=True,
                   note="자신이 쓰거나 자신이 맞는 모든 기술이 필중이며, 공중날기·구멍파기 등 회피율 최대 상태도 무시하고 명중. 방어(Protect) 기술은 못 뚫음")],
    "Stall": [R("modify_priority", "special", code="move_last_in_bracket")],
    "Technician": [R("modify_bp", "mult", 1.5, bp_max=60)],
    "Leaf Guard": [R("immunity", "immune", code="status:any", weather="sun")],
    "Klutz": [R("passive", "special", code="item_disabled")],
    "Mold Breaker": [R("passive", "ignore", code="foe_abilities")],
    "Super Luck": [R("modify_crit", "crit_stage", 1)],
    "Aftermath": [R("on_faint", "damage_frac", 0.25, target="attacker", contact=True, note="Damp 있으면 불발")],
    "Anticipation": [R("switch_in", "info", code="foe_supereffective_move")],
    "Forewarn": [R("switch_in", "info", code="foe_strongest_move")],
    "Unaware": [R("passive", "ignore", code="foe_stat_stages", note="공격 시 상대 방어/회피, 피격 시 상대 공격/명중 단계 무시")],
    "Filter": [R("modify_dmg_taken", "mult", 0.75, super_effective=True)],
    "Scrappy": [R("passive", "ignore", code="ghost_immunity", note="노말/격투가 고스트에 적중"), no_intimidate()],
    "Ice Body": [ds(0.0625, "snow")],
    "Solid Rock": [R("modify_dmg_taken", "mult", 0.75, super_effective=True)],
    "Snow Warning": [R("switch_in", "set_weather", 5, code="snow")],
    "Frisk": [R("switch_in", "info", code="foe_item")],
    "Reckless": [R("modify_bp", "mult", 1.2, has_recoil=True)],
    "Pickpocket": [R("on_hit_taken", "special", code="steal_item", target="attacker", contact=True, self_item_empty=True)],
    "Sheer Force": [R("modify_bp", "mult", 1.3, has_secondary=True), R("passive", "special", code="remove_secondary_effects")],
    "Contrary": [R("passive", "special", code="invert_stat_changes")],
    "Unnerve": [R("passive", "special", code="foe_cannot_eat_berries", target="foe")],
    "Defiant": [R("on_stat_drop", "stat_stage", 2, code="atk", target="self", by_foe=True, note="낮아진 능력 하나당")],
    "Cursed Body": [R("on_hit_taken", "volatile", code="disable", target="attacker", chance=30)],
    "Healer": [R("turn_end", "cure_status", target="ally", chance=30, note="더블에서만")],
    "Friend Guard": [R("modify_dmg_taken", "mult", 0.75, target_side="ally", note="더블에서만")],
    "Weak Armor": [R("on_hit_taken", "stat_stage", -1, code="def", target="self", move_category="physical"),
                   R("on_hit_taken", "stat_stage", 2, code="spe", target="self", move_category="physical")],
    "Heavy Metal": [R("passive", "special", code="weight_mult", value=2)],
    "Light Metal": [R("passive", "special", code="weight_mult", value=0.5)],
    "Multiscale": [R("modify_dmg_taken", "mult", 0.5, hp_full=True)],
    "Harvest": [R("turn_end", "special", code="restore_berry", chance=50),
                R("turn_end", "special", code="restore_berry", chance=100, weather="sun")],
    "Telepathy": [R("immunity", "immune", code="ally_damage", note="더블에서만")],
    "Moody": [R("turn_end", "special", code="random_stat_change", up=2, down=1, excluded="acc|eva",
                    note="무작위 능력 +2단계, 다른 무작위 능력 -1단계 (명중/회피 제외)")],
    "Overcoat": [R("immunity", "immune", code="flag:powder"), R("immunity", "immune", code="weather_damage:sand")],
    "Poison Touch": [R("on_hit_dealt", "status", code="psn", target="foe", chance=30, contact=True)],
    "Regenerator": [R("switch_out", "heal_frac", 0.3333, target="self")],
    "Big Pecks": [stat_lock("def")],
    "Sand Rush": [weather_speed("sand"), R("immunity", "immune", code="weather_damage:sand")],
    "Analytic": [R("modify_bp", "mult", 1.3, moves_last=True)],
    "Illusion": [R("switch_in", "special", code="illusion", note="마지막 파티 포켓몬으로 위장, 피격 시 해제")],
    "Imposter": [R("switch_in", "special", code="transform")],
    "Infiltrator": [R("passive", "ignore", code="substitute_and_screens")],
    "Mummy": [R("on_hit_taken", "special", code="set_attacker_ability:Mummy", target="attacker", contact=True)],
    "Moxie": [R("on_ko", "stat_stage", 1, code="atk", target="self")],
    "Justified": [R("on_hit_taken", "stat_stage", 1, code="atk", target="self", move_type="Dark")],
    "Rattled": [R("on_hit_taken", "stat_stage", 1, code="spe", target="self", move_type="Bug|Dark|Ghost"),
                R("on_hit_taken", "stat_stage", 1, code="spe", target="self", intimidated=True)],
    "Magic Bounce": [R("immunity", "special", code="reflect_status_moves")],
    "Sap Sipper": absorb_stat("Grass", "atk"),
    "Prankster": [R("modify_priority", "add_priority", 1, move_category="status", note="악타입 상대에게는 무효")],
    "Sand Force": [R("modify_bp", "mult", 1.3, weather="sand", move_type="Ground|Rock|Steel"), R("immunity", "immune", code="weather_damage:sand")],
    "Aroma Veil": [R("immunity", "immune", code="volatile:attract|disable|encore|heal_block|taunt|torment", target="ally")],
    "Flower Veil": [R("immunity", "immune", code="stat_drop|status", target="ally", ally_type="Grass")],
    "Cheek Pouch": [R("on_item_use", "heal_frac", 0.3333, target="self", item_class="berry")],
    "Protean": [R("modify_move_type", "special", code="change_own_type_once", note="사용 기술 타입으로 변화(교체 후 1회)")],
    "Fur Coat": [R("modify_def", "mult", 2, move_category="physical")],
    "Magician": [R("on_hit_dealt", "special", code="steal_item", target="foe", self_item_empty=True)],
    "Bulletproof": [R("immunity", "immune", code="flag:bullet")],
    "Competitive": [R("on_stat_drop", "stat_stage", 2, code="spa", target="self", by_foe=True, note="낮아진 능력 하나당")],
    "Strong Jaw": [R("modify_bp", "mult", 1.5, move_flag="bite")],
    "Refrigerate": convert("Ice"),
    "Sweet Veil": [R("immunity", "immune", code="status:slp", target="ally")],
    "Stance Change": [R("before_move", "special", code="aegislash_stance")],
    "Gale Wings": [R("modify_priority", "add_priority", 1, move_type="Flying", hp_full=True)],
    "Mega Launcher": [R("modify_bp", "mult", 1.5, move_flag="pulse")],
    "Grass Pelt": [R("modify_def", "mult", 1.5, move_category="physical", terrain="grassy")],
    "Symbiosis": [R("passive", "special", code="pass_item_to_ally", note="더블에서만")],
    "Tough Claws": [R("modify_bp", "mult", 1.3, contact=True)],
    "Pixilate": convert("Fairy"),
    "Gooey": [R("on_hit_taken", "stat_stage", -1, code="spe", target="attacker", contact=True)],
    "Aerilate": convert("Flying"),
    "Parental Bond": [R("modify_bp", "special", code="extra_hit", value=0.25, hits=2, excluded="multihit|multi_target|two_turn|explosion",
                    note="2번째 타격 위력 1/4")],
    "Fairy Aura": [R("modify_bp", "mult", 1.33, move_type="Fairy", target_side="all", note="필드의 모든 포켓몬의 페어리 기술")],
    "Stamina": [R("on_hit_taken", "stat_stage", 1, code="def", target="self")],
    "Emergency Exit": [R("on_damage_taken_hp", "special", code="switch_out", crosses_half_hp=True)],
    "Merciless": [R("modify_crit", "always_crit", target_status="psn|tox")],
    "Stakeout": [R("modify_atk", "mult", 2, target_switched_in=True)],
    "Water Bubble": [R("modify_atk", "mult", 2, move_type="Water"), R("modify_dmg_taken", "mult", 0.5, move_type="Fire"), no_status("brn")],
    "Berserk": [R("on_damage_taken_hp", "stat_stage", 1, code="spa", target="self", crosses_half_hp=True)],
    "Slush Rush": [weather_speed("snow")],
    "Long Reach": [R("passive", "special", code="no_contact")],
    "Liquid Voice": [R("modify_move_type", "special", code="sound>Water")],
    "Surge Surfer": [R("modify_spe", "mult", 2, terrain="electric")],
    "Disguise": [R("immunity", "special", code="first_hit_zero_damage", value=0.125, species="Mimikyu",
                    note="첫 피격 데미지 0, 가면이 깨지며 value=최대HP 비율만큼 손실. 이후 Busted 폼")],
    "Corrosion": [R("passive", "ignore", code="poison_immunity_types")],
    "Queenly Majesty": [R("immunity", "immune", code="priority_moves", target="all")],
    "Innards Out": [R("on_faint", "damage_frac", code="equal_to_last_damage", target="attacker")],
    "Fluffy": [R("modify_dmg_taken", "mult", 0.5, contact=True), R("modify_dmg_taken", "mult", 2.0, move_type="Fire")],
    "Receiver": [R("passive", "special", code="copy_fainted_ally_ability", note="더블에서만")],
    "Electric Surge": [R("switch_in", "set_terrain", 5, code="electric")],
    "Psychic Surge": [R("switch_in", "set_terrain", 5, code="psychic")],
    "Grassy Surge": [R("switch_in", "set_terrain", 5, code="grassy")],
    "Libero": [R("modify_move_type", "special", code="change_own_type_once")],
    "Mirror Armor": [R("on_stat_drop", "special", code="reflect_to_source")],
    "Stalwart": [R("passive", "ignore", code="move_redirection")],
    "Punk Rock": [R("modify_bp", "mult", 1.3, move_flag="sound"), R("modify_dmg_taken", "mult", 0.5, move_flag="sound")],
    "Sand Spit": [R("on_hit_taken", "set_weather", 5, code="sand")],
    "Ripen": [R("passive", "special", code="berry_effect_x2")],
    "Mimicry": [R("passive", "special", code="type_follows_terrain", terrain_types="electric:Electric|grassy:Grass|misty:Fairy|psychic:Psychic")],
    "Screen Cleaner": [R("switch_in", "special", code="remove_screens_both_sides")],
    "Steely Spirit": [R("modify_bp", "mult", 1.5, move_type="Steel", target_side="self_and_ally")],
    "Wandering Spirit": [R("on_hit_taken", "special", code="swap_ability", target="attacker", contact=True)],
    "Hunger Switch": [R("turn_end", "special", code="morpeko_form_toggle")],
    "Quick Draw": [R("modify_priority", "special", code="first_in_bracket", chance=30, move_category="physical|special")],
    "Unseen Fist": [R("passive", "ignore", code="protect", contact=True)],
    "Curious Medicine": [R("switch_in", "special", code="reset_ally_stat_stages", note="더블에서만")],
    "Seed Sower": [R("on_hit_taken", "set_terrain", 5, code="grassy")],
    "Thermal Exchange": [R("on_hit_taken", "stat_stage", 1, code="atk", target="self", move_type="Fire"), no_status("brn")],
    "Purifying Salt": [R("immunity", "immune", code="status:any"), R("modify_dmg_taken", "mult", 0.5, move_type="Ghost")],
    "Guard Dog": [R("immunity", "stat_stage", 1, code="atk", target="self", intimidated=True, note="위협 대신 공격 +1"),
                  R("immunity", "immune", code="forced_switch")],
    "Zero to Hero": [R("switch_out", "special", code="palafin_hero_form")],
    "Electromorphosis": [R("on_hit_taken", "special", code="charge_next_electric_x2", value=2.0, move_type="Electric",
                         note="피격 후 다음 전기 기술 위력 x2 (1회)")],
    "Good as Gold": [R("immunity", "immune", code="move_class:status", note="상대가 쓰는 변화 기술 무효")],
    "Opportunist": [R("on_foe_stat_rise", "special", code="copy_stat_boost")],
    "Cud Chew": [R("turn_end", "special", code="reeat_berry_next_turn")],
    "Sharpness": [R("modify_bp", "mult", 1.5, move_flag="slicing")],
    "Supreme Overlord": [R("modify_bp", "special", code="per_fainted_ally_mult", value=0.1, max_count=5, max_mult=1.5,
                         note="위력 x(1+0.1×쓰러진 아군 수), 아군 수는 최대 5까지만 인정(최대 x1.5)")],
    "Toxic Debris": [R("on_hit_taken", "special", code="set_toxic_spikes", value=1, target="foe_side", move_category="physical",
                    max_layers=2, note="피격 시 독압정 1겹 설치, 최대 2겹")],
    "Armor Tail": [R("immunity", "immune", code="priority_moves", target="all")],
    "Earth Eater": [absorb("Ground")],
    "Supersweet Syrup": [R("switch_in", "stat_stage", -1, code="eva", target="foe", note="배틀당 1회")],
    "Hospitality": [R("switch_in", "heal_frac", 0.25, target="ally", note="더블에서만")],
    "Piercing Drill": [R("passive", "ignore", code="protect", contact=True), R("modify_dmg_dealt", "mult", 0.25, contact=True, target_protected=True)],
    "Dragonize": convert("Dragon"),
    "Mega Sol": [R("passive", "special", code="treat_weather_as:sun", note="자신의 기술은 쾌청 상태로 취급")],
    "Spicy Spray": [R("on_hit_taken", "status", code="brn", target="attacker")],
    "Eelevate": [R("immunity", "immune", code="type:Ground"), R("passive", "immune", code="ground_hazards"),
                 R("on_ko", "stat_stage", 1, code="highest_stat", target="self")],
    "Fire Mane": [R("modify_atk", "mult", 1.5, move_type="Fire")],
    "Aura Guard": [R("modify_dmg_taken", "mult", 0.5, contact=True)],
}
