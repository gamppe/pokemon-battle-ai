"""구애스카프 A(더 빠름)가 트릭, B는 기술 -> 다음 턴에 A/B 가 쓸 수 있는 기술 (Showdown 요청 vs 우리 엔진 legal_actions)"""
import json, os, random, subprocess, sys
sys.path.insert(0, ".")
from ai.battle import Engine
from ai.gamedata import GameData, connect
SP = {"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}
def mon(sid, ab, moves, item): return dict(sid=sid, ability=ab, item=item, nature="Serious", sp=SP, moves=moves)
A = mon(os.environ.get("ASID", "gholdengo"), "Good as Gold", os.environ.get("AMOVES", "trick,shadowball,makeitrain,recover").split(","), os.environ.get("AITEM", "Choice Scarf"))
B = mon(os.environ.get("BSID", "snorlax"), "Rough Skin", os.environ.get("BMOVES", "bodyslam,earthquake,crunch,rest").split(","), "Choice Scarf")
bench = [mon("clefable", "Magic Guard", ["moonblast"], ""), mon("torkoal", "White Smoke", ["yawn"], "")]
teams = [[A] + bench, [B] + bench]
open("verify/out/lock_in.json", "w").write(json.dumps([dict(id="x", teams=teams, turns=[[["m", int(os.environ.get("AMOVE", "0"))], ["m", int(sys.argv[1]) if len(sys.argv) > 1 else 0]]], runs=1)]))
js = r'''
const path=require('path'),fs=require('fs');const sd=path.resolve('showdown');
const {Battle,Dex}=require(path.join(sd,'dist/sim'));
const sc=JSON.parse(fs.readFileSync('verify/out/lock_in.json','utf8'))[0];
const mk=(s,i)=>({name:String(i),species:s.sid,item:s.item,ability:s.ability,moves:s.moves,nature:'Serious',gender:'N',evs:Object.assign({hp:0,atk:0,def:0,spa:0,spd:0,spe:0},s.sp),ivs:{hp:31,atk:31,def:31,spa:31,spd:31,spe:31},level:50});
const b=new Battle({formatid:'gen9championsbssregmc',seed:[1,2,3,4],p1:{name:'A',team:sc.teams[0].map(mk)},p2:{name:'B',team:sc.teams[1].map(mk)}});
if(b.requestState==='teampreview')b.makeChoices('team 123','team 123');
b.choose('p1','move '+(sc.turns[0][0][1]+1));b.choose('p2','move '+(sc.turns[0][1][1]+1));
const out=b.sides.map(s=>{const r=s.activeRequest;return r&&r.active?r.active[0].moves.map(m=>m.move+(m.disabled?'(X)':'')):null});
console.log(JSON.stringify({log:b.log.filter(l=>l.startsWith('|move')||l.startsWith('|-item')||l.startsWith('|-activate')),A_item:b.sides[0].pokemon[0].item,B_item:b.sides[1].pokemon[0].item,moves:out}));
'''
open("verify/out/lock_sd.js","w").write(js)
r = subprocess.run(["node", "verify/out/lock_sd.js"], capture_output=True, text=True, encoding="utf-8")
print("Showdown:", r.stdout.strip(), r.stderr[-300:])
eng = Engine(GameData(connect()))
rng = random.Random(1)
st = eng.new_state(teams[0], teams[1], rng=rng)
eng.step(st, [("m", int(os.environ.get("AMOVE", "0"))), ("m", int(sys.argv[1]) if len(sys.argv) > 1 else 0)], rng, None)
for i in (0, 1):
    m = st.sides[i].mon
    print("우리", "AB"[i], "도구:", m.item, "잠금:", m.locked, "가능한 행동:", [(a, m.spec["moves"][a[1]]) if a[0] == "m" else a for a in eng.legal_actions(st, i)])
