"""九转炼丹完整流程；只用免费次数，实际落子，倒计时后正常结算。"""
import importlib
import time
import threading
import random

MODELS = {
    '(羊肉串)冻结小模型（RL，需torch）': 'jiuzhuan_rl',
    '(花崎桜雪)预期最高分数': 'jiuzhuan_huazaki',
    '共同裁判': 'jiuzhuan_goal_referee',
    '诊断干预版（实验）': 'jiuzhuan_diagnostic_guard',
    '融合达标版（实验）': 'jiuzhuan_fusion',
    '回收价值版': 'jiuzhuan_recovery_value',
    '压力修正版': 'jiuzhuan_pressure_aligned',
    '动态分支版': 'jiuzhuan_adaptive',
    '原 G2W 版': 'jiuzhuan_legacy_g2w',
}
DEFAULT_MODEL = '(羊肉串)冻结小模型（RL，需torch）'
CONFIG_VERSION = 'cg1_20261026_1'
START = 'scene.holidayHandler.startJiuZhuan'
NEXT = 'scene.holidayHandler.addJiuZhuanDan'
SCENE = 'scene.playerHandler.enterScene'
TARGET = 45000
REWARD_ID = 105200006
_RUN_LOCK = threading.Lock()


def load_model(label=DEFAULT_MODEL):
    model = importlib.import_module(MODELS[label])
    if model.CONFIG_SOURCE['version'] != CONFIG_VERSION:
        raise RuntimeError('九转配置版本不匹配，未开局')
    if label not in ('共同裁判', '诊断干预版（实验）', '(花崎桜雪)预期最高分数', '融合达标版（实验）'):
        from jiuzhuan_fast_math import install
        if not getattr(model, '_toolbox_fast_installed', False):
            install(model)
            model._toolbox_fast_installed = True
    return model


def request(flow, route, body):
    reply = flow.request(route, body, timeout=12)
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        raise RuntimeError('九转请求失败：%s，code=%s，error=%s' % (
            route.rsplit('.', 1)[-1], reply.get('code') if isinstance(reply, dict) else '?',
            reply.get('error') if isinstance(reply, dict) else '回包非对象'))
    return reply


def state(scene):
    if not isinstance(scene.get('curRecord'), dict):
        raise RuntimeError('未读取到当前存档')
    act = scene['curRecord'].get('jiuZhuanAct')
    if not isinstance(act, dict) or int(act.get('actId', 0)) != 1450:
        raise RuntimeError('未读取到本期九转活动，未开局')
    return act


def material(model, game):
    return sum(model.POINTS.get(v, 0) for v in model.board_from_pool(game['ballPool']))


def run(flow, scene, *, model_label=DEFAULT_MODEL, practice=True, stop=None,
        emit=None, reconnect=None, clock=time.monotonic, sleep=time.sleep, resume=False):
    """No retry on an ambiguous response. Caller owns initial/final connection.

    reconnect, when supplied, returns (flow, scene) for this same account/slot.
    Events contain game state only, never login/session secrets.
    """
    if not _RUN_LOCK.acquire(blocking=False):
        raise RuntimeError('已有九转任务运行')
    model = None
    try:
        model = load_model(model_label)
        # Warm workers before spending the formal attempt or starting its timer.
        if hasattr(model, 'warmup'):
            model.warmup(3)
        return _play(flow, scene, model, model_label, practice, stop, emit,
                     reconnect, clock, sleep, resume)
    finally:
        if model is not None and hasattr(model, 'shutdown'):
            model.shutdown()
        _RUN_LOCK.release()


def _play(flow, scene, model, label, practice, stop, emit, reconnect, clock, sleep, resume):
    def event(stage, **data):
        if emit:
            emit(stage, **data)
    act = state(scene)
    existing = act.get('curEliminate') or {}
    if existing and not existing.get('isTest') and not resume:
        raise RuntimeError('当前有未结算正式局；先恢复或在游戏中结算，未新开局')
    if not practice and not resume and ('count' not in act or int(act['count']) >= 1):
        raise RuntimeError('免费次数不足或未知；已阻止开局，不花点券')
    before_points = (scene.get('user', {}).get('gem'), scene.get('user', {}).get('usedGem'))
    began = clock()
    if resume:
        if not existing or bool(existing.get('isTest')) != practice:
            raise RuntimeError('没有可恢复的同模式局')
        sync = request(flow, 'scene.holidayHandler.syncActTime', {})
        game = dict(existing)
        game['ut'] = sync.get('ut', existing.get('ut', 0))
        reply = {'jiuZhuanAct': {'curEliminate': game}}
    else:
        reply = request(flow, START, {'isTest': 1} if practice else {})
    game = (reply.get('jiuZhuanAct') or {}).get('curEliminate') or {}
    if not game or bool(game.get('isTest')) != practice:
        raise RuntimeError('开局模式与请求不一致；已停止，勿重复开局')
    remaining = float(game.get('ut', 0)) / 1000
    if not 0 < remaining <= 300:
        raise RuntimeError('倒计时缺失或异常；已停止，勿重复开局')
    # Starting the clock before the request errs on the side of stopping early.
    deadline = began + remaining
    play_to_end = bool(getattr(model, "PLAY_TO_END", False))
    action_deadline = deadline - (2 if play_to_end else 18)
    score = int(reply.get('score', material(model, game)))
    event('started', practice=practice, model=label, config=CONFIG_VERSION, play_to_end=play_to_end,
          free_used_before=act.get('count'), game=game, score=score)
    moves = 0
    reward = None
    terminal = False
    target_announced = False
    while clock() < deadline - 2:
        if score < TARGET and clock() >= action_deadline:
            break
        if stop is not None and stop.is_set():
            event('stopped', score=score, elapsed=clock()-began)
            return {'status': 'stopped_unsettled', 'score': score, 'practice': practice}
        if score >= TARGET and not play_to_end:
            if not target_announced:
                event('target_reached', score=score, elapsed=clock()-began, finish='random_fill')
                target_announced = True
            board = model.board_from_pool(game['ballPool'])
            empty = [i for i,v in enumerate(board) if v == 0]
            if not empty:
                break
            index = random.SystemRandom().choice(empty)
            x,y = model.CELLS[index]
            choice = {'pos': {'x':x, 'y':y},
                      'predicted': model.simulate(board, index, int(game['nextId'])),
                      'finish_random': True}
        else:
            choice = model.choose(game, current_score=score, allow_clear=True,
                                  clear_limit=3, time_budget=1.8)
        if choice is None:
            break
        if clock() >= (deadline-2 if score >= TARGET else action_deadline):
            break
        old = game
        reply = request(flow, NEXT, {'pos': choice['pos']})
        moves += 1
        score = int(reply.get('score', score))
        event('move', move=moves, score=score, pos=choice['pos'],
              action=choice.get('action', 'place'), finish_random=choice.get('finish_random', False), elapsed=clock()-began,
              search_seconds=choice.get('search_seconds'),
              referee_status=choice.get('referee_status'),
              referee_samples=choice.get('referee_samples'), game=reply.get('jiuZhuanAct'),
              log=reply.get('log'), isEnd=reply.get('isEnd'), reward=reply.get('reward'))
        if reply.get('isEnd'):
            terminal = True
            reward = reply.get('reward')
            break
        game = (reply.get('jiuZhuanAct') or {}).get('curEliminate') or {}
        if choice.get('action') == 'clear':
            # Clear responses may be {code:200} only. Read, never resend the move.
            if reconnect:
                flow, fresh = reconnect()
            else:
                fresh = request(flow, SCENE, None)
            game = (state(fresh).get('curEliminate') or {})
            if (bool(game.get('isTest')) != practice or
                    int(game.get('jingDanNum', 0)) != int(old.get('jingDanNum', 0))+1 or
                    game.get('nextId') != old.get('nextId')):
                raise RuntimeError('净丹露状态无法确认，已停止；勿重复提交')
        if not game or bool(game.get('isTest')) != practice or int(game.get('step', -1)) != int(old.get('step', 0))+1:
            raise RuntimeError('回包缺少本局棋盘，已停止；勿重复提交')
        board = model.board_from_pool(game['ballPool'])
        if hasattr(model, 'verify_transition'):
            valid = model.verify_transition(old, choice, reply, game)
        elif choice.get('action') == 'clear':
            valid = tuple(choice['predicted']) == board
        else:
            valid = model.explain_random_events(choice['predicted'], board, reply.get('log'))
        if not valid:
            raise RuntimeError('棋盘合成/随机事件与模型不符，已停止')
        if material(model, game) != score:
            raise RuntimeError('服务器分数与棋盘丹气不一致，已停止')
    if not terminal:
        event('waiting_settlement', score=score, target_met=score >= TARGET,
              elapsed=clock()-began)
        # Official client sends {} when its 300-second timer expires. No more
        # strategic search after reaching the reward cap; random fill is above.
        while clock() < deadline + 1.5:
            if stop is not None and stop.is_set():
                return {'status': 'stopped_unsettled', 'score': score, 'practice': practice}
            sleep(min(.5, max(.001, deadline+1.5-clock())))
        reply = request(flow, NEXT, {})
        event('settlement', score=reply.get('score', score), isEnd=reply.get('isEnd'),
              reward=reply.get('reward'), elapsed=clock()-began)
        if not reply.get('isEnd'):
            raise RuntimeError('服务器未确认结算；不重复提交，请读取本局状态')
        score = int(reply.get('score', score))
        reward = reply.get('reward')
    if reconnect:
        flow, after = reconnect()
    else:
        after = request(flow, SCENE, None)
    after_act = state(after)
    after_points = (after.get('user', {}).get('gem'), after.get('user', {}).get('usedGem'))
    if before_points != after_points or None in before_points:
        raise RuntimeError('点券前后状态异常或缺失，请核查；已停止')
    if after_act.get('curEliminate'):
        raise RuntimeError('结束回包后仍有活动局，结算尚未核实')
    if not practice and not reward:
        raise RuntimeError('正式局未返回奖励，不能认定领取成功')
    result = {'status': 'settled', 'practice': practice, 'model': label,
              'score': score, 'target_met': score >= TARGET, 'moves': moves,
              'reward': reward, 'free_used_after': after_act.get('count'),
              'points_unchanged': True, 'elapsed': round(clock()-began, 3)}
    event('complete', **result)
    return result

