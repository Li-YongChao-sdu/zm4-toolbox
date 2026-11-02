"""普通材料采集：材料目录来自游戏 Collect 配置。"""
import json
import math
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox


def build_tab(app):
    rows = json.loads((Path(__file__).parent / 'output_cg1_20260921_1_2/025___Collect.xml.json').read_text(encoding='utf-8'))['RECORD']
    rows = [r for r in rows if r.get('propType') in ('2', '3', '4')]
    tab = ttk.Frame(app.daily_notebook, padding=10)
    app.daily_notebook.add(tab, text='材料采集')
    category = tk.StringVar(value='木材')
    material = tk.StringVar()
    mode = tk.StringVar(value='按数量')
    amount = tk.StringVar(value='12')
    hours = tk.StringVar(value='1')
    ttk.Label(tab, text='选择具体材料采集', font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=8)
    line = ttk.Frame(tab); line.pack(fill='x', pady=5)
    types = ttk.Combobox(line, textvariable=category, values=['木材', '矿石', '布料'], state='readonly', width=8)
    types.pack(side='left')
    choice = ttk.Combobox(line, textvariable=material, state='readonly', width=35)
    choice.pack(side='left', padx=8)
    available = {}
    def update(event=None):
        available.clear()
        kind = {'木材':'2', '矿石':'3', '布料':'4'}[category.get()]
        for r in rows:
            if r['propType'] == kind:
                available['%s（%s）' % (r['name'], r.get('label', ''))] = r
        choice['values'] = list(available)
        if available: choice.current(0)
    types.bind('<<ComboboxSelected>>', update); update()
    line = ttk.Frame(tab); line.pack(fill='x', pady=5)
    ttk.Combobox(line, textvariable=mode, values=['按数量', '按时长'], state='readonly', width=9).pack(side='left')
    ttk.Label(line, text='目标材料数量：').pack(side='left', padx=(8,0))
    ttk.Entry(line, textvariable=amount, width=8).pack(side='left')
    ttk.Label(line, text='时长（小时）：').pack(side='left', padx=(8,0))
    ttk.Entry(line, textvariable=hours, width=8).pack(side='left')
    ttk.Label(tab, text='数量按每轮产量向上取整；时长按完整采集轮次向上取整。VIP5及以上产量翻倍。\n采集消耗体力，材料解锁条件由服务器校验。先预览，再开始；到时点击领取。', wraplength=680).pack(anchor='w', pady=8)
    status = ttk.Label(tab, text='待操作', wraplength=680); status.pack(anchor='w', pady=8)
    buttons = []
    def operate(action):
        if not app._ensure_login(): return
        row = available.get(material.get())
        selected_mode = mode.get()
        try:
            value = float(amount.get() if selected_mode == '按数量' else hours.get())
            if not math.isfinite(value) or value <= 0: raise ValueError()
            if selected_mode == '按数量' and value != int(value): raise ValueError()
        except ValueError:
            messagebox.showwarning('提示', '请输入正整数数量或大于0的小时数'); return
        save = app.current_save['index']
        for b in buttons: b.config(state='disabled')
        def worker():
            flow = None
            try:
                flow, entry, scene = app._connect_and_enter(save)
                cur = scene.get('curRecord', {})
                def request(route, body):
                    result = flow.request(route, body, timeout=15)
                    if result.get('code') != 200 or result.get('error'):
                        raise RuntimeError(result.get('error') or str(result))
                    return result
                result = {'collectInfo':(entry.get('record') or {}).get('collectInfo') or {}, 'serverTime':scene.get('serverTime') or entry.get('serverTime'), 'collectPower':cur.get('collectPower', 0)}
                info = result.get('collectInfo') or {}
                slots = info.get('slots') if isinstance(info, dict) else None
                tasks = list(slots.values()) if isinstance(slots, dict) else ([info] if info.get('id') else [])
                now = int(result.get('serverTime') or 0)
                if action == '领取':
                    if not tasks: raise RuntimeError('没有待领取的采集任务')
                    if not now: raise RuntimeError('服务器未返回时间，无法确认采集完成')
                    if any(int(t.get('endTime', 0)) > now for t in tasks):
                        raise RuntimeError('仍有采集未完成，请到时再领，避免提前终止')
                    results = []
                    for slot, task in (slots or {'0':info}).items():
                        if not task: continue
                        results.append(request('scene.copyHandler.endCollectData', {'type':2,'isSubGem':0,'index':str(slot),'num':0}))
                    result = {'data':[item for response in results for item in response.get('data', [])]}
                    names = {str(r['propId']):r['name'] for r in rows}
                    text = '领取回包：' + '、'.join('%s ×%s' % (names.get(str(x['id']), str(x['id'])), x['count']) for x in result.get('data', []))
                elif action == '状态':
                    names = {str(r['id']):r['name'] for r in rows}
                    text = '；'.join('%s：%s轮，%s' % (names.get(str(t.get('id')), str(t.get('id'))), t.get('num'), '可领取' if now and int(t.get('endTime',0)) <= now else '采集中') for t in tasks) or '没有进行中的采集'
                else:
                    if not row: raise RuntimeError('请选择材料')
                    vip = int((scene.get('user') or {}).get('vipLevel', 0) or 0)
                    per = int(row['collectNum']) * (2 if vip >= 5 else 1)
                    seconds = int(row['collectTime'])
                    num = math.ceil(value / per) if selected_mode == '按数量' else math.ceil(value * 3600 / seconds)
                    cost = num * int(row['collectPower'])
                    power = int(result.get('collectPower', cur.get('collectPower', 0)))
                    text = '%s：%d轮，预计%d个，%.2f小时，消耗%d体力；当前体力%d，VIP%d。' % (row['name'], num, num*per, num*seconds/3600, cost, power, vip)
                    if num > 60: raise RuntimeError(text + ' 单批最多60轮，请减少数量或时长。')
                    if action == '开始':
                        if tasks: raise RuntimeError('已有采集任务，请先完成并领取')
                        if cost > power: raise RuntimeError(text + ' 体力不足。')
                        result = request('scene.copyHandler.collectData', {'id':int(row['id']), 'num':num, 'index':1})
                        text = '服务器已接受采集。' + text
                app._log('[材料采集] ' + text)
            except Exception as error:
                text = '操作停止：%s' % error
                app._log('[材料采集] ' + text)
            finally:
                if flow: flow.disconnect()
                def finish(message=text):
                    status.config(text=message)
                    for b in buttons: b.config(state='normal')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()
    line = ttk.Frame(tab); line.pack(fill='x', pady=8)
    for label, action in [('预览数量/时长/消耗','预览'), ('开始采集','开始'), ('刷新采集状态','状态'), ('领取已完成材料','领取')]:
        button = ttk.Button(line, text=label, command=lambda a=action: operate(a))
        button.pack(side='left', padx=3); buttons.append(button)
