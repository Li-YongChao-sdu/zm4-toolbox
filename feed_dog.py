"""限时活动子页面：双十一喂狗粮。"""
import threading
import time
from datetime import datetime, timedelta, timezone
import tkinter as tk
from tkinter import ttk, messagebox

import daily_liveness

DOG_FOOD_ID = 143200011
TIERS = (10, 20, 40, 60, 80)
REWARD_NAMES = {
    10: ("单身节烟花 ×1", "五行洗炼石 ×1"),
    20: ("法宝洗炼石 ×1", "成长率洗炼石 ×1"),
    40: ("中级幸运符 ×1", "高级幸运符 ×1"),
    60: ("2级宝石袋 ×1", "3级百变宝石袋 ×1"),
    80: ("万仙果 ×1", "单身随心礼包 ×1"),
}
DEADLINE = datetime(2026, 11, 15, 23, 59, 59)
MAX_FEED_ONCE = 200


class FeedDogPage:
    def _build_feed_dog_tab(self):
        tab = self._limited_page("喂狗粮", padding=12)
        ttk.Label(tab, text="双十一活动：在须弥山找到「汪汪的春天」，用狗粮投喂。"
                            "好感度达到 10/20/40/60/80 可领取对应档位奖励。",
                  wraplength=850).pack(anchor="w", pady=(0, 6))
        ttk.Label(tab, text="狗粮来源：活跃度日奖励 30/60/90/120/150 每档 1 个。"
                            "进度可以超过 80，全部可领奖励领完后本页会停止继续喂食。",
                  foreground="gray", wraplength=850).pack(anchor="w", pady=(0, 10))

        bar = ttk.Frame(tab)
        bar.pack(fill="x", pady=8)
        self._feed_dog_buttons = []
        for title, action in (("刷新状态", "refresh"), ("一键领活跃奖励（含狗粮）", "liveness"),
                              ("一键喂狗粮", "feed"), ("一键领奖", "claim")):
            button = ttk.Button(bar, text=title, command=lambda a=action: self._feed_dog_action(a))
            button.pack(side="left", padx=5)
            self._feed_dog_buttons.append(button)

        self._feed_dog_status = tk.StringVar(value="登录后点击刷新状态")
        ttk.Label(tab, textvariable=self._feed_dog_status, wraplength=850,
                  justify="left", font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", pady=8)

        self._feed_dog_tree = ttk.Treeview(
            tab, columns=("like", "first", "first_state", "second", "second_state"),
            show="headings", height=5)
        for key, label, width in (("like", "好感度", 70), ("first", "第一列奖励", 220),
                                   ("first_state", "状态", 90), ("second", "第二列奖励（需解锁）", 220),
                                   ("second_state", "状态", 90)):
            self._feed_dog_tree.heading(key, text=label)
            self._feed_dog_tree.column(key, width=width)
        self._feed_dog_tree.pack(fill="both", expand=True, pady=8)

        ttk.Label(tab, text="说明：喂 1 个狗粮本次实测 +3 好感度；第二列需在游戏内解锁后才能领取。"
                            "活动截止 2026-11-15 23:59:59。",
                  foreground="gray", wraplength=850).pack(anchor="w", pady=6)

        self._feed_dog_busy = False
        self._feed_dog_last = None
        self._feed_dog_render_empty()

    def _feed_dog_render_empty(self):
        self._feed_dog_tree.delete(*self._feed_dog_tree.get_children())
        for tier in TIERS:
            first, second = REWARD_NAMES[tier]
            self._feed_dog_tree.insert("", "end", iid=str(tier), values=(
                tier, first, "未刷新", second, "未刷新"))

    def _feed_dog_expired(self):
        now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
        return now > DEADLINE

    def _feed_dog_action(self, action):
        if not self._ensure_login() or self._feed_dog_busy:
            return
        if self._feed_dog_expired():
            messagebox.showinfo("活动已结束", "喂狗粮活动已超过 2026-11-15 23:59:59")
            return
        if action == "feed" and self._feed_dog_last:
            if self._feed_dog_last["all_claimed"]:
                messagebox.showinfo("奖励已领完", "所有可领奖励均已领取，不再继续喂狗粮")
                self._feed_dog_render(self._feed_dog_last)
                return
            if self._feed_dog_last["dog_food"] <= 0:
                messagebox.showinfo("没有狗粮", "背包里没有狗粮；可先一键领取活跃奖励")
                return
        self._feed_dog_set_busy(True)
        threading.Thread(target=self._feed_dog_worker, args=(action,), daemon=True).start()

    def _feed_dog_set_busy(self, busy):
        self._feed_dog_busy = busy
        for button in self._feed_dog_buttons:
            button.config(state="disabled" if busy else "normal")
        if not busy and self._feed_dog_last:
            self._feed_dog_render(self._feed_dog_last)

    def _feed_dog_worker(self, action):
        flow = None
        try:
            flow, entry, scene = self._connect_and_enter()
            snapshot = self._feed_dog_snapshot(entry, scene)
            if action == "liveness":
                daily_liveness.claim(flow, entry, scene, self._log)
            elif action == "feed":
                if snapshot["all_claimed"]:
                    raise RuntimeError("所有可领奖励均已领取，不再继续喂狗粮")
                self._feed_dog_feed_all(flow, snapshot)
            elif action == "claim":
                self._feed_dog_claim_all(flow, snapshot)
            flow.disconnect()
            flow = None
            # 重新登录读取最新背包与活动状态，避免使用操作前的快照。
            flow, entry, scene = self._connect_and_enter()
            snapshot = self._feed_dog_snapshot(entry, scene)
            self.root.after(0, lambda s=snapshot: self._feed_dog_render(s))
        except Exception as error:
            text = str(error)
            self._log("[喂狗粮] " + text)
            self.root.after(0, lambda t=text: self._feed_dog_status.set("操作失败：" + t))
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self._feed_dog_set_busy(False))

    @staticmethod
    def _feed_dog_snapshot(entry, scene):
        record = scene.get("curRecord") or {}
        feed = (entry.get("record") or {}).get("feedDog") or record.get("feedDog") or {}
        if not feed:
            raise RuntimeError("登录返回中没有 feedDog 活动数据，可能活动未开启")
        like = int(feed.get("like") or 0)
        unlock = list(feed.get("unlock") or [0, 0])
        while len(unlock) < 2:
            unlock.append(0)
        reward = feed.get("reward") or {}
        bag = record.get("itemsBag") or {}
        items = bag.get("items") if isinstance(bag, dict) else bag
        dog_food = 0
        for item in items or []:
            if isinstance(item, dict):
                try:
                    if int(item.get("id")) == DOG_FOOD_ID:
                        dog_food = int(item.get("count") or 0)
                        break
                except (TypeError, ValueError):
                    continue
        columns = [0] + ([1] if int(unlock[1]) == 1 else [])
        claimable = 0
        all_claimed = True
        for tier in TIERS:
            state = reward.get(str(tier)) or reward.get(tier) or [0, 0]
            while len(state) < 2:
                state.append(0)
            for column in columns:
                claimed = bool(int(state[column] or 0))
                if like >= tier and not claimed:
                    claimable += 1
                if not claimed:
                    all_claimed = False
        return {"like": like, "unlock": unlock, "reward": reward, "dog_food": dog_food,
                "columns": columns, "claimable": claimable, "all_claimed": all_claimed}

    def _feed_dog_feed_all(self, flow, snapshot):
        food = snapshot["dog_food"]
        if food <= 0:
            raise RuntimeError("背包里没有狗粮，请先领取活跃奖励")
        like = snapshot["like"]
        count = 0
        while food > 0 and count < MAX_FEED_ONCE:
            result = flow.request("scene.holidayHandler.feedDog", {}, timeout=15)
            if result.get("code") != 200:
                message = str(result.get("error") or result.get("message") or result)
                if "狗粮" in message or "不足" in message:
                    self._log("[喂狗粮] 服务器提示：" + message)
                    break
                raise RuntimeError(message)
            add = int(result.get("addLike") or 0)
            like = int((result.get("feedDog") or {}).get("like", like + add))
            food -= 1
            count += 1
            self._log("[喂狗粮] 第%d次：好感度 +%d → %d，剩余狗粮约 %d 个"
                      % (count, add, like, food))
            time.sleep(0.12)
        self._log("[喂狗粮] 本次共喂 %d 次，好感度 %d，背包狗粮剩余约 %d 个"
                  % (count, like, food))

    def _feed_dog_claim_all(self, flow, snapshot):
        like = snapshot["like"]
        columns = snapshot["columns"]
        if 1 not in columns:
            self._log("[喂狗粮] 第二列尚未解锁，本次只领取第一列")
        claimed = 0
        for tier in TIERS:
            state = snapshot["reward"].get(str(tier)) or snapshot["reward"].get(tier) or [0, 0]
            while len(state) < 2:
                state.append(0)
            for column in columns:
                if like < tier or bool(int(state[column] or 0)):
                    continue
                result = flow.request("scene.holidayHandler.getFeedDogReward",
                                      {"id": tier, "i": column}, timeout=15)
                if result.get("code") != 200:
                    self._log("[喂狗粮] 领取 %d 档第 %d 列失败：%s"
                              % (tier, column + 1, result.get("error", result.get("code"))))
                    continue
                claimed += 1
                self._log("[喂狗粮] 领取 %d 档第 %d 列成功：%s"
                          % (tier, column + 1, result.get("add", result.get("items", []))))
                time.sleep(0.15)
        if claimed == 0:
            self._log("[喂狗粮] 没有可领取的奖励")
        else:
            self._log("[喂狗粮] 本次共领取 %d 个奖励" % claimed)

    def _feed_dog_render(self, snapshot):
        self._feed_dog_last = snapshot
        like = snapshot["like"]
        food = snapshot["dog_food"]
        unlock = int(snapshot["unlock"][1]) == 1
        total = len(TIERS) * len(snapshot["columns"])
        claimed_count = 0
        for tier in TIERS:
            state = snapshot["reward"].get(str(tier)) or snapshot["reward"].get(tier) or [0, 0]
            while len(state) < 2:
                state.append(0)
            claimed_count += sum(1 for column in snapshot["columns"] if int(state[column] or 0))
        self._feed_dog_status.set(
            "好感度 %d ｜ 狗粮 %d 个 ｜ 第二列 %s ｜ 可领奖励 %d 个 ｜ 已领 %d/%d"
            % (like, food, "已解锁" if unlock else "未解锁", snapshot["claimable"],
               claimed_count, total))
        self._feed_dog_tree.delete(*self._feed_dog_tree.get_children())
        for tier in TIERS:
            first, second = REWARD_NAMES[tier]
            state = snapshot["reward"].get(str(tier)) or snapshot["reward"].get(tier) or [0, 0]
            while len(state) < 2:
                state.append(0)
            if like < tier:
                first_state = "未达标"
            else:
                first_state = "已领" if int(state[0] or 0) else "可领"
            if not unlock:
                second_state = "未解锁"
            elif like < tier:
                second_state = "未达标"
            else:
                second_state = "已领" if int(state[1] or 0) else "可领"
            self._feed_dog_tree.insert("", "end", iid=str(tier), values=(
                tier, first, first_state, second, second_state))
        self._feed_dog_apply_button_state(snapshot)

    def _feed_dog_apply_button_state(self, snapshot):
        if not getattr(self, "_feed_dog_buttons", None):
            return
        refresh, liveness, feed, claim = self._feed_dog_buttons
        expired = self._feed_dog_expired()
        busy = self._feed_dog_busy
        refresh.config(state="disabled" if busy else "normal")
        liveness.config(state="disabled" if busy or expired else "normal")
        feed.config(state="disabled" if busy or expired or snapshot["all_claimed"]
                     or snapshot["dog_food"] <= 0 else "normal")
        claim.config(state="disabled" if busy or expired or snapshot["claimable"] <= 0 else "normal")
