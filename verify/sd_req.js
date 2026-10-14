// 사용: node sd_turns.js <showdown 경로> <scenarios.json> <out.json>
// scenarios: [{id, teams:[[set,set,set],[...]], turns:[[actA,actB],...], runs}]  set={sid,ability,item,nature,sp,moves:[이름...]}
// act = ["m", 기술번호(0부터)] | ["M", 기술번호] (메가진화 후 사용) | ["s", 팀내 원래 번호] | null(기본). 쓰러져서 교체해야 할 때는 살아있는 가장 낮은 원래 번호를 고른다.
// 각 시나리오를 runs 번 (시드만 바꿔) 돌리고 마지막 상태 요약을 모두 돌려준다. 우리 엔진과 분포를 비교하기 위함.
const path = require('path');
const fs = require('fs');
const sd = path.resolve(process.argv[2]);
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const {Battle, Dex} = require(path.join(sd, 'dist/sim'));
const CDEX = Dex.mod('champions');
const FORMAT = 'gen9championsbssregmc';

// 모든 배틀은 메가진화 전 모습으로 시작한다: 메가 종 + 맞는 메가스톤이면 원래 종 + 기본 특성으로 바꾼다 (엔진의 demega_spec 과 같은 규칙)
function demega(s) {
  const item = CDEX.items.get(s.item || '');
  if (item.exists && item.megaStone) {
    for (const [base, mega] of Object.entries(item.megaStone)) {
      if (CDEX.toID(mega) === CDEX.toID(s.sid)) {
        const bs = CDEX.species.get(base);
        if (bs.exists) return Object.assign({}, s, {sid: bs.id, ability: bs.abilities['0']});
      }
    }
  }
  return s;
}
function mkSet(s, idx) {
  s = demega(s);
  const sp = Object.assign({hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, s.sp || {});
  return {name: String(idx), species: s.sid, item: s.item || '', ability: s.ability, moves: s.moves, nature: s.nature || 'Serious',
    gender: s.gender || 'N', evs: sp, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31}, level: 50};
}


const out = {};
function mix(x) { x = (x ^ (x >>> 16)) >>> 0; x = Math.imul(x, 0x45d9f3b) >>> 0; x = (x ^ (x >>> 16)) >>> 0; x = Math.imul(x, 0x45d9f3b) >>> 0; return (x ^ (x >>> 16)) >>> 0; }
for (const sc of scenarios) {
  const rows = [];
  for (let r = 0; r < sc.runs; r++) {
    const battle = new Battle({formatid: FORMAT, seed: [mix(r * 4 + 1), mix(r * 4 + 2), mix(r * 4 + 3), mix(r * 4 + 4)],
      p1: {name: 'A', team: sc.teams[0].map(mkSet)}, p2: {name: 'B', team: sc.teams[1].map(mkSet)}});
    if (battle.requestState === 'teampreview') battle.makeChoices('team 123', 'team 123');
    const ids = ['p1', 'p2'];
    for (let i = 0; i < 2; i++) {
      const a = sc.turns[0][i];
      let ok = false;
      if (a) ok = battle.choose(ids[i], a[0] === 'm' ? 'move ' + (a[1] + 1) : 'switch ' + (a[1] + 1));
      if (!ok) battle.choose(ids[i], 'default');
    }
    // 턴이 끝난 직후: 누가 교체 포켓몬을 골라야 하는가 (requestState === 'switch')
    const need = battle.sides.map(s => s.requestState === 'switch' && !s.pokemon.every(p => p.fainted || p.isActive));
    const act = battle.sides.map(s => Number(s.active[0].name));
    rows.push({hp: battle.sides.map(s => s.pokemon.map(p => p.hp)), need, act, fnt: battle.sides.map(s => s.active[0].fainted ? 1 : 0), turn: battle.turn});
  }
  out[sc.id] = rows;
}
fs.writeFileSync(process.argv[4], JSON.stringify(out));
