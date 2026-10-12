"""리플레이 분석 보고서 (replay / replay_mon 테이블 -> docs/REPLAY_ANALYSIS.md).
- 종별 팀 포함률 / 선출률 / 리드율 / 선출됐을 때 승률
- 가장 흔한 선출 3마리 조합과 승률, 조합 집중도(레이팅 구간별)
- 선출 예측 기준선: '많이 뽑히는 종 3마리' 규칙이 실제 선출과 얼마나 겹치는가 (선출 AI가 넘어야 할 기준)
사용: python -m ai.replay_report [--min-n 40] [--out docs/REPLAY_ANALYSIS.md]"""
import argparse
import collections
import math

import numpy as np
import pandas as pd

from .gamedata import connect, norm


def load(conn):
    cur = conn.cursor()
    cur.execute("""select m.replay_id, m.side, m.slot, m.species, m.pokemon_id, m.brought, m.is_lead, m.mega_form,
                          r.rating, r.winner, r.uploadtime, r.turns
                   from replay_mon m join replay r using(replay_id)""")
    mon = pd.DataFrame(cur.fetchall())
    for col in ("side", "slot", "brought", "is_lead", "uploadtime"):
        mon[col] = pd.to_numeric(mon[col])
    for col in ("rating", "winner", "turns"):
        mon[col] = pd.to_numeric(mon[col].astype(float), errors="coerce")
    cur.execute("select pokemon_id, name_ko, name_en, form_name, showdown_id from pokemon")
    return mon, pd.DataFrame(cur.fetchall())


def band(r):
    if pd.isna(r):
        return "none"
    return "<1100" if r < 1100 else "1100-1199" if r < 1200 else "1200-1299" if r < 1300 else "1300+"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-n", type=int, default=40, help="종별 통계를 보일 최소 팀 포함 횟수")
    ap.add_argument("--out", default="docs/REPLAY_ANALYSIS.md")
    a = ap.parse_args()
    conn = connect()
    mon, names = load(conn)
    FORM = {"mega": "메가", "mega-x": "메가X", "mega-y": "메가Y", "mega-z": "메가Z", "wash": "워시", "heat": "히트", "alola": "알로라",
            "galar": "가라르", "hisui": "히스이", "paldea": "팔데아", "eternal": "영원", "blade": "블레이드"}
    ko_by_sid = {}
    for r in names.itertuples():
        if r.showdown_id:
            f = r.form_name if isinstance(r.form_name, str) and r.form_name else None
            ko_by_sid[r.showdown_id] = r.name_ko + (f"({FORM.get(f, f)})" if f else "")

    def ko(species, mega):
        sid = norm(mega) if isinstance(mega, str) and mega else norm(species)
        return ko_by_sid.get(sid) or ko_by_sid.get(norm(species)) or species

    mon["name"] = [ko(s, m) for s, m in zip(mon.species, mon.mega_form)]
    mon["win"] = (mon.winner == mon.side).astype(float)
    mon.loc[mon.winner.isna(), "win"] = np.nan
    mon["band"] = mon.rating.map(band)
    games = mon.drop_duplicates("replay_id")
    n_games = len(games)
    out = []
    P = out.append
    P("# 리플레이 분석 (Showdown 공개 리플레이, BSS Reg M-C)\n")
    P(f"- 표본: **{n_games}판**, 기간 {pd.to_datetime(games.uploadtime.min(), unit='s').date()} ~ {pd.to_datetime(games.uploadtime.max(), unit='s').date()}")
    P("- 레이팅 구간별 판 수: " + ", ".join(f"{b} {n}" for b, n in games.band.value_counts().sort_index().items()))
    P("- 주의: 공개된 리플레이만 있어 표본이 치우쳐 있고(상위 레이팅은 거의 없음), 선출은 '실제로 필드에 나온 포켓몬' 기준이라 "
      "3마리가 모두 나오기 전에 끝난 판은 제외했다. 승률은 선출된 쪽 기준이다.\n")


    # ── 팀 반복 (같은 6마리 팀) ──
    team_key = mon.groupby(["replay_id", "side"]).species.apply(lambda x: ",".join(sorted(x))).rename("team").reset_index()
    tc = team_key.team.value_counts()
    P("## 0. 같은 6마리 팀의 반복\n")
    P(f"- 전체 {len(team_key)}개 팀 중 서로 다른 팀은 **{tc.size}개**. 상위 1개 팀이 {tc.iloc[0] / len(team_key):.1%}, 상위 10개가 {tc.head(10).sum() / len(team_key):.1%}.")
    P("- 한 사람이 같은 팀으로 여러 판을 올리거나 유행 팀이 많다는 뜻이다. 아래 통계는 '판 기준'(실제로 만나는 빈도)이고, "
      "학습 데이터로 쓸 때는 팀 단위로 가중치를 낮춰 편향을 줄여야 한다.\n")
    P("| 순위 | 팀(영문 종 이름) | 횟수 |\n|---:|---|---:|")
    for k, (t, n) in enumerate(tc.head(8).items(), 1):
        P(f"| {k} | {t.replace(',', ', ')} | {n} |")
    P("")
    # ── 종별 ──
    g = mon.groupby("name")
    sp = pd.DataFrame({"in_team": g.size(), "brought": g.brought.sum(), "lead": g.is_lead.sum()})
    wr = mon[mon.brought == 1].groupby("name").win.agg(["mean", "count"])
    sp = sp.join(wr).rename(columns={"mean": "win_when_brought", "count": "n_brought_known"})
    sp["bring_rate"] = sp.brought / sp.in_team
    sp["lead_rate"] = sp.lead / sp.brought.clip(lower=1)
    sp["team_rate"] = sp.in_team / n_games / 2
    sp = sp[sp.in_team >= a.min_n].sort_values("in_team", ascending=False)
    P("## 1. 종별 통계 (팀 포함 횟수 상위, 팀 포함 %는 한 쪽 6마리 기준)\n")
    P("| 포켓몬 | 팀 포함 | 포함률 | 선출률(포함 시) | 리드율(선출 시) | 선출 시 승률 |\n|---|---:|---:|---:|---:|---:|")
    for name, r in sp.head(30).iterrows():
        P(f"| {name} | {int(r.in_team)} | {r.team_rate:.1%} | {r.bring_rate:.0%} | {r.lead_rate:.0%} | {r.win_when_brought:.1%} |")
    P("")
    best = sp[sp.brought >= a.min_n].sort_values("win_when_brought", ascending=False)
    P("### 선출 시 승률이 높은/낮은 종 (선출 횟수가 충분한 종만)\n")
    P("높은 쪽: " + ", ".join(f"{n} {r.win_when_brought:.0%}({int(r.brought)})" for n, r in best.head(8).iterrows()))
    P("\n낮은 쪽: " + ", ".join(f"{n} {r.win_when_brought:.0%}({int(r.brought)})" for n, r in best.tail(8).iterrows()) + "\n")

    # ── 선출 3마리 조합 ──
    br = mon[mon.brought == 1].sort_values(["replay_id", "side", "is_lead"], ascending=[True, True, False])
    trios = {}
    for (rid, side), grp in br.groupby(["replay_id", "side"]):
        if len(grp) == 3:
            trios[(rid, side)] = (tuple(sorted(grp.name)), grp.name.iloc[0], grp.win.iloc[0], grp.band.iloc[0])
    tdf = pd.DataFrame([(k[0], k[1], *v) for k, v in trios.items()], columns=["rid", "side", "trio", "lead", "win", "band"])
    P(f"## 2. 선출 3마리 조합 (3마리가 모두 확인된 {len(tdf)}개 선출)\n")
    P(f"- 서로 다른 조합 {tdf.trio.nunique()}개 / 전체 {len(tdf)}개 → 같은 조합이 반복되는 정도: 상위 10개 조합이 {tdf.trio.value_counts().head(10).sum() / len(tdf):.1%}\n")
    tdf = tdf.merge(team_key.rename(columns={"replay_id": "rid"}), on=["rid", "side"], how="left")
    P("| 순위 | 조합 | 횟수 | 서로 다른 팀 수 | 승률 | 주 리드 |\n|---:|---|---:|---:|---:|---|")
    for k, (trio, cnt) in enumerate(tdf.trio.value_counts().head(15).items(), 1):
        sub = tdf[tdf.trio == trio]
        lead = sub.lead.value_counts().index[0]
        P(f"| {k} | {' + '.join(trio)} | {cnt} | {sub.team.nunique()} | {sub.win.mean():.0%} | {lead} |")
    P("")
    dedup = tdf.drop_duplicates(["team", "trio"])
    P(f"- 같은 (6마리 팀, 선출 3마리) 쌍을 한 번만 센 기준: {len(dedup)}개 선출, 서로 다른 조합 {dedup.trio.nunique()}개, "
      f"상위 10개 조합 점유율 {dedup.trio.value_counts().head(10).sum() / len(dedup):.1%}\n")

    # ── 리드 ──
    leads = tdf.lead.value_counts()
    P("## 3. 리드 (첫 번째로 나오는 포켓몬)\n")
    P("| 리드 | 횟수 | 비율 | 승률 |\n|---|---:|---:|---:|")
    for name, cnt in leads.head(12).items():
        P(f"| {name} | {cnt} | {cnt / len(tdf):.1%} | {tdf[tdf.lead == name].win.mean():.1%} |")
    P("")

    # ── 레이팅 구간별 다양성 ──
    P("## 4. 레이팅 구간별 구성 다양성\n")
    P("| 구간 | 선출 수 | 서로 다른 종 | 유효 종 수* | 상위 10종 선출 점유율 | 조합 상위10 점유율 |\n|---|---:|---:|---:|---:|---:|")
    for b in ("<1100", "1100-1199", "1200-1299", "1300+"):
        sub = br[br.band == b]
        if len(sub) < 300:
            continue
        p = sub.name.value_counts(normalize=True)
        eff = math.exp(-(p * np.log(p)).sum())
        t = tdf[tdf.band == b].trio.value_counts()
        P(f"| {b} | {len(sub)} | {p.size} | {eff:.1f} | {p.head(10).sum():.1%} | {t.head(10).sum() / max(1, t.sum()):.1%} |")
    P("\n*유효 종 수 = exp(엔트로피). 클수록 다양하다.\n")

    # ── 선출 예측 기준선 ──
    bring_rate = (sp.bring_rate).to_dict()
    overlaps, rnd = [], []
    rng = np.random.RandomState(0)
    for (rid, side), grp in mon.groupby(["replay_id", "side"]):
        team = grp.name.tolist()
        real = set(grp[grp.brought == 1].name)
        if len(real) != 3 or len(team) != 6:
            continue
        pred = sorted(team, key=lambda n: -bring_rate.get(n, 0.5))[:3]
        overlaps.append(len(real & set(pred)))
        rnd.append(len(real & set(rng.choice(team, 3, replace=False))))
    P("## 5. 선출 예측 기준선\n")
    P(f"- '많이 선출되는 종 3마리' 규칙: 실제 선출과 평균 **{np.mean(overlaps):.2f}/3**마리 일치 (무작위 선출은 {np.mean(rnd):.2f}/3). "
      f"3마리 모두 맞춘 비율 {np.mean([o == 3 for o in overlaps]):.1%}.")
    P("- 선출 AI(상대 6마리를 보고 내 3마리를 고르는 모델)는 이 기준선을 넘어야 한다. 상대 팀 정보를 쓰는 모델은 이보다 높아야 한다.\n")
    open(a.out, "w", encoding="utf-8").write("\n".join(out))
    print("\n".join(out[:60]))
    print(f"\n저장: {a.out}")


if __name__ == "__main__":
    main()
