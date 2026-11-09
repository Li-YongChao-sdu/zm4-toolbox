"""联盟药园：读取土地、消耗现有种子种植、仙露浇水、成熟收获。"""
import json
from pathlib import Path
import threading
import time
import math


def prop_config():
    root = Path(__file__).resolve().parent
    # Use the bundled, readable configuration; prefer newer extracted entries.
    result = {}
    for folder in ('output_cg1_20260921_1_2', 'config_review_20261012_2/decoded'):
        for path in (root / folder).glob('*___Prop.xml.json'):
            for row in json.loads(path.read_text(encoding='utf-8-sig'))['RECORD']:
                result[int(row['id'])] = row
    if not result:
        raise RuntimeError('缺少Prop配置，无法识别种子与仙露消耗')
    return result


def checked(flow, route, payload):
    result = flow.request(route, payload, timeout=20)
    if result.get('code') != 200 or result.get('error'):
        raise RuntimeError(str(result.get('error') or '请求失败：' + route))
    return result


def item_counts(scene):
    rows = ((scene.get('curRecord') or {}).get('itemsBag') or {}).get('items') or []
    if isinstance(rows, dict):
        rows = rows.values()
    counts = {}
    for row in rows:
        key = int(row['id'])
        counts[key] = counts.get(key, 0) + int(row.get('count', 1))
    return counts


def inspect_land(flow, scene, config):
    data = checked(flow, 'league.leagueHandler.getLeagueInfo1', {})
    measured_at = time.monotonic()
    league = data.get('leagueInfo')
    if not isinstance(league, dict):
        raise RuntimeError('当前存档没有可读取的联盟药园')
    plant = league.get('plantLandInfo') or {}
    raw = plant.get('landInfo')
    if not isinstance(raw, list) or 'plantLandNum' not in plant or not data.get('time'):
        raise RuntimeError('土地列表、开放数量或服务器时间缺失')
    personal = checked(flow, 'league.leagueHandler.getUserLeagueInfo', {})
    if not isinstance(personal.get('userInfo'), dict):
        raise RuntimeError('未收到个人药园仓库数据')
    now = int(data['time'])
    locks = plant.get('lock') or {}
    lands = []
    for index in range(int(plant['plantLandNum'])):
        row = (raw[index] if index < len(raw) else None) or {}
        seed = int(row.get('seedId') or 0)
        grow = int(row.get('grow') or 0)
        next_time = int(row.get('nextTime') or 0)
        remaining = max(0, next_time - now)
        if seed <= 0:
            status = '冷却中' if remaining else '可种植'
        elif grow >= 10:
            status = '可收获'
        else:
            status = '生长中'
        lock = locks.get(str(index), locks.get(index, [])) if isinstance(locks, dict) else (
            locks[index] if isinstance(locks, list) and index < len(locks) else [])
        if lock is None:
            lock = []
        if not isinstance(lock, list):
            raise RuntimeError('未知地块种子限制结构')
        farmer = row.get('farmerInfo') or {}
        helpers = row.get('helperList') or []
        lands.append(dict(landNum=index, seedId=seed, grow=grow, nextTime=next_time,
                          farmerId=farmer.get('userId'), farmer=farmer.get('name', ''),
                          crop=config.get(seed, {}).get('name', str(seed) if seed > 0 else '—'),
                          helpers='、'.join(str(x.get('name', '')) for x in helpers if isinstance(x, dict)),
                          state=status, remaining=remaining, allowedSeeds=[int(x) for x in lock]))
    return dict(lands=lands, counts=item_counts(scene), measured_at=measured_at,
                storage=personal['userInfo'].get('storageInfo') or {},
                leaguePost=(scene.get('user') or {}).get('leaguePost'),
                points={k: (scene.get('user') or {}).get(k) for k in ('gem', 'usedGem')})


def fingerprint(land):
    return tuple(land.get(k) for k in ('landNum', 'seedId', 'farmerId', 'grow', 'nextTime'))


def plant_seed(flow, snapshot, land_num, seed_id, config):
    land = snapshot['lands'][land_num]
    seed = config.get(seed_id) or {}
    if land['state'] != '可种植':
        raise RuntimeError('此地块不是空闲可种植状态')
    if int(seed.get('propType', 0)) != 48:
        raise RuntimeError('所选道具不是药园种子')
    if snapshot['counts'].get(seed_id, 0) < 1:
        raise RuntimeError('背包没有该种子')
    if land['allowedSeeds'] and seed_id not in land['allowedSeeds']:
        raise RuntimeError('该地块不允许种植所选种子')
    return checked(flow, 'scene.leagueHandler.tillLand', {'landNum': land_num, 'itemId': seed_id})


def water_land(flow, snapshot, land_num, config):
    land = snapshot['lands'][land_num]
    if land['state'] != '生长中':
        raise RuntimeError('仅可浇灌尚未成熟的植物')
    seed = config.get(land['seedId']) or {}
    cost = int(seed.get('attributV1') or 0)
    if cost <= 0:
        raise RuntimeError('未确认仙露消耗，停止')
    if snapshot['counts'].get(147200001, 0) < cost:
        raise RuntimeError('仙露不足，需要%d滴' % cost)
    return checked(flow, 'scene.leagueHandler.wateringSeed', {'landNum': land_num, 'type': 1})


def harvest_land(flow, snapshot, land_num):
    if snapshot['lands'][land_num]['state'] != '可收获':
        raise RuntimeError('该植物尚未成熟')
    return checked(flow, 'scene.leagueHandler.getResultItem', {'landNum': land_num})


def build_panel(app, parent):
    import tkinter as tk
    from tkinter import ttk
    ttk.Label(parent, text='联盟药园：土地检测、种植、仙露浇水、成熟收获',
              font=('Microsoft YaHei', 11, 'bold')).pack(anchor='w', pady=5)
    ttk.Label(parent, text='选择一块地后执行一次操作。种植消耗现有种子，浇水仅使用仙露。'
              '本人作物收获首先进入药园仓库；帮助他人收获不代表本人获得产物。',
              wraplength=850).pack(anchor='w', pady=5)
    state = {'busy': False, 'snapshot': None, 'identity': None, 'config': {}, 'seeds': [],
             'cards': {}, 'timer': None, 'expiry_requested': False, 'columns': 0}
    status = tk.StringVar(value='先登录、选择存档，再点击检测土地。土地读取及仙露浇水已实测；种植、收获尚待验证。')
    ttk.Label(parent, textvariable=status, wraplength=850).pack(anchor='w', pady=5)
    overview = ttk.LabelFrame(parent, text='土地状况', padding=8)
    overview.pack(fill='x', pady=5)
    summary = tk.StringVar(value='等待检测土地')
    ttk.Label(overview, textvariable=summary, wraplength=850).pack(anchor='w', pady=(0, 6))
    cards = ttk.Frame(overview)
    cards.pack(fill='x')
    ttk.Label(overview, text='绿色：空地可种植　橙色：冷却　蓝色：生长中　金色：可收获。'
              '点击地块可选中；生长进度以服务器检测结果为准。',
              wraplength=850).pack(anchor='w', pady=(6, 0))
    ttk.Label(parent, text='土地详细列表').pack(anchor='w')
    frame = ttk.Frame(parent)
    frame.pack(fill='both', expand=True, pady=5)
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    columns = ('number', 'state', 'crop', 'grow', 'farmer', 'cd', 'helpers', 'lock')
    tree = ttk.Treeview(frame, columns=columns, show='headings', selectmode='browse', height=7)
    for col, title, width in zip(columns, ('土地', '状态', '作物', '进度', '种植者', '冷却', '参与者', '限种'),
                                 (55, 80, 140, 65, 120, 90, 180, 160)):
        tree.heading(col, text=title)
        tree.column(col, width=width, stretch=False)
    vertical = ttk.Scrollbar(frame, orient='vertical', command=tree.yview)
    horizontal = ttk.Scrollbar(frame, orient='horizontal', command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    tree.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    seed_row = ttk.Frame(parent)
    seed_row.pack(fill='x', pady=5)
    ttk.Label(seed_row, text='背包种子：').pack(side='left')
    seeds = ttk.Combobox(seed_row, state='readonly', width=56)
    seeds.pack(side='left', fill='x', expand=True)
    detail = tk.StringVar(value='浇水消耗会随所选地块显示；同一角色能否重复浇水由服务器校验。')
    ttk.Label(parent, textvariable=detail, wraplength=850).pack(anchor='w', pady=5)
    storage = tk.Text(parent, height=3, wrap='word', state='disabled')
    storage.pack(fill='x', pady=5)
    buttons = []
    actions = ttk.Frame(parent)
    actions.pack(anchor='w', pady=5)

    def show_detail(event=None):
        selected = tree.selection()
        if selected and state['snapshot']:
            land = state['snapshot']['lands'][int(selected[0])]
            seed = state['config'].get(land['seedId'], {})
            detail.set('第%d块地：%s；仙露浇水消耗%s滴。' %
                       (land['landNum'] + 1, land['state'], seed.get('attributV1', '未知')))
        for index, button in state['cards'].items():
            button.configure(relief='sunken' if str(index) in selected else 'raised',
                             borderwidth=3 if str(index) in selected else 1)
    tree.bind('<<TreeviewSelect>>', show_detail)

    def select_land(index):
        if tree.exists(str(index)):
            tree.selection_set(str(index))
            tree.see(str(index))
            show_detail()

    def arrange_cards(event=None):
        count = max(1, min(4, cards.winfo_width() // 235))
        if count == state['columns']:
            return
        state['columns'] = count
        for col in range(4):
            cards.columnconfigure(col, weight=1 if col < count else 0)
        for position, button in enumerate(state['cards'].values()):
            button.grid(row=position // count, column=position % count, sticky='nsew', padx=3, pady=3)
    cards.bind('<Configure>', arrange_cards)

    def update_overview():
        snapshot = state['snapshot']
        if not snapshot:
            return False
        elapsed = max(0, time.monotonic() - snapshot['measured_at'])
        totals = {'可种植': 0, '冷却中': 0, '生长中': 0, '可收获': 0}
        expired = False
        colors = {'可种植': '#e2f2df', '冷却中': '#fff0d6', '生长中': '#e1eefb', '可收获': '#fff4b8'}
        for land in snapshot['lands']:
            index = land['landNum']
            kind = land['state']
            totals[kind] += 1
            seconds = max(0, math.ceil(land['remaining'] / 1000 - elapsed))
            cd = '%02d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60)
            lock = '、'.join(state['config'].get(x, {}).get('name', str(x))
                             for x in land['allowedSeeds']) or '不限'
            if kind == '冷却中':
                text = '空地 · 冷却中\n剩余 ' + cd if seconds else '空地 · 冷却预计结束\n等待服务器确认'
                expired = expired or seconds == 0
                tree.set(str(index), 'cd', cd if seconds else '待刷新确认')
            elif kind == '可种植':
                text = '空地 · 可种植\n无作物'
            else:
                seed = state['config'].get(land['seedId'], {})
                target = state['config'].get(int(seed.get('makeId') or 0), {})
                crop = target.get('name') or land['crop'].removesuffix('种子')
                text = '%s　%d/10\n%s · %s' % (crop, land['grow'], kind, land['farmer'] or '种植者未知')
            text += '\n限种：' + lock
            button = state['cards'].get(index)
            if button:
                button.configure(text='第%d块地\n%s' % (index + 1, text), bg=colors[kind],
                                 activebackground=colors[kind])
        summary.set('共%d块地：空闲%d　冷却%d　生长中%d　可收获%d' %
                    (len(snapshot['lands']), totals['可种植'], totals['冷却中'], totals['生长中'], totals['可收获']))
        return expired

    def render(snapshot, config):
        selected = tree.selection()
        tree.delete(*tree.get_children())
        for land in snapshot['lands']:
            seconds = land['remaining'] // 1000
            cd = '%02d:%02d:%02d' % (seconds // 3600, seconds // 60 % 60, seconds % 60) if land['state'] == '冷却中' else '—'
            lock = '、'.join(config.get(x, {}).get('name', str(x)) for x in land['allowedSeeds']) or '不限'
            tree.insert('', 'end', iid=str(land['landNum']), values=(land['landNum'] + 1, land['state'],
                        land['crop'], '%d/10' % land['grow'] if land['seedId'] > 0 else '—',
                        land['farmer'], cd, land['helpers'], lock))
        for button in state['cards'].values():
            button.destroy()
        state['cards'] = {}
        for land in snapshot['lands']:
            index = land['landNum']
            button = tk.Button(cards, anchor='w', justify='left', width=24, height=4,
                               wraplength=220, command=lambda value=index: select_land(value))
            state['cards'][index] = button
        state['columns'] = 0
        state['expiry_requested'] = False
        arrange_cards()
        update_overview()
        if selected and tree.exists(selected[0]):
            tree.selection_set(selected[0])
        state['seeds'] = [key for key in sorted(config) if int(config[key].get('propType', 0)) == 48
                          and snapshot['counts'].get(key, 0) > 0]
        seeds['values'] = ['%s ×%d（%s）' % (config[key].get('name', key), snapshot['counts'][key], key)
                           for key in state['seeds']]
        seeds.set('')
        if state['seeds']:
            seeds.current(0)
        rows = snapshot['storage']
        text = '药园仓库：' + ('；'.join('%s ×%s' % (config.get(int(k), {}).get('name', k), v)
                                      for k, v in rows.items()) if isinstance(rows, dict) else '未知结构')
        storage.configure(state='normal')
        storage.delete('1.0', 'end')
        storage.insert('1.0', text)
        storage.configure(state='disabled')
        show_detail()

    def start(action):
        if state['busy'] or not app._ensure_login():
            return
        slot = app.current_save['index']
        identity = (str(app.client.uid), slot)
        selected = tree.selection()
        expected = None
        seed_id = None
        if action != 'inspect':
            if state['identity'] != identity or not selected or not state['snapshot']:
                status.set('请先检测当前账号存档的土地，并选择一块地')
                return
            expected = dict(state['snapshot']['lands'][int(selected[0])])
            if action == 'plant':
                index = seeds.current()
                if index < 0:
                    status.set('请先选择背包中已有的种子')
                    return
                seed_id = state['seeds'][index]
        state['busy'] = True
        for button in buttons:
            button.configure(state='disabled')
        seeds.configure(state='disabled')
        status.set('正在读取服务器药园状态…')

        def worker():
            flow = None
            snapshot = None
            config = None
            sent = False
            text = ''
            try:
                if (str(app.client.uid), app.current_save['index']) != identity:
                    raise RuntimeError('账号或存档已切换，请重新检测')
                config = prop_config()
                flow, _, scene = app._connect_and_enter(slot)
                snapshot = inspect_land(flow, scene, config)
                if action != 'inspect':
                    index = expected['landNum']
                    if index >= len(snapshot['lands']) or fingerprint(snapshot['lands'][index]) != fingerprint(expected):
                        raise RuntimeError('该地块已变化，列表已更新；请重新选择操作')
                    # Only the selected operation is dispatched; no retries after a write.
                    if action == 'plant':
                        operation = lambda: plant_seed(flow, snapshot, index, seed_id, config)
                    elif action == 'water':
                        operation = lambda: water_land(flow, snapshot, index, config)
                    else:
                        operation = lambda: harvest_land(flow, snapshot, index)
                    sent = True
                    operation()
                    points = snapshot['points']
                    flow.disconnect()
                    flow = None
                    flow, _, scene = app._connect_and_enter(slot)
                    snapshot = inspect_land(flow, scene, config)
                    if snapshot['points'] != points:
                        raise RuntimeError('点券数据变化，请核查日志；已停止')
                    current = snapshot['lands'][index]
                    verified = ((action == 'plant' and current['seedId'] == seed_id) or
                                (action == 'water' and current['seedId'] == expected['seedId'] and
                                 current['grow'] > expected['grow']) or
                                (action == 'harvest' and current['seedId'] <= 0))
                    if not verified:
                        raise RuntimeError('请求返回成功，但重登土地状态未确认预期变化')
                    text = {'plant': '种植请求成功', 'water': '仙露浇水请求成功', 'harvest': '收获请求成功'}[action]
                    text += '；已重登刷新土地、背包种子/仙露和药园仓库。'
                else:
                    text = '槽%s：%d块地；仙露%d滴。' % (slot, len(snapshot['lands']), snapshot['counts'].get(147200001, 0))
                app._log('[联盟药园] ' + text)
            except Exception as error:
                text = '停止：' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__)
                if sent:
                    text += '；未自动重试，操作结果以重新检测为准。'
                app._log('[联盟药园] ' + text)
            finally:
                if flow:
                    flow.disconnect()
                def finish():
                    state['busy'] = False
                    for button in buttons:
                        button.configure(state='normal')
                    seeds.configure(state='readonly')
                    if not app.client or not app.current_save or (str(app.client.uid), app.current_save['index']) != identity:
                        status.set('账号或存档已切换，请重新检测土地')
                        return
                    if snapshot is not None and config is not None:
                        state.update(snapshot=snapshot, identity=identity, config=config)
                        render(snapshot, config)
                    status.set(text)
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for title, action in (('检测土地', 'inspect'), ('种植所选种子', 'plant'),
                          ('仙露浇水一次', 'water'), ('收获所选成熟作物', 'harvest')):
        button = ttk.Button(actions, text=title, command=lambda value=action: start(value))
        button.pack(side='left', padx=(0, 8))
        buttons.append(button)

    def tick():
        state['timer'] = None
        if not parent.winfo_exists():
            return
        if state['snapshot']:
            identity = (str(app.client.uid), app.current_save['index']) if app.client and app.current_save else None
            if identity != state['identity']:
                state.update(snapshot=None, identity=None, seeds=[])
                tree.delete(*tree.get_children())
                for button in state['cards'].values():
                    button.destroy()
                state['cards'] = {}
                seeds.set('')
                seeds['values'] = []
                summary.set('账号或存档已切换，请重新检测土地')
                detail.set('等待检测当前存档')
                storage.configure(state='normal')
                storage.delete('1.0', 'end')
                storage.configure(state='disabled')
            elif update_overview() and not state['expiry_requested'] and not state['busy'] and parent.winfo_viewable():
                # One read at expiry; no automatic planting, watering or harvesting.
                state['expiry_requested'] = True
                start('inspect')
        state['timer'] = parent.after(1000, tick)

    def destroy_timer(event):
        if event.widget == parent and state['timer'] is not None:
            parent.after_cancel(state['timer'])
            state['timer'] = None
    parent.bind('<Destroy>', destroy_timer, add='+')
    state['timer'] = parent.after(1000, tick)
