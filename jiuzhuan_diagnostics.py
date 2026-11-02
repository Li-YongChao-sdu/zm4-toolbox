"""Read-only 九转 diagnostics. No choose(), weights, RNG, network or policy hooks.

All positions are {x, y}. Facts use cg1_20261026_1 and the existing resolver.
Geometric plans describe possibilities, not mutually independent rewards or a
prediction of winning. Only explicitly named bounds are conclusive.
"""
from collections import Counter
from jiuzhuan_recovery_value import (
    CELLS, INDEX, TRIPLES, POINTS, DISTRIBUTIONS, CONFIG_SOURCE,
    resolve, board_from_pool, simulate_with_merge_levels,
)

VERSION = 'diagnostics_v1_readonly'


def _positions(indices):
    return [{'x': CELLS[i][0], 'y': CELLS[i][1]} for i in indices]


def _support(highest):
    return {v: w/sum(w for _, w in DISTRIBUTIONS[highest])
            for v, w in DISTRIBUTIONS[highest]}


def _inventory(board, highest):
    floor = min(_support(highest))
    low = [i for i, v in enumerate(board) if 0 < v < floor]
    nines = [i for i, v in enumerate(board) if v == 9]
    slag = [i for i, v in enumerate(board) if v == -1]
    return {
        'empty': board.count(0), 'natural_draw_floor': floor,
        'low_without_natural_supply': _positions(low),
        'low_without_natural_supply_count': len(low),
        'low_histogram': dict(sorted(Counter(board[i] for i in low).items())),
        'unmergeable_nines': _positions(nines), 'nine_count': len(nines),
        'slag': _positions(slag), 'slag_count': len(slag),
        'active_pill_count': sum(floor <= v < 9 for v in board),
        'note': '低阶无自然来源不自动等于无解；本轮已知丹药可能触发低阶连锁补救。',
    }


def _placements(board, pill):
    rows = []
    for i, value in enumerate(board):
        if value != 0:
            continue
        after, levels = simulate_with_merge_levels(board, i, pill)
        rows.append({'index': i, 'after': after, 'merge_levels': levels})
    return rows


def _plans(board, highest, known):
    """Compatible occupied lines; every plan lists all resources it consumes.

    No summed plan score/probability is produced. A future indirect chain can
    create a pill even when its direct draw probability is zero; do not label
    such a plan impossible solely because it is not in the current distribution.
    """
    support = _support(highest)
    plans = []
    for line_id, triple in enumerate(TRIPLES):
        values = [board[i] for i in triple]
        occupied = [i for i in triple if board[i] > 0]
        if not occupied or any(v < 0 or v == 9 for v in values):
            continue
        level = board[occupied[0]]
        if any(board[i] != level for i in occupied):
            continue
        blank = [i for i in triple if board[i] == 0]
        if not blank:
            continue  # Inputs must already be settled.
        plans.append({
            'id': '%d:%d' % (line_id, level), 'line_id': line_id, 'level': level,
            'cells': list(triple), 'occupied_indices': occupied,
            'blank_indices': blank, 'missing_count': len(blank),
            'known_pill_matches': known == level,
            'natural_draw_probability_per_draw': support.get(level, 0.),
            'supply': ('natural_draw_available' if level in support else
                       'known_pill_or_indirect_chain_required'),
        })
    return plans


def _plan_report(plans):
    conflicts = []
    for i, a in enumerate(plans):
        for b in plans[i+1:]:
            shared = set(a['cells']) & set(b['cells'])
            if shared:
                conflicts.append({'a': a['id'], 'b': b['id'],
                                  'shared_cells': _positions(sorted(shared))})
    users = {}
    for plan in plans:
        for i in plan['blank_indices']:
            users.setdefault(i, []).append(plan['id'])
    shared_blanks = [{'pos': _positions([i])[0], 'plan_ids': ids}
                     for i, ids in sorted(users.items()) if len(ids) > 1]
    # A concrete feasible packing witness, not an optimum and not a policy.
    # Ordering is deterministic; no tuneable weights or combined score.
    occupied = set()
    witness = []
    for plan in sorted(plans, key=lambda p: (p['missing_count'], p['line_id'])):
        if not occupied.intersection(plan['cells']):
            witness.append(plan['id'])
            occupied.update(plan['cells'])
    public = []
    for plan in plans:
        item = {k: v for k, v in plan.items()
                if k not in ('cells', 'occupied_indices', 'blank_indices')}
        item.update(cells=_positions(plan['cells']),
                    occupied=_positions(plan['occupied_indices']),
                    required_blanks=_positions(plan['blank_indices']))
        public.append(item)
    return {'compatible_plans': public, 'conflicts': conflicts,
            'shared_blank_cells': shared_blanks,
            'disjoint_plan_witness': witness,
            'witness_is_maximum': False,
            'note': '几何兼容不保证能兑现；不相交集合仅为见证，不是最优组合，也不累加成功概率。'}


def _immediate(rows, empty):
    return [{'pos': _positions([r['index']])[0],
             'merge_levels': list(r['merge_levels']),
             'empty_after': r['after'].count(0),
             'net_empty_change': r['after'].count(0)-empty}
            for r in rows if r['merge_levels']]


def _promotion(board, highest, pill, rows, score, target):
    before = _inventory(board, highest)
    before_floor = before['natural_draw_floor']
    old_support = set(_support(highest))
    promotions, wait, cleanup = [], [], []
    low_count = sum(0 < v <= 4 for v in board)
    for r in rows:
        after = r['after']
        new_highest = max(highest, max(after))
        after_floor = min(_support(new_highest))
        after_low = [i for i, v in enumerate(after) if 0 < v < after_floor]
        # A new cutoff affects only surviving cells that were not below the
        # previous cutoff. Existing already-retired pieces are not counted twice.
        newly = [i for i in after_low if after[i] >= before_floor]
        item = {'pos': _positions([r['index']])[0], 'highest_after': new_highest,
                'empty_after': after.count(0), 'merge_levels': list(r['merge_levels']),
                'new_unmergeable_nine_positions': _positions(
                    [i for i, v in enumerate(after) if v == 9 and board[i] != 9]),
                'working_cells_after': sum(v == 0 or after_floor <= v < 9 for v in after),
                'fills_board_before_target': after.count(0) == 0 and score+POINTS[pill] < target}
        if new_highest > highest:
            item.update(
                natural_draw_floor_before=before_floor,
                natural_draw_floor_after=after_floor,
                lost_natural_draw_levels=sorted(old_support-set(_support(new_highest))),
                newly_without_natural_supply=_positions(newly),
                newly_without_natural_supply_count=len(newly),
                total_low_without_natural_supply_after=len(after_low),
                irreversible_cutoff=after_floor > before_floor,
                evidence='after_resolving_known_pill_before_random_residue',
            )
            promotions.append(item)
        else:
            wait.append(item)
        removed = low_count-sum(0 < v <= 4 for v in after)
        if removed > 0:
            cleanup.append({**item, 'low_pill_occupancy_reduction': removed})
    return {'before': before, 'promoting_placements': promotions,
            'nonpromoting_placements': wait, 'low_cleanup_placements': cleanup,
            'nonpromotion_possible_now': bool(wait),
            'note': '只比较当前已知丹药；暂缓升阶不保证以后抽到所需低阶，也可能耗尽空间。'}


def diagnose(game, current_score, *, target=45000, clear_limit=3):
    """Return three judgments with evidence. Does not select an action.

    Requires a settled live/saved board and an explicit allowed clear_limit.
    Never assumes a remaining bottle can remove an ordinary pill.
    """
    board = board_from_pool(game['ballPool'])
    if any(v not in range(-1, 10) for v in board) or resolve(board) != board:
        raise ValueError('诊断需要已经结算完合成、且格子值合法的棋盘')
    highest = int(game['maxId'])
    pill = int(game['nextId'])
    score = int(current_score)
    used = int(game.get('jingDanNum', 0))
    if not 1 <= highest <= 9 or highest < max(board) or pill not in POINTS:
        raise ValueError('最高等级或当前已知丹药无效')
    if not 0 <= used <= 3 or not 0 <= clear_limit <= 3 or score < 0 or target != 45000:
        raise ValueError('净丹露次数、丹气或目标无效')
    left = max(0, clear_limit-used)
    inventory = _inventory(board, highest)
    rows = _placements(board, pill)
    promotion = _promotion(board, highest, pill, rows, score, target)
    plans = _plans(board, highest, pill)
    conversion = _plan_report(plans)
    conversion['immediate_known_pill_merges'] = _immediate(rows, inventory['empty'])
    low_indices = {i for i, v in enumerate(board)
                   if 0 < v < inventory['natural_draw_floor']}
    rescue = set()
    rescue_actions = []
    for row in rows:
        recovered = [i for i in low_indices if not
                     0 < row['after'][i] < inventory['natural_draw_floor']]
        if recovered:
            rescue.update(recovered)
            rescue_actions.append({'pos': _positions([row['index']])[0],
                                   'recovered_low_cells': _positions(recovered)})
    conversion['known_pill_low_rescue_actions'] = rescue_actions
    conversion['low_cells_without_any_known_pill_rescue'] = _positions(sorted(low_indices-rescue))
    base_ids = {p['id'] for p in plans}
    immediate_indices = {r['index'] for r in rows if r['merge_levels']}
    clears = []
    if left and inventory['empty']:
        # Once the board is already full the game has ended; a spare bottle
        # cannot retroactively revive it.
        for i, value in enumerate(board):
            if value != -1:
                continue
            after = board[:i]+(0,)+board[i+1:]
            after_plans = _plans(after, highest, pill)
            followups = _placements(after, pill)  # Same known pill after clear.
            new_moves = [r for r in followups if r['merge_levels']
                         and r['index'] not in immediate_indices]
            clears.append({'pos': _positions([i])[0], 'known_pill_preserved': pill,
                           'empty_after_clear': after.count(0),
                           'new_compatible_plan_ids': [p['id'] for p in after_plans if p['id'] not in base_ids],
                           'new_immediate_merge_followups': _immediate(new_moves, inventory['empty']),
                           'note': '额外腾空/连锁仍可能被后续随机药渣影响。'})
    conversion.update(clear_actions=clears, bottles_left=left,
                      bottles_usable_now=bool(clears),
                      actual_clearable_slag_count=min(left, inventory['slag_count']) if inventory['empty'] else 0)
    gap = max(0, target-score)
    empty = inventory['empty']
    extra = min(left, inventory['slag_count']) if empty else 0
    slots = empty+extra
    maximum_draw_points = max(POINTS[v] for v in _support(highest))
    # Exact upper bound for the NO-MERGE scenario: highest stays unchanged,
    # current known pill counts once, all remaining draws take their maximum,
    # ignore all future residue, and spend every usable bottle on existing slag.
    optimistic = POINTS[pill]+max(0, slots-1)*maximum_draw_points if slots else 0
    must_merge = gap > optimistic
    cutoff_risks = [p for p in promotion['promoting_placements']
                    if p['newly_without_natural_supply_count'] > 0]
    known_finishes = bool(empty and POINTS[pill] >= gap and gap)
    forced_failure = bool(gap and (not empty or
        (empty == 1 and not clears and POINTS[pill] < gap and
         not conversion['immediate_known_pill_merges'])))
    flags = []
    if cutoff_risks:
        flags.append('promotion_may_retire_low_pills')
    if must_merge:
        flags.append('merges_required_even_with_best_draws')
    if not clears and left:
        flags.append('remaining_bottles_not_usable_now')
    if gap == 0:
        name = 'target_met'
    elif forced_failure:
        name = 'forced_full_board_failure'
    elif known_finishes:
        name = 'known_pill_finishes'
    elif cutoff_risks and promotion['nonpromotion_possible_now']:
        name = 'promotion_cleanup_review'
    elif must_merge:
        name = 'merge_turnover_required'
    else:
        name = 'finish_capacity_review'
    stage = {'name': name, 'flags': flags, 'score_gap': gap,
             'known_pill_points': POINTS[pill],
             'known_pill_finishes': known_finishes,
             'forced_full_board_failure': forced_failure,
             'no_merge_optimistic_capacity_points': optimistic,
             'no_merge_capacity_includes_existing_slag_clears': extra,
             'merges_required_even_with_best_draws': must_merge,
             'capacity_sufficiency_is_not_guaranteed': bool(gap and not known_finishes and not must_merge),
             'capacity_assumptions': ['no_future_merges', 'best_possible_natural_draws',
                                      'no_future_residue', 'all_usable_bottles_clear_existing_slag'],
             'time_remaining_ms_as_supplied': game.get('ut'),
             'note': '阶段按当前局面判断，不按固定步数；容量上界足够不等于实际能达标。'}
    return {'version': VERSION, 'config_version': CONFIG_SOURCE['version'],
            'mode': 'diagnosis_only_no_action_selection', 'step': game.get('step'),
            'score': score, 'known_pill': pill, 'promotion': promotion,
            'conversion': conversion, 'stage': stage,
            'limitations': ['不预测未知来药或药渣具体位置', '不保证等待升阶一定更好',
                            '兼容线和不相交见证均不是全局最优解', '不估算网络或计算耗时达标率']}


def diagnose_frame(frame):
    return diagnose(frame['game'], frame['score'])
