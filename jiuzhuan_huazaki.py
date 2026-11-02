"""花崎桜雪原版算法的工具箱接口；原始JS代码、权重、开局表均不修改。"""
import hashlib
import json
import queue
import subprocess
import threading
from pathlib import Path
from jiuzhuan_recovery_value import CELLS, INDEX, POINTS, CONFIG_SOURCE, board_from_pool

AUTHOR = '花崎桜雪'
STRATEGY_VERSION = 'huazaki_original_expected_final_score'
STABILITY_VERIFIED = False
PLAY_TO_END = True
_ROOT = Path(__file__).resolve().parent/'jiuzhuan_huazaki_core'
_engine = None
_lock = threading.RLock()
_pending = []
_expected = None


class _Engine:
    def __init__(self):
        origin = json.loads((_ROOT/'来源.json').read_text(encoding='utf-8'))
        for name,digest in origin['original_core_files_sha256'].items():
            if hashlib.sha256((_ROOT/name).read_bytes()).hexdigest()!=digest:
                raise RuntimeError('花崎桜雪原版核心文件校验失败：'+name)
        runtime = _ROOT/'runtime/node.exe'
        if not runtime.is_file():
            raise RuntimeError('缺少花崎桜雪算法的Node计算组件，请保留完整算法目录')
        if hashlib.sha256(runtime.read_bytes()).hexdigest()!=origin['runtime_sha256']:
            raise RuntimeError('花崎桜雪算法的Node计算组件校验失败')
        self.process = subprocess.Popen([str(runtime),str(_ROOT/'bridge.mjs')],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',bufsize=1,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.replies = queue.Queue()
        self.sequence = 0
        def read():
            try:
                for line in self.process.stdout:
                    self.replies.put(json.loads(line))
            except Exception:
                pass
            finally:
                self.replies.put(None)
        threading.Thread(target=read,daemon=True).start()

    def call(self,command,**data):
        if self.process.poll() is not None:
            raise RuntimeError('花崎桜雪计算进程已退出')
        self.sequence += 1
        request = {'id':self.sequence,'command':command,**data}
        self.process.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
        self.process.stdin.flush()
        try:
            reply = self.replies.get(timeout=max(20,float(data.get('options',{}).get('budgetMs',0))/1000+10))
        except queue.Empty:
            self.close()
            raise RuntimeError('花崎桜雪计算超时，已停止；未发送游戏动作')
        if reply is None or reply.get('id')!=self.sequence:
            raise RuntimeError('花崎桜雪计算回包中断或编号不一致')
        if not reply.get('ok'):
            raise RuntimeError('花崎桜雪原版算法：'+str(reply.get('error')))
        return reply['value']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        for stream in (self.process.stdin,self.process.stdout):
            if stream:
                try:stream.close()
                except OSError:pass


def _get():
    global _engine
    if _engine is None:
        _engine = _Engine()
        meta = _engine.call('metadata')
        if [(p['x'],p['y']) for p in meta['cells']]!=list(CELLS):
            raise RuntimeError('花崎桜雪与工具箱的棋盘坐标不一致')
        if meta['values']!=[0]+[POINTS[i] for i in range(1,10)]:
            raise RuntimeError('花崎桜雪与当前配置的丹气分值不一致')
    return _engine


def warmup(workers=1):
    global _pending,_expected
    with _lock:
        _pending=[];_expected=None
        return _get().call('metadata')


def shutdown(force=False):
    global _engine,_pending,_expected
    with _lock:
        if _engine is not None:_engine.close()
        _engine=None;_pending=[];_expected=None


def _state(game,allow_clear=True,clear_limit=3):
    board=board_from_pool(game['ballPool'])
    return {'board':list(board),'nextId':int(game['nextId']),
            'maxId':max(1,int(game.get('maxId',1)),max(board)),
            'step':int(game.get('step',0)),
            'clears':max(0,int(clear_limit)-int(game.get('jingDanNum',0))) if allow_clear else 0}


def choose(game,current_score=0,allow_clear=True,clear_limit=3,time_budget=1.8,**kwargs):
    global _pending,_expected
    with _lock:
        state=_state(game,allow_clear,3 if clear_limit is None else clear_limit)
        engine=_get()
        if _pending:
            if state!=_expected:
                raise RuntimeError('花崎桜雪清理后的盘面与原计划不符，停止执行后续动作')
            sequence=list(_pending)
            action=sequence[0]
            after=engine.call('apply',state=state,action=action)['after']
            result={'algorithm':'committed_clear_continuation','elapsedMs':0}
        else:
            answer=engine.call('plan',state=state,options={'budgetMs':float(time_budget)*1000})
            result=answer['result']
            if result.get('status')!='ready':return None
            sequence=result['sequence'];action=sequence[0];after=answer['after']
        _pending=sequence[1:]
        _expected=after if _pending else None
        x,y=CELLS[action['index']]
        choice={'pos':{'x':x,'y':y},'predicted':tuple(after['board']),
                'strategy_version':STRATEGY_VERSION,'config_version':CONFIG_SOURCE['version'],
                'search_seconds':result.get('elapsedMs',0)/1000,
                'objective':'expected_final_score','original_sequence':sequence,
                'original_algorithm':result.get('algorithm'),
                'original_action':action,'book_hit':result.get('bookHit',False)}
        if action['type']=='clear':choice['action']='clear'
        return choice


def verify_transition(before,choice,reply,after):
    with _lock:
        expected=_get().call('replay',state=_state(before),action=choice['original_action'],
                              log=reply.get('log') or [],nextId=int(after['nextId']))
        return expected==_state(after)
