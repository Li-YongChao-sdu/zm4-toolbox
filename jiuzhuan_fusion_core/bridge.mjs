// Toolbox transport only. Files imported below are unmodified author sources.
import readline from 'node:readline';
import {plan} from './fusion_planner.mjs';
import {CELLS,VALUES,DRAW_TABLE,normalizeState,serializeState,deterministicMove,replayMove} from './rules.mjs';

function apply(state,action){return serializeState(deterministicMove(normalizeState(state),action).state);}
function validateSequence(state,sequence,recommendation){
  if(!Array.isArray(sequence)||!sequence.length)throw Error('Empty original sequence');
  if(sequence[0].type!==recommendation.type||sequence[0].index!==recommendation.index)throw Error('Original sequence mismatch');
  let next=normalizeState(state);
  sequence.forEach((a,i)=>{
    if((i<sequence.length-1&&a.type!=='clear')||(i===sequence.length-1&&a.type!=='place'))throw Error('Invalid clear-place sequence');
    next=deterministicMove(next,a).state;
  });
}
const lines=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
for await(const line of lines){
  if(!line.trim())continue;
  let request;
  try{
    request=JSON.parse(line);let value;
    if(request.command==='metadata')value={cells:CELLS,values:VALUES,drawTable:DRAW_TABLE,node:process.version};
    else if(request.command==='plan'){
      const result=plan(request.state,request.options);
      if(result.status==='ready'){
        validateSequence(request.state,result.sequence,result.recommendation);
        value={result,after:apply(request.state,result.recommendation)};
      }else value={result};
    }else if(request.command==='apply')value={after:apply(request.state,request.action)};
    else if(request.command==='replay')value=serializeState(replayMove(normalizeState(request.state),request.action,request.log,request.nextId));
    else throw Error('Unknown bridge command');
    console.log(JSON.stringify({id:request.id,ok:true,value}));
  }catch(error){console.log(JSON.stringify({id:request?.id,ok:false,error:String(error.message)}));}
}
