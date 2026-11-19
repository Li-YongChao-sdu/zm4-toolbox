"""感恩大回馈：仅领取当天免费登录奖励，不提供提前领取或特供购买。"""
import threading
from tkinter import ttk
from inventory_warehouse import read_bag

TITLE = '感恩节免费领取'
FREE_ROUTE = 'scene.playerThirdHandler.getLandingRewardOther'


def run(app, expected_client=None, expected_slot=None):
    if expected_client is None:
        expected_client = app.client
    if expected_slot is None:
        expected_slot = app.current_save['index']

    def check():
        if app.client is not expected_client or (app.current_save or {}).get('index') != expected_slot:
            raise RuntimeError('账号或存档已切换，停止领取')
        if app._limited_config_expired(TITLE):
            raise RuntimeError('感恩节活动已过期')

    def points(scene):
        user = scene.get('user') or {}
        result = {key: user.get(key) for key in ('gem', 'usedGem')}
        if any(value is None for value in result.values()):
            raise RuntimeError('未能确认点券数据，停止领取')
        return result

    flow = None
    try:
        check()
        flow, _, before = app._connect_and_enter(expected_slot, expected_client=expected_client)
        check()
        baseline = points(before)
        bag = read_bag(before['curRecord'].get('itemsBag'))
        if bag['capacity'] is None or bag['capacity'] - bag['used'] < 3:
            raise RuntimeError('道具背包不足3个空格，未发送领取请求')
        # 唯一领奖请求：客户端当天免费入口，禁止任何付费分支或失败后替代领取。
        reply = flow.request(FREE_ROUTE, {}, timeout=20)
        if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
            message = reply.get('error') if isinstance(reply, dict) else '无有效回包'
            raise RuntimeError('免费领取未成功：%s；未尝试提前领取或特供购买' % message)
        expected = {}
        for item in reply.get('items') or []:
            key, count = int(item['id']), int(item.get('count', 1))
            if count <= 0:
                raise RuntimeError('服务器返回异常奖励数量，停止后续操作')
            expected[key] = expected.get(key, 0) + count
        flow.disconnect()
        flow = None
        check()
        flow, _, after = app._connect_and_enter(expected_slot, expected_client=expected_client)
        check()
        if points(after) != baseline:
            raise RuntimeError('重登发现点券或累计消费变化，请核对日志，停止后续操作')
        after_bag = read_bag(after['curRecord'].get('itemsBag'))
        delta = {key: after_bag['counts'].get(key, 0) - bag['counts'].get(key, 0)
                 for key in expected}
        if any(delta[key] < count for key, count in expected.items()):
            raise RuntimeError('重登后奖励增量未确认，请核对背包；不自动重复领取')
        if not expected:
            raise RuntimeError('服务器未返回奖励道具，未确认领取成功；点券未变，不自动重试')
        app._log('[感恩节免费领取] 重登确认奖励入包：%s；点券及累计消费未变' % delta)
        return {'items': expected, 'deltas': delta, 'points_unchanged': True,
                'landingInfo': reply.get('landingInfo')}
    finally:
        if flow:
            flow.disconnect()


def start(app):
    if not app._ensure_login() or getattr(app, '_limited_activity_busy', False):
        return
    if app._limited_config_expired(TITLE):
        app._log('[感恩节免费领取] 活动已过期，跳过')
        return
    client, slot = app.client, app.current_save['index']
    app._limited_activity_busy = True
    app.btn_thanksgiving_free.config(state='disabled')

    def worker():
        try:
            run(app, client, slot)
        except Exception as error:
            app._log('[感恩节免费领取] 未完成：%s' % error)
        finally:
            def done():
                app._limited_activity_busy = False
                app.btn_thanksgiving_free.config(state='normal')
            app.root.after(0, done)
    threading.Thread(target=worker, daemon=True).start()


def build_tab(app):
    tab = app._limited_page(TITLE, padding=12)
    ttk.Label(tab, text='领取“感恩大回馈”当天可领取的免费登录奖励，每次点击只请求一次。\n'
                       '不提前领取，不购买点券特供感恩节礼包，不补领、不自动重试。',
              wraplength=850).pack(anchor='w', pady=10)
    app.btn_thanksgiving_free = ttk.Button(tab, text='领取今日免费奖励',
                                           command=app._do_thanksgiving_free)
    app.btn_thanksgiving_free.pack(anchor='w', pady=10)
    ttk.Label(tab, text='请预留至少3个道具背包空格；领取后重登核对奖励和点券。\n'
                       '已领、未到领取条件或服务器拒绝时停止，不切换到付费接口。',
              wraplength=850, foreground='gray').pack(anchor='w')
