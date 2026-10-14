// 사용: node sd_dump.js <showdown 경로> <out.json>  — Showdown(champions 모드)의 기술/특성/도구/종 데이터를 JSON 으로 덤프
const path = require('path'), fs = require('fs');
const {Dex} = require(path.join(path.resolve(process.argv[2]), 'dist/sim'));
const D = Dex.mod('champions');
const hooks = o => Object.keys(o).filter(k => /^on[A-Z]/.test(k) && typeof o[k] === 'function' || /^on.*(Priority|Order|SubOrder)$/.test(k) && typeof o[k] === 'number');
const out = {moves: {}, abilities: {}, items: {}, species: {}};
for (const m of D.moves.all()) {
  if (m.isNonstandard && m.isNonstandard !== 'Unobtainable') continue;
  const cond = m.condition ? hooks(m.condition) : [];
  out.moves[m.id] = {name: m.name, type: m.type, category: m.category, bp: m.basePower, acc: m.accuracy, pp: m.pp, priority: m.priority,
    target: m.target, flags: Object.keys(m.flags), secondary: m.secondary || null, secondaries: m.secondaries || null, self: m.self || null,
    boosts: m.boosts || null, drain: m.drain || null, recoil: m.recoil || null, heal: m.heal || null, multihit: m.multihit || null,
    critRatio: m.critRatio, willCrit: m.willCrit || false, ohko: m.ohko || false, damage: m.damage === undefined ? null : m.damage,
    selfSwitch: m.selfSwitch || false, forceSwitch: m.forceSwitch || false, selfdestruct: m.selfdestruct || false,
    status: m.status || null, volatileStatus: m.volatileStatus || null, sideCondition: m.sideCondition || null, weather: m.weather || null,
    terrain: m.terrain || null, pseudoWeather: m.pseudoWeather || null, selfBoost: m.selfBoost || null, isNonstandard: m.isNonstandard || null,
    hooks: hooks(m), condHooks: cond};
}
for (const a of D.abilities.all()) out.abilities[a.id] = {name: a.name, hooks: hooks(a), cond: a.condition ? hooks(a.condition) : [], isNonstandard: a.isNonstandard || null};
for (const i of D.items.all()) out.items[i.id] = {name: i.name, hooks: hooks(i), cond: i.condition ? hooks(i.condition) : [], isNonstandard: i.isNonstandard || null,
  megaStone: i.megaStone || null, fling: i.fling || null, naturalGift: i.naturalGift || null};
for (const s of D.species.all()) out.species[s.id] = {name: s.name, types: s.types, base: s.baseStats, abilities: s.abilities, isNonstandard: s.isNonstandard || null, baseSpecies: s.baseSpecies, forme: s.forme};
fs.writeFileSync(process.argv[3], JSON.stringify(out));
console.log(Object.keys(out).map(k => k + ':' + Object.keys(out[k]).length).join(' '));
