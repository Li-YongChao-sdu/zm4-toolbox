"""金甲战猿活动副本入口，免费次数共享，不购买挑战次数。"""
import threading
import tkinter as tk
from tkinter import ttk

def run(app, mid, expected_client=None, expected_slot=None):
    from mainfarm_routes import clear_stage, dungeon_rows
    if app._limited_config_expired('抓捕金甲战猿'): raise RuntimeError('金甲战猿活动已过期')
    if expected_client is None: expected_client = app.client
    if expected_slot is None: expected_slot = (getattr(app, 'current_save', None) or {}).get('index')
    row = dungeon_rows().get(mid) or {}
    if not row:
        raise RuntimeError('关卡配置缺失，已停止')
    if str(row.get('consumePointTicket')) != '0':
        raise RuntimeError('该关卡需要点券，已停止')
    max_times = int(row.get('dailyCountMax') or 0)
    ticket_price = int(row.get('ticket') or 0)
    results, counts, details, gem_prev, total = [], {}, [], None, 0
    while True:
        flow = None
        try:
            if expected_slot is None:
                flow, entry, scene = app._connect_and_enter()
            else:
                flow, entry, scene = app._connect_and_enter(expected_slot, expected_client=expected_client)
            used = sum(int(r.get('num',0)) for r in scene['curRecord'].get('copyHistory',[])
                       if int(r.get('id',0)) in (2091,2092))
            gem = (scene.get('user') or {}).get('gem')
            if gem is not None:
                gem = int(gem)
                if gem_prev is not None and gem < gem_prev:
                    raise RuntimeError('检测到点券减少（%s→%s），已停止挑战' % (gem_prev, gem))
                gem_prev = gem
            if used >= max_times:
                if total == 0:
                    raise RuntimeError('今日共享免费次数已用完（%d/%d）' % (used, max_times))
                app._log('[金甲战猿] 免费次数已用完（%d/%d），共挑战%d次' % (used, max_times, total))
                break
            if total >= max_times:
                raise RuntimeError('服务器免费次数未增加，已停止，避免消耗点券')
            app._log('[金甲战猿] 第%d次挑战，剩余免费%d次%s' % (
                total + 1, max_times - used,
                ('；不购买额外次数（%d点券/次）' % ticket_price) if ticket_price else ''))
            class BoundFlow:
                def request(self, route, data, **options):
                    if app.client is not expected_client or (expected_slot is not None and app.current_save['index'] != expected_slot):
                        raise RuntimeError('账号或存档已切换，停止挑战')
                    return flow.request(route, data, **options)
            result = clear_stage(BoundFlow(), scene, mid)
            total += 1
            results.append(result)
            for key, value in (result.get('counts') or {}).items():
                counts[key] = counts.get(key, 0) + int(value or 0)
            details.extend(result.get('details') or [])
            app._log('[金甲战猿] 第%d次结算：%s' % (total, result.get('counts')))
        finally:
            if flow: flow.disconnect()
    return {'mid': mid, 'runs': total, 'counts': counts, 'details': details, 'results': results}

def build_tab(app):
    tab = app._limited_page('抓捕金甲战猿', padding=12)
    ttk.Label(tab,text='简单/困难共享每天2次免费挑战；点一次打完全部剩余免费次数，免费次数用完即停止，不购买200点券/次的额外次数，也不自动消耗战猿灵珠。奖励以服务器结算为准。').pack(anchor='w')
    mode=tk.StringVar(value='简单')
    ttk.Combobox(tab,textvariable=mode,values=('简单','困难'),state='readonly').pack(anchor='w',pady=8)
    def click():
        if not app._ensure_login() or getattr(app,'_limited_activity_busy',False): return
        mid=2091 if mode.get()=='简单' else 2092
        client, slot = app.client, app.current_save['index']
        app._limited_activity_busy=True;button.config(state='disabled')
        def worker():
            try:run(app,mid,client,slot)
            except Exception as e:app._log('[金甲战猿] 未完成：'+str(e))
            finally:
                app._limited_activity_busy=False
                app.root.after(0,lambda:button.config(state='normal'))
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(tab,text='挑战剩余免费次数',command=click);button.pack(anchor='w')
