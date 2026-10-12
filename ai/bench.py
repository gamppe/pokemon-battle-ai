"""엔진/정책 벤치마크: 같은 메타 팀 쌍으로 (a) greedy vs greedy 좌우 대칭, (b) MC 탐색 AI vs greedy"""
import argparse, random, time
from .gamedata import GameData, connect
from .meta import Meta
from .battle import Engine
from .policy import greedy_action, make_switch_policy, play_out, evaluate_actions

ap = argparse.ArgumentParser()
ap.add_argument("--snap", type=int, default=33)
ap.add_argument("--games", type=int, default=100)
ap.add_argument("--mc", type=int, default=0, help="0 이면 greedy vs greedy, 아니면 MC 롤아웃 수")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
conn = connect(); data = GameData(conn); meta = Meta(conn, data, a.snap); eng = Engine(data)
rng = random.Random(a.seed)
wins = [0.0, 0.0]; turns = 0; t0 = time.time()
for g in range(a.games):
    t0_, t1_ = meta.random_team(rng), meta.random_team(rng)
    st = eng.new_state(t0_, t1_)
    pol = make_switch_policy(eng, rng)
    while st.winner is None and st.turn < 80:
        if a.mc:
            ev = evaluate_actions(eng, st, 0, n=a.mc, seed=rng.randrange(10**9))
            act0 = max(ev, key=ev.get)
        else:
            act0 = greedy_action(eng, st, 0, rng)
        act1 = greedy_action(eng, st, 1, rng)
        eng.step(st, [act0, act1], rng, pol)
    w = st.winner if st.winner is not None else -1
    if w == -1: wins[0] += .5; wins[1] += .5
    else: wins[w] += 1
    turns += st.turn
print(f"games={a.games} side0={wins[0]:.1f} side1={wins[1]:.1f}  avg_turns={turns/a.games:.1f}  {time.time()-t0:.1f}s")
print("unsupported:", sorted(eng.unsupported.items(), key=lambda kv: -kv[1])[:15])
