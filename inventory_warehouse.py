"""道具背包/仓库管理，沿用原客户端的单项存取和同类合并参数。"""
import threading
import json
from pathlib import Path
from decimal import Decimal, ROUND_CEILING
from types import SimpleNamespace

from league_garden import prop_config


# Exact IDs: never include similarly named consumables or material gift packs.
WUDU_TIERS = (
    ((110000001, '蟾衣'), (110000002, '蛛壳'), (110000003, '蜈蚣皮'), (110000004, '蛇鳞'), (110000005, '蝎壳')),
    ((110000006, '蟾酥'), (110000007, '蛛腺'), (110000008, '蜈蚣腺'), (110000009, '蛇毒'), (110000010, '蝎毒')),
    ((110000011, '蟾舌'), (110000012, '蛛齿'), (110000014, '蜈蚣角'), (110000013, '蛇皮'), (110000015, '蝎钳')),
    ((110000016, '蟾肝'), (110000017, '蛛螯'), (110000019, '蜈蚣刺'), (110000018, '蛇牙'), (110000020, '蝎尾')),
    ((110000021, '蟾胆'), (110000022, '蛛爪'), (110000025, '蜈蚣头'), (110000023, '蛇胆'), (110000024, '蝎腹')),
)
WUDU_NAMES = dict(pair for tier in WUDU_TIERS for pair in tier)


def wudu_sale_estimate(plan, config):
    """Match Unify.sellPrice: ceil(Common.sellDiscount * price * count)."""
    discount = None
    root = Path(__file__).resolve().parent
    for folder in ('output_cg1_20260921_1_2', 'config_review_20261012_2/decoded'):
        for path in (root / folder).glob('*___Common.xml.json'):
            rows = json.loads(path.read_text(encoding='utf-8-sig'))['RECORD']
            for row in rows if isinstance(rows, list) else [rows]:
                if 'sellDiscount' in row:
                    discount = Decimal(str(row['sellDiscount']))
    if discount is None or not 0 <= discount <= 1:
        raise RuntimeError('缺少有效售出折扣配置，请停止并核对配置')
    return sum(int((Decimal(str(config[key]['price'])) * count * discount)
                   .to_integral_value(rounding=ROUND_CEILING)) for key, count in plan.items())


def wudu_sale_plan(snapshot, config):
    plan = {}
    for key, name in WUDU_NAMES.items():
        row = config.get(key, {})
        if row.get('name') != name or str(row.get('isSell')) != '1':
            raise RuntimeError('五毒材料配置不匹配：%s，停止售出' % key)
        count = snapshot['backpack']['counts'].get(key, 0)
        if count > 0:
            plan[key] = count
    return plan


def verify_wudu_sale(before, after, item_id):
    if item_id not in WUDU_NAMES:
        raise RuntimeError('不在五毒材料白名单')
    expected = dict(before['backpack']['counts'])
    expected.pop(item_id, None)
    if after['backpack']['counts'] != expected:
        raise RuntimeError('售出后背包数量不符合预期，请刷新核对')
    if before['warehouse']['counts'] != after['warehouse']['counts']:
        raise RuntimeError('仓库数量变化，请核对')
    for key in ('gem', 'usedGem'):
        if before['points'].get(key) != after['points'].get(key):
            raise RuntimeError('点券数据变化，已停止')


def checked(flow, route, payload):
    reply = flow.request(route, payload, timeout=20)
    if reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError(str(reply.get('error') or '请求失败：' + route))
    return reply


def read_bag(value):
    if not isinstance(value, dict):
        raise RuntimeError('未收到预期的背包/仓库数据')
    rows = value.get('items') or []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise RuntimeError('未知物品列表格式')
    counts = {}
    used = 0
    for row in rows:
        if not isinstance(row, dict) or 'id' not in row:
            raise RuntimeError('物品数据缺少ID')
        key = int(row['id'])
        count = int(row.get('count', 1))
        if count <= 0:
            continue
        used += 1
        counts[key] = counts.get(key, 0) + count
    capacity = value.get('itemCount')
    return dict(counts=counts, used=used, capacity=int(capacity) if capacity is not None else None)


def inspect_inventory(flow, scene):
    reply = checked(flow, 'scene.playerSecondHandler.getWareHouseInfo', {})
    return dict(backpack=read_bag((scene.get('curRecord') or {}).get('itemsBag')),
                warehouse=read_bag(reply.get('itemWareHouse')),
                points={key: (scene.get('user') or {}).get(key) for key in ('gem', 'usedGem')})


def category(item_id, config):
    value = str(config.get(item_id, {}).get('propType', ''))
    return {'2': '木', '3': '矿', '4': '布'}.get(value, '其他')


def source_and_target(snapshot, direction):
    if direction not in (1, 2):
        raise RuntimeError('未知存取方向')
    names = ('backpack', 'warehouse') if direction == 1 else ('warehouse', 'backpack')
    return snapshot[names[0]], snapshot[names[1]]


def transfer(flow, snapshot, direction, item_id):
    source, target = source_and_target(snapshot, direction)
    if source['counts'].get(item_id, 0) <= 0:
        raise RuntimeError('来源中已没有所选道具，请刷新')
    if item_id not in target['counts'] and target['capacity'] is not None and target['used'] >= target['capacity']:
        raise RuntimeError('目标没有空格，请先整理')
    return checked(flow, 'scene.playerSecondHandler.operateWareHourse',
                   {'operateType': direction, 'itemId': item_id, 'type': 1})


def merge_same(flow, snapshot, direction):
    source, target = source_and_target(snapshot, direction)
    if not set(source['counts']).intersection(target['counts']):
        raise RuntimeError('背包和仓库没有相同道具可合并')
    return checked(flow, 'scene.playerSecondHandler.operateAllWareHourse', {'operateType': direction})


def verify_transfer(before, after, direction, expected_ids):
    source_before, target_before = source_and_target(before, direction)
    source_after, target_after = source_and_target(after, direction)
    moved = {}
    for key in expected_ids:
        removed = source_before['counts'].get(key, 0) - source_after['counts'].get(key, 0)
        added = target_after['counts'].get(key, 0) - target_before['counts'].get(key, 0)
        if removed < 0 or removed != added:
            raise RuntimeError('道具%s两侧数量变化不一致，请核对' % key)
        if removed:
            moved[key] = removed
    for key in ('gem', 'usedGem'):
        old, new = before['points'].get(key), after['points'].get(key)
        if old is not None and new is not None and old != new:
            raise RuntimeError('点券数据变化，已停止，请查看日志')
    return moved


def build_panel(app, parent):
    import tkinter as tk
    from tkinter import messagebox, ttk
    ttk.Label(parent, text='道具背包 / 仓库', font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=5)
    ttk.Label(parent, text='单项存取沿用游戏原始请求，实际转移数量由服务器决定。'
              '同类合并处理两边全部相同道具，不受搜索和分类筛选影响。', wraplength=850).pack(anchor='w', pady=5)
    filters = ttk.Frame(parent)
    filters.pack(fill='x', pady=5)
    ttk.Label(filters, text='名称/ID：').pack(side='left')
    query = tk.StringVar()
    ttk.Entry(filters, textvariable=query, width=26).pack(side='left', padx=4)
    kind = tk.StringVar(value='全部')
    ttk.Combobox(filters, textvariable=kind, values=('全部', '木', '布', '矿', '木布矿', '其他'),
                 state='readonly', width=10).pack(side='left', padx=4)
    status = tk.StringVar(value='先登录、选择存档，再刷新。当前为道具背包，不包含装备、羽毛等独立背包。')
    ttk.Label(parent, textvariable=status, wraplength=850).pack(anchor='w', pady=5)
    state = {'snapshot': None, 'identity': None, 'busy': False, 'config': {}}
    tables = {}
    panels = ttk.Frame(parent)
    panels.pack(fill='both', expand=True)
    panels.rowconfigure(0, weight=1)
    for column, (side, title) in enumerate((('backpack', '背包'), ('warehouse', '仓库'))):
        panels.columnconfigure(column, weight=1)
        box = ttk.LabelFrame(panels, text=title, padding=5)
        box.grid(row=0, column=column, sticky='nsew', padx=3)
        capacity = tk.StringVar(value='未读取')
        ttk.Label(box, textvariable=capacity).pack(anchor='w')
        area = ttk.Frame(box)
        area.pack(fill='both', expand=True)
        area.rowconfigure(0, weight=1)
        area.columnconfigure(0, weight=1)
        tree = ttk.Treeview(area, columns=('name', 'id', 'count', 'other', 'kind'), show='headings',
                            selectmode='browse', height=14)
        for field, heading, width in (('name', '物品', 165), ('id', 'ID', 100), ('count', '本侧数量', 80),
                                      ('other', '另一侧数量', 90), ('kind', '分类', 55)):
            tree.heading(field, text=heading)
            tree.column(field, width=width, stretch=field == 'name')
        vertical = ttk.Scrollbar(area, orient='vertical', command=tree.yview)
        horizontal = ttk.Scrollbar(area, orient='horizontal', command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        tree.grid(row=0, column=0, sticky='nsew')
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        tables[side] = (tree, capacity)
    actions = ttk.Frame(parent)
    actions.pack(anchor='w', pady=8)
    buttons = []
    ttk.Label(parent, text='单项存取、双向同类合并已有实测记录；五毒一键售出仅处理背包内1—5阶25种材料，整组售出，不受搜索筛选影响。'
              '若服务器要求二级密码，停止并显示原始业务提示，不绕过验证。',
              foreground='gray', wraplength=850).pack(anchor='w', pady=4)

    def identity_now():
        return (str(app.client.uid), app.current_save['index']) if app.client and app.current_save else None

    def render(*unused):
        snapshot = state['snapshot']
        if not snapshot:
            return
        needle = query.get().strip().casefold()
        selected_kind = kind.get()
        for side, (tree, capacity) in tables.items():
            selected = tree.selection()
            tree.delete(*tree.get_children())
            bag = snapshot[side]
            other = snapshot['warehouse' if side == 'backpack' else 'backpack']['counts']
            cap = bag['capacity']
            capacity.set('已用格子：%d / %s　空余：%s　道具种类：%d' %
                         (bag['used'], cap if cap is not None else '未知',
                          max(0, cap - bag['used']) if cap is not None else '未知', len(bag['counts'])))
            for key, count in sorted(bag['counts'].items()):
                name = state['config'].get(key, {}).get('name', '未识别道具')
                label = category(key, state['config'])
                if needle and needle not in name.casefold() and needle not in str(key):
                    continue
                if selected_kind != '全部' and not (label in ('木', '布', '矿') if selected_kind == '木布矿' else label == selected_kind):
                    continue
                tree.insert('', 'end', iid=str(key), values=(name, key, count, other.get(key, 0), label))
            if selected and tree.exists(selected[0]):
                tree.selection_set(selected[0])
    query.trace_add('write', render)
    kind.trace_add('write', render)

    def start(action, direction=1):
        if state['busy'] or not app._ensure_login():
            return
        identity = identity_now()
        client = app.client
        slot = identity[1]
        item_id = None
        expected = {}
        if action != 'inspect':
            if state['identity'] != identity or not state['snapshot']:
                status.set('请先刷新当前账号存档的背包和仓库')
                return
            source, target = source_and_target(state['snapshot'], direction)
            if action == 'sell_wudu':
                try:
                    sale_plan = wudu_sale_plan(state['snapshot'], state['config'])
                except RuntimeError as error:
                    status.set(str(error))
                    return
                if not sale_plan:
                    status.set('背包没有可售出的五毒1—5阶材料')
                    return
                preview = '\n'.join('%s × %d' % (WUDU_NAMES[key], count) for key, count in sale_plan.items())
                try:
                    estimate = wudu_sale_estimate(sale_plan, state['config'])
                except (RuntimeError, ValueError, KeyError) as error:
                    status.set(str(error))
                    return
                if not messagebox.askokcancel('售出五毒材料',
                    '将整组售出以下背包材料（不含仓库）：\n%s\n共%d种、%d件，配置估算%d灵魂。\n售出无法撤回，确认执行？' %
                    (preview, len(sale_plan), sum(sale_plan.values()), estimate), parent=parent):
                    return
                ids = set(sale_plan)
            elif action == 'transfer':
                selection = tables['backpack' if direction == 1 else 'warehouse'][0].selection()
                if not selection:
                    status.set('请先在来源一侧选择一个道具')
                    return
                item_id = int(selection[0])
                ids = {item_id}
            else:
                ids = set(source['counts']).intersection(target['counts'])
                if not ids:
                    status.set('没有相同道具可以合并')
                    return
                preview = '\n'.join('%s：来源%d，目标%d' %
                                    (state['config'].get(key, {}).get('name', str(key)),
                                     source['counts'][key], target['counts'][key]) for key in sorted(ids)[:12])
                if not messagebox.askokcancel('合并全部同类道具',
                    '方向：%s\n共%d种相同道具，包含筛选范围外的物品。\n%s\n\n实际数量由服务器决定，是否执行？' %
                    ('背包 → 仓库' if direction == 1 else '仓库 → 背包', len(ids), preview), parent=parent):
                    return
            expected = {key: (source['counts'].get(key, 0), target['counts'].get(key, 0)) for key in ids}
        state['busy'] = True
        for button in buttons:
            button.configure(state='disabled')
        status.set('正在读取背包及仓库…')

        def worker():
            flow = None
            snapshot = None
            config = None
            message = ''
            attempted = False
            invalidate = False
            # Freeze the login client for this operation, even if the UI switches account.
            owner = SimpleNamespace(client=client, current_save={'index': slot})

            def reconnect():
                nonlocal flow
                if flow:
                    flow.disconnect()
                    flow = None
                flow, _, scene = type(app)._connect_and_enter(owner, slot)
                if scene.get('code') != 200:
                    raise RuntimeError('进入存档失败')
                return inspect_inventory(flow, scene)

            try:
                config = prop_config()
                snapshot = reconnect()
                if action == 'sell_wudu':
                    if identity_now() != identity:
                        raise RuntimeError('账号或存档已切换，未售出')
                    if wudu_sale_plan(snapshot, config) != sale_plan:
                        raise RuntimeError('五毒材料数量已变化，请重新确认')
                    sold = []
                    for key in sale_plan:
                        if identity_now() != identity:
                            raise RuntimeError('账号或存档已切换，停止后续售出')
                        before = snapshot
                        attempted = True
                        checked(flow, 'scene.playerHandler.sellItem', {'itemId': key, 'bagType': 1})
                        snapshot = None
                        snapshot = reconnect()
                        verify_wudu_sale(before, snapshot, key)
                        sold.append(key)
                        app._log('[五毒材料售出] 重登核对：%s ×%d 已售出' % (WUDU_NAMES[key], sale_plan[key]))
                    message = '五毒材料售出完成：%d种、%d件，已逐项重登核对。' % (len(sold), sum(sale_plan.values()))
                elif action != 'inspect':
                    if identity_now() != identity:
                        raise RuntimeError('账号或存档已切换，未执行存取')
                    source, target = source_and_target(snapshot, direction)
                    if any((source['counts'].get(key, 0), target['counts'].get(key, 0)) != counts
                           for key, counts in expected.items()):
                        raise RuntimeError('物品数量已变化，列表已刷新，请重新选择')
                    ids = set(expected)
                    if action == 'merge' and ids != set(source['counts']).intersection(target['counts']):
                        raise RuntimeError('同类道具集合已变化，列表已刷新，请重新确认')
                    before = snapshot
                    attempted = True
                    if action == 'transfer':
                        transfer(flow, before, direction, item_id)
                    else:
                        merge_same(flow, before, direction)
                    snapshot = None
                    snapshot = reconnect()
                    moved = verify_transfer(before, snapshot, direction, ids)
                    if not moved:
                        message = '请求已返回，重登未发现道具转移；未自动重试。'
                    else:
                        text = '；'.join('%s ×%d' % (config.get(key, {}).get('name', key), count)
                                        for key, count in sorted(moved.items()))
                        message = '重登核对完成：%s，%s' % ('存入仓库' if direction == 1 else '取出到背包', text)
                else:
                    message = '槽%s背包与仓库已读取，显示当前服务器返回数据。' % slot
            except Exception as error:
                message = '停止：' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__)
                if attempted:
                    invalidate = True
                    message += '；未自动重试，请先刷新核对实际结果。'
            finally:
                if flow:
                    try:
                        flow.disconnect()
                    except Exception:
                        pass
                app._log('[背包/仓库] ' + message)
                def finish():
                    state['busy'] = False
                    for button in buttons:
                        button.configure(state='normal')
                    if identity_now() != identity:
                        state.update(snapshot=None, identity=None)
                        for tree, capacity in tables.values():
                            tree.delete(*tree.get_children())
                            capacity.set('未读取当前账号存档')
                        status.set('账号或存档已切换，请重新刷新')
                        return
                    if snapshot is not None and config is not None:
                        state.update(snapshot=snapshot, config=config, identity=None if invalidate else identity)
                        render()
                    elif invalidate:
                        state['identity'] = None
                    status.set(message)
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for title, action, direction in (('刷新背包/仓库', 'inspect', 1), ('所选存入 →', 'transfer', 1),
                                      ('← 所选取出', 'transfer', 2), ('全部同类合并至仓库', 'merge', 1),
                                      ('全部同类合并至背包', 'merge', 2), ('五毒材料一键售出', 'sell_wudu', 1)):
        button = ttk.Button(actions, text=title, command=lambda a=action, d=direction: start(a, d))
        button.pack(side='left', padx=(0, 6))
        buttons.append(button)
