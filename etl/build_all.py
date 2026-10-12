"""처음부터 전체 재구성. 사용: DB_PASSWORD 설정 후 `python build_all.py [DB이름]` (기본 pokemon_check)
이 순서가 중요함: champions_legal(게임 기술 목록 확정) -> move_effects(수치 덮어쓰기) -> champions_move_changes."""
import os, subprocess, sys
db = sys.argv[1] if len(sys.argv) > 1 else "pokemon_check"
here = os.path.dirname(os.path.abspath(__file__))
USER = os.environ.get("DB_USER", "root")
env = dict(os.environ, POKEMON_DB=db, MYSQL_PWD=os.environ["DB_PASSWORD"], PYTHONIOENCODING="utf-8")
schema = open(os.path.join(here, "..", "schema.sql"), encoding="utf-8").read()
schema = schema.replace("EXISTS pokemon\n", f"EXISTS {db}\n").replace("USE pokemon;", f"USE {db};")
subprocess.run(["mysql", "-u", USER, "-e", f"drop database if exists {db}"], env=env, check=True)
subprocess.run(["mysql", "-u", USER, "--default-character-set=utf8mb4"], input=schema.encode("utf-8"), env=env, check=True)
def run(script, *extra, fatal=True):
    r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(here, script), *extra], env=env, cwd=here, capture_output=True, text=True, encoding="utf-8")
    print(("OK   " if r.returncode == 0 else "FAIL ") + script)
    if r.returncode and fatal:
        print(r.stderr[-800:]); sys.exit(1)
    return r.returncode


run("download_sources.py")          # Showdown 원본/파생 파일 (있으면 건너뜀). PokeAPI 캐시는 fetch.py가 필요할 때 받음
SHOW = os.path.join(here, "..", "showdown")
if os.path.isdir(SHOW):   # Showdown 정답 덤프 생성 (없으면 건너뜀)
    r = subprocess.run(["node", os.path.join(here, "..", "verify", "sd_dump.js"), SHOW,
                        os.path.join(here, "..", "verify", "out", "sd_champions.json")], capture_output=True, text=True, encoding="utf-8")
    print(("OK   " if r.returncode == 0 else "FAIL ") + "sd_dump.js")
    if r.returncode:
        print(r.stderr[-500:]); sys.exit(1)
for s in ["load.py", "load_items_extra.py", "load_za_moves.py", "load_type_chart.py", "load_type_immunity.py", "load_champions_legal.py",
          "load_move_effects.py", "load_champions_move_changes.py", "apply_sd_champion_overrides.py", "load_move_rules.py", "load_battle_rules.py", "manual_fixes.py",
          "load_ability_effects.py", "load_item_effects.py", "load_move_immunities.py", "load_move_interaction.py", "load_battle_states.py", "load_battle_rules_global.py", "load_battle_phases.py"]:
    if s == "load_za_moves.py":      # ZA 습득 기술: pokemondb 크롤링 결과가 없으면 먼저 수집 (Crawl-delay 2초 준수, 약 15분)
        cz = os.path.join(here, "cache_za")
        if not os.path.isdir(cz) or len(os.listdir(cz)) < 360:
            run("scrape_za_moves.py")
    r = subprocess.run([sys.executable, os.path.join(here, s)], env=env, cwd=here, capture_output=True, text=True, encoding="utf-8")
    print(("OK   " if r.returncode == 0 else "FAIL ") + s)
    if r.returncode:
        print(r.stderr[-800:]); sys.exit(1)
print("build done ->", db)
