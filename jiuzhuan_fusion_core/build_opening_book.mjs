import {writeFile,mkdir} from 'node:fs/promises';
import {performance} from 'node:perf_hooks';
import {normalizeState,serializeState,deterministicMove,DRAW_TABLE,ITEM_PROBABILITY,stepProbability} from './rules.mjs';
import {searchLayouts} from './layout_search.mjs';
import {openingKey,openingFingerprint} from './opening_book.mjs';

// Exhaust every possible next-pill draw on the helper's chosen opening route.
// Six placements precede any possible grade-4/step slag event on these paths.
const placements=6,seen=new Set(),entries=[],queue=[normalizeState({board:Array(30).fill(0),nextId:1,maxId:1,step:0,clears:3})];
const begin=performance.now();
while(queue.length){
 const state=queue.shift(),key=openingKey(state);
 if(seen.has(key)||state.step>=placements)continue;
 seen.add(key);
 const choice=searchLayouts(state,['current_max'],{timeMs:10000,targetDepth:4,width:8})[0];
 if(choice.depth<3)throw Error('Opening analysis failed to complete three placements.');
 if(choice.sequence.length!==1||choice.action.type!=='place')throw Error('Unexpected opening clear.');
 entries.push({state:serializeState(state),index:choice.action.index,depth:choice.depth});
 const move=deterministicMove(state,choice.action);
 if(stepProbability(move.state.step)||move.merges.some(m=>ITEM_PROBABILITY[m.maxId]))throw Error('Opening requires stochastic slag branches; reduce the cutoff.');
 for(const nextId of DRAW_TABLE[move.state.maxId].levels)queue.push({...move.state,nextId});
 console.log(JSON.stringify({states:entries.length,step:state.step,depth:choice.depth,pending:queue.length}));
}
const book={schema:1,placements,sourceFingerprint:openingFingerprint(),coverage:'all next-pill draws reachable under the stored helper opening policy',entries};
await writeFile(new URL('opening_book.json',import.meta.url),JSON.stringify(book));
const review=new URL('../验证记录/布局深化与开局表_20261029/',import.meta.url);await mkdir(review,{recursive:true});
await writeFile(new URL('开局表生成.json',review),JSON.stringify({placements,states:entries.length,elapsedMs:performance.now()-begin,sourceFingerprint:book.sourceFingerprint,depths:[...new Set(entries.map(e=>e.depth))],gameInputs:0},null,2));
console.log(JSON.stringify({complete:true,placements,states:entries.length,elapsedMs:performance.now()-begin}));
