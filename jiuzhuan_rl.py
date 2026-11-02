"""九转炼丹 RL 策略适配器：调用 freeze-small-model 的神经网络策略。

物理规则（棋盘坐标、合成、出渣解释）全部复用 jiuzhuan_recovery_value，
只替换选点逻辑为已训练的神经网络（torch 依赖，lazy 加载，不影响其它策略）。
"""
from __future__ import annotations
import sys
from pathlib import Path

# 复用底座：物理规则与契约字段全部从 recovery_value 拿，保证与其它策略一致
# （含 TRIPLES / ORDERED_TRIPLES / DISTRIBUTIONS 等供 fast_math.install 使用）
from jiuzhuan_recovery_value import *  # noqa: F401,F403
from jiuzhuan_recovery_value import (  # 显式列出，便于静态阅读
    CELLS, INDEX, POINTS, CONFIG_SOURCE, CONFIG_RULES, CONFIG_PILLS,
    DISTRIBUTIONS, ITEM_PROBABILITIES, STEP_THRESHOLDS, STEP_PROBABILITIES,
    TARGET_SCORE, PRACTICE_CLEAR_LIMIT, GAME_SECONDS,
    board_from_pool, simulate, resolve, explain_random_events,
    step_probability, TRIPLES, ORDERED_TRIPLES, CELL_DEGREE,
)

STRATEGY_VERSION = 'freeze_small_rl_v1'
STABILITY_VERIFIED = False
PLAY_TO_END = False
VALIDATION_NOTE = '基于 freeze-small-model 神经网络策略；训练假设与当前 config 对齐，未在真实服务器验证达标率。'

_MODEL_DIR = Path(__file__).resolve().parent / 'jiuzhuan_rl_model'
_predictor = None


def _load_predictor():
    global _predictor
    if _predictor is not None:
        return _predictor
    try:
        import torch  # noqa: F401  仅在本策略被选中时才需要 torch
    except ImportError as e:
        raise RuntimeError(
            '未安装 torch，无法使用 RL 策略。请用运行本工具箱的同一 Python 版本执行：'
            'python -m pip install torch --index-url https://download.pytorch.org/whl/cpu'
        ) from e
    torch.set_num_threads(1)
    sys.path.insert(0, str(_MODEL_DIR))
    try:
        from inference import Predictor
    except Exception as e:
        raise RuntimeError('加载 RL 策略失败（需要 torch 且 jiuzhuan_rl_model 完整）：%s' % e) from e
    if not (_MODEL_DIR / 'model.pt').is_file():
        raise RuntimeError('缺少模型权重：%s' % (_MODEL_DIR / 'model.pt'))
    _predictor = Predictor(device='cpu')
    return _predictor


def warmup(workers=1):
    """预热：加载权重（workers 仅为接口兼容，单进程推理）。"""
    p = _load_predictor()
    # 跑一次空盘前向，把图和权重真正加载到内存
    p.predict({'board': [0] * 30, 'next_level': 1, 'max_level': 1,
               'water_left': 3, 'score': 0, 'time_left': 300.0})
    print('[jiuzhuan_rl] 模型已加载，device=cpu')
    return {'strategy': STRATEGY_VERSION, 'config': CONFIG_SOURCE['version']}


def shutdown(force=False):
    global _predictor
    _predictor = None


def choose(game, current_score=0, allow_clear=True, clear_limit=3, time_budget=1.8, **kwargs):
    predictor = _load_predictor()
    board = board_from_pool(game['ballPool'])
    next_id = int(game['nextId'])
    max_lvl = max(1, int(game.get('maxId', 1)), max(board))
    used = int(game.get('jingDanNum', 0))
    limit = PRACTICE_CLEAR_LIMIT if clear_limit is None else min(PRACTICE_CLEAR_LIMIT, int(clear_limit))
    water = max(0, limit - used) if allow_clear else 0
    time_left = max(0.0, int(game.get('ut', GAME_SECONDS * 1000)) / 1000.0)
    obs = {
        'board': list(board),
        'next_level': next_id,
        'max_level': max_lvl,
        'water_left': water,
        'score': int(current_score),
        'time_left': time_left,
    }
    result = predictor.predict(obs, include_probabilities=False)
    action_type = result.get('type')
    cell_index = int(result['cell_index'])

    if action_type == 'end' or result.get('action_index') == 60:
        # 模型判定终局（达 45000 或无合法动作）；交给 service 的结算/随机填充分支
        return None

    if not 0 <= cell_index < len(CELLS):
        raise RuntimeError('RL 策略返回非法格子索引：%s' % cell_index)

    if action_type == 'water':
        if board[cell_index] != -1:
            raise RuntimeError('RL 策略请求清理非丹渣格：index=%s' % cell_index)
        predicted = board[:cell_index] + (0,) + board[cell_index + 1:]
        action = 'clear'
    else:
        if board[cell_index] != 0:
            raise RuntimeError('RL 策略请求在非空格落子：index=%s' % cell_index)
        predicted = simulate(board, cell_index, next_id)
        action = None

    x, y = CELLS[cell_index]
    choice = {
        'pos': {'x': x, 'y': y},
        'predicted': tuple(predicted),
        'strategy_version': STRATEGY_VERSION,
        'config_version': CONFIG_SOURCE['version'],
        'search_seconds': 0.0,
        'objective': 'target_45000',
        # 以下为 RL 特有解释字段（不影响 service 契约）
        'rl_type': action_type,
        'rl_action_index': int(result['action_index']),
        'rl_probability': float(result.get('probability', 0.0)),
        'rl_water_left': water,
        'rl_time_left': round(time_left, 2),
        'rl_max_level': max_lvl,
    }
    if action == 'clear':
        choice['action'] = 'clear'
    return choice


def verify_transition(before, choice, reply, after):
    """落子后棋盘一致性校验；丹渣随机事件由 explain_random_events 处理。"""
    predicted = tuple(choice['predicted'])
    actual = board_from_pool(after['ballPool'])
    if choice.get('action') == 'clear':
        return predicted == actual
    return explain_random_events(predicted, actual, reply.get('log'))
