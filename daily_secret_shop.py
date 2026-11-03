"""神秘商店：已开启货架按格位号降序购买。"""
import json,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox


def buy(flow,scene,limit,log,entry=None):
    config=json.loads((Path(__file__).parent/'output_cg1_20260921_1_2/179___ShopItem.xml.json').read_text(encoding='utf-8'))['RECORD']
    goods={str(r['id']):r for r in config}
    vip=int(scene['user'].get('vipLevel',0) or 0)
    vip_rows=json.loads((Path(__file__).parent/'output_cg1_20260921_1_2/236___VIP.xml.json').read_text(encoding='utf-8'))['RECORD']
    vip_config=next((r for r in vip_rows if int(r['id'])==vip), None)
    if vip_config is None:raise RuntimeError('未知VIP等级，无法确认购买次数')
    extra=max(0,int(vip_config.get('stallNum',0)))
    daily_cap=5+extra
    limit=daily_cap if limit is None else min(int(limit),daily_cap)
    record=(entry or {}).get('record') or scene['curRecord']
    vip_info=record.get('vipInfo') or scene['curRecord'].get('vipInfo') or {}
    vip_used=int(vip_info['secretStallNum']) if 'secretStallNum' in vip_info else None
    log('[神秘商店] VIP%d，每日上限%d次；本轮最多%d次'%(vip,daily_cap,limit))
    spirit=int(scene['curRecord'].get('spirit',0));gem=scene['user']['gem'];bought=0
    baseline_checked=False
    while bought<limit:
        state=flow.request('scene.itemHandler.enterSecretShop',{},timeout=15)
        if state.get('code')!=200 or state.get('error'):raise RuntimeError(state.get('error')or str(state))
        # 一键日常里前面的任务（如师徒学艺）会消耗灵魂，登录快照的 spirit 可能已过期；
        # 货架回包若带实时余额就以它为准，否则在首次购买时用回包余额反推基线。
        if not baseline_checked and state.get('spirit') is not None:
            fresh=int(state['spirit'])
            if fresh!=spirit:
                log('[神秘商店] 灵魂快照%d已过期，按实际余额%d判断（前置任务已消耗）'%(spirit,fresh))
            spirit=fresh;baseline_checked=True
        if 'vipSecretStallNum' in state:
            vip_used=int(state['vipSecretStallNum'])
        if state.get('secretStallNum') is not None:
            base_remaining=int(state['secretStallNum'])
            if base_remaining<=0 and (extra==0 or (vip_used is not None and vip_used>=extra)):
                log('[神秘商店] 今日购买次数已用完，停止');break
        stall=state.get('stallData')or[]
        if isinstance(stall,dict):stall=list(stall.values())
        candidates=[]
        for row in stall:
            if not isinstance(row,dict) or not row.get('stallId'):continue
            item=goods.get(str(row.get('goodsId')))
            if not item:
                log('[神秘商店] 商品%s缺少价格配置，跳过'%row.get('goodsId'));continue
            if int(item.get('consumePointTicket',0)or 0)>0:continue
            cost=int(item.get('consumeSpirit',-1))
            if cost<0:continue
            candidates.append((int(row['stallId']),row,item,cost))
        if not candidates:
            log('[神秘商店] 没有可购买的灵魂商品，停止');break
        progressed=False
        for slot,row,item,cost in sorted(candidates,key=lambda x:x[0],reverse=True):
            if cost>spirit:
                log('[神秘商店] 格位%d灵魂不足，跳过'%slot);continue
            reply=flow.request('scene.itemHandler.secretShop',{'stallId':slot,'type':1},timeout=15)
            if reply.get('code')!=200 or reply.get('error'):
                log('[神秘商店] 格位%d购买停止：%s'%(slot,reply.get('error')or reply.get('code')))
                return bought
            if reply.get('gem') is not None and reply['gem']!=gem:raise RuntimeError('点券变化，停止购买')
            if reply.get('spirit') is None:raise RuntimeError('购买回包缺少灵魂余额，停止')
            after=int(reply['spirit'])
            if after!=spirit-cost:
                if bought==0 and not baseline_checked:
                    # 快照过期但货架回包没带余额：用首次购买回包反推基线，之后仍严格校验单价
                    log('[神秘商店] 灵魂基线%d与实际%d不符（前置任务已消耗%d），按回包余额校准'%(spirit,after+cost,spirit-after-cost))
                    spirit=after+cost;baseline_checked=True
                else:
                    raise RuntimeError('灵魂消耗与配置不符，停止')
            if 'vipSecretStallNum' in reply:vip_used=int(reply['vipSecretStallNum'])
            spirit=after;bought+=1;progressed=True
            log('[神秘商店] 第%d次：格位%d，%s，消耗%d灵魂，剩余次数字段%s'%(bought,slot,item.get('name',row['goodsId']),cost,reply.get('secretStallNum','未返回')))
            time.sleep(0.5)
            break # 每次购买后重读货架，包含本次新开启的后排格子。
        if not progressed:break
    log('[神秘商店] 本次成功购买%d次'%bought)
    return bought


def build_tab(app):
    tab=ttk.Frame(app.daily_notebook,padding=10);app.daily_notebook.add(tab,text='神秘商店')
    ttk.Label(tab,text='优先购买已开启的后排格子',font=('Microsoft YaHei',12,'bold')).pack(anchor='w',pady=8)
    ttk.Label(tab,text='是否纳入一键日常，请在“一键日常”面板勾选。',foreground='gray').pack(anchor='w',pady=5)
    ttk.Label(tab,text='自动读取VIP：VIP0每天5次，VIP1及以上每天10次（普通5次＋VIP额外5次）。',wraplength=660).pack(anchor='w',pady=6)
    ttk.Label(tab,text='按当前格位号从大到小购买，每次买完重新读取货架；结合今日已用次数，到上限即停。仅买灵魂商品。',wraplength=660).pack(anchor='w',pady=8)
    status=ttk.Label(tab,text='待执行；已实测后排优先、VIP次数及道具入包',wraplength=660);status.pack(anchor='w',pady=8)
    def start():
        if not app._ensure_login():return
        save=app.current_save['index'];button.config(state='disabled')
        def worker():
            flow=None
            try:
                flow,entry,scene=app._connect_and_enter(save)
                count=buy(flow,scene,None,app._log,entry=entry)
                text='成功购买%d次；详细结果见日志'%count
            except Exception as e:text='停止：'+str(e);app._log('[神秘商店] '+text)
            finally:
                if flow:flow.disconnect()
                def finish(t=text):status.config(text=t);button.config(state='normal')
                app.root.after(0,finish)
        threading.Thread(target=worker,daemon=True).start()
    button=ttk.Button(tab,text='按后排优先购买',command=start);button.pack(anchor='w',pady=8)
