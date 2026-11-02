"""主线坐骑隐藏关：免费捕获与资质筛选。"""
import json
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

TARGETS = ((1003, 1000400), (1005, 1000500), (1010, 1000700))
FIELDS = (("生命", "hpQualification"), ("攻击", "atkQualification"), ("防御", "defQualification"))

def horse_list(scene):
    rows = (scene.get("curRecord", {}).get("horseList") or {}).get("horses") or []
    if isinstance(rows, dict):
        rows = rows.values()
    return {str(row["entityId"]): row for row in rows if row.get("entityId")}

def capture_once(flow, mid):
    if mid not in {row[0] for row in TARGETS}:
        raise ValueError("未确认的坐骑隐藏关")
    created = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=20)
    if created.get("code") != 200:
        raise RuntimeError(created.get("error", "进入坐骑隐藏关失败"))
    time.sleep(1)
    response = flow.request("scene.animalHandler.catchHorse", {"cType": 1, "copyId": mid}, timeout=20)
    if response.get("code") != 200:
        raise RuntimeError(response.get("error", "捕获请求失败"))
    return response

def meets_qualifications(horse, minimums):
    return all(field in horse and int(horse[field]) >= threshold for field, threshold in minimums.items())

def build_capture_tab(app):
    configs = json.loads((Path(__file__).resolve().parent / "output_cg1_20260921_1_2" / "086___Horse.xml.json").read_text(encoding="utf-8"))["RECORD"]
    configs = {int(row["id"]): row for row in configs}
    tab = ttk.Frame(app.mainfarm_notebook, padding=10)
    app.mainfarm_notebook.add(tab, text="隐藏关抓坐骑")
    settings = ttk.LabelFrame(tab, text="捕获设置", padding=8)
    settings.pack(fill="x")
    app.var_horse_capture_target = tk.StringVar(value=str(TARGETS[0][0]))
    labels = {"%s（隐藏关%d）" % (configs[hid]["name"], mid): (mid, hid) for mid, hid in TARGETS}
    choice = ttk.Combobox(settings, values=list(labels), state="readonly", width=28)
    choice.grid(row=0, column=0, columnspan=2, sticky="w", pady=4)
    choice.current(0)
    app.var_horse_capture_times = tk.IntVar(value=10)
    app.var_horse_capture_delay = tk.DoubleVar(value=2)
    ttk.Label(settings, text="最多尝试次数").grid(row=1, column=0, sticky="w")
    ttk.Spinbox(settings, from_=1, to=10000, textvariable=app.var_horse_capture_times, width=10).grid(row=1, column=1)
    ttk.Label(settings, text="两次间隔（秒）").grid(row=2, column=0, sticky="w")
    ttk.Spinbox(settings, from_=1, to=60, textvariable=app.var_horse_capture_delay, width=10).grid(row=2, column=1)
    app.var_horse_capture_filter = tk.BooleanVar(value=False)
    ttk.Checkbutton(settings, text="启用资质筛选，达到全部条件后停止", variable=app.var_horse_capture_filter).grid(row=3, column=0, columnspan=3, sticky="w", pady=5)
    app.horse_capture_minimums = {field: tk.IntVar(value=0) for _, field in FIELDS}
    for index, (label, field) in enumerate(FIELDS, start=4):
        ttk.Label(settings, text=label + "资质至少").grid(row=index, column=0, sticky="w")
        ttk.Spinbox(settings, from_=0, to=10000, textvariable=app.horse_capture_minimums[field], width=10).grid(row=index, column=1)
    hint = ttk.Label(settings, wraplength=680, foreground="gray")
    hint.grid(row=7, column=0, columnspan=4, sticky="w", pady=5)
    def update_hint(event=None):
        mid, hid = labels[choice.get()]
        app.var_horse_capture_target.set(str(mid))
        row = configs[hid]
        hint.config(text="初始资质范围：" + "；".join("%s %s" % (label, row[field].replace(";", "～")) for label, field in FIELDS) + "。只用免费捕获；未达标的坐骑仍保留。")
    choice.bind("<<ComboboxSelected>>", update_hint)
    def restore_choice(event=None):
        choice.set(next((label for label, (mid, _) in labels.items() if str(mid) == app.var_horse_capture_target.get()), list(labels)[0]))
        update_hint()
    choice.bind("<Map>", restore_choice)
    update_hint()
    result = ttk.Treeview(tab, columns=("attempt", "name", "hp", "atk", "def", "status", "entity"), show="headings", height=10)
    for field, title, width in (("attempt", "次数", 60), ("name", "坐骑", 100), ("hp", "生命资质", 90), ("atk", "攻击资质", 90), ("def", "防御资质", 90), ("status", "结果", 160), ("entity", "坐骑编号", 130)):
        result.heading(field, text=title)
        result.column(field, width=width)
    scroll = ttk.Scrollbar(tab, orient="vertical", command=result.yview)
    result.configure(yscrollcommand=scroll.set)
    actions = ttk.Frame(tab)
    actions.pack(fill="x", pady=6)
    stop_event = threading.Event()
    def run():
        if not app._ensure_login():
            return
        try:
            mid, hid = labels[choice.get()]
            maximum, delay = app.var_horse_capture_times.get(), app.var_horse_capture_delay.get()
            use_filter = app.var_horse_capture_filter.get()
            minimums = {field: var.get() for field, var in app.horse_capture_minimums.items()} if use_filter else {}
            if maximum < 1 or delay < 1:
                raise ValueError("次数至少1，间隔至少1秒")
            if any(value < 0 or value > int(configs[hid][field].split(";")[1]) for field, value in minimums.items()):
                raise ValueError("最低资质不能超过所选坐骑的初始资质上限")
        except (ValueError, tk.TclError) as error:
            messagebox.showwarning("设置有误", str(error))
            return
        stop_event.clear()
        app.btn_horse_capture_run.config(state="disabled")
        app.btn_horse_capture_stop.config(state="normal")
        for item in result.get_children():
            result.delete(item)
        save_index = app.current_save["index"]
        def worker():
            flow = None
            caught = {}
            try:
                flow, _, scene = app._connect_and_enter(save_index)
                baseline = dict(scene["user"])
                existing = horse_list(scene)
                capacity = int(scene["curRecord"]["horseList"]["itemCount"])
                for number in range(1, maximum + 1):
                    if stop_event.is_set():
                        break
                    if len(existing) + len(caught) >= capacity:
                        app._log("[坐骑捕获] 坐骑栏已满，停止")
                        break
                    response = capture_once(flow, mid)
                    horse = response.get("horse")
                    if horse:
                        entity = str(horse.get("entityId", ""))
                        if not entity or entity in existing or entity in caught or int(horse.get("id", 0)) != hid:
                            raise RuntimeError("服务器返回的坐骑身份异常，已停止")
                        matched = meets_qualifications(horse, minimums)
                        caught[entity] = horse
                        values = (number, configs[hid]["name"], *(horse.get(field, "?") for _, field in FIELDS), "已捕获，待重登核验" if matched else "未达标，已保留", entity)
                        app.root.after(0, lambda v=values, e=entity: result.insert("", "end", iid=e, values=v))
                        app._log("[坐骑捕获] %s，资质%s，%s" % (configs[hid]["name"], "/".join(str(horse.get(field, "?")) for _, field in FIELDS), "达标" if matched else "未达标，保留"))
                        if matched:
                            break
                    else:
                        app._log("[坐骑捕获] 第%d次：%s" % (number, response.get("error", "未捕获")))
                    if number < maximum and stop_event.wait(delay):
                        break
                flow.disconnect()
                flow = None
                flow, _, after = app._connect_and_enter(save_index)
                persisted = horse_list(after)
                if any(baseline.get(key) != after["user"].get(key) for key in ("gem", "usedGem")):
                    raise RuntimeError("重登发现点券变化，请检查")
                for entity, horse in caught.items():
                    saved = persisted.get(entity)
                    if not saved or any(saved.get(field) != horse.get(field) for _, field in FIELDS):
                        raise RuntimeError("坐骑或资质未通过重登核验")
                    status = "已保存，达标" if meets_qualifications(horse, minimums) else "已保存，未达标保留"
                    app.root.after(0, lambda e=entity, s=status: result.set(e, "status", s))
                app._log("[坐骑捕获] 重登确认新增%d只，点券未消耗" % len(caught))
            except Exception as error:
                app._log("[坐骑捕获] 已停止：%s" % error)
            finally:
                if flow:
                    flow.disconnect()
                app.root.after(0, lambda: app.btn_horse_capture_run.config(state="normal"))
                app.root.after(0, lambda: app.btn_horse_capture_stop.config(state="disabled"))
        threading.Thread(target=worker, daemon=True).start()
    app.btn_horse_capture_run = ttk.Button(actions, text="开始免费捕获", command=run, state="disabled")
    app.btn_horse_capture_run.pack(side="left", padx=4)
    app.btn_horse_capture_stop = ttk.Button(actions, text="停止（完成当前次）", command=stop_event.set, state="disabled")
    app.btn_horse_capture_stop.pack(side="left", padx=4)
    scroll.pack(side="right", fill="y")
    result.pack(fill="both", expand=True)
