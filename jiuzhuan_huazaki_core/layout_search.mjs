import {performance} from 'node:perf_hooks';
import {DRAW_TABLE,emptyCount,score} from './rules.mjs';
import {continuations,evaluateDetailed as evaluate,boardFeatures} from './policy.mjs';

const EXPIRED=Symbol('layout search budget');
const difference=(a,b)=>Math.abs(b-a)>1e-8?b-a:0;
function compare(a,b){return difference(a.value,b.value)||a.sequence.length-b.sequence.length||a.action.index-b.action.index;}
function key(state){return `${Array.from(state.board).join(',')}|${state.nextId}|${state.maxId}|${state.step}|${state.clears}`;}
function select(candidates,width){
 const ordered=[...candidates].sort(compare);
 if(ordered.length<=width)return ordered;
 const chosen=ordered.slice(0,Math.max(1,width-2));
 // Reserve space for preparation and follow-on merges. They need not win the
 // immediate score comparison to survive the beam.
 const annotated=ordered.map(c=>({candidate:c,f:boardFeatures(c.next)}));
 for(const metric of [f=>f.chain,f=>f.patterns-.4*f.competition+.05*f.lanes]){
  const alternate=[...annotated].sort((a,b)=>metric(b.f)-metric(a.f)||compare(a.candidate,b.candidate))
   .find(a=>!chosen.includes(a.candidate));
  if(alternate&&chosen.length<width)chosen.push(alternate.candidate);
 }
 for(const c of ordered)if(chosen.length<width&&!chosen.includes(c))chosen.push(c);
 return chosen;
}

export function searchLayouts(state,models,options={}){
 const begin=performance.now(),timeMs=options.timeMs??1000;
 const deadline=begin+timeMs;
 let nodes=0,cacheHits=0;
 const checkpoint=()=>{if(performance.now()>=deadline)throw EXPIRED;};
 const rootFeatures=boardFeatures(state);
 const critical=rootFeatures.chain>0||rootFeatures.readyPairs>=2||
  (state.clears>0&&state.board.includes(-1))||rootFeatures.empties<=8;
 const targetDepth=options.targetDepth??(critical?4:3);
 const width=options.width??(critical?8:6);
 const results=[];
 for(let m=0;m<models.length;m++){
  const mergeModel=models[m];
  // Give each model time; never return a partly evaluated probability branch.
  const modelDeadline=Math.min(deadline,performance.now()+(deadline-performance.now())/(models.length-m));
  const check=()=>{checkpoint();if(performance.now()>=modelDeadline)throw EXPIRED;};
  const memo=new Map(),candidateMemo=new Map();
  function candidatesFor(node){
   const k=key(node);let c=candidateMemo.get(k);
   if(!c){c=continuations(node,{mergeModel,stepBefore:options.stepBefore,checkpoint:check,detailedEvaluation:true});candidateMemo.set(k,c);}
   return c;
  }
  function search(node,depth,root=false){
   check();nodes++;
   const k=`${depth}|${key(node)}`;
   if(memo.has(k)){cacheHits++;return memo.get(k);}
   if(!emptyCount(node.board))return {value:score(node.board)};
   const candidates=candidatesFor(node);
   let best;
   if(depth===1)best=[...candidates].sort(compare)[0];
   else{
    const selected=select(candidates,root?width:depth>=3?3:2);
    const searched=[];
    for(const c of selected){
     let future=score(c.next.board);
     if(emptyCount(c.next.board)){
      future=0;const table=DRAW_TABLE[c.next.maxId],total=table.weights.reduce((a,b)=>a+b,0);
      for(let j=0;j<table.levels.length;j++){
       future+=table.weights[j]/total*search({...c.next,nextId:table.levels[j]},depth-1).value;
      }
     }
     searched.push({...c,value:c.value+future-evaluate(c.next)});
    }
    best=searched.sort(compare)[0];
   }
   memo.set(k,best);return best;
  }
  // Guaranteed legal fallback. Each completed iteration replaces it atomically.
  const base=continuations(state,{mergeModel,stepBefore:options.stepBefore,detailedEvaluation:true}).sort(compare);
  let best=base[0],depth=1;
  try{
   for(let d=2;d<=targetDepth;d++){best=search(state,d,true);depth=d;}
  }catch(error){if(error!==EXPIRED)throw error;}
  results.push({mergeModel,...best,depth,targetDepth,width,searchedCandidates:Math.min(width,base.length)});
 }
 results.stats={elapsedMs:performance.now()-begin,nodes,cacheHits,targetDepth,width,critical,
  completedDepth:Math.min(...results.map(r=>r.depth)),spatialSlag:'expected_space_cost'};
 return results;
}
