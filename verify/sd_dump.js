// 사용: node sd_dump.js <showdown 경로> <출력 json 경로>
// Showdown 챔피언스 모드(BSS Reg M-C)가 실제로 쓰는 값을 정답으로 뽑는다.
const path = require('path');
const fs = require('fs');
const sd = path.resolve(process.argv[2]);
const out = path.resolve(process.argv[3]);
const {Dex} = require(path.join(sd, 'dist/sim'));
const {TeamValidator} = require(path.join(sd, 'dist/sim/team-validator'));
const FORMAT = 'gen9championsbssregmc';
const dex = Dex.mod('champions');
const gen9 = Dex;
const v = TeamValidator.get(FORMAT);

const data = {format: FORMAT, species: {}, moves: {}, items: {}, abilities: {}, typechart: {}, natures: {}};

// 전체 species 중 이 포맷에서 사용 가능한 것
const legalSpecies = [];
for (const sp of dex.species.all()) {
  if (sp.isNonstandard || sp.tier === 'Illegal') continue;
  if (!sp.exists || sp.num <= 0) continue;
  const baseSp = dex.species.get(sp.baseSpecies);
  if ((sp.battleOnly && !sp.requiredItem) || (baseSp.cosmeticFormes || []).includes(sp.name)) continue;
  legalSpecies.push(sp);
}
// 사용 가능한 기술/도구/특성
const legalMoves = dex.moves.all().filter(m => m.exists && !m.isNonstandard && m.num > 0 && !m.isZ && !m.isMax);
for (const m of dex.moves.all()) {
  if (!m.exists || m.num <= 0) continue;
  data.moves[m.id] = {
    name: m.name, type: m.type, category: m.category, basePower: m.basePower, accuracy: m.accuracy, pp: m.pp,
    priority: m.priority, target: m.target, flags: Object.keys(m.flags || {}).sort(),
    isNonstandard: m.isNonstandard || null, critRatio: m.critRatio || 1,
    drain: m.drain || null, recoil: m.recoil || null, heal: m.heal || null, multihit: m.multihit || null,
    secondary: m.secondary ? {chance: m.secondary.chance || 100, status: m.secondary.status || null,
      volatileStatus: m.secondary.volatileStatus || null, boosts: m.secondary.boosts || null,
      self: m.secondary.self ? (m.secondary.self.boosts || true) : null} : null,
    secondaries: m.secondaries ? m.secondaries.map(s => ({chance: s.chance, status: s.status || null, volatileStatus: s.volatileStatus || null, boosts: s.boosts || null})) : null,
    boosts: m.boosts || null, selfBoosts: m.self && m.self.boosts ? m.self.boosts : null,
    status: m.status || null, volatileStatus: m.volatileStatus || null,
    selfVolatile: m.self && m.self.volatileStatus ? m.self.volatileStatus : null,
    base: (() => { const b = gen9.moves.get(m.id); return b.exists ? {basePower: b.basePower, accuracy: b.accuracy, pp: b.pp, type: b.type, category: b.category, priority: b.priority, target: b.target, flags: Object.keys(b.flags || {}).sort()} : null; })(),
    selfSwitch: m.selfSwitch || null, ohko: m.ohko || null, weather: m.weather || null, terrain: m.terrain || null,
    sideCondition: m.sideCondition || null, pseudoWeather: m.pseudoWeather || null,
  };
}
for (const sp of legalSpecies) {
  const moves = [];
  for (const m of legalMoves) {
    let problem = null;
    try { problem = v.checkCanLearn(m, sp); } catch (e) { problem = 'error'; }
    if (!problem) moves.push(m.id);
  }
  data.species[sp.id] = {
    name: sp.name, num: sp.num, types: sp.types, baseStats: sp.baseStats, abilities: sp.abilities,
    tier: sp.tier, baseSpecies: sp.baseSpecies, forme: sp.forme || null, requiredItem: sp.requiredItem || null, learnset: moves,
  };
}
for (const it of dex.items.all()) {
  if (!it.exists || it.num <= 0) continue;
  data.items[it.id] = {name: it.name, isNonstandard: it.isNonstandard || null, fling: it.fling || null, megaStone: it.megaStone || null};
}
for (const ab of dex.abilities.all()) {
  if (!ab.exists || ab.num <= 0) continue;
  data.abilities[ab.id] = {name: ab.name, isNonstandard: ab.isNonstandard || null};
}
for (const [t, info] of Object.entries(dex.data.TypeChart)) data.typechart[t] = info.damageTaken;
for (const n of dex.natures.all()) data.natures[n.id] = {plus: n.plus || null, minus: n.minus || null};
fs.mkdirSync(path.dirname(out), {recursive: true});
fs.writeFileSync(out, JSON.stringify(data));
console.log('species', Object.keys(data.species).length, 'moves', Object.keys(data.moves).length,
  'items', Object.keys(data.items).length, 'abilities', Object.keys(data.abilities).length);
