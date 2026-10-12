"""팀 구성 출처.
- MetaTeams : 메타 사용률 상위 종을 사용률 가중으로 뽑는다 (조합 정보 없음) — Meta.random_team 과 같다.
- ReplayTeams: Showdown 공개 리플레이에서 실제로 선출된 3마리 조합(리드 포함)을 그대로 뽑는다. 세트(특성/도구/기술/SP)는 메타 분포에서 샘플링한다.
  → 선출 조합/리드의 실제 빈도가 반영된다 (etl/collect_replays.py 로 replay, replay_mon 테이블을 먼저 채워야 한다)."""
import collections
import random

from .gamedata import norm


class MetaTeams:
    def __init__(self, meta):
        self.meta = meta

    def random_team(self, rng):
        return self.meta.random_team(rng)


class ReplayTeams:
    def __init__(self, conn, data, meta, min_rating=0, require_full=True, max_rating=None):
        self.data, self.meta = data, meta
        cur = conn.cursor()
        cur.execute("""select m.replay_id, m.side, m.slot, m.species, m.is_lead, m.mega_form
                       from replay_mon m join replay r using(replay_id)
                       where m.brought=1 and coalesce(r.rating,0) >= %s and coalesce(r.rating, 0) <= %s
                       order by m.replay_id, m.side, m.is_lead desc, m.slot""", (min_rating, max_rating if max_rating is not None else 10 ** 9))
        groups = collections.OrderedDict()
        for r in cur.fetchall():
            groups.setdefault((r["replay_id"], r["side"]), []).append(r)
        self.trios, self.skipped = [], 0
        for rows in groups.values():
            if require_full and len(rows) != 3:
                self.skipped += 1
                continue
            sids = []
            for r in rows:
                base = norm(r["species"])
                sid = norm(r["mega_form"]) if r["mega_form"] else base
                if sid not in data.pokemon:
                    sid = base
                if sid not in data.pokemon:
                    sids = None
                    break
                sids.append(sid)
            if sids and len(set(sids)) == len(sids):
                self.trios.append(tuple(sids))
        if not self.trios:
            raise RuntimeError("리플레이에서 선출 3마리 조합을 하나도 못 읽었다 (collect_replays.py 를 먼저 실행)")
        self._mega_items = {norm(r["item_name"]) for r in self._mega_stone_items(cur)}

    @staticmethod
    def _mega_stone_items(cur):
        cur.execute("select i.name_en item_name from mega_evolution me join item i on i.item_id=me.item_id")
        return cur.fetchall()

    def top_trios(self, n=10):
        return collections.Counter(tuple(sorted(t)) for t in self.trios).most_common(n)

    def _set(self, sid, rng):
        """메타 분포로 세트를 만든다. 메가가 아닌 형태는 메가스톤을 들지 않게 한다"""
        for _ in range(20):
            sets = self.meta.build_set(sid, rng) if self.meta.spreads.get(sid) else None
            if sets is None:
                break
            if "mega" in sid or norm(sets["item"]) not in self._mega_items:
                return sets
        # 메타에 없는 종: 기술/특성은 DB 기본값, 성격 무보정 (드문 경우)
        p = self.data.pokemon[sid]
        mv = [m for m in list(p["learn"])[:4] if m in self.data.moves]
        return dict(sid=sid, ability=next(iter(p["abilities"].values()), ""), item="", nature="Serious", sp={}, moves=mv)

    def random_team(self, rng):
        trio = rng.choice(self.trios)
        return [self._set(sid, rng) for sid in trio]
