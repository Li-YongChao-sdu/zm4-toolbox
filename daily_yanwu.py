"""演武堂榜首爱心：对应 ManRank / ManRankItem 的免费请求。"""
import json

def give_love(flow, entry, scene, log):
    records = [scene.get('curRecord') or {}, entry.get('record') or {}, scene.get('record') or {}]
    if any(int(r.get('criticiseTop1', 0) or 0) >= 1 for r in records):
        log('[演武堂] 今日爱心已赠送，跳过')
        return
    ranks = flow.request('scene.roleRankHandler.getAllTop1', None, timeout=15)
    if ranks.get('code') != 200 or ranks.get('error'):
        raise RuntimeError(ranks.get('error') or str(ranks.get('code')))
    data = ranks.get('data') or {}
    if not isinstance(data, dict):
        raise RuntimeError('榜首列表格式不符，停止点赞')
    own = str((scene.get('user') or {}).get('uid', (scene.get('curRecord') or {}).get('uid', '')))
    target = next((r for r in data.values() if isinstance(r, dict) and r.get('uid') and str(r['uid']) != own), None)
    if not target:
        log('[演武堂] 没有可赠送爱心的榜首玩家')
        return
    result = flow.request('scene.roleRankHandler.criticiseTop1Like', {'uid':int(target['uid'])}, timeout=15)
    if result.get('code') != 200 or result.get('error'):
        raise RuntimeError(result.get('error') or str(result.get('code')))
    log('[演武堂] 爱心赠送成功，奖励回包：' + json.dumps({k:v for k,v in result.items() if k not in ('user','record','curRecord')}, ensure_ascii=False))
