// 사용: node sd_learnsets.js <showdown 경로> <out.json> — champions 모드의 종별 습득 기술(자기 learnset + 이전 진화형/폼 상속)
const path = require('path'), fs = require('fs');
const {Dex} = require(path.join(path.resolve(process.argv[2]), 'dist/sim'));
const D = Dex.mod('champions');
const out = {};
for (const sp of D.species.all()) {
  if (sp.isNonstandard) continue;
  const moves = new Set();
  let cur = sp;
  for (let g = 0; g < 4 && cur && cur.exists; g++) {          // 이전 진화형까지 거슬러 올라가며 합친다
    const ld = D.species.getLearnsetData(cur.id);
    for (const m of Object.keys((ld && ld.learnset) || {})) moves.add(m);
    const base = cur.battleOnly ? D.species.get(Array.isArray(cur.battleOnly) ? cur.battleOnly[0] : cur.battleOnly) : (cur.prevo ? D.species.get(cur.prevo) : (cur.changesFrom ? D.species.get(cur.changesFrom) : null));
    cur = base;
  }
  out[sp.id] = [...moves].filter(m => { const mv = D.moves.get(m); return mv.exists && !mv.isNonstandard; });
}
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(Object.keys(out).length);
