"""魔渊前八层：复用2026-10-22实测请求，重登核验进度、领奖和背包。"""
from collections import Counter
from functools import lru_cache
import json
from pathlib import Path
import threading
import time
import tkinter as tk
from tkinter import ttk

BASE = Path(__file__).resolve().parent


def load_config():
    config = json.loads((BASE / 'moyuan_weekly_config.json').read_text(encoding='utf-8'))
    if (int(config['firstDungeonId']), int(config['lastDungeonId']), int(config['targetScore'])) != (300101, 300108, 8000):
        raise RuntimeError('魔渊配置超出已验证的前八层范围')
    if [int(x['id']) for x in config['rewards']] != [1, 2, 3, 4, 5]:
        raise RuntimeError('魔渊阶段奖励配置异常')
    if any(int(x['score']) > 8000 for x in config['rewards']):
        raise RuntimeError('魔渊奖励超出8000分范围')
    return config


def progress(scene, config):
    value = scene.get('curRecord', {}).get('zhuXie')
    if not isinstance(value, dict) or not all(k in value for k in ('cur', 'score', 'actId')):
        raise RuntimeError('未读到完整魔渊进度，请先确认该存档已开放魔渊')
    if int(value['actId']) != int(config['actId']):
        raise RuntimeError('服务器魔渊期数为%s，当前配置为%s，需要更新本期配置' %
                           (value['actId'], config['actId']))
    if not 0 <= int(value['cur']) <= 9 or int(value['score']) < 0:
        raise RuntimeError('服务器魔渊层数或积分异常')
    return dict(value)


def reward_received(state, reward_id):
    values = state.get('reward') or {}
    if not isinstance(values, dict):
        raise RuntimeError('服务器奖励领取标记格式异常')
    return values.get(str(reward_id), values.get(reward_id)) in (True, 1, '1')


def pending_rewards(state, config):
    return [r for r in config['rewards'] if not reward_received(state, r['id'])]


def item_counts(scene):
    bag = scene.get('curRecord', {}).get('itemsBag')
    if not isinstance(bag, dict):
        raise RuntimeError('未读取到道具背包')
    rows = bag.get('items') or []
    rows = rows.values() if isinstance(rows, dict) else rows
    result = Counter()
    for row in rows:
        result[str(row['id'])] += int(row.get('count', 1) or 0)
    return result


def points(scene):
    user = scene.get('user') or {}
    if not all(key in user for key in ('gem', 'usedGem')):
        raise RuntimeError('未读取到点券与累计消费，停止执行')
    return {key: user[key] for key in ('gem', 'usedGem')}


def check_room(scene, rewards):
    bag = scene['curRecord']['itemsBag']
    if 'itemCount' not in bag:
        raise RuntimeError('未读取到背包容量')
    existing = item_counts(scene)
    needed = {str(iid) for r in rewards for iid in r['items'] if existing[str(iid)] == 0}
    free = int(bag['itemCount']) - len(bag.get('items') or [])
    if free < len(needed):
        raise RuntimeError('待领奖励至少还需%d个背包格子，当前空闲%d个' % (len(needed), max(0, free)))


@lru_cache(maxsize=1)
def item_names():
    names = {}
    folder = BASE / 'output_cg1_20260921_1_2'
    for path in folder.glob('*___Prop.xml.json'):
        rows = json.loads(path.read_text(encoding='utf-8')).get('RECORD', [])
        rows = [rows] if isinstance(rows, dict) else rows
        names.update({str(r['id']): str(r.get('name', r['id'])) for r in rows})
    return names


def reward_text(items):
    names = item_names()
    return '、'.join('%s×%s' % (names.get(str(iid), str(iid)), count) for iid, count in items.items())


class MoyuanRun:
    def __init__(self, connect, log, stop=None, config=None):
        self.connect = connect
        self.log = log
        self.stop = stop if stop is not None else threading.Event()
        self.config = config if config is not None else load_config()
        self.flow = None

    def close(self):
        if self.flow is not None:
            try:
                self.flow.disconnect()
            finally:
                self.flow = None

    def reconnect(self):
        self.close()
        self.flow, _, scene = self.connect()
        return scene, progress(scene, self.config)

    def request(self, route, body):
        reply = self.flow.request(route, body, timeout=25)
        if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
            detail = reply.get('error', reply) if isinstance(reply, dict) else reply
            raise RuntimeError('%s：%s' % (route, detail))
        return reply

    def refresh(self):
        try:
            scene, state = self.reconnect()
            points(scene)
            return state
        finally:
            self.close()

    def run(self, clear=True):
        claimed = []
        expected_items = Counter()
        try:
            scene, state = self.reconnect()
            before_points = points(scene)
            before_items = item_counts(scene)
            missing = pending_rewards(state, self.config)
            if not missing:
                self.log('[魔渊前八层] 本期五档阶段奖励均已领取。')
                return {'state': state, 'claimed': [], 'verified': True, 'stopped': False}
            # Include rewards reached by the requested clearing, before consuming a challenge.
            desired = missing if clear else [r for r in missing if int(r['score']) <= int(state['score'])]
            check_room(scene, desired)
            while clear and int(state['score']) < 8000 and int(state['cur']) < 8:
                if self.stop.is_set():
                    break
                current = int(state['cur'])
                expected_mid = 300101 + current
                # Never call open after the eighth layer or when 8000 was already reached.
                opened = self.request('scene.onlineCopyHandler.openZhuXieChallenge', {})
                mid = int(opened.get('dungeonId', 0))
                if mid not in range(300101, 300109):
                    raise RuntimeError('服务器返回关卡%s，超出前八层，未发送通关请求' % mid)
                if mid != expected_mid or int(opened.get('isOnline', 0) or 0) != 0:
                    raise RuntimeError('服务器关卡或联机标记与当前进度不符，停止结算')
                self.log('[魔渊前八层] 第%d层（%d）已进入。' % (current + 1, mid))
                time.sleep(float(self.config['stageDelaySeconds']))
                ended = self.request('scene.onlineCopyHandler.endZhuXieChallenge', {
                    'param': False, 'life': 0, 'bossHp': 0,
                    'frames': [{'currFrame': int(self.config['settlementFrame'])}],
                    'cg': self.config['cg'],
                })
                next_state = progress({'curRecord': ended}, self.config)
                if int(next_state['cur']) != current + 1 or int(next_state['score']) < (current + 1) * 1000:
                    raise RuntimeError('服务器未确认第%d层进度，停止后续操作' % (current + 1))
                state = next_state
                self.log('[魔渊前八层] 第%d层结算成功，净化魔气%d。' % (current + 1, int(state['score'])))

            expected_score = int(state['score'])
            scene, state = self.reconnect()
            if points(scene) != before_points:
                raise RuntimeError('重登后点券或累计消费发生变化，停止执行')
            if int(state['score']) < expected_score:
                raise RuntimeError('重登后魔渊积分未持久化，停止领奖')
            if self.stop.is_set():
                self.log('[魔渊前八层] 已完成当前层并停止；可稍后继续或单独领奖。')
                return {'state': state, 'claimed': [], 'verified': True, 'stopped': True}
            if clear and int(state['score']) < 8000:
                raise RuntimeError('当前进度不足8000分，未继续挑战或领取阶段奖励')

            eligible = [r for r in pending_rewards(state, self.config) if int(r['score']) <= int(state['score'])]
            check_room(scene, eligible)
            for reward in eligible:
                if self.stop.is_set():
                    break
                reply = self.request('scene.onlineCopyHandler.getReward', {'id': int(reward['id'])})
                new_state = progress({'curRecord': reply}, self.config)
                if not reward_received(new_state, reward['id']):
                    raise RuntimeError('领奖回包未确认第%s档标记，请刷新核对，不自动重试' % reward['id'])
                rows = reply.get('resultItem')
                if not isinstance(rows, list):
                    raise RuntimeError('领奖回包缺少resultItem，请刷新核对，不自动重试')
                received = Counter()
                for item in rows:
                    received[str(item['id'])] += int(item.get('count', 0))
                configured = Counter({str(k): int(v) for k, v in reward['items'].items()})
                if received != configured:
                    raise RuntimeError('第%s档奖励回包与配置不一致，请刷新核对，不自动重试' % reward['id'])
                state = new_state
                claimed.append(int(reward['id']))
                expected_items.update(received)
                self.log('[魔渊前八层] %s分奖励回包成功：%s。' %
                          (reward['score'], reward_text(received)))

            scene, final = self.reconnect()
            if points(scene) != before_points:
                raise RuntimeError('领奖后点券或累计消费发生变化')
            after_items = item_counts(scene)
            for reward_id in claimed:
                if not reward_received(final, reward_id):
                    raise RuntimeError('重登后第%d档领取标记缺失，不能确认领奖成功' % reward_id)
            for iid, count in expected_items.items():
                delta = after_items[iid] - before_items[iid]
                self.log('[魔渊前八层] 重登核对%s：%d → %d（增加%d，预期%d）。' %
                          (item_names().get(iid, iid), before_items[iid], after_items[iid], delta, count))
                if delta != count:
                    raise RuntimeError('物品%s入包数量与领奖回包不一致' % iid)
            self.log('[魔渊前八层] 完成；本次%d档奖励已重登核对，点券未变。' % len(claimed))
            return {'state': final, 'claimed': claimed, 'verified': True, 'stopped': self.stop.is_set()}
        finally:
            self.close()


def build_panel(app, parent):
    config = load_config()
    ttk.Label(parent, text='魔渊诛邪·前八层：达到8000分后领取五档阶段奖励。',
              wraplength=720).pack(anchor='w', pady=8)
    ttk.Label(parent, text='自动读取当前进度，从未完成层继续；第八层后停止。奖励领取后重登核对背包。',
              wraplength=720).pack(anchor='w', pady=5)
    status = ttk.Label(parent, text='登录并选择存档后，点击刷新读取本期进度。', wraplength=720)
    status.pack(anchor='w', pady=8)
    table = ttk.Treeview(parent, columns=('score', 'items', 'status'), show='headings', height=5)
    for key, title, width in [('score', '净化魔气', 100), ('items', '阶段奖励', 470), ('status', '状态', 100)]:
        table.heading(key, text=title)
        table.column(key, width=width, stretch=(key == 'items'))
    table.pack(fill='x', pady=8)
    for reward in config['rewards']:
        table.insert('', 'end', iid=str(reward['id']), values=(reward['score'], reward_text(reward['items']), '未读取'))
    controls = ttk.Frame(parent)
    controls.pack(anchor='w', pady=8)
    stop = threading.Event()
    busy = False
    buttons = []

    def update(state):
        received = sum(reward_received(state, r['id']) for r in config['rewards'])
        status.config(text='本期%s；当前已通关%d层；净化魔气%d；阶段奖励已领取%d/5。' %
                      (state['actId'], state['cur'], state['score'], received))
        for reward in config['rewards']:
            label = '已领取' if reward_received(state, reward['id']) else (
                '可领取' if int(state['score']) >= int(reward['score']) else '未达成')
            table.set(str(reward['id']), 'status', label)

    def start(mode):
        nonlocal busy
        if busy or not app._ensure_login():
            return
        slot = app.current_save['index']
        busy = True
        stop.clear()
        for button in buttons:
            button.config(state='disabled')
        stop_button.config(state='normal' if mode != 'refresh' else 'disabled')
        status.config(text='正在连接槽%s，读取魔渊进度…' % slot)

        def worker():
            state = None
            error_text = None
            runner = MoyuanRun(lambda: app._connect_and_enter(slot), app._log, stop, config)
            try:
                if mode == 'refresh':
                    state = runner.refresh()
                else:
                    app._log('[魔渊前八层] 槽%s，%s。' % (slot, '续跑并领奖' if mode == 'clear' else '仅领取已达成奖励'))
                    state = runner.run(clear=(mode == 'clear'))['state']
            except Exception as error:
                error_text = '已停止：%s' % error
                app._log('[魔渊前八层] ' + error_text)
            finally:
                def finish():
                    nonlocal busy
                    busy = False
                    if state is not None:
                        update(state)
                    if error_text is not None:
                        status.config(text=error_text)
                    for button in buttons:
                        button.config(state='normal')
                    stop_button.config(state='disabled')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for text, mode in [('刷新进度与奖励', 'refresh'), ('通关前八层并领奖', 'clear'), ('仅领取已达成奖励', 'claim')]:
        button = ttk.Button(controls, text=text, command=lambda mode=mode: start(mode))
        button.pack(side='left', padx=(0, 6))
        buttons.append(button)
    stop_button = ttk.Button(controls, text='本层结束后停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=3)
