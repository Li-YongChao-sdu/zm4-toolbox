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

def hidden_choices(mid):
    return [r for r in dungeon_rows().values() if str(r.get("comefromId")) == str(mid)
            and str(r.get("isHide")) == "1" and str(r.get("consumePointTicket")) == "0"]

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
    payload = {"copyId": drops["copyId"], "pickItems": picks, "mobIds": mobs,
        "killMonsters": kills, "completed": 1, "currentEXP": p1.get("experience", 0),
        "pickExp": exp, "pickSp": spirit, "propertyP1Str": ";".join(str(p1.get(k, 0))
        for k in ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
        "propertyP2Total": 0, "hitCombo": 100}
    if enter_w:
        payload["enterW"] = 1
        payload["completed"] |= 16777216
    settled = request("syncDropInfoNew", payload)
    return {"mid": mid, "counts": counts, "featherCounts": feather_counts,
            "details": details, "settled": settled}
