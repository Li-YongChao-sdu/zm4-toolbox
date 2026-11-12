"""类型6及已核实类型12的免费分支；不调用商城，不自动打开礼包。"""
import json
import re
import threading
from collections import Counter
import tkinter as tk
from tkinter import ttk, messagebox
from inventory_warehouse import read_bag
from toolbox_identity import require_identity, identity_busy, lock_controls

ROUTE = 'scene.playerHandler.rewardGiftByFree'
TYPE12_REWARDS = {
    '花好月圆': '51225', '童梦奇缘礼包': '51120', '气清景明礼包': '51110',
    '暑期加油包': '51199', '福满迎春礼包': '51210', '瑞雪丰年礼包': '51210',
    '相遇十年礼包': '52180', '相遇十一年礼包': '52242',
}


def type12_items(gift, rewards):
    if str(gift.get('onlyRecord')) != '1': return None
    name = re.sub(r'^\d{2,4}年?', '', str(gift.get('name', '')))
    reward_id = TYPE12_REWARDS.get(name)
    if reward_id is None or str(gift.get('rewardId')) != reward_id:
        return None
    row = (rewards or {}).get(reward_id)
    if not isinstance(row, dict): return None
    # 已核实页面均只发物品；若新配置变为装备或货币奖励，停止自动套用旧规则。
    for key in ('spirit', 'exp', 'pointTicket', 'jjcMoney', 'petjjcMoney', 'progress', 'returnScore', 'fishProgress', 'baoQuan'):
        if str(row.get(key, '0')) not in ('0', '-1'): return None
    for key in ('equipId', 'featherId', 'fashionId', 'magicweaponId', 'soulBeadId'):
        if str(row.get(key, '-1')) not in ('-1', '0'): return None
    ids, counts = str(row.get('itemId', '')).split(';'), str(row.get('num', '')).split(';')
    if len(ids) != len(counts): return None
    result = Counter()
    try:
        for item_id, count in zip(ids, counts):
            if int(item_id) <= 0 or int(count) <= 0: return None
            result[int(item_id)] += int(count)
    except (TypeError, ValueError): return None
    return dict(result) or None


def activity_state(gift, now=None):
    from super_gift import _now, _parse_time
    now = now or _now()
    start, end = _parse_time(gift.get('shelfTime')), _parse_time(gift.get('underTime'))
    if start is None or end is None: return '日期待核实'
    if now < start: return '尚未开始'
    if now > end: return '已过期'
    if str((now.weekday()+1) % 7) not in str(gift.get('week', '')).split(';'): return '非开放星期'
    return '可尝试领取'


def eligible_gifts(rows, now=None, rewards=None, include_expired=False):
    from super_gift import _now, _parse_time, _int
    now = now or _now()
    gifts = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get('type')) not in ('6', '12'):
            continue
        start, end = _parse_time(row.get('shelfTime')), _parse_time(row.get('underTime'))
        if start is None or end is None:
            continue
        if _int(row.get('isNeedCode')) not in (-1, 0):
            continue
        if not include_expired and activity_state(row, now) != '可尝试领取':
            continue
        if _int(row.get('id')) <= 0:
            continue
        if _int(row.get('receiveNum'), 0) != 1:
            continue  # 多次领取类型的计数语义尚未核实
        expected = ({_int(row.get('propId')): 1} if str(row.get('type')) == '6'
                    and _int(row.get('propId')) > 0 else type12_items(row, rewards)
                    if str(row.get('type')) == '12' else None)
        if not expected: continue
        gifts.append({**row, '_expected_items': expected, '_state': activity_state(row, now)})
    return sorted(gifts, key=lambda r: (r['underTime'], int(r['id'])))


def points(scene):
    result = {key: (scene.get('user') or {}).get(key) for key in ('gem', 'usedGem')}
    if any(value is None for value in result.values()):
        raise RuntimeError('缺少点券余额，未执行领取')
    return result


def bag(scene):
    return read_bag((scene.get('curRecord') or {}).get('itemsBag'))


def claim_once(flow, scene, gift, now=None, rewards=None):
    eligible = eligible_gifts([gift], now, rewards)
    if not eligible:
        raise RuntimeError('所选礼包不在已核实的免费领取范围或已经过期，请刷新配置')
    gift = eligible[0]
    active_id, kind = int(gift['id']), int(gift['type'])
    expected = gift['_expected_items']
    record = scene.get('curRecord') or {}
    flags = record.get('activeList')
    record_key = str(record.get('_id') or '') + '_' + str(active_id)
    if kind == 12 and not record.get('_id'):
        raise RuntimeError('缺少存档ID，无法确认类型12领取记录')
    mark = record_key if kind == 12 else str(active_id)
    if isinstance(flags, dict) and str(flags.get(mark, flags.get(active_id) if kind == 6 else None)) == '1':
        raise RuntimeError('当前存档已有领取标记，未重复领取')
    before = bag(scene)
    required_slots = len(expected)  # 不假定已有堆叠一定还能容纳奖励
    if before['capacity'] is None or before['capacity'] - before['used'] < required_slots:
        raise RuntimeError('请先腾出至少%d个道具背包空格' % required_slots)
    baseline = points(scene)
    body = {'activeId': active_id}
    if kind == 6: body.update(type=6, pNum=1, cdkey='')
    reply = flow.request(ROUTE, body, timeout=20)
    if not isinstance(reply, dict) or reply.get('code') != 200:
        raise RuntimeError('领取未成功：%s；未自动重试' % (reply.get('error', reply.get('code')) if isinstance(reply, dict) else reply))
    # 旧协议将合法领奖数据JSON放在error字段中，普通错误文本仍需拒绝。
    payload = reply
    if reply.get('error'):
        try:
            payload = json.loads(reply['error'])
        except (TypeError, ValueError):
            raise RuntimeError('领取被拒绝：%s；未自动重试' % reply['error'])
        if not isinstance(payload, dict) or str(payload.get('activeId')) not in (str(active_id), record_key) or not isinstance(payload.get('items'), list):
            raise RuntimeError('领奖JSON结构不符，结果待核实；未自动重试')
    if kind == 12:
        if not isinstance(payload.get('items'), list):
            raise RuntimeError('类型12回包缺少奖励物品，结果待核实；未自动重试')
        received = Counter()
        try:
            for row in payload['items']: received[int(row['id'])] += int(row['count'])
        except (TypeError, ValueError, KeyError):
            raise RuntimeError('类型12奖励结构不符，结果待核实；未自动重试')
        if dict(received) != expected:
            raise RuntimeError('类型12奖励与官方奖励表不符，结果待核实；未自动重试')
    if kind == 6 and payload.get('propId') is not None and str(payload['propId']) != str(gift['propId']):
        raise RuntimeError('领奖道具ID与配置不符，结果待核实；未自动重试')
    result = {'id': active_id, 'type': kind, 'expected_items': expected,
              'before_counts': {i: before['counts'].get(i, 0) for i in expected}, 'points': baseline}
    if kind == 6: result.update(prop_id=int(gift['propId']), before_count=before['counts'].get(int(gift['propId']), 0))
    return result


def verify_claim(before, scene):
    if points(scene) != before['points']:
        raise RuntimeError('重登后点券或累计消费变化，请核实')
    counts = bag(scene)['counts']
    gained = {}
    for item_id, expected in before['expected_items'].items():
        delta = counts.get(item_id, 0) - before['before_counts'][item_id]
        if delta != expected:
            raise RuntimeError('重登后道具%s增加%d，预期%d；领取结果待核实，不自动补领' % (item_id, delta, expected))
        gained[item_id] = delta
    return 1 if before['type'] == 6 else gained


def build_panel(app, parent, shared, set_shared_busy, refresh):
    panel = ttk.LabelFrame(parent, text='免费节日礼包', padding=8)
    panel.pack(fill='both', expand=True, pady=(12, 0))
    ttk.Label(panel, text='类型6领取礼包道具；类型12仅领取已核实的免费奖励，不购买同页商品。实际领取资格由服务器确认。',
              wraplength=880).pack(anchor='w')
    status = ttk.Label(panel, text='尚未读取免费礼包配置', wraplength=880)
    status.pack(anchor='w', pady=4)
    tabs = ttk.Notebook(panel)
    tabs.pack(fill='both', expand=True)
    trees = {}
    for kind, title in (('6', '类型6 · 普通免费礼包'), ('12', '类型12 · 活动免费奖励')):
        page = ttk.Frame(tabs); tabs.add(page, text=title)
        tree = ttk.Treeview(page, columns=('name', 'state', 'end', 'reward', 'id'), show='headings', height=3, selectmode='browse')
        for key, heading, width in (('name', '礼包', 180), ('state', '状态', 100), ('end', '截止时间', 155), ('reward', '免费奖励', 260), ('id', '活动ID', 85)):
            tree.heading(key, text=heading); tree.column(key, width=width)
        scroll = ttk.Scrollbar(page, orient='horizontal', command=tree.xview)
        tree.config(xscrollcommand=scroll.set)
        tree.pack(fill='both', expand=True); scroll.pack(fill='x')
        trees[kind] = tree
    controls = ttk.Frame(panel); controls.pack(anchor='w', pady=5)
    current = {'rows': [], 'claimed': set(), 'cache': {}}
    show_expired = tk.BooleanVar(value=False)
    button = ttk.Button(controls, text='领取选中免费礼包', state='disabled')
    button.pack(side='left')
    ttk.Button(controls, text='刷新配置', command=refresh).pack(side='left', padx=8)
    ttk.Checkbutton(controls, text='显示已过期／未开放', variable=show_expired, command=lambda: render()).pack(side='left', padx=8)

    def selected_gift():
        index = tabs.index(tabs.select())
        if index >= 2: return None
        kind = ('6', '12')[index]
        selected = trees[kind].selection()
        if not selected: return None
        return next((row for row in current['rows'] if str(row['type']) == kind and str(row['id']) == selected[0]), None)

    def selection_changed(*_):
        if tabs.index(tabs.select()) >= 2:
            controls.pack_forget()
        elif not controls.winfo_manager():
            controls.pack(anchor='w', pady=5)
        gift = selected_gift()
        enabled = bool(gift and gift['_state'] == '可尝试领取' and str(gift['id']) not in current['claimed'] and not shared['busy'])
        button.config(state='normal' if enabled else 'disabled')

    def update(cache):
        current['claimed'].clear()
        current['cache'] = cache
        render()
        update_argot(cache)

    def render():
        cache = current['cache']
        current['rows'] = eligible_gifts(cache.get('freeActivities') or [], rewards=cache.get('freeRewards'), include_expired=show_expired.get())
        for tree in trees.values():
            for key in tree.get_children(): tree.delete(key)
        for gift in current['rows']:
            reward = '；'.join('%s×%s' % (i, n) for i, n in gift['_expected_items'].items())
            trees[str(gift['type'])].insert('', 'end', iid=str(gift['id']), values=(gift['name'], gift['_state'], gift['underTime'], reward, gift['id']))
        version = cache.get('freeVersion', cache.get('version', '?'))
        status.config(text='配置%s：类型6显示%d项，类型12显示%d项；已过期条目不能领取。' % (version, sum(str(r['type'])=='6' for r in current['rows']), sum(str(r['type'])=='12' for r in current['rows'])))
        selection_changed()

    def claim():
        if shared['busy'] or identity_busy(app) or not app._ensure_login(): return
        gift = selected_gift()
        if gift is None or gift['_state'] != '可尝试领取' or str(gift['id']) in current['claimed']: return
        client, slot = app.client, app.current_save['index']
        require_identity(app, client, slot)
        set_shared_busy(True)
        button.config(state='disabled'); lock_controls(app, True)
        status.config(text='正在领取%s并核对背包…' % gift['name'])

        def worker():
            flow = None
            ok = False
            try:
                require_identity(app, client, slot)
                flow, _, scene = app._connect_and_enter(slot)
                require_identity(app, client, slot)
                result = claim_once(flow, scene, gift, rewards=current['cache'].get('freeRewards'))
                flow.disconnect(); flow = None
                require_identity(app, client, slot)
                flow, _, scene = app._connect_and_enter(slot)
                verify_claim(result, scene)
                ok = True
                reward_text = '；'.join('%s×%s' % (i, n) for i, n in result['expected_items'].items())
                text = '类型%s %s领取成功：%s，重登核验通过，点券未变。' % (gift['type'], gift['name'], reward_text)
            except Exception as error:
                text = '%s已停止：%s' % (gift['name'], error)
            finally:
                if flow:
                    try: flow.disconnect()
                    except Exception: pass
                app._log('[免费礼包] ' + text)
                def done():
                    # 本次尝试后禁用该项，刷新配置才可重新选取；不自动重发。
                    current['claimed'].add(str(gift['id']))
                    set_shared_busy(False); lock_controls(app, False)
                    status.config(text=text)
                    selection_changed()
                    if not ok: messagebox.showwarning('免费礼包', text)
                app.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

    button.config(command=claim)
    for tree in trees.values(): tree.bind('<<TreeviewSelect>>', selection_changed)
    tabs.bind('<<NotebookTabChanged>>', selection_changed)
    from argot_gifts import build_tab as build_argot_tab
    update_argot = build_argot_tab(app, tabs, shared, set_shared_busy, refresh)
    return update
