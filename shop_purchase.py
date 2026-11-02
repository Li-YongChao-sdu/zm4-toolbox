"""通用商店购买：手动调用 scene.itemHandler.generalShop。"""
import json
import threading
from pathlib import Path

import tkinter as tk
from tkinter import ttk, messagebox

CONFIG_PATH = Path(__file__).parent / 'output_cg1_20260921_1_2' / '178___Shop.xml.json'

PRICE_FIELDS = (
    ('consumeSpirit', '灵魂'),
    ('yuanxiaoMoney', '元宵币'),
    ('jjcMoney', '竞技币'),
    ('petjjcMoney', '斗宠币'),
    ('consumeYB', '点券'),
    ('integral', '积分'),
    ('xinYuanBi', '心愿币'),
    ('beiKe', '贝壳'),
    ('bonusPoints', '积分'),
    ('plantPoints', '种植积分'),
)

# 名称、商品ID、generalShop 需要的 type（留空表示不传）、预设数量
PRESETS = (
    ('3级强化石 13004', '13004', '', 1),
    ('2级宝石袋 28002', '28002', '', 1),
    ('朱雀令 3030', '3030', '', 1),
)


def load_goods():
    data = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))['RECORD']
    return {str(row['id']): row for row in data}


def _int(value, default=-1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def price_text(row):
    parts = []
    for key, label in PRICE_FIELDS:
        value = _int(row.get(key))
        if value > 0:
            parts.append('%s %d' % (label, value))
    require_id = _int(row.get('changeID'), 0)
    require_num = _int(row.get('purchaseNum'), 0)
    if require_id > 0 and require_num > 0:
        parts.append('道具 %d × %d' % (require_id, require_num))
    return '，'.join(parts) if parts else '无货币价格'


def item_text(row):
    item_id = str(row.get('itemId', ''))
    num = _int(row.get('num'), 1)
    if item_id and item_id != '-1':
        return '获得道具 %s × %d' % (item_id, num)
    return '无直接道具产出'


def limit_text(row):
    buy_max = _int(row.get('buyMaxNum'))
    total_max = _int(row.get('purchaseMaxNum'))
    week_max = _int(row.get('weekPurchaseMaxNum'))
    parts = []
    if buy_max > 0:
        parts.append('单次最多 %d' % buy_max)
    if total_max > 0:
        parts.append('累计最多 %d' % total_max)
    if week_max > 0:
        parts.append('每周最多 %d' % week_max)
    return '，'.join(parts) if parts else '未限制'


def buy(flow, goods_id, num, shop_type, log):
    params = {'goodsId': int(goods_id), 'num': int(num)}
    if shop_type not in (None, ''):
        params['type'] = int(shop_type)
    log('[商店] 请求 generalShop：%s' % json.dumps(params, ensure_ascii=False))
    reply = flow.request('scene.itemHandler.generalShop', params, timeout=15)
    if not isinstance(reply, dict):
        raise RuntimeError('购买回包异常：%r' % (reply,))
    if reply.get('error'):
        raise RuntimeError('购买失败：%s' % reply['error'])
    if reply.get('code') != 200:
        raise RuntimeError('购买失败：code=%s' % reply.get('code'))
    log('[商店] 回包：%s' % json.dumps(reply, ensure_ascii=False)[:600])
    if reply.get('goodsNum') is not None:
        log('[商店] 该商品累计已购 %s 次' % reply['goodsNum'])
    return reply


def build_tab(app):
    tab = ttk.Frame(app.daily_notebook, padding=10)
    app.daily_notebook.add(tab, text='商店购买')
    ttk.Label(tab, text='通用商店购买（手动，不纳入一键日常）',
              font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=6)
    ttk.Label(tab, text='路由：scene.itemHandler.generalShop；商品ID与价格来自 178___Shop.xml。'
                        '先在下方输入商品ID查询，确认名称和价格后再购买。',
              wraplength=680).pack(anchor='w', pady=4)

    vars = {}
    row = ttk.Frame(tab)
    row.pack(fill='x', pady=6)
    ttk.Label(row, text='商品ID').pack(side='left')
    vars['id'] = tk.StringVar()
    ttk.Entry(row, textvariable=vars['id'], width=12).pack(side='left', padx=(4, 12))
    ttk.Label(row, text='类型 type').pack(side='left')
    vars['type'] = tk.StringVar(value='')
    ttk.Entry(row, textvariable=vars['type'], width=6).pack(side='left', padx=(4, 4))
    ttk.Label(row, text='（一般留空；旧商店等需要时再填）').pack(side='left')

    info = tk.StringVar(value='输入商品ID后点“查询商品”。')
    ttk.Label(tab, textvariable=info, justify='left', wraplength=680).pack(anchor='w', pady=6)

    def query():
        goods_id = vars['id'].get().strip()
        row_data = load_goods().get(goods_id)
        if row_data is None:
            info.set('未在 Shop.xml 找到商品ID %s。' % (goods_id or '（空）'))
            return
        info.set('名称：%s\n%s\n价格：%s\n限购：%s\n配置类型 type：%s'
                 % (row_data.get('name', '?'), item_text(row_data), price_text(row_data),
                    limit_text(row_data), row_data.get('type', '?')))

    ttk.Button(row, text='查询商品', command=query).pack(side='left', padx=(20, 0))

    preset_row = ttk.Frame(tab)
    preset_row.pack(fill='x', pady=4)
    ttk.Label(preset_row, text='常用：').pack(anchor='w')
    preset_lines = (ttk.Frame(preset_row), ttk.Frame(preset_row))
    for line in preset_lines:
        line.pack(anchor='w', fill='x')
    for index, (text, goods_id, shop_type, preset_num) in enumerate(PRESETS):
        def fill(gid=goods_id, gtype=shop_type, num=preset_num):
            vars['id'].set(gid)
            vars['type'].set(gtype)
            vars['num'].set(num)
            query()
        ttk.Button(preset_lines[0 if index < 3 else 1], text=text,
                   command=fill).pack(side='left', padx=3)

    buy_row = ttk.Frame(tab)
    buy_row.pack(fill='x', pady=8)
    ttk.Label(buy_row, text='购买数量').pack(side='left')
    vars['num'] = tk.IntVar(value=1)
    ttk.Spinbox(buy_row, from_=1, to=999, textvariable=vars['num'], width=6).pack(side='left', padx=(4, 15))
    status = tk.StringVar(value='待购买；购买会消耗对应货币/道具。')
    ttk.Label(buy_row, textvariable=status).pack(side='left')

    def start():
        if not app._ensure_login():
            return
        goods_id = vars['id'].get().strip()
        row_data = load_goods().get(goods_id)
        if row_data is None:
            messagebox.showwarning('商店购买', '未在 Shop.xml 找到商品ID %s。' % (goods_id or '（空）'))
            return
        try:
            num = int(vars['num'].get())
            shop_type = vars['type'].get().strip()
            if shop_type:
                int(shop_type)
        except ValueError:
            messagebox.showwarning('商店购买', '数量或 type 必须是整数。')
            return
        buy_max = _int(row_data.get('buyMaxNum'))
        if buy_max > 0 and num > buy_max:
            messagebox.showwarning('商店购买', '该商品单次最多购买 %d 个。' % buy_max)
            return
        cost = price_text(row_data)
        if not messagebox.askyesno('确认购买',
                                   '商品：%s\n数量：%d\n价格：%s\n\n确定购买？'
                                   % (row_data.get('name', goods_id), num, cost)):
            return
        save = app.current_save['index']
        button.config(state='disabled')
        status.set('正在连接并购买……')

        def worker():
            flow = None
            text = ''
            try:
                flow, _entry, _scene = app._connect_and_enter(save)
                buy(flow, goods_id, num, shop_type, app._log)
                text = '购买成功：%s × %d' % (row_data.get('name', goods_id), num)
            except Exception as exc:
                text = '购买停止：%s' % exc
                app._log('[商店] ' + text)
            finally:
                if flow:
                    flow.disconnect()

                def finish():
                    status.set(text)
                    button.config(state='normal')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    button = ttk.Button(tab, text='购买', command=start)
    button.pack(anchor='w', pady=6)
    ttk.Label(tab, text='提示：3级强化石 13004（27 主题币，周2）、2级宝石袋 28002（50 花印，周1）、'
                        '朱雀令 3030（160 联盟贡献，周1）。type 暂留空，购买失败可分别填 13、28、3。',
              wraplength=680).pack(anchor='w', pady=4)
