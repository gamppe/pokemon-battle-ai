-- Pokemon DB schema (MySQL 8.0+)
CREATE DATABASE IF NOT EXISTS pokemon
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE pokemon;

-- ───────── 기준 테이블 ─────────

-- 게임(세대): SwSh, SV, ZA, Champions
CREATE TABLE game (
  game_id     TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  code        VARCHAR(20)  NOT NULL UNIQUE,   -- 'SwSh','SV','ZA','CHAMPIONS'
  name_ko     VARCHAR(50)  NOT NULL,
  name_en     VARCHAR(50)  NOT NULL,
  generation  TINYINT UNSIGNED NOT NULL,      -- 8, 9, ...
  release_date DATE NULL
);

CREATE TABLE type (
  type_id  TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name_ko  VARCHAR(20) NOT NULL UNIQUE,
  name_en  VARCHAR(20) NOT NULL UNIQUE
);

-- ───────── 포켓몬 ─────────

-- 폼(리전폼, 메가 등)마다 종족값/타입이 다르므로 행을 분리.
-- dex_no = 전국도감번호, 기본폼은 form_name IS NULL
CREATE TABLE pokemon (
  pokemon_id  SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  dex_no      SMALLINT UNSIGNED NOT NULL,
  form_name   VARCHAR(50) NULL,
  name_ko     VARCHAR(50) NOT NULL,
  name_en     VARCHAR(50) NOT NULL,
  type1_id    TINYINT UNSIGNED NOT NULL,
  type2_id    TINYINT UNSIGNED NULL,
  base_hp     TINYINT UNSIGNED NOT NULL,
  base_atk    TINYINT UNSIGNED NOT NULL,
  base_def    TINYINT UNSIGNED NOT NULL,
  base_spa    TINYINT UNSIGNED NOT NULL,
  base_spd    TINYINT UNSIGNED NOT NULL,
  base_spe    TINYINT UNSIGNED NOT NULL,
  base_total  SMALLINT UNSIGNED AS (base_hp+base_atk+base_def+base_spa+base_spd+base_spe) STORED,
  showdown_id VARCHAR(40) NULL,                  -- Showdown 종 id (챔피언스 허용 포켓몬만)
  weight_kg   DECIMAL(6,1) NULL,                 -- 몸무게(kg). 안다리걸기/풀묶기/헤비봄버/히트스탬프 위력 계산용
  UNIQUE KEY uq_dex_form (dex_no, form_name),
  KEY idx_name_ko (name_ko),
  KEY idx_name_en (name_en),
  FOREIGN KEY (type1_id) REFERENCES type(type_id),
  FOREIGN KEY (type2_id) REFERENCES type(type_id)
);

-- ───────── 특성 ─────────

CREATE TABLE ability (
  ability_id  SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name_ko     VARCHAR(50) NOT NULL,
  name_en     VARCHAR(50) NOT NULL,
  effect_text TEXT NULL,
  notes       TEXT NULL,
  KEY idx_name_ko (name_ko)
);

-- ───────── 기술 ─────────

CREATE TABLE move (
  move_id     SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name_ko     VARCHAR(50) NOT NULL,
  name_en     VARCHAR(50) NOT NULL,
  type_id     TINYINT UNSIGNED NOT NULL,
  category    ENUM('physical','special','status') NOT NULL,
  power       SMALLINT UNSIGNED NULL,         -- NULL = 변동/없음
  accuracy    TINYINT UNSIGNED NULL,          -- NULL = 필중
  pp          TINYINT UNSIGNED NOT NULL,
  priority    TINYINT NOT NULL DEFAULT 0,
  effect_text TEXT NULL,                      -- 부가효과
  notes       TEXT NULL,                      -- 특이사항
  -- 배틀 AI용 수치 (etl/load_move_effects.py)
  target       VARCHAR(20) NULL,              -- normal/self/allAdjacentFoes ...
  crit_stage   TINYINT NOT NULL DEFAULT 0,
  always_crit  BOOL NOT NULL DEFAULT 0,
  min_hits     TINYINT UNSIGNED NOT NULL DEFAULT 1,
  max_hits     TINYINT UNSIGNED NOT NULL DEFAULT 1,
  drain_pct    TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- 준 데미지 대비 회복 %
  recoil_pct   TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- 준 데미지 대비 반동 %
  heal_pct     TINYINT UNSIGNED NOT NULL DEFAULT 0,   -- 최대 HP 대비 회복 %
  self_switch  BOOL NOT NULL DEFAULT 0,
  force_switch BOOL NOT NULL DEFAULT 0,
  self_destruct BOOL NOT NULL DEFAULT 0,
  ohko         BOOL NOT NULL DEFAULT 0,
  fixed_damage SMALLINT NULL,
  extra        JSON NULL,                             -- 기타 규칙 플래그
  KEY idx_name_ko (name_ko),
  FOREIGN KEY (type_id) REFERENCES type(type_id)
);

-- 기술 플래그 (contact, sound, punch, slicing, protect ...). game_id=0 공통
CREATE TABLE move_flag (
  move_id SMALLINT UNSIGNED NOT NULL,
  flag    VARCHAR(20) NOT NULL,
  game_id TINYINT UNSIGNED NOT NULL DEFAULT 0,
  PRIMARY KEY (move_id, flag, game_id), KEY idx_flag (flag),
  FOREIGN KEY (move_id) REFERENCES move(move_id)
);

-- 기술 부가효과. game_id=0 공통. game_move.effects_overridden=1이면 해당 게임 행만 사용
CREATE TABLE move_effect (
  effect_id    INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  move_id      SMALLINT UNSIGNED NOT NULL,
  trigger_type ENUM('primary','secondary') NOT NULL,
  applies_to   ENUM('target','self','field','side') NOT NULL,
  kind         ENUM('status','volatile','stat_stage','weather','terrain','pseudo_weather','side_condition','slot_condition','special') NOT NULL,
  code         VARCHAR(30) NOT NULL,
  stages       TINYINT NULL,
  chance_pct   TINYINT UNSIGNED NOT NULL DEFAULT 100,
  game_id      TINYINT UNSIGNED NOT NULL DEFAULT 0,
  KEY idx_move (move_id), KEY idx_kind (kind, code),
  FOREIGN KEY (move_id) REFERENCES move(move_id)
);

-- ───────── 아이템 (배틀 지닌물건) ─────────

CREATE TABLE item (
  item_id     SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  name_ko     VARCHAR(50) NOT NULL,
  name_en     VARCHAR(50) NOT NULL,
  effect_text TEXT NULL,                      -- 특이사항(효과)
  KEY idx_name_ko (name_ko)
);

-- ───────── 게임별 존재 여부 ─────────

CREATE TABLE game_pokemon (
  game_id    TINYINT UNSIGNED  NOT NULL,
  pokemon_id SMALLINT UNSIGNED NOT NULL,
  tier       VARCHAR(10) NULL,                -- Showdown 티어(챔피언스)
  PRIMARY KEY (game_id, pokemon_id),
  FOREIGN KEY (game_id)    REFERENCES game(game_id),
  FOREIGN KEY (pokemon_id) REFERENCES pokemon(pokemon_id)
);

CREATE TABLE game_move (
  game_id TINYINT UNSIGNED  NOT NULL,
  move_id SMALLINT UNSIGNED NOT NULL,
  -- 게임별로 위력/PP/효과가 바뀌는 경우 덮어쓰기용 (NULL이면 move 기본값)
  power_override  SMALLINT UNSIGNED NULL,
  accuracy_override TINYINT UNSIGNED NULL,
  pp_override     TINYINT UNSIGNED NULL,
  type_override   TINYINT UNSIGNED NULL,
  effects_overridden BOOL NOT NULL DEFAULT 0,
  notes           TEXT NULL,
  PRIMARY KEY (game_id, move_id),
  FOREIGN KEY (game_id) REFERENCES game(game_id),
  FOREIGN KEY (move_id) REFERENCES move(move_id)
);

CREATE TABLE game_item (
  game_id TINYINT UNSIGNED  NOT NULL,
  item_id SMALLINT UNSIGNED NOT NULL,
  notes   TEXT NULL,                          -- 게임별 효과 차이
  PRIMARY KEY (game_id, item_id),
  FOREIGN KEY (game_id) REFERENCES game(game_id),
  FOREIGN KEY (item_id) REFERENCES item(item_id)
);

-- 포켓몬별 특성 (슬롯: 1, 2 = 일반 특성 / hidden = 숨겨진 특성)
-- 특성 구성은 게임/세대에 따라 바뀔 수 있어 game_id를 포함
CREATE TABLE pokemon_ability (
  game_id    TINYINT UNSIGNED  NOT NULL,
  pokemon_id SMALLINT UNSIGNED NOT NULL,
  slot       ENUM('1','2','hidden') NOT NULL,
  ability_id SMALLINT UNSIGNED NOT NULL,
  PRIMARY KEY (game_id, pokemon_id, slot),
  KEY idx_ability (ability_id),
  FOREIGN KEY (game_id, pokemon_id) REFERENCES game_pokemon(game_id, pokemon_id),
  FOREIGN KEY (ability_id) REFERENCES ability(ability_id)
);

-- ───────── 배울 수 있는 기술 (게임별) ─────────

CREATE TABLE pokemon_move (
  game_id    TINYINT UNSIGNED  NOT NULL,
  pokemon_id SMALLINT UNSIGNED NOT NULL,
  move_id    SMALLINT UNSIGNED NOT NULL,
  method     ENUM('level-up','machine','egg','tutor','other') NOT NULL,
  level      TINYINT UNSIGNED NOT NULL DEFAULT 0,  -- level-up 외에는 0
  PRIMARY KEY (game_id, pokemon_id, move_id, method, level),
  KEY idx_move (move_id),
  FOREIGN KEY (game_id, pokemon_id) REFERENCES game_pokemon(game_id, pokemon_id),
  FOREIGN KEY (game_id, move_id)    REFERENCES game_move(game_id, move_id)
);

-- ───────── 초기 데이터 ─────────

INSERT INTO game (code, name_ko, name_en, generation) VALUES
  ('SwSh',      '소드/실드',      'Sword/Shield',        8),
  ('SV',        '스칼렛/바이올렛', 'Scarlet/Violet',      9),
  ('ZA',        'Z-A',           'Legends: Z-A',         9),
  ('CHAMPIONS', '챔피언스',       'Pokémon Champions',   9);

INSERT INTO type (name_ko, name_en) VALUES
  ('노말','Normal'),('불꽃','Fire'),('물','Water'),('전기','Electric'),
  ('풀','Grass'),('얼음','Ice'),('격투','Fighting'),('독','Poison'),
  ('땅','Ground'),('비행','Flying'),('에스퍼','Psychic'),('벌레','Bug'),
  ('바위','Rock'),('고스트','Ghost'),('드래곤','Dragon'),('악','Dark'),
  ('강철','Steel'),('페어리','Fairy');

-- ───────── 배틀 규칙 ─────────

-- 타입 상성표 (공격 타입 -> 방어 타입 배율; 표에 없는 조합은 1배)
CREATE TABLE type_efficacy (
  attack_type_id  TINYINT UNSIGNED NOT NULL,
  defense_type_id TINYINT UNSIGNED NOT NULL,
  multiplier      DECIMAL(3,1) NOT NULL,   -- 0, 0.5, 2
  PRIMARY KEY (attack_type_id, defense_type_id),
  FOREIGN KEY (attack_type_id)  REFERENCES type(type_id),
  FOREIGN KEY (defense_type_id) REFERENCES type(type_id)
);

-- 메가진화: 메가폼 -> 기본폼, 메가스톤
CREATE TABLE mega_evolution (
  mega_pokemon_id SMALLINT UNSIGNED PRIMARY KEY, base_pokemon_id SMALLINT UNSIGNED NOT NULL, item_id SMALLINT UNSIGNED NULL,
  FOREIGN KEY (mega_pokemon_id) REFERENCES pokemon(pokemon_id), FOREIGN KEY (base_pokemon_id) REFERENCES pokemon(pokemon_id),
  FOREIGN KEY (item_id) REFERENCES item(item_id)
);

CREATE TABLE nature (
  nature_id TINYINT UNSIGNED PRIMARY KEY, name_ko VARCHAR(20) NOT NULL, name_en VARCHAR(20) NOT NULL,
  plus_stat ENUM('atk','def','spa','spd','spe') NULL, minus_stat ENUM('atk','def','spa','spd','spe') NULL
);

-- 대전 규칙 (etl/load_battle_rules.py)
CREATE TABLE battle_format (
  format_id TINYINT UNSIGNED PRIMARY KEY AUTO_INCREMENT, code VARCHAR(40) NOT NULL UNIQUE, name VARCHAR(80) NOT NULL,
  game_id TINYINT UNSIGNED NOT NULL, game_type ENUM('singles','doubles') NOT NULL,
  level TINYINT UNSIGNED NOT NULL, team_size TINYINT UNSIGNED NOT NULL, pick_size TINYINT UNSIGNED NOT NULL,
  sp_total TINYINT UNSIGNED NOT NULL, sp_max_per_stat TINYINT UNSIGNED NOT NULL, iv_fixed TINYINT UNSIGNED NOT NULL,
  species_clause BOOL NOT NULL, item_clause BOOL NOT NULL, ban_mythical BOOL NOT NULL, ban_restricted BOOL NOT NULL,
  notes TEXT NULL, FOREIGN KEY (game_id) REFERENCES game(game_id)
);

-- 특성 효과 수치화 (etl/ability_effects_data.py -> etl/load_ability_effects.py)
-- hook/kind/cond 어휘 설명은 ability_effects_data.py 상단 주석 참고
CREATE TABLE ability_effect (
  effect_id  INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  ability_id SMALLINT UNSIGNED NOT NULL,
  hook       VARCHAR(24) NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  target     VARCHAR(12) NULL,
  code       VARCHAR(60) NULL,
  value      DECIMAL(7,4) NULL,
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  cond       JSON NULL,
  note       VARCHAR(200) NULL,
  phase_no   TINYINT UNSIGNED NULL,                -- battle_phase 번호(처리 순서)
  KEY idx_ability (ability_id), KEY idx_hook (hook, kind),
  FOREIGN KEY (ability_id) REFERENCES ability(ability_id)
);

-- 아이템 효과 수치화 (etl/item_effects_data.py + mega_evolution -> etl/load_item_effects.py)
CREATE TABLE item_effect (
  effect_id  INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  item_id    SMALLINT UNSIGNED NOT NULL,
  hook       VARCHAR(24) NOT NULL,
  kind       VARCHAR(24) NOT NULL,
  target     VARCHAR(12) NULL,
  code       VARCHAR(60) NULL,
  value      DECIMAL(7,4) NULL,
  chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  single_use BOOL NOT NULL DEFAULT 0,
  cond       JSON NULL,
  note       VARCHAR(200) NULL,
  phase_no   TINYINT UNSIGNED NULL,                -- battle_phase 번호(처리 순서)
  KEY idx_item (item_id), KEY idx_hook (hook, kind),
  FOREIGN KEY (item_id) REFERENCES item(item_id)
);

-- 사람이 읽기 위한 조회용 뷰
CREATE OR REPLACE VIEW v_ability_effect AS
SELECT a.ability_id, a.name_ko, a.name_en, e.hook, e.kind, e.target, e.code, e.value, e.chance_pct, e.cond, e.note
FROM ability_effect e JOIN ability a USING (ability_id);

CREATE OR REPLACE VIEW v_item_effect AS
SELECT i.item_id, i.name_ko, i.name_en, e.hook, e.kind, e.target, e.code, e.value, e.chance_pct, e.single_use, e.cond, e.note
FROM item_effect e JOIN item i USING (item_id);

-- 코드로만 처리되던 기술 동작의 구조화 (etl/move_rules_data.py -> etl/load_move_rules.py)
CREATE TABLE move_rule (
  rule_id   INT UNSIGNED PRIMARY KEY AUTO_INCREMENT,
  move_id   SMALLINT UNSIGNED NOT NULL,
  game_id   TINYINT UNSIGNED NOT NULL DEFAULT 0,
  rule_type VARCHAR(24) NOT NULL,
  params    JSON NOT NULL,
  note      VARCHAR(300) NULL,
  phase_no   TINYINT UNSIGNED NULL,                -- battle_phase 번호(처리 순서)
  KEY idx_move (move_id), KEY idx_type (rule_type),
  FOREIGN KEY (move_id) REFERENCES move(move_id)
);

-- 배틀 처리 순서 (etl/load_battle_phases.py): 번호가 작을수록 먼저 처리
CREATE TABLE battle_phase (
  phase_no TINYINT UNSIGNED PRIMARY KEY, code VARCHAR(20) NOT NULL UNIQUE, name_ko VARCHAR(30) NOT NULL,
  description VARCHAR(300) NOT NULL, showdown_events VARCHAR(100) NOT NULL DEFAULT '',
  sort_order DECIMAL(5,2) NULL
);
CREATE TABLE hook_phase (
  hook VARCHAR(24) PRIMARY KEY, phase_no TINYINT UNSIGNED NOT NULL,
  FOREIGN KEY (phase_no) REFERENCES battle_phase(phase_no)
);

-- 지속 상태 (etl/battle_state_data.py -> etl/load_battle_states.py): 날씨/필드/방/진영/개별 상태/상태이상
CREATE TABLE battle_state (
  state_id SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT, code VARCHAR(30) NOT NULL UNIQUE, name_ko VARCHAR(40) NOT NULL,
  scope ENUM('field','side','pokemon','slot') NOT NULL, category VARCHAR(20) NOT NULL, set_by VARCHAR(120) NULL,
  duration_turns TINYINT UNSIGNED NULL, duration_ext JSON NULL, note VARCHAR(300) NULL
);
CREATE TABLE battle_state_effect (
  effect_id INT UNSIGNED PRIMARY KEY AUTO_INCREMENT, state_id SMALLINT UNSIGNED NOT NULL,
  hook VARCHAR(24) NOT NULL, kind VARCHAR(24) NOT NULL, target VARCHAR(16) NULL, code VARCHAR(60) NULL,
  value DECIMAL(7,4) NULL, chance_pct TINYINT UNSIGNED NOT NULL DEFAULT 100,
  order_no SMALLINT UNSIGNED NULL, cond JSON NULL, note VARCHAR(300) NULL, phase_no TINYINT UNSIGNED NULL,
  KEY idx_state (state_id), KEY idx_hook (hook, kind), FOREIGN KEY (state_id) REFERENCES battle_state(state_id)
);

-- 전역 상호작용 규칙 (etl/load_battle_rules_global.py): 반무적/방어/접지/우선도 차단 등
CREATE TABLE battle_rule (
  rule_id SMALLINT UNSIGNED PRIMARY KEY AUTO_INCREMENT, rule_key VARCHAR(40) NOT NULL UNIQUE, name_ko VARCHAR(60) NOT NULL,
  phase_no TINYINT UNSIGNED NULL, params JSON NOT NULL, note VARCHAR(400) NULL
);

-- 타입별 면역 (etl/load_type_immunity.py): 키가 대문자 시작이면 피해, 소문자면 상태/조건(powder, prankster, par, brn, psn, tox, frz ...)
CREATE TABLE type_immunity (
  type_id TINYINT UNSIGNED NOT NULL, immunity_key VARCHAR(20) NOT NULL,
  kind ENUM('damage','condition') NOT NULL, note VARCHAR(120) NULL,
  PRIMARY KEY (type_id, immunity_key), FOREIGN KEY (type_id) REFERENCES type(type_id)
);

-- 기술별 방어/분신/마법반사 상호작용 (etl/load_move_interaction.py, 플래그/대상에서 자동 계산)
CREATE TABLE move_interaction (
  move_id SMALLINT UNSIGNED PRIMARY KEY, targets_foe BOOL NOT NULL,
  protect ENUM('blocked','passes','na') NOT NULL, substitute ENUM('passes','hits_sub','blocked','na') NOT NULL,
  sub_after_effects BOOL NOT NULL DEFAULT 0, kings_shield_blocks BOOL NOT NULL,
  magic_bounce BOOL NOT NULL, powder BOOL NOT NULL, sound BOOL NOT NULL, note VARCHAR(200) NULL,
  FOREIGN KEY (move_id) REFERENCES move(move_id)
);

-- 일본어 이름 (etl/load_names_ja.py가 컬럼을 추가하고 PokeAPI 'ja' 이름으로 채움; 신규 항목은 manual_fixes.py)
-- ALTER TABLE pokemon ADD COLUMN name_ja VARCHAR(60) NULL, ADD COLUMN form_name_ja VARCHAR(60) NULL;
-- ALTER TABLE move    ADD COLUMN name_ja VARCHAR(60) NULL;
-- ALTER TABLE ability ADD COLUMN name_ja VARCHAR(60) NULL;
-- ALTER TABLE item    ADD COLUMN name_ja VARCHAR(60) NULL;
-- ALTER TABLE type    ADD COLUMN name_ja VARCHAR(30) NULL;
-- ALTER TABLE nature  ADD COLUMN name_ja VARCHAR(30) NULL;

-- 메타 통계(etl/collect_meta_smogon.py가 테이블을 만들고 채움): meta_snapshot(출처/포맷/레이팅 컷오프/월), meta_pokemon(사용률),
-- meta_ability / meta_item / meta_move (weight=가중 횟수, prob=세트 수 대비 확률), meta_spread(성격+SP 배분), meta_teammate, meta_counter
