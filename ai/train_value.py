"""가치망 학습. 사용: python -m ai.train_value --data data/value --epochs 20
- 게임 단위로 학습/검증을 나눈다 (같은 판의 상태가 양쪽에 섞이면 과대평가됨)
- 비교 기준(baseline): HP 비율 합 차이 + 남은 포켓몬 수 로지스틱 회귀"""
import argparse
import glob
import os
import time

import numpy as np
import torch
import torch.nn as nn

from .features import Vocab
from .value_net import ValueNet


def load(path):
    C, N, G, Y, T = [], [], [], [], []
    for f in sorted(glob.glob(os.path.join(path, "chunk_*.npz"))):
        d = np.load(f)
        C.append(d["cat"]); N.append(d["num"]); G.append(d["glob"]); Y.append(d["y"]); T.append(d["turn"])
    return np.concatenate(C), np.concatenate(N), np.concatenate(G), np.concatenate(Y), np.concatenate(T)


def baseline_feats(num):
    # num 토큰 순서: 내 3 + 상대 3, 열 0 = hp 비율, 1 = alive
    my_hp, op_hp = num[:, :3, 0].sum(1), num[:, 3:, 0].sum(1)
    my_n, op_n = num[:, :3, 1].sum(1), num[:, 3:, 1].sum(1)
    return np.stack([my_hp - op_hp, my_n - op_n], axis=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/value")
    ap.add_argument("--epochs", type=int, default=20)
    ap.add_argument("--bs", type=int, default=512)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--out", default="data/value/value_net.pt")
    a = ap.parse_args()
    C, N, G, Y, T = load(a.data)
    n = len(Y)
    # 게임 경계가 저장돼 있지 않아 연속 구간(2개 시점 x 턴 수)이 한 게임이므로, 구간 단위로 나눈다
    block = 1500
    rng = np.random.RandomState(0)
    idx_blocks = np.arange(n // block + 1)
    rng.shuffle(idx_blocks)
    val_blocks = set(idx_blocks[: max(1, len(idx_blocks) // 10)])
    is_val = np.array([(i // block) in val_blocks for i in range(n)])
    tr, va = ~is_val, is_val
    print(f"상태 {n}개 (학습 {tr.sum()}, 검증 {va.sum()}), 평균 승률 {Y.mean():.3f}")
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    vocab = Vocab.load(os.path.join(a.data, "vocab.json"))
    net = ValueNet({k: vocab.size(k) for k in vocab.t}, N.shape[2], G.shape[1]).to(dev)
    opt = torch.optim.AdamW(net.parameters(), lr=a.lr, weight_decay=5e-2)
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=a.lr, total_steps=int(a.epochs * (int(tr.sum()) // a.bs + 1)))
    t = lambda x, dt=None: torch.tensor(x, dtype=dt, device=dev) if dt else torch.tensor(x, device=dev)
    Ct, Nt, Gt, Yt = t(C, torch.long), t(N, torch.float32), t(G, torch.float32), t(Y, torch.float32)
    tri, vai = np.where(tr)[0], np.where(va)[0]
    bce = nn.BCEWithLogitsLoss()

    def evaluate(ids):
        net.eval()
        with torch.no_grad():
            out = []
            for k in range(0, len(ids), 4096):
                b = torch.tensor(ids[k:k + 4096], device=dev)
                out.append(torch.sigmoid(net(Ct[b], Nt[b], Gt[b])))
            p = torch.cat(out).cpu().numpy()
        y = Y[ids]
        ll = -np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
        dec = y != 0.5
        acc = np.mean((p[dec] > 0.5) == (y[dec] > 0.5))
        return ll, acc, p

    # baseline
    from sklearn.linear_model import LogisticRegression
    bf = baseline_feats(N)
    dec_tr = Y[tri] != 0.5
    lr_model = LogisticRegression().fit(bf[tri][dec_tr], (Y[tri][dec_tr] > 0.5).astype(int))
    pb = lr_model.predict_proba(bf[vai])[:, 1]
    yv = Y[vai]
    llb = -np.mean(yv * np.log(np.clip(pb, 1e-6, 1)) + (1 - yv) * np.log(np.clip(1 - pb, 1e-6, 1)))
    accb = np.mean((pb[yv != 0.5] > 0.5) == (yv[yv != 0.5] > 0.5))
    print(f"기준선(HP합/생존수 로지스틱): 검증 logloss {llb:.4f}, 정확도 {accb:.3f}")
    t0 = time.time()
    best = (9e9, 0, None)
    for ep in range(a.epochs):
        net.train()
        perm = np.random.permutation(tri)
        tot = 0.0
        for k in range(0, len(perm), a.bs):
            b = torch.tensor(perm[k:k + a.bs], device=dev)
            cb, nb = Ct[b], Nt[b]
            for lo in (1, 4):                                   # 벤치 두 칸 순서는 의미가 없으니 무작위로 맞바꾼다
                sw = torch.rand(len(b), device=dev) < 0.5
                idx = torch.tensor([0, 1, 2, 3, 4, 5], device=dev).repeat(len(b), 1)
                idx[sw, lo], idx[sw, lo + 1] = lo + 1, lo
                cb = torch.gather(cb, 1, idx.unsqueeze(-1).expand(-1, -1, cb.shape[2]))
                nb = torch.gather(nb, 1, idx.unsqueeze(-1).expand(-1, -1, nb.shape[2]))
            loss = bce(net(cb, nb, Gt[b]), Yt[b])
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tot += loss.item() * len(b)
        ll, acc, _ = evaluate(vai)
        print(f"epoch {ep + 1:2d}  train {tot / len(perm):.4f}  val logloss {ll:.4f}  acc {acc:.3f}  ({time.time() - t0:.0f}s)", flush=True)
        if ll < best[0]:
            best = (ll, acc, {k: v.detach().clone() for k, v in net.state_dict().items()})
    print(f"최고 검증: logloss {best[0]:.4f}, 정확도 {best[1]:.3f}")
    net.load_state_dict(best[2])
    torch.save(dict(state=net.state_dict(), n_num=N.shape[2], n_glob=G.shape[1], vocab_sizes={k: vocab.size(k) for k in vocab.t}), a.out)
    print("저장:", a.out)


if __name__ == "__main__":
    main()
