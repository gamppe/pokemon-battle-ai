"""외부 데이터에 없어서 수작업으로 확인해 넣는 값 (출처 기재)."""
import os, pymysql
db = pymysql.connect(host=os.environ.get("DB_HOST", "localhost"), user=os.environ.get("DB_USER", "root"), password=os.environ["DB_PASSWORD"],
                     database=os.environ.get("POKEMON_DB", "pokemon"), charset="utf8mb4")
cur = db.cursor()
ABILITY_KO = {  # 챔피언스 신규 특성 한글명 (천정부지: 포켓몬 위키, 나머지: OP.GG 포켓몬 챔피언스 - 공식 표기 미확인)
    "Eelevate": "천정부지", "Fire Mane": "불꽃의갈기", "Aura Guard": "파동의방호",
}
for en, ko in ABILITY_KO.items():
    cur.execute("update ability set name_ko=%s where name_en=%s", (ko, en))
db.commit()
print("manual fixes:", len(ABILITY_KO))
