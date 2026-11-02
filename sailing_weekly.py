"""航海寻宝：沿用实测地图组合1及专用进度、领奖接口。"""
import threading
import time
import tkinter as tk
from tkinter import ttk

CHEST_ID = '197100002'
MAX_REWARDS = 3


def request(flow, route, body=None):
    reply = flow.request(route, body, timeout=20)
    if reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('%s：%s' % (route, reply.get('error', reply)))
    return reply


def state(flow):
    info = request(flow, 'scene.playerSecondHandler.getSailingInfo').get('sailingInfo')
    if not isinstance(info, dict) or 'sailingRewardCnt' not in info or 'completed' not in info:
        raise RuntimeError('服务器未返回完整航海次数与完成状态')
    if not 0 <= int(info['sailingRewardCnt']) <= MAX_REWARDS:
        raise RuntimeError('航海领奖次数异常')
    return info


def item_counts(scene):
    rows = scene['curRecord']['itemsBag'].get('items') or []
    rows = rows.values() if isinstance(rows, dict) else rows
    return {str(row['id']): int(row.get('count', 1)) for row in rows}


def points(scene):
    return {key: scene['user'][key] for key in ('gem', 'usedGem')}


def run_once(flow, scene, log):
    info = state(flow)
    used = int(info['sailingRewardCnt'])
    if used >= MAX_REWARDS:
        raise RuntimeError('本周三次领奖机会已用完')
    bag = scene['curRecord']['itemsBag']
    counts = item_counts(scene)
    if not counts.get(CHEST_ID) and int(bag.get('itemCount', 0))-len(bag.get('items') or []) < 1:
        raise RuntimeError('道具背包空间不足，请先清理')
    if int(info['completed']) != 1:
        from mainfarm_routes import clear_stage
        for mid in (5101, 5105, 5110):
            log('[航海寻宝] 进入关卡%d，costGem=0' % mid)
            clear_stage(flow, scene, mid, reward_mode='none')
            payload = {'completed': 1}
            if mid == 5110:
                payload.update({'sailingLayer': 1, 'p1': {}, 'p2': {}, 'pickItems': {}})
            request(flow, 'scene.playerSecondHandler.updateSailingInfo', payload)
            time.sleep(2)
    ready = state(flow)
    if int(ready['sailingRewardCnt']) != used or int(ready['completed']) != 1:
        raise RuntimeError('服务器未确认通关或次数已变化，不发送领奖请求')
    reward = request(flow, 'scene.playerSecondHandler.getSailingReward')
    log('[航海寻宝] 领奖回包：%s' % reward)
    items = reward.get('items')
    if not isinstance(items, list) or sum(int(x.get('count', 0)) for x in items
                                        if str(x.get('id')) == CHEST_ID) != 1:
        raise RuntimeError('领奖响应未确认航海宝箱1个，请重登核对，不重试领奖')
    return {'usedBefore': used, 'chestBefore': counts.get(CHEST_ID, 0),
            'pointsBefore': points(scene), 'reward': reward}


def verify(flow, scene, result):
    after = state(flow)
    delta = item_counts(scene).get(CHEST_ID, 0)-result['chestBefore']
    if points(scene) != result['pointsBefore']:
        raise RuntimeError('点券或累计消费变化，停止执行')
    if delta != 1 or int(after['sailingRewardCnt']) != result['usedBefore']+1 or int(after['completed']) != 0:
        raise RuntimeError('重登后宝箱或领奖次数不符合预期，停止执行')
    return after


def build_panel(app, parent):
    ttk.Label(parent, text='每周最多领取3次航海宝箱；结束后重登核对入包与点券。',
              wraplength=700).pack(anchor='w', pady=8)
    controls = ttk.Frame(parent); controls.pack(anchor='w', pady=6)
    ttk.Label(controls, text='执行次数：').pack(side='left')
    count = tk.StringVar(value='3')
    combo = ttk.Combobox(controls, textvariable=count, values=('1', '2', '3'), state='readonly', width=5)
    combo.pack(side='left', padx=5)
    status = ttk.Label(parent, text='登录后刷新本周次数', wraplength=700)
    status.pack(anchor='w', pady=8)
    ttk.Label(parent, text='最多执行剩余领奖次数；有待领奖时先领奖。只领取最终航海宝箱，不自动开箱。\n'
              '固定免费入口，不购买次数；背包不足时停止。停止按钮在当前轮完成后生效。',
              wraplength=700).pack(anchor='w', pady=6)
    busy = False
    stop = threading.Event()
    buttons = []

    def start(run):
        nonlocal busy
        if busy or not app._ensure_login(): return
        slot = app.current_save['index']
        rounds = int(count.get())
        busy = True; stop.clear()
        for button in buttons: button.config(state='disabled')
        combo.config(state='disabled'); stop_button.config(state='normal')
        status.config(text='正在连接槽%s…' % slot)

        def worker():
            flow = None
            text = ''
            try:
                flow, _, scene = app._connect_and_enter(slot)
                info = state(flow)
                total = min(rounds, max(0, MAX_REWARDS-int(info['sailingRewardCnt']))) if run else 0
                for index in range(total):
                    if stop.is_set(): break
                    app._log('[航海寻宝] 槽%s，第%d/%d轮' % (slot, index+1, total))
                    result = run_once(flow, scene, app._log)
                    flow.disconnect(); flow = None
                    flow, _, scene = app._connect_and_enter(slot)
                    info = verify(flow, scene, result)
                    app._log('[航海寻宝] 重登确认航海宝箱增加1个，点券未变；已领奖%d/3' % int(info['sailingRewardCnt']))
                text = '本周已领奖%d/3；剩余%d次；%s' % (int(info['sailingRewardCnt']),
                    max(0, MAX_REWARDS-int(info['sailingRewardCnt'])),
                    '有待领取奖励' if int(info['completed']) == 1 else '无待领取奖励')
                if stop.is_set(): text = '已停止；' + text
            except Exception as error:
                text = '已停止：' + str(error)
            finally:
                if flow: flow.disconnect()
                app._log('[航海寻宝] ' + text)
                def finish():
                    nonlocal busy
                    busy = False
                    status.config(text=text)
                    for button in buttons: button.config(state='normal')
                    combo.config(state='readonly'); stop_button.config(state='disabled')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for title, run in (('刷新本周次数', False), ('执行并领取航海宝箱', True)):
        button = ttk.Button(controls, text=title, command=lambda run=run: start(run))
        button.pack(side='left', padx=5); buttons.append(button)
    stop_button = ttk.Button(controls, text='完成本轮后停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=5)
