"""pokemon(현재) vs pokemon_check(처음부터 재구성) 행 단위 비교. 자동증가 id 컬럼은 제외."""
import os, sys, pymysql
A, B = "pokemon", sys.argv[1] if len(sys.argv) > 1 else "pokemon_check"
mk = lambda d: pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"], database=d, charset="utf8mb4")
a, b = mk(A), mk(B)
SURR = {"effect_id", "format_id", "rule_id"}
def tables(c):
    cur = c.cursor(); cur.execute("show tables"); return {r[0] for r in cur.fetchall()}
def cols(c, t):
    cur = c.cursor(); cur.execute(f"show columns from `{t}`"); return [r[0] for r in cur.fetchall()]
ta, tb = tables(a), tables(b)
print("테이블만 한쪽에:", sorted(ta ^ tb))
bad = 0
for t in sorted(ta & tb):
    ca, cb = cols(a, t), cols(b, t)
    if set(ca) != set(cb):
        print(f"[컬럼 다름] {t}: {sorted(set(ca) ^ set(cb))}"); bad += 1; continue
    use = [c for c in ca if c not in SURR]
    q = f"select {','.join('`'+c+'`' for c in use)} from `{t}`"
    ra, rb = [], []
    cur = a.cursor(); cur.execute(q); ra = [tuple(map(str, r)) for r in cur.fetchall()]
    cur = b.cursor(); cur.execute(q); rb = [tuple(map(str, r)) for r in cur.fetchall()]
    from collections import Counter
    ca_, cb_ = Counter(ra), Counter(rb)
    if ca_ == cb_:
        print(f"[OK] {t}: {len(ra)}행"); continue
    bad += 1
    onlya, onlyb = ca_ - cb_, cb_ - ca_
    print(f"[차이] {t}: {A}={len(ra)} {B}={len(rb)} | {A}에만 {sum(onlya.values())} / {B}에만 {sum(onlyb.values())}")
    for r in list(onlya)[:6]: print("   현재에만:", [x[:40] for x in r][:8])
    for r in list(onlyb)[:6]: print("   재구성에만:", [x[:40] for x in r][:8])
print("차이 있는 테이블 수:", bad)
