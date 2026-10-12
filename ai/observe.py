"""관측 가능한 사건을 기록하는 엔진. Engine 을 상속해서 기록만 덧붙이므로 battle.py 는 건드리지 않는다.
st.events 에 다음 튜플이 쌓인다 (실제 게임 화면의 메시지/팝업에 해당하는 공개 정보):
  ('switch_in', side)            포켓몬이 등장
  ('act', side)                  행동 시작 (창 구분용)
  ('trigger', side, 'ability:이름' | 'item:이름')   특성/도구가 발동 (예: 위협, 날씨 특성, 먹다남은음식, 열매)
  ('item', side, 이름)           도구가 소모됨 (기합의띠 등)"""
from .battle import Engine


class ObsEngine(Engine):
    def clone(self, st):
        c = super().clone(st)
        c.events = None         # 롤아웃 복제본은 기록하지 않는다 (속도)
        c.no_events = True
        return c

    def _rec(self, st, ev):
        evs = getattr(st, "events", None)
        if evs is None and not getattr(st, "no_events", False):
            st.events = evs = []         # 첫 사건(초기 등장) 때 만든다
        if evs is not None:
            evs.append(ev)

    def _switch_in(self, st, side, rng, to=None, carry=False):
        self._rec(st, ("switch_in", side))
        return super()._switch_in(st, side, rng, to=to, carry=carry)

    def _do_action(self, st, i, act, acts, rng, switch_policy):
        self._rec(st, ("act", i))
        return super()._do_action(st, i, act, acts, rng, switch_policy)

    def apply_row(self, st, src, row, side, bm, rng, mv=None, dmg=0, foe_side=None):
        ok = super().apply_row(st, src, row, side, bm, rng, mv, dmg, foe_side)
        if ok and ":" in src and src.split(":", 1)[0] in ("ability", "item"):
            self._rec(st, ("trigger", side, src))
        return ok

    def _run_switch_in(self, st, side, bm, rng):
        foe = st.sides[1 - side].mon
        before = dict(foe.boosts)
        super()._run_switch_in(st, side, bm, rng)
        if foe.boosts != before:                    # 위협/끈적끈적 시럽 등 상대 능력치를 바꾸는 등장 특성
            for src, r in self.rows(bm, "switch_in"):
                if r["kind"] == "stat_stage" and r["target"] == "foe":
                    self._rec(st, ("trigger", side, r["label"]))
                    break

    def _consume(self, st, bm):
        side = next((i for i in (0, 1) if bm in st.sides[i].team), None)
        if bm.item and side is not None:
            self._rec(st, ("item", side, bm.item))
        return super()._consume(st, bm)
