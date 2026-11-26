"""福果来：固定600分，开图等待10秒，仅领取每日免费奖励。"""
import json
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tkinter import ttk

from count_states import usage
from inventory_warehouse import read_bag

TITLE = '福果来'
MID = 2166
TARGET_SCORE = 600
WAIT_SECONDS = 10.0
CONFIG_FILE = Path(__file__).with_name('fuguolai_config.json')
TIME_FORMAT = '%Y/%m/%d-%H:%M:%S'


def _version(value):
    match = re.fullmatch(r'cg1_(\d{8})_(\d+)', str(value or ''))
    return tuple(map(int, match.groups())) if match else (0, 0)


def config():
    data = json.loads(CONFIG_FILE.read_text(encoding='utf-8'))
    row = data['dungeon']
    if (int(row['id']) != MID or row.get('classType') != 'Putishu'
            or int(row['consumePointTicket']) != 0 or int(row['dailyCountMax']) != 1):
        raise RuntimeError('福果来免费关卡配置发生变化，请核对配置')
    if int(data['score']) != TARGET_SCORE or int(row['itemBagLimit']) != 2:
        raise RuntimeError('福果来积分或背包要求配置发生变化')
    # 复用既有配置刷新缓存；此处只读本地文件，不发起下载或轮询。
    from super_gift import load_cache
    cache = load_cache() or {}
    activity = data['activity']
    if _version(cache.get('freeVersion')) >= _version(data['version']):
        rows = cache.get('freeActivities') or []
        activity = next((r for r in rows if str(r.get('id')) == str(activity['id'])), None)
        if activity is None:
            raise RuntimeError('最新活动配置已无福果来入口')
    if int(activity['dungeonId']) != MID:
        raise RuntimeError('福果来活动入口配置不匹配')
    data['activity'] = activity
    return data


def activity_deadline():
    try:
        return datetime.strptime(config()['activity']['underTime'], TIME_FORMAT)
    except (OSError, ValueError, KeyError, TypeError, RuntimeError):
        return None


def ensure_open(data):
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    start = datetime.strptime(data['activity']['shelfTime'], TIME_FORMAT)
    end = datetime.strptime(data['activity']['underTime'], TIME_FORMAT)
    if not start <= now <= end:
        raise RuntimeError('福果来活动尚未开放或已过期')


def _points(scene):
    user = scene.get('user') or {}
    values = {k: user.get(k) for k in ('gem', 'usedGem')}
    if any(v is None for v in values.values()):
        raise RuntimeError('未能确认点券数据，未开始挑战')
    return values


def show_counts(app, scene):
    label = getattr(app, 'lbl_fuguolai_remain', None)
    if label is None:
        return
    if scene is None:
        label.config(text='免费领奖次数：正在读取…')
        return
    try:
        used = usage(scene).get(MID, 0)
        label.config(text='今日免费领奖剩余：%d（已领%d/1）' % (max(0, 1 - used), used))
    except (ValueError, TypeError, RuntimeError):
        label.config(text='免费领奖次数：读取失败，请刷新')


def run(app, expected_client=None, expected_slot=None):
    client = app.client if expected_client is None else expected_client
    slot = app.current_save['index'] if expected_slot is None else expected_slot
    data = config()

    def check():
        if app.client is not client or (app.current_save or {}).get('index') != slot:
            raise RuntimeError('账号或存档已切换，停止福果来；未重试结算')
        ensure_open(data)

    def post_counts(scene):
        def update():
            if app.client is client and (app.current_save or {}).get('index') == slot:
                show_counts(app, scene)
        app.root.after(0, update)

    flow = None
    baseline = None
    try:
        check()
        flow, _, before = app._connect_and_enter(slot, expected_client=client)
        check()
        baseline = _points(before)
        used = usage(before).get(MID, 0)
        post_counts(before)
        if used >= int(data['dungeon']['dailyCountMax']):
            app._log('[福果来] 今日免费领奖次数已用完，跳过，不购买额外次数')
            return {'runs': 0, 'reason': 'free_times_exhausted'}
        if int(before['curRecord']['p1']['level']) < int(data['dungeon']['needLevel']):
            raise RuntimeError('福果来需要20级，未开图')
        bag = read_bag(before['curRecord'].get('itemsBag'))
        if bag['capacity'] is None or bag['capacity'] - bag['used'] < 2:
            raise RuntimeError('道具背包不足2个空格，未开图，请先清理')

        def request(route, payload):
            check()
            reply = flow.request(route, payload, timeout=20)
            if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
                error = reply.get('error', reply.get('code')) if isinstance(reply, dict) else '无有效回包'
                raise RuntimeError('%s未成功：%s；不重试、不切换付费接口' % (route.rsplit('.', 1)[-1], error))
            if reply.get('gem') is not None and reply['gem'] != baseline['gem']:
                raise RuntimeError('点券变化，停止后续操作，请核对日志')
            return reply

        started = time.monotonic()
        created = request('scene.copyHandler.createSinglePlayerCopy', {'mid': MID, 'costGem': 0})
        copy_id = (created.get('drops') or {}).get('copyId')
        if not copy_id:
            raise RuntimeError('服务器未返回副本ID，停止，不自动重试')
        app._log('[福果来] 免费开图成功，等待10秒后结算600分')
        wait_until = time.monotonic() + WAIT_SECONDS
        while True:
            check()
            remaining = wait_until - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.25, remaining))
        request('scene.copyHandler.finishDungeon', {'dungeonId': MID})
        p1 = before['curRecord']['p1']
        request('scene.copyHandler.syncDropInfoNew', {
            'copyId': copy_id, 'pickItems': [], 'mobIds': [], 'killMonsters': [],
            'completed': 1, 'currentEXP': p1.get('experience', 0), 'pickExp': 0, 'pickSp': 0,
            'propertyP1Str': ';'.join(str(p1.get(k, 0)) for k in
                                    ('hpMax', 'mpMax', 'atk', 'phyDef', 'reHP', 'reMP')),
            'propertyP2Total': 0, 'hitCombo': 0, 'score': TARGET_SCORE,
        })
        reward = request('scene.copyHandler.getDumpActRewards', {
            'id': MID, 'killMonsters': [], 'score': TARGET_SCORE,
        })
        expected = {int(k): int(v) for k, v in data['rewardItems'].items()}
        received = {}
        for item in reward.get('items') or []:
            key = int(item['id'])
            received[key] = received.get(key, 0) + int(item.get('count', 1))
        if received != expected or int(reward.get('copyNum', -1)) != used + 1:
            raise RuntimeError('领奖回包与600分奖励/次数不符，请核对；不重复领取')
        flow.disconnect()
        flow = None
        check()
        flow, _, after = app._connect_and_enter(slot, expected_client=client)
        check()
        if _points(after) != baseline:
            raise RuntimeError('重登后点券或累计消费变化，请核对；不重复领取')
        after_bag = read_bag(after['curRecord'].get('itemsBag'))
        delta = {key: after_bag['counts'].get(key, 0) - bag['counts'].get(key, 0) for key in expected}
        if delta != expected or usage(after).get(MID, 0) != used + 1:
            raise RuntimeError('重登后奖励或领奖次数增量未确认，请刷新核对；不重复领取')
        post_counts(after)
        app._log('[福果来] 600分领奖完成，重登确认菩提果×30、菩提之心×1；点券未变')
        return {'runs': 1, 'score': TARGET_SCORE, 'items': delta,
                'used': used + 1, 'seconds': round(time.monotonic() - started, 3)}
    finally:
        if flow:
            flow.disconnect()


def start(app):
    if not app._ensure_login() or getattr(app, '_limited_activity_busy', False):
        return
    try:
        ensure_open(config())
    except Exception as error:
        app._log('[福果来] 未完成：%s' % error)
        return
    client, slot = app.client, app.current_save['index']
    app._limited_activity_busy = True
    app.btn_fuguolai_run.config(state='disabled')

    def worker():
        try:
            run(app, client, slot)
        except Exception as error:
            app._log('[福果来] 未完成：%s' % error)
        finally:
            def done():
                app._limited_activity_busy = False
                app.btn_fuguolai_run.config(state='normal')
            app.root.after(0, done)
    threading.Thread(target=worker, daemon=True).start()


def build_tab(app):
    tab = app._limited_page(TITLE, padding=12)
    end = activity_deadline()
    ttk.Label(tab, text='600分最高档：菩提果×30、菩提之心×1。',
              wraplength=850).pack(anchor='w', pady=(0, 8))
    ttk.Label(tab, text='每天仅领取1次免费奖励；开图后等待10秒，完成结算并领取。\n'
                       '免费次数用完自动跳过；请预留2个道具背包空格。',
              wraplength=850).pack(anchor='w', pady=6)
    app.lbl_fuguolai_remain = ttk.Label(tab, text='免费领奖次数：登录或切换存档后读取')
    app.lbl_fuguolai_remain.pack(anchor='w', pady=6)
    app.btn_fuguolai_run = ttk.Button(tab, text='完成福果来并领取（600分）', command=app._do_fuguolai_run)
    app.btn_fuguolai_run.pack(anchor='w', pady=10)
    ttk.Label(tab, text='活动截止：%s（北京时间）\n一键运行及“我的日常”沿用本页流程。' % (
        end.strftime('%Y-%m-%d %H:%M:%S') if end else '配置缺失，已停止运行'),
        foreground='gray', wraplength=850).pack(anchor='w')
    listeners = getattr(app, '_count_state_listeners', None)
    if listeners is None:
        app._count_state_listeners = listeners = []
    listeners.append(lambda scene: show_counts(app, scene))
