"""선출 AI v0: 내 6마리 + 상대 6마리 -> 내가 선출할 3마리.
리플레이의 실제 선출(필드에 나온 포켓몬)을 정답으로 학습한다. 6마리 각각에 '선출될 확률'을 내고 상위 3마리를 고른다.
평가: 같은 6마리 팀이 학습/검증에 걸치면 외우기만 해도 맞으므로 '팀 단위'로 학습/검증을 나눈다.
사용: python -m ai.selection [--epochs 40] [--min-rating 0]"""
import argparse
import collections
import time

import numpy as np
import torch
import torch.nn as nn

from .gamedata import GameData, connect, norm

TYPES = ["Normal", "Fire", "Water", "Electric", "Grass", "Ice", "Fighting", "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
         "Dragon", "Dark", "Steel", "Fairy"]


def species_info(data, species):
    """종 이름 -> (타입 원-핫 18, 종족값 6/150, 타입 목록, 종족값 dict). 메가는 팀에 등록된 기본 종의 값을 쓴다"""
    sid = norm(species)
    p = data.pokemon.get(sid) or next((v for k, v in data.pokemon.items() if k.startswith(sid)), None)
    if p is None:
        return np.zeros(18, dtype=np.float32), np.zeros(6, dtype=np.float32), [], {}
    oh = np.zeros(18, dtype=np.float32)
    for t in p["types"]:
        if t in TYPES:
            oh[TYPES.index(t)] = 1.0
    b = p["base"]
    return oh, np.array([b[k] / 150.0 for k in ("hp", "atk", "def_", "spa", "spd", "spe")], dtype=np.float32), p["types"], b


def matchup(data, a_info, d_info):
    """a 가 d 에게 주는 타입 상성 배율의 최댓값(STAB 기준 공격 타입) — 공격 효율 지표"""
    a_types, d_types = a_info[2], d_info[2]
    if not a_types or not d_types:
        return 1.0
    best = 0.0
    for at in a_types:
        m = 1.0
        for dt in d_types:
            m *= data.type_chart.get((at, dt), 1.0)
        best = max(best, m)
    return best


def build_dataset(conn):
    """(replay, side) 마다: 내 6마리 종 id, 상대 6마리 종 id, 선출 마스크(6), 3마리 확인 여부, 팀 키"""
    cur = conn.cursor()
    cur.execute("""select m.replay_id, m.side, m.slot, m.species, m.brought, m.is_lead, m.mega_form, r.rating
                   from replay_mon m join replay r using(replay_id) order by m.replay_id, m.side, m.slot""")
    rows = cur.fetchall()
    species = sorted({(r["mega_form"] or r["species"]) for r in rows} | {r["species"] for r in rows})
    sid = {n: i + 1 for i, n in enumerate(species)}        # 0 = 패딩
    teams = collections.defaultdict(list)
    for r in rows:
        teams[(r["replay_id"], r["side"])].append(r)
    X_my, X_op, Y, OK, KEY, RAT, N_MY, N_OP = [], [], [], [], [], [], [], []
    for (rid, side), mine in teams.items():
        opp = teams.get((rid, 1 - side))
        if opp is None or len(mine) != 6 or len(opp) != 6:
            continue
        # 팀 구성이 같으면 순서와 무관하게 같은 키 (반복 팀 누수 방지)
        key = ",".join(sorted(r["species"] for r in mine))
        # 종 id: 메가로 진화한 폼이 아니라 팀에 등록된 기본 종으로 통일 (선출 시점엔 메가 여부를 모른다)
        my_ids = [sid[r["species"]] for r in mine]
        op_ids = [sid[r["species"]] for r in opp]
        y = [float(r["brought"]) for r in mine]
        X_my.append(my_ids); X_op.append(op_ids); Y.append(y)
        N_MY.append([r["species"] for r in mine]); N_OP.append([r["species"] for r in opp])
        OK.append(sum(y) == 3)
        KEY.append(key)
        RAT.append(mine[0]["rating"] or 0)
    return (np.array(X_my), np.array(X_op), np.array(Y, dtype=np.float32), np.array(OK), KEY, np.array(RAT), len(species) + 1, N_MY, N_OP)


def pair_features(data, n_my, n_op, cache={}):
    """한 샘플의 (내 6마리 x 상대 6마리) 상성 특징: 내가 상대를 때리는 배율, 상대가 나를 때리는 배율, 속도 우열.
    반환: (6,6,4) -> [내 공격 배율/4, 상대 공격 배율/4, 내 속도>상대, 내 종족값합-상대 종족값합]"""
    def info(sp):
        if sp not in cache:
            cache[sp] = species_info(data, sp)
        return cache[sp]
    out = np.zeros((6, 6, 4), dtype=np.float32)
    for i, a in enumerate(n_my):
        ia = info(a)
        for j, o in enumerate(n_op):
            io = info(o)
            out[i, j, 0] = matchup(data, ia, io) / 4.0
            out[i, j, 1] = matchup(data, io, ia) / 4.0
            out[i, j, 2] = float(ia[3].get("spe", 0) > io[3].get("spe", 0))
            out[i, j, 3] = (sum(ia[3].values()) - sum(io[3].values())) / 300.0 if ia[3] and io[3] else 0.0
    return out


class SelNet(nn.Module):
    """내 포켓몬 6마리 각각의 선출 점수. 입력: 포켓몬 자체 특징(타입, 종족값) + 상대 6마리에 대한 상성 요약 (+ 선택: 종 id 임베딩).
    내 팀 맥락(자기 어텐션)과 상대 6마리(교차 어텐션)를 본다."""

    def __init__(self, n_species, d=64, heads=4, drop=0.2, use_id=True):
        super().__init__()
        self.use_id = use_id
        self.emb = nn.Embedding(n_species, d, padding_idx=0)
        self.opp_emb = nn.Embedding(n_species, d, padding_idx=0)
        self.feat = nn.Sequential(nn.Linear(24, d), nn.GELU())              # 타입 18 + 종족값 6
        self.pair = nn.Sequential(nn.Linear(18, d), nn.GELU())              # 상성 요약 18
        self.self_att = nn.TransformerEncoderLayer(d, heads, dim_feedforward=d * 2, dropout=drop, batch_first=True, norm_first=True)
        self.cross = nn.MultiheadAttention(d, heads, dropout=drop, batch_first=True)
        self.ctx = nn.TransformerEncoderLayer(d, heads, dim_feedforward=d * 2, dropout=drop, batch_first=True, norm_first=True)
        self.head = nn.Sequential(nn.LayerNorm(d), nn.Dropout(drop), nn.Linear(d, d), nn.GELU(), nn.Linear(d, 1))

    @staticmethod
    def summarize(pair):
        """pair: (B,6,6,4) = [내 공격 배율, 상대 공격 배율, 속도 우위, 종족값 차]. 상대 순서에 무관한 요약 (B,6,18)"""
        atk = torch.sort(pair[..., 0], dim=2, descending=True).values[:, :, :3]       # 내가 때리는 배율 상위 3
        dfn = torch.sort(pair[..., 1], dim=2, descending=True).values[:, :, :3]       # 상대가 나를 때리는 배율 상위 3
        return torch.cat([pair.mean(2), pair.max(2).values, pair.min(2).values, atk, dfn], dim=-1)

    def forward(self, mine, opp, f_my, f_op, pair):
        a = self.feat(f_my) + (self.emb(mine) if self.use_id else 0)
        o = self.feat(f_op) + (self.opp_emb(opp) if self.use_id else 0)
        a = self.self_att(a + self.pair(self.summarize(pair)))
        c, _ = self.cross(a, o, o)
        return self.head(self.ctx(a + c)).squeeze(-1)           # (B, 6) 로짓


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--min-rating", type=int, default=0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--no-id", dest="use_id", action="store_false", help="종 id 임베딩 없이 타입/종족값/상성만 사용")
    a = ap.parse_args()
    conn = connect()
    data = GameData(conn)
    Xm, Xo, Y, OK, KEY, RAT, n_sp, NM, NO = build_dataset(conn)
    keep = OK & (RAT >= a.min_rating)
    idx = np.where(keep)[0]
    Xm, Xo, Y, RAT = Xm[idx], Xo[idx], Y[idx], RAT[idx]
    KEY = [KEY[i] for i in idx]
    NM, NO = [NM[i] for i in idx], [NO[i] for i in idx]
    n = len(Y)
    # 특징 (정적): 포켓몬별 타입+종족값, 상대와의 상성
    F_my = np.array([[np.concatenate(species_info(data, sp)[:2]) for sp in team] for team in NM], dtype=np.float32)
    F_op = np.array([[np.concatenate(species_info(data, sp)[:2]) for sp in team] for team in NO], dtype=np.float32)
    P = np.array([pair_features(data, m, o) for m, o in zip(NM, NO)], dtype=np.float32)
    # 팀 키 단위 분할 (같은 6마리 팀이 학습과 검증에 동시에 나오지 않게)
    uniq = sorted(set(KEY))
    rng = np.random.RandomState(a.seed)
    rng.shuffle(uniq)
    val_keys = set(uniq[: max(1, len(uniq) // 5)])
    isv = np.array([k in val_keys for k in KEY])
    tr, va = np.where(~isv)[0], np.where(isv)[0]
    print(f"선출 샘플 {n}개 (서로 다른 팀 {len(uniq)}개), 학습 {len(tr)} / 검증 {len(va)}  종 id 사용: {a.use_id}")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    T = lambda x, dt=torch.float32: torch.tensor(x, dtype=dt, device=dev)
    Xm_t, Xo_t, Y_t, Fm_t, Fo_t, P_t = T(Xm, torch.long), T(Xo, torch.long), T(Y), T(F_my), T(F_op), T(P)

    # 기준선: 학습 구간에서 구한 종별 선출률 상위 3마리 / 무작위
    cnt, br = collections.Counter(), collections.Counter()
    for i in tr:
        for s, y in zip(Xm[i], Y[i]):
            cnt[s] += 1; br[s] += y
    rate = {s: br[s] / cnt[s] for s in cnt}
    truth = lambda i: set(np.where(Y[i] == 1)[0])
    base = np.mean([len(set(np.argsort([-rate.get(s, 0.5) for s in Xm[i]])[:3]) & truth(i)) for i in va])
    base_all3 = np.mean([set(np.argsort([-rate.get(s, 0.5) for s in Xm[i]])[:3]) == truth(i) for i in va])
    rnd = np.mean([len(set(rng.choice(6, 3, replace=False)) & truth(i)) for i in va])
    print(f"기준선(종별 선출률 상위 3): 평균 {base:.2f}/3 일치, 3마리 모두 {base_all3:.1%}   (무작위 {rnd:.2f}/3)")

    net = SelNet(n_sp, use_id=a.use_id).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=5e-2)
    bce = nn.BCEWithLogitsLoss()

    def run(ids, train=False):
        b = torch.tensor(ids, device=dev)
        mine, opp, fm, fo, pr, y = Xm_t[b], Xo_t[b], Fm_t[b], Fo_t[b], P_t[b], Y_t[b]
        if train:                                          # 증강: 내 6마리 순서 / 상대 6마리 순서를 무작위로 섞는다
            pm = torch.argsort(torch.rand(len(b), 6, device=dev), dim=1)
            po = torch.argsort(torch.rand(len(b), 6, device=dev), dim=1)
            g1 = lambda x, p: torch.gather(x, 1, p.view(*p.shape, *([1] * (x.dim() - 2))).expand(*x.shape))
            mine, fm, y = g1(mine, pm), g1(fm, pm), g1(y, pm)
            opp, fo = g1(opp, po), g1(fo, po)
            pr = torch.gather(pr, 1, pm.view(len(b), 6, 1, 1).expand(-1, -1, 6, 4))
            pr = torch.gather(pr, 2, po.view(len(b), 1, 6, 1).expand(-1, 6, -1, 4))
        return net(mine, opp, fm, fo, pr), y

    def evaluate():
        net.eval()
        with torch.no_grad():
            lg, y = run(va)
        top3 = np.argsort(-lg.cpu().numpy(), axis=1)[:, :3]
        ov = [len(set(t) & truth(i)) for t, i in zip(top3, va)]
        return np.mean(ov), np.mean([o == 3 for o in ov]), bce(lg, y).item()

    best = (-1, 0, 9)
    t0 = time.time()
    for ep in range(a.epochs):
        net.train()
        perm = np.random.permutation(tr)
        for k in range(0, len(perm), 256):
            lg, y = run(perm[k:k + 256], train=True)
            loss = bce(lg, y)
            opt.zero_grad()
            loss.backward()
            opt.step()
        ov, all3, ll = evaluate()
        if ov > best[0]:
            best = (ov, all3, ll)
        if (ep + 1) % 5 == 0 or ep == 0:
            print(f"epoch {ep + 1:3d}  검증 평균 일치 {ov:.2f}/3  3마리 모두 {all3:.1%}  logloss {ll:.3f}  ({time.time() - t0:.0f}s)", flush=True)
    print(f"\n최고: 평균 {best[0]:.2f}/3 일치, 3마리 모두 {best[1]:.1%}  (기준선 {base:.2f}/3, {base_all3:.1%} / 무작위 {rnd:.2f}/3)")


if __name__ == "__main__":
    main()
