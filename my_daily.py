"""我的日常独立窗口：从工具箱所有子标签中选择收藏任务，支持排序、单项和批量执行。

收藏按界面标签分组；执行沿用“一键运行”队列，各任务参数仍使用对应页面的设置。
"""
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

# 不是日常执行项的按钮：查询、配置、停止、物品整理等。
NON_TASK_WORDS = ("停止", "刷新", "检测", "读取", "查询", "查看", "打开", "清空", "重置",
                  "保存", "存为", "查找", "加入", "预览", "合并", "存入", "取出", "售出",
                  "购买", "替换", "保留", "洗练", "载入", "粘贴", "删除", "查")

# 不纳入“我的日常”收藏的大标签：入口页、洗练/主线、周本、魔渊、打造刷属性、时光之舟、超值礼包。
EXCLUDED_TABS = ("一键运行", "洗练", "主线刷取", "主线通关", "周本",
                 "魔渊诛邪", "魔渊诛邪（前八层）", "打造刷属性", "时光之舟", "超值礼包",
                 "冰川（熔岩层）", "商店购买", "游戏盒签到（实验）", "联盟药园")

# 个别页面只暴露指定任务，其余按钮不进入收藏目录；元组顺序即收藏目录中的显示/执行顺序。
PAGE_TASK_FILTERS = {
    "一键日常": ("一键日常（部分）",),
    "日常任务": ("任务批量接取1", "任务批量接取2", "任务批量接取3", "一键领取已完成任务"),
    "九转炼丹": ("运行一次",),
    "普通悬赏": ("打满今日次数（自动接取/通关/领奖）",),
    "宠物装备副本": ("宠物副本批量1", "宠物副本批量2", "宠物副本批量3"),
    "坐骑副本": ("坐骑副本批量1", "坐骑副本批量2", "坐骑副本批量3"),
}

SCHEDULE_FILENAME = "my_daily_schedule.json"


def schedule_path(favorites_path):
    return Path(favorites_path).with_name(SCHEDULE_FILENAME)


def load_schedule(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    return {"enabled": bool(data.get("enabled")),
            "time": str(data.get("time") or "08:00"),
            "last_date": str(data.get("last_date") or ""),
            "account": str(data.get("account") or ""),
            "slot": data.get("slot")}


def save_schedule(path, data):
    path = Path(path)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def update_schedule_identity(favorites_path, username, slot):
    """记录上次成功登录的账号与存档槽位，供无人值守自动登录使用。"""
    path = schedule_path(favorites_path)
    data = load_schedule(path)
    data["account"] = username or ""
    data["slot"] = slot
    try:
        save_schedule(path, data)
    except OSError:
        pass


def is_task_label(label):
    """按钮文案是否像一个可收藏的执行任务。"""
    text = (label or "").strip()
    return bool(text) and not any(word in text for word in NON_TASK_WORDS)


def load_favorites(path, allowed):
    """读取收藏与勾选状态；只保留仍然存在的任务，顺序保持不变。"""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], []
    keys = data.get("favorites", []) if isinstance(data, dict) else []
    checked = data.get("checked", []) if isinstance(data, dict) else []
    if not isinstance(keys, list):
        return [], []
    favorites = []
    for key in keys:
        if isinstance(key, str) and key in allowed and key not in favorites:
            favorites.append(key)
    selected = []
    if isinstance(checked, list):
        for key in checked:
            if isinstance(key, str) and key in favorites and key not in selected:
                selected.append(key)
    return favorites, selected


def save_favorites(path, keys, allowed, checked=None):
    """按界面顺序保存收藏；tmp 文件替换，避免写入中断损坏配置。"""
    path = Path(path)
    if checked is None:
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
            checked = previous.get("checked") if isinstance(previous, dict) else None
        except (OSError, ValueError):
            checked = None
    ordered = [key for key in dict.fromkeys(keys) if key in allowed]
    payload = {"favorites": ordered}
    if isinstance(checked, list):
        payload["checked"] = [key for key in dict.fromkeys(checked)
                              if key in ordered]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    temporary.replace(path)


class ButtonTask:
    """把页面按钮包装成“一键运行”队列可执行的项目。"""
    def __init__(self, key, label, button):
        self.key = key
        self.label = label
        self.button = button

    def run(self):
        self.button.invoke()


class DailyEntry:
    """收藏目录中的一项：显示名、所属标签、队列项。"""
    def __init__(self, key, label, button, page, queue_item):
        self.key = key
        self.label = label
        self.button = button
        self.page = page
        self.queue_item = queue_item


class CollapsiblePanel:
    """给 LabelFrame 加可点击标题，支持折叠/展开（参考造五的实现）。"""
    def __init__(self, frame, collapsed=True):
        self.frame = frame
        self.title = str(frame.cget("text"))
        self.collapsed = False
        self.saved = []
        self.height = frame.cget("height")
        self.width = frame.cget("width")
        self.pack_propagate = frame.pack_propagate()
        self.grid_propagate = frame.grid_propagate()
        self.header = ttk.Frame(frame)
        self.button = ttk.Button(self.header, text="▾ " + self.title, command=self.toggle)
        self.button.pack(side="left")
        frame.configure(labelwidget=self.header)
        if collapsed:
            self.set_collapsed(True)

    def toggle(self):
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, value):
        value = bool(value)
        if self.collapsed == value:
            return
        if value:
            self.saved = []
            for child in self.frame.winfo_children():
                if child == self.header:
                    continue
                manager = child.winfo_manager()
                if manager in ("pack", "grid", "place"):
                    self.saved.append((child, manager, getattr(child, manager + "_info")()))
                    getattr(child, manager + "_forget")()
            self.frame.pack_propagate(False)
            self.frame.grid_propagate(False)
            self.frame.configure(height=max(34, self.button.winfo_reqheight() + 10), width=1)
        else:
            self.frame.configure(height=self.height, width=self.width)
            self.frame.pack_propagate(self.pack_propagate)
            self.frame.grid_propagate(self.grid_propagate)
            for child, manager, info in self.saved:
                if child.winfo_exists():
                    getattr(child, manager)(**info)
            self.saved = []
        self.collapsed = value
        self.button.configure(text=("▸ " if value else "▾ ") + self.title)


def page_buttons(page):
    """页面自身的按钮，不包含更深层子标签里的按钮。"""
    buttons = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Notebook):
                continue
            if isinstance(child, ttk.Button):
                buttons.append(child)
            walk(child)

    walk(page)
    return buttons


def child_notebooks(page):
    found = []

    def walk(widget):
        for child in widget.winfo_children():
            if isinstance(child, ttk.Notebook):
                found.append(child)
            else:
                walk(child)

    walk(page)
    return found


def walk_nodes(nodes):
    for node in nodes:
        yield node
        yield from walk_nodes(node["children"])


def node_task_count(node):
    return len(node["entries"]) + sum(node_task_count(child) for child in node["children"])


def discover_tree(app, quick_tasks):
    """遍历工具箱所有标签，返回大标签套小标签的树；顺序与界面一致。"""
    excluded_pages = {str(app.notebook.nametowidget(tab)) for tab in app.notebook.tabs()
                      if app.notebook.tab(tab, "text") in EXCLUDED_TABS}

    def under_excluded(widget):
        while widget is not None:
            if str(widget) in excluded_pages:
                return True
            widget = widget.master
        return False

    tasks = [spec for spec in quick_tasks
             if getattr(app, spec[3], None) is not None
             and not under_excluded(getattr(app, spec[3]))]
    quick_by_widget = {}
    for spec in tasks:
        quick_by_widget[str(getattr(app, spec[3]))] = spec
    used_keys = set()

    def build(notebook, tab, titles):
        try:
            if str(notebook.tab(tab, "state")) == "hidden":
                return None
        except tk.TclError:
            pass
        title = notebook.tab(tab, "text")
        if title in EXCLUDED_TABS:
            return None
        page = notebook.nametowidget(tab)
        parts = list(titles)
        if not parts or parts[-1] != title:
            parts.append(title)
        path = " / ".join(parts)
        entries = []
        counts = {}
        for button in page_buttons(page):
            text = str(button.cget("text")).strip()
            spec = quick_by_widget.get(str(button))
            if spec is not None:
                entries.append(DailyEntry(spec[0], spec[1], button, title, spec))
                continue
            if not is_task_label(text):
                continue
            occurrence = counts.get(text, 0)
            counts[text] = occurrence + 1
            key = "%s::%s#%d" % (path, text, occurrence)
            if key in used_keys:
                key = "%s|%s#%d" % (key, str(page), occurrence)
            used_keys.add(key)
            label = text if occurrence == 0 else "%s（%d）" % (text, occurrence + 1)
            entries.append(DailyEntry(key, label, button, title, ButtonTask(key, label, button)))
        allowed = PAGE_TASK_FILTERS.get(title)
        if allowed is not None:
            order = {label: index for index, label in enumerate(allowed)}
            entries = sorted((entry for entry in entries if entry.label in allowed),
                             key=lambda entry: order[entry.label])
        children = []
        for child_notebook in child_notebooks(page):
            for child_tab in child_notebook.tabs():
                child = build(child_notebook, child_tab, titles + [title])
                if child is not None:
                    children.append(child)
        return {"title": title, "path": path, "entries": entries, "children": children}

    def prune(node):
        """去掉没有任何任务、也没有可用子标签的空页面。"""
        node["children"] = [child for child in node["children"] if prune(child)]
        return bool(node["entries"] or node["children"])

    nodes = []
    for tab in app.notebook.tabs():
        if app.notebook.tab(tab, "text") in EXCLUDED_TABS:
            continue
        node = build(app.notebook, tab, [])
        if node is not None:
            nodes.append(node)
    for node in nodes:
        prune(node)
    found = {entry.key for node in walk_nodes(nodes) for entry in node["entries"]}
    missing = [spec for spec in tasks if spec[0] not in found]
    if missing:
        entries = [DailyEntry(spec[0], spec[1], getattr(app, spec[3], None), "其他任务", spec)
                   for spec in missing]
        nodes.append({"title": "其他任务", "path": "其他任务", "entries": entries, "children": []})
    return nodes


class MyDailyWindow:
    TITLE = "我的日常"

    def __init__(self, app, tasks, path):
        self.app = app
        self.tasks = tuple(tasks)
        self.path = Path(path)
        self.nodes = discover_tree(app, self.tasks)
        self.entries = {entry.key: entry for node in walk_nodes(self.nodes)
                        for entry in node["entries"]}
        self.favorites, checked = load_favorites(self.path, self.entries)
        self._place_claim_after_dungeons(self.favorites)
        self.check_vars = {key: tk.BooleanVar(master=app.root, value=key in checked)
                           for key in self.entries}
        self.schedule = load_schedule(schedule_path(self.path))
        self._auto_running = False
        self.window = None
        self.body = None
        self.status = None
        self.btn_start = None
        self.btn_stop = None
        self._run_buttons = []

    # ---------- 收藏顺序 ----------
    @staticmethod
    def _place_claim_after_dungeons(favorites):
        """领取奖励必须等所有副本打完：排在收藏最后；收藏了活跃度奖励时，活跃度最后、领取倒数第二。"""
        claim = next((key for key in favorites if "一键领取已完成任务" in key), None)
        if not claim:
            return favorites
        liveness = next((key for key in favorites if "领取活跃度" in key), None)
        favorites.remove(claim)
        if liveness:
            favorites.remove(liveness)
            favorites.append(liveness)
            favorites.insert(len(favorites) - 1, claim)
        else:
            favorites.append(claim)
        return favorites

    # ---------- 窗口 ----------
    def _alive(self):
        try:
            return self.window is not None and self.window.winfo_exists()
        except tk.TclError:
            return False

    def _busy(self):
        stop = getattr(self.app, "btn_quick_stop", None)
        try:
            return stop is not None and bool(stop.instate(["!disabled"]))
        except tk.TclError:
            return False

    def open(self):
        if self._alive():
            self.render()
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()
            return
        window = tk.Toplevel(self.app.root)
        self.window = window
        window.title(self.TITLE + " · 造梦西游4 活动工具箱")
        window.geometry("860x600")
        window.minsize(660, 420)
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        self.status = tk.StringVar()
        ttk.Label(window, textvariable=self.status, wraplength=820).pack(anchor="w", padx=12, pady=8)
        bar = ttk.Frame(window)
        bar.pack(fill="x", padx=10)
        ttk.Button(bar, text="管理收藏任务", command=self.manage).pack(side="left", padx=4)
        self.btn_start = ttk.Button(bar, text="执行本窗口所选", command=self.start_selected)
        self.btn_start.pack(side="left", padx=4)
        self.btn_stop = ttk.Button(bar, text="停止后续项目", command=self.app._quick_stop, state="disabled")
        self.btn_stop.pack(side="left", padx=4)
        schedule_bar = ttk.Frame(window)
        schedule_bar.pack(fill="x", padx=10, pady=(6, 0))
        self.var_schedule_enabled = tk.BooleanVar(master=window, value=self.schedule["enabled"])
        ttk.Checkbutton(schedule_bar, text="每天定时执行",
                        variable=self.var_schedule_enabled,
                        command=self._save_schedule).pack(side="left")
        ttk.Label(schedule_bar, text="时间：").pack(side="left", padx=(10, 0))
        self.var_schedule_time = tk.StringVar(master=window, value=self.schedule["time"])
        ttk.Entry(schedule_bar, textvariable=self.var_schedule_time, width=7).pack(side="left")
        ttk.Button(schedule_bar, text="保存定时", command=self._save_schedule).pack(side="left", padx=6)
        ttk.Button(schedule_bar, text="创建Windows计划任务",
                   command=self._create_windows_task).pack(side="left", padx=6)
        self.lbl_schedule_info = ttk.Label(window, text="", foreground="#666", wraplength=820)
        self.lbl_schedule_info.pack(anchor="w", padx=12, pady=(2, 0))
        self._refresh_schedule_label()
        ttk.Label(window, text="仅执行收藏且勾选的项目；点击“打开设置”可跳到对应页面调整参数。",
                  wraplength=820).pack(anchor="w", padx=12, pady=8)
        area = ttk.Frame(window)
        area.pack(fill="both", expand=True, padx=10, pady=6)
        canvas = tk.Canvas(area, highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        self.body = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        self.render()
        self.tick()

    def render(self):
        if not self._alive():
            return
        for child in self.body.winfo_children():
            child.destroy()
        self._run_buttons = []
        favorites = [key for key in self.favorites if key in self.entries]
        if not favorites:
            ttk.Label(self.body, text="还没有收藏任务，点击“管理收藏任务”从各标签中选择。").pack(
                anchor="w", padx=8, pady=18)
            return
        busy = self._busy()
        for index, key in enumerate(favorites):
            entry = self.entries[key]
            row = ttk.Frame(self.body, padding=5, relief="groove")
            row.pack(fill="x", padx=4, pady=3)
            header = ttk.Frame(row)
            header.pack(fill="x")
            for text, direction in (("↑", -1), ("↓", 1)):
                move_button = ttk.Button(header, text=text, width=3,
                                         command=lambda k=key, d=direction: self.move(k, d))
                move_button.pack(side="left", padx=1)
                if not 0 <= index + direction < len(favorites):
                    move_button.config(state="disabled")
            ttk.Checkbutton(header, text="执行", variable=self.check_vars[key],
                            command=lambda k=key: self._check_changed(k)).pack(side="left", padx=6)
            ttk.Label(header, text=entry.label, font=("微软雅黑", 10, "bold")).pack(side="left", padx=4)
            settings_button = ttk.Button(header, text="打开设置",
                                         command=lambda k=key: self.open_settings(k))
            settings_button.pack(side="right", padx=3)
            if not self._page_chain(key):
                settings_button.config(state="disabled")
            run_button = ttk.Button(header, text="单独执行",
                                    command=lambda k=key: self.execute([k]))
            run_button.pack(side="right", padx=3)
            if busy:
                run_button.config(state="disabled")
            self._run_buttons.append(run_button)
            page = self._page_title(key) or entry.page
            ttk.Label(row, text="设置页：%s" % (page or "未找到对应页面"),
                      foreground="#666").pack(anchor="w", padx=28, pady=(2, 0))

    # ---------- 设置页导航 ----------
    def _page_chain(self, key):
        """从任务按钮向上找出各级标签页：[(notebook, 页面), ...]，最内层在前。"""
        entry = self.entries.get(key)
        widget = entry.button if entry else None
        chain = []
        while widget is not None and widget.master is not None:
            parent = widget.master
            if isinstance(parent, ttk.Notebook):
                chain.append((parent, str(widget)))
            widget = parent
        return chain

    def _page_title(self, key):
        chain = self._page_chain(key)
        if not chain:
            return ""
        try:
            return chain[0][0].tab(chain[0][1], "text")
        except tk.TclError:
            return ""

    def open_settings(self, key):
        chain = self._page_chain(key)
        if not chain:
            messagebox.showinfo(self.TITLE, "暂时找不到该任务的设置页面。", parent=self.window)
            return
        for notebook, page in reversed(chain):
            notebook.select(page)
        self.app.root.deiconify()
        self.app.root.lift()
        self.app.root.focus_force()

    # ---------- 定时执行 ----------
    def _check_changed(self, key=None):
        try:
            save_favorites(self.path, self.favorites, self.entries,
                           [k for k, variable in self.check_vars.items() if variable.get()])
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.window)

    def _refresh_schedule_label(self):
        if not self.schedule["enabled"]:
            text = "定时未启用；勾选并保存时间后，每天到点自动登录并执行勾选项目。"
        else:
            text = "每天 %s 自动执行；上次执行日期：%s" % (
                self.schedule["time"], self.schedule["last_date"] or "无")
        self.lbl_schedule_info.config(text=text)

    def _save_schedule(self):
        value = self.var_schedule_time.get().strip()
        try:
            datetime.strptime(value, "%H:%M")
        except ValueError:
            messagebox.showwarning(self.TITLE, "时间格式应为 HH:MM，例如 08:30。",
                                   parent=self.window)
            return False
        self.schedule["enabled"] = bool(self.var_schedule_enabled.get())
        self.schedule["time"] = value
        try:
            save_schedule(schedule_path(self.path), self.schedule)
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.window)
            return False
        self._refresh_schedule_label()
        return True

    def _create_windows_task(self):
        if not self._save_schedule():
            return
        program = Path(sys.argv[0]).resolve()
        if getattr(sys, "frozen", False):
            command = '"%s" --schedule-run' % sys.executable
        else:
            pythonw = Path(sys.executable).with_name("pythonw.exe")
            interpreter = pythonw if pythonw.exists() else Path(sys.executable)
            command = '"%s" "%s" --schedule-run' % (interpreter, program)
        task_name = "ZM4_Toolbox_MyDaily"
        subprocess.run(["schtasks", "/Delete", "/TN", task_name, "/F"],
                       capture_output=True, text=True)
        result = subprocess.run(
            ["schtasks", "/Create", "/SC", "DAILY", "/TN", task_name,
             "/TR", command, "/ST", self.schedule["time"], "/F"],
            capture_output=True, text=True)
        if result.returncode == 0:
            messagebox.showinfo(
                self.TITLE,
                "已创建计划任务：%s，每天 %s 启动工具箱并执行勾选项目。\n"
                "计划任务需要管理员权限；若创建失败，请用管理员身份运行工具箱。"
                % (task_name, self.schedule["time"]), parent=self.window)
        else:
            messagebox.showerror(
                "创建计划任务失败",
                (result.stderr or result.stdout or "未知错误").strip(),
                parent=self.window)

    def auto_run(self, quit_after=False):
        """计划任务或工具箱定时器入口：自动登录后执行勾选项目。"""
        if self._auto_running or self._busy():
            return
        self._auto_running = True
        self.app._schedule_quit_on_fail = quit_after

        def start():
            self._auto_running = False
            if not self._alive():
                self.open()
            self.render()
            keys = self.selected()
            if not keys:
                self.app._log("[我的日常] 定时执行跳过：没有勾选的收藏任务")
                if quit_after:
                    self.app.root.after(1000, self.app._close_toolbox)
                return
            self.execute(keys, quit_after=quit_after)

        self.app._schedule_ensure_login(start)

    # ---------- 收藏与排序 ----------
    def move(self, key, direction):
        if self._busy() or key not in self.favorites:
            return
        index = self.favorites.index(key)
        destination = index + direction
        if not 0 <= destination < len(self.favorites):
            return
        favorites = list(self.favorites)
        favorites[index], favorites[destination] = favorites[destination], favorites[index]
        try:
            save_favorites(self.path, favorites, self.entries)
        except OSError as exc:
            messagebox.showerror("排序保存失败", str(exc), parent=self.window)
            return
        self.favorites = favorites
        self.render()

    def manage(self):
        if not self._alive():
            return
        dialog = tk.Toplevel(self.window)
        dialog.title("管理" + self.TITLE)
        dialog.geometry("720x600")
        dialog.transient(self.window)
        ttk.Label(dialog, text="点击分组标题可展开或收起；勾选要加入我的日常的任务。",
                  foreground="#666").pack(anchor="w", padx=10, pady=(10, 0))
        states = getattr(self, "_manage_collapse", {})
        self._manage_collapse = states
        panels = []
        toolbar = ttk.Frame(dialog)
        toolbar.pack(fill="x", padx=10, pady=(6, 0))

        def set_all(collapsed):
            for path, panel in panels:
                panel.set_collapsed(collapsed)
                states[path] = panel.collapsed

        ttk.Button(toolbar, text="全部展开", command=lambda: set_all(False)).pack(side="left", padx=3)
        ttk.Button(toolbar, text="全部折叠", command=lambda: set_all(True)).pack(side="left", padx=3)
        area = ttk.Frame(dialog)
        area.pack(fill="both", expand=True, padx=10, pady=4)
        canvas = tk.Canvas(area, highlightthickness=0)
        scroll = ttk.Scrollbar(area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(canvas)
        item = canvas.create_window(0, 0, window=body, anchor="nw")
        body.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(item, width=event.width))
        check_vars = {}

        def draw_group(parent, node, depth):
            frame = ttk.LabelFrame(parent, text="%s（%d项）" % (node["title"], node_task_count(node)),
                                   padding=6)
            frame.pack(fill="x", padx=(depth * 10, 0), pady=4)
            if node["entries"]:
                grid = ttk.Frame(frame)
                grid.pack(fill="x")
                for index, entry in enumerate(node["entries"]):
                    variable = tk.BooleanVar(master=dialog, value=entry.key in self.favorites)
                    check_vars[entry.key] = variable
                    ttk.Checkbutton(grid, text=entry.label, variable=variable).grid(
                        row=index // 2, column=index % 2, sticky="w", padx=8, pady=4)
            elif not node["children"]:
                ttk.Label(frame, text="（暂无可收藏任务）", foreground="#999").pack(anchor="w", padx=6)
            for child in node["children"]:
                draw_group(frame, child, depth + 1)
            path = node["path"]
            panel = CollapsiblePanel(frame, collapsed=states.get(path, True))
            panels.append((path, panel))

            def toggle(path=path, panel=panel):
                panel.toggle()
                states[path] = panel.collapsed

            panel.button.configure(command=toggle)

        for node in self.nodes:
            draw_group(body, node, 0)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", pady=8)

        def save():
            chosen = [entry.key for node in walk_nodes(self.nodes) for entry in node["entries"]
                      if check_vars[entry.key].get()]
            favorites = [key for key in self.favorites if key in chosen]
            favorites += [key for key in chosen if key not in favorites]
            self._place_claim_after_dungeons(favorites)
            try:
                save_favorites(self.path, favorites, self.entries)
            except OSError as exc:
                messagebox.showerror("保存失败", str(exc), parent=dialog)
                return
            added = [key for key in favorites if key not in self.favorites]
            self.favorites = favorites
            for key in added:
                self.check_vars[key].set(True)
            self._check_changed()
            self.render()
            dialog.destroy()

        ttk.Button(buttons, text="保存收藏", command=save).pack(side="right", padx=4)
        ttk.Button(buttons, text="取消", command=dialog.destroy).pack(side="right", padx=4)

    # ---------- 执行 ----------
    def selected(self):
        return [key for key in self.favorites
                if key in self.entries and self.check_vars[key].get()]

    def start_selected(self):
        self.execute(self.selected())

    def execute(self, keys, quit_after=False):
        keys = [key for key in keys if key in self.entries]
        if not keys:
            messagebox.showinfo(self.TITLE, "请先勾选要执行的收藏任务。", parent=self.window)
            if quit_after:
                self.app.root.after(1000, self.app._close_toolbox)
            return
        if quit_after:
            self.app._quick_quit_after = True
        started = self.app._start_quick_queue(
            [self.entries[key].queue_item for key in keys], self.TITLE)
        if not started:
            self.app._quick_quit_after = False
            if quit_after:
                self.app.root.after(1000, self.app._close_toolbox)

    def tick(self):
        if not self._alive():
            return
        busy = self._busy()
        account = self.app.lbl_status.cget("text")
        save = self.app.save_var.get() or "未选择存档"
        detail = self.app.lbl_quick_status.cget("text") if busy else "空闲"
        self.status.set("%s｜存档：%s｜%s" % (account, save, detail))
        for button in self._run_buttons:
            if button.winfo_exists():
                button.config(state="disabled" if busy else "normal")
        if self.btn_start is not None:
            self.btn_start.config(state="disabled" if busy else "normal")
        if self.btn_stop is not None:
            self.btn_stop.config(state="normal" if busy else "disabled")
        self.window.after(300, self.tick)
