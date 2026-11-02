"""师徒每日学艺，仅使用gem=0的每日分支。"""
import json
from pathlib import Path

def learn(flow,entry,scene,log):
    rows=json.loads((Path(__file__).parent/'output_cg1_20260921_1_2/100___LearnSkill.xml.json').read_text(encoding='utf-8'))['RECORD']
    social=flow.request('scene.socialHandler.getSocialInfo',None,timeout=15)
    if social.get('code')!=200 or social.get('error'):raise RuntimeError(social.get('error')or str(social.get('code')))
    friends=(social.get('info')or{}).get('friends')or{}
    friends=list(friends.values())if isinstance(friends,dict)else friends
    teacher=next((x for x in friends if int(x.get('type',0))==1),None)
    if not teacher:
        log('[师徒学艺] 当前没有师父，跳过');return {'skipped':'no_teacher'}
    now=scene['curRecord'].get('time')or scene.get('serverTime')or entry.get('serverTime')or social.get('serverTime')
    if not now or not teacher.get('createTime'):raise RuntimeError('缺少服务器时间或拜师时间，停止')
    days=max(0,int((int(now)-int(teacher['createTime']))//86400000))
    vip=int(scene['user'].get('vipLevel',0))
    candidates=[x for x in rows if int(x['vip'])==vip and int(x['type'])==1 and int(x['day'])>=days]
    if not candidates:raise RuntimeError('没有匹配的每日学艺配置')
    selected=min(candidates,key=lambda x:int(x['day']))
    account=scene['user'].get('accountInfo')or (entry.get('record')or{}).get('accountInfo')or scene['curRecord'].get('accountInfo')or{}
    used=account.get('learnSkill')or{}
    if int(used.get(str(selected['id']),0)or 0)>=int(selected['learnNum']):
        log('[师徒学艺] 今日已学艺，跳过');return {'skipped':'already_learned'}
    result=flow.request('scene.socialHandler.learnSkill',{'learnSkillId':int(selected['id']),'gem':0},timeout=15)
    if result.get('code')!=200 or result.get('error'):raise RuntimeError(result.get('error')or str(result))
    if result.get('gem') is not None and result['gem']!=scene['user']['gem']:raise RuntimeError('点券发生变化，停止')
    if not result.get('buffId') or not result.get('learnSkill'):raise RuntimeError('缺少学艺祝福或次数回包，不能确认成功')
    # 学艺会扣灵魂，回包带余额时把登录快照同步更新，避免后续任务（神秘商店等）读到过期灵魂
    if result.get('spirit') is not None:
        scene['curRecord']['spirit']=int(result['spirit'])
    log('[师徒学艺] VIP%d、拜师%d天，每日学艺成功：祝福%s；配置消耗%d灵魂，点券未消耗。'%(vip,days,result['buffId'],int(selected['num'])))
    return result
