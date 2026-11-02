"""幽夜泽：服务器推送驱动的组队、通关和免费领奖。"""
import queue
import threading
import time
from collections import Counter
from tkinter import ttk

EVENTS = ('onPlayerJoinAwaitRoom', 'onPlayerLeaveAwaitRoom', 'onPlayerChangeStatus',
          'onPlayerChangeSeat', 'onTeamHorseDungeonChange', 'onTeamHorseStart',
          'onKickOutAwaitRoom', 'onTeamHorseDungeonFinish', 'onTeamHorseBossBegin',
          'onTeamHorseBossHP', 'onTeamHorseBossSuccess', 'onTeamHorseBossFail', 'onTeamHorseFail')
REWARD_ITEM = '197000042'


def item_counts(scene):
    rows = scene['curRecord'].get('itemsBag', {}).get('items') or []
    result = Counter()
    for row in (rows.values() if isinstance(rows, dict) else rows):
        result[str(row['id'])] += int(row.get('count', 1))
    return result


class YouyeRun:
    def __init__(self, flow, scene, stop, display, log):
        self.flow, self.scene, self.stop = flow, scene, stop
        self.display, self.log = display, log
        self.incoming = queue.Queue()
        self.room_id = None
        self.room = {}
        self.started = False
        self.boss = None
        self.boss_ready = None
        self.success = None
        self.failure = None
        self.last_ping = 0
        self.created = False
        self.phase = '读取房间'
        self.uid = str(scene['curRecord'].get('userId', scene.get('user', {}).get('uid', '')))
        for name in EVENTS:
            # 回调仅排队，不能在网络接收线程中等待请求响应。
            flow.on(name, lambda data, name=name: self.incoming.put((name, data)))

    def request(self, route, data):
        response = self.flow.request(route, data, timeout=15)
        if response.get('code') != 200 or response.get('error'):
            raise RuntimeError(response.get('error', '请求失败：' + route))
        return response

    def show(self):
        people = [p for p in self.room.get('players', []) if p]
        names = []
        for person in people:
            name = person.get('player', {}).get('name', person.get('playerId', '?'))
            host = str(person.get('playerId')) == str(self.room.get('data', {}).get('uid'))
            state = ('房主·已开局' if host else '已开局') if self.started else ('房主' if host else ('已准备' if person.get('status') == 1 else '未准备'))
            names.append('%s（%s）' % (name, state))
        data = self.room.get('data', {}).get('teamHorseData', {})
        self.display({'phase': self.phase, 'room': self.room_id or '尚未入房',
                      'people': '%d/3：%s' % (len(people), '、'.join(names)),
                      'progress': '全队成功%s/6，失败%s' % (data.get('success', 0), data.get('failure', 0)),
                      'boss': '尚未出现' if self.boss is None else '血量%s' % self.boss.get('hp', '?')})

    def drain(self):
        while True:
            try:
                name, data = self.incoming.get_nowait()
            except queue.Empty:
                break
            if not isinstance(data, dict):
                continue
            incoming_room = data.get('room') or {}
            rid = data.get('roomId') or incoming_room.get('roomId')
            if self.room_id and rid and str(rid) != str(self.room_id):
                continue
            if incoming_room:
                self.room = incoming_room
            if name == 'onTeamHorseStart':
                self.started = True
                self.phase = '已开局，准备进入小关'
                self.log('[幽夜泽] 已收到服务器开局推送')
            elif name == 'onTeamHorseDungeonFinish':
                if data.get('teamHorseData'):
                    self.room.setdefault('data', {})['teamHorseData'] = data['teamHorseData']
                self.log('[幽夜泽] 玩家%s，小关%s，结果%s' % (data.get('playerId'), data.get('dungeonId'), data.get('win')))
            elif name == 'onTeamHorseBossBegin':
                if self.boss is None:
                    self.boss = dict(data)
                    ready_ms = data.get('bossReadyTime') or self.room.get('data', {}).get('teamHorseData', {}).get('bossReadyTime') or 30000
                    self.boss_ready = time.monotonic() + float(ready_ms) / 1000
                    self.phase = 'BOSS已出现，等待准备倒计时'
                    self.log('[幽夜泽] BOSS已出现；准备倒计时结束前不发送伤害')
            elif name == 'onTeamHorseBossHP' and self.boss is not None:
                self.boss.update(data)
            elif name == 'onTeamHorseBossSuccess':
                self.success = data
                self.phase = 'BOSS已击败，准备领取奖励'
            elif name in ('onTeamHorseFail', 'onTeamHorseBossFail', 'onKickOutAwaitRoom'):
                self.failure = name
            self.show()
        if self.stop.is_set():
            raise RuntimeError('用户已停止')
        if self.failure:
            raise RuntimeError('服务器通知结束或移出房间：' + self.failure)

    def pulse(self):
        if not self.flow.game or not self.flow.game._running:
            raise RuntimeError('游戏连接已断开，停止挑战')
        self.drain()
        if self.room_id and time.monotonic() - self.last_ping >= 5:
            self.request('room.awaitHandler.ping', {'roomId': self.room_id, 'code': 200, 'time': int(time.time() * 1000)})
            self.last_ping = time.monotonic()
            self.drain()

    def wait(self, seconds, until_boss=False):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.pulse()
            if self.success or (until_boss and self.boss is not None):
                return
            self.stop.wait(min(.2, max(0, deadline - time.monotonic())))

    def choose_room(self, force_create=False):
        for attempt in range(0 if force_create else 2):
            result = self.request('room.awaitHandler.getAwaitRoomList', {'type': 'teamHorse', 'index': 0, 'limit': 100})
            rooms = result.get('list') or []
            if isinstance(rooms, dict):
                rooms = list(rooms.values())
            candidates = [room for room in rooms if not room.get('lock')
                          and str(room.get('data', {}).get('dungeonId')) == '200401'
                          and len(room.get('players') or []) < 3
                          and not room.get('data', {}).get('teamHorseData', {}).get('status')]
            for room in sorted(candidates, key=lambda r: len(r.get('players') or []), reverse=True):
                self.drain()
                response = self.flow.request('scene.teamHandler.joinTeamHorse', {'id': 200401, 'roomId': room['roomId']}, timeout=15)
                if response.get('code') == 200 and not response.get('error'):
                    self.room_id = str(room['roomId'])
                    self.room = response.get('room') or room
                    self.drain()
                    self.request('room.awaitHandler.changePlayerStatus', {'roomId': self.room_id, 'type': 'ready', 'status': 1})
                    self.phase = '已加入并准备，等待房主开局'
                    self.log('[幽夜泽] 加入他人房间%s，准备成功' % self.room_id)
                    self.pulse()
                    self.show()
                    return
                self.log('[幽夜泽] 房间%s暂不可加入：%s' % (room.get('roomId'), response.get('error', '房间变化')))
            if not candidates:
                break
        self.drain()
        response = self.request('scene.teamHandler.createTeamHorse', {'id': 200401})
        self.room = response['room']
        self.room_id = str(self.room['roomId'])
        self.created = True
        self.phase = '已自建房间，等待三人及队友准备'
        self.log(('[幽夜泽] 指定自建房间%s' if force_create else '[幽夜泽] 没有可加入的公开房间，自建%s') % self.room_id)
        self.show()

    def run(self, force_create=False):
        bag = self.scene['curRecord'].get('itemsBag', {})
        rows = bag.get('items') or []
        if int(bag.get('itemCount', 0)) - len(rows) < 3:
            raise RuntimeError('请先腾出至少3个道具背包格子，再开始幽夜泽')
        self.choose_room(force_create=force_create)
        deadline = time.monotonic() + 300
        last_start = 0
        while not self.started and time.monotonic() < deadline:
            self.pulse()
            people = [p for p in self.room.get('players', []) if p]
            host = str(self.room.get('data', {}).get('uid'))
            ready = len(people) == 3 and all(str(p.get('playerId')) == host or p.get('status') == 1 for p in people)
            if self.created and ready and time.monotonic() - last_start >= 5:
                last_start = time.monotonic()
                response = self.flow.request('scene.teamHandler.startTeamHorse', {'roomId': self.room_id, 'type': 'start'}, timeout=15)
                self.log('[幽夜泽] 请求开局：%s' % response.get('error', response.get('code')))
            elif not self.created:
                me = next((p for p in people if str(p.get('playerId')) == self.uid), None)
                if me and me.get('status') != 1:
                    self.request('room.awaitHandler.changePlayerStatus', {'roomId': self.room_id, 'type': 'ready', 'status': 1})
            self.stop.wait(.2)
        if not self.started:
            raise RuntimeError('等待开局超过5分钟，已停止')
        completed = set()
        for index in range(3):
            self.pulse()
            if self.boss or self.success:
                break
            response = self.request('scene.teamHandler.beginTeamHorseDungeon', {'roomId': self.room_id})
            if response.get('room'):
                self.room = response['room']
            self.drain()
            dungeon = response['dungeonId']
            if str(dungeon) in completed:
                raise RuntimeError('服务器重复分配已结算的小关，停止重复提交')
            self.phase = '小关%s：第%d/3关，进入后等待30秒' % (dungeon, index + 1)
            self.show()
            self.wait(30, until_boss=True)
            if self.boss or self.success:
                break
            result = self.request('scene.teamHandler.endTeamHorseDungeon', {'roomId': self.room_id, 'dungeonId': dungeon, 'win': 1})
            if result.get('win') != 1:
                raise RuntimeError('服务器未确认小关成功，停止后续提交')
            completed.add(str(dungeon))
            self.log('[幽夜泽] 小关%s通关请求成功' % dungeon)
            self.wait(3, until_boss=True)
        self.phase = '个人小关结束，等待全队完成和BOSS出现'
        self.show()
        deadline = time.monotonic() + 600
        last_attack = 0
        while not self.success and time.monotonic() < deadline:
            self.pulse()
            if self.success:
                break
            now = time.monotonic()
            if self.boss is not None and self.boss_ready is not None and now >= self.boss_ready:
                self.phase = 'BOSS战：每次10000伤害，间隔至少1秒'
                self.show()
                if now - last_attack >= 1:
                    # 收到成功推送后不再开始下一次请求。
                    self.drain()
                    if self.success:
                        break
                    self.request('scene.teamHandler.attackTeamHorseBoss', {'roomId': self.room_id, 'hurt': 10000})
                    last_attack = time.monotonic()
            self.stop.wait(.2)
        if not self.success:
            raise RuntimeError('未收到服务器BOSS成功凭证，不领取奖励')
        self.phase = '正在房间内领取免费奖励'
        self.show()
        reward = self.request('scene.copyHandler.getTeamHorseBossReward', {'roomId': self.room_id, 'token': self.success['token'], 'id': self.success['id']})
        self.log('[幽夜泽] 领奖成功：%s' % reward.get('items', []))
        return reward


def build_panel(app, parent):
    panel = ttk.LabelFrame(parent, text='幽夜泽（三人组队）', padding=10)
    panel.pack(fill='both', expand=True, pady=5)
    ttk.Label(panel, text='优先加入可用公开房间；没有可加入的房间才自建。自动准备，房主凑齐三人且队友准备后开局。', wraplength=720).pack(anchor='w')
    labels = {}
    for key, title in (('phase', '当前阶段'), ('room', '房间'), ('people', '成员'), ('progress', '小关进度'), ('boss', 'BOSS')):
        label = ttk.Label(panel, text=title + '：待开始', wraplength=720)
        label.pack(anchor='w', pady=2)
        labels[key] = (title, label)
    ttk.Label(panel, text='小关进入30秒后结算；BOSS出现并结束准备倒计时后，每次上报10000伤害，间隔至少1秒。\n领奖后重登核对兽魂宝箱和点券；开始前需至少3个道具空格。', wraplength=720, foreground='gray').pack(anchor='w', pady=5)
    actions = ttk.Frame(panel)
    actions.pack(fill='x')
    stop = threading.Event()

    def display(values):
        def apply():
            for key, value in values.items():
                title, label = labels[key]
                label.config(text=title + '：' + str(value))
        app.root.after(0, apply)

    def start():
        if not app._ensure_login():
            return
        save_index = app.current_save['index']
        stop.clear()
        start_button.config(state='disabled')
        stop_button.config(state='normal')
        display({'phase': '正在登录槽%s' % save_index, 'room': '待匹配', 'people': '待匹配', 'progress': '待开始', 'boss': '尚未出现'})
        def worker():
            flow = verify = runner = None
            try:
                flow, _, before = app._connect_and_enter(save_index)
                points = {key: before['user'].get(key) for key in ('gem', 'usedGem')}
                initial = item_counts(before)
                runner = YouyeRun(flow, before, stop, display, app._log)
                reward = runner.run()
                runner.request('room.awaitHandler.exitAwaitRoom', {'roomId': runner.room_id})
                runner.room_id = None
                flow.disconnect()
                flow = None
                display({'phase': '领奖成功，重登核对背包'})
                verify, _, after = app._connect_and_enter(save_index)
                expected = Counter()
                for row in reward.get('items', []):
                    expected[str(row['id'])] += int(row.get('count', 1))
                final = item_counts(after)
                for item, count in expected.items():
                    actual = final[item] - initial[item]
                    app._log('[幽夜泽核验] 物品%s：%d→%d；预期+%d，实际+%d' % (item, initial[item], final[item], count, actual))
                    if actual != count:
                        raise RuntimeError('奖励回包与重登背包变化不一致')
                if not expected:
                    raise RuntimeError('领奖回包没有物品，需核实')
                if any(points[key] != after['user'].get(key) for key in points):
                    raise RuntimeError('点券或累计消费变化，需核实')
                display({'phase': '完成：奖励已入包，点券未变'})
                app._log('[幽夜泽] 完整流程核验完成，奖励已入包，点券未变')
            except Exception as error:
                text = str(error)
                app._log('[幽夜泽] 已停止：' + text)
                display({'phase': '已停止：' + text})
            finally:
                if runner and flow and runner.room_id:
                    try:
                        runner.request('room.awaitHandler.exitAwaitRoom', {'roomId': runner.room_id})
                    except Exception as error:
                        app._log('[幽夜泽] 退出房间未确认：%s' % error)
                for connection in (flow, verify):
                    if connection:
                        try:
                            connection.disconnect()
                        except Exception:
                            pass
                def finish():
                    start_button.config(state='normal')
                    stop_button.config(state='disabled')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    start_button = ttk.Button(actions, text='自动组队、通关并领奖一次', command=start)
    start_button.pack(side='left', padx=4)
    stop_button = ttk.Button(actions, text='停止并退出房间', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
