"""메가스톤을 든 메타몽이 변신하면 메가진화할 수 있는가 (Showdown 요청 canMegaEvo vs 우리 엔진 legal_actions 의 'M')"""
import json, random, subprocess, sys
sys.path.insert(0, ".")
from ai.battle import Engine
from ai.gamedata import GameData, connect
SP = {"hp": 32, "atk": 16, "def": 8, "spa": 16, "spd": 8, "spe": 16}
def mon(sid, ab, moves, item): return dict(sid=sid, ability=ab, item=item, nature="Serious", sp=SP, moves=moves)
bench = [mon("clefable", "Magic Guard", ["moonblast"], ""), mon("torkoal", "White Smoke", ["yawn"], "")]
CASES = {
 "메타몽(메가스톤 = 리자몽Y) 변신 후, 상대 리자몽 (메가스톤 보유)": (mon("ditto", "Imposter", ["transform"], "Charizardite Y"), mon("charizard", "Blaze", ["flamethrower", "roost", "solarbeam", "airslash"], "Charizardite Y")),
 "메타몽(메가스톤 = 리자몽Y) 변신 후, 상대 리자몽 (도구 없음)": (mon("ditto", "Imposter", ["transform"], "Charizardite Y"), mon("charizard", "Blaze", ["flamethrower", "roost", "solarbeam", "airslash"], "")),
 "메타몽(도구 없음) 변신 후, 상대 리자몽 (메가스톤 보유)": (mon("ditto", "Imposter", ["transform"], ""), mon("charizard", "Blaze", ["flamethrower", "roost", "solarbeam", "airslash"], "Charizardite Y")),
}
js = r'''
const path=require('path'),fs=require('fs');const sd=path.resolve('showdown');
const {Battle}=require(path.join(sd,'dist/sim'));
const sc=JSON.parse(fs.readFileSync('verify/out/dm_in.json','utf8'));
const mk=(s,i)=>({name:String(i),species:s.sid,item:s.item,ability:s.ability,moves:s.moves,nature:'Serious',gender:'N',evs:Object.assign({hp:0,atk:0,def:0,spa:0,spd:0,spe:0},s.sp),ivs:{hp:31,atk:31,def:31,spa:31,spd:31,spe:31},level:50});
const out={};
for(const [k,v] of Object.entries(sc)){
 const b=new Battle({formatid:'gen9championsbssregmc',seed:[1,2,3,4],p1:{name:'A',team:v.map(t=>t.map(mk))[0]},p2:{name:'B',team:v.map(t=>t.map(mk))[1]}});
 if(b.requestState==='teampreview')b.makeChoices('team 123','team 123');
 b.choose('p1','move 1');b.choose('p2','move 1');
 const r=b.sides[0].activeRequest;
 out[k]={species:b.sides[0].active[0].species.name,canMega:!!(r&&r.active&&r.active[0].canMegaEvo),moves:r.active[0].moves.map(m=>m.move)};
}
console.log(JSON.stringify(out));
'''
json.dump({k: [[v[0]] + bench, [v[1]] + bench] for k, v in CASES.items()}, open("verify/out/dm_in.json", "w"))
open("verify/out/dm_sd.js", "w").write(js)
r = subprocess.run(["node", "verify/out/dm_sd.js"], capture_output=True, text=True, encoding="utf-8")
sd = json.loads(r.stdout) if r.stdout.strip() else {}
print(r.stderr[-500:])
eng = Engine(GameData(connect()))
for k, v in CASES.items():
    rng = random.Random(1)
    st = eng.new_state([v[0]] + bench, [v[1]] + bench, rng=rng)
    eng.step(st, [("m", 0), ("m", 0)], rng, None)
    la = eng.legal_actions(st, 0)
    ours = any(a[0] == "M" for a in la)
    print(k, "\n  Showdown:", sd.get(k), "\n  우리: 현재 종", st.sides[0].mon.sid, "메가진화 가능", ours, [a for a in la if a[0] == "M"])
