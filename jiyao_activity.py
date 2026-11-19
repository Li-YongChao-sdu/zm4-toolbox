"""缉妖令：普通/噩梦共享免费次数，默认四种奖励筛选。"""
import threading
import tkinter as tk
from tkinter import ttk

MODES = {"普通": 2156, "噩梦": 2157}
TITLE = "缉妖令"


def run(app, mid, filter_rewards=True, expected_client=None, expected_slot=None):
    from mainfarm_routes import clear_stage, dungeon_rows
    from inventory_warehouse import read_bag
    if mid not in MODES.values():
        raise RuntimeError("缉妖令难度无效，请重新选择")
    if app._limited_config_expired(TITLE):
        raise RuntimeError("缉妖令活动已过期")
    if expected_client is None:
        expected_client = app.client
    if expected_slot is None:
        expected_slot = app.current_save['index']

    def check_identity():
        if app.client is not expected_client or (app.current_save or {}).get('index') != expected_slot:
            raise RuntimeError("账号或存档已切换，停止缉妖令挑战")
        if app._limited_config_expired(TITLE):
            raise RuntimeError("缉妖令活动已过期")

    check_identity()
    row = dungeon_rows().get(mid) or {}
    if row.get('classType') != 'Zhudongfuyao' or str(row.get('consumePointTicket')) != '0':
        raise RuntimeError("缉妖令配置缺失或需要点券，已停止")
    limit = int(row.get('dailyCountMax') or 0)
    if limit != 1:
        raise RuntimeError("缉妖令每日次数配置发生变化，请先核对")
    flow = None
    try:
        flow, _, scene = app._connect_and_enter(expected_slot, expected_client=expected_client)
        check_identity()
        used = sum(int(r.get('num', 0)) for r in scene['curRecord'].get('copyHistory', [])
                   if int(r.get('id', 0)) in MODES.values())
        if used >= limit:
            app._log('[缉妖令] 今日共享免费次数已用完，跳过；不购买额外次数')
            return {'runs': 0, 'reason': 'free_times_exhausted'}
        bag = read_bag(scene['curRecord'].get('itemsBag'))
        # 未筛选时会提交大量场内补给，采用比筛选模式更高的空间预留。
        required = 5 if filter_rewards else 70
        if bag['capacity'] is None or bag['capacity'] - bag['used'] < required:
            raise RuntimeError('道具背包不足%d个空格，未开图，请先清理或开启奖励筛选' % required)

        class BoundFlow:
            def request(self, route, data, **options):
                check_identity()
                if route == 'scene.copyHandler.createSinglePlayerCopy':
                    if not isinstance(data, dict) or data.get('mid') != mid or data.get('costGem') != 0:
                        raise RuntimeError('禁止额外关卡或点券挑战')
                return flow.request(route, data, **options)

        mode = next(name for name, value in MODES.items() if value == mid)
        app._log('[缉妖令] 开始%s，奖励筛选%s；仅使用今日免费次数' % (
            mode, '开启' if filter_rewards else '关闭'))
        result = clear_stage(BoundFlow(), scene, mid, filter_jiyao_rewards=filter_rewards)
        app._log('[缉妖令] %s结算成功，奖励：%s' % (mode, result.get('counts') or {}))
        return {'runs': 1, **result}
    finally:
        if flow:
            flow.disconnect()


def start(app):
    if not app._ensure_login() or getattr(app, '_limited_activity_busy', False):
        return
    if app._limited_config_expired(TITLE):
        app._log('[缉妖令] 活动已过期，跳过')
        return
    mid = MODES.get(app.var_jiyao_mode.get())
    if mid is None:
        app._log('[缉妖令] 难度选项无效，请重新选择')
        return
    # 在UI线程读取设置并固定身份，一键运行与手动点击共用同一入口。
    filtered = bool(app.var_jiyao_filter.get())
    client, slot = app.client, app.current_save['index']
    app._limited_activity_busy = True
    app.btn_jiyao_run.config(state='disabled')
    app.combo_jiyao_mode.config(state='disabled')
    app.check_jiyao_filter.config(state='disabled')

    def worker():
        try:
            run(app, mid, filtered, client, slot)
        except Exception as error:
            app._log('[缉妖令] 未完成：%s' % error)
        finally:
            def done():
                app._limited_activity_busy = False
                app.btn_jiyao_run.config(state='normal')
                app.combo_jiyao_mode.config(state='readonly')
                app.check_jiyao_filter.config(state='normal')
            app.root.after(0, done)
    threading.Thread(target=worker, daemon=True).start()


def build_tab(app):
    tab = app._limited_page(TITLE, padding=12)
    ttk.Label(tab, text='普通与噩梦共享每天1次免费挑战，次数用完即跳过，不购买额外次数。',
              wraplength=850).pack(anchor='w', pady=(0, 10))
    settings = ttk.Frame(tab)
    settings.pack(anchor='w')
    ttk.Label(settings, text='难度：').pack(side='left')
    app.var_jiyao_mode = tk.StringVar(value='噩梦')
    app.combo_jiyao_mode = ttk.Combobox(settings, textvariable=app.var_jiyao_mode,
                                      values=tuple(MODES), state='readonly', width=12)
    app.combo_jiyao_mode.pack(side='left', padx=6)
    app.var_jiyao_filter = tk.BooleanVar(value=True)
    app.check_jiyao_filter = ttk.Checkbutton(tab, text='仅拾取活动展示的四种奖励',
                                            variable=app.var_jiyao_filter)
    app.check_jiyao_filter.pack(anchor='w', pady=10)
    ttk.Label(tab, text='3级宝石袋、2级宝石袋、2级强化石、中级幸运符。筛选开启时至少预留5格；\n'
                       '关闭筛选后会拾取场内补给，至少预留70格，全局过滤开关仍然生效。',
              wraplength=850, foreground='gray').pack(anchor='w')
    app.btn_jiyao_run = ttk.Button(tab, text='挑战缉妖令（免费）', command=app._do_jiyao_run)
    app.btn_jiyao_run.pack(anchor='w', pady=12)
    ttk.Label(tab, text='一键运行中的“缉妖令”沿用本页难度和筛选设置。',
              foreground='gray').pack(anchor='w')
