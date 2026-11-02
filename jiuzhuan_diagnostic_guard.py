"""Experimental action guard driven by factual diagnostics; no weight changes.

Not installed in the toolbox. Avoiding a reported risk is not a guarantee of
winning. Existing native planners choose between eligible alternatives.
"""
import time,itertools
from unittest.mock import patch
import jiuzhuan_goal_referee as published
import jiuzhuan_diagnostics as diagnostic
from jiuzhuan_recovery_value import *

STRATEGY_VERSION='diagnostic_action_guard_experimental'
STABILITY_VERIFIED=False


def eligible_alternatives(game,score,choice,report):
    """Return existing legal action keys plus a reason; no invented weighted score."""
    if choice is None or report['stage']['known_pill_finishes'] or score>=45000:
        return set(),None
    b=board_from_pool(game['ballPool']);pill=int(game['nextId']);highest=int(game['maxId'])
    i=INDEX[choice['pos']['x'],choice['pos']['y']]
    if choice.get('action')=='clear':return set(),None
    floor=min(v for v,w in DISTRIBUTIONS[highest])
    promoted=next((p for p in report['promotion']['promoting_placements'] if p['pos']==choice['pos']),None)
    keys=set()
    if promoted and promoted['newly_without_natural_supply_count']:
        lost=set(promoted['lost_natural_draw_levels'])
        for p in report['promotion']['nonpromoting_placements']:
            if p['fills_board_before_target']:continue
            j=INDEX[p['pos']['x'],p['pos']['y']]
            after,_=simulate_with_merge_levels(b,j,pill)
            plans=diagnostic._plans(after,highest,pill)
            # Wait only if an actual compatible low-tier line retains natural
            # supply before the cutoff. This is an opportunity, not a guarantee.
            if any(plan['level'] in lost and plan['natural_draw_probability_per_draw']>0 for plan in plans):
                keys.add(('place',j))
        if keys:return keys,'retain_low_cleanup_before_cutoff'
    _,levels=simulate_with_merge_levels(b,i,pill)
    if report['stage']['merges_required_even_with_best_draws'] and not levels:
        for p in report['conversion']['immediate_known_pill_merges']:
            j=INDEX[p['pos']['x'],p['pos']['y']]
            after,_=simulate_with_merge_levels(b,j,pill)
            new_highest=max(highest,max(after))
            if min(v for v,w in DISTRIBUTIONS[new_highest])<=floor:
                keys.add(('place',j))
        if keys:return keys,'realize_existing_merge_when_turnover_required'
    return set(),None


def choose(game,current_score=0,*,base=None,deterministic=False,time_budget=1.8,**kwargs):
    started=time.monotonic();base=base or published
    report=diagnostic.diagnose(game,current_score,clear_limit=kwargs.get('clear_limit',3))
    choice=base.choose(game,current_score=current_score,deterministic=deterministic,
                       time_budget=time_budget,**kwargs)
    if choice is None:return None
    keys,reason=eligible_alternatives(game,current_score,choice,report)
    replacement=None
    if keys:
        for planner in (published.old,published.new):
            budget=min(.45,max(0.,time_budget-(time.monotonic()-started)))
            args={k:v for k,v in kwargs.items() if k in ('allow_clear','clear_limit','max_depth','target')}
            if deterministic:
                clock=itertools.count(0.,1e-8)
                with patch('time.monotonic',side_effect=lambda:next(clock)):
                    alt=planner.choose(game,current_score=current_score,root_keys=keys,time_budget=.45,**args)
            else:
                alt=planner.choose(game,current_score=current_score,root_keys=keys,time_budget=budget,**args)
            if alt:
                k=(alt.get('action','place'),INDEX[alt['pos']['x'],alt['pos']['y']])
                if k not in keys:raise ValueError('restricted planner returned an ineligible action')
                replacement=alt;break
    result=dict(replacement or choice)
    result.update(strategy_version=STRATEGY_VERSION,guard_changed=replacement is not None,
                  guard_reason=reason if replacement else None,guard_considered_reason=reason,
                  guard_eligible_count=len(keys),guard_base_pos=choice['pos'],
                  guard_base_action=choice.get('action','place'),
                  diagnostic_stage=report['stage'],search_seconds=time.monotonic()-started)
    return result


def warmup(workers=3):
    return published.warmup(workers)


def shutdown(force=False):
    return published.shutdown(force=force)
