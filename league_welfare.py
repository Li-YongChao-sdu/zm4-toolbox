import json
import threading
from pathlib import Path
CHOICES = ('掉宝率', '回血', '回魔', '攻击')
ATTRS = dict(zip(CHOICES, ('dropProbability', 'reHP', 'reMP', 'atk')))
def checked(flow, route, body):
    r = flow.request(route, body, timeout=20)
    if r.get('code') != 200 or r.get('error'):
        raise RuntimeError(str(r.get('error') or '请求失败：' + route))
    return r
def config():
    root = Path(__file__).resolve().parent / 'config_review_20261012_2/decoded'
    def read(name):
        paths = list(root.glob('*___' + name + '.xml.json'))
        if len(paths) != 1: raise RuntimeError('缺少配置：' + name)
        return json.loads(paths[0].read_text(encoding='utf-8-sig'))['RECORD']
    return read('Union'), read('BuffScene'), int(read('Common')['unionBuffDayNum'])
def inspect(flow, choice='掉宝率'):
    if choice not in ATTRS: raise ValueError('无效Buff')
    unions, buffs, limit = config()
    league = checked(flow, 'league.leagueHandler.getLeagueInfo1', {}).get('leagueInfo') or {}
    personal = checked(flow, 'league.leagueHandler.getUserLeagueInfo', {})
    info = personal.get('userInfo') or {}
    used = personal.get('unionBuffDayNum', info.get('unionBuffDayNum'))
    union = next((x for x in unions if str(x['id']) == str(league.get('level'))), None)
    if used is None or union is None: raise RuntimeError('未收到联盟等级或当天Buff次数，停止领取')
    ids = [int(x) for x in str(union['buffSceneId']).split(';')]
    rows = [x for x in buffs if int(x['id']) in ids and x.get('attributes') == ATTRS[choice]]
    if len(rows) != 1: raise RuntimeError('无法唯一确认所选Buff')
    return dict(level=int(union['id']), used=int(used), limit=limit, contribution=info.get('totalContribution'), buff=rows[0])
def claim_free(flow, choice='掉宝率'):
    before = inspect(flow, choice)
    if before['used'] >= before['limit']: raise RuntimeError('今日免费Buff已领完，不消耗联盟贡献')
    result = checked(flow, 'scene.leagueHandler.getLeagueWelfare', {'buffId': int(before['buff']['id'])})
    return before, result

def build_panel(app, parent):
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text='联盟福利Buff').pack(anchor='w', pady=6)
    row = ttk.Frame(parent); row.pack(anchor='w', pady=5)
    choice = tk.StringVar(master=parent, value=CHOICES[0])
    ttk.Combobox(row, textvariable=choice, values=CHOICES, state='readonly', width=12).pack(side='left', padx=4)
    status = ttk.Label(parent, text='默认掉宝率；仅使用每日免费额度，不消耗联盟贡献。', wraplength=650)
    status.pack(anchor='w', pady=6)
    buttons = []
    def run(claim):
        if not app._ensure_login(): return
        save, selected = app.current_save['index'], choice.get()
        for b in buttons: b.config(state='disabled')
        def worker():
            flow = None
            text = '操作未完成'
            try:
                flow, _, _ = app._connect_and_enter(save)
                if claim:
                    before, result = claim_free(flow, selected)
                    text = '槽%s：%sBuff领取成功，持续%s分钟' % (save, selected, before['buff']['consumeParam'])
                    app._log('[联盟Buff] ' + text)
                    try:
                        after = inspect(flow, selected)
                        text += '；今日已领%d/%d次，贡献%s→%s' % (after['used'], after['limit'], before['contribution'], after['contribution'])
                    except Exception as e: text += '；刷新失败，请查询状态：' + str(e)
                else:
                    state = inspect(flow, selected); buff = state['buff']
                    effect = float(buff['buffEffect'])
                    amount = ('%g%%' % (effect*100)) if str(buff['isPercent']) == '1' else '%g' % effect
                    text = '槽%s：%d级联盟，%s+%s，持续%s分钟；今日已领%d/%d次，贡献%s' % (save, state['level'], selected, amount, buff['consumeParam'], state['used'], state['limit'], state['contribution'])
            except Exception as e: text = str(e) + '；不自动重试，结果不明时先查询状态。'
            finally:
                if flow:
                    try: flow.disconnect()
                    except Exception: pass
                app._log('[联盟Buff] ' + text)
                def finish(message=text):
                    status.config(text=message)
                    for b in buttons: b.config(state='normal')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()
    for label, claim in (('查询状态', False), ('免费领取', True)):
        b = ttk.Button(row, text=label, command=lambda claim=claim: run(claim)); b.pack(side='left', padx=4); buttons.append(b)
