import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {describeAction,serializeState,score,emptyCount} from './rules.mjs';

export function openingKey(state){return `${state.step}|${state.maxId}|${state.clears}|${state.nextId}|${Array.from(state.board).join(',')}`;}
export function openingFingerprint(){
 const hash=createHash('sha256');
 for(const name of ['rules.mjs','policy.mjs','layout_search.mjs'])hash.update(readFileSync(new URL(name,import.meta.url)));
 return hash.digest('hex');
}
let book=null,entries=new Map();
try{
 const data=JSON.parse(readFileSync(new URL('opening_book.json',import.meta.url),'utf8'));
 if(data.schema===1&&data.sourceFingerprint===openingFingerprint()){
  book=data;entries=new Map(data.entries.map(entry=>[openingKey(entry.state),entry]));
 }
}catch(error){if(error.code!=='ENOENT'&&!(error instanceof SyntaxError))throw error;}

export function lookupOpening(state){
 if(!book||state.step>=book.placements||state.clears!==3)return null;
 const entry=entries.get(openingKey(state));
 if(!entry||state.board[entry.index]!==0)return null;
 const action={type:'place',index:entry.index};
 return {status:'ready',algorithm:'enumerated_opening_book',strategyVersion:'2.0',
  strategyRevision:'layout_depth_opening',objective:'expected_final_score',
  state:serializeState(state),score:score(state.board),emptyCells:emptyCount(state.board),
  recommendation:describeAction(action),sequence:[action],clearPurpose:{type:'none'},
  recommendationReason:'built_in_opening',ranking:[],rounds:0,totalRollouts:0,
  sampleRange:[0,0],elapsedMs:0,bookHit:true,bookPlacements:book.placements,
  bookStates:entries.size,precomputedDepth:entry.depth,
  limits:['内置助手开局路线可达状态；表外局面恢复搜索。','内置走法由有限搜索预计算，未证明全局最优。']};
}
