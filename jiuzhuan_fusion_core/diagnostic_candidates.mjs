// Factual diagnostics derived from our read-only module. No scoring weights,
// hidden RNG, hard action vetoes or new early/late step thresholds.
import {DRAW_TABLE,VALUES,TRIPLES,emptyCount,score} from './rules.mjs';

const floor=max=>Math.min(...DRAW_TABLE[max].levels);
const key=action=>`${action.type}:${action.index}`;
function retainsLowLine(state,lost){
  return TRIPLES.some(t=>{
    const occupied=t.filter(i=>state.board[i]>0);
    if(!occupied.length||t.some(i=>state.board[i]<0||state.board[i]===9))return false;
    const grade=state.board[occupied[0]];
    return lost.has(grade)&&occupied.every(i=>state.board[i]===grade)&&t.some(i=>state.board[i]===0);
  });
}

export function diagnosticProtection(state,macros,anchorKey){
  const beforeFloor=floor(state.maxId),empties=emptyCount(state.board);
  const slag=Array.from(state.board).filter(v=>v===-1).length;
  const slots=empties+(empties?Math.min(state.clears,slag):0);
  const optimistic=slots?VALUES[state.nextId]+Math.max(0,slots-1)*Math.max(...DRAW_TABLE[state.maxId].levels.map(v=>VALUES[v])):0;
  const gap=Math.max(0,45000-score(state.board));
  const mustMerge=gap>optimistic;
  const anchor=macros.find(m=>key(m.action)===anchorKey);
  const protectedCandidates=[];
  let newlyRetired=[];
  if(anchor){
    const afterFloor=floor(anchor.next.maxId);
    newlyRetired=Array.from(anchor.next.board).flatMap((v,i)=>v>0&&v>=beforeFloor&&v<afterFloor?[i]:[]);
    if(newlyRetired.length){
      const lost=new Set(DRAW_TABLE[state.maxId].levels.filter(v=>!DRAW_TABLE[anchor.next.maxId].levels.includes(v)));
      const candidates=macros.filter(m=>key(m.action)!==anchorKey&&emptyCount(m.next.board)>0&&
        floor(m.next.maxId)===beforeFloor&&retainsLowLine(m.next,lost));
      candidates.sort((a,b)=>b.value-a.value||a.sequence.length-b.sequence.length||a.action.index-b.action.index);
      if(candidates.length)protectedCandidates.push({key:key(candidates[0].action),reason:'retain_low_cleanup_opportunity'});
    }
    if(mustMerge&&!anchor.merges){
      const candidates=macros.filter(m=>key(m.action)!==anchorKey&&m.merges>0&&floor(m.next.maxId)===beforeFloor);
      candidates.sort((a,b)=>b.value-a.value||a.sequence.length-b.sequence.length||a.action.index-b.action.index);
      if(candidates.length&&!protectedCandidates.some(p=>p.key===key(candidates[0].action)))
        protectedCandidates.push({key:key(candidates[0].action),reason:'realize_existing_turnover'});
    }
  }
  return {newlyRetiredIndices:newlyRetired,mustMerge,optimisticNoMergePoints:optimistic,
    protectedCandidates,hardVeto:false,extraEvaluationWeights:false,
    note:'Protection only; waiting or merging is not forced and does not guarantee winning.'};
}
