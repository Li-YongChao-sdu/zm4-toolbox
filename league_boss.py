"""联盟梼杌：采用地狱实测的进场、伤害和结算推送流程。"""
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox

DIFFICULTIES = {'狂暴（普通）': 1, '噩梦': 2, '地狱': 3}


def build_panel(app, parent):
    difficulty = tk.StringVar(value='地狱')
    controls = ttk.Frame(parent)
    controls.pack(anchor='w', pady=10)
    ttk.Label(controls, text='难度：').pack(side='left')
    combo = ttk.Combobox(controls, textvariable=difficulty,
                         values=list(DIFFICULTIES), state='readonly', width=16)
    combo.pack(side='left', padx=5)
    damage_controls = ttk.Frame(parent)
    damage_controls.pack(anchor='w', pady=5)
    first_damage = tk.StringVar(value='10000')
    tick_damage = tk.StringVar(value='1')
    ttk.Label(damage_controls, text='首次伤害：').pack(side='left')
    first_entry = ttk.Entry(damage_controls, textvariable=first_damage, width=12)
    first_entry.pack(side='left', padx=5)
    ttk.Label(damage_controls, text='之后每秒伤害：').pack(side='left')
    tick_entry = ttk.Entry(damage_controls, textvariable=tick_damage, width=12)
    tick_entry.pack(side='left', padx=5)
    status = ttk.Label(parent, text='待开始', wraplength=720)
    status.pack(anchor='w', pady=8)
    ttk.Label(parent, text='进入成功后第1秒提交首次伤害，之后每秒提交设定伤害，保持协议心跳直到本场结束。\n'
              '自动显示服务器返回的BOSS等级；奖励由服务器发送邮件，可在邮件领取功能中领取。',
              wraplength=720).pack(anchor='w', pady=5)
    stop = threading.Event()

    def show(text):
        app.root.after(0, lambda: status.config(text=text))

    def start():
        if not app._ensure_login():
            return
        try:
            initial_hurt = int(first_damage.get().strip())
            following_hurt = int(tick_damage.get().strip())
            if initial_hurt < 1 or following_hurt < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning('伤害设置', '首次伤害和每秒伤害均需填写大于0的整数。')
            return
        slot = app.current_save['index']
        name = difficulty.get()
        boss_index = DIFFICULTIES[name]
        stop.clear()
        start_button.config(state='disabled')
        combo.config(state='disabled')
        first_entry.config(state='disabled')
        tick_entry.config(state='disabled')
        stop_button.config(state='normal')
        show('正在连接槽%s…' % slot)

        def worker():
            flow = None
            entered = False
            incoming = queue.Queue()
            result = None
            ended = False
            server_hit = 0

            def drain():
                nonlocal result, ended, server_hit
                while True:
                    try:
                        route, body = incoming.get_nowait()
                    except queue.Empty:
                        break
                    if not isinstance(body, dict):
                        continue
                    body = body.get('message', body)
                    if route == 'kicked':
                        raise RuntimeError('连接被服务器断开')
                    if route == 'onBossCopySelfHit':
                        server_hit = body.get('hit', server_hit)
                    elif route == 'onLeagueBossHpChange' and body.get('hp') == 0:
                        ended = True
                    elif route == 'onFinishLeagueBossCopy':
                        result = body
                        ended = True

            try:
                flow, _, scene = app._connect_and_enter(slot)
                if scene.get('code') != 200 or not scene.get('curRecord'):
                    raise RuntimeError(scene.get('error', '进入存档失败'))
                for route in ('onBossCopySelfHit', 'onLeagueBossHpChange',
                              'onFinishLeagueBossCopy', 'kicked'):
                    flow.on(route, lambda body, route=route: incoming.put((route, body)))
                response = flow.request('scene.leagueBossNewHandler.challengeBoss',
                                        {'pNum': 1, 'bossIndex': boss_index}, timeout=15)
                if response.get('code') != 200 or response.get('error'):
                    raise RuntimeError(response.get('error', '进场失败'))
                entered = True
                if int(response.get('bossIndex', 0)) != boss_index:
                    raise RuntimeError('服务器返回的难度与选择不一致')
                title = '%s梼杌，等级%s（ID %s）' % (
                    name, response.get('bossLv', '未知'), response.get('bossId', '未知'))
                app._log('[联盟梼杌] 进入成功：' + title)
                end_time = float(response['endTime']) / 1000
                next_send = time.monotonic() + 1
                count = 0
                submitted = 0
                while not stop.is_set() and time.time() < end_time:
                    drain()
                    if ended:
                        break
                    if time.monotonic() < next_send:
                        stop.wait(min(.1, next_send - time.monotonic()))
                        continue
                    hurt = initial_hurt if count == 0 else following_hurt
                    next_send = time.monotonic() + 1
                    attack = flow.request('scene.leagueBossNewHandler.attackLeagueBoss',
                                          {'bossIndex': boss_index, 'hurt': hurt}, timeout=15)
                    drain()
                    if attack.get('code') != 200 or attack.get('error'):
                        if ended or '挑战已结束' in str(attack.get('error', '')):
                            ended = True
                            break
                        raise RuntimeError(attack.get('error', '伤害提交失败'))
                    count += 1
                    submitted += hurt
                    show('%s；提交%d次，累计提交%d，服务器累计伤害%s' %
                         (title, count, submitted, server_hit))
                if not stop.is_set():
                    # 血量归零、结束回包与最终结算可能先后到达。
                    deadline = time.monotonic() + 3
                    while result is None and time.monotonic() < deadline and not stop.is_set():
                        stop.wait(.1)
                        drain()
                if result is not None:
                    text = '结算%s：排名%s，伤害%s；奖励详见邮件' % (
                        '成功' if result.get('success') else '结束',
                        result.get('rank', '未知'), result.get('hit', server_hit))
                    app._log('[联盟梼杌] ' + text)
                    app._log('[联盟梼杌] 奖励明细：排名%s，参与%s' %
                             (result.get('rankReward', []), result.get('joinReward', [])))
                    show(text)
                else:
                    show('已手动停止' if stop.is_set() else '本场已结束，未收到最终结算；请查看邮件或联盟记录')
            except Exception as error:
                text = str(error)
                app._log('[联盟梼杌] 已停止：' + text)
                show('已停止：' + text)
            finally:
                if flow:
                    if entered:
                        try:
                            flow.request('scene.leagueBossNewHandler.exitLeagueBoss', {}, timeout=10)
                        except Exception as error:
                            app._log('[联盟梼杌] 退出未确认：%s' % error)
                    flow.disconnect()
                def finish():
                    start_button.config(state='normal')
                    stop_button.config(state='disabled')
                    combo.config(state='readonly')
                    first_entry.config(state='normal')
                    tick_entry.config(state='normal')
                app.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    start_button = ttk.Button(controls, text='进入并自动挑战', command=start)
    start_button.pack(side='left', padx=5)
    stop_button = ttk.Button(controls, text='停止并退出', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=5)
