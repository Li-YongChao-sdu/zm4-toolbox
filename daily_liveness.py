"""活跃任务点数及日、周档位奖励，独立页面和日常收尾共用。"""
import json
import time
import threading
from tkinter import ttk


def claim(flow, entry, scene, log):
    cur = scene.get('curRecord', {})
    liveness = cur.get("liveness") or entry.get("record", {}).get("liveness") or {}
    if not liveness:
        raise RuntimeError("进入存档时未返回活跃度数据，已停止领取")
    day_point = int(liveness.get("dayActivePoint", 0))
    total_point = int(liveness.get("activePoint", 0))
    tasks = liveness.get("tasks") or {}
    log("  当前活跃度: 日%d / 总%d" % (day_point, total_point))

    # 领取已完成任务活跃度
    claimed = 0
    for tid, task in tasks.items():
        if task.get("isCompleted") == 1:
            r2 = flow.request("scene.livenessHandler.getLivenessPoint", {"id": int(tid)}, timeout=15)
            if isinstance(r2, dict) and r2.get("code") == 200 and not r2.get("error") and r2.get("liveness"):
                liveness = r2["liveness"]
                day_point = int(liveness.get("dayActivePoint", day_point))
                total_point = int(liveness.get("activePoint", total_point))
                claimed += 1
                log("  任务%s活跃度领取成功" % tid)
            else:
                log("  任务%s活跃度领取失败: %s" % (tid, (r2.get("error", r2.get("code")) if isinstance(r2, dict) else "返回格式异常")))
            time.sleep(0.3)
    if claimed > 0:
        log("  领取了%d个任务活跃度，当前日活跃度: %d" % (claimed, day_point))
    else:
        log("  没有可领取的任务活跃度")

    # 领取档位奖励
    LIVENESS_DAY = [30, 60, 90, 120, 150]
    LIVENESS_WEEK = [450, 1050]
    for lv in LIVENESS_DAY:
        if day_point >= lv and not (liveness.get("dayRewardHistory") or {}).get(str(lv)):
            r3 = flow.request("scene.livenessHandler.getReward", {"type": 0, "id": lv}, timeout=15)
            if isinstance(r3, dict) and r3.get("code") == 200 and not (r3.get("error") if isinstance(r3, dict) else "返回格式异常"):
                liveness = r3.get("liveness") or liveness
                log("  领取日奖励%d: %s" % (lv, json.dumps(r3.get("add", r3.get("items", [])), ensure_ascii=False)))
            else:
                log("  日奖励%d领取失败: %s" % (lv, (r3.get("error") if isinstance(r3, dict) else "返回格式异常")))
            time.sleep(0.3)
    for lv in LIVENESS_WEEK:
        if total_point >= lv and not (liveness.get("weekRewardHistory") or {}).get(str(lv)):
            r3 = flow.request("scene.livenessHandler.getReward", {"type": 1, "id": lv}, timeout=15)
            if isinstance(r3, dict) and r3.get("code") == 200 and not (r3.get("error") if isinstance(r3, dict) else "返回格式异常"):
                liveness = r3.get("liveness") or liveness
                log("  领取周奖励%d: %s" % (lv, json.dumps(r3.get("add", r3.get("items", [])), ensure_ascii=False)))
            else:
                log("  周奖励%d领取失败: %s" % (lv, (r3.get("error") if isinstance(r3, dict) else "返回格式异常")))
            time.sleep(0.3)

    return liveness


def execute(app, save_index):
    flow = None
    try:
        # 收尾时重新登录，读取完成活动后的最新任务状态。
        flow, entry, scene = app._connect_and_enter(save_index)
        return claim(flow, entry, scene, app._log)
    finally:
        if flow:
            flow.disconnect()


def build_tab(app):
    tab = ttk.Frame(app.daily_notebook, padding=10)
    app.daily_notebook.add(tab, text='活跃奖励')
    ttk.Label(tab, text='所有活动做完后，再来领取活跃度和档位奖励。', font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=8)
    ttk.Label(tab, text='是否纳入一键日常，请在“一键日常”面板勾选。', foreground='gray').pack(anchor='w', pady=5)
    ttk.Label(tab, text='领取已完成任务的活跃度，以及达标且未领取的日奖励、周奖励（包括宝石结晶）。', wraplength=680).pack(anchor='w', pady=8)
    status = ttk.Label(tab, text='待领取；点击后重新读取服务器最新任务状态', wraplength=680)
    status.pack(anchor='w', pady=8)

    def run():
        if not app._ensure_login():
            return
        save_index = app.current_save['index']
        button.config(state='disabled')
        status.config(text='正在读取最新状态并领取…')
        def worker():
            try:
                result = execute(app, save_index)
                text = '处理完成：今日活跃%s，周活跃%s；详细领取结果见日志。' % (result.get('dayActivePoint', 0), result.get('activePoint', 0))
            except Exception as error:
                text = '领取异常：%s' % error
                app._log('[活跃奖励] ' + text)
            def finish():
                status.config(text=text)
                button.config(state='normal')
            app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    button = ttk.Button(tab, text='领取活跃度及全部达标奖励', command=run)
    button.pack(anchor='w', pady=10)
