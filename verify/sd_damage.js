// 사용: node sd_damage.js <showdown 경로> <cases.json> <out.json>
// cases: [{id, atk:{species,ability,item,nature,sp:{hp,atk,def,spa,spd,spe},boosts?,status?,hp_frac?}, def:{...}, move, crit, weather?, terrain?, screens?:[...]}]
// 각 경우에 대해 Showdown(챔피언스 모드)이 계산한 데미지 16단계(난수 0..15)를 돌려준다. 계산 불가(면역 등)는 null.
const path = require('path');
const fs = require('fs');
const sd = path.resolve(process.argv[2]);
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const {Battle} = require(path.join(sd, 'dist/sim'));
const FORMAT = 'gen9championsbssregmc';

function mkSet(p, moves) {
  const sp = Object.assign({hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0}, p.sp || {});
  return {name: p.species, species: p.species, item: p.item || '', ability: p.ability, moves, nature: p.nature || 'Serious',
    gender: p.gender || 'N', evs: sp, ivs: {hp: 31, atk: 31, def: 31, spa: 31, spd: 31, spe: 31}, level: 50};
}

const out = {};
let errors = 0;
for (const c of cases) {
  try {
    const battle = new Battle({formatid: FORMAT, seed: [1, 2, 3, 4], forceRandomChance: undefined,
      p1: {name: 'a', team: [mkSet(c.atk, [c.move])]}, p2: {name: 'b', team: [mkSet(c.def, ['splash'])]}});
    if (battle.requestState === 'teampreview') battle.makeChoices('team 1', 'team 1');
    const A = battle.sides[0].active[0], D = battle.sides[1].active[0];
    // 등장 효과로 생긴 상태 초기화
    for (const p of [A, D]) { p.clearBoosts(); p.clearStatus(); }
    battle.field.clearWeather(); battle.field.clearTerrain();
    for (const side of battle.sides) for (const k of Object.keys(side.sideConditions)) side.removeSideCondition(k);
    for (const [p, s] of [[A, c.atk], [D, c.def]]) {
      for (const [k, v] of Object.entries(s.boosts || {})) p.boosts[k] = v;
      if (s.status) { p.status = s.status; p.statusState = battle.initEffectState({id: s.status, target: p}); }
      if (s.hp_frac != null) p.hp = Math.max(1, Math.floor(p.maxhp * s.hp_frac));
    }
    if (c.weather) battle.field.setWeather(c.weather, A);
    if (c.terrain) battle.field.setTerrain(c.terrain, A);
    for (const sc of (c.screens || [])) battle.sides[1].addSideCondition(sc, D);
    const aItem = A.item, dItem = D.item;
    const restoreItems = () => {
      for (const [p, id] of [[A, aItem], [D, dItem]]) {
        if (id && p.item !== id) { p.item = id; p.itemState = battle.initEffectState({id, target: p}); }
      }
    };
    const prepareMove = () => {
      const move = battle.dex.getActiveMove(c.move);
      move.willCrit = !!c.crit;
      battle.setActiveMove(move, A, D);
      // 실제 기술 사용 순서(useMoveInner): 기술 자체 -> 특성/도구 순으로 타입·위력 변환
      battle.singleEvent('ModifyType', move, null, A, D, move, move);
      battle.singleEvent('ModifyMove', move, null, A, D, move, move);
      battle.runEvent('ModifyType', A, D, move, move);
      battle.runEvent('ModifyMove', A, D, move, move);
      if (c.hit) move.hit = c.hit;                                   // 트리플악셀 등 타수
      if (c.proc !== undefined) battle.randomChance = () => !!c.proc;   // 변덕레이저 등 확률
      if (c.move === 'fling') {                                      // 내던지기: 도구에 따라 위력 결정/실패
        const ok = battle.singleEvent('PrepareHit', move, {}, D, A, move);
        if (ok === false) move.__failed = true;
      }
      return move;
    };
    // 중간 값 (계산기와 단계별로 비교하기 위함)
    const mid = {};
    {
      const move = prepareMove();
      if (move.__failed) { mid.failed = true; }
      mid.moveType = move.type;
      let bp = move.basePower;
      if (move.basePowerCallback) bp = move.basePowerCallback.call(battle, A, D, move);
      mid.bp0 = bp;
      bp = battle.clampIntRange(bp, 1);
      bp = battle.runEvent('BasePower', A, D, move, bp, true);
      mid.bp = bp;
      mid.typeMod = D.runEffectiveness(move);
      restoreItems();
    }
    const rolls = [];
    let immune = false, failedMove = false;
    for (let r = 0; r < 16; r++) {
      battle.random = () => r;
      const move = prepareMove();
      if (move.__failed) { immune = true; failedMove = true; rolls.push(null); break; }
      const dmg = battle.actions.getDamage(A, D, move);
      restoreItems();
      if (typeof dmg !== 'number') { immune = true; rolls.push(null); break; }
      rolls.push(dmg);
    }
    out[c.id] = immune ? {immune: true, failed: failedMove, mid} : {mid, rolls, atk: {maxhp: A.maxhp, stats: A.storedStats}, def: {maxhp: D.maxhp, stats: D.storedStats}};
  } catch (e) {
    errors++;
    out[c.id] = {error: String(e.message || e).slice(0, 200)};
  }
}
fs.writeFileSync(path.resolve(process.argv[4]), JSON.stringify(out));
console.log('cases', cases.length, 'errors', errors);
