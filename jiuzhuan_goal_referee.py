"""Goal-only common-random-number referee. Local research prototype."""
import time,random,hashlib,math,atexit,itertools
from unittest.mock import patch
from concurrent.futures import ProcessPoolExecutor,wait
import jiuzhuan_pressure_aligned as old
import jiuzhuan_recovery_value as new
from jiuzhuan_fast_math import install
install(old);install(new)
from jiuzhuan_recovery_value import *
STRATEGY_VERSION='goal_common_referee_experimental'
STABILITY_VERIFIED=False
_POOL=None

def _warm(x):return x

def enable_parallel(workers=3):
 global _POOL
 if _POOL is None:
  _POOL=ProcessPoolExecutor(max_workers=max(1,min(4,int(workers))))
  list(_POOL.map(_warm,range(max(1,min(4,int(workers))))))

def shutdown(force=False):
 global _POOL
 if _POOL is None:return
 pool=_POOL;_POOL=None
 if force:
  for proc in tuple((getattr(pool,'_processes',None) or {}).values()):
   if proc.is_alive():proc.terminate()
 pool.shutdown(wait=not force,cancel_futures=True)

atexit.register(shutdown)
warmup=enable_parallel

def _fast_action(b,p,hi,left,step,score,style):
 places=[];clears=[];gap=TARGET_SCORE-score
 def value(board,bottles,recovered):
  if not board.count(0):return -1e9
  minimum=min(v for v,w in DISTRIBUTIONS[max(hi,max(board))])
  stranded=sum(0<v<minimum for v in board)
  # Both root candidates use this same continuation policy, not their own score.
  v=new.evaluate(board)-220*stranded+bottles*(180+170*min(1.,gap/TARGET_SCORE))
  v+=(110 if style==0 else 55)*recovered
  if style:v+=.35*new.mobility_value(board)
  return v
 for i,v in enumerate(b):
  if v==0:
   after=new.simulate(b,i,p)
   if POINTS[p]>=gap:return ('place',i,after)
   recovered=max(0,after.count(0)-b.count(0)+1)
   places.append((value(after,left,recovered),-i,('place',i,after)))
  elif v<0 and left:
   after=b[:i]+(0,)+b[i+1:]
   clears.append((value(after,left-1,0),-i,('clear',i,after)))
 if not places and not clears:return None
 return max(places+clears,key=lambda x:(x[0],x[2][0]=='place',x[1]))[2]

def _draw(hi,u):
 dist=DISTRIBUTIONS[hi];total=sum(w for _,w in dist);threshold=u*total
 for p,w in dist:
  threshold-=w
  if threshold<0:return p
 return dist[-1][0]

def _rollout(state,first,sample_seed,horizon,style,deadline):
 b,p,hi,left,step,score=state
 rng=random.Random(sample_seed)
 # Fixed per-placement/channel coordinates keep step and merge draws aligned
 # even when one candidate clears or makes a different number of merges.
 tape=[tuple(rng.random() for _ in range(19)) for _ in range(horizon)]
 placements=0;actions=0;action=first
 while actions<horizon+3:
  if deadline is not None and time.monotonic()>deadline:return None
  if score>=TARGET_SCORE:return (True,actions,False)
  if not b.count(0):return (False,actions,False)
  if action is None:action=_fast_action(b,p,hi,left,step,score,style)
  if action is None:return (False,actions,False)
  kind,i,predicted=action;action=None;actions+=1;step+=1
  if kind=='clear':
   if left<=0 or b[i]>=0:raise ValueError('illegal rollout clear')
   b=b[:i]+(0,)+b[i+1:];left-=1;continue
  if placements>=horizon:return (False,actions,True)
  if b[i]!=0:raise ValueError('illegal rollout placement')
  b,levels=new.simulate_with_merge_levels(b,i,p);score+=POINTS[p]
  if score>=TARGET_SCORE:return (True,actions,False)
  row=tape[placements];placements+=1
  probs=[step_probability(step)]+[ITEM_PROBABILITIES[level] for level in levels]
  if len(probs)>9:raise ValueError('unexpected merge chain length')
  for channel,probability in enumerate(probs):
   if row[1+channel]<probability:
    empty=[j for j,v in enumerate(b) if v==0]
    if empty:
     j=empty[min(len(empty)-1,int(row[10+channel]*len(empty)))];b=b[:j]+(-1,)+b[j+1:]
  if not b.count(0):return (False,actions,False)
  hi=max(hi,max(b));p=_draw(hi,row[0])
 return (score>=TARGET_SCORE,actions,True)

def _compare_sample(payload):
 state,candidates,seed,horizon,style,deadline=payload
 results=[]
 for action in candidates:
  outcome=_rollout(state,action,seed,horizon,style,deadline)
  if outcome is None:return None
  results.append(outcome)
 return results

def choose(game,target=TARGET_SCORE,current_score=0,allow_clear=False,clear_limit=None,max_depth=3,time_budget=1.8,samples=16,horizon=120,deterministic=False,**kwargs):
 started=time.monotonic();deadline=None if deterministic else started+max(0.,float(time_budget))
 goal=min(int(target),TARGET_SCORE)
 if goal!=TARGET_SCORE:raise ValueError('referee prototype evaluates the 45000 reward target only')
 if current_score>=goal:return None
 b=new.board_from_pool(game['ballPool']);p=int(game['nextId']);hi=max(1,int(game.get('maxId',1)),max(b));step=int(game.get('step',0))
 limit=(PRACTICE_CLEAR_LIMIT if game.get('isTest') else 0) if clear_limit is None else min(PRACTICE_CLEAR_LIMIT,int(clear_limit))
 left=max(0,limit-int(game.get('jingDanNum',0))) if allow_clear else 0
 if not b.count(0):return None
 native_kwargs={'target':goal,'current_score':current_score,'allow_clear':allow_clear,'clear_limit':clear_limit,'max_depth':max_depth,'time_budget':min(.45,max(0.,float(time_budget))/3)}
 def native_choice(model):
  if not deterministic:return model.choose(game,**native_kwargs)
  clock=itertools.count(0.,1e-8)
  with patch('time.monotonic',side_effect=lambda:next(clock)):return model.choose(game,**native_kwargs)
 fallback=native_choice(new)
 if fallback is None:return None
 if POINTS[p]>=goal-current_score:
  result=dict(fallback);result.update(strategy_version=STRATEGY_VERSION,referee_status='known_pill_finishes',search_seconds=time.monotonic()-started);return result
 old_choice=native_choice(old)
 candidates=[];keys=[];labels=[];native=[]
 def add(ch,label):
  if ch is None:return
  kind=ch.get('action','place');i=INDEX[ch['pos']['x'],ch['pos']['y']];key=(kind,i)
  if key in keys:labels[keys.index(key)].append(label);return
  predicted=tuple(ch['predicted']);expected=new.simulate(b,i,p) if kind=='place' else b[:i]+(0,)+b[i+1:]
  if predicted!=expected:raise ValueError('candidate physics mismatch')
  candidates.append((kind,i,predicted));keys.append(key);labels.append([label]);native.append(ch)
 add(fallback,'recovery');add(old_choice,'previous')
 merges=[]
 for i,v in enumerate(b):
  if v==0:
   after=new.simulate(b,i,p)
   if after.count(0)>b.count(0)-1:merges.append((after.count(0),new.evaluate(after),-i,i,after))
 if merges:
  _,_,_,i,after=max(merges)
  add({'pos':{'x':CELLS[i][0],'y':CELLS[i][1]},'predicted':after},'immediate_space')
 if len(candidates)==1:
  result=dict(fallback);result.update(strategy_version=STRATEGY_VERSION,referee_status='candidates_agree',candidate_sources=labels,search_seconds=time.monotonic()-started);return result
 state=(b,p,hi,left,step,int(current_score))
 # Does not inspect the real test seed or the environment's random generator.
 fingerprint=repr((b,p,hi,left,step,int(current_score))).encode();base=int.from_bytes(hashlib.blake2b(fingerprint,digest_size=8).digest(),'little')
 requested=max(2,min(32,int(samples)));horizon=max(16,min(200,int(horizon)));results=[]
 payloads=[(state,candidates,base+7919*j,horizon,j%2,deadline) for j in range(requested)]
 if _POOL is None:
  for payload in payloads:
   if deadline is not None and time.monotonic()>=deadline:break
   result=_compare_sample(payload)
   if result is None:break
   results.append(result)
 else:
  futures=[_POOL.submit(_compare_sample,payload) for payload in payloads]
  timeout=None if deadline is None else max(0.,deadline-time.monotonic())+.02
  done,pending=wait(futures,timeout=timeout)
  # Keep sample identity/order: a candidate is never scored on a different subset.
  for future in futures:
   if future in done:
    result=future.result()
    if result is not None:results.append(result)
  if pending:
   for future in pending:future.cancel()
   shutdown(force=True)
 n=len(results);wins=[sum(sample[i][0] for sample in results) for i in range(len(candidates))];best=max(range(len(candidates)),key=lambda i:(wins[i],-i));selected=0
 paired_net=0
 if n>=8 and best!=0:
  paired_net=sum(int(sample[best][0])-int(sample[0][0]) for sample in results)
  if paired_net>=2:selected=best
 kind,i,predicted=candidates[selected];result=dict(native[selected])
 result.update(pos={'x':CELLS[i][0],'y':CELLS[i][1]},predicted=predicted,target=goal,remaining_score=goal-current_score,strategy_version=STRATEGY_VERSION,config_version=CONFIG_SOURCE['version'],search_seconds=time.monotonic()-started,referee_status='selected_by_common_rollouts' if selected else 'inconclusive_or_baseline_best',referee_samples=n,candidate_sources=labels,candidate_wins=wins,native_value=native[selected].get('value'),value=(wins[selected]/n if n else None),paired_net_wins=paired_net,selected_candidate=selected,rollout_horizon=horizon,censored_counts=[sum(sample[j][2] for sample in results) for j in range(len(candidates))],goal_metric='sampled_goal_completion_common_continuation')
 if kind=='clear':result['action']='clear'
 else:result.pop('action',None)
 return result
