"""九转炼丹实验选点器；先校验规则，尚未验证45000达标率。无网络或付费逻辑。"""
STABILITY_VERIFIED = False
STRATEGY_VERSION = 'goal_adaptive_experimental'
VALIDATION_NOTE = '实验：低阶收尾按真实三连位置和连锁结算；尚未完成本版本验证。'

from functools import lru_cache
from math import sqrt
BLOCKED={'00','01','04','05','10','15','50','55','60','61','64','65'}
CELLS=tuple((x,y) for y in range(7) for x in range(6) if str(y)+str(x) not in BLOCKED)
INDEX={p:i for i,p in enumerate(CELLS)}
CONFIG_SOURCE={'version': 'cg1_20261026_1', 'url': 'https://sda.4399.com/4399swf/upload_swf/ftp15/csya/20150127/1/assets/data/cg1_20261026_1.swf', 'sha256': 'e7e2389a76b254f4bfaf14bd83290d65e14d16bcda29d384036001f5790c4f6c'}
CONFIG_RULES={'id': '1', 'activityId': '1450', 'jiFen': '0;5000;10000;20000;45000', 'itemId': '105200006', 'itemNum': '24;28;32;36;40', 'ticket': '300', 'jingDanNum': '3', 'time': '300', 'dailyCountMax': '1', 'step': '0;30;50;80', 'stepProbability': '0;0.03;0.06;0.12', 'lengthWidth': '7;6', 'Column12': {}}
CONFIG_PILLS=[{'id': '1', 'score': '1', 'nextLv': '1', 'lvProbability': '1', 'itemProbability': '0'}, {'id': '2', 'score': '3', 'nextLv': '1;2', 'lvProbability': '1;1', 'itemProbability': '0'}, {'id': '3', 'score': '9', 'nextLv': '1;2;3', 'lvProbability': '1;3;2', 'itemProbability': '0'}, {'id': '4', 'score': '27', 'nextLv': '2;3;4', 'lvProbability': '1;3;2', 'itemProbability': '0.05'}, {'id': '5', 'score': '81', 'nextLv': '3;4;5', 'lvProbability': '1;3;2', 'itemProbability': '0.05'}, {'id': '6', 'score': '243', 'nextLv': '3;4;5;6', 'lvProbability': '1;3;3;2', 'itemProbability': '0.1'}, {'id': '7', 'score': '729', 'nextLv': '4;5;6;7', 'lvProbability': '1;3;3;2', 'itemProbability': '0.15'}, {'id': '8', 'score': '2187', 'nextLv': '5;6;7;8', 'lvProbability': '1;3;3;2', 'itemProbability': '0.15'}, {'id': '9', 'score': '6561', 'nextLv': '5;6;7;8', 'lvProbability': '1;1;3;3', 'itemProbability': '0.2'}]
POINTS={int(r['id']):int(r['score']) for r in CONFIG_PILLS}
DISTRIBUTIONS={int(r['id']):tuple(zip(map(int,r['nextLv'].split(';')),map(int,r['lvProbability'].split(';')))) for r in CONFIG_PILLS}
ITEM_PROBABILITIES={int(r['id']):float(r['itemProbability']) for r in CONFIG_PILLS}
STEP_THRESHOLDS=tuple(map(int,CONFIG_RULES['step'].split(';')))
STEP_PROBABILITIES=tuple(map(float,CONFIG_RULES['stepProbability'].split(';')))
TARGET_SCORE=max(map(int,CONFIG_RULES['jiFen'].split(';')))
PRACTICE_CLEAR_LIMIT=int(CONFIG_RULES['jingDanNum'])
GAME_SECONDS=int(CONFIG_RULES['time'])
EXPECTED_POINTS={hi:sum(POINTS[v]*w for v,w in dist)/sum(w for _,w in dist) for hi,dist in DISTRIBUTIONS.items()}
def step_probability(step):
 for threshold,p in reversed(tuple(zip(STEP_THRESHOLDS,STEP_PROBABILITIES))):
  if step>=threshold:return p
 return 0.
@lru_cache(maxsize=8000)
def expected_step_residue(step,placements):
 first=int(step)+1;last=int(step)+int(placements);total=0.
 for i,(threshold,p) in enumerate(zip(STEP_THRESHOLDS,STEP_PROBABILITIES)):
  end=STEP_THRESHOLDS[i+1]-1 if i+1<len(STEP_THRESHOLDS) else last
  total+=max(0,min(last,end)-max(first,threshold)+1)*p
 return total

LINES=[]
for vertical in (True,False):
 for fixed in range(6 if vertical else 7):
  run=[]
  for moving in range(7 if vertical else 6):
   pos=(fixed,moving) if vertical else (moving,fixed)
   if pos in INDEX:run.append(INDEX[pos])
   else:
    if len(run)>=3:LINES.append(tuple(run))
    run=[]
  if len(run)>=3:LINES.append(tuple(run))
LINES=tuple(LINES)
TRIPLES=tuple(line[i:i+3] for line in LINES for i in range(len(line)-2))
CELL_TRIPLES=tuple(tuple(t for t in TRIPLES if i in t) for i in range(len(CELLS)))
CELL_DEGREE=tuple(map(len,CELL_TRIPLES))
def board_from_pool(pool):
 if not isinstance(pool,list):raise ValueError('缺少服务器棋盘')
 result=[]
 for x,y in CELLS:
  row=pool[y] if y<len(pool) else []
  if not isinstance(row,list):raise ValueError('棋盘行格式异常')
  value=row[x] if x<len(row) else None
  result.append(int(value) if value is not None else 0)
 return tuple(result)
ORDERED_TRIPLES=tuple(sorted(TRIPLES,key=lambda t:(t[0],0 if CELLS[t[0]][0]==CELLS[t[1]][0] else 1)))

def resolve(board):
 board=list(board)
 for _ in range(60):
  for triple in ORDERED_TRIPLES:
   value=board[triple[0]]
   if 0<value<9 and all(board[i]==value for i in triple):
    for i in triple:board[i]=0
    board[triple[0]]=value+1
    break
  else:return tuple(board)
 raise RuntimeError('连锁超出上限')

def simulate(board,pos,piece):
 if board[pos]!=0:raise ValueError('落点非空')
 new=list(board);new[pos]=int(piece)
 return resolve(new)
BLOCK_PENALTY=80
@lru_cache(maxsize=20000)
def evaluate(board):
 highest=max(1,max(board,default=1));empty=board.count(0)
 minimum=min(v for v,_ in DISTRIBUTIONS[min(9,highest)])
 stranded=sum(0<v<minimum for v in board)
 value=200*highest**2+empty*160-sum(v<0 for v in board)*150-stranded*1000+sum(sqrt(POINTS.get(v,0))*1.5 for v in board)
 opportunities=[];reachable=set()
 dist=DISTRIBUTIONS[min(9,highest)];total=sum(w for _,w in dist);probability={v:w/total for v,w in dist};peak=max(probability.values())
 for triple in TRIPLES:
  positive=[board[i] for i in triple if board[i]>0]
  if not positive or any(board[i]<0 for i in triple):continue
  level=positive[0]
  if level>=9 or level not in probability or any(v!=level for v in positive):continue
  reachable.update(i for i in triple if board[i]>0)
  if len(positive)==2:
   opportunities.append((sqrt(POINTS[level])*8*sqrt(probability[level]/peak),sum(1<<i for i in triple)))
  elif len(positive)==1:
   opportunities.append((sqrt(POINTS[level])*.6*sqrt(probability[level]/peak),sum(1<<i for i in triple)))
 # Each tile and empty cell can contribute to at most one scored plan.
 occupied=0
 for benefit,mask in sorted(opportunities,reverse=True):
  if not occupied&mask:value+=benefit;occupied|=mask
 value-=BLOCK_PENALTY*sum(minimum<=v<9 and i not in reachable for i,v in enumerate(board))
 value-=board.count(9)*80
 value-=sum(12*CELL_DEGREE[i] for i,v in enumerate(board) if v==9)
 if empty<7:value-=(7-empty)**2*150
 return value


def explain_random_events(predicted, actual, logs):
    """Apply only server-reported random residue events; all other differences remain errors."""
    board=list(predicted)
    for event in logs or []:
        failed=event.get('failed')
        if isinstance(failed,dict):
            pos=(int(failed['x']),int(failed['y']))
            if pos not in INDEX:return False
            board[INDEX[pos]]=-1
    return tuple(board)==tuple(actual)


@lru_cache(maxsize=60000)
def finish_without_merges(gap_units,slots,tick,highest):
 """Configured step-channel scenario: reach the goal before space runs out, with no future merges or clears."""
 if gap_units<=0:return 1.
 if slots<=0:return 0.
 tick=min(80,tick)
 dist=DISTRIBUTIONS[highest];total=sum(w for _,w in dist)
 if gap_units>slots*max(POINTS[p]//81 for p,_ in dist):return 0.
 q=step_probability(tick+1);answer=0.
 for p,w in dist:
  rest=gap_units-POINTS[p]//81
  if rest<=0:chance=1.
  else:
   chance=(1-q)*finish_without_merges(rest,slots-1,min(80,tick+1),highest)+q*finish_without_merges(rest,slots-2,min(80,tick+1),highest)
  answer+=w*chance/total
 return answer


# Reward probability of usable future merges, instead of penalizing every shared line.
MOBILITY_WEIGHTS={'immediate':400.,'backup':100.,'two_move':120.}
@lru_cache(maxsize=24000)
def mobility_features(b):
 maximum=max(1,max(b));dist=DISTRIBUTIONS[maximum];total=sum(w for _,w in dist)
 probabilities={v:w/total for v,w in dist};pairs={};singles={}
 for t in TRIPLES:
  vals=[b[i] for i in t]
  if any(v<0 or v==9 for v in vals):continue
  positive=[v for v in vals if v>0];empty=[i for i in t if b[i]==0]
  if not positive or len(set(positive))!=1:continue
  level=positive[0]
  if level not in probabilities:continue
  if len(positive)==2:pairs.setdefault(level,set()).update(empty)
  elif len(positive)==1:singles.setdefault(level,set()).add(tuple(empty))
 immediate=sum(probabilities[v] for v in pairs)
 backup=sum(probabilities[v]*min(2,max(0,len(cells)-1))/2 for v,cells in pairs.items())
 # Completing a single-pill lane needs two draws of its level; cap overlapping duplicates.
 two_move=sum(probabilities[v]**2 for v in singles if v not in pairs)
 return immediate,backup,two_move

def mobility_value(b):
 f=mobility_features(b);w=MOBILITY_WEIGHTS
 return w['immediate']*f[0]+w['backup']*f[1]+w['two_move']*f[2]


# Additional permanent-space cost; calibrated only by explicit regression, not a hard upgrade ban.
CLEANUP_WEIGHT=600.
@lru_cache(maxsize=24000)
def cleanup_features(b,maximum):
 """Retired occupancy after actual, fixed-position triples and their chains.

 No arithmetic carry can relocate pills. After real merges settle, future
 draws cannot supply levels below the configured minimum, and clears only
 remove residue. The remaining retired pills therefore cannot be recovered.
 """
 projected=resolve(b)
 maximum=max(int(maximum),max(projected,default=1))
 minimum=min(level for level,weight in DISTRIBUTIONS[maximum])
 details=tuple((level,projected.count(level)) for level in range(1,minimum))
 return sum(count for level,count in details),details

# Separate ablation switches; no network or account logic in this module.
POLICY={'cashout':True,'resource':True,'delay':True}
CASHOUT_WEIGHT=90.
BOTTLE_HAZARD_WEIGHT=130.
WORK_WEIGHT=20.
def remaining_work(gap,maximum):
 # Optimistic progression proxy, NOT a fitted server timing/probability model.
 optimistic=ceil(max(0,gap)/EXPECTED_POINTS[9])+6*max(0,9-maximum)
 direct=ceil(max(0,gap)/EXPECTED_POINTS[maximum])
 return min(100,max(1,min(direct,optimistic)))

def state_policy(board,piece,maximum,bottles,step,gap):
 """Observable root state only; no seed, replay outcome, or unknown next draw."""
 work=remaining_work(gap,maximum)
 hazard=expected_step_residue(step,work)
 reserve=board.count(0)+.65*bottles-hazard
 pressure=max(0.,min(1.,(10.-reserve)/8.))
 known_merge=any(sum(board[i]==piece for i in t)==2 and sum(board[i]==0 for i in t)==1 for t in TRIPLES) if piece<9 else False
 cash=pressure if known_merge else 0.
 # Ramp the low-stage work cost only once the configured step hazard starts.
 delay_pressure=pressure*max(0.,min(1.,(step-30.)/30.)) if maximum<8 else 0.
 finish=gap<=2*EXPECTED_POINTS[maximum]
 mode='finish' if finish else 'space_recovery' if cash>.25 else 'cleanup' if maximum<8 else 'resource_preservation'
 return {'mode':mode,'pressure':pressure,'known_merge':known_merge,'reserve':reserve,
         'policy':{'cashout':cash>0.,'resource':True,'delay':delay_pressure>0.},
         'weights':{'cashout':CASHOUT_WEIGHT*cash,'resource':BOTTLE_HAZARD_WEIGHT,
                    'delay':WORK_WEIGHT*delay_pressure,'opportunity_scale':1.-.65*cash}}

import time
from math import ceil,log1p

class SearchBudgetExceeded(Exception):pass

def choose(game,target=TARGET_SCORE,current_score=0,lookahead=True,allow_clear=False,clear_limit=None,max_depth=3,time_budget=1.8,risk_mode='step_only',risk_aversion=1.,root_keys=None,protect_merges=True,repeated_residue=False,policy=None,coefficients=None):
 """Plan only to the configured reward cap. Residue positions use an adverse scenario, not a measured location distribution."""
 goal=min(int(target),TARGET_SCORE)
 if int(current_score)>=goal:return None
 if risk_mode not in ('step_only','separate_channels'):raise ValueError('unknown risk scenario')
 started=time.monotonic();board=board_from_pool(game['ballPool']);piece=int(game['nextId'])
 if piece not in POINTS:raise ValueError('invalid next pill')
 hi=max(1,int(game.get('maxId',1)),max(board));used=int(game.get('jingDanNum',0));step=max(0,int(game.get('step',0)))
 if clear_limit is None:clear_limit=PRACTICE_CLEAR_LIMIT if game.get('isTest') else 0
 left=max(0,min(int(clear_limit),PRACTICE_CLEAR_LIMIT)-used) if allow_clear else 0
 need=goal-int(current_score);empty=board.count(0);slag=board.count(-1)
 pressure=max(0.,min(1.,float(risk_aversion)))
 @lru_cache(maxsize=16000)
 def material(b):return sum(POINTS.get(v,0) for v in b)
 root_material=material(board)
 auto=state_policy(board,piece,hi,left,step,need)
 active_policy=dict(auto['policy'] if policy is None else policy)
 if set(active_policy)!=set(POLICY):raise ValueError('invalid policy keys')
 active_weights=dict(auto['weights'])
 if coefficients is not None:
  if not set(coefficients).issubset(active_weights):raise ValueError('invalid coefficient keys')
  active_weights.update(coefficients)

 def score_gap(b):return need-material(b)+root_material
 @lru_cache(maxsize=22000)
 def utility(b,bottles,tick):
  gap=score_gap(b)
  if gap<=0:return 100000.  # No reward for score above the configured target.
  blanks=b.count(0)
  if blanks==0:return -100000.
  maximum=max(hi,max(b));n=min(60 if maximum>=8 else 16,ceil(gap/EXPECTED_POINTS[maximum]))
  future_residue=expected_step_residue(tick,n)
  reserve=blanks+.65*bottles-future_residue
  value=evaluate(b)+bottles*310+100.*bottles*min(1.,max(0.,gap/goal))+(active_weights['opportunity_scale'] if active_policy['cashout'] else 1.)*mobility_value(b)-CLEANUP_WEIGHT*cleanup_features(b,maximum)[0]
  work=remaining_work(gap,maximum)
  if active_policy['resource']:
   # Concave inventory value: the last bottle has the highest marginal reserve value.
   value+=active_weights['resource']*expected_step_residue(tick,work)*log1p(bottles)
  if active_policy['delay']:value-=active_weights['delay']*work
  if reserve<4:value-=(4-reserve)**2*180
  # A reachable target matters more than accumulating score or perfecting the board indefinitely.
  if maximum>=8:
   value-=min(60,n)*18
   value+=12000*finish_without_merges(ceil(gap/81),min(8,blanks),min(80,tick),maximum)
  return value
 def low_tier_tie_break(a):
  return -CELL_DEGREE[a[1]] if piece in (1,2) and a[4]=='place' else 0
 def make_result(a,value,depth,desired,nodes):
  _,pos,new,bottles,kind=a;x,y=CELLS[pos]
  result={'pos':{'x':x,'y':y},'predicted':new,'value':value,'target':goal,'remaining_score':need,'search_actions':depth,'depth_limit':desired,'nodes':nodes,'search_seconds':time.monotonic()-started,'config_version':CONFIG_SOURCE['version'],'step_probability':step_probability(step),'risk_mode':risk_mode,'stop_at_target':True,'strategy_version':STRATEGY_VERSION,'policy':dict(active_policy),'adaptive_mode':auto['mode'],'adaptive_pressure':auto['pressure'],'adaptive_weights':dict(active_weights),'low_tier_tie_break':low_tier_tie_break(a),'goal_metric':'finish_without_further_merges_step_scenario'}
  if kind=='clear':result['action']='clear'
  return result
 def actions(b,p,bottles,tick,full=False):
  places=[];clears=[]
  for pos,v in enumerate(b):
   if v==0:
    new=simulate(b,pos,p);places.append((utility(new,bottles,tick+1),pos,new,bottles,'place'))
   elif v<0 and bottles:
    new=b[:pos]+(0,)+b[pos+1:];clears.append((utility(new,bottles-1,tick+1),pos,new,bottles-1,'clear'))
  places.sort(reverse=True);clears.sort(reverse=True)
  return places+clears if full else places[:2]+clears[:2]
 root=actions(board,piece,left,step,True)
 if not root:return None
 # The current pill's score is known: finish now, without clearing or further search.
 winners=[a for a in root if a[4]=='place' and score_gap(a[2])<=0]
 if winners:
  best=max(winners,key=lambda a:(a[2].count(0),evaluate(a[2]),-a[1]))
  return make_result(best,100000.,0,0,0)
 best=max(root,key=lambda a:(a[0],a[4]=='place',low_tier_tie_break(a),-a[1]));best_value=best[0];completed=0;nodes=0
 desired=2 if empty>=19 and hi<=5 else 3 if empty>11 and slag<4 else 4
 if empty<=6 or (slag>=7 and left):desired=5
 desired=min(desired,max(1,int(max_depth)),3)
 seconds=int(game.get('ut',GAME_SECONDS*1000))/1000
 if seconds<60:desired=min(desired,3)
 if seconds<30:desired=min(desired,2)
 if not lookahead:desired=1
 budget=min(max(0,float(time_budget)),{1:.04,2:.2,3:1.8,4:1.8,5:1.8}[desired])
 if seconds<30:budget=min(budget,.06)
 deadline=started+budget
 def check():
  nonlocal nodes
  nodes+=1
  if nodes>14000 or time.monotonic()>deadline:raise SearchBudgetExceeded
 @lru_cache(maxsize=8000)
 def adverse(b,bottles,tick):
  blanks=[i for i,v in enumerate(b) if v==0]
  if len(blanks)>8:
   def critical(i):
    score=CELL_DEGREE[i]
    for triple in CELL_TRIPLES[i]:
     others=[b[j] for j in triple if j!=i]
     if others[0]>0 and others[0]==others[1] and others[0]<9:score+=sqrt(POINTS[others[0]])*8
    return score
   blanks=sorted(blanks,key=critical,reverse=True)[:4]
  return min((b[:i]+(-1,)+b[i+1:] for i in blanks),key=lambda n:utility(n,bottles,tick)) if blanks else b
 @lru_cache(maxsize=18000)
 def search(b,p,maximum,bottles,tick,depth,stress_left):
  check()
  if score_gap(b)<=0:return 100000.
  if not b.count(0):return -100000.
  choices=actions(b,p,bottles,tick)
  if not choices:return -100000.
  return max(action_value(a,b,p,maximum,tick,depth,stress_left) for a in choices)
 def chance(b,maximum,bottles,tick,depth,stress_left):
  if score_gap(b)<=0:return 100000.
  if not b.count(0):return -100000.
  if depth<=0:return utility(b,bottles,tick)
  dist=DISTRIBUTIONS[min(9,maximum)];total=sum(w for _,w in dist)
  return sum(w*search(b,p,maximum,bottles,tick,depth,stress_left)/total for p,w in dist)
 def action_value(a,old,p,maximum,tick,depth,stress_left):
  _,pos,new,bottles,kind=a;newtick=tick+1
  if kind=='clear':
   return utility(new,bottles,newtick) if depth<=1 else search(new,p,maximum,bottles,newtick,depth-1,stress_left)
  newhi=max(maximum,max(new))
  nominal=chance(new,newhi,bottles,newtick,depth-1,stress_left)
  if score_gap(new)<=0:return 100000.
  probability=step_probability(newtick)
  if risk_mode=='separate_channels':
   # Alternative single-channel scenario only: NOT addition or an inferred server union probability.
   merge_count=(sum(v>0 for v in old)+1-sum(v>0 for v in new))//2
   if merge_count:probability=max(probability,ITEM_PROBABILITIES[newhi])
  if pressure and stress_left and probability and new.count(0):
   stressed=adverse(new,bottles,newtick)
   bad=chance(stressed,newhi,bottles,newtick,depth-1,1 if repeated_residue else 0)
   nominal-=pressure*probability*max(0,nominal-bad)
  if active_policy['cashout'] and nominal>-90000:
   recovered=max(0,new.count(0)-old.count(0)+1)
   nominal+=active_weights['cashout']*recovered
  return nominal
 places=sorted([a for a in root if a[4]=='place'],reverse=True)
 if protect_merges:
  merges=[a for a in places if a[2].count(0)>empty-1]
  chosen=merges+[a for a in places if a not in merges][:max(0,6-len(merges))]
 else:chosen=places[:6]
 roots=chosen+sorted([a for a in root if a[4]=='clear'],reverse=True)[:3]
 if root_keys is not None:roots=[a for a in roots if (a[4],a[1]) in root_keys]
 if not roots:return None
 best=max(roots,key=lambda a:(a[0],a[4]=='place',low_tier_tie_break(a),-a[1]));best_value=best[0]
 try:
  for depth in range(1,desired+1):
   round_values=[]
   for a in roots:
    check();round_values.append((action_value(a,board,piece,hi,step,depth,1),a[4]=='place',(low_tier_tie_break(a),-a[1]),a))
   check();best_value,_,_,best=max(round_values);completed=depth
 except SearchBudgetExceeded:pass
 return make_result(best,best_value,completed,desired,nodes)
