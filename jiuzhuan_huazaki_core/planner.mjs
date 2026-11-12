import {performance} from 'node:perf_hooks';
import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import readline from 'node:readline';
import {
  CELLS, TRIPLES, VALUES, DRAW_TABLE, normalizeState, serializeState, score,
  emptyCount, legalActions, describeAction, deterministicMove, randomMove,
  expectedDraw, ITEM_PROBABILITY, stepProbability,
} from './rules.mjs';

export function seededRandom(seed) {
  let value = seed >>> 0;
  return () => {
    value += 0x6D2B79F5;
    let t = Math.imul(value ^ value >>> 15, 1 | value);
    t ^= t + Math.imul(t ^ t >>> 7, 61 | t);
    return ((t ^ t >>> 14) >>> 0) / 4294967296;
  };
}

import {evaluate, actionContinuation, greedyAction, strategicChoices, rootContinuations} from './policy.mjs';
import {searchLayouts} from './layout_search.mjs';
import {lookupOpening} from './opening_book.mjs';
export {evaluate, actionContinuation, greedyAction};

export function rollout(initial, firstAction, seed, mergeModel, options = {}) {
  const random = seededRandom(seed);
  const profile = options.profile ?? (seed % 3);
  const horizon = options.horizon ?? 240;
  let state=initial,moves=0,clearActions=0,clearsWithMoreThanTwoEmpties=0;
  function apply(sequence){
    for(const action of sequence){
      if(action.type==='clear'){
        clearActions++;
        if(emptyCount(state.board)>2)clearsWithMoreThanTwoEmpties++;
      }
      state=randomMove(state,action,random,{mergeModel,stepBefore:options.stepBefore});
      moves++;
    }
  }
  apply(Array.isArray(firstAction)?firstAction:[firstAction]);
  while (emptyCount(state.board) && moves < horizon) {
    const continuation=actionContinuation(state,random,profile,{mergeModel,stepBefore:options.stepBefore});
    if(!continuation)break;
    apply(continuation.sequence);
  }
  const truncated = emptyCount(state.board) > 0;
  // A capped rollout gets an explicitly approximate continuation value.
  return {value: truncated ? evaluate(state, profile) : score(state.board),
    finalScore: score(state.board), moves, truncated, maxId: state.maxId,
    clearActions, clearsWithMoreThanTwoEmpties};
}

function summary(record) {
  const mean = record.n ? record.sum / record.n : 0;
  const variance = record.n > 1 ? Math.max(0, (record.sumSquares - record.sum * mean) / (record.n - 1)) : 0;
  return {samples: record.n, mean, standardError: Math.sqrt(variance / Math.max(1, record.n))};
}
export function plan(input, options = {}) {
  const state = normalizeState(input), begin = performance.now();
  const actions = legalActions(state);
  const requestedBudget = Number(options.budgetMs ?? 1800);
  if (!Number.isFinite(requestedBudget)) throw new Error('计算时间必须是有效数字。');
  const budgetMs = Math.min(120000, Math.max(50, requestedBudget));
  const seed = Number(options.seed ?? 20261029) >>> 0;
  const models = options.models ?? ['current_max', 'new_grade', 'final_max'];
  if (!models.length || new Set(models).size!==models.length || models.some(model => !['current_max', 'new_grade', 'final_max'].includes(model))) throw new Error('丹渣概率模型无效。');
  if (!actions.length) return {status:'ended', score:score(state.board), ranking:[], elapsedMs:0};
  const horizon=Number(options.horizon??240);
  if(!Number.isInteger(horizon)||horizon<1||horizon>1000)throw new Error('推演上限应为1至1000步。');
  const maximumRounds=Number(options.rounds??1000000);
  if(!Number.isInteger(maximumRounds)||maximumRounds<models.length)throw new Error('推演次数至少覆盖全部模型。');
  if(options.openingBook!==false){
    const opening=lookupOpening(state);
    if(opening){opening.elapsedMs=performance.now()-begin;return opening;}
  }
  const strategic=searchLayouts(state,models,{stepBefore:options.stepBefore,
    timeMs:Math.min(1200,Math.max(10,budgetMs*.65)),targetDepth:options.layoutDepth});
  const macros=rootContinuations(state,models,strategic,{stepBefore:options.stepBefore});
  const protectedKeys=new Set(strategic.map(c=>`${c.action.type}:${c.action.index}`));
  const records=macros.map(macro=>({action:macro.action,sequence:macro.sequence,clearPurpose:macro.clearPurpose,
    key:`${macro.action.type}:${macro.action.index}`,n:0,sum:0,sumSquares:0,
    perModel:Object.fromEntries(models.map(model=>[model,{n:0,sum:0,sumSquares:0}])),
    truncated:0,moves:0,clearActions:0,earlyClearActions:0,active:true,values:[],
    immediate:deterministicMove(state,macro.action)}));
  const votes=new Map();
  for(const c of strategic){const key=`${c.action.type}:${c.action.index}`;votes.set(key,(votes.get(key)??0)+1);}
  const anchorKey=[...votes.entries()].sort((a,b)=>b[1]-a[1])[0][0];
  const anchor=records.find(r=>r.key===anchorKey);
  let rounds=0,totalRollouts=0;
  while(rounds+models.length<=maximumRounds && (rounds===0 || performance.now()-begin<budgetMs)){
    const active=records.filter(r=>r.active);
    // Complete whole model blocks. Within a block every active action sees the
    // same seeds, and each action always has equal sample counts across models.
    const block=[];let expired=false;
    for(let m=0;m<models.length;m++){
      const model=models[m],roundSeed=(seed+Math.imul(rounds+m+1,2654435761))>>>0;
      for(const record of active){
        if(rounds>0&&performance.now()-begin>=budgetMs){expired=true;break;}
        const sample=rollout(state,record.sequence,roundSeed,model,{horizon,profile:0,stepBefore:options.stepBefore});
        block.push({record,sample,model,index:rounds+m});
      }
      if(expired)break;
    }
    if(expired)break;
    for(const {record,sample,model,index} of block){
        for(const counter of [record,record.perModel[model]]){
          counter.n++;counter.sum+=sample.value;counter.sumSquares+=sample.value*sample.value;
        }
        record.truncated+=Number(sample.truncated);record.moves+=sample.moves;
        record.values[index]=sample.value;
        record.clearActions+=sample.clearActions;record.earlyClearActions+=sample.clearsWithMoreThanTwoEmpties;
        totalRollouts++;
    }
    rounds+=models.length;
    if(options.racing!==false && active.length>6 && rounds>=models.length*2){
      // Retain the short lookahead leaders while focusing later simulations.
      // A discarded action is labelled, never compared as if equally sampled.
      const ordered=[...active].sort((a,b)=>b.sum/b.n-a.sum/a.n);
      const keep=new Set(ordered.slice(0,Math.max(6,Math.ceil(active.length/2))).map(r=>r.key));
      for(const r of active)r.active=keep.has(r.key)||protectedKeys.has(r.key);
    }
  }
  // The maximum of many noisy rollout estimates is optimistic. Compare each
  // challenger against the strong short-search policy on paired scenarios;
  // without enough evidence, keep that policy instead of randomizing the layout.
  // This is a conservative switching rule, not a formal sequential confidence bound.
  let chosen=anchor,bestEvidence=0;
  const paired=new Map();
  for(const record of records){
    const deltas=record.values.map((v,i)=>v-anchor.values[i]);
    const n=deltas.length,mean=deltas.reduce((a,b)=>a+b,0)/n;
    const variance=n>1?deltas.reduce((a,b)=>a+(b-mean)**2,0)/(n-1):0;
    const standardError=Math.sqrt(variance/n),lower=mean-2.8*standardError;
    paired.set(record.key,{samples:n,meanDifference:mean,standardError,conservativeDifference:lower});
    if(record.active&&n>=12&&lower>bestEvidence){chosen=record;bestEvidence=lower;}
  }
  const ranking=records.map(record=>({
    action:describeAction(record.action),sequence:record.sequence,clearPurpose:record.clearPurpose,
    ...summary(record),searchActive:record.active,
    models:Object.fromEntries(Object.entries(record.perModel).map(([name,counter])=>[name,summary(counter)])),
    truncatedRollouts:record.truncated,averageFutureActions:record.moves/record.n,
    averageClearActions:record.clearActions/record.n,averageClearsWithMoreThanTwoEmpties:record.earlyClearActions/record.n,
    immediateMerges:record.immediate.merges.length,emptyAfterDeterministic:emptyCount(record.immediate.state.board),
    maximumAfterDeterministic:record.immediate.state.maxId,
    selected:record===chosen,pairedAgainstLayout:paired.get(record.key),
  })).sort((a,b)=>Number(b.selected)-Number(a.selected)||Number(b.searchActive)-Number(a.searchActive)||b.mean-a.mean||b.immediateMerges-a.immediateMerges||a.action.index-b.action.index);
  const modelChoices=Object.fromEntries(models.map(model=>{
    const best=ranking.filter(r=>r.searchActive).sort((a,b)=>b.models[model].mean-a.models[model].mean)[0];
    return [model,{index:best.action.index,type:best.action.type,mean:best.models[model].mean}];
  }));
  const choicesAgree=new Set(Object.values(modelChoices).map(c=>`${c.type}:${c.index}`)).size===1;
  const overlap=ranking.length>1 && ranking[0].mean-ranking[1].mean<=1.96*Math.hypot(ranking[0].standardError,ranking[1].standardError);
  return {status:'ready',algorithm:'space_policy_chance_lookahead_and_rollout_racing',strategyVersion:'2.0',
    strategyRevision:'layout_depth_opening',objective:'expected_final_score',
    score:score(state.board),emptyCells:emptyCount(state.board),state:serializeState(state),recommendation:ranking[0].action,
    sequence:chosen.sequence,clearPurpose:chosen.clearPurpose,
    ranking,rounds,totalRollouts,sampleRange:[Math.min(...ranking.map(r=>r.samples)),Math.max(...ranking.map(r=>r.samples))],
    elapsedMs:Math.round(performance.now()-begin),modelChoices,modelsAgree:choicesAgree,samplingUncertain:overlap||rounds<12,
    layoutAction:describeAction(anchor.action),recommendationReason:chosen===anchor?'iterative_layout_search':'paired_rollout_improvement',
    layoutSearch:strategic.stats,
    shortLookahead:strategic.map(s=>({model:s.mergeModel,action:describeAction(s.action),sequence:s.sequence,depth:s.depth,targetDepth:s.targetDepth,width:s.width})),
    assumptions:{mergeModels:models,modelWeights:'equal working weights; not fitted posterior probabilities',
      stepTable:options.stepBefore?'before_action':'after_action',slagPosition:'uniform_among_current_empty_cells',phaseRandomness:'independent',
      horizon,timerOptimized:false,shortLookahead:'iterative 3-4 placement plies; adaptive width 6-8; preparation slots retained; exact next-pill weights; expected slag spatial cost',
      clearPolicy:'use_current_pill_at_cleared_cell_or_strictly_reduce_this_placement_terminal_risk',
      rolloutActionPolicy:'committed_clear_then_placement; unused_preparatory_clears_deferred',
      rootAllocation:options.racing===false?'uniform':'all actions sampled before focusing; lookahead leaders retained',
      rolloutSlagEvaluation:'sampled at each actual phase; greedy leaf evaluation approximates expected empty loss and terminal risk'},
    limits:['近似搜索，尚未证明全局最优。','丹渣概率选表、空格位置分布与独立性仍含待验证假设。','估计分数来自离线模型，不是官服实测得分。']};
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes('--worker')) {
    const lines = readline.createInterface({input: process.stdin, crlfDelay: Infinity});
    for await (const line of lines) {
      if (!line.trim()) continue;
      let message;
      try {
        message = JSON.parse(line);
        process.stdout.write(JSON.stringify({id: message.id, ok: true, result: plan(message.state, message.options)}) + '\n');
      } catch (error) {
        process.stdout.write(JSON.stringify({id: message?.id, ok: false, error: error.message}) + '\n');
      }
    }
    return;
  }
  const filename = args[args.indexOf('--state') + 1];
  if (!args.includes('--state') || !filename) {
    process.stderr.write('Usage: node planner.mjs --state state.json [--budget 1500]\n');
    process.exitCode = 2;
    return;
  }
  const options = {};
  if (args.includes('--budget')) options.budgetMs = Number(args[args.indexOf('--budget') + 1]);
  const state = JSON.parse((await readFile(filename, 'utf8')).replace(/^\uFEFF/, ''));
  process.stdout.write(JSON.stringify(plan(state, options), null, 2) + '\n');
}
if (process.argv[1] && fileURLToPath(import.meta.url).toLowerCase() === process.argv[1].toLowerCase()) {
  main().catch(error => { process.stderr.write(error.stack + '\n'); process.exitCode = 1; });
}
