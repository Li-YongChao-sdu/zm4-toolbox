"""法宝/羽毛洗练。预览与确认共用连接，避免确认到其他实例。"""
import json
import threading
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

BASE = Path(__file__).parent / 'output_cg1_20260921_1_2'
ATTRS = {'growthRate':'成长率', 'fiveElements':'五行', 'hpMax':'生命', 'mpMax':'魔法',
         'atk':'攻击', 'phyDef':'防御', 'critical':'暴击', 'toughness':'韧性',
         'lucky':'幸运', 'guardian':'守护', 'dodge':'闪避', 'hit':'命中',
         'soar':'腾空', 'sprint':'疾跑', 'reHP':'回血', 'reMP':'回魔',
         'suckBlood':'吸血', 'backLash':'反伤', 'magRes':'魔抗', 'reduceMagDef':'破魔'}
MAGIC_LOCKS = ('hpMax','mpMax','atk','phyDef','reHP','reMP','suckBlood','backLash')


def rows(name):
    return json.loads((BASE / name).read_text(encoding='utf-8'))['RECORD']


def values(data):
    return list(data.values()) if isinstance(data, dict) else (data or [])


def feather_lock_keys(item, config):
    """普通词条和上古额外词条使用各自配置池；仅显示当前羽毛已有的属性。"""
    allowed = set()
    for field in ('attributeDetails', 'attributeDetails2'):
        raw = config.get(field) or ''
        if isinstance(raw, str):
            allowed.update(raw.split(';'))
    return [key for key in ATTRS if key in item and key in allowed]


def checked(flow, route, body):
    result = flow.request(route, body, timeout=20)
    if result.get('code') != 200 or result.get('error'):
        raise RuntimeError(result.get('error') or str(result))
    return result


def targets(scene, names):
    record = scene['curRecord']; result = []; seen = set()
    for pkey in ('p1', 'p2', 'p3', 'p4'):
        player = record.get(pkey) or {}
        for item in values(player.get('equipments')):
            if not isinstance(item, dict) or not item.get('entityId'):
                continue
            if 'growthRate' in item and 'fiveElements' in item:
                key = ('magic', item['entityId'])
                if key not in seen:
                    seen.add(key)
                    result.append(dict(kind='magic', item=item, pNum=int(pkey[1:]),
                                       label='法宝 · %s · 角色%s · %s' %
                                       (names.get(str(item['id']), item['id']), pkey[1:], item['entityId'])))
    for pkey, wings in (record.get('wingList') or {}).items():
        if not pkey.startswith('p') or not pkey[1:].isdigit():
            continue
        for wing in values(wings):
            for item in values(wing.get('featherInfo')):
                key = ('feather', item['entityId'])
                if key in seen:
                    continue
                seen.add(key)
                result.append(dict(kind='feather', item=item, pNum=int(pkey[1:]), wingId=wing['id'],
                                   label='羽毛 · %s · %s/%s号位 · %s' %
                                   (names.get(str(item['id']), item['id']),
                                    names.get(str(wing['id']), wing['id']), item['pos'], item['entityId'])))
    return result


class WashPage:
    def __init__(self, app, parent, keep):
        self.app = app; self.keep = keep; self.data = []; self.scene = None
        self.identity = None; self.flow = None; self.pending = None; self.busy = False
        self.names = {}; self.lock_vars = {}
        self.feathers = {str(r['id']):r for r in rows('057___Feather.xml.json')}
        self.vips = {int(r['id']):r for r in rows('236___VIP.xml.json')}
        self.common = json.loads((BASE/'026___Common.xml.json').read_text(encoding='utf-8'))
        if 'RECORD' in self.common:
            self.common = self.common['RECORD']
        if isinstance(self.common,list):self.common=self.common[0]
        for name in ('106___Magicweapon.xml.json', '057___Feather.xml.json', '242___Wing.xml.json'):
            self.names.update({str(r['id']):r.get('name', r['id']) for r in rows(name)})
        # 页面独立滚动，缩小窗口也可以操作确认按钮。
        canvas = tk.Canvas(parent, highlightthickness=0)
        scroll = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y'); canvas.pack(side='left', fill='both', expand=True)
        panel = ttk.Frame(canvas, padding=12); window = canvas.create_window((0,0), window=panel, anchor='nw')
        panel.bind('<Configure>', lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>', lambda e:canvas.itemconfigure(window, width=e.width))
        ttk.Label(panel, text='先读取存档，再选择要洗练的法宝或羽毛。法宝需先装备，羽毛需先镶嵌。',
                  wraplength=650).pack(anchor='w', pady=4)
        ttk.Label(panel, text=('先预览新旧属性，再选择替换或保留；预览消耗次数，保留不返还。' if keep else
                              '直接洗练会立即覆盖原属性，无法保留。'), foreground='#b05020',
                  wraplength=650).pack(anchor='w', pady=4)
        self.refresh = ttk.Button(panel, text='读取／刷新当前存档', command=self.load)
        self.refresh.pack(anchor='w', pady=5)
        self.info = ttk.Label(panel, text='尚未读取', wraplength=650); self.info.pack(anchor='w', pady=4)
        self.selection = ttk.Combobox(panel, state='readonly', width=78)
        self.selection.pack(fill='x', pady=5); self.selection.bind('<<ComboboxSelected>>', self.select)
        self.source = tk.StringVar(value='免费次数')
        self.source_box = ttk.Combobox(panel, state='readonly', textvariable=self.source,
                                      values=['免费次数', '羽毛材料洗练'] if keep else ['免费次数'], width=24)
        self.source_box.pack(anchor='w', pady=4)
        self.source_box.bind('<<ComboboxSelected>>', lambda e:self.cost())
        self.lock_frame = ttk.LabelFrame(panel, text='锁定词条（至少留一项不锁）', padding=7)
        self.lock_frame.pack(fill='x', pady=5)
        self.cost_label = ttk.Label(panel, wraplength=650); self.cost_label.pack(anchor='w', pady=4)
        self.tree = ttk.Treeview(panel, columns=('attr','old','new'), show='headings', height=10)
        for key, label in [('attr','属性'), ('old','原属性'), ('new','新属性')]:
            self.tree.heading(key, text=label); self.tree.column(key, width=150, stretch=True)
        self.tree.pack(fill='x', pady=5)
        actions = ttk.Frame(panel); actions.pack(fill='x', pady=6)
        self.run_button = ttk.Button(actions, text='洗练一次并预览' if keep else '直接洗练一次', command=self.start)
        self.run_button.pack(side='left', padx=3)
        self.replace_button = ttk.Button(actions, text='替换为新属性', command=lambda:self.decide(True), state='disabled')
        self.old_button = ttk.Button(actions, text='保留原属性', command=lambda:self.decide(False), state='disabled')
        if keep:
            self.replace_button.pack(side='left', padx=3); self.old_button.pack(side='left', padx=3)
        self.status = ttk.Label(panel, text='每次仅洗练一次；免费用完即停，材料洗练不自动购买材料。', wraplength=650)
        self.status.pack(anchor='w', pady=5)

    def current_identity(self):
        return (id(self.app.client), self.app.current_save['index'])

    def controls(self):
        blocked = self.busy or self.pending is not None
        for widget in (self.refresh, self.run_button):
            widget.configure(state='disabled' if blocked else 'normal')
        for widget in (self.selection, self.source_box):
            widget.configure(state='disabled' if blocked else 'readonly')
        for widget in self.lock_frame.winfo_children():
            widget.configure(state='disabled' if blocked else 'normal')
        for widget in (self.replace_button, self.old_button):
            widget.configure(state='normal' if self.pending and not self.busy else 'disabled')

    def async_work(self, work, done):
        if self.busy:return
        self.busy = True; self.controls()
        def worker():
            try:
                result = work(); error = None
            except Exception as exc:
                result = None; error = str(exc)
            def finish():
                self.busy = False
                if error:
                    self.status.configure(text='停止：'+error); self.app._log('[洗练] '+error)
                else:
                    done(result)
                self.controls()
            self.app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def load(self):
        if not self.app._ensure_login():return
        if any(p.pending or p.busy for p in self.app.wash_pages if p is not self):
            messagebox.showinfo('洗练', '请先处理另一洗练页面的操作或预览'); return
        identity = self.current_identity(); save = identity[1]
        def work():
            flow = None
            try:
                flow, _, scene = self.app._connect_and_enter(save)
                return scene
            finally:
                if flow:flow.disconnect()
        def done(scene):
            self.scene = scene; self.identity = identity
            self.data = targets(scene, self.names)
            self.selection.configure(values=[t['label'] for t in self.data])
            self.selection.set('')
            vip = int(scene['user'].get('vipLevel',0)); cfg = self.vips[vip]; rec = scene['curRecord']
            self.info.configure(text='VIP%d；法宝免费剩余%d次，羽毛免费剩余%d次。' %
                (vip, max(0,int(cfg['amuletResetNum'])-int((rec.get('vipInfo')or{}).get('magicEquipNum',0))),
                 max(0,int(cfg['feaResetNum'])-int(rec.get('resetFeatherNum',0)))))
            self.status.configure(text='已读取%d个可洗练对象。'%len(self.data))
            if self.data:self.selection.current(0)
            self.select()
        self.async_work(work, done)

    def target(self):
        index = self.selection.current()
        return self.data[index] if 0 <= index < len(self.data) else None

    def show(self, old, new=None):
        self.tree.delete(*self.tree.get_children())
        for key, label in ATTRS.items():
            if key in old or (new is not None and key in new):
                self.tree.insert('', 'end', values=(label, old.get(key,'—'), new.get(key,'—') if new is not None else '—'))

    def select(self, event=None):
        for child in self.lock_frame.winfo_children():child.destroy()
        self.lock_vars = {}; target = self.target()
        if not target:
            self.tree.delete(*self.tree.get_children()); return
        item = target['item']; self.show(item)
        sources = ['免费次数']
        if self.keep:sources.append('羽毛材料洗练' if target['kind']=='feather' else '法宝词条材料洗练')
        self.source_box.configure(values=sources)
        if self.source.get() not in sources:self.source.set('免费次数')
        if target['kind']=='feather':
            config = self.feathers.get(str(item['id']), {})
            for key in feather_lock_keys(item, config):
                var = tk.BooleanVar(value=False); self.lock_vars[key] = var
                ttk.Checkbutton(self.lock_frame, text='%s：%s'%(ATTRS[key],item[key]),
                                variable=var, command=self.cost).grid(row=(len(self.lock_vars)-1)//3,
                                column=(len(self.lock_vars)-1)%3, sticky='w', padx=8, pady=3)
        else:
            if self.keep:
                for index,key in enumerate(MAGIC_LOCKS):
                    if key not in item:continue
                    var=tk.BooleanVar(value=False); self.lock_vars[key]=var
                    ttk.Checkbutton(self.lock_frame,text='%s：%s'%(ATTRS[key],item[key]),
                                    variable=var,command=self.cost).grid(row=index//3,column=index%3,
                                    sticky='w',padx=8,pady=3)
            else:
                ttk.Label(self.lock_frame, text='法宝免费洗练会重新生成整体属性，不支持锁词条。').grid(sticky='w')
        self.cost()

    def cost(self):
        target = self.target()
        if not target:return
        if target['kind']=='feather' and self.source.get()=='羽毛材料洗练':
            cfg = self.feathers[str(target['item']['id'])]
            count = int(cfg['washNum'])*(1+sum(v.get() for v in self.lock_vars.values()))
            self.cost_label.configure(text='本次需羽毛洗练材料%s × %d；勾选锁定会增加消耗。'%(cfg['washItemId'],count))
        elif target['kind']=='magic' and self.source.get()=='法宝词条材料洗练':
            counts=self.common['resetAmuletAttributeNum'].split(';')
            count=int(counts[sum(v.get() for v in self.lock_vars.values())])
            self.cost_label.configure(text='本次需法宝洗练材料%s × %d；只洗基础词条，不洗成长率和五行。'%
                                      (self.common['resetAmuletAttributeItem'],count))
        else:self.cost_label.configure(text='本次消耗1次免费洗练；不扣洗练材料。')

    def start(self):
        if not self.app._ensure_login():return
        target = self.target()
        if not target or not self.scene:
            messagebox.showinfo('洗练', '请先读取并选择法宝或羽毛'); return
        if self.identity != self.current_identity():
            messagebox.showinfo('洗练', '账号或存档已变更，请重新读取'); return
        # 两个子页不得同时保有预览。
        if any(p.pending or p.busy for p in self.app.wash_pages if p is not self):
            messagebox.showinfo('洗练', '请先处理另一洗练页面的操作或预览'); return
        locks = [k for k,v in self.lock_vars.items() if v.get()]
        if self.lock_vars and len(locks)>=len(self.lock_vars):
            messagebox.showinfo('洗练', '至少保留一个未锁定词条'); return
        material = self.source.get()!='免费次数'
        if target['kind']=='magic' and locks and not material:
            messagebox.showinfo('洗练','法宝锁词条需要选择“法宝词条材料洗练”，免费整体洗练不支持锁定');return
        if not self.keep and not messagebox.askyesno('直接覆盖', '本次洗练将立即覆盖所选对象的原属性，是否继续？'):return
        if material and not messagebox.askyesno('材料洗练', self.cost_label.cget('text')+'\n确认使用已有材料洗练一次？'):return
        save = self.identity[1]
        def work():
            flow = None; retain = False
            try:
                flow, _, scene = self.app._connect_and_enter(save)
                candidates = targets(scene, self.names)
                actual = next((t for t in candidates if t['kind']==target['kind'] and
                               t['pNum']==target['pNum'] and t['item']['entityId']==target['item']['entityId'] and
                               t.get('wingId')==target.get('wingId')), None)
                if not actual or actual['item']!=target['item']:
                    raise RuntimeError('所选对象已改变，请重新读取')
                vip = self.vips[int(scene['user'].get('vipLevel',0))]; rec = scene['curRecord']
                ability = 'featherWashCanChange' if target['kind']=='feather' else 'magicweaponWashCanChange'
                if bool(int(vip[ability])) != self.keep:
                    raise RuntimeError('当前VIP应使用“%s”页面'%('高VIP保留洗练' if int(vip[ability]) else '低VIP直接洗练'))
                item = actual['item']
                if target['kind']=='magic':
                    if material:
                        item_id=self.common['resetAmuletAttributeItem']
                        need=int(self.common['resetAmuletAttributeNum'].split(';')[len(locks)])
                        have=sum(int(x.get('count',1)) for x in values((rec.get('itemsBag')or{}).get('items'))
                                 if str(x.get('id'))==str(item_id))
                        if have<need:raise RuntimeError('法宝洗练材料不足：需要%d，现有%d'%(need,have))
                    else:
                        used = int((rec.get('vipInfo')or{}).get('magicEquipNum',0))
                        if used>=int(vip['amuletResetNum']):raise RuntimeError('今日法宝免费次数已用完')
                    body = {'pNum':actual['pNum'],'entityId':item['entityId'],'resetType':4 if material else 1}
                    if material:body['lock']=locks
                    if self.keep:body['new']=0
                    route = 'scene.equipHandler.resetAmulet'
                else:
                    if material:
                        cfg = self.feathers[str(item['id'])]
                        have = sum(int(x.get('count',1)) for x in values((rec.get('itemsBag')or{}).get('items'))
                                   if str(x.get('id'))==str(cfg['washItemId']))
                        need = int(cfg['washNum'])*(1+len(locks))
                        if have<need:raise RuntimeError('羽毛洗练材料不足：需要%d，现有%d'%(need,have))
                        if not self.keep:raise RuntimeError('材料洗练使用保留预览流程，请在高VIP页面执行')
                    elif int(rec.get('resetFeatherNum',0))>=int(vip['feaResetNum']):
                        raise RuntimeError('今日羽毛免费次数已用完')
                    body = {'pNum':actual['pNum'],'eId':item['entityId'],'pos':item['pos'],'wingId':actual['wingId']}
                    if locks:body['lockAttrArray']=locks
                    if material:body['isProp']=1
                    route = 'scene.equipSecondHandler.'+('tryResetFeather' if self.keep else 'resetFeather')
                reply = checked(flow, route, body)
                new = reply.get('newFeather') if self.keep and target['kind']=='feather' else reply.get('feather' if target['kind']=='feather' else 'magicEquip')
                if self.keep:
                    # 即使服务器返回异常，也留住本连接供用户选择保留。
                    self.flow = flow; self.pending = dict(target=actual, body=body, new=new)
                    retain = True
                if not isinstance(new,dict):raise RuntimeError('洗练已提交，但回包缺少属性；请保留并刷新核对')
                for key in locks:
                    if new.get(key)!=item.get(key):raise RuntimeError('锁定词条与原属性不符，请保留并刷新核对')
                self.app._log('[洗练] %s；%s'%(actual['label'], json.dumps(reply,ensure_ascii=False)))
                return actual, new
            finally:
                if flow and not retain:flow.disconnect()
        def done(result):
            actual,new = result; self.show(actual['item'],new)
            self.status.configure(text='已生成新属性，请选择替换或保留。' if self.keep else '已直接覆盖原属性；再次洗练前请刷新。')
            if not self.keep:self.scene=None
        self.async_work(work, done)

    def decide(self, replace):
        if not self.pending or self.busy:return
        if replace and (not self.app.client or not self.app.current_save or self.identity != self.current_identity()):
            messagebox.showinfo('洗练', '账号或存档已变更，请先保留原属性，再重新读取'); return
        pending = self.pending; flow = self.flow
        if replace and not isinstance(pending.get('new'),dict):
            messagebox.showinfo('洗练', '未取得完整新属性，只能保留原属性'); return
        def work():
            target = pending['target']
            if target['kind']=='magic':
                body=dict(pending['body'])
                if body['resetType']==1:body['resetType']=0
                body['new']=1 if replace else 2
                checked(flow, 'scene.equipHandler.resetAmulet',body)
            elif replace:
                checked(flow,'scene.equipSecondHandler.confirmResetFeather',{'isReplace':1})
            # 羽毛保留与客户端一致：不发送确认请求。
            flow.disconnect(); self.flow=None; self.pending=None
            return replace
        def done(replaced):
            self.scene=None
            self.status.configure(text=('已替换为新属性。' if replaced else '已保留原属性。')+'请刷新读取服务器状态。')
            self.app._log('[洗练] '+self.status.cget('text'))
        self.async_work(work, done)


def build_tab(app):
    group = ttk.Frame(app.notebook); app.notebook.add(group,text='洗练')
    notebook = ttk.Notebook(group); notebook.pack(fill='both',expand=True)
    app.wash_pages=[]
    for title,keep in [('高VIP保留洗练',True),('低VIP直接洗练',False)]:
        panel=ttk.Frame(notebook); notebook.add(panel,text=title)
        app.wash_pages.append(WashPage(app,panel,keep))
