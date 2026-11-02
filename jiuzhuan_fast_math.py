"""Equivalent scalar hot-path implementations; no policy or search changes."""
from functools import lru_cache
from collections import OrderedDict
from math import sqrt

def install(g):
 triples=tuple(g.TRIPLES);ordered=tuple(g.ORDERED_TRIPLES)
 masks=tuple(sum(1<<i for i in t) for t in triples)
 sq={v:sqrt(g.POINTS.get(v,0))*1.5 for v in range(-1,10)}
 tables={}
 for hi in range(1,10):
  dist=g.DISTRIBUTIONS[hi];total=sum(w for _,w in dist);prob={v:w/total for v,w in dist};peak=max(prob.values())
  pair={v:sqrt(g.POINTS[v])*8*sqrt(prob[v]/peak) for v in prob}
  single={v:sqrt(g.POINTS[v])*.6*sqrt(prob[v]/peak) for v in prob}
  tables[hi]=(min(prob),prob,pair,single)
 resolved_cache=OrderedDict()
 def resolve(board):
  key=tuple(board)
  if key in resolved_cache:
   result=resolved_cache[key];resolved_cache.move_to_end(key);return result
  b=list(key)
  for _ in range(60):
   for a,c,d in ordered:
    v=b[a]
    if 0<v<9 and b[c]==v and b[d]==v:
     b[a]=v+1;b[c]=b[d]=0;break
   else:
    result=tuple(b);resolved_cache[key]=result;resolved_cache[result]=result
    while len(resolved_cache)>60000:resolved_cache.popitem(last=False)
    return result
  raise RuntimeError('merge loop')
 @lru_cache(maxsize=20000)
 def evaluate(b):
  highest=max(1,max(b,default=1));empty=b.count(0);minimum,prob,pair,single=tables[min(9,highest)]
  stranded=sum(0<v<minimum for v in b)
  value=200*highest**2+empty*160-sum(v<0 for v in b)*150-stranded*getattr(g,'STRANDED_WEIGHT',1000)+sum(sq[v] for v in b)
  opportunities=[];reachable=0
  for j,(a,c,d) in enumerate(triples):
   x,y,z=b[a],b[c],b[d]
   if x<0 or y<0 or z<0:continue
   level=x or y or z
   if level<=0 or level>=9 or level not in prob:continue
   if (x and x!=level) or (y and y!=level) or (z and z!=level):continue
   count=(x>0)+(y>0)+(z>0)
   if x:reachable|=1<<a
   if y:reachable|=1<<c
   if z:reachable|=1<<d
   if count==2:opportunities.append((pair[level],masks[j]))
   elif count==1:opportunities.append((single[level],masks[j]))
  occupied=0
  for benefit,mask in sorted(opportunities,reverse=True):
   if not occupied&mask:value+=benefit;occupied|=mask
  value-=g.BLOCK_PENALTY*sum(minimum<=v<9 and not (reachable&(1<<i)) for i,v in enumerate(b))
  value-=b.count(9)*80
  value-=sum(12*g.CELL_DEGREE[i] for i,v in enumerate(b) if v==9)
  if empty<7:value-=(7-empty)**2*150
  return value
 @lru_cache(maxsize=24000)
 def mobility(b):
  maximum=max(1,max(b));_,prob,_,_=tables[maximum];pairs={};singles={}
  for a,c,d in triples:
   x,y,z=b[a],b[c],b[d]
   if x<0 or y<0 or z<0 or x==9 or y==9 or z==9:continue
   level=x or y or z
   if not level or level not in prob:continue
   if (x and x!=level) or (y and y!=level) or (z and z!=level):continue
   count=(x>0)+(y>0)+(z>0)
   if count==2:
    blank=a if x==0 else c if y==0 else d
    pairs[level]=pairs.get(level,0)|(1<<blank)
   elif count==1:singles[level]=True
  immediate=sum(prob[v] for v in pairs)
  backup=sum(prob[v]*min(2,max(0,cells.bit_count()-1))/2 for v,cells in pairs.items())
  two_move=sum(prob[v]**2 for v in singles if v not in pairs)
  return immediate,backup,two_move
 g.resolve=resolve;g.evaluate=evaluate;g.mobility_features=mobility
 return g
