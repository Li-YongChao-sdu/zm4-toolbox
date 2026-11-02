"""官方速通；只使用已核实的能量、体力及免费次数。"""
import json
import threading
from pathlib import Path

def configs():
    root = Path(__file__).resolve().parent / 'config_review_20261012_2/decoded'
    def read(name):
        paths = list(root.glob('*___'+name+'.xml.json'))
        if len(paths) != 1: raise RuntimeError('缺少配置：'+name)
        return json.loads(paths[0].read_text(encoding='utf-8-sig'))['RECORD']
    return read('Sweep'), read('VIP')

def budget(scene, row):
    cur, user = scene.get('curRecord') or {}, scene.get('user') or {}
    _, vips = configs()
    vip = next((x for x in vips if str(x['id']) == str(user.get('vipLevel'))), None)
    if vip is None or cur.get('sweepEnergy') is None or cur.get('collectPower') is None:
        raise RuntimeError('能量、体力或VIP数据缺失，停止速通')
    remaining = int(vip['daySweep']) - int(cur['sweepEnergy'])
    cost, stamina = int(row['consumeNum']), max(0, int(row['tiliNum']))
    if cost <= 0 or int(row['tiliNum']) < -1: raise RuntimeError('消耗配置异常，停止速通')
    if remaining < cost: raise RuntimeError('剩余速通能量%d，不足%d；停止，不使用点券' % (remaining, cost))
    if int(cur['collectPower']) < stamina: raise RuntimeError('体力不足，停止速通')
    if cur.get('p1', {}).get('atkPoint') is None: raise RuntimeError('战力数据缺失')
    if int(cur['p1']['atkPoint']) < int(row['powerMin']): raise RuntimeError('战力不足')
    if int(row['daySweep']) > 0:
        root = Path(__file__).resolve().parent / 'config_review_20261012_2/decoded'
        paths = list(root.glob('*___Dungeon.xml.json'))
        if len(paths) != 1: raise RuntimeError('副本共享次数配置缺失')
        dungeons = json.loads(paths[0].read_text(encoding='utf-8-sig'))['RECORD']
        dungeon = next((d for d in dungeons if str(d['id']) == str(row['id'])), None)
        history = cur.get('copyHistory')
        if dungeon is None or not isinstance(history, list): raise RuntimeError('免费次数记录缺失，停止')
        shared = dungeon.get('shareDungeonID')
        ids = [int(x) for x in shared.split(';')] if isinstance(shared, str) and shared else [int(row['id'])]
        cap = min(int(row['daySweep']), int(dungeon['dailyCountMax']))
        if cap <= 0: raise RuntimeError('免费次数配置异常')
        used = sum(int(x['num']) for x in history if int(x['id']) in ids)
        if used >= cap: raise RuntimeError('副本共享免费次数已用完，停止，不使用点券')
    for key in ('gem', 'usedGem'):
        if user.get(key) is None: raise RuntimeError('点券核对数据缺失')
    return remaining

def sweep_once(flow, scene, row, hidden=False):
    remaining = budget(scene, row)
    body = {'mid': int(row['id'])}
    if str(row['isHide']) == '1': body['hide'] = int(bool(hidden))
    elif hidden: raise RuntimeError('此副本不支持隐藏选项')
    result = flow.request('scene.copyHandler.sweep', body, timeout=20)
    if result.get('code') != 200 or result.get('error'):
        raise RuntimeError(str(result.get('error') or '速通失败'))
    if result.get('sweepEnergy') is None: raise RuntimeError('速通已返回成功但能量未返回；停止，请重登核对')
    if int(result['sweepEnergy']) != int(scene['curRecord']['sweepEnergy']) + int(row['consumeNum']):
        raise RuntimeError('能量扣减与配置不符；停止，请重登核对')
    return result

def build_panel(app, parent):
    import tkinter as tk
    from tkinter import ttk
    rows, _ = configs()
    labels = ['%s（%s）%s' % (r['name'], r['id'], '［次数待适配］' if int(r['daySweep']) > 0 else '') for r in rows]
    chosen = tk.StringVar(master=parent, value=labels[0])
    times = tk.IntVar(master=parent, value=1)
    hidden = tk.BooleanVar(master=parent, value=False)
    ttk.Label(parent, text='官方副本速通').pack(anchor='w', pady=6)
    ttk.Combobox(parent, textvariable=chosen, values=labels, state='readonly', width=38).pack(anchor='w')
    row = ttk.Frame(parent); row.pack(anchor='w', pady=6)
    ttk.Label(row, text='次数：').pack(side='left')
    ttk.Spinbox(row, from_=1, to=100, textvariable=times, width=5).pack(side='left')
    ttk.Checkbutton(row, text='隐藏掉落（仅支持的副本）', variable=hidden).pack(side='left', padx=8)
    status = ttk.Label(parent, text='每次重新登录检查剩余能量、体力和免费次数。任一不足或无法确认即停止，不购买能量、不使用点券。', wraplength=680)
    status.pack(anchor='w', pady=6)
    stop = threading.Event(); buttons = []
    def run(start):
        if not app._ensure_login(): return
        try:
            selected = rows[labels.index(chosen.get())]; count = times.get(); hide = hidden.get()
            if not 1 <= count <= 100: raise ValueError('次数须为1至100')
        except (ValueError, tk.TclError) as e:
            status.config(text=str(e)); return
        slot = app.current_save['index']; stop.clear()
        for b in buttons: b.config(state='disabled')
        stop_button.config(state='normal' if start else 'disabled')
        def worker():
            flow = None; completed = 0; text = '已停止'
            baseline = None
            try:
                for _ in range(count if start else 1):
                    if stop.is_set(): break
                    flow, _, scene = app._connect_and_enter(slot)
                    points = tuple(scene.get('user', {}).get(k) for k in ('gem', 'usedGem'))
                    if baseline is None: baseline = points
                    elif points != baseline: raise RuntimeError('点券发生变化，停止后续速通')
                    remaining = budget(scene, selected)
                    if not start:
                        text = '%s：剩余能量%d，单次消耗%d，体力消耗%d，战力要求%s' % (selected['name'], remaining, int(selected['consumeNum']), int(selected['tiliNum']), selected['powerMin'])
                        break
                    result = sweep_once(flow, scene, selected, hide)
                    completed += 1
                    app._log('[官方速通] 第%d次成功：%s；掉落%s' % (completed, selected['name'], result.get('drops', {})))
                    flow.disconnect(); flow = None
                    # Fresh server state also verifies points after the final sweep.
                    flow, _, verified = app._connect_and_enter(slot)
                    if tuple(verified.get('user', {}).get(k) for k in ('gem', 'usedGem')) != baseline:
                        raise RuntimeError('重登发现点券变化，停止')
                    if int(verified['curRecord']['sweepEnergy']) != int(result['sweepEnergy']):
                        raise RuntimeError('重登能量与回包不符，停止')
                    text = '已完成%d次；点券未变。' % completed
                    flow.disconnect(); flow = None
            except Exception as e:
                text = '已完成%d次；%s。未自动重试，超时请先重登核对。' % (completed, e)
            finally:
                if flow:
                    try: flow.disconnect()
                    except Exception: pass
                app._log('[官方速通] '+text)
                def finish(message=text):
                    status.config(text=message)
                    for b in buttons: b.config(state='normal')
                    stop_button.config(state='disabled')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()
    controls = ttk.Frame(parent); controls.pack(anchor='w', pady=6)
    for label, start in (('查询消耗与资格', False), ('开始速通', True)):
        b = ttk.Button(controls, text=label, command=lambda start=start: run(start)); b.pack(side='left', padx=4); buttons.append(b)
    stop_button = ttk.Button(controls, text='本次结束后停止', command=stop.set, state='disabled'); stop_button.pack(side='left', padx=4)


def add_mode_controls(app, parent, key):
    import tkinter as tk
    from tkinter import ttk
    frame = ttk.Frame(parent)
    frame.pack(side='top', fill='x', pady=(0, 6))
    mode = tk.StringVar(master=parent, value='手打（非扫荡）')
    hidden = tk.BooleanVar(master=parent, value=False)
    stop = threading.Event()
    if not hasattr(app, '_sweep_controls'): app._sweep_controls = {}
    app._sweep_controls[key] = (mode, hidden, stop, parent)
    ttk.Label(frame, text='通关方式：').pack(side='left')
    ttk.Combobox(frame, textvariable=mode, values=('手打（非扫荡）', '扫荡'), state='readonly', width=18).pack(side='left')
    ttk.Checkbutton(frame, text='扫荡隐藏掉落', variable=hidden).pack(side='left', padx=6)
    ttk.Button(frame, text='停止扫荡', command=stop.set).pack(side='left')
    ttk.Label(frame, text='扫荡按整关结算；不支持的关卡停止，能量/免费次数不足停止。').pack(side='left', padx=6)

def dispatch(app, key, mids, times=1):
    from tkinter import ttk, messagebox
    mode, hidden, stop, parent = app._sweep_controls[key]
    if mode.get() != '扫荡': return False
    try:
        times = int(times)
        if not 1 <= times <= 100: raise ValueError('次数须为1至100')
        rows, _ = configs()
        by_id = {int(r['id']): r for r in rows}
        selected = [by_id[int(mid)] for mid in dict.fromkeys(mids)]
        if not selected: raise ValueError('请选择支持扫荡的关卡')
        hide = hidden.get()
        if hide and any(str(r['isHide']) != '1' for r in selected):
            raise ValueError('所选关卡不支持隐藏扫荡，请取消隐藏选项')
    except (KeyError, ValueError) as error:
        messagebox.showwarning('扫荡未开始', '关卡未配置官方扫荡或参数无效：%s' % error)
        return True
    if getattr(app, '_integrated_sweep_running', False):
        messagebox.showwarning('提示', '已有扫荡任务正在执行'); return True
    slot = app.current_save['index']
    owner = app.client
    app._integrated_sweep_running = True
    stop.clear()
    def children(widget):
        for child in widget.winfo_children():
            yield child
            yield from children(child)
    disabled = [(w, str(w.cget('state'))) for w in children(parent)
                if isinstance(w, ttk.Button) and w.cget('text') != '停止扫荡']
    for w, _ in disabled: w.config(state='disabled')
    def worker():
        flow = None; completed = 0; baseline = None
        try:
            for row in selected:
                for _ in range(times):
                    if stop.is_set(): return
                    flow, _, scene = app._connect_and_enter(slot)
                    points = tuple(scene.get('user', {}).get(k) for k in ('gem', 'usedGem'))
                    if baseline is None: baseline = points
                    elif points != baseline: raise RuntimeError('点券变化，停止')
                    result = sweep_once(flow, scene, row, hide)
                    completed += 1
                    app._log('[扫荡] %s成功：%s' % (row['name'], result.get('drops', {})))
                    flow.disconnect(); flow = None
                    flow, _, verified = app._connect_and_enter(slot)
                    if tuple(verified.get('user', {}).get(k) for k in ('gem', 'usedGem')) != baseline:
                        raise RuntimeError('重登点券变化，停止')
                    if int(verified['curRecord']['sweepEnergy']) != int(result['sweepEnergy']):
                        raise RuntimeError('重登能量与回包不符，停止')
                    flow.disconnect(); flow = None
        except Exception as error:
            app._log('[扫荡] 停止：%s；不自动重试，结果不明时先重登核对。' % error)
        finally:
            if flow:
                try: flow.disconnect()
                except Exception: pass
            app._log('[扫荡] 已完成%d次' % completed)
            def finish():
                app._integrated_sweep_running = False
                for w, state in disabled: w.config(state=state)
                app._refresh_finished_counts(slot, owner)
            app.root.after(0, finish)
    threading.Thread(target=worker, daemon=True).start()
    return True
