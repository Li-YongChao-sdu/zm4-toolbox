"""已核对客户端路由的限时活动页面。"""
import json
import os
import threading
import time
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import ttk, messagebox


def _mode_dungeon(modes, value):
    """兼容历史配置里保存的旧难度文案：按关卡号或名字归一到当前选项。"""
    if value in modes:
        return modes[value]
    for key, mid in modes.items():
        if str(mid) in str(value) or str(value) in str(key):
            return mid
    raise RuntimeError("难度选项“%s”已失效，请在难度下拉框重新选择" % value)


class LimitedActivityPages:
    def _build_million_soul_tab(self):
        tab = self._limited_page("国庆签到·千万灵魂", padding=12)
        ttk.Label(tab, text="免费每日签到；签到奖励与最终灵魂分别领取。领取最终灵魂后，本期活动结束。",
                  wraplength=850).pack(anchor="w", pady=8)
        bar = ttk.Frame(tab); bar.pack(fill="x", pady=8)
        self._million_buttons = []
        for title, action in (("刷新签到状态", "refresh"), ("今日免费签到", "sign"),
                              ("领取签到奖励", "extra"), ("领取最终灵魂", "reward")):
            button = ttk.Button(bar, text=title, command=lambda a=action: self._limited_action("million", a))
            button.pack(side="left", padx=5)
            self._million_buttons.append(button)
        self._million_status = tk.StringVar(value="登录后点击刷新签到状态")
        ttk.Label(tab, textvariable=self._million_status, wraplength=850, justify="left").pack(anchor="w", pady=12)

    def _build_pet_collect_tab(self):
        tab = self._limited_page("宠物加速养成", padding=12)
        ttk.Label(tab, text="宠物采集宠装强化材料：每天最多3次，每次120分钟，完成后免费领取。\n"
                            "「按上次宠物再次派遣」会先免费领取全部已完成采集，再按上次记录派遣最多3只（可自动补位）。",
                  wraplength=850).pack(anchor="w", pady=8)
        bar = ttk.Frame(tab); bar.pack(fill="x", pady=8)
        self._pet_collect_buttons = []
        for title, action in (("刷新宠物与采集", "refresh"), ("派遣采集", "begin"), ("领取选中采集", "claim"), ("一键领取", "claimall"), ("按上次宠物再次派遣", "rebegin")):
            button = ttk.Button(bar, text=title, command=lambda a=action: self._limited_action("petcollect", a))
            button.pack(side="left", padx=5); self._pet_collect_buttons.append(button)
        form = ttk.Frame(tab); form.pack(fill="x", pady=8)
        ttk.Label(form, text="宠物：").grid(row=0, column=0)
        self._collect_pet_choice = ttk.Combobox(form, state="readonly", width=35)
        self._collect_pet_choice.grid(row=0, column=1, padx=6)
        ttk.Label(form, text="材料：").grid(row=0, column=2)
        self._collect_prop_choice = ttk.Combobox(form, state="readonly", width=26,
            values=("玲珑鳞（38级，6个）", "血焰珠（56级，5个）", "七煞髓（80级，4个）",
                    "青罡金（90级，3个）", "幽影砂（100级，3个）"))
        self._collect_prop_choice.current(4); self._collect_prop_choice.grid(row=0, column=3, padx=6)
        self._collect_status = tk.StringVar(value="登录后点击刷新宠物与采集")
        ttk.Label(tab, textvariable=self._collect_status, wraplength=850, justify="left").pack(anchor="w", pady=12)
        self._collect_tree = ttk.Treeview(tab, columns=("pet", "material", "status"), show="headings", height=5)
        for key, label in (("pet", "宠物"), ("material", "采集材料"), ("status", "剩余时间 / 状态")):
            self._collect_tree.heading(key, text=label); self._collect_tree.column(key, width=220)
        self._collect_tree.pack(fill="both", expand=True)
        self._collect_tree.bind("<<TreeviewSelect>>", lambda event: setattr(self, "_collect_selected_slot", next(iter(self._collect_tree.selection()), None)))
        self._collect_pets = []
        self._collect_selected_slot = None

    def _limited_action(self, page, action):
        if not self._ensure_login() or getattr(self, "_limited_activity_busy", False):
            return
        title = "国庆签到·千万灵魂" if page == 'million' else '宠物加速养成'
        if ((page == 'million' and action != 'refresh') or
                (page == 'petcollect' and action in ('begin', 'rebegin'))) and self._limited_config_expired(title):
            self._log('[%s] 活动配置已过期，停止执行' % title)
            messagebox.showinfo('活动已过期', title + '已超过配置截止时间')
            return
        if page == "million" and action == "reward":
            if not messagebox.askyesno("领取最终灵魂", "领取后本期千万灵魂活动结束，确定领取？"):
                return
        pet_id = None
        prop_index = 5
        if page == "petcollect":
            prop_index = self._collect_prop_choice.current() + 1
            selected = self._collect_pet_choice.current()
            if action == "begin":
                if selected < 0 or selected >= len(self._collect_pets):
                    messagebox.showinfo("选择宠物", "请先刷新并选择一只宠物")
                    return
                pet_id = self._collect_pets[selected]["entityId"]
        self._limited_activity_busy = True
        for button in self._activity_buttons():
            button.config(state="disabled")
        threading.Thread(target=self._limited_activity_worker,
            args=(page, action, pet_id, prop_index, self.client, self.current_save["index"]), daemon=True).start()

    @staticmethod
    def _limited_request(flow, route, payload):
        result = flow.request(route, payload, timeout=20)
        if not isinstance(result, dict) or result.get("code") != 200 or result.get("error"):
            raise RuntimeError(str(result.get("error") or result.get("message") or result) if isinstance(result, dict) else "请求回包不是对象：" + route)
        return result

    def _limited_activity_worker(self, page, action, pet_id, prop_index, expected_client=None, expected_slot=None):
        flow = None
        prefix = "[千万灵魂]" if page == "million" else "[宠物加速养成]"
        try:
            client = expected_client or self.client
            slot = expected_slot if expected_slot is not None else self.current_save['index']
            flow, entry, scene = self._connect_and_enter(slot, expected_client=client)
            def request(route, data):
                if self.client is not client or self.current_save['index'] != slot:
                    raise RuntimeError('账号或存档已切换，停止采集操作')
                return self._limited_request(flow, route, data)
            if page == "million":
                route = "scene.holidayHandler."
                state = request(route + "getMillionSoulInfo", {})["millionSoul"]
                info, dates = state.get("info", []), state.get("time", [])
                day = int(state.get("curDay", 0))
                if action != "refresh" and state.get("reward"):
                    raise RuntimeError("本期最终灵魂已领取")
                if action == "sign":
                    if not 1 <= day <= 7 or day in [int(x) for x in dates]:
                        raise RuntimeError("今日已签到或不在签到时间内")
                    result = request(route + "millionSoulSign", {"type": 1, "day": len(info) + 1})
                elif action == "extra":
                    sequence = len(state.get("extraReward", [])) + 1
                    if sequence > len(info):
                        raise RuntimeError("没有可领取的签到奖励")
                    result = request(route + "millionSoulAccumulativeSignReward", {"type": 4, "day": sequence})
                elif action == "reward":
                    if day < 7 or not info:
                        raise RuntimeError("尚未到最终灵魂领取时间或没有签到记录")
                    result = request(route + "millionSoulReward", {})
                else:
                    result = None
                if result is not None:
                    self._log(prefix + "服务器返回：" + json.dumps(result, ensure_ascii=False))
                    state = request(route + "getMillionSoulInfo", {})["millionSoul"]
                text = "活动第%s天；已签到%s次；已领签到奖励%s次；最终灵魂：%s\n签到记录：%s\n签到倍率：%s" % (
                    state.get("curDay", 0), len(state.get("info", [])), len(state.get("extraReward", [])),
                    "已领取" if state.get("reward") else "未领取", state.get("time", []), state.get("info", []))
                self.root.after(0, lambda t=text: self._million_status.set(t))
            else:
                self._pet_collect_work(request, entry, scene, action, pet_id, prop_index)
        except Exception as error:
            self._log(prefix + "操作未完成：" + str(error))
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, self._limited_activity_unlock)

    def _limited_activity_unlock(self):
        self._limited_activity_busy = False
        for button in self._activity_buttons():
            button.config(state="normal")

    def _pet_collect_work(self, request, entry, scene, action, pet_id, prop_index):
        from pet_collect_routes import work
        return work(self, request, entry, scene, action, pet_id, prop_index)

    def _show_pet_collect(self, state, pets, names, used):
        slots = (state.get("petCollect") or {}).get("slots") or {}
        if not isinstance(slots, dict):
            slots = {str(i): s for i, s in enumerate(slots) if s}
        busy = {s.get("entityId") for s in slots.values() if s}
        self._collect_pets = [p for p in pets if int(p.get("level", 0)) >= 38 and
            int(p.get("status", 0)) == 0 and p.get("entityId") not in busy]
        values = ["%s · %s级 · %s" % (p.get("newName") or names.get(str(p.get("id")), p.get("id")),
                  p.get("level"), p["entityId"]) for p in self._collect_pets]
        self._collect_pet_choice.config(values=values)
        self._collect_pet_choice.set(values[0] if values else "")
        self._collect_status.set("本工具今日已确认采集 %s/3 次（服务器仍校验上限）；占用槽位 %s/%s" % (
            used, len(slots), (state.get("petCollect") or {}).get("maxSlot", 0)))
        self._collect_tree.delete(*self._collect_tree.get_children())
        now = int(state.get("serverTime", 0))
        for pos, slot in sorted(slots.items()):
            pet = (slot.get("data") or {}).get("pet") or {}
            prop = (slot.get("data") or {}).get("prop") or {}
            remaining = max(0, (int(slot.get("time", 0)) - now + 999) // 1000)
            status = "可免费领取" if not remaining else "%s分%s秒（刷新更新）" % divmod(remaining, 60)
            self._collect_tree.insert("", "end", iid=str(pos), values=(
                pet.get("newName") or names.get(str(pet.get("id")), slot.get("entityId")),
                "%s ×%s" % (prop.get("name", "材料"), prop.get("collectNum", "?")), status))

    def _activity_buttons(self):
        names = ("_million_buttons", "_pet_collect_buttons", "_horse_collect_buttons",
                 "_xingtian_buttons", "_nian_buttons", "_double_ninth_buttons", "_pingyi_buttons")
        return tuple(button for name in names for button in (getattr(self, name, None) or ()))

    def _build_pingyi_tab(self):
        tab = self._limited_page("挑战屏翳", padding=12)
        ttk.Label(tab, text="四档共享每天1次免费挑战；默认最高难度地狱。仅使用免费次数，不购买次数。",
                  wraplength=800).pack(anchor="w", pady=8)
        self._pingyi_modes = {"普通": 2064, "精英": 2065, "噩梦": 2066, "地狱": 2121}
        self._pingyi_mode = tk.StringVar(value="地狱")
        form = ttk.Frame(tab); form.pack(anchor="w", pady=8)
        ttk.Label(form, text="难度：").pack(side="left")
        ttk.Combobox(form, textvariable=self._pingyi_mode, values=tuple(self._pingyi_modes),
                     state="readonly", width=20).pack(side="left", padx=5)
        self._pingyi_buttons = []
        for title, run in (("刷新免费次数", False), ("免费挑战一次", True)):
            button = ttk.Button(tab, text=title, command=lambda run=run: self._pingyi_action(run))
            button.pack(anchor="w", pady=5); self._pingyi_buttons.append(button)
        self._pingyi_status = tk.StringVar(value="登录后刷新免费次数")
        ttk.Label(tab, textvariable=self._pingyi_status, wraplength=800).pack(anchor="w", pady=8)
        ttk.Label(tab, text="本期截止2026年11月1日。预留至少5个道具空格。\n"
                  "2026-10-22七音槽3地狱难度已实测：结算、重登入包、免费次数及点券核验通过。",
                  wraplength=800).pack(anchor="w", pady=8)

    def _pingyi_action(self, run):
        if not self._ensure_login() or getattr(self, "_limited_activity_busy", False):
            return
        if run and self._limited_config_expired("挑战屏翳"):
            messagebox.showinfo("活动已过期", "挑战屏翳已超过本期配置截止时间")
            return
        try:
            mid = _mode_dungeon(self._pingyi_modes, self._pingyi_mode.get())
        except RuntimeError as error:
            messagebox.showinfo("难度选项", str(error))
            return
        slot = self.current_save['index']
        self._limited_activity_busy = True
        for button in self._activity_buttons(): button.config(state="disabled")
        threading.Thread(target=self._pingyi_worker, args=(run, mid, slot), daemon=True).start()

    def _pingyi_worker(self, run, mid, slot):
        flow = None
        text = ""
        def used(scene):
            history = scene['curRecord'].get('copyHistory')
            if not isinstance(history, list):
                raise RuntimeError("无法读取挑战次数，已停止")
            return sum(int(row.get('num', 0)) for row in history
                       if int(row.get('id', 0)) in (2064, 2065, 2066, 2121))
        try:
            from mainfarm_routes import clear_stage
            if mid not in (2064, 2065, 2066, 2121):
                raise RuntimeError("未知屏翳难度")
            flow, _, scene = self._connect_and_enter(slot)
            initial = used(scene)
            if run:
                if initial >= 1:
                    raise RuntimeError("今日共享免费次数已用完，停止执行")
                bag = scene['curRecord'].get('itemsBag') or {}
                if int(bag.get('itemCount', 0)) - len(bag.get('items') or []) < 5:
                    raise RuntimeError("道具背包不足5个空格，请先清理")
                baseline = scene
                points = {key: scene['user'].get(key) for key in ('gem', 'usedGem')}
                self._log("[挑战屏翳] 槽%s，关卡%s，免费挑战 costGem=0" % (slot, mid))
                result = clear_stage(flow, scene, mid, pick_equips=True)
                self._log("[挑战屏翳] 结算成功，拾取：%s" % result['counts'])
                flow.disconnect(); flow = None
                flow, _, scene = self._connect_and_enter(slot)
                if points != {key: scene['user'].get(key) for key in points}:
                    raise RuntimeError("点券或累计消费发生变化，停止执行")
                for iid, expected in result['counts'].items():
                    delta = self._special_item_count(scene, iid) - self._special_item_count(baseline, iid)
                    self._log("[屏翳核验] 道具%s：重登增加%d，预期%d" % (iid, delta, expected))
                    if delta < expected:
                        raise RuntimeError("道具%s入包数量不足，请检查日志" % iid)
                if used(scene) != initial + 1:
                    raise RuntimeError("重登后挑战次数变化异常，请检查日志")
            text = "今日已用%d/1，剩余免费次数%d" % (used(scene), max(0, 1-used(scene)))
            self._log("[挑战屏翳] " + text)
        except Exception as exc:
            text = "失败：%s" % exc
            self._log("[挑战屏翳] " + text)
        finally:
            if flow: flow.disconnect()
            self.root.after(0, lambda value=text: self._pingyi_status.set(value))
            self.root.after(0, self._limited_activity_unlock)

    def _build_double_ninth_tab(self):
        tab = self._limited_page("重阳签到", padding=12)
        ttk.Label(tab, text="只领取服务器当天的免费签到奖励，不提供补签或日期输入。\n"
                  "当天不在活动签到列表、已签到或无法确认服务器日期时，停止执行。",
                  wraplength=800).pack(anchor="w", pady=8)
        self._double_ninth_status = tk.StringVar(value="登录后刷新签到状态")
        ttk.Label(tab, textvariable=self._double_ninth_status, wraplength=800).pack(anchor="w", pady=8)
        self._double_ninth_buttons = []
        for title, run in (("刷新签到状态", False), ("今日免费签到并领奖", True)):
            button = ttk.Button(tab, text=title, command=lambda run=run: self._double_ninth_action(run))
            button.pack(anchor="w", pady=5); self._double_ninth_buttons.append(button)

    def _double_ninth_action(self, run):
        if not self._ensure_login() or getattr(self, "_limited_activity_busy", False):
            return
        slot = self.current_save['index']
        self._limited_activity_busy = True
        for button in self._activity_buttons(): button.config(state="disabled")
        threading.Thread(target=self._double_ninth_worker, args=(run, slot), daemon=True).start()

    def _double_ninth_worker(self, run, slot):
        flow = None
        text = ""
        def request(route, body):
            result = self._limited_request(flow, route, body)
            if result.get('error'): raise RuntimeError(str(result['error']))
            return result
        def get_state():
            result = request('scene.playerThirdHandler.getSignInfo', {})
            days = (result.get('signInfo') or {}).get('signDay')
            if not isinstance(days, dict): raise RuntimeError("未读到签到日期列表，停止执行")
            return days
        def server_day():
            stamp = request('scene.playerSecondHandler.getCurDateTime', {}).get('time')
            if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or stamp < 1000000000000:
                raise RuntimeError("无法确认服务器时间，停止执行")
            date = datetime.fromtimestamp(stamp/1000, timezone(timedelta(hours=8)))
            if date.hour == 23 and date.minute == 59 and date.second >= 50:
                raise RuntimeError("临近服务器跨日，请稍后刷新再签到")
            return '%d/%d/%d' % (date.year, date.month, date.day)
        try:
            flow, _, before = self._connect_and_enter(slot)
            days = get_state()
            today = server_day()
            if run:
                if today not in days: raise RuntimeError("服务器当天不在活动签到列表内")
                if str(days[today]) != '0': raise RuntimeError("今日已签到或状态不明确")
                # 日期只来自刚获取的服务器时间；再次确认，跨日时不发送旧日期。
                if server_day() != today: raise RuntimeError("服务器日期已变化，请重新刷新")
                points = {key: before['user'].get(key) for key in ('gem', 'usedGem')}
                reply = request('scene.playerThirdHandler.sign', {'type': 1, 'signDay': today})
                self._log('[重阳签到] 签到服务器返回：' + json.dumps(reply, ensure_ascii=False))
                flow.disconnect(); flow = None
                flow, _, after = self._connect_and_enter(slot)
                if points != {key: after['user'].get(key) for key in points}:
                    raise RuntimeError("点券或累计消费变化，请查看日志")
                days = get_state()
                if str(days.get(today)) != '1': raise RuntimeError("重登后签到状态未确认成功")
                old_bag = before['curRecord'].get('itemsBag') or {}
                new_bag = after['curRecord'].get('itemsBag') or {}
                def counts(bag):
                    rows = bag.get('items') or []
                    rows = rows.values() if isinstance(rows, dict) else rows
                    return {str(row['id']): int(row.get('count', 1)) for row in rows}
                old, new = counts(old_bag), counts(new_bag)
                delta = {key: new.get(key, 0)-old.get(key, 0) for key in new.keys() | old.keys()
                         if new.get(key, 0) != old.get(key, 0)}
                self._log('[重阳签到] 重登确认已签到；道具变化%s；点券未变' % delta)
            status = '不在签到日期内' if today not in days else (
                '未签到，可免费领取' if str(days[today]) == '0' else
                '已签到' if str(days[today]) == '1' else '状态未知，不可执行')
            text = '服务器日期：%s；%s\n签到记录：%s' % (today, status, days)
        except Exception as error:
            text = '已停止：' + str(error)
            self._log('[重阳签到] ' + text)
        finally:
            if flow: flow.disconnect()
            self.root.after(0, lambda t=text: self._double_ninth_status.set(t))
            self.root.after(0, self._limited_activity_unlock)

    def _build_nian_tab(self):
        tab = self._limited_page("挑战年兽", padding=12)
        ttk.Label(tab, text="三个难度共享每天2次免费机会；自动通关并拾取，重登核对入包。",
                  wraplength=800).pack(anchor="w", pady=8)
        form = ttk.Frame(tab); form.pack(anchor="w", pady=8)
        self._nian_modes = {"简单（2061）": 2061, "困难（2062）": 2062,
                            "噩梦（2085）": 2085}
        self._nian_mode = tk.StringVar(value="噩梦（2085）")
        ttk.Label(form, text="难度：").pack(side="left")
        ttk.Combobox(form, textvariable=self._nian_mode, values=tuple(self._nian_modes),
                     state="readonly", width=29).pack(side="left", padx=5)
        self._nian_count = tk.StringVar(value="2")
        ttk.Label(form, text="次数：").pack(side="left")
        ttk.Combobox(form, textvariable=self._nian_count, values=("1", "2"),
                     state="readonly", width=5).pack(side="left", padx=5)
        self._nian_only_horn = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="仅拾取年兽断角", variable=self._nian_only_horn).pack(side="left", padx=12)
        self._nian_buttons = []
        for title, run in (("刷新免费次数", False), ("执行免费挑战", True)):
            button = ttk.Button(tab, text=title, command=lambda run=run: self._nian_action(run))
            button.pack(anchor="w", pady=5); self._nian_buttons.append(button)
        self._nian_status = tk.StringVar(value="登录后刷新免费次数")
        ttk.Label(tab, textvariable=self._nian_status, wraplength=800).pack(anchor="w", pady=8)
        ttk.Label(tab, text="最多执行当前剩余免费次数，不购买额外次数。请先留出至少5个道具背包空格（勾选“仅拾取年兽断角”时仅需1个）。\n"
                  "本期第三档名称为噩梦；三个入口均已实测。活动是否开放以服务器返回为准。",
                  wraplength=800).pack(anchor="w", pady=8)

    def _nian_action(self, run):
        if not self._ensure_login() or getattr(self, "_limited_activity_busy", False):
            return
        try:
            mid = _mode_dungeon(self._nian_modes, self._nian_mode.get())
            count = int(self._nian_count.get())
        except (RuntimeError, ValueError) as error:
            messagebox.showinfo("年兽选项", str(error))
            return
        only_horn = bool(self._nian_only_horn.get())
        slot = self.current_save['index']
        self._limited_activity_busy = True
        for button in self._activity_buttons(): button.config(state="disabled")
        threading.Thread(target=self._nian_worker, args=(run, mid, count, slot, only_horn),
                         daemon=True).start()

    def _nian_worker(self, run, mid, count, slot, only_horn=False):
        flow = None
        text = ""
        need_space = 1 if only_horn else 5
        def used(scene):
            history = scene['curRecord'].get('copyHistory')
            if not isinstance(history, list): raise RuntimeError("无法读取挑战次数，已停止")
            return sum(int(row.get('num', 0)) for row in history
                       if int(row.get('id', 0)) in (2061, 2062, 2085))
        try:
            from mainfarm_routes import clear_stage
            flow, _, scene = self._connect_and_enter(slot)
            initial = used(scene)
            attempts = min(count, max(0, 2-initial)) if run else 0
            if run and not attempts: raise RuntimeError("今日共享免费次数已用完")
            last_create = 0.0
            for index in range(attempts):
                # 服务器要求两次创建关卡至少间隔1秒，否则会出现创建/结算异常
                if last_create:
                    gap = time.monotonic() - last_create
                    if gap < 1.2:
                        time.sleep(1.2 - gap)
                if used(scene) >= 2: raise RuntimeError("免费次数已用完，已停止")
                bag = scene['curRecord'].get('itemsBag') or {}
                if int(bag.get('itemCount', 0))-len(bag.get('items') or []) < need_space:
                    raise RuntimeError("道具背包不足%d个空格，请先清理" % need_space)
                points = {key: scene['user'].get(key) for key in ('gem', 'usedGem')}
                baseline = scene
                previous_used = used(scene)
                self._log("[年兽] 槽%s，关卡%s，第%d/%d次，免费挑战%s" % (
                    slot, mid, index+1, attempts, "（只拾取年兽断角）" if only_horn else ""))
                result = clear_stage(flow, scene, mid, pick_equips=not only_horn,
                                     only_item_ids=[143300007] if only_horn else None)
                last_create = time.monotonic()
                self._log("[年兽] 结算成功，拾取：%s" % result['counts'])
                flow.disconnect(); flow = None
                flow, _, scene = self._connect_and_enter(slot)
                if points != {key: scene['user'].get(key) for key in points}:
                    raise RuntimeError("点券或累计消费发生变化，停止执行")
                for iid, expected in result['counts'].items():
                    delta = self._special_item_count(scene, iid)-self._special_item_count(baseline, iid)
                    self._log("[年兽核验] 道具%s：重登增加%d，预期%d" % (iid, delta, expected))
                    if delta != expected: raise RuntimeError("掉落入包数量不一致，停止执行")
                if used(scene) != previous_used+1: raise RuntimeError("挑战次数核对不一致，停止执行")
            text = "今日已用%d/2次；剩余免费次数%d" % (used(scene), max(0, 2-used(scene)))
            self._log("[年兽] " + text)
        except Exception as error:
            text = "已停止：" + str(error)
            self._log("[年兽] " + text)
        finally:
            if flow: flow.disconnect()
            self.root.after(0, lambda t=text: self._nian_status.set(t))
            self.root.after(0, self._limited_activity_unlock)

    def _build_horse_collect_tab(self):
        tab = self._limited_page("骑装加速养成", padding=12)
        ttk.Label(tab, text="坐骑采集骑装强化材料，每天3次，每次120分钟。骑乘中的坐骑会先下马，开始采集后恢复骑乘。",
                  wraplength=850).pack(anchor="w", pady=8)
        bar = ttk.Frame(tab); bar.pack(fill="x", pady=8)
        self._horse_collect_buttons = []
        for title, action in (("刷新采集状态", "refresh"), ("开始采集", "begin"),
                              ("免费领取已完成采集", "claim"), ("用上次坐骑再次采集", "rebegin")):
            button = ttk.Button(bar, text=title, command=lambda a=action: self._new_activity_action("horse", a))
            button.pack(side="left", padx=5); self._horse_collect_buttons.append(button)
        form = ttk.Frame(tab); form.pack(fill="x", pady=8)
        ttk.Label(form, text="坐骑：").grid(row=0, column=0)
        self._horse_choice = ttk.Combobox(form, state="readonly", width=35)
        self._horse_choice.grid(row=0, column=1, padx=6)
        ttk.Label(form, text="材料：").grid(row=0, column=2)
        self._horse_prop_choice = ttk.Combobox(form, state="readonly", width=26,
            values=("炎晶（38级，4个）", "沙晶（56级，3个）", "木晶（80级，3个）", "瑰晶（90级，3个）"))
        self._horse_prop_choice.current(3); self._horse_prop_choice.grid(row=0, column=3, padx=6)
        self._horse_status = tk.StringVar(value="登录后点击刷新采集状态")
        ttk.Label(tab, textvariable=self._horse_status, wraplength=850, justify="left").pack(anchor="w", pady=12)
        self._horse_tree = ttk.Treeview(tab, columns=("horse", "prop", "state"), show="headings", height=5)
        for key, label in (("horse", "坐骑"), ("prop", "采集材料"), ("state", "剩余时间 / 状态")):
            self._horse_tree.heading(key, text=label); self._horse_tree.column(key, width=220)
        self._horse_tree.pack(fill="both", expand=True)
        self._collect_horses = []
        self._last_horse_collects = []

    def _build_xingtian_tab(self):
        tab = self._limited_page("挑战刑天", padding=12)
        ttk.Label(tab, text="三个模式共享每天1次免费机会。选择难度后自动通关并拾取奖励，默认地狱难度。",
                  wraplength=850).pack(anchor="w", pady=8)
        ttk.Label(tab, text="奖励：刑天之羽、刑天珍宝箱等，以服务器实际掉落为准。",
                  wraplength=850).pack(anchor="w", pady=5)
        choices = ttk.Frame(tab); choices.pack(fill="x", pady=8)
        ttk.Label(choices, text="难度：").pack(side="left")
        self._xingtian_modes = {"普通": 2050,
                                "噩梦": 2051,
                                "地狱": 2081}
        self.var_xingtian_difficulty = tk.StringVar(value="地狱")
        ttk.Combobox(choices, textvariable=self.var_xingtian_difficulty,
                     values=tuple(self._xingtian_modes), state="readonly", width=30).pack(side="left", padx=8)
        bar = ttk.Frame(tab); bar.pack(fill="x", pady=8)
        self._xingtian_buttons = []
        for title, action in (("刷新免费次数", "refresh"), ("免费挑战一次", "run")):
            button = ttk.Button(bar, text=title, command=lambda a=action: self._new_activity_action("xingtian", a))
            button.pack(side="left", padx=5); self._xingtian_buttons.append(button)
        self._xingtian_status = tk.StringVar(value="登录后刷新免费次数")
        ttk.Label(tab, textvariable=self._xingtian_status, wraplength=850, justify="left").pack(anchor="w", pady=12)

    def _new_activity_action(self, page, action):
        if not self._ensure_login() or getattr(self, "_limited_activity_busy", False):
            return
        entity = None; prop = 4
        if page == "horse":
            if action == "begin":
                prop = self._horse_prop_choice.current() + 1
                selected = self._horse_choice.current()
                if selected < 0 or selected >= len(self._collect_horses):
                    messagebox.showinfo("选择坐骑", "请先刷新并选择坐骑")
                    return
                entity = self._collect_horses[selected]["entityId"]
            elif action == "rebegin":
                prop = 0
        xingtian_mid = 2081
        if page == "xingtian":
            modes = getattr(self, "_xingtian_modes", None)
            if modes:
                xingtian_mid = modes.get(self.var_xingtian_difficulty.get(), 2081)
        self._limited_activity_busy = True
        for button in self._activity_buttons(): button.config(state="disabled")
        threading.Thread(target=self._new_activity_worker, args=(page, action, entity, prop, xingtian_mid), daemon=True).start()

    @staticmethod
    def _horse_collect_used(entry, scene, state):
        stamp = int(state.get("serverTime", 0))
        weekday = (datetime.fromtimestamp(stamp / 1000, timezone(timedelta(hours=8))).weekday() + 1) % 7
        weekly = entry.get("record", {}).get("everyWeekSetting", {})
        rid = scene.get("curRecord", {}).get("_id")
        key = "%s_%s_horseCollect" % (rid, weekday)
        return int(weekly.get(key, 0))

    def _new_activity_worker(self, page, action, entity, prop_index, xingtian_mid=2081):
        flow = None
        title = "骑装加速养成" if page == "horse" else "挑战刑天"
        try:
            flow, entry, scene = self._connect_and_enter()
            if page == "horse":
                self._horse_collect_work(flow, entry, scene, action, entity, prop_index)
            else:
                used = sum(int(r.get("num", 0)) for r in scene["curRecord"].get("copyHistory", [])
                           if int(r.get("id", 0)) in (2050, 2051, 2081))
                if action == "run":
                    if used >= 1: raise RuntimeError("今日共享免费次数已用完")
                    from mainfarm_routes import clear_stage
                    if xingtian_mid not in (2050, 2051, 2081): raise RuntimeError("未知刑天难度")
                    self._log("[挑战刑天] 本次选择关卡%d" % xingtian_mid)
                    result = clear_stage(flow, scene, xingtian_mid)
                    self._log("[挑战刑天] 通关及拾取结算成功：" + str(result["counts"]))
                    baseline = scene
                    flow.disconnect(); flow = None
                    flow, _, scene = self._connect_and_enter()
                    for iid, count in result["counts"].items():
                        old = self._special_item_count(baseline, iid); new = self._special_item_count(scene, iid)
                        self._log("[挑战刑天核验] 道具%s：%d → %d（实际增加%d，掉落%d）" % (iid, old, new, new-old, count))
                    self._log("[挑战刑天核验] 点券：%s → %s" % (baseline["user"].get("gem"), scene["user"].get("gem")))
                    used = sum(int(r.get("num", 0)) for r in scene["curRecord"].get("copyHistory", [])
                               if int(r.get("id", 0)) in (2050, 2051, 2081))
                    if used != 1: self._log("[挑战刑天] 次数核对异常，请查看日志")
                text = "今日已使用 %d/1 次；剩余免费机会 %d 次" % (used, max(0, 1-used))
                status = getattr(self, "_xingtian_status", None)
                if status is not None:
                    self.root.after(0, lambda t=text: status.set(t))
        except Exception as error:
            self._log("[%s] 操作未完成：%s" % (title, error))
        finally:
            if flow: flow.disconnect()
            self.root.after(0, self._limited_activity_unlock)

    @staticmethod
    def _horse_prop_index(config, prop):
        try:
            index = int(prop.get("index", 0))
        except (TypeError, ValueError):
            index = 0
        if 1 <= index <= 4:
            return index
        name = str(prop.get("name") or "")
        for i in range(1, 5):
            raw = config.get("item%d" % i)
            if not raw or raw == "-1":
                continue
            item = json.loads(raw)
            if name and item.get("name") == name:
                return i
            if (int(prop.get("level", 0)) == int(item.get("level", 0)) and
                    int(prop.get("collectNum", 0)) == int(item.get("collectNum", 0))):
                return i
        return 0

    def _horse_collect_work(self, flow, entry, scene, action, entity, prop_index):
        request = lambda route, data: self._limited_request(flow, route, data)
        route = "scene.playerFourthHandler."
        state = request(route + "getHorseCollectData", {})
        collect = state.get("horseCollect") or {}
        slots = collect.get("slots") or {}
        if not isinstance(slots, dict): slots = {str(i): s for i, s in enumerate(slots) if s}
        used = self._horse_collect_used(entry, scene, state)
        base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
        with open(os.path.join(base, "136___PetCollect.xml.json"), encoding="utf-8") as file:
            config = next(r for r in json.load(file)["RECORD"] if str(r["id"]) == "2")
        with open(os.path.join(base, "086___Horse.xml.json"), encoding="utf-8") as file:
            names = {str(r["id"]): r.get("name", r["id"]) for r in json.load(file)["RECORD"]}
        horses = (scene["curRecord"].get("horseList") or {}).get("horses") or []
        if isinstance(horses, dict): horses = list(horses.values())
        horses = list({h["entityId"]: h for h in horses}.values())

        def slot_entity(slot):
            data = slot.get("data") or {}
            horse = data.get("horse") or {}
            return horse.get("entityId") or slot.get("entityId")

        def slot_source(slot):
            data = slot.get("data") or {}
            horse = data.get("horse") or {}
            prop = data.get("prop") or {}
            entity = horse.get("entityId") or slot.get("entityId")
            index = self._horse_prop_index(config, prop)
            if entity and index:
                return {"entityId": entity, "prop_index": index}
            return None

        def current_sources():
            records = []
            for slot in slots.values():
                item = slot_source(slot)
                if item and item not in records:
                    records.append(item)
            return records

        def ready_slots():
            return [(pos, s) for pos, s in slots.items()
                    if int(s.get("time", 0)) <= int(state.get("serverTime", 0))]

        def start_collect(horse, prop, index):
            nonlocal used
            if int(collect.get("v", -1)) != int(config["activeId"]): raise RuntimeError("本期采集配置已变化，请更新配置后开始")
            if used >= int(config["dayMax"]): raise RuntimeError("今日采集次数已用完")
            if not horse or int(horse["level"]) < int(prop["level"]): raise RuntimeError("坐骑等级不足")
            if any(slot_entity(s) == horse["entityId"] for s in slots.values()):
                raise RuntimeError("这只坐骑已在采集")
            pos = next((i for i in range(int(collect.get("maxSlot", 0))) if not slots.get(str(i))), None)
            if pos is None: raise RuntimeError("没有空闲采集槽位")
            original = int(horse.get("status", 0)); down = False
            try:
                if original > 0:
                    request("scene.animalHandler.downHorse", {"entityId": horse["entityId"], "pNum": original}); down = True
                chosen = {"id": horse["id"], "entityId": horse["entityId"], "level": horse["level"],
                          "name": names.get(str(horse["id"]), "坐骑"), "fight": horse.get("horseAtkPoint", 0), "order": horse["level"]}
                request(route + "horseCollectBegin", {"data": {"index": pos, "horse": chosen, "prop": prop},
                    "pos": pos, "entityId": horse["entityId"], "index": index})
                used += 1
                record = {"entityId": horse["entityId"], "prop_index": index}
                if record not in self._last_horse_collects:
                    self._last_horse_collects.append(record)
                slots[str(pos)] = {"time": int(state.get("serverTime", 0)) + 120 * 60 * 1000,
                                   "data": {"horse": chosen, "prop": prop}}
                self._log("[骑装加速养成] 已开始采集%s，120分钟后免费领取" % prop["name"])
            finally:
                if down:
                    try: request("scene.animalHandler.rideHorse", {"entityId": horse["entityId"], "pNum": original})
                    except Exception as error: self._log("[骑装加速养成] 恢复骑乘失败，请手动上马：%s" % error)

        if action == "begin":
            horse = next((h for h in horses if h["entityId"] == entity), None)
            prop = json.loads(config["item%d" % prop_index])
            start_collect(horse, prop, prop_index)
        elif action == "claim":
            ready = ready_slots()
            if not ready: raise RuntimeError("没有已完成的采集，请等待倒计时结束")
            ready.sort(key=lambda item: int(item[1].get("time", 0)))
            records = []
            for pos, slot in ready:
                item = slot_source(slot)
                if item and item not in records:
                    records.append(item)
                result = request(route + "horseCollectEnd", {"pos": int(pos), "type": 0})
                self._log("[骑装加速养成] 免费领奖服务器返回：" + json.dumps(result, ensure_ascii=False))
            if records:
                self._last_horse_collects = records
        elif action == "rebegin":
            sources = list(getattr(self, "_last_horse_collects", []) or [])
            for item in current_sources():
                if item not in sources:
                    sources.append(item)
            sources = [s for s in sources
                       if s.get("entityId") and int(s.get("prop_index") or 0) >= 1]
            if not sources:
                raise RuntimeError("没有上次采集记录，请先手动采集一次")
            ready = ready_slots()
            ready.sort(key=lambda item: int(item[1].get("time", 0)))
            for pos, slot in ready:
                result = request(route + "horseCollectEnd", {"pos": int(pos), "type": 0})
                self._log("[骑装加速养成] 免费领奖服务器返回：" + json.dumps(result, ensure_ascii=False))
            if ready:
                state = request(route + "getHorseCollectData", {})
                collect = state.get("horseCollect") or {}
                slots = collect.get("slots") or {}
                if not isinstance(slots, dict): slots = {str(i): s for i, s in enumerate(slots) if s}
                used = self._horse_collect_used(entry, scene, state)
            self._last_horse_collects = [dict(s) for s in sources]
            started = 0; errors = []
            for source in sources:
                target = source.get("entityId")
                index = int(source.get("prop_index") or 0)
                source_slot = next((s for s in slots.values() if slot_entity(s) == target), None)
                if source_slot and int(source_slot.get("time", 0)) > int(state.get("serverTime", 0)):
                    errors.append("坐骑%s还未完成采集" % target)
                    continue
                horse = next((h for h in horses if h["entityId"] == target), None)
                if not horse:
                    errors.append("坐骑%s已不在坐骑列表" % target)
                    continue
                prop = json.loads(config["item%d" % index])
                try:
                    start_collect(horse, prop, index)
                    started += 1
                except Exception as error:
                    errors.append(str(error))
                    if "今日采集次数已用完" in str(error) or "没有空闲采集槽位" in str(error):
                        break
            if started == 0:
                raise RuntimeError(errors[0] if errors else "没有可再次采集的坐骑")
            for error in errors:
                self._log("[骑装加速养成] 跳过再次采集：%s" % error)
            self._log("[骑装加速养成] 再次采集完成：开始 %s 个槽位（上次记录 %s 只）" % (started, len(sources)))
            if started == 1 and len(sources) == 1 and int(collect.get("maxSlot", 0)) > 1:
                self._log("[骑装加速养成] 同一坐骑不能同时占用多个槽位；如需占满其余槽位，"
                          "请用“开始采集”选择其他坐骑")
        state = request(route + "getHorseCollectData", {})
        self.root.after(0, lambda s=state, h=horses, n=names, u=used: self._show_horse_collect(s, h, n, u))

    def _show_horse_collect(self, state, horses, names, used):
        collect = state.get("horseCollect") or {}; slots = collect.get("slots") or {}
        if not isinstance(slots, dict): slots = {str(i): s for i, s in enumerate(slots) if s}

        def slot_entity(slot):
            data = slot.get("data") or {}
            horse = data.get("horse") or {}
            return horse.get("entityId") or slot.get("entityId")

        busy = {slot_entity(s) for s in slots.values()}
        self._collect_horses = [h for h in horses if int(h.get("level", 0)) >= 38 and h["entityId"] not in busy]
        values = ["%s · %s级 · %s" % (h.get("newName") or names.get(str(h["id"]), h["id"]), h["level"], h["entityId"])
                  for h in self._collect_horses]
        self._horse_choice.config(values=values); self._horse_choice.set(values[0] if values else "")
        self._horse_status.set("本期版本 %s；今日已采集 %s/3 次；占用槽位 %s/%s；可采集坐骑 %s 只" % (
            collect.get("v"), used, len(slots), collect.get("maxSlot", 0), len(self._collect_horses)))
        self._horse_tree.delete(*self._horse_tree.get_children())
        for pos, slot in sorted(slots.items()):
            data = slot.get("data") or {}; horse = data.get("horse") or {}; prop = data.get("prop") or {}
            remaining = max(0, (int(slot.get("time", 0))-int(state.get("serverTime", 0))+999)//1000)
            text = "可免费领取" if not remaining else "%s分%s秒（刷新更新）" % divmod(remaining, 60)
            self._horse_tree.insert("", "end", iid=str(pos), values=(names.get(str(horse.get("id")), slot.get("entityId")),
                "%s ×%s" % (prop.get("name", "材料"), prop.get("collectNum", "?")), text))
