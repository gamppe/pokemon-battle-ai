"""메타 통계(meta_* 테이블)에서 포켓몬 세트(특성/도구/성격+SP/기술 4개)를 뽑는다.
- 특성/도구/스프레드/기술은 서로 독립인 주변분포로 취급한다 (Smogon 통계에는 조합 상관이 없다). [근사]
- snapshot 은 (format, 기간, 레이팅 컷오프) 한 묶음. 컷오프가 곧 "티어" 파라미터다."""
import random

from .gamedata import norm

SP_KEYS = ("hp", "atk", "def", "spa", "spd", "spe")


class Meta:
    def __init__(self, conn, data, snapshot_id):
        self.data, self.snapshot_id = data, snapshot_id
        cur = conn.cursor()
        cur.execute("select * from meta_snapshot where snapshot_id=%s", (snapshot_id,))
        self.info = cur.fetchone()
        sid_by_pid = {v["pid"]: k for k, v in data.pokemon.items()}
        move_by_id = {m["id"]: k for k, m in data.moves.items()}
        cur.execute("select pokemon_id, usage_pct from meta_pokemon where snapshot_id=%s and pokemon_id is not null", (snapshot_id,))
        self.usage = {sid_by_pid[r["pokemon_id"]]: float(r["usage_pct"]) for r in cur.fetchall() if r["pokemon_id"] in sid_by_pid}
        cur.execute("""select p.pokemon_id, a.name_en n, x.prob from meta_ability x join ability a using(ability_id)
                       join meta_pokemon p on p.snapshot_id=x.snapshot_id and p.pokemon_key=x.pokemon_key where x.snapshot_id=%s""", (snapshot_id,))
        self.abilities = self._group(cur.fetchall(), sid_by_pid)
        cur.execute("""select p.pokemon_id, i.name_en n, x.prob from meta_item x join item i using(item_id)
                       join meta_pokemon p on p.snapshot_id=x.snapshot_id and p.pokemon_key=x.pokemon_key where x.snapshot_id=%s""", (snapshot_id,))
        self.items = self._group(cur.fetchall(), sid_by_pid)
        cur.execute("""select p.pokemon_id, x.move_id, x.prob from meta_move x
                       join meta_pokemon p on p.snapshot_id=x.snapshot_id and p.pokemon_key=x.pokemon_key
                       where x.snapshot_id=%s and x.move_id is not null""", (snapshot_id,))
        self.moves = {}
        for r in cur.fetchall():
            sid, mk = sid_by_pid.get(r["pokemon_id"]), move_by_id.get(r["move_id"])
            if sid and mk:
                self.moves.setdefault(sid, []).append((mk, float(r["prob"])))
        cur.execute("""select p.pokemon_id, x.nature, x.sp_hp, x.sp_atk, x.sp_def, x.sp_spa, x.sp_spd, x.sp_spe, x.prob from meta_spread x
                       join meta_pokemon p on p.snapshot_id=x.snapshot_id and p.pokemon_key=x.pokemon_key where x.snapshot_id=%s""", (snapshot_id,))
        self.spreads = {}
        for r in cur.fetchall():
            sid = sid_by_pid.get(r["pokemon_id"])
            if sid:
                sp = {k: r["sp_" + k] for k in SP_KEYS}
                self.spreads.setdefault(sid, []).append(((r["nature"], sp), float(r["prob"])))

    @staticmethod
    def _group(rows, sid_by_pid):
        out = {}
        for r in rows:
            sid = sid_by_pid.get(r["pokemon_id"])
            if sid:
                out.setdefault(sid, []).append((r["n"], float(r["prob"])))
        return out

    def top_species(self, n=30):
        return [s for s, _ in sorted(self.usage.items(), key=lambda kv: -kv[1])[:n]]

    @staticmethod
    def _pick(pairs, rng):
        tot = sum(p for _, p in pairs)
        x = rng.random() * tot
        for v, p in pairs:
            x -= p
            if x <= 0:
                return v
        return pairs[-1][0]

    def _moves4(self, sid, rng):
        pool = [(m, p) for m, p in self.moves.get(sid, []) if m in self.data.moves]
        out = []
        while pool and len(out) < 4:
            m = self._pick(pool, rng) if rng else max(pool, key=lambda x: x[1])[0]
            out.append(m)
            pool = [(a, b) for a, b in pool if a != m]
        return out

    def build_set(self, sid, rng=None):
        """rng=None 이면 가장 흔한 값(최빈) 세트, 아니면 확률대로 샘플링"""
        pick = (lambda pairs: self._pick(pairs, rng)) if rng else (lambda pairs: max(pairs, key=lambda x: x[1])[0])
        nature, sp = pick(self.spreads[sid]) if self.spreads.get(sid) else ("Serious", {})
        return dict(sid=sid, ability=pick(self.abilities[sid]) if self.abilities.get(sid) else self._default_ability(sid),
                    item=pick(self.items[sid]) if self.items.get(sid) else "", nature=nature, sp=dict(sp),
                    moves=self._moves4(sid, rng))

    def _default_ability(self, sid):
        ab = self.data.pokemon[sid]["abilities"]
        return next(iter(ab.values()), "")

    def random_team(self, rng, k=3, pool=30):
        """사용률 상위 pool 마리에서 사용률 가중으로 k마리 (종 중복 없음)"""
        sp = self.top_species(pool)
        w = {s: self.usage[s] for s in sp}
        team = []
        while len(team) < k:
            s = self._pick(list(w.items()), rng)
            team.append(self.build_set(s, rng))
            w.pop(s)
        return team
