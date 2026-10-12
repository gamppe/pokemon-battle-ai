"""MySQL(pokemon DB)에서 배틀 계산에 필요한 데이터를 메모리로 읽어온다.
AI 쪽 코드는 이 모듈로만 DB에 접근한다 (Showdown 데이터는 쓰지 않음 = DB 자체를 검증/사용하기 위함)."""
import json
import os
import re

import pymysql

norm = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("’", ""))


def connect(db=None):
    return pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"),
                           password=os.environ["DB_PASSWORD"], database=db or os.environ.get("POKEMON_DB", "pokemon"),
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)


def _rows(cur, sql, args=()):
    cur.execute(sql, args)
    return cur.fetchall()


def _cond(c):
    if c is None:
        return {}
    return json.loads(c) if isinstance(c, (str, bytes)) else c


class GameData:
    """한 게임(기본 CHAMPIONS) 기준의 포켓몬/기술/특성/아이템/상태 규칙"""

    def __init__(self, conn, game="CHAMPIONS"):
        cur = conn.cursor()
        g = _rows(cur, "select game_id from game where code=%s", (game,))[0]["game_id"]
        self.game_id = g
        # 타입 상성
        self.type_chart = {(r["a"], r["d"]): float(r["m"]) for r in _rows(
            cur, """select a.name_en a, d.name_en d, e.multiplier m from type_efficacy e
                    join type a on a.type_id=e.attack_type_id join type d on d.type_id=e.defense_type_id""")}
        self.types = [r["name_en"] for r in _rows(cur, "select name_en from type")]
        self.natures = {norm(r["name_en"]): (r["plus_stat"], r["minus_stat"]) for r in _rows(
            cur, "select name_en, plus_stat, minus_stat from nature")}
        # 포켓몬
        self.pokemon = {}
        for r in _rows(cur, """select p.pokemon_id pid, p.showdown_id sid, p.name_en, p.weight_kg, p.base_hp,p.base_atk,p.base_def,p.base_spa,p.base_spd,p.base_spe,
                t1.name_en t1, t2.name_en t2 from game_pokemon gp join pokemon p using(pokemon_id)
                join type t1 on t1.type_id=p.type1_id left join type t2 on t2.type_id=p.type2_id where gp.game_id=%s""", (g,)):
            self.pokemon[r["sid"]] = dict(pid=r["pid"], name=r["name_en"], weight_hg=int(round(float(r["weight_kg"] or 0) * 10)), types=[r["t1"]] + ([r["t2"]] if r["t2"] else []),
                                          base=dict(hp=r["base_hp"], atk=r["base_atk"], def_=r["base_def"], spa=r["base_spa"],
                                                    spd=r["base_spd"], spe=r["base_spe"]), abilities={}, learn=set())
        by_pid = {v["pid"]: k for k, v in self.pokemon.items()}
        for r in _rows(cur, "select pokemon_id, slot, a.name_en from pokemon_ability pa join ability a using(ability_id) where pa.game_id=%s", (g,)):
            if r["pokemon_id"] in by_pid:
                self.pokemon[by_pid[r["pokemon_id"]]]["abilities"][r["slot"]] = r["name_en"]
        for r in _rows(cur, "select pokemon_id, m.name_en from pokemon_move pm join move m using(move_id) where pm.game_id=%s", (g,)):
            if r["pokemon_id"] in by_pid:
                self.pokemon[by_pid[r["pokemon_id"]]]["learn"].add(norm(r["name_en"]))
        # 기술 (챔피언스 덮어쓰기 반영)
        flags, over = {}, {}
        for r in _rows(cur, "select move_id, flag, game_id from move_flag where game_id in (0,%s)", (g,)):
            (over if r["game_id"] == g else flags).setdefault(r["move_id"], set()).add(r["flag"])
        rules = {}
        for r in _rows(cur, "select move_id, rule_type, params from move_rule where game_id=0"):
            rules.setdefault(r["move_id"], []).append(dict(type=r["rule_type"], params=_cond(r["params"])))
        sec = {}
        for r in _rows(cur, "select move_id, game_id from move_effect where trigger_type='secondary'"):
            sec.setdefault(r["move_id"], set()).add(r["game_id"])
        eff = {}                                   # 부가효과: 게임별 덮어쓰기가 있으면 그것만, 없으면 공통(game_id=0)
        for r in _rows(cur, "select move_id, game_id, trigger_type, applies_to, kind, code, stages, chance_pct from move_effect where game_id in (0,%s)", (g,)):
            eff.setdefault(r["move_id"], {}).setdefault(r["game_id"], []).append(r)
        self.moves = {}
        for r in _rows(cur, """select m.move_id, m.name_en, t.name_en type, ot.name_en otype, m.category, m.power, g.power_override,
                m.recoil_pct, m.drain_pct, m.extra, m.priority, m.accuracy, g.accuracy_override, m.crit_stage, m.always_crit,
                m.min_hits, m.max_hits, m.heal_pct, m.self_switch, m.force_switch, m.self_destruct, m.ohko, m.fixed_damage,
                m.target, g.target_override, g.effects_overridden from game_move g join move m using(move_id) join type t on t.type_id=m.type_id
                left join type ot on ot.type_id=g.type_override where g.game_id=%s""", (g,)):
            mid = r["move_id"]
            self.moves[norm(r["name_en"])] = dict(
                id=mid, name=r["name_en"], type=r["otype"] or r["type"], category=r["category"],
                bp=(r["power_override"] if r["power_override"] is not None else (r["power"] or 0)),
                flags=over.get(mid) or flags.get(mid, set()), rules=rules.get(mid, []),
                recoil=r["recoil_pct"], has_secondary=bool(sec.get(mid)), extra=_cond(r["extra"]),
                priority=r["priority"] or 0, accuracy=(r["accuracy_override"] if r["accuracy_override"] is not None else r["accuracy"]),
                crit_stage=r["crit_stage"] or 0, always_crit=bool(r["always_crit"]), min_hits=r["min_hits"] or 1, max_hits=r["max_hits"] or 1,
                drain=r["drain_pct"] or 0, heal=r["heal_pct"] or 0, self_switch=bool(r["self_switch"]), force_switch=bool(r["force_switch"]),
                self_destruct=bool(r["self_destruct"]), ohko=bool(r["ohko"]), fixed_damage=r["fixed_damage"],
                target=r["target_override"] or r["target"],
                effects=(eff.get(mid, {}).get(g) if r["effects_overridden"] and g in eff.get(mid, {}) else eff.get(mid, {}).get(0, [])))
        br = _rows(cur, "select params from battle_rule where rule_key='mold_breaker'")
        self.breakable = {norm(x) for x in (_cond(br[0]["params"]).get("ignores_abilities", []) if br else [])}
        # 특성/아이템 효과
        self.ability_fx = {}
        for r in _rows(cur, """select a.name_en n, e.* from ability_effect e join ability a using(ability_id)"""):
            self.ability_fx.setdefault(norm(r["n"]), []).append(self._fx(r, "ability:" + r["n"]))
        self.item_fx = {}
        for r in _rows(cur, """select i.name_en n, e.* from item_effect e join item i using(item_id)"""):
            self.item_fx.setdefault(norm(r["n"]), []).append(self._fx(r, "item:" + r["n"]))
        self.state_fx = {}
        for r in _rows(cur, """select s.code n, e.* from battle_state_effect e join battle_state s using(state_id)"""):
            self.state_fx.setdefault(r["n"], []).append(self._fx(r, "state:" + r["n"]))

    @staticmethod
    def _fx(r, label):
        return dict(label=label, hook=r["hook"], kind=r["kind"], target=r["target"], code=r["code"],
                    value=None if r["value"] is None else float(r["value"]), chance=r["chance_pct"], cond=_cond(r["cond"]), note=r["note"])
