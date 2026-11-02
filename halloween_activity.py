"""万圣节2035：20261026配置，每日两次免费完整副本流程。"""
import threading
import time
from datetime import datetime, timezone, timedelta
from tkinter import ttk

MID = 2035
ACTIVITY = 44
DAILY_MAX = 2
CONFIG_VERSION = 'cg1_20261026_1'
BEGIN = datetime(2016, 10, 19, 16, 43, 11)
END = datetime(2026, 11, 15, 23, 59, 59)
_LOCK = threading.Lock()


def used(scene):
    record = scene.get('curRecord')
    if not isinstance(record, dict) or not isinstance(record.get('copyHistory'), list):
        raise RuntimeError('未读取到副本次数，未进入万圣节')
    return sum(int(r.get('num', 0)) for r in record['copyHistory'] if int(r.get('id', -1)) == MID)


def bag_count(scene, iid):
    bag = scene['curRecord'].get('itemsBag') or {}
    items = bag.get('items', []) if isinstance(bag, dict) else bag
    if not isinstance(items, list):
        raise RuntimeError('背包格式未知，无法核实奖励')
    return sum(int(r.get('count', r.get('num', 1)) or 0) for r in items
               if str(r.get('id', r.get('itemId'))) == str(iid))


def points(scene):
    user = scene.get('user') or {}
    if user.get('gem') is None or user.get('usedGem') is None:
        raise RuntimeError('点券状态缺失，停止免费副本操作')
    return user['gem'], user['usedGem']


def clear_once(flow, scene, emit):
    now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    if not BEGIN <= now <= END:
        raise RuntimeError('万圣节不在本期开放时间内')
    if used(scene) >= DAILY_MAX:
        raise RuntimeError('万圣节免费次数已用完，不花点券')
    if int((scene['curRecord'].get('p1') or {}).get('level', 0)) < 20:
        raise RuntimeError('万圣节需要20级')
    points(scene)
    def req(name, body):
        r = flow.request('scene.copyHandler.'+name, body, timeout=20)
        emit('route', route=name, code=r.get('code'), error=r.get('error'))
        if r.get('code') != 200 or r.get('error'):
            raise RuntimeError('%s失败：%s；不自动重试' % (name, r.get('error', r.get('code'))))
        return r
    created = req('createSinglePlayerCopy', {'mid': MID, 'costGem': 0})
    drops = created.get('drops') or {}
    if not drops.get('copyId'):
        raise RuntimeError('创建未返回副本ID，不重复创建')
    picks, mobs, kills, counts = [], [], [], {}
    exp = spirit = 0
    for drop in drops.get('newDrops') or []:
        exp += int(drop.get('exp', 0) or 0)
        spirit += int(drop.get('spirit', 0) or 0)
        if drop.get('item'):
            monster = str(drop['monsterId'])
            mobs.append(monster)
            kills.append('%s_%s' % (monster, drop.get('index', 0)))
            for iid, values in drop['item'].items():
                if not isinstance(values, list):
                    raise RuntimeError('掉落格式异常，停止当前副本')
                for value in values:
                    picks.append(value)
                    num = int(value.get('count', 1) or 1) if isinstance(value, dict) else 1
                    counts[str(iid)] = counts.get(str(iid), 0)+num
    emit('drops', expected=counts, drop_monsters=len(drops.get('newDrops') or []))
    time.sleep(.5)
    req('bossDead', None)
    req('finishDungeon', {'dungeonId': MID})
    p = scene['curRecord']['p1']
    req('syncDropInfoNew', {'copyId': drops['copyId'], 'pickItems': picks,
        'mobIds': mobs, 'killMonsters': kills, 'completed': 1,
        'currentEXP': p.get('experience', 0), 'pickExp': exp, 'pickSp': spirit,
        'propertyP1Str': ';'.join(str(p.get(k, 0)) for k in
            ('hpMax', 'mpMax', 'atk', 'phyDef', 'reHP', 'reMP')),
        'propertyP2Total': 0, 'hitCombo': 100})
    return counts


def run_daily(connect, *, limit=2, emit=None):
    """connect returns a fresh (flow, scene) for the same account/slot.

    Keep one connection across create/finish/sync; after each successful run,
    reconnect read-only to verify counts, bag deltas and unchanged point tickets.
    """
    emit = emit or (lambda *args, **kw: None)
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError('万圣节任务已在运行')
    flow = None
    results = []
    try:
        flow, scene = connect()
        initial = used(scene)
        emit('state', used=initial, remaining=max(0, DAILY_MAX-initial), config=CONFIG_VERSION)
        for n in range(min(max(0, int(limit)), max(0, DAILY_MAX-initial))):
            before_used, before_points = used(scene), points(scene)
            started = time.monotonic()
            counts = clear_once(flow, scene, emit)
            baseline = scene
            flow.disconnect()
            flow = None
            flow, scene = connect()
            after_used = used(scene)
            actual = {iid: bag_count(scene, iid)-bag_count(baseline, iid) for iid in counts}
            if after_used != before_used+1:
                raise RuntimeError('次数未按预期增加1，停止后续挑战')
            if before_points != points(scene):
                raise RuntimeError('点券状态变化，停止后续挑战')
            if actual != counts:
                raise RuntimeError('奖励入账与掉落不一致，停止后续挑战：%s / %s' % (actual, counts))
            result = {'number': n+1, 'used_before': before_used, 'used_after': after_used,
                      'rewards': actual, 'points_unchanged': True,
                      'elapsed': round(time.monotonic()-started, 3)}
            results.append(result)
            emit('verified', **result)
        emit('complete', completed=len(results), used=used(scene), remaining=max(0, DAILY_MAX-used(scene)))
        return results
    finally:
        if flow:
            flow.disconnect()
        _LOCK.release()


class HalloweenPage:
    def _do_jiuzhuan(self, *args, **kwargs):
        if getattr(self, '_halloween_busy', False):
            self._log('[九转炼丹] 请先结束当前万圣节任务')
            return
        return super()._do_jiuzhuan(*args, **kwargs)

    def _build_halloween_tab(self):
        tab = self._limited_page('万圣节', padding=12)
        ttk.Label(tab, text='万圣节：每日2次免费挑战；完成通关、拾取结算后核对奖励入账。',
                  wraplength=850).pack(anchor='w', pady=8)
        ttk.Label(tab, text='配置 cg1_20261026_1；活动44 / 副本2035；开放至2026年11月15日。\n'
                  '仅执行剩余免费次数，不购买200点券额外次数。',
                  wraplength=850, foreground='gray').pack(anchor='w', pady=8)
        self.lbl_halloween = ttk.Label(tab, text='登录后刷新剩余次数')
        self.lbl_halloween.pack(anchor='w', pady=8)
        def count_changed(scene):
            if scene is None:
                text = '当前存档：正在刷新万圣节次数…'
            else:
                try:
                    count = used(scene)
                    text = '今日已用%d/2，剩余%d次' % (count, max(0, DAILY_MAX-count))
                except (ValueError, TypeError, RuntimeError):
                    text = '当前存档万圣节次数未知，请刷新'
            self.lbl_halloween.config(text=text)
        if not hasattr(self, '_count_state_listeners'):
            self._count_state_listeners = []
        self._count_state_listeners.append(count_changed)
        row = ttk.Frame(tab)
        row.pack(anchor='w', pady=8)
        self._halloween_buttons = []
        for text, limit in [('刷新次数', 0), ('完成当天剩余免费次数', 2)]:
            b = ttk.Button(row, text=text, command=lambda n=limit: self._do_halloween(n))
            b.pack(side='left', padx=5)
            self._halloween_buttons.append(b)

    def _do_halloween(self, limit):
        if not self._ensure_login() or getattr(self, '_halloween_busy', False):
            return
        if getattr(self, '_jiuzhuan_running', False):
            self._log('[万圣节] 请先结束当前九转任务')
            return
        slot, client = self.current_save['index'], self.client
        self._halloween_busy = True
        for b in self._halloween_buttons:
            b.config(state='disabled')
        self.combo_save.config(state='disabled')
        self.btn_login.config(state='disabled')
        def connect():
            if self.client is not client:
                raise RuntimeError('账号已切换，停止万圣节任务')
            flow, _, scene = self._connect_and_enter(slot)
            return flow, scene
        def emit(stage, **data):
            if stage in ('state', 'complete'):
                text = '今日已用%d/2，剩余%d次' % (data['used'], data['remaining'])
            elif stage == 'verified':
                text = '第%d次完成，已用%d/2，奖励%s，点券未变' % (
                    data['number'], data['used_after'], data['rewards'])
            else:
                return
            self._log('[万圣节] '+text)
            self.root.after(0, lambda t=text: self.lbl_halloween.config(text=t))
        def worker():
            try:
                run_daily(connect, limit=limit, emit=emit)
            except Exception as e:
                self._log('[万圣节] '+str(e)+'；未自动重试')
            finally:
                def done():
                    self._halloween_busy = False
                    for b in self._halloween_buttons:
                        b.config(state='normal')
                    self.combo_save.config(state='readonly')
                    self.btn_login.config(state='normal')
                self.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()
