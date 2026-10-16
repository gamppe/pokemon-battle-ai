// Showdown 의 한국어 배틀 문구(data/text/ko)를 JSON 으로 뽑는다: node gui/ko_dump.js <showdown 폴더> <출력.json>
const path = require("path");
const [sd, out] = [process.argv[2], process.argv[3]];
const D = path.join(path.resolve(sd), "dist", "data", "text");
const SKIP = /^(name|desc|shortDesc|gen\d)$/;
const pick = (T) => {
  const o = {};
  for (const id in T) {
    const e = {};
    for (const k in T[id] || {}) if (!SKIP.test(k) && typeof T[id][k] === "string" && T[id][k]) e[k] = T[id][k];
    if (Object.keys(e).length) o[id] = e;
  }
  return o;
};
const res = {
  default: pick(require(path.join(D, "ko/default.js")).DefaultText),
  abilities: pick(require(path.join(D, "ko/abilities.js")).AbilitiesText),
  moves: pick(require(path.join(D, "ko/moves.js")).MovesText),
  items: pick(require(path.join(D, "ko/items.js")).ItemsText),
};
require("fs").writeFileSync(out, JSON.stringify(res));
console.log("ok", Object.keys(res.moves).length, Object.keys(res.abilities).length, Object.keys(res.items).length);
