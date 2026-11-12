"""超值礼包：读取官方最新配置，用灵魂购买本周在售礼包。"""
import datetime
import hashlib
import json
import re
import struct
import sys
import threading
import time
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path
from tkinter import ttk, messagebox

import requests

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
CACHE_FILE = BASE / 'super_gift_cache.json'
ROOT = 'https://sda.4399.com/4399swf/upload_swf/ftp15/csya/20150127/1/'
# 造四官方配置有防盗链：Referer 必须是游戏页，否则会返回 23KB 的占位 SWF
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/142.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
    'Referer': 'https://www.4399.com/flash/147621_4.htm',
}
MAX_AGE = 7 * 86400
EMPTY_AGE = 6 * 3600
MAX_SUFFIX = 4
MAX_CONFIGS = 4
TIME_FORMAT = '%Y/%m/%d-%H:%M:%S'


def _now():
    from datetime import timezone, timedelta
    return datetime.datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)


def _int(value, default=-1):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _parse_time(value):
    try:
        return datetime.datetime.strptime(str(value).strip(), TIME_FORMAT)
    except (TypeError, ValueError):
        return None


def _clean_name(name):
    return ''.join(ch for ch in name if ch.isprintable())


def _swf_blocks(data):
    """解析官方 mo2 配置文件，逐个返回 (块名, 解压内容)。"""
    if data[:3] != b'mo2':
        raise RuntimeError('配置文件不是 mo2 格式')
    count = struct.unpack('>H', data[3:5])[0]
    offset = 5 + 4 * count
    lengths = [struct.unpack('>I', data[5 + 4 * i:9 + 4 * i])[0] for i in range(count)]
    for size in lengths:
        compressed = data[offset:offset + size]
        offset += size
        try:
            raw = zlib.decompress(compressed, -15)
        except zlib.error:
            continue
        name_len = struct.unpack('>H', raw[:2])[0]
        name = raw[2:2 + name_len].decode('utf-8', errors='ignore')
        yield name, raw[2 + name_len + 2:]


def _mall_xml(data):
    for name, content in _swf_blocks(data):
        if _clean_name(name) == 'Mall.xml':
            return content
    raise RuntimeError('官方配置中没有找到 Mall.xml')


def _records(content):
    """同时兼容子元素文本（新配置）与属性（旧导出 JSON）两种记录结构。"""
    text = content.decode('utf-8-sig', errors='ignore')
    text = re.sub(r'<(/?)(\d)', r'<\1_\2', text)
    root = ET.fromstring(text)
    rows = []
    for element in root:
        if not isinstance(element.tag, str) or element.tag.upper() != 'RECORD':
            continue
        row = dict(element.attrib)
        for child in element:
            if isinstance(child.tag, str):
                row[child.tag] = (child.text or '').strip()
        rows.append(row)
    return rows


def parse_gifts(content, now=None):
    """筛出灵魂售价、限购大于 0 且当前处于上架期的礼包。"""
    now = now or _now()
    gifts = []
    for row in _records(content):
        spirit = _int(row.get('consumeSpirit'))
        limit = _int(row.get('purchaseMaxNum'), 0)
        if spirit <= 0 or limit <= 0:
            continue
        shelf = _parse_time(row.get('shelfTime'))
        under = _parse_time(row.get('underTime'))
        if shelf is None or under is None or not shelf <= now <= under:
            continue
        goods_id = _int(row.get('id'))
        if goods_id <= 0:
            continue
        gifts.append({
            'id': goods_id,
            'name': str(row.get('name') or goods_id),
            'spirit': spirit,
            'limit': limit,
            'shelfTime': str(row.get('shelfTime') or ''),
            'underTime': str(row.get('underTime') or ''),
            'itemId': str(row.get('itemId') or ''),
        })
    gifts.sort(key=lambda gift: (_parse_time(gift['underTime']) or now, gift['id']))
    return gifts


def _candidate_dates():
    today = _now().date()
    dates = [today - datetime.timedelta(days=offset) for offset in range(8)]
    monday = today - datetime.timedelta(days=today.weekday())
    dates += [monday - datetime.timedelta(weeks=week) for week in range(1, 7)]
    return sorted(set(dates), reverse=True)


def _download(session, day, suffix):
    name = 'cg1_%s_%d.swf' % (day.strftime('%Y%m%d'), suffix)
    url = ROOT + 'assets/data/' + name
    response = session.get(url, headers=HEADERS, timeout=(6, 30))
    if response.status_code != 200:
        return None
    data = response.content
    if data[:3] != b'mo2':
        return None
    if len(data) > 32 * 1024 * 1024:
        raise RuntimeError('配置文件异常，超过 32MB')
    return name, url, data


def _probe_day(session, day):
    """同一天可能先有 _1（周更完整包），周内再出 _2/_3；取当天序号最大的有效文件。"""
    best = None
    misses = 0
    for suffix in range(1, MAX_SUFFIX + 1):
        found = _download(session, day, suffix)
        if found:
            best = found
            misses = 0
            continue
        if best:
            break
        misses += 1
        if misses >= 2:
            break
    return best


def _candidate_configs(session):
    network_errors = 0
    for day in _candidate_dates():
        try:
            found = _probe_day(session, day)
        except requests.RequestException:
            network_errors += 1
            if network_errors >= 3:
                raise RuntimeError('无法连接官方配置服务器')
            continue
        network_errors = 0
        if found:
            yield found


def load_cache():
    try:
        saved = json.loads(CACHE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(saved, dict) or not isinstance(saved.get('gifts'), list):
        return None
    for gift in saved['gifts']:
        if not isinstance(gift, dict) or not all(
                key in gift for key in ('id', 'name', 'spirit', 'limit', 'underTime')):
            return None
    return saved


def cache_valid(cache):
    if not cache:
        return False
    if (cache.get('freeSchema') != 2 or not isinstance(cache.get('freeActivities'), list)
            or not isinstance(cache.get('freeRewards'), dict)
            or cache.get('argotSchema') != 1 or not isinstance(cache.get('argotRows'), list)):
        return False
    age = time.time() - float(cache.get('checkedAt') or 0)
    if age > (MAX_AGE if cache['gifts'] else EMPTY_AGE):
        return False
    ends = [_parse_time(gift['underTime']) for gift in cache['gifts']]
    ends = [end for end in ends if end is not None]
    return not ends or _now() <= min(ends)


def update_cycle_start(now=None):
    """返回最近一次周四11:00（GMT+8），作为本次配置更新周期起点。"""
    now = now or _now()
    if now.tzinfo is not None:
        now = now.astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
    start = (now - datetime.timedelta(days=(now.weekday() - 3) % 7)).replace(hour=11, minute=0, second=0, microsecond=0)
    return start if now >= start else start - datetime.timedelta(days=7)


def update_cycle_key(now=None):
    return update_cycle_start(now).isoformat(timespec='seconds') + '+08:00'


def automatic_update_due(cache, now=None):
    """本周期任意一天首次打开都可补更；只有成功过才跳过。"""
    now = now or _now()
    if now.tzinfo is not None:
        now = now.astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
    cache = cache or {}
    last_time = None
    try:
        last_time = datetime.datetime.fromisoformat(str(cache.get('lastSuccessfulUpdateAt', '')))
        if last_time.tzinfo is not None:
            last_time = last_time.astimezone(datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
    except (TypeError, ValueError):
        pass
    if last_time is None:
        # 兼容旧缓存；仅有日期而没有可核实时间时，本周期允许补更一次。
        try:
            last_time = datetime.datetime.fromtimestamp(
                float(cache.get('checkedAt')), datetime.timezone(datetime.timedelta(hours=8))).replace(tzinfo=None)
        except (ValueError, TypeError, OverflowError, OSError):
            pass
    if last_time is not None:
        return not (update_cycle_start(now) <= last_time <= now)
    return cache.get('lastSuccessfulUpdateCycle') != update_cycle_key(now)


def save_cache(result):
    body = dict(result)
    body['checkedAt'] = time.time()
    checked = _now()
    body['lastSuccessfulUpdateDate'] = checked.date().isoformat()
    body['lastSuccessfulUpdateAt'] = checked.isoformat(timespec='seconds') + '+08:00'
    body['lastSuccessfulUpdateCycle'] = update_cycle_key(checked)
    temporary = CACHE_FILE.with_suffix('.tmp')
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(CACHE_FILE)
    return body


def refresh(force=False):
    cache = load_cache()
    if not force and cache_valid(cache):
        return cache
    session = requests.Session()
    newest = None
    checked = 0
    try:
        for name, url, data in _candidate_configs(session):
            version = name[:-4]
            gifts = parse_gifts(_mall_xml(data))
            result = {
                'version': version,
                'url': url,
                'sha256': hashlib.sha256(data).hexdigest(),
                'gifts': gifts,
            }
            if newest is None:
                blocks = {_clean_name(block): content for block, content in _swf_blocks(data)
                          if _clean_name(block) in ('Activity.xml', 'Reward.xml', 'Argot.xml')}
                activity = blocks.get('Activity.xml')
                if activity is None:
                    raise RuntimeError('官方配置缺少Activity.xml，无法核实免费礼包')
                if 'Reward.xml' not in blocks:
                    raise RuntimeError('官方配置缺少Reward.xml，无法核实类型12免费奖励')
                if 'Argot.xml' not in blocks:
                    raise RuntimeError('官方配置缺少Argot.xml，无法核实暗语礼包')
                result['argotRows'] = _records(blocks['Argot.xml'])
                result['argotSchema'] = 1
                result['argotVersion'] = version
                result['freeActivities'] = [row for row in _records(activity) if str(row.get('type')) in ('6', '12')]
                reward_ids = {str(row.get('rewardId')) for row in result['freeActivities'] if row.get('type') == '12'}
                result['freeRewards'] = {str(row['id']): row for row in _records(blocks['Reward.xml']) if str(row.get('id')) in reward_ids}
                result['freeSchema'] = 2
                result['freeVersion'] = version
                newest = result
            else:
                # 灵魂礼包可能回溯旧包；免费活动始终以最新包为准。
                result['freeActivities'] = newest['freeActivities']
                result['freeVersion'] = newest['freeVersion']
                result['freeRewards'] = newest['freeRewards']
                result['freeSchema'] = newest['freeSchema']
                result['argotRows'] = newest['argotRows']
                result['argotSchema'] = newest['argotSchema']
                result['argotVersion'] = newest['argotVersion']
            if gifts:
                return save_cache(result)
            checked += 1
            if checked >= MAX_CONFIGS:
                break
        if newest is not None:
            return save_cache(newest)
        raise RuntimeError('最近 6 周没有找到可用的官方配置文件')
    finally:
        session.close()


def _short_time(value):
    parsed = _parse_time(value)
    return parsed.strftime('%m月%d日 %H:%M') if parsed else (value or '-')


def purchased_count(scene, goods_id):
    record = (scene or {}).get('curRecord') or {}
    entries = record.get('specialItemBuyNum') or []
    if isinstance(entries, dict):
        entries = list(entries.values())
    for entry in entries:
        if isinstance(entry, dict) and str(entry.get('goodsId')) == str(goods_id):
            return int(entry.get('num') or 0)
    return 0


def purchase_ok(reply):
    """商城接口成功回包通常带 code 200；也兼容不带 code 但带余额/商品字段的回包。"""
    if not isinstance(reply, dict) or reply.get('error'):
        return False
    code = reply.get('code')
    if code is not None:
        try:
            return int(code) == 200
        except (TypeError, ValueError):
            return False
    return any(key in reply for key in ('spirit', 'gem', 'goodsId', 'curGoodsNum', 'itemList'))


def build_tab(app):
    page = ttk.Frame(app.notebook, padding=10)
    app.notebook.add(page, text='超值礼包')
    state = {'cache': None, 'busy': False}

    header = ttk.Frame(page)
    header.pack(fill='x')
    ttk.Label(header, text='本周灵魂超值礼包', font=('微软雅黑', 12, 'bold')).pack(side='left')
    ttk.Label(header, text='自动读取官方最新配置，仅显示当前上架、可用灵魂购买且有购买上限的礼包。',
              foreground='#666').pack(side='left', padx=10)

    ttk.Label(page, text='配置来源：', foreground='#666').pack(anchor='w', pady=(8, 2))
    lbl_status = ttk.Label(page, text='尚未读取官方配置，正在自动检查…', wraplength=900)
    lbl_status.pack(anchor='w')

    table = ttk.Frame(page)
    table.pack(fill='both', expand=True, pady=8)
    columns = ('name', 'spirit', 'limit', 'ends', 'id')
    tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='extended', height=7)
    for column, title, width in (('name', '礼包', 260), ('spirit', '灵魂价格', 100),
                                 ('limit', '限购', 60), ('ends', '结束时间', 140),
                                 ('id', '商品ID', 90)):
        tree.heading(column, text=title)
        tree.column(column, width=width, anchor='center' if column != 'name' else 'w')
    scroll = ttk.Scrollbar(table, orient='vertical', command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side='left', fill='both', expand=True)
    scroll.pack(side='right', fill='y')

    actions = ttk.Frame(page)
    actions.pack(fill='x')
    btn_check = ttk.Button(actions, text='检查更新', command=lambda: refresh_clicked())
    btn_check.pack(side='left', padx=(0, 6))
    btn_select_all = ttk.Button(actions, text='全选',
                                command=lambda: (tree.selection_set(tree.get_children()),
                                                 update_total()))
    btn_select_all.pack(side='left', padx=6)
    btn_selected = ttk.Button(actions, text='购买选中礼包', state='disabled',
                              command=lambda: buy_selected())
    btn_selected.pack(side='left', padx=6)
    btn_all = ttk.Button(actions, text='一键购齐本周礼包', state='disabled',
                         command=lambda: buy_all())
    btn_all.pack(side='left', padx=6)
    lbl_total = ttk.Label(actions, text='选中合计：0 灵魂', foreground='#666')
    lbl_total.pack(side='left', padx=10)

    note = ttk.Label(page, text='限购次数按账号计算；已购满的礼包会自动跳过，购买前请确认灵魂余额。',
                     foreground='orange', wraplength=900)
    note.pack(anchor='w', pady=(6, 0))
    ttk.Label(page, text='配置更新周期：每周四11:00（GMT+8）起；本周期首次打开自动补更，成功后不重复。可随时手动检查更新。',
              foreground='#666', wraplength=900).pack(anchor='w', pady=(4, 0))

    from free_activity_gifts import build_panel
    update_free_gifts = build_panel(app, page, state,
                                   lambda busy: set_busy(busy), lambda: refresh_clicked())

    def gifts_by_selection():
        result = []
        for iid in tree.selection():
            rows = state['cache']['gifts'] if state['cache'] else []
            gift = next((g for g in rows if str(g['id']) == iid), None)
            if gift:
                result.append(gift)
        return result

    def update_total(*_):
        total = sum(gift['spirit'] * gift['limit'] for gift in gifts_by_selection())
        lbl_total.config(text='选中合计：%d 灵魂' % total)

    tree.bind('<<TreeviewSelect>>', update_total)

    def set_busy(busy, text=None):
        state['busy'] = busy
        status = 'disabled' if busy else ('normal' if state['cache'] and state['cache']['gifts'] else 'disabled')
        btn_check.config(state='disabled' if busy else 'normal')
        for button in (btn_selected, btn_all):
            button.config(state=status)
        if text:
            lbl_status.config(text=text)

    def status_text(prefix=''):
        cache = state['cache']
        if not cache:
            return prefix + '尚未读取官方配置'
        checked = datetime.datetime.fromtimestamp(float(cache.get('checkedAt') or 0),
                                                  datetime.timezone(datetime.timedelta(hours=8)))
        if cache['gifts']:
            total = sum(gift['spirit'] * gift['limit'] for gift in cache['gifts'])
            return '%s配置 %s · %s 检查 · 本周 %d 个礼包，购齐需 %d 灵魂' % (
                prefix, cache['version'], checked.strftime('%m月%d日 %H:%M'),
                len(cache['gifts']), total)
        return '%s配置 %s · %s 检查 · 本周暂无灵魂在售礼包' % (
            prefix, cache['version'], checked.strftime('%m月%d日 %H:%M'))

    def apply_cache(cache):
        state['cache'] = cache
        for row in tree.get_children():
            tree.delete(row)
        for gift in cache['gifts']:
            tree.insert('', 'end', iid=str(gift['id']), values=(
                gift['name'], gift['spirit'], gift['limit'], _short_time(gift['underTime']), gift['id']))
        lbl_status.config(text=status_text())
        update_total()
        set_busy(False)
        update_free_gifts(cache)

    def fail(error, prefix=''):
        lbl_status.config(text=prefix + '读取官方配置失败：%s；可稍后点击「检查更新」重试。' % error)
        set_busy(False)

    def refresh_clicked():
        if state['busy']:
            return
        set_busy(True, '正在检查官方最新配置…（约 2MB，请稍候）')

        def worker():
            try:
                cache = refresh(force=True)
                app.root.after(0, lambda: apply_cache(cache))
            except Exception as error:
                app.root.after(0, lambda text=str(error): fail(text))
        threading.Thread(target=worker, daemon=True).start()

    def buy_selected():
        gifts = gifts_by_selection()
        if not gifts:
            messagebox.showinfo('超值礼包', '请先在列表中选中要购买的礼包')
            return
        buy(gifts, '购买选中礼包')

    def buy_all():
        if not state['cache'] or not state['cache']['gifts']:
            return
        buy(state['cache']['gifts'], '一键购齐本周礼包')

    def buy(gifts, title):
        if state['busy'] or not app._ensure_login():
            return
        total = sum(gift['spirit'] * gift['limit'] for gift in gifts)
        detail = '\n'.join('  %s ×%d（%d 灵魂）' % (gift['name'], gift['limit'],
                                                  gift['spirit'] * gift['limit']) for gift in gifts)
        if not messagebox.askyesno('确认购买', '存档：%s\n%s\n最多合计：%d 灵魂\n\n%s吗？' % (
                app.current_save['name'], detail, total, title)):
            return
        slot, client = app.current_save['index'], app.client
        set_busy(True, '正在购买本周礼包…')

        def worker():
            flow = None
            bought = failed = skipped = 0
            remaining = None
            spirit = 0
            try:
                if app.client is not client:
                    raise RuntimeError('账号已切换，停止购买')
                flow, entry, scene = app._connect_and_enter(slot)
                record = scene.get('curRecord') or entry.get('record') or {}
                spirit = int(record.get('spirit') or 0)
                app._log('[超值礼包] 存档 %s 当前灵魂 %d，计划最多消耗 %d' % (
                    app.current_save['name'], spirit, total))
                for gift in gifts:
                    already = purchased_count(scene, gift['id'])
                    if already >= gift['limit']:
                        skipped += 1
                        app._log('[超值礼包] %s 已购 %d/%d，本周无需再买，跳过' % (
                            gift['name'], already, gift['limit']))
                        continue
                    for _ in range(gift['limit'] - already):
                        if spirit < gift['spirit']:
                            failed += 1
                            app._log('[超值礼包] %s 灵魂不足（需要 %d，当前 %d），跳过' % (
                                gift['name'], gift['spirit'], spirit))
                            break
                        reply = flow.request('scene.mallHandler.buySpecialItem',
                                             {'buyList': [{'id': gift['id'], 'count': 1}]},
                                             timeout=20)
                        if not purchase_ok(reply):
                            failed += 1
                            reason = (reply.get('error') or reply.get('code')) if isinstance(reply, dict) else reply
                            app._log('[超值礼包] %s 购买失败：%s' % (gift['name'], reason))
                            break
                        before = spirit
                        if reply.get('spirit') is not None:
                            try:
                                spirit = int(reply['spirit'])
                            except (TypeError, ValueError):
                                spirit = before - gift['spirit']
                            if spirit != before - gift['spirit']:
                                raise RuntimeError('购买 %s 后灵魂余额异常（%d→%d，单价 %d），已停止' % (
                                    gift['name'], before, spirit, gift['spirit']))
                        else:
                            spirit = before - gift['spirit']
                        already += 1
                        if reply.get('goodsId') is not None and str(reply['goodsId']) != str(gift['id']):
                            raise RuntimeError('%s 的服务器回包商品ID不一致，已停止' % gift['name'])
                        if reply.get('curGoodsNum') is not None:
                            try:
                                if int(reply['curGoodsNum']) != already:
                                    raise RuntimeError('%s 的限购计数未按预期增加，已停止' % gift['name'])
                            except (TypeError, ValueError):
                                pass
                        bought += 1
                        remaining = spirit
                        app._log('[超值礼包] 购买 %s 1 个（%d/%d），消耗 %d 灵魂，剩余 %d' % (
                            gift['name'], already, gift['limit'], gift['spirit'], spirit))
                parts = ['成功 %d 件' % bought]
                if skipped:
                    parts.append('跳过已购满 %d 件' % skipped)
                if failed:
                    parts.append('失败 %d 项' % failed)
                app._log('[超值礼包] 结束：%s，剩余灵魂 %d' % ('，'.join(parts), spirit))
            except Exception as error:
                app._log('[超值礼包] 异常：%s' % error)
                failed += 1
            finally:
                if flow:
                    try:
                        flow.disconnect()
                    except Exception:
                        pass

                def done():
                    suffix = ' · 本次已购 %d 件' % bought if bought else ''
                    set_busy(False, status_text(suffix and '已购买：' or '') + suffix)
                    if bought and not failed:
                        messagebox.showinfo('超值礼包', '已购买 %d 件，跳过 %d 件，剩余灵魂 %s' % (
                            bought, skipped, remaining if remaining is not None else '未知'))
                    elif bought or failed:
                        messagebox.showwarning('超值礼包', '完成 %d 件，失败 %d 项。\n详情见底部日志。' % (
                            bought, failed))
                app.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()

    cache = load_cache()
    if cache:
        apply_cache(cache)
    else:
        lbl_status.config(text='暂无本地配置，正在检查本周期配置；也可点击「检查更新」手动获取。')
    def automatic_refresh():
        # 真正开始前重读文件，兼容等待期间另一次手动更新已经完成。
        if automatic_update_due(load_cache()): refresh_clicked()
    if automatic_update_due(cache):
        app.root.after(300, automatic_refresh)
