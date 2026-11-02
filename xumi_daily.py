"""须弥山三路每日免费挑战，沿用七音实测的羽毛拾取流程。"""
import threading
from tkinter import ttk

ROUTES = (('城东·四象祖巫', (2054,), 10),
          ('城南·五行祖巫', (2034,), 11),
          ('城北·三才祖巫', (2067, 2080), 2))


def _entries(bag):
    rows = (bag or {}).get('items') or []
    return list(rows.values()) if isinstance(rows, dict) else rows


def _feathers(scene):
    return {str(row.get('entityId', row.get('id'))): row
            for row in _entries(scene['curRecord'].get('featherBag'))}


def _items(scene):
    return {str(row['id']): int(row.get('count', 1))
            for row in _entries(scene['curRecord'].get('itemsBag'))}


def _used(scene, mid):
    history = scene.get('curRecord', {}).get('copyHistory')
    if not isinstance(history, list):
        raise RuntimeError('未读到今日挑战次数，已停止')
    return next((int(row.get('num', 0)) for row in history
                 if int(row.get('id', 0)) == mid), 0)


def build_panel(app, parent):
    notebook = ttk.Notebook(parent)
    notebook.pack(fill='both', expand=True)
    buttons = []
    busy = False

    for title, stages, space in ROUTES:
        page = ttk.Frame(notebook, padding=12)
        notebook.add(page, text=title)
        ttk.Label(page, text=title, font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=5)
        ttk.Label(page, text='关卡：' + ' → '.join(map(str, stages))).pack(anchor='w', pady=5)
        status = ttk.Label(page, text='登录后刷新今日次数', wraplength=700)
        status.pack(anchor='w', pady=8)
        def refresh_counts(scene, status=status, mid=stages[0]):
            if scene is None:
                status.config(text='已切换存档，正在读取今日次数…')
            else:
                try:
                    used = _used(scene, mid)
                    status.config(text='今日已用%d/1次；剩余免费次数%d' % (used, max(0, 1-used)))
                except Exception:
                    status.config(text='次数读取失败，请刷新')
        if not hasattr(app, '_count_state_listeners'):
            app._count_state_listeners = []
        app._count_state_listeners.append(refresh_counts)

        actions = ttk.Frame(page)
        actions.pack(anchor='w', pady=5)
        ttk.Label(page, text='每天免费一次；拾取普通道具和羽毛，结束后重登核对羽毛背包。\n'
                  '不购买次数、不花点券。全局补给过滤开启时不拾取桃子、萝卜、蓝瓶、蓝壶。',
                  wraplength=700).pack(anchor='w', pady=8)

        def start(run, title=title, stages=stages, space=space, status=status):
            nonlocal busy
            if busy or not app._ensure_login():
                return
            slot = app.current_save['index']
            busy = True
            for button in buttons:
                button.config(state='disabled')
            status.config(text='正在连接槽%s…' % slot)

            def worker():
                nonlocal busy
                flow = None
                text = ''
                try:
                    from mainfarm_routes import clear_stage
                    flow, _, before = app._connect_and_enter(slot)
                    if before.get('code') != 200 or not before.get('curRecord'):
                        raise RuntimeError(before.get('error', '进入存档失败'))
                    used = _used(before, stages[0])
                    text = '今日已用%d/1次；剩余免费次数%d' % (used, max(0, 1-used))
                    if run:
                        if used >= 1:
                            raise RuntimeError('今日免费次数已用完')
                        for bag_name, minimum in (('featherBag', space), ('itemsBag', 6)):
                            bag = before['curRecord'].get(bag_name) or {}
                            free = int(bag.get('itemCount', 0)) - len(_entries(bag))
                            if free < minimum:
                                raise RuntimeError('%s空格不足，至少需要%d个空格' %
                                                   ('羽毛背包' if bag_name == 'featherBag' else '道具背包', minimum))
                        old_feathers, old_items = _feathers(before), _items(before)
                        points = {key: before['user'].get(key) for key in ('gem', 'usedGem')}
                        expected = 0
                        scene = before
                        for mid in stages:
                            app._log('[%s] 槽%s进入关卡%s，costGem=0' % (title, slot, mid))
                            result = clear_stage(flow, scene, mid, enter_w=len(stages) > 1,
                                                 pick_equips=True)
                            expected += sum(result.get('featherCounts', {}).values())
                            app._log('[%s] 关卡%s结算成功；羽毛分配%s，普通道具%s' %
                                     (title, mid, result.get('featherCounts', {}), result['counts']))
                        flow.disconnect()
                        flow = None
                        flow, _, after = app._connect_and_enter(slot)
                        if any(points[key] != after['user'].get(key) for key in points):
                            raise RuntimeError('点券或累计消费发生变化，请核查')
                        added = {key: value for key, value in _feathers(after).items()
                                 if key not in old_feathers}
                        final_items = _items(after)
                        delta = {key: value-old_items.get(key, 0) for key, value in final_items.items()
                                 if value != old_items.get(key, 0)}
                        app._log('[%s] 重登新增羽毛%d件，分配%d件；道具变化%s' %
                                 (title, len(added), expected, delta))
                        if len(added) != expected:
                            raise RuntimeError('羽毛背包新增数量与分配数量不一致，请查看日志')
                        text = '完成：重登确认羽毛新增%d件，点券未变；剩余免费次数%d' % (
                            len(added), max(0, 1-_used(after, stages[0])))
                    app._log('[%s] %s' % (title, text))
                except Exception as error:
                    text = '已停止：' + str(error)
                    app._log('[%s] %s' % (title, text))
                finally:
                    if flow:
                        flow.disconnect()
                    def finish():
                        nonlocal busy
                        busy = False
                        status.config(text=text)
                        for button in buttons:
                            button.config(state='normal')
                    app.root.after(0, finish)
            threading.Thread(target=worker, daemon=True).start()

        for text, run in (('刷新今日次数', False), ('免费挑战并拾取一次', True)):
            button = ttk.Button(actions, text=text, command=lambda run=run, start=start: start(run))
            button.pack(side='left', padx=5)
            buttons.append(button)
