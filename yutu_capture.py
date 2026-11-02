import json,threading,time
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
FIELDS=(('潜力','capacity'),('根骨','bone'),('灵力','wakan'),('生命资质','hpQualification'),('攻击资质','atkQualification'),('防御资质','defQualification'))

def run(flow,entry,scene,*,attempts,buy_limit,prebuy,baby,minimums,filtering,stop,log,delay=3.2):
    record=scene['curRecord'];user=scene['user'];gem=user['gem'];spirit=int(record.get('spirit',0))
    items=record['itemsBag'].get('items') or [];items=list(items.values()) if isinstance(items,dict) else items
    remaining=sum(int(x.get('count',0)) for x in items if str(x.get('id'))=='156100001')
    petbag=record.get('petList') or {};pets=petbag.get('pets') or [];pets=list(pets.values())if isinstance(pets,dict)else pets
    if len(pets)>=int(petbag.get('itemCount',0)):raise RuntimeError('宠物栏已满')
    old={str(x.get('entityId'))for x in pets};capacity=int(petbag['itemCount'])-len(pets)
    configs={str(r['id']):r for r in json.loads((Path(__file__).parent/'output_cg1_20260921_1_2/132___Pet.xml.json').read_text(encoding='utf-8'))['RECORD']}
    bought=0;created=False;result={'attempts':0,'released':[],'kept':[],'missed':0}
    def req(route,body):
        r=flow.request(route,body,timeout=20)
        if r.get('gem') is not None and r['gem']!=gem:raise RuntimeError('点券变化，停止')
        if r.get('code')!=200:raise RuntimeError(r.get('error')or str(r))
        return r
    def buy():
        nonlocal bought,remaining,spirit
        if bought>=buy_limit:raise RuntimeError('已达到葫芦购买上限')
        if spirit<4000:raise RuntimeError('灵魂不足4000')
        r=req('scene.itemHandler.generalShop',{'goodsId':11,'type':0,'num':1})
        if r.get('error')or str(r.get('itemId'))!='156100001' or int(r.get('spirit',-1))!=spirit-4000:raise RuntimeError('葫芦购买未核实')
        spirit=r['spirit'];remaining+=1;bought+=1
    try:
        for _ in range(min(prebuy,buy_limit)):
            if stop.is_set():break
            buy()
        if stop.is_set():return result
        r=req('scene.copyHandler.createSinglePlayerCopy',{'mid':2161,'costGem':0})
        if r.get('error'):raise RuntimeError(r['error'])
        created=True
        for n in range(attempts):
            if stop.is_set():break
            if capacity<=0:raise RuntimeError('宠物栏已满，停止')
            if remaining<=0:buy()
            if stop.wait(delay):break
            r=req('scene.animalHandler.catchPet',{'cType':2,'copyId':2161,'itemId':156100001,'pId':2000300})
            if str(r.get('itemId'))!='156100001':raise RuntimeError(r.get('error')or '捕捉回包异常')
            if r.get('error') and r['error']!='没有捕捉到当前宠物':raise RuntimeError(r['error'])
            remaining-=1;result['attempts']+=1
            pet=r.get('pet')
            if not pet:
                result['missed']+=1;log('第%d次：捕捉失败，剩余葫芦%d'%(n+1,remaining));continue
            entity=str(pet.get('entityId')or'');config=configs.get(str(pet.get('id')))or{}
            if not entity or entity in old or str(pet.get('id'))not in ('2000300','2000301','2000310','2000311'):raise RuntimeError('新宠物身份无法确认，不放生')
            old.add(entity);capacity-=1
            kind=int(config.get('type',-1));values=[int(pet.get(f,0))for _,f in FIELDS]
            log('第%d次：%s，天赋%s，资质%s'%(n+1,'宝宝' if kind==1 else '普通',values[:3],values[3:]))
            if kind not in (0,1):raise RuntimeError('宠物类型未知，不放生')
            passes=(not baby or kind==1)and all(int(pet.get(f,0))>=v for f,v in minimums.items())
            if not filtering or passes:
                result['kept'].append(pet)
                if filtering:break
            else:
                freed=req('scene.animalHandler.freePet',{'entityId':entity})
                if freed.get('error')or str(freed.get('entityId'))!=entity:raise RuntimeError('放生未确认，停止')
                capacity+=1;result['released'].append(entity)
    finally:
        result.update(bought=bought,remaining=remaining)
        if created:
            settled=req('scene.copyHandler.getDumpActRewards',{'id':2161,'killMonsters':[],'score':4100})
            result['settlement']=settled
            if settled.get('error'):log('结算失败：'+str(settled['error']))
    return result


def build_panel(app,tab):
    ttk.Label(tab,text='领奖前连续捕捉兔仔/咕咕兔；达标后停止并结算。',wraplength=650).pack(anchor='w',pady=6)
    filtering=tk.BooleanVar(value=True);baby=tk.BooleanVar(value=True)
    ttk.Checkbutton(tab,text='启用筛选，不达标自动放生（仅本轮新抓宠物）',variable=filtering).pack(anchor='w')
    ttk.Checkbutton(tab,text='只保留宝宝',variable=baby).pack(anchor='w')
    fields={};frame=ttk.Frame(tab);frame.pack(fill='x',pady=6)
    for i,(label,field)in enumerate(FIELDS):
        v=tk.IntVar(value=3 if i<3 else 0);fields[field]=v
        ttk.Label(frame,text=label).grid(row=i//3,column=i%3*2,padx=4,pady=4)
        ttk.Entry(frame,textvariable=v,width=7).grid(row=i//3,column=i%3*2+1)
    options=ttk.Frame(tab);options.pack(fill='x');variables=[]
    for label,default in [('最多尝试',1000),('最多购买葫芦',100),('开始前购买',20)]:
        v=tk.IntVar(value=default);variables.append(v);ttk.Label(options,text=label).pack(side='left',padx=3);ttk.Entry(options,textvariable=v,width=6).pack(side='left')
    ttk.Label(tab,text='筛选填0表示不限；葫芦4000灵魂/个，购买上限包含预购。每天免费进入次数由服务器判断。',wraplength=650).pack(anchor='w',pady=6)
    stop=threading.Event();status=ttk.Label(tab,text='待捕捉',wraplength=650);status.pack(anchor='w',pady=6)
    def start():
        if not app._ensure_login():return
        try:
            attempts,limit,prebuy=[v.get()for v in variables];minimums={f:v.get()for f,v in fields.items()}
            if not 1<=attempts<=10000 or not 0<=prebuy<=limit<=1000 or any(v<0 or v>9999 for v in minimums.values()):raise ValueError()
        except (ValueError,tk.TclError):messagebox.showwarning('捕捉设置','请检查次数、购买上限和筛选数值');return
        save=app.current_save['index'];filtered=filtering.get();baby_only=baby.get();stop.clear();button.config(state='disabled')
        def log(t):
            app._log('[玉兔捕捉] '+t);app.root.after(0,lambda text=t:status.config(text=text))
        def worker():
            flow=None
            try:
                flow,entry,scene=app._connect_and_enter(save)
                result=run(flow,entry,scene,attempts=attempts,buy_limit=limit,prebuy=prebuy,baby=baby_only,minimums=minimums,filtering=filtered,stop=stop,log=log)
                flow.disconnect();flow=None
                flow,_,after=app._connect_and_enter(save)
                p=(after['curRecord'].get('petList')or{}).get('pets')or[];p=list(p.values())if isinstance(p,dict)else p
                ids={str(x.get('entityId'))for x in p}
                if any(str(x['entityId'])not in ids for x in result['kept']):raise RuntimeError('重登未找到保留宠物')
                if any(after['user'].get(k)!=scene['user'].get(k)for k in ('gem','usedGem')):raise RuntimeError('点券核对不符')
                log('完成%d次，保留%d只，放生%d只；重登已核对。'%(result['attempts'],len(result['kept']),len(result['released'])))
            except Exception as e:log('停止：'+str(e))
            finally:
                if flow:flow.disconnect()
                app.root.after(0,lambda:button.config(state='normal'))
        threading.Thread(target=worker,daemon=True).start()
    actions=ttk.Frame(tab);actions.pack(fill='x')
    button=ttk.Button(actions,text='开始筛选捕捉',command=start);button.pack(side='left',padx=4)
    ttk.Button(actions,text='停止并结算',command=stop.set).pack(side='left',padx=4)
