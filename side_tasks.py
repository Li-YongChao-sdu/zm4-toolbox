"""支线任务：接取 / 通关型自动完成 / 领奖。

独立页面模块，只通过 build_tab(app) 挂到主界面；不修改 zm4_toolbox 的其它逻辑。
"""
import json
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

BASE = Path(__file__).resolve().parent / "output_cg1_20260921_1_2"
TASKTYPE_FILE = BASE / "210___TaskType.xml.json"
FILTERS = ("可操作", "通关型", "可接", "进行中", "可领奖", "已完成", "全部")
OPERABLE = {"可接", "进行中", "可领奖"}


def load_defs(app):
    app._side_task_defs = {}
    app._side_task_load_error = None
    try:
        records = json.loads(TASKTYPE_FILE.read_text(encoding="utf-8")).get("RECORD", [])
        for row in records:
            if isinstance(row, dict) and str(row.get("taskClass")) == "1":
                app._side_task_defs[int(row["id"])] = row
    except (OSError, ValueError, KeyError) as exc:
        app._side_task_load_error = str(exc)


def build_tab(app):
    load_defs(app)
    app._side_task_snapshot = {}
    app._side_task_filter = "可操作"

    tab = ttk.Frame(app.notebook, padding=10)
    app.notebook.add(tab, text="支线任务")

    left = ttk.LabelFrame(tab, text="支线任务列表", padding=8)
    left.pack(side="left", fill="both", expand=True, padx=(0, 10))
    filter_row = ttk.Frame(left)
    filter_row.pack(fill="x", pady=(0, 6))
    ttk.Label(filter_row, text="筛选：").pack(side="left")
    app.combo_side_task_filter = ttk.Combobox(filter_row, state="readonly", width=12,
                                              values=FILTERS)
    app.combo_side_task_filter.set("可操作")
    app.combo_side_task_filter.pack(side="left")
    app.combo_side_task_filter.bind("<<ComboboxSelected>>", lambda event: apply_filter(app))

    tree_frame = ttk.Frame(left)
    tree_frame.pack(fill="both", expand=True)
    scroll = ttk.Scrollbar(tree_frame)
    scroll.pack(side="right", fill="y")
    app.side_task_tree = ttk.Treeview(
        tree_frame, columns=("id", "name", "progress", "state", "route"),
        show="headings", yscrollcommand=scroll.set, height=18)
    scroll.config(command=app.side_task_tree.yview)
    for column, title, width in (("id", "编号", 70), ("name", "任务", 170),
                                 ("progress", "进度", 60), ("state", "状态", 70),
                                 ("route", "自动", 70)):
        app.side_task_tree.heading(column, text=title)
        app.side_task_tree.column(column, width=width, anchor="w")
    app.side_task_tree.pack(side="left", fill="both", expand=True)
    app.side_task_tree.bind("<<TreeviewSelect>>", lambda event: on_select(app))

    right = ttk.Frame(tab, width=270)
    right.pack(side="right", fill="y")
    right.pack_propagate(False)
    hint = ("配置读取失败：%s" % app._side_task_load_error
            if app._side_task_load_error else "选择存档后请点击刷新任务列表")
    app.lbl_side_task_summary = ttk.Label(right, text=hint, foreground="blue",
                                          wraplength=250, justify="left")
    app.lbl_side_task_summary.pack(anchor="w", pady=(0, 12))
    app.btn_side_task_check = ttk.Button(right, text="刷新任务列表",
                                         command=lambda: do_check(app), state="disabled")
    app.btn_side_task_check.pack(fill="x", pady=3)
    app.btn_side_task_accept = ttk.Button(right, text="接取所选任务",
                                          command=lambda: action(app, "accept"),
                                          state="disabled")
    app.btn_side_task_accept.pack(fill="x", pady=3)
    app.btn_side_task_complete = ttk.Button(right, text="自动完成并领奖",
                                            command=lambda: action(app, "complete"),
                                            state="disabled")
    app.btn_side_task_complete.pack(fill="x", pady=3)
    app.btn_side_task_claim = ttk.Button(right, text="领取已完成任务",
                                         command=lambda: action(app, "claim"),
                                         state="disabled")
    app.btn_side_task_claim.pack(fill="x", pady=3)
    app.lbl_side_task_detail = ttk.Label(right, text="选中任务可查看目标与前置条件。",
                                         wraplength=250, justify="left")
    app.lbl_side_task_detail.pack(anchor="w", pady=(16, 10))
    ttk.Label(right, text="自动完成仅支持免点券路线：同关计次、入口关+单独Boss房、击杀副本Boss（含二阶段）。需要点券的副本不自动；每轮通关前检查体力，不足直接停止，不会花点券买体力。",
              wraplength=250, justify="left", foreground="gray").pack(anchor="w")
    return tab


def enable_buttons(app):
    for name in ("btn_side_task_check", "btn_side_task_accept",
                 "btn_side_task_complete", "btn_side_task_claim"):
        button = getattr(app, name, None)
        if button is not None:
            button.config(state="normal")


def selected_id(app):
    selection = app.side_task_tree.selection()
    return int(selection[0]) if selection else None


def clear_route(app, task_id):
    """支线自动路线：通关型同关/入口+Boss房，或击败型打副本 Boss。"""
    row = app._side_task_defs.get(task_id) or {}
    task_type = str(row.get("taskType", ""))
    if task_type == "0":
        from mainfarm_routes import side_clear_route
        route = side_clear_route(row.get("dungeonId"), row.get("targetId"),
                                 row.get("targetNum", 1))
    elif task_type == "1":
        from mainfarm_routes import boss_clear_route
        route = boss_clear_route(row.get("dungeonId"), row.get("targetId"),
                                 row.get("targetNum", 1))
    else:
        route = None
    if not route:
        return None
    route = dict(route)
    route["name"] = row.get("name", "?")
    route["mid"] = route["target_id"]
    route["kind"] = "boss" if task_type == "1" else "stage"
    return route


def progress_counts(app, task_id, active_row):
    row = app._side_task_defs.get(task_id, {})
    need = int(row.get("targetNum", 1) or 1)
    if not active_row:
        return 0, need
    if active_row.get("taskState") == 1:
        return need, need
    data = active_row.get("taskData") or {}
    if not isinstance(data, dict):
        data = {}
    if str(row.get("taskType")) == "1":
        current = data.get("mobKilled", data.get("cnt"))
        if not current and data.get("killedList"):
            current = len(data.get("killedList"))
    else:
        current = data.get("dungeonCnt", data.get("cnt", data.get("num")))
    if current is None:
        current = active_row.get("cnt", active_row.get("num"))
    return int(current or 0), need


def progress_text(app, task_id, active_row):
    current, need = progress_counts(app, task_id, active_row)
    if not active_row:
        return "-/%s" % need
    return "%s/%s" % (current, need)


def find_cur(scene_obj, task_id):
    return next((row for row in scene_obj.get("curRecord", {}).get("curTasks", [])
                 if isinstance(row, dict)
                 and str(row.get("taskId", "")).isdigit()
                 and int(row.get("taskId")) == task_id), None)


def bag_free_slots(scene):
    """物品背包剩余格数；读不到时返回 None。"""
    bag = ((scene or {}).get("curRecord") or {}).get("itemsBag") or {}
    free = bag.get("freeCount")
    if isinstance(free, int):
        return free
    capacity = bag.get("itemCount")
    if isinstance(capacity, int):
        return max(0, capacity - len(bag.get("items") or []))
    return None


def require_bag_space(scene, reason="领奖"):
    free = bag_free_slots(scene)
    if free is not None and free < 1:
        raise RuntimeError("背包空间不足（剩余%d格），无法%s，请先清理背包" % (free, reason))


def make_snapshot(app, scene, slot):
    cur = scene.get("curRecord", {})
    level = int(cur.get("p1", {}).get("level", 1) or 1)
    old = {int(row.get("taskId")) for row in cur.get("oldTasks", [])
           if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()
           and int(row.get("num", 0) or 0) > 0}
    active = {int(row.get("taskId")): row for row in cur.get("curTasks", [])
              if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()}
    states, progress = {}, {}
    for task_id, row in app._side_task_defs.items():
        active_row = active.get(task_id)
        progress[task_id] = progress_text(app, task_id, active_row)
        if task_id in active:
            states[task_id] = "可领奖" if active[task_id].get("taskState") == 1 else "进行中"
        elif task_id in old:
            states[task_id] = "已完成"
        elif str(row.get("isClose", "0")) != "0":
            states[task_id] = "未开放"
        elif level < int(row.get("level", 1) or 1):
            states[task_id] = "等级不足"
        elif any(int(pre) not in old for pre in str(row.get("preTaskId", "-1")).split(";")
                 if pre.lstrip("-").isdigit() and int(pre) > 0):
            states[task_id] = "前置未完成"
        else:
            states[task_id] = "可接"
    counts = {
        "可接": sum(1 for s in states.values() if s == "可接"),
        "进行中": sum(1 for s in states.values() if s == "进行中"),
        "可领奖": sum(1 for s in states.values() if s == "可领奖"),
        "已完成": sum(1 for s in states.values() if s == "已完成"),
    }
    return {"slot": slot, "level": level, "states": states, "progress": progress,
            "active": active, "counts": counts}


def reset_display(app):
    app._side_task_snapshot = {}
    if getattr(app, "lbl_side_task_summary", None) is None:
        return
    app.lbl_side_task_summary.config(text="请点击刷新任务列表")
    rebuild_tree(app, {})


def on_select(app):
    task_id = selected_id(app)
    if task_id is None:
        return
    row = app._side_task_defs.get(task_id, {})
    state = app._side_task_snapshot.get("states", {}).get(task_id, "待读取")
    progress = app._side_task_snapshot.get("progress", {}).get(task_id, "-")
    route = clear_route(app, task_id)
    if route:
        stages = route["stages"]
        if route.get("kind") == "boss":
            if len(stages) > 1:
                route_text = "可自动：通关%s（%d）→ %s（%d）×%d" % (
                    stages[0][0], stages[0][0], stages[1][0], stages[1][0], route["need"])
            else:
                route_text = "可自动：通关%s击败目标（%d）×%d" % (
                    route["dungeon_name"], stages[0][0], route["need"])
        elif len(stages) == 1:
            route_text = "可自动：通关%s（%d）×%d" % (
                route["dungeon_name"], stages[0][0], route["need"])
        else:
            route_text = "可自动：入口%d + Boss房%s（%d）×%d" % (
                stages[0][0], route["dungeon_name"], stages[1][0], route["need"])
    else:
        route_text = "暂不自动（非通关型或需点券/多关）"
    app.lbl_side_task_detail.config(
        text="%s（%d）\n状态：%s\n进度：%s\n%s\n等级要求：%s\n前置任务：%s\n关卡：%s\n目标：%s" %
             (row.get("name", "?"), task_id, state, progress, route_text, row.get("level", "?"),
              row.get("preTaskId", "?"), row.get("dungeonId", "?"),
              row.get("targetDescribe") or row.get("describe") or "?"))


def apply_filter(app):
    app._side_task_filter = app.combo_side_task_filter.get() or "可操作"
    rebuild_tree(app, app._side_task_snapshot.get("states", {}),
                 app._side_task_snapshot.get("progress", {}))


def rebuild_tree(app, states, progress=None):
    progress = progress or {}
    selected = selected_id(app)
    for item in app.side_task_tree.get_children():
        app.side_task_tree.delete(item)
    filt = getattr(app, "_side_task_filter", "可操作")
    for task_id, row in sorted(app._side_task_defs.items()):
        state = states.get(task_id, "待读取")
        clearable = bool(clear_route(app, task_id))
        is_operable = state in OPERABLE or state == "待读取"
        if filt == "通关型":
            if not is_operable or not clearable:
                continue
        elif filt == "可操作":
            if not is_operable:
                continue
        elif filt != "全部" and state != filt:
            continue
        app.side_task_tree.insert(
            "", "end", iid=str(task_id),
            values=(task_id, row.get("name", "?"), progress.get(task_id, "-"), state,
                    "通关型" if clearable else "—"))
    if selected is not None and app.side_task_tree.exists(str(selected)):
        app.side_task_tree.selection_set(str(selected))
        app.side_task_tree.see(str(selected))
    on_select(app)


def display_snapshot(app, snapshot):
    if app.current_save is None or app.current_save["index"] != snapshot["slot"]:
        return
    app._side_task_snapshot = snapshot
    counts = snapshot["counts"]
    app.lbl_side_task_summary.config(
        text="槽%d Lv.%d：可接%d · 进行中%d · 可领奖%d · 已完成%d" %
             (snapshot["slot"], snapshot["level"], counts["可接"], counts["进行中"],
              counts["可领奖"], counts["已完成"]))
    rebuild_tree(app, snapshot["states"], snapshot["progress"])


def do_check(app):
    if not app.client or app.current_save is None:
        return
    slot = app.current_save["index"]
    app.btn_side_task_check.config(state="disabled")
    app.lbl_side_task_summary.config(text="正在读取槽%d的支线任务…" % slot)

    def worker():
        flow = None
        try:
            flow, entry, scene = app._connect_and_enter(slot)
            if entry.get("code") != 200 or not scene.get("curRecord"):
                raise RuntimeError("当前槽位没有角色")
            snapshot = make_snapshot(app, scene, slot)
            app.root.after(0, lambda: display_snapshot(app, snapshot))
        except Exception as exc:
            if app.current_save and app.current_save["index"] == slot:
                app._log("[支线任务] 读取失败: %s" % exc)
                app.root.after(0, lambda: reset_display(app))
                app.root.after(0, lambda: app.lbl_side_task_summary.config(text="读取失败，请刷新"))
        finally:
            if flow:
                flow.disconnect()
            app.root.after(0, lambda: app.btn_side_task_check.config(state="normal"))

    threading.Thread(target=worker, daemon=True).start()


def action(app, kind):
    if not app._ensure_login():
        return
    task_id = selected_id(app)
    if task_id is None:
        messagebox.showwarning("提示", "请先选择支线任务")
        return
    status = app._side_task_snapshot.get("states", {}).get(task_id)
    route = clear_route(app, task_id)
    if kind == "accept" and status != "可接":
        messagebox.showwarning("提示", "当前任务状态为%s，不能接取" % (status or "待读取"))
        return
    if kind == "claim" and status != "可领奖":
        messagebox.showwarning("提示", "任务尚未达到可领奖状态")
        return
    if kind == "complete":
        if not route:
            messagebox.showwarning("提示", "该支线需要点券或暂无可自动路线（通关/击杀型）")
            return
        if status not in ("可接", "进行中", "可领奖"):
            messagebox.showwarning("提示", "当前任务状态为%s，不能自动完成" % (status or "待读取"))
            return
    slot = app.current_save["index"]
    side_buttons = (app.btn_side_task_check, app.btn_side_task_accept,
                    app.btn_side_task_complete, app.btn_side_task_claim)
    for button in side_buttons:
        button.config(state="disabled")
    app.combo_save.config(state="disabled")
    app.btn_login.config(state="disabled")

    def worker():
        flow = None
        claimed_items = []
        try:
            from mainfarm_routes import clear_stage
            flow, entry, scene = app._connect_and_enter(slot)
            if entry.get("code") != 200 or not scene.get("curRecord"):
                raise RuntimeError("当前槽位没有角色")
            if kind in ("complete", "claim"):
                require_bag_space(scene)
            if kind == "accept":
                if find_cur(scene, task_id):
                    raise RuntimeError("任务%d已在进行中，无需重复接取" % task_id)
                started = flow.request("scene.taskHandler.startTask", {"taskId": task_id}, timeout=15)
                if started.get("code") != 200:
                    raise RuntimeError("接取任务%d失败: %s" %
                                       (task_id, started.get("error", started.get("code"))))
                app._log("[支线任务] 已接取 %s（%d）" %
                         (app._side_task_defs[task_id].get("name", "?"), task_id))
            if kind == "complete":
                current = find_cur(scene, task_id)
                if current is None:
                    started = flow.request("scene.taskHandler.startTask", {"taskId": task_id}, timeout=15)
                    if started.get("code") != 200:
                        raise RuntimeError("接取任务%d失败: %s" %
                                           (task_id, started.get("error", started.get("code"))))
                    app._log("[支线任务] 已接取 %s（%d）" % (route["name"], task_id))
                    current = {"taskState": 0, "taskData": {"dungeonCnt": 0}}
                if current.get("taskState") != 1:
                    done, need = progress_counts(app, task_id, current)
                    remain = max(0, need - done)
                    stages = route["stages"]
                    stage_text = " → ".join(str(mid) for mid, _ in stages)
                    app._log("[支线任务] %s 自动通关：%s，进度%d/%d，剩余%d次（不计副本掉落）" %
                             (route["name"], stage_text, done, need, remain))
                    try:
                        from zm4_toolbox import NIGHTMARE_LEVELS
                        power_map = {mid: power for mid, _, power in NIGHTMARE_LEVELS}
                    except Exception:
                        power_map = {}
                    round_cost = sum(power_map.get(mid, 0) for mid, _ in stages)
                    baseline_gem = (scene.get("user") or {}).get("gem")
                    for index in range(remain):
                        power_now = int((scene.get("curRecord") or {}).get("collectPower") or 0)
                        if round_cost and power_now < round_cost:
                            raise RuntimeError(
                                "体力不足（%d < %d），已停止；不会消耗点券购买体力" %
                                (power_now, round_cost))
                        for mid, enter_w in stages:
                            clear_stage(flow, scene, mid, enter_w, reward_mode="none",
                                        quest_count=True,
                                        report_kills=route.get("kind") == "boss")
                            app._log("[支线任务] 通关关卡%d（第%d/%d轮）" %
                                     (mid, done + index + 1, need))
                            time.sleep(0.4)
                        flow.disconnect()
                        flow, _, scene = app._connect_and_enter(slot)
                        gem_now = (scene.get("user") or {}).get("gem")
                        if baseline_gem is not None and gem_now != baseline_gem:
                            raise RuntimeError("点券发生变化（%s → %s），已停止" %
                                               (baseline_gem, gem_now))
                    if remain == 0:
                        flow.disconnect()
                        flow, _, scene = app._connect_and_enter(slot)
                    current = find_cur(scene, task_id)
                    if not current or current.get("taskState") != 1:
                        done2, need2 = progress_counts(app, task_id, current)
                        raise RuntimeError(
                            "已提交通关，但任务未变为可领奖（进度%s/%s）。请刷新后检查结算标记。" %
                            (done2, need2))
                should_claim = True
            else:
                should_claim = kind == "claim"
            if should_claim:
                current = find_cur(scene, task_id)
                if not current or current.get("taskState") != 1:
                    flow.disconnect()
                    flow, _, scene = app._connect_and_enter(slot)
                    current = find_cur(scene, task_id)
                if not current or current.get("taskState") != 1:
                    raise RuntimeError("任务%d尚未达到可领奖状态，保留当前进度" % task_id)
                require_bag_space(scene)
                claimed = flow.request("scene.taskHandler.handoverTask", {"taskId": task_id}, timeout=15)
                if claimed.get("code") != 200:
                    raise RuntimeError("任务%d领奖失败: %s" %
                                       (task_id, claimed.get("error", claimed.get("code"))))
                claimed_items = claimed.get("items", [])
                app._log("[支线任务] 任务%d领奖成功：物品%s，经验%s，灵魂%s" %
                         (task_id, claimed_items, claimed.get("addExp", 0),
                          claimed.get("addSpirit", 0)))
            flow.disconnect()
            flow, _, scene = app._connect_and_enter(slot)
            snapshot = make_snapshot(app, scene, slot)
            app.root.after(0, lambda: display_snapshot(app, snapshot))
            if claimed_items:
                bag = scene.get("curRecord", {}).get("itemsBag", {}).get("items", [])
                if isinstance(bag, dict):
                    bag = list(bag.values())
                for reward in claimed_items:
                    reward_id = str(reward.get("id"))
                    count = sum(int(item.get("num", item.get("count", 0)) or 0)
                                for item in bag if isinstance(item, dict)
                                and str(item.get("id")) == reward_id)
                    app._log("[支线任务] 背包核对：道具%s当前%d个" % (reward_id, count))
        except Exception as exc:
            app._log("[支线任务] 操作停止: %s" % exc)
            app.root.after(0, lambda: do_check(app))
        finally:
            if flow:
                flow.disconnect()
            for button in side_buttons:
                app.root.after(0, lambda btn=button: btn.config(state="normal"))
            app.root.after(0, lambda: app.combo_save.config(state="readonly"))
            app.root.after(0, lambda: app.btn_login.config(state="normal"))

    threading.Thread(target=worker, daemon=True).start()
