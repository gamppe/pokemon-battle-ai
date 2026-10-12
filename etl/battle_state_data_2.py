"""지속 상태 추가분: 방어 계열, 연속 사용 카운터(stall), 분신, 씨뿌리기, 멸망의 노래 (Showdown 소스 수작업).
battle_state_data.py 끝에서 STATES에 합쳐진다."""
from battle_state_data import E, S


def PROTECT(code, name, move, blocks_status, punish_note, punish_effect=None):
    eff = [E("immunity", "immune", code="move_flag:protect", target="self", order_no=None,
             blocks_status_moves=blocks_status, bypassed_by="기술에 protect 플래그 없음 / Feint·Phantom Force / Unseen Fist·Piercing Drill(접촉)",
             note="이번 턴 기술을 막음. 명중 판정보다 먼저 처리(TryHit)")]
    if punish_effect:
        eff.append(punish_effect)
    return S(code, name, "pokemon", "volatile", move, 1, None, eff, punish_note)


STATES2 = [
    PROTECT("protect", "방어", "Protect / Detect", True, "접촉 피해 없음"),
    PROTECT("baneful_bunker", "토치카", "Baneful Bunker", True, "막은 뒤 접촉한 상대를 독 상태로",
            E("on_hit_taken", "status", code="psn", target="attacker", contact=True)),
    PROTECT("spiky_shield", "니들가드", "Spiky Shield", True, "막은 뒤 접촉한 상대에게 최대HP 1/8 피해",
            E("on_hit_taken", "damage_frac", 0.125, target="attacker", contact=True)),
    PROTECT("kings_shield", "킹실드", "King's Shield", False, "공격 기술만 막음, 접촉 시 공격 -1",
            E("on_hit_taken", "stat_stage", -1, code="atk", target="attacker", contact=True)),
    PROTECT("silk_trap", "실크트랩", "Silk Trap", False, "공격 기술만 막음, 접촉 시 스피드 -1",
            E("on_hit_taken", "stat_stage", -1, code="spe", target="attacker", contact=True)),
    PROTECT("burning_bulwark", "불꽃 방어", "Burning Bulwark", False, "공격 기술만 막음, 접촉 시 화상",
            E("on_hit_taken", "status", code="brn", target="attacker", contact=True)),
    PROTECT("obstruct", "저지", "Obstruct", False, "공격 기술만 막음, 접촉 시 방어 -2",
            E("on_hit_taken", "stat_stage", -2, code="def", target="attacker", contact=True)),
    S("endure", "버티기", "pokemon", "volatile", "Endure", 1, None, [
        E("modify_dmg_taken", "special", code="survive_at_1hp", target="self", note="이번 턴 기술 데미지로는 HP 1까지만 줄어듦(간접 피해는 해당 없음)")]),
    S("stall", "방어 연속 카운터", "pokemon", "volatile", "Protect/Detect/Endure/King's Shield 등", 2, None, [
        E("before_move", "special", code="consecutive_protect_chance", value=0.3333, cond_base=3, max_counter=729,
          note="연속 사용할 때마다 성공 확률이 1/3, 1/9, 1/27 ... (카운터 3에 3씩 곱해 최대 729). 다른 기술을 쓰거나 실패하면 초기화")]),
    S("substitute", "분신", "pokemon", "volatile", "Substitute", None, None, [
        E("passive", "special", code="substitute_hp", value=0.25, note="생성 시 최대HP 1/4 소모, 그 값이 분신 HP (HP 3/4 이상이어야 생성)"),
        E("immunity", "immune", code="damaging_and_status_moves", target="self",
          bypassed_by="기술의 bypasssub 플래그(소리 기술 등) / Infiltrator 특성 / 자기 자신 대상 기술",
          note="분신이 데미지를 대신 받고 부가효과·상태이상은 막음. 분신 HP가 0이 되면 사라짐(남은 데미지는 본체에 전달 안 됨)"),
        E("passive", "special", code="removes_partial_trap", note="생성 시 속박 상태 해제"),
        E("passive", "special", code="blocks_secondary_effects", note="분신에 맞은 기술은 드레인·반동은 적용되지만 부가효과는 막힘")]),
    S("leech_seed", "씨뿌리기", "pokemon", "volatile", "Leech Seed", None, None, [
        E("turn_end", "damage_frac", 0.125, target="self", order_no=8,
          note="매 턴 종료 시 최대HP 1/8 손실, 심은 쪽이 같은 양 회복. 심은 쪽이 쓰러지면 효과 없음. 풀 타입에는 걸리지 않음. Rapid Spin/Mortal Spin으로 제거")]),
    S("perish_count", "멸망의 노래 카운트", "pokemon", "volatile", "Perish Song", 4, None, [
        E("turn_end", "special", code="perish_countdown", order_no=24, note="4에서 매 턴 1씩 감소, 0이 되면 기절. 교체하면 해제")]),
]
