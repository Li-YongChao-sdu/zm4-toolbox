"""主线及隐藏房刷取共用流程。"""
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent / "output_cg1_20260921_1_2"
REWARD_MODES = {
    "全部领取（道具/经验/灵魂）": "all",
    "不领道具，领取经验和灵魂": "exp_spirit",
    "只通关，全部不领取": "none",
}

def dungeon_rows():
    return {int(r["id"]): r for r in json.loads((BASE / "036___Dungeon.xml.json").read_text(encoding="utf-8"))["RECORD"]}

# 少数早期隐藏房 fromId 写的是后一关；按实际入口关补全，避免误用 prevId 串到无关关卡。
HIDDEN_ENTRY_OVERRIDES = {
    7: (1005,),  # 普陀隐藏：配置 fromId=8，入口在普陀山脚
}

def hidden_choices(mid):
    """列出本关可进的隐藏/Boss房。早期关多写 fromId/specialDoor，后期才有 comefromId。"""
    rows = dungeon_rows()
    key = str(mid)
    found, seen = [], set()

    def add(row):
        if not row or str(row.get("isHide")) != "1" or str(row.get("consumePointTicket")) != "0":
            return
        rid = int(row["id"])
        if rid in seen:
            return
        seen.add(rid)
        found.append(row)

    for row in rows.values():
        linked = (str(row.get("comefromId")), str(row.get("fromId")), str(row.get("specialDoor")))
        if key in linked:
            add(row)
    for rid in HIDDEN_ENTRY_OVERRIDES.get(int(mid), ()):
        add(rows.get(rid))
    found.sort(key=lambda row: int(row["id"]))
    return found

def side_clear_route(entry_id, target_id, need):
    """支线通关路线：同关计次，或入口关 + 单独隐藏/Boss房计次。"""
    try:
        entry_id = int(entry_id)
        target_id = int(target_id)
        need = int(need)
    except (TypeError, ValueError):
        return None
    if entry_id <= 0 or target_id <= 0 or need <= 0:
        return None
    rows = dungeon_rows()
    entry = rows.get(entry_id)
    target = rows.get(target_id)
    if not entry or not target:
        return None
    if str(entry.get("consumePointTicket")) != "0" or str(target.get("consumePointTicket")) != "0":
        return None
    if entry_id == target_id:
        stages = [(entry_id, False)]
    else:
        hide_ids = {int(row["id"]) for row in hidden_choices(entry_id)}
        if target_id not in hide_ids or str(target.get("isHide")) != "1":
            return None
        # 与主线刷取勾选隐藏Boss房一致：先打入口关并带 W，再打计次的 Boss 房。
        stages = [(entry_id, True), (target_id, False)]
    return {
        "stages": stages,
        "need": need,
        "entry_id": entry_id,
        "target_id": target_id,
        "dungeon_name": target.get("name", str(target_id)),
    }


def clear_stage(flow, scene, mid, enter_w=False, pick_equips=False, *, reward_mode="all",
                only_item_ids=None):
    if reward_mode not in REWARD_MODES.values():
        raise ValueError("未知的奖励领取模式")
    row = dungeon_rows().get(mid)
    if not row or str(row.get("consumePointTicket")) != "0":
        raise RuntimeError("关卡配置缺失或需要点券，已停止")
    def request(route, data):
        response = flow.request("scene.copyHandler." + route, data, timeout=20)
        if response.get("code") != 200 or response.get("error"):
            detail = ""
            if route == "syncDropInfoNew" and isinstance(data, dict):
                detail = "（拾取%d项，经验%s，灵魂%s，enterW=%s）" % (
                    len(data.get("pickItems", [])), data.get("pickExp"),
                    data.get("pickSp"), data.get("enterW", 0))
            raise RuntimeError("%s关%s失败：%s%s" % (mid, route, response.get("error", response), detail))
        return response
    created = request("createSinglePlayerCopy", {"mid": mid, "costGem": 0})
    drops = created.get("drops") or {}
    if not drops.get("copyId"):
        raise RuntimeError("服务器未返回副本ID")
    picks, mobs, kills, counts, details = [], [], [], {}, []
    feather_counts = {}
    exp = spirit = 0
    allow = {str(x) for x in only_item_ids} if only_item_ids else None
    for drop in drops.get("newDrops") or []:
        monster = str(drop.get("monsterId", "0")); index = drop.get("index", 0)
        exp += int(drop.get("exp", 0) or 0); spirit += int(drop.get("spirit", 0) or 0)
        pickup_groups = dict(drop.get("item") or {})
        for iid, values in (drop.get("feather") or {}).items():
            values = values if isinstance(values, list) else [values]
            pickup_groups.setdefault(iid, []).extend(values)
        if pick_equips:
            for iid, values in (drop.get("equip") or {}).items():
                values = values if isinstance(values, list) else [values]
                pickup_groups.setdefault(iid, []).extend(values)
        if allow is not None:
            # 只拾取指定道具（如年兽断角），其余掉落留在原地
            pickup_groups = {iid: values for iid, values in pickup_groups.items() if str(iid) in allow}
        if pickup_groups:
            mobs.append(monster); kills.append("%s_%s" % (monster, index))
            for iid, values in pickup_groups.items():
                for value in values:
                    picks.append(value)
                    count = int(value.get("count", 1) or 1) if isinstance(value, dict) else 1
                    is_feather = iid in (drop.get("feather") or {})
                    target_counts = feather_counts if is_feather else counts
                    target_counts[str(iid)] = target_counts.get(str(iid), 0) + count
                    details.append({"monsterId": monster, "itemId": str(iid), "count": count,
                                    "kind": "feather" if is_feather else "item"})
    if reward_mode != "all":
        picks, counts, details = [], {}, []
        feather_counts = {}
        exp = spirit = 0
    if reward_mode == "none":
        mobs, kills = [], []
    import time
    time.sleep(0.5)
    request("bossDead", None)
    request("finishDungeon", {"dungeonId": mid})
    p1 = scene["curRecord"]["p1"]
    # 与「主线通关 / 悬赏」一致：completed 带 16777216，并带 enterW。
    # 仅 completed=1 时掉落仍会结算，但支线 taskData.dungeonCnt 往往不涨。
    payload = {"copyId": drops["copyId"], "pickItems": picks, "mobIds": mobs,
        "killMonsters": kills, "completed": 1 | 16777216, "enterW": 1,
        "currentEXP": p1.get("experience", 0),
        "pickExp": exp, "pickSp": spirit, "propertyP1Str": ";".join(str(p1.get(k, 0))
        for k in ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
        "propertyP2Total": 0, "hitCombo": 100}
    if enter_w:
        # 隐藏房 / W 线入口仍保留原标记；completed 位已包含
        payload["enterW"] = 1
    settled = request("syncDropInfoNew", payload)
    return {"mid": mid, "counts": counts, "featherCounts": feather_counts,
            "details": details, "settled": settled}
