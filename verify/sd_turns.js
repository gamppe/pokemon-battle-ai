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

const VOLS = new Set(['confusion', 'leechseed', 'curse', 'focusenergy', 'taunt', 'encore', 'disable', 'substitute', 'healblock', 'yawn']);   // 비교하는 임시 상태
function summary(battle) {
  // 턴이 끝난 시점에는 열매/허브 등이 다음 Update 이벤트에서 소모되도록 대기 중일 수 있다 (엔진은 즉시 처리) -> 읽기 전에 한 번 돌려 맞춘다
  battle.eachEvent('Update');
  const mons = battle.sides.map(side => {
    const o = [];
    for (const p of side.pokemon) {
      const b = {};
      for (const [k, v] of Object.entries(p.boosts)) if (v) b[k] = v;
      const v = p.isActive && !p.fainted ? Object.keys(p.volatiles).filter(k => VOLS.has(k)).sort().join(',') : '';
      o[Number(p.name)] = {hp: p.hp, st: p.status || '', b, it: p.item || '', fnt: p.fainted ? 1 : 0, v, pp: p.moveSlots.map(m => m.pp)};
    }
    return o;
  });
  const act = battle.sides.map(side => Number(side.active[0] ? side.active[0].name : -1));
  const sc = battle.sides.map(side => {
    const o = {};
    for (const [k, v] of Object.entries(side.sideConditions)) o[k] = v.layers || 1;
    return o;
  });
  const winner = battle.winner ? (battle.winner === battle.sides[0].name ? 0 : battle.winner === battle.sides[1].name ? 1 : -1) : (battle.ended ? -1 : null);
  return {mons, act, sc, w: battle.field.weather || '', t: battle.field.terrain || '', win: winner};
}

// 인접한 시드가 상관된 난수열을 내지 않도록 섞는다
function mix(x) { x = (x ^ (x >>> 16)) >>> 0; x = Math.imul(x, 0x45d9f3b) >>> 0; x = (x ^ (x >>> 16)) >>> 0; x = Math.imul(x, 0x45d9f3b) >>> 0; return (x ^ (x >>> 16)) >>> 0; }
const out = {};
for (const sc of scenarios) {
  const results = [];
  let err = null;
  for (let r = 0; r < sc.runs; r++) {
    try {
      const battle = new Battle({formatid: FORMAT, seed: [mix(r * 4 + 1 + (sc.seed || 7) * 100003), mix(r * 4 + 2 + (sc.seed || 7) * 100003), mix(r * 4 + 3 + (sc.seed || 7) * 100003), mix(r * 4 + 4 + (sc.seed || 7) * 100003)],
        p1: {name: 'A', team: sc.teams[0].map(mkSet)}, p2: {name: 'B', team: sc.teams[1].map(mkSet)}});
      if (battle.requestState === 'teampreview') battle.makeChoices('team 123', 'team 123');
      const ids = ['p1', 'p2'];
      const posOf = (side, orig) => side.pokemon.findIndex(p => Number(p.name) === orig) + 1;
      const forced = () => {          // 쓰러진 자리: 살아있는 가장 낮은 원래 번호로 교체
        for (let g = 0; g < 4 && !battle.ended; g++) {
          const need = battle.sides.map(s => s.requestState === 'switch');
          if (!need[0] && !need[1]) break;
          for (let i = 0; i < 2; i++) {
            if (!need[i]) continue;
            const side = battle.sides[i];
            const rev = side.slotConditions && side.slotConditions[0] && side.slotConditions[0]['revivalblessing'];
            const alive = side.pokemon.filter(p => rev ? p.fainted : (!p.fainted && !p.isActive)).map(p => Number(p.name)).sort((a, b) => a - b);
            if (alive.length) battle.choose(ids[i], 'switch ' + posOf(side, alive[0]));
            else battle.choose(ids[i], 'pass');
          }
        }
      };
      for (const turn of sc.turns) {
        if (battle.ended) break;
        for (let i = 0; i < 2; i++) {
          const a = turn[i];
          let ok = false;
          if (a) ok = battle.choose(ids[i], a[0] === 'm' ? 'move ' + (a[1] + 1) : a[0] === 'M' ? 'move ' + (a[1] + 1) + ' mega' : 'switch ' + posOf(battle.sides[i], a[1]));
          if (!ok) battle.choose(ids[i], 'default');
        }
        forced();
      }
      const sm = summary(battle);
      if (process.env.SD_LOG) sm.log = battle.log.filter(l => !l.startsWith('|split') && !l.startsWith('|t:|')).join('\n');
      results.push(sm);
    } catch (e) { err = String(e && e.stack || e).split('\n').slice(0, 3).join(' | '); break; }
  }
  out[sc.id] = err ? {error: err} : {results};
}
fs.writeFileSync(process.argv[4], JSON.stringify(out));
