"""仅领取Argot.xml中有效的暗语，不猜口令、不购买、不自动使用奖励。"""
from collections import Counter
import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk
from free_activity_gifts import bag, points, verify_claim
from toolbox_identity import require_identity, identity_busy, lock_controls

ROUTE = 'scene.holidayHandler.getArgotReward'


class Unconfirmed(RuntimeError):
    pass


def expected_items(row):
    if str(row.get('type')) != 'item' or not str(row.get('argot', '')).strip(): return None
    ids, nums = str(row.get('itemId', '')).split(';'), str(row.get('num', '')).split(';')
    if len(ids) != len(nums): return None
    result = Counter()
    try:
        limit = int(row.get('receiveNumMax', 0))
        if limit == 0 or limit < -1: return None
        for item_id, num in zip(ids, nums):
            if int(item_id) <= 0 or int(num) <= 0: return None
            result[int(item_id)] += int(num)
    except (TypeError, ValueError): return None
    return dict(result) or None


def state(row, now=None):
    from super_gift import _now, _parse_time
    now = now or _now()
    if not expected_items(row): return '配置待核实'
    start, end = _parse_time(row.get('openTime')), _parse_time(row.get('underTime'))
    if start is None or end is None or start > end: return '日期待核实'
    return '未开始' if now < start else '已过期' if now > end else '可尝试领取'


def available(rows, now=None):
    seen = set(); result = []
    for row in rows:
        if not isinstance(row, dict) or state(row, now) != '可尝试领取': continue
        text = row['argot']
        if text in seen: continue
        seen.add(text); result.append(dict(row))
    return result


def claim_once(flow, scene, row, now=None):
    if not available([row], now): raise RuntimeError('暗语已过期、未开始或配置不支持，未发送领取')
    expected = expected_items(row); before = bag(scene); baseline = points(scene)
    if before['capacity'] is None or before['capacity'] - before['used'] < len(expected):
        raise RuntimeError('道具背包需至少%d个空格，未发送领取' % len(expected))
    reply = flow.request(ROUTE, {'text': row['argot']}, timeout=20)
    if not isinstance(reply, dict): raise Unconfirmed('暗语回包不是对象，结果待核实，不自动重试')
    error = str(reply.get('error') or '')
    if error:
        if any(word in error for word in ('重复领取', '已经领取', '已领取', '已兑换')):
            return {'status': 'already_claimed', 'text': row['argot'], 'message': error}
        raise RuntimeError('暗语领取被拒绝：'+error)
    if reply.get('code') != 200: raise RuntimeError('暗语领取返回代码%s，已停止' % reply.get('code'))
    if 'items' in reply:
        received = Counter()
        try:
            for item in reply['items']: received[int(item['id'])] += int(item['count'])
        except (TypeError, ValueError, KeyError): raise Unconfirmed('奖励结构未知，结果待核实，不自动重试')
        if dict(received) != expected: raise Unconfirmed('暗语奖励回包与配置不符，不自动重试')
    return {'status': 'pending_verification', 'type': 'argot', 'text': row['argot'],
            'expected_items': expected, 'before_counts': {i: before['counts'].get(i, 0) for i in expected}, 'points': baseline}


def claim_all(connect, rows, emit, stop=None):
    stop = stop or threading.Event(); flow = None; done = []; skipped = []
    try:
        for row in available(rows):
            if stop.is_set(): break
            flow, _, scene = connect()
            result = claim_once(flow, scene, row)
            flow.disconnect(); flow = None
            if result['status'] == 'already_claimed':
                skipped.append(row['argot']); emit('已领取，跳过：'+row['argot']); continue
            flow, _, scene = connect()
            try: verify_claim(result, scene)
            except Exception as error: raise Unconfirmed(str(error))
            flow.disconnect(); flow = None
            done.append(row['argot']); emit('领取并重登核验成功：'+row['argot'])
        return {'claimed': done, 'already_claimed': skipped, 'stopped': stop.is_set()}
    finally:
        if flow:
            try: flow.disconnect()
            except Exception: pass


def build_tab(app, notebook, shared, set_shared_busy, refresh):
    page = ttk.Frame(notebook); notebook.add(page, text='暗语礼包')
    ttk.Label(page, text='从Argot.xml读取原文，一键依次领取当前有效暗语；重复领取会跳过，奖励保留不自动使用。', wraplength=850).pack(anchor='w', pady=4)
    status = ttk.Label(page, text='尚未读取暗语配置', wraplength=850); status.pack(anchor='w', pady=4)
    tree = ttk.Treeview(page, columns=('text','state','end','reward'), show='headings', height=3)
    for key, title, width in (('text','暗语',200),('state','状态',100),('end','截止时间',160),('reward','奖励道具',300)):
        tree.heading(key,text=title);tree.column(key,width=width)
    tree.pack(fill='x')
    scroll=ttk.Scrollbar(page,orient='horizontal',command=tree.xview);tree.configure(xscrollcommand=scroll.set);scroll.pack(fill='x')
    bar=ttk.Frame(page);bar.pack(anchor='w',pady=5)
    local={'rows':[],'version':'?','blocked':set()};history=tk.BooleanVar(value=False);stop=threading.Event()
    button=ttk.Button(bar,text='一键领取暗语礼包',state='disabled');button.pack(side='left')
    stop_button=ttk.Button(bar,text='停止后续领取',state='disabled',command=stop.set);stop_button.pack(side='left',padx=5)
    ttk.Button(bar,text='刷新暗语配置',command=refresh).pack(side='left',padx=5)

    def identity():return (id(getattr(app,'client',None)),(getattr(app,'current_save',None) or {}).get('index'))
    def render():
        for key in tree.get_children():tree.delete(key)
        for n,row in enumerate(local['rows']):
            row_state=state(row)
            if row_state!='可尝试领取' and not history.get():continue
            reward='；'.join('%s×%s'%(i,count) for i,count in (expected_items(row) or {}).items())
            tree.insert('', 'end', iid=str(n), values=(row.get('argot','?'),row_state,row.get('underTime','?'),reward))
        count=len(available(local['rows']))
        status.configure(text='配置%s：共%d条，当前有效%d条。'%(local['version'],len(local['rows']),count))
        button.configure(state='normal' if count and not shared['busy'] and identity() not in local['blocked'] else 'disabled')

    ttk.Checkbutton(bar,text='显示历史暗语',variable=history,command=render).pack(side='left',padx=5)
    def update(cache):
        if isinstance(cache.get('argotRows'),list):
            local['rows']=cache['argotRows'];local['version']=cache.get('argotVersion',cache.get('freeVersion','?'))
        else:
            path=Path(__file__).resolve().parent/'output_cg1_20260921_1_2/005___Argot.xml.json'
            try:
                raw=json.loads(path.read_text(encoding='utf-8-sig'))
                local['rows']=raw.get('RECORD',[]) if isinstance(raw,dict) else []
            except (OSError,ValueError,TypeError):local['rows']=[]
            local['version']='本地默认；可点击刷新暗语配置'
        if not isinstance(local['rows'],list):local['rows']=[]
        local['rows']=[r for r in local['rows'] if isinstance(r,dict)];render()

    def run():
        if shared['busy'] or identity_busy(app) or identity() in local['blocked'] or not app._ensure_login():return
        rows=available(local['rows'])
        if not rows:return
        client,slot=app.client,app.current_save['index'];key=identity();stop.clear()
        require_identity(app,client,slot);set_shared_busy(True);lock_controls(app,True)
        button.configure(state='disabled');stop_button.configure(state='normal');status.configure(text='正在依次领取有效暗语…')
        def connect():
            require_identity(app,client,slot);flow,entry,scene=app._connect_and_enter(slot)
            try:require_identity(app,client,slot)
            except Exception:flow.disconnect();raise
            return flow,entry,scene
        def emit(text):app._log('[暗语礼包] '+text)
        def worker():
            blocked=False
            try:
                result=claim_all(connect,rows,emit,stop);text='暗语礼包：成功%d条，已领跳过%d条%s。'%(len(result['claimed']),len(result['already_claimed']),'，已停止' if result['stopped'] else '')
            except Exception as error:
                blocked=isinstance(error,(Unconfirmed,TimeoutError,ConnectionError,OSError));text='暗语礼包已停止：%s'%error
            emit(text)
            def finish():
                if blocked:local['blocked'].add(key)
                set_shared_busy(False);lock_controls(app,False);stop_button.configure(state='disabled');render();status.configure(text=text)
            app.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()
    button.configure(command=run)
    update({})
    return update
