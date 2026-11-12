"""羽毛背包：查看羽毛词条，按品质批量分解为羽枝。"""
import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

MELT_ITEM_ID = 172300001
# 6 级是上古羽毛、7 级不可分解，批量分解一律禁止。
BLOCKED_QUALITY = 6
CONFIG_FOLDERS = ('output_cg1_20260921_1_2', 'upcoming_assets_20261102/config_unpacked',
                  'config_review_20261012_2/decoded')

QUALITY_NAMES = {1: "1级", 2: "2级", 3: "3级", 4: "4级", 6: "6级(上古)", 7: "7级"}
ATTR_NAMES = {
    "atk": "攻击", "hpMax": "生命", "mpMax": "魔法", "phyDef": "物防",
    "magRes": "魔抗", "reduceMagDef": "减魔防", "hit": "命中", "dodge": "闪避",
    "critical": "暴击", "toughness": "韧性", "lucky": "幸运", "guardian": "守护",
    "reHP": "回血", "reMP": "回魔", "suckBlood": "吸血", "backLash": "反伤",
    "soar": "翱翔", "sprint": "疾行",
}
PERCENT_ATTRS = {"magRes", "reduceMagDef", "hit", "dodge", "critical", "toughness"}


def _records(name):
    root = Path(__file__).resolve().parent
    for folder in CONFIG_FOLDERS:
        path = root / folder / name
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8-sig'))['RECORD']
    raise RuntimeError('缺少配置：' + name)


def feather_config():
    return {int(row['id']): row for row in _records('057___Feather.xml.json')}


def _number(value):
    if isinstance(value, float):
        if abs(value) >= 100:
            return '%d' % value
        return ('%.4f' % value).rstrip('0').rstrip('.')
    return str(value)


def _attr_text(item):
    parts = []
    for key, value in item.items():
        if key not in ATTR_NAMES:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if not value:
            continue
        name = ATTR_NAMES[key]
        if key in PERCENT_ATTRS:
            parts.append('%s+%s%%' % (name, _number(round(value * 100, 2))))
        else:
            parts.append('%s+%s' % (name, _number(value)))
    return ' '.join(parts) or '无词条'


class FeatherBagPage:
    def _build_feather_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="羽毛背包")
        ttk.Label(tab, text="羽毛背包独立于道具背包；已镶嵌的羽毛在翅膀里，不会出现在这里。"
                            "分解产物统一为「羽枝」，用于重置羽毛属性。",
                  wraplength=900).pack(anchor="w")
        ttk.Label(tab, text="批量分解默认只勾选 1~2 级；6 级（上古）和 7 级禁止批量分解。分解不可撤销。",
                  foreground="gray", wraplength=900).pack(anchor="w", pady=(2, 8))

        self._feather_config = feather_config()
        quality_bar = ttk.Frame(tab)
        quality_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(quality_bar, text="按品质选中：").pack(side="left")
        self._feather_quality_vars = {}
        for quality in sorted({int(row.get('quality') or 0) for row in self._feather_config.values()}):
            variable = tk.BooleanVar(value=quality in (1, 2))
            check = ttk.Checkbutton(quality_bar, text=QUALITY_NAMES.get(quality, '%d级' % quality),
                                    variable=variable)
            if quality >= BLOCKED_QUALITY:
                check.config(state="disabled")
            check.pack(side="left", padx=3)
            self._feather_quality_vars[quality] = variable

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=6)
        self._feather_buttons = []
        for title, action in (("刷新状态", self._feather_refresh),
                              ("按品质选中", self._feather_select_by_quality),
                              ("全选", self._feather_select_all),
                              ("清空选择", self._feather_clear_selection),
                              ("一键分解选中", self._feather_decompose_selected)):
            button = ttk.Button(bar, text=title, command=action)
            button.pack(side="left", padx=4)
            self._feather_buttons.append(button)

        self._feather_status = tk.StringVar(value="登录并选择存档后点击「刷新状态」")
        ttk.Label(tab, textvariable=self._feather_status, justify="left",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", pady=6)

        table = ttk.Frame(tab)
        table.pack(fill="both", expand=True)
        self._feather_tree = ttk.Treeview(
            table, columns=("quality", "name", "attrs", "gain"),
            show="headings", selectmode="extended", height=16)
        for key, label, width, anchor in (("quality", "品质", 70, "center"),
                                          ("name", "羽毛", 120, "w"),
                                          ("attrs", "词条", 480, "w"),
                                          ("gain", "分解可得", 110, "center")):
            self._feather_tree.heading(key, text=label)
            self._feather_tree.column(key, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self._feather_tree.yview)
        self._feather_tree.configure(yscrollcommand=scroll.set)
        self._feather_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._feather_tree.bind("<<TreeviewSelect>>", lambda _event: self._feather_update_status())

        self._feather_busy = False
        self._feather_rows = {}
        self._feather_last = None

    def _feather_set_busy(self, busy):
        self._feather_busy = busy
        for button in self._feather_buttons:
            button.config(state="disabled" if busy else "normal")

    def _feather_selected(self):
        return [self._feather_rows[iid] for iid in self._feather_tree.selection()
                if iid in self._feather_rows]

    def _feather_update_status(self):
        snapshot = self._feather_last
        if not snapshot:
            return
        selected = self._feather_selected()
        gain = sum(row["resolve"] for row in selected if row["resolve"] > 0
                   and row["quality"] < BLOCKED_QUALITY)
        self._feather_status.set(
            "背包 %d/%d，剩余 %d 格 ｜ 共 %d 根 ｜ 已选 %d 根，预计获得羽枝 ×%d"
            % (len(snapshot["items"]), snapshot["itemCount"], snapshot["freeCount"],
               len(snapshot["items"]), len(selected), gain))

    @staticmethod
    def _feather_snapshot(entry, scene):
        record = scene.get("curRecord") or {}
        bag = record.get("featherBag") or (entry.get("record") or {}).get("featherBag") or {}
        items = bag.get("items") or []
        if isinstance(items, dict):
            items = list(items.values())
        return {"items": [row for row in items if isinstance(row, dict)],
                "itemCount": int(bag.get("itemCount") or 0),
                "freeCount": int(bag.get("freeCount") or 0)}

    def _feather_refresh(self):
        if not self._ensure_login() or self._feather_busy:
            return
        self._feather_set_busy(True)
        threading.Thread(target=self._feather_refresh_worker, daemon=True).start()

    def _feather_refresh_worker(self):
        flow = None
        try:
            flow, entry, scene = self._connect_and_enter()
            snapshot = self._feather_snapshot(entry, scene)
            self.root.after(0, lambda s=snapshot: self._feather_render(s))
            self._log("[羽毛] 背包 %d/%d，剩余 %d 格"
                      % (len(snapshot["items"]), snapshot["itemCount"], snapshot["freeCount"]))
        except Exception as error:
            text = str(error)
            self._log("[羽毛] 刷新失败：" + text)
            self.root.after(0, lambda t=text: self._feather_status.set("刷新失败：" + t))
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self._feather_set_busy(False))

    def _feather_render(self, snapshot):
        self._feather_last = snapshot
        self._feather_rows = {}
        self._feather_tree.delete(*self._feather_tree.get_children())
        for item in snapshot["items"]:
            entity = str(item.get("entityId") or "")
            if not entity:
                continue
            try:
                config = self._feather_config.get(int(item.get("id") or 0)) or {}
            except (TypeError, ValueError):
                config = {}
            quality = int(config.get("quality") or 0)
            resolve = int(config.get("resolveNum") or 0)
            if not config:
                quality_text, gain_text = "未知", "不可分解"
            elif resolve <= 0:
                quality_text, gain_text = QUALITY_NAMES.get(quality, '%d级' % quality), "不可分解"
            else:
                quality_text = QUALITY_NAMES.get(quality, '%d级' % quality)
                gain_text = "羽枝 ×%d" % resolve
            row = {"entityId": entity, "quality": quality, "resolve": resolve,
                   "name": config.get("name") or str(item.get("id")), "itemId": item.get("id")}
            self._feather_rows[entity] = row
            self._feather_tree.insert("", "end", iid=entity, values=(
                quality_text, row["name"], _attr_text(item), gain_text))
        if not snapshot["items"]:
            self._feather_status.set("羽毛背包为空")
        else:
            self._feather_update_status()

    def _feather_select_by_quality(self):
        if not self._feather_last:
            messagebox.showinfo("羽毛背包", "请先刷新状态")
            return
        chosen = {quality for quality, variable in self._feather_quality_vars.items()
                  if variable.get()}
        targets = [iid for iid, row in self._feather_rows.items()
                   if row["quality"] in chosen and row["resolve"] > 0
                   and row["quality"] < BLOCKED_QUALITY]
        self._feather_tree.selection_set(*targets)
        self._feather_update_status()

    def _feather_select_all(self):
        self._feather_tree.selection_set(*list(self._feather_rows))
        self._feather_update_status()

    def _feather_clear_selection(self):
        current = self._feather_tree.selection()
        if current:
            self._feather_tree.selection_remove(*current)
        self._feather_update_status()

    def _feather_decompose_selected(self):
        if not self._ensure_login() or self._feather_busy:
            return
        selected = self._feather_selected()
        if not selected:
            messagebox.showinfo("羽毛背包", "请先选择要分解的羽毛")
            return
        blocked = [row for row in selected
                   if row["quality"] >= BLOCKED_QUALITY or row["resolve"] <= 0]
        targets = [row for row in selected if row not in blocked]
        if not targets:
            messagebox.showinfo("无法分解",
                                "所选羽毛都不支持批量分解：6 级以上或分解产物为 0。")
            return
        gain = sum(row["resolve"] for row in targets)
        lines = ["%s（%s → 羽枝×%d）" % (row["name"], QUALITY_NAMES.get(row["quality"], row["quality"]),
                                       row["resolve"]) for row in targets[:10]]
        if len(targets) > 10:
            lines.append("……共 %d 根" % len(targets))
        text = ("将分解 %d 根羽毛，获得羽枝 ×%d：\n\n%s" % (len(targets), gain, "\n".join(lines)))
        if blocked:
            text += ("\n\n以下 %d 根不处理：%s"
                     % (len(blocked), "、".join(row["name"] for row in blocked[:8])))
        text += "\n\n分解不可撤销，确认继续？"
        if not messagebox.askyesno("确认分解羽毛", text):
            return
        self._feather_set_busy(True)
        threading.Thread(target=self._feather_decompose_worker, args=(targets,),
                         daemon=True).start()

    def _feather_decompose_worker(self, targets):
        flow = None
        try:
            flow, entry, scene = self._connect_and_enter()
            snapshot = self._feather_snapshot(entry, scene)
            present = {str(row.get("entityId")) for row in snapshot["items"]}
            done = failed = total = 0
            for row in targets:
                entity = row["entityId"]
                if entity not in present:
                    self._log("[羽毛] %s 已不在背包，跳过" % row["name"])
                    continue
                result = flow.request("scene.equipSecondHandler.disassembledFeather",
                                      {"eId": entity, "quality": row["quality"]}, timeout=20)
                if result.get("code") != 200:
                    failed += 1
                    self._log("[羽毛] 分解 %s 失败：%s"
                              % (row["name"], result.get("error") or result.get("code")))
                    continue
                add = int(result.get("addNum") or 0)
                total += add
                done += 1
                self._log("[羽毛] 分解 %s，获得羽枝 ×%d" % (row["name"], add))
                time.sleep(0.12)
            self._log("[羽毛] 本次分解 %d 根，失败 %d 根，共获得羽枝 ×%d"
                      % (done, failed, total))
            flow.disconnect()
            flow = None
            flow, entry, scene = self._connect_and_enter()
            snapshot = self._feather_snapshot(entry, scene)
            self.root.after(0, lambda s=snapshot: self._feather_render(s))
        except Exception as error:
            text = str(error)
            self._log("[羽毛] 分解失败：" + text)
            self.root.after(0, lambda t=text: self._feather_status.set("分解失败：" + t))
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self._feather_set_busy(False))
