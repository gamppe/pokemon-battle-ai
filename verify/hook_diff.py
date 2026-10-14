"""특성/도구 구현 누락 후보 목록: Showdown 에 이벤트 핸들러가 있는데 우리 쪽에 구현 흔적(DB 효과 행, 또는 엔진 코드의 이름 언급)이 없는 항목.
메타(스냅샷 33) 사용 가중치 순. 사용: python -m verify.hook_diff -> verify/out/hook_diff.csv"""
import csv
import json
import re

from ai.gamedata import connect, norm

ENGINE_FILES = ["ai/battle.py", "ai/damage_calc.py", "ai/policy.py", "ai/observe.py"]


# Showdown 핸들러 -> 우리 훅 분류 (여러 개면 그중 하나라도 있으면 구현된 것으로 본다)
MAP = {
    "onStart": {"switch_in"}, "onSwitchIn": {"switch_in"}, "onEnd": {"switch_out", "turn_end"}, "onSwitchOut": {"switch_out"},
    "onResidual": {"turn_end"}, "onDamagingHit": {"on_hit_taken", "on_crit_taken", "on_flinch"}, "onSourceDamagingHit": {"on_hit_dealt"},
    "onAfterMoveSecondarySelf": {"on_hit_dealt", "on_ko"}, "onAfterMoveSecondary": {"on_hit_taken", "on_hit_dealt"},
    "onSourceAfterFaint": {"on_ko"}, "onFaint": {"on_faint"}, "onAnyFaint": {"on_faint"},
    "onTryHit": {"immunity"}, "onImmunity": {"immunity"}, "onAllyTryHitSide": {"immunity"},
    "onModifyAtk": {"modify_atk", "modify_atk_foe"}, "onModifySpA": {"modify_atk", "modify_atk_foe"},
    "onModifyDef": {"modify_def"}, "onModifySpD": {"modify_def"}, "onBasePower": {"modify_bp", "modify_bp_foe"},
    "onModifySpe": {"modify_spe"}, "onModifyPriority": {"modify_priority"}, "onFractionalPriority": {"modify_priority"},
    "onModifyType": {"modify_move_type"}, "onModifyMove": {"modify_move_type", "passive", "modify_crit", "modify_acc"},
    "onModifyCritRatio": {"modify_crit"}, "onModifyAccuracy": {"modify_acc", "modify_evasion"},
    "onSourceModifyAccuracy": {"modify_acc", "modify_evasion"}, "onModifyDamage": {"modify_dmg_dealt", "modify_dmg_taken"},
    "onSourceModifyDamage": {"modify_dmg_taken"}, "onFoeModifyDamage": {"modify_dmg_taken"}, "onAnyModifyDamage": {"modify_dmg_taken"},
    "onModifySTAB": {"modify_stab"}, "onTryBoost": {"on_stat_drop", "on_foe_stat_rise"}, "onAfterBoost": {"on_stat_drop", "on_foe_stat_rise"},
    "onSetStatus": {"on_status", "immunity"}, "onUpdate": {"on_status", "passive", "switch_in", "turn_end"},
    "onDamage": {"on_damage_taken_hp"}, "onTryHeal": {"passive"}, "onEat": {"on_item_use"}, "onAfterUseItem": {"on_item_use"},
    "onWeatherModifyDamage": {"modify_dmg_dealt", "passive"}, "onModifyWeight": {"passive"}, "onFoeTryMove": {"immunity"},
    "onAllyBasePower": {"modify_bp"}, "onAnyBasePower": {"modify_bp"}, "onAnyAccuracy": {"modify_acc"},
}


def main():
    sd = json.load(open("verify/out/sd_dump.json", encoding="utf-8"))
    conn = connect()
    cur = conn.cursor()
    lits = set()
    for f in ENGINE_FILES:
        for m in re.finditer(r"""["']([A-Za-z][A-Za-z0-9 _'-]{1,39})["']""", open(f, encoding="utf-8").read()):
            lits.add(norm(m.group(1)))
    out = []
    for kind, table, mtable, col in (("특성", "ability", "meta_ability", "ability_key"), ("도구", "item", "meta_item", "item_key")):
        cur.execute(f"select a.name_en n, e.hook h from {table} a join {table}_effect e on e.{table}_id=a.{table}_id")
        mine = {}
        for r in cur.fetchall():
            mine.setdefault(norm(r["n"]), set()).add(r["h"])
        cur.execute(f"select {col} k, sum(weight) w from {mtable} where snapshot_id=33 group by {col}")
        use = {norm(r["k"]): float(r["w"]) for r in cur.fetchall()}
        for k, s in sd["abilities" if kind == "특성" else "items"].items():
            if k not in use:
                continue
            hs = [h for h in s["hooks"] + s["cond"] if not re.search(r"(Priority|Order|SubOrder)$", h) and h != "onTakeItem"]
            have = mine.get(k, set())
            miss = []
            for h in hs:
                base = h.split(".")[-1]
                if base not in MAP:
                    miss.append(base + "(?)")
                elif not (MAP[base] & have):
                    miss.append(base)
            if miss:
                out.append((kind, s["name"], "코드 언급 있음" if k in lits else "구현 흔적 없음", " ".join(sorted(set(miss))), " ".join(sorted(have)) or "-", round(use[k], 1)))
    out.sort(key=lambda r: (r[2] != "구현 흔적 없음", -r[5]))
    with open("verify/out/hook_diff.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["분류", "이름", "상태", "Showdown에만 있는 훅", "우리 훅", "메타가중치"])
        w.writerows(out)
    n0 = sum(1 for r in out if r[2] == "구현 흔적 없음")
    print(f"훅 불일치 {len(out)}건 (구현 흔적 없음 {n0}, 코드 언급 있음 {len(out) - n0})")
    for r in out[:40]:
        print(r)


if __name__ == "__main__":
    main()
