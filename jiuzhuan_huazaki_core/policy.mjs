// Board-space policy and bounded chance lookahead. It never receives the
// environment RNG or a pre-generated future; only the currently visible pill.
import {TRIPLES,DRAW_TABLE,score,emptyCount,legalActions,deterministicMove,
 expectedDraw,ITEM_PROBABILITY,stepProbability} from './rules.mjs';

const MEANS=Array.from({length:10},(_,m)=>m?expectedDraw(m):0);
const TABLES=Array.from({length:10},()=>new Float64Array(1331));
for(let m=1;m<=9;m++){
 const t=DRAW_TABLE[m],total=t.weights.reduce((a,b)=>a+b,0);
 t.levels.forEach((level,j)=>{
  // A low-level merge frees the same two squares as a high-level merge.
  // Arrival frequency governs how soon the opportunity can be completed.
  const factor=Math.pow(t.weights[j]/total,.55);
  for(let mask=1;mask<7;mask++){
   const a=mask&1?level:0,b=mask&2?level:0,c=mask&4?level:0;
   const count=Number(a>0)+Number(b>0)+Number(c>0);
   TABLES[m][(a+1)*121+(b+1)*11+c+1]=(count===2?1.95:.55)*factor/count;
  }
 });
}
const potentialScratch=new Float64Array(30),flexibilityScratch=new Uint8Array(30);
const LINES=Array.from({length:30},(_,i)=>TRIPLES.filter(t=>t.includes(i)));
const incoming=Array.from({length:10},(_,m)=>new Set(DRAW_TABLE[m]?.levels??[]));
export function boardFeatures(state){
 const board=state.board,points=score(board),empties=emptyCount(board);
 const potentials=potentialScratch.fill(0),flexibility=flexibilityScratch.fill(0);
 const table=TABLES[state.maxId];let structural=0;
 const compatible=new Uint8Array(30),openLanes=new Uint8Array(30);
 const holes=new Float64Array(30),bestHole=new Float64Array(30),ready=[];
 for(const triple of TRIPLES){
  const a=board[triple[0]],b=board[triple[1]],c=board[triple[2]];
  if(a>=0&&a<9&&b>=0&&b<9&&c>=0&&c<9){structural++;for(const i of triple)openLanes[i]++;}
  const value=table[(a+1)*121+(b+1)*11+c+1];
  if(value)for(const i of triple)if(board[i]>0){potentials[i]=Math.max(potentials[i],value);flexibility[i]++;}
  // Compatibility also counts low grades no longer present in the draw table;
  // a stranded low pill with no matching line is permanent board congestion.
  let grade=0,count=0,hole=-1,ok=true;
  for(const i of triple){const v=board[i];if(v<0||v===9){ok=false;break;}
   if(!v)hole=i;else{count++;if(grade&&grade!==v){ok=false;break;}grade=v;}}
  if(ok&&grade){
   for(const i of triple)if(board[i]===grade)compatible[i]++;
   if(count===2&&hole>=0){
    const weight=incoming[state.maxId].has(grade)?1:.25;
    holes[hole]+=weight;bestHole[hole]=Math.max(bestHole[hole],weight);
    ready.push({triple,grade,hole});
   }
  }
 }
 let patterns=0,isolated=0,obsolete=0,competition=0,deadSpaces=0,lanes=0,chain=0;
 for(let i=0;i<30;i++){
  patterns+=potentials[i]+Math.min(.18,flexibility[i]*.025);
  competition+=Math.max(0,holes[i]-bestHole[i]);
  if(board[i]>0&&board[i]<9){
   if(!compatible[i])isolated++;
   if(!incoming[state.maxId].has(board[i]))obsolete+=compatible[i]?.25:1;
  }
  if(board[i]===0){if(!openLanes[i])deadSpaces++;lanes+=Math.min(4,openLanes[i]);}
 }
 for(const {triple,grade} of ready){
  if(grade>=8)continue;
  const landing=triple[0];let best=0;
  for(const line of LINES[landing]){
   let matched=0,possible=true;
   for(const i of line){if(i===landing)continue;const v=triple.includes(i)?0:board[i];
    if(v===grade+1)matched++;else if(v!==0){possible=false;break;}}
   if(possible)best=Math.max(best,matched===2?1:matched===1?.3:0);
  }
  chain+=best;
 }
 return {points,empties,patterns,structural,isolated,obsolete,competition,deadSpaces,lanes,chain,
  readyPairs:ready.length};
}
export function evaluateDetailed(state){
 const f=boardFeatures(state);
 if(!f.empties)return f.points;
 return f.points+MEANS[state.maxId]*(1.9*f.empties+2.2*state.clears+.85*f.patterns+
  .01*f.structural+.025*f.lanes+.48*f.chain-.16*f.isolated-.3*f.obsolete-
  .28*f.competition-.24*f.deadSpaces);
}
// Keep the calibrated inexpensive policy for long sampled continuations.
// Richer position features are reserved for the actual multi-ply layout search.
export function evaluate(state){
 const board=state.board,points=score(board),empties=emptyCount(board);
 if(!empties)return points;
 const potentials=potentialScratch.fill(0),flexibility=flexibilityScratch.fill(0);
 const table=TABLES[state.maxId];let structural=0;
 for(const triple of TRIPLES){
  const a=board[triple[0]],b=board[triple[1]],c=board[triple[2]];
  if(a>=0&&a<9&&b>=0&&b<9&&c>=0&&c<9)structural++;
  const value=table[(a+1)*121+(b+1)*11+c+1];
  if(value)for(const i of triple)if(board[i]>0){potentials[i]=Math.max(potentials[i],value);flexibility[i]++;}
 }
 let patterns=0;
 for(let i=0;i<30;i++)patterns+=potentials[i]+Math.min(.18,flexibility[i]*.025);
 return points+MEANS[state.maxId]*(1.9*empties+2.2*state.clears+.85*patterns+.01*structural);
}
export function placementValue(before,transition,options){
 const next=transition.state,empties=emptyCount(next.board),base=(options.detailedEvaluation?evaluateDetailed:evaluate)(next);
 if(!empties)return base;
 const points=score(next.board),stepP=stepProbability(options.stepBefore?before.step:next.step);
 const model=options.mergeModel??'current_max';let expectedSlag=stepP,lastMergeP=0;
 for(const merge of transition.merges){
  const key=model==='new_grade'?merge.level:model==='final_max'?next.maxId:merge.maxId;
  lastMergeP=ITEM_PROBABILITY[key];expectedSlag+=lastMergeP;
 }
 if(empties===1)return points+(1-stepP)*(base-points);
 const squareValue=1.9*MEANS[next.maxId];let value=base-expectedSlag*squareValue;
 if(empties===2&&transition.merges.length===1)value-=lastMergeP*stepP*(base-2*squareValue-points);
 return value;
}

// Count the slag phases that can fill this placement's remaining spaces.
// This uses the same working probabilities as randomMove, without sampling.
export function terminalRisk(before,transition,options={}){
 const empties=emptyCount(transition.state.board);
 if(!empties)return 1;
 if(empties>transition.merges.length+1)return 0;
 const models=options.models??[options.mergeModel??'current_max'];
 return Math.max(...models.map(model=>{
  const probabilities=transition.merges.map(merge=>ITEM_PROBABILITY[
   model==='new_grade'?merge.level:model==='final_max'?transition.state.maxId:merge.maxId]);
  probabilities.push(stepProbability(options.stepBefore?before.step:transition.state.step));
  let counts=[1];
  for(const p of probabilities){
   const next=Array(counts.length+1).fill(0);
   counts.forEach((mass,n)=>{next[n]+=mass*(1-p);next[n+1]+=mass*p;});
   counts=next;
  }
  return counts.slice(empties).reduce((a,b)=>a+b,0);
 }));
}

function clearPurpose(node,placement,transition,path,options){
 const clears=path.slice(0,-1);
 if(!clears.length)return {type:'none'};
 const unused=clears.filter(action=>action.index!==placement.index);
 if(!unused.length)return {type:'use_now'};
 if(emptyCount(transition.state.board)-1>transition.merges.length+1)return null;
 const after=terminalRisk(node,transition,options);
 let before=0;
 for(const clear of unused){
  // If this clear can be removed without increasing the current placement's
  // terminal risk, hold the water until the slot is actually needed.
  const board=node.board.slice();board[clear.index]=-1;
  const omitted={...node,board,step:node.step-1,clears:node.clears+1};
  const risk=terminalRisk(omitted,deterministicMove(omitted,placement),options);
  if(risk<=after+1e-12)return null;
  before=Math.max(before,risk);
 }
 return {type:'prevent_full_board',riskWithoutOneClear:before,riskAfter:after};
}

export function continuations(state,options={}){
 const candidates=[],path=[];let leaves=0;
 function visit(node,minimumClearIndex=0){
  options.checkpoint?.();
  for(const action of legalActions(node)){
   if(action.type==='clear'&&action.index<minimumClearIndex)continue;
   const transition=deterministicMove(node,action);path.push(action);
   if(action.type==='clear')visit(transition.state,action.index+1);
   else {
    const purpose=clearPurpose(node,action,transition,path,options);
    if(!purpose){path.pop();continue;}
    leaves++;const value=placementValue(node,transition,options);
    const candidate={action:path[0],sequence:[...path],next:transition.state,value,clearPurpose:purpose,
     merges:transition.merges.length};
    if(options.collect!==false||!candidates.length||compare(candidate,candidates[0])<0){
     if(options.collect===false)candidates.length=0;
     candidates.push(candidate);
    }
   }
   path.pop();
  }
 }
 visit(state);candidates.leaves=leaves;return candidates;
}
function valueDifference(a,b){const delta=b-a;return Math.abs(delta)>1e-9?delta:0;}
function compare(a,b){return valueDifference(a.value,b.value)||a.sequence.length-b.sequence.length||a.action.index-b.action.index;}
export function actionContinuation(state,random=()=>0,profile=0,options={}){
 const candidates=continuations(state,{...options,collect:(options.depth??1)>1});
 if(!candidates.length)return null;
 candidates.sort(compare);
 const depth=options.depth??1,width=options.width??4;
 if(depth>1){
  for(const c of candidates.slice(0,width)){
   const table=DRAW_TABLE[c.next.maxId],total=table.weights.reduce((a,b)=>a+b,0);
   let future=0;
   if(emptyCount(c.next.board)){
    for(let j=0;j<table.levels.length;j++){
     const continuation=actionContinuation({...c.next,nextId:table.levels[j]},random,profile,{...options,depth:depth-1});
     future+=table.weights[j]/total*(continuation?.value??score(c.next.board));
    }
   }else future=score(c.next.board);
   c.lookaheadValue=c.value+future-evaluate(c.next);
  }
  const searched=candidates.slice(0,width);
  searched.sort((a,b)=>valueDifference(a.lookaheadValue,b.lookaheadValue)||a.sequence.length-b.sequence.length||compare(a,b));
  const best=searched[0];
  return {...best,value:best.lookaheadValue,evaluatedContinuations:candidates.leaves,
    searchedCandidates:searched.length,depth};
 }
 return {...candidates[0],evaluatedContinuations:candidates.leaves,depth:1};
}
export function greedyAction(state,random=()=>0,profile=0,options={}){
 return actionContinuation(state,random,profile,options)?.action??null;
}
export function strategicChoices(state,models,options={}){
 return models.map(mergeModel=>({mergeModel,...actionContinuation(state,()=>0,0,
  {...options,mergeModel,depth:2,width:4})}));
}

// Keep one complete clear(s)-then-placement plan per legal first action.
// This preserves the existing root budget while making rollout and execution
// evaluate the same continuation instead of changing plans after each clear.
export function rootContinuations(state,models,strategic,options={}){
 const candidates=continuations(state,{...options,models}).sort(compare),chosen=new Map();
 const key=action=>`${action.type}:${action.index}`;
 for(const candidate of candidates)if(!chosen.has(key(candidate.action)))chosen.set(key(candidate.action),candidate);
 for(const actionKey of new Set(strategic.map(c=>key(c.action)))){
  const votes=new Map();
  for(const candidate of strategic.filter(c=>key(c.action)===actionKey)){
   const sequenceKey=JSON.stringify(candidate.sequence),entry=votes.get(sequenceKey);
   if(entry)entry.votes++;else votes.set(sequenceKey,{candidate,votes:1});
  }
  const winner=[...votes.values()].sort((a,b)=>b.votes-a.votes||compare(a.candidate,b.candidate))[0];
  chosen.set(actionKey,winner.candidate);
 }
 return legalActions(state).map(action=>chosen.get(key(action)));
}
