"""외부 데이터(PokeAPI 등)에 없어서 수작업으로 확인해 넣는 값 (출처 기재).
load_names_ja.py 이후에 실행해야 name_ja 컬럼이 존재한다."""
import os, pymysql

db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()

# 챔피언스 신규 특성: (영문, 한글, 일본어). 출처: 포켓몬 위키(fandom ko) 각 특성 문서 - 문서 제목과 일본어 표기를 확인함.
#  천정부지 うなぎのぼり / 불꽃의갈기 ほのおのたてがみ / 파동의방호 はどうのぼうご   (공식 게임 표기는 아님)
ABILITY_NAMES = {
    "Eelevate": ("천정부지", "うなぎのぼり"),
    "Fire Mane": ("불꽃의갈기", "ほのおのたてがみ"),
    "Aura Guard": ("파동의방호", "はどうのぼうご"),
}
for en, (ko, ja) in ABILITY_NAMES.items():
    cur.execute("update ability set name_ko=%s, name_ja=%s where name_en=%s", (ko, ja, en))

# 아이템: PokeAPI 에서는 'stick' 이라는 이름이라 매칭되지 않은 항목. 출처: 포켓몬 위키 '대파' 문서 (일: ながねぎ, 영: Leek)
ITEM_NAMES = {"Leek": ("대파", "ながねぎ")}
for en, (ko, ja) in ITEM_NAMES.items():
    cur.execute("update item set name_ko=%s, name_ja=%s where name_en=%s", (ko, ja, en))
# 스케일샷: 연속 공격 후 방어 -1, 스피드 +1 (기존 적재에 부가효과가 비어 있음. Showdown selfBoost 기준)
cur.execute("select move_id from move where name_en='Scale Shot'")
row = cur.fetchone()
if row:
    for stat, stg in (("def", -1), ("spe", 1)):
        cur.execute("select 1 from move_effect where move_id=%s and game_id=0 and code=%s and trigger_type='primary'", (row[0], stat))
        if not cur.fetchone():
            cur.execute("insert into move_effect (move_id, trigger_type, applies_to, kind, code, stages, chance_pct, game_id) "
                        "values (%s,'primary','self','stat_stage',%s,%s,100,0)", (row[0], stat, stg))
# 되살리기(Revival Blessing)는 교체 기술이 아니다 (적재 과정에서 self_switch 가 잘못 켜져 있었음)
cur.execute("update move set self_switch=0 where name_en='Revival Blessing'")
db.commit()
print("manual fixes:", len(ABILITY_NAMES) + len(ITEM_NAMES))
