"""竞技场与斗宠大会：每局重新读取免费次数和对手。"""
import threading
import time
import random
import tkinter as tk
from tkinter import ttk


def checked(flow, route, params):
    result = flow.request(route, params, timeout=15)
    if result.get('code') != 200:
        raise RuntimeError(result.get('error', '请求失败：' + route))
    return result


def handler_name(cur, pet):
    return 'rankPetHandler' if pet else ('rankDoubleHandler' if cur.get('p2') else 'rankHandler')


def pet_arena_ids(cur):
    """报名阵容优先读取 clientStore.petArena；没有配队时从宠物栏取3只30级以上宠物。"""
    ids = [str(eid) for eid in ((cur.get('clientStore') or {}).get('petArena') or []) if eid]
    if len(ids) >= 3:
        return ids[:3], '当前配队'
    pets = ((cur.get('petList') or {}).get('pets') or [])
    candidates = [p for p in pets if isinstance(p, dict) and p.get('entityId')
                  and int(p.get('level') or 0) >= 30]
    candidates.sort(key=lambda p: int(p.get('level') or 0), reverse=True)
    picked = [str(p['entityId']) for p in candidates[:3]]
    if len(picked) < 3:
        raise RuntimeError('宠物栏不足3只30级以上宠物，不能报名斗宠大会')
    return picked, '宠物栏自动选择'


def apply_arena(flow, cur, pet, log):
    """报名竞技场/斗宠大会；斗宠提交纯 entityId 字符串数组。"""
    handler = handler_name(cur, pet)
    try:
        info = checked(flow, 'scene.' + handler + '.getCurRecordRankInfo',
                       {'recordId': cur['_id']}).get('curInfo') or {}
        if info.get('isApply') == 1:
            return '本赛季已报名，未重复提交'
    except Exception:
        pass
    params = {}
    if pet:
        ids, source = pet_arena_ids(cur)
        params['eIdArray'] = ids
        log('  斗宠报名阵容（%s）：%s' % (source, '、'.join(ids)))
    result = flow.request('scene.' + handler + '.applyArena', params, timeout=15)
    if result.get('code') != 200:
        raise RuntimeError(result.get('error', '报名失败'))
    return '报名成功'


def current_count(flow, cur, pet):
    # 次数来自本次登录的服务器存档，每次成功开始挑战后扣减；不调用找回次数接口。
    field = 'petArenaChallengeNum' if pet else 'arenaChallengeNum'
    if field not in cur:
        raise RuntimeError('未收到当前免费次数，停止挑战')
    return int(cur[field])


def state(flow, cur, pet=False):
    count = current_count(flow, cur, pet)
    handler = handler_name(cur, pet)
    rivals = checked(flow, 'rank.' + handler + '.getRivalInfo', {'recordId': cur['_id']}).get('rivalInfo', [])
    return count, rivals


def identity(row):
    return str(row.get('recordId')), str(row.get('rid')), str(row.get('uid'))



ARENA_ROBOT = '神秘竞技者'
PET_SPECIFIED = '指定对手（手动字段）'
PET_RECOMMENDED_HIGHEST = '推荐列表中战力最高'
PET_RANK_HIGHEST = '排行榜战力最高'
PET_RANK_RANDOM = '排行榜前N名随机'
PET_RANK_TOP_HIGHEST = '排行榜前N名战力最高'
PET_RANK_MODES = (PET_RANK_HIGHEST, PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST)


def read_ranking(flow, cur, pet=True):
    handler = handler_name(cur, pet)
    info = checked(flow, 'scene.' + handler + '.getCurRecordRankInfo',
                   {'recordId': cur['_id']}).get('curInfo') or {}
    season = info.get('currentArenaNum')
    if season is None:
        raise RuntimeError('未读取到当前赛季，停止查询')
    rows = checked(flow, 'rank.' + handler + '.getRankInfo',
                   {'arenaNum': season}).get('rankInfo')
    if not isinstance(rows, list):
        raise RuntimeError('排行榜数据异常')
    return season, rows


def complete_arena_identities(flow, cur, rows):
    # A UID alone is not enough: the same account can have multiple records.
    handler = handler_name(cur, False)
    sources = list(checked(flow, 'rank.' + handler + '.getRivalInfo',
                          {'recordId': cur['_id']}).get('rivalInfo') or [])
    try:
        _, pet_rows = read_ranking(flow, cur, True)
        sources.extend(pet_rows)
    except Exception:
        # Recommended opponents may still supply a unique full identity.
        pass
    mapping = {}
    for row in sources:
        if not isinstance(row, dict) or not all(row.get(k) is not None for k in ('uid', 'rid', 'recordId')):
            continue
        key = (str(row['uid']), str(row['rid']))
        mapping.setdefault(key, set()).add(str(row['recordId']))
    result = []
    for row in rows:
        row = dict(row)
        if row.get('recordId') is None:
            matches = mapping.get((str(row.get('uid')), str(row.get('rid'))), set())
            if len(matches) == 1:
                row['recordId'] = next(iter(matches))
        result.append(row)
    return result


def rank_snapshot(flow, cur, pet=True, top_n=None):
    """开打前锁定一份排行榜名单；竞技场榜缺存档ID的先按同UID＋rid唯一补齐。"""
    _, rows = read_ranking(flow, cur, pet)
    rows = [dict(row) for row in rows if isinstance(row, dict)]
    if not pet:
        rows = complete_arena_identities(flow, cur, rows)
    rows = [row for row in rows
            if int(row.get('rank') or 0) > 0
            and str(row.get('recordId')) != str(cur['_id'])]
    rows.sort(key=lambda row: int(row['rank']))
    if top_n is None:
        return rows
    return [row for row in rows if int(row['rank']) <= int(top_n)]


def usable_rank_rows(rows):
    return [row for row in rows
            if all(row.get(key) is not None for key in ('uid', 'rid', 'atkPoint', 'rank', 'recordId'))]


def choose_rank_opponent(rows, mode, top_n=10):
    candidates = [row for row in rows if int(row['rank']) > 0]
    if mode in (PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST):
        top_n = int(top_n)
        if not 1 <= top_n <= 100:
            raise ValueError('排行榜前N名须为1至100')
        candidates = [row for row in candidates if int(row['rank']) <= top_n]
    if not candidates:
        raise RuntimeError('当前排行榜范围内没有带可核实存档ID的对手')
    if mode in (PET_RANK_HIGHEST, PET_RANK_TOP_HIGHEST):
        return max(candidates, key=lambda row: int(row['atkPoint']))
    if mode == PET_RANK_RANDOM:
        return random.choice(candidates)
    raise ValueError('未知的排行榜挑战方式')


def manual_opponent(uid, record_id, rid):
    uid, record_id, rid = str(uid).strip(), str(record_id).strip(), str(rid).strip()
    if not uid.isascii() or not uid.isdecimal() or int(uid) <= 0:
        raise ValueError('pkUid须为有效的正整数账号UID')
    if not record_id or any(ch.isspace() for ch in record_id):
        raise ValueError('请填写有效的pkRecordId（对手存档ID，不能含空白）')
    if not rid or any(ch.isspace() for ch in rid):
        raise ValueError('请填写有效的rid（按竞技场目标字段原样填写）')
    # UI text must preserve the numeric type used by live arena records.
    typed_rid = int(rid) if rid.isascii() and rid.isdecimal() else rid
    return {'uid': int(uid), 'recordId': record_id, 'rid': typed_rid, 'name': 'UID ' + uid}


def lookup_pet_rank(flow, cur, field, query, pet=True):
    fields = {'UID': 'uid', '存档ID': 'recordId', '昵称': 'name'}
    query = str(query).strip()
    if field not in fields or not query:
        raise ValueError('请选择查询类型并填写查询内容')
    if field == 'UID' and (not query.isascii() or not query.isdecimal()):
        raise ValueError('UID应为数字；昵称请切换到昵称查询')
    season, rows = read_ranking(flow, cur, pet)
    if not pet:
        rows = complete_arena_identities(flow, cur, [row for row in rows if isinstance(row, dict)])
    key = fields[field]
    matches = [dict(row) for row in rows if isinstance(row, dict)
               and str(row.get(key, '')) == query]
    return season, len(rows), matches


def open_pet_rank_lookup(app, pet=True):
    prefix = 'petarena' if pet else 'arena'
    title = '斗宠' if pet else '竞技场'
    window = tk.Toplevel(app.root)
    window.title('按身份查询' + title + '榜')
    window.geometry('900x370')
    panel = ttk.Frame(window, padding=10)
    panel.pack(fill='both', expand=True)
    field = tk.StringVar(window, value='UID')
    query = tk.StringVar(window, value=getattr(app, 'var_' + prefix + '_target_uid').get())
    bar = ttk.Frame(panel)
    bar.pack(fill='x')
    ttk.Combobox(bar, textvariable=field, values=('UID', '存档ID', '昵称'), state='readonly', width=9).pack(side='left')
    ttk.Entry(bar, textvariable=query, width=30).pack(side='left', padx=6)
    status = ttk.Label(panel, text='精确匹配当前期前100条左右；竞技场缺少存档ID时尝试同UID＋rid唯一补齐，补不齐显示空白。查询不会挑战。', wraplength=850)
    status.pack(fill='x', pady=8)
    columns = ('name', 'rank', 'atkPoint', 'uid', 'recordId', 'rid')
    table_frame = ttk.Frame(panel)
    table_frame.pack(fill='both', expand=True)
    table = ttk.Treeview(table_frame, columns=columns, show='headings', height=8, selectmode='browse')
    for key, label, width in zip(columns, ('昵称', '排名', '战力', 'pkUid', 'pkRecordId', 'rid'), (150, 55, 90, 130, 180, 60)):
        table.heading(key, text=label)
        table.column(key, width=width, minwidth=45)
    scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=table.yview)
    table.configure(yscrollcommand=scrollbar.set)
    table.pack(side='left', fill='both', expand=True)
    scrollbar.pack(side='right', fill='y')
    results = {}
    result_owner = {'client': None, 'slot': None}

    def selected():
        ids = table.selection()
        if not ids:
            status.config(text='请先选择一条查询结果')
            return None
        return results.get(ids[0])

    def copy_fields():
        row = selected()
        if row is None:
            return
        text = 'pkUid=%s\npkRecordId=%s\nrid=%s' % (row.get('uid', ''), row.get('recordId', ''), row.get('rid', ''))
        window.clipboard_clear()
        window.clipboard_append(text)
        status.config(text='已复制选中玩家的三个字段')

    def fill_fields():
        row = selected()
        if row is None:
            return
        if app.client is not result_owner['client'] or not app.current_save or app.current_save['index'] != result_owner['slot']:
            status.config(text='账号或存档已切换，请重新查询')
            return
        if not all(row.get(k) is not None for k in ('uid', 'recordId', 'rid')):
            status.config(text='榜单未能唯一补齐存档ID，不能填入；请手动提供pkRecordId')
            return
        getattr(app, 'var_' + prefix + '_target_uid').set(str(row['uid']))
        getattr(app, 'var_' + prefix + '_target_record').set(str(row['recordId']))
        getattr(app, 'var_' + prefix + '_target_rid').set(str(row['rid']))
        status.config(text='已填入' + title + '指定对手字段；没有开始挑战，也没有更改打法')

    def search():
        if not app._ensure_login():
            return
        kind, value = field.get(), query.get().strip()
        if not value:
            status.config(text='请填写查询内容')
            return
        owner, slot = app.client, app.current_save['index']
        search_button.config(state='disabled')
        results.clear()
        for item in table.get_children():
            table.delete(item)
        result_owner.update(client=None, slot=None)
        status.config(text='正在查询当前' + title + '榜…')

        def work():
            flow = None
            data, error = None, None
            try:
                flow, _, scene = app._connect_and_enter(slot)
                data = lookup_pet_rank(flow, scene['curRecord'], kind, value, pet)
            except Exception as exc:
                error = str(exc)
            finally:
                if flow:
                    flow.disconnect()

            def finish():
                if not window.winfo_exists():
                    return
                search_button.config(state='normal')
                if error:
                    status.config(text='查询失败：' + error)
                    return
                if app.client is not owner or not app.current_save or app.current_save['index'] != slot:
                    status.config(text='账号或存档已切换，已丢弃旧查询结果')
                    return
                season, count, rows = data
                result_owner.update(client=owner, slot=slot)
                for index, row in enumerate(rows):
                    iid = str(index)
                    results[iid] = row
                    table.insert('', 'end', iid=iid, values=[row.get(k, '') for k in columns])
                if rows:
                    status.config(text='第%s期返回%d条记录，匹配%d条；同UID可能对应多个存档，请核对pkRecordId。' % (season, count, len(rows)))
                else:
                    status.config(text='第%s期返回的%d条记录中未找到匹配项；不代表该玩家不存在或未参赛。' % (season, count))
            app.root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    search_button = ttk.Button(bar, text='查询', command=search)
    search_button.pack(side='left')
    actions = ttk.Frame(panel)
    actions.pack(fill='x', pady=(8, 0))
    ttk.Button(actions, text='复制三个字段', command=copy_fields).pack(side='left')
    ttk.Button(actions, text='填入指定对手', command=fill_fields).pack(side='left', padx=6)
    ttk.Button(actions, text='关闭', command=window.destroy).pack(side='right')
    return window

def fight(flow, cur, rival, pet=False):
    if current_count(flow, cur, pet) <= 0:
        raise RuntimeError('免费次数已用完，停止挑战')
    handler = handler_name(cur, pet)
    params = {'pkRecordId': rival['recordId'], 'rid': rival['rid'], 'pkUid': int(rival['uid'])}
    if pet:
        ids = cur.get('clientStore', {}).get('petArena', [])
        if len(ids) < 3:
            raise RuntimeError('请先在游戏里设置三只出战宠物')
        params['eIdArray'] = [{'eId': eid} for eid in ids]
    result = checked(flow, 'scene.' + handler + '.beginBattle', params)
    if 'type' in result:
        errors = {1: '找不到己方参战的宠物', 2: '找不到对方参战的宠物'} if pet else {}
        raise RuntimeError(errors.get(result['type'], result.get('error', '挑战返回异常：%s' % result['type'])))
    field = 'petArenaChallengeNum' if pet else 'arenaChallengeNum'
    cur[field] = int(cur[field]) - 1
    time.sleep(0.3)
    result = checked(flow, 'scene.' + handler + '.endBattle', {'isSuccess': 1, 'pkRecordId': rival['recordId']})
    return result.get('addPetArenaCoin' if pet else 'addArenaCoin', 0)


def automatic_robot(flow, cur, pet, log, stop, update, limit):
    if pet or cur.get('p2'):
        raise ValueError('神秘竞技者方案仅支持单人竞技场存档')
    count = current_count(flow, cur, False)
    completed = 0
    log('  神秘竞技者：使用独立结算接口，不运行实际战斗模拟。')
    for _ in range(min(count, limit)):
        if stop and stop.is_set():
            break
        result = checked(flow, 'scene.rankHandler.robotBattle', {'isSuccess': 1})
        if result.get('error') or 'type' in result:
            raise RuntimeError(str(result.get('error') or '神秘竞技者返回异常'))
        count -= 1
        cur['arenaChallengeNum'] = count
        if 'arenaCoin' in result:
            cur['arenaCoin'] = result['arenaCoin']
        completed += 1
        log('  第%d局：神秘竞技者，获得%s竞技币' % (completed, result.get('addArenaCoin', 0)))
        if update:
            update(count, [])
        time.sleep(0.5)
    log('  已完成%d局，剩余免费次数%d' % (completed, count))


def automatic(flow, cur, pet, log, stop=None, update=None, mode="每把刷新重选", limit=10, top_n=10, target=None):
    limit = int(limit)
    if limit < 1:
        raise ValueError("挑战次数至少为1")
    if mode == ARENA_ROBOT:
        return automatic_robot(flow, cur, pet, log, stop, update, limit)
    specified = mode == PET_SPECIFIED
    if specified:
        if not isinstance(target, dict):
            raise ValueError('请填写指定对手的pkUid、pkRecordId和rid')
        target = manual_opponent(target.get('uid', ''), target.get('recordId', ''), target.get('rid', ''))
        if str(target['recordId']) == str(cur['_id']):
            raise ValueError('不能挑战自己的存档')
    ranked = mode in PET_RANK_MODES
    if mode in (PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST):
        top_n = int(top_n)
        if not 1 <= top_n <= 100:
            raise ValueError('排行榜前N名须为1至100')
    if ranked or specified:
        count, rivals = current_count(flow, cur, pet), []
    else:
        count, rivals = state(flow, cur, pet)
    ceiling = min(count, limit)
    completed = 0
    fixed = None
    ranked_pool = []
    if ranked:
        scan_n = top_n if mode in (PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST) else None
        snapshot = rank_snapshot(flow, cur, pet, scan_n)
        ranked_pool = usable_rank_rows(snapshot)
        scope = '前%d名' % top_n if scan_n else '全部'
        log('  已锁定排行榜%s，共%d人：' % (scope, len(snapshot)))
        for row in snapshot:
            mark = '' if row.get('recordId') is not None else '（缺存档ID，跳过）'
            log('    第%s名 %s 战力%s%s' % (row['rank'], row.get('name', '?'), row.get('atkPoint'), mark))
        if mode == PET_RANK_RANDOM:
            log('  可挑战%d人，将从这份名单中随机挑选。' % len(ranked_pool))
        else:
            log('  可挑战%d人，将固定选择名单中战力最高的对手。' % len(ranked_pool))
        if not ranked_pool:
            raise RuntimeError('排行榜%s没有带可核实存档ID的对手' % scope)
    while count > 0 and completed < ceiling and not (stop and stop.is_set()):
        if specified:
            rival = target
        elif ranked:
            rival = choose_rank_opponent(ranked_pool, mode, top_n)
            log('  选中排行榜第%s名：%s，战力%s' % (rival['rank'], rival.get('name', '?'), rival['atkPoint']))
        else:
            if not rivals:
                raise RuntimeError('没有可挑战的对手')
            if fixed is None or mode != '固定同一对手':
                selector = max if mode == PET_RECOMMENDED_HIGHEST else min
                fixed = selector(rivals, key=lambda row: int(row.get('atkPoint', 0)))
            rival = fixed
        if str(rival.get('recordId')) == str(cur['_id']):
            raise RuntimeError('不能挑战自己的存档')
        before = count
        coin = fight(flow, cur, rival, pet)
        completed += 1
        log('  第%d局：%s，获得%s币' % (completed, rival.get('name', '?'), coin))
        if ranked or specified:
            count = current_count(flow, cur, pet)
        else:
            count, rivals = state(flow, cur, pet)
        if update:
            update(count, rivals)
        if count >= before:
            raise RuntimeError('挑战后免费次数未减少，停止重复请求')
        time.sleep(0.5)
    log('  已完成%d局，剩余免费次数%d' % (completed, count))


def build_tabs(app):
    for pet, title in ((False, '竞技场'), (True, '斗宠大会')):
        build_tab(app, pet, title)


def build_tab(app, pet, title):
    page = ttk.Frame(app.daily_notebook, padding=10)
    app.daily_notebook.add(page, text=title)
    ttk.Label(page, text='是否纳入一键日常，请在“一键日常”面板勾选。', foreground='gray').pack(anchor='w')
    mode = tk.StringVar(value='每把刷新重选')
    setattr(app, 'var_petarena_mode' if pet else 'var_arena_mode', mode)
    settings = ttk.LabelFrame(page, text='挑战方式', padding=10)
    settings.pack(fill='x', pady=8)
    choices = ('固定同一对手', '每把刷新重选', PET_RECOMMENDED_HIGHEST,
               PET_RANK_HIGHEST, PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST, PET_SPECIFIED)
    if not pet:
        choices += (ARENA_ROBOT,)
    mode_row = ttk.Frame(settings)
    mode_row.pack(anchor='w', pady=4)
    ttk.Label(mode_row, text='打法：').pack(side='left')
    ttk.Combobox(mode_row, textvariable=mode, values=choices,
                 state='readonly', width=24).pack(side='left', padx=4)
    prefix = 'petarena' if pet else 'arena'
    top_n = tk.IntVar(value=10)
    setattr(app, 'var_' + prefix + '_top_n', top_n)
    rank_row = ttk.Frame(settings)
    rank_row.pack(anchor='w', pady=4)
    ttk.Label(rank_row, text='随机范围：排行榜前').pack(side='left')
    ttk.Spinbox(rank_row, from_=1, to=100, textvariable=top_n, width=6).pack(side='left')
    ttk.Label(rank_row, text='名（开打前锁定名单；随机模式每局抽，战力最高模式固定选最高；缺存档ID的跳过，最多100条）').pack(side='left')
    manual_frame = ttk.LabelFrame(settings, text='指定对手：手动填写身份字段', padding=6)
    manual_frame.pack(fill='x', pady=5)
    uid_var, record_var, rid_var = (tk.StringVar(value='') for _ in range(3))
    setattr(app, 'var_' + prefix + '_target_uid', uid_var)
    setattr(app, 'var_' + prefix + '_target_record', record_var)
    setattr(app, 'var_' + prefix + '_target_rid', rid_var)
    for row_index, (label, variable) in enumerate((
        ('pkUid（账号UID）', uid_var),
        ('pkRecordId（对手存档ID）', record_var),
        ('rid（竞技场返回的目标字段）', rid_var),
    )):
        ttk.Label(manual_frame, text=label + '：').grid(row=row_index, column=0, sticky='w', pady=2)
        ttk.Entry(manual_frame, textvariable=variable, width=34).grid(row=row_index, column=1, sticky='ew', pady=2)
    manual_frame.columnconfigure(1, weight=1)
    ttk.Label(manual_frame, text='仅指定对手打法使用这些字段。人物资料中的同名rid不能直接替代竞技场rid。', wraplength=650).grid(row=3, column=0, columnspan=2, sticky='w', pady=4)

    def get_manual_target():
        return manual_opponent(uid_var.get(), record_var.get(), rid_var.get())
    setattr(app, 'get_' + prefix + '_target', get_manual_target)
    ttk.Button(manual_frame, text='按UID / 存档ID / 昵称查' + title + '榜',
               command=lambda: open_pet_rank_lookup(app, pet)).grid(row=4, column=0, columnspan=2, sticky='w', pady=4)
    if not pet:
        ttk.Label(settings, text='按当前存档自动选择单人/双人竞技场。竞技场榜记录多数不含存档ID，只用同UID＋rid能在推荐/斗宠榜唯一补齐的对手；补不齐的自动跳过，不猜值。', wraplength=650).pack(anchor='w', pady=4)
    times = tk.IntVar(value=10)
    setattr(app, 'var_petarena_times' if pet else 'var_arena_times', times)
    count_row = ttk.Frame(settings)
    count_row.pack(anchor='w', pady=6)
    ttk.Label(count_row, text='挑战次数：').pack(side='left')
    ttk.Spinbox(count_row, from_=1, to=1000, textvariable=times, width=8).pack(side='left')
    status = ttk.Label(page, text='按所选方式选择对手，按设置次数执行')
    status.pack(anchor='w', pady=8)
    def refresh_count_status(scene):
        if scene is None:
            status.config(text='已切换存档，正在读取免费次数…')
        else:
            field = 'petArenaChallengeNum' if pet else 'arenaChallengeNum'
            count = (scene.get('curRecord') or {}).get(field)
            status.config(text='剩余免费次数：%s' % (count if count is not None else '未知'))
    if not hasattr(app, '_count_state_listeners'):
        app._count_state_listeners = []
    app._count_state_listeners.append(refresh_count_status)

    controls = ttk.Frame(page)
    controls.pack(fill='x', pady=8)
    stop = threading.Event()
    buttons = []

    def run(action):
        if not app._ensure_login():
            return
        save = app.current_save['index']
        selected_mode = mode.get()
        chosen_target, maximum, chosen_top_n = None, 0, 10
        if action == 'auto':
            try:
                chosen_target = getattr(app, 'get_' + prefix + '_target')() if selected_mode == PET_SPECIFIED else None
                maximum = times.get()
                chosen_top_n = top_n.get() if selected_mode in (PET_RANK_RANDOM, PET_RANK_TOP_HIGHEST) else 10
                if not 1 <= chosen_top_n <= 100:
                    raise ValueError("排行榜前N名须为1至100")
                if maximum < 1:
                    raise ValueError('挑战次数至少为1')
            except (ValueError, tk.TclError) as error:
                status.config(text=str(error) if isinstance(error, ValueError) else '请填写有效整数：次数至少1，排行榜随机范围1至100')
                return
        stop.clear()
        for button in buttons:
            button.config(state='disabled')
        stop_button.config(state='normal' if action == 'auto' else 'disabled')
        status.config(text='正在处理…')

        def update(count, rivals):
            app.root.after(0, lambda: status.config(text='槽%s：剩余免费次数%d' % (save, count)))

        def worker():
            flow = None
            try:
                flow, _, scene = app._connect_and_enter(save)
                cur = scene['curRecord']
                if action == 'claim':
                    route = 'scene.' + handler_name(cur, pet) + '.getArenaReward'
                    result = checked(flow, route, {})
                    money_key = 'petjjcMoney' if pet else 'jjcMoney'
                    balance = result.get(money_key)
                    message = '槽%s：赛季奖励领取成功' % save
                    if balance is not None:
                        message += '，当前%s币%s' % ('斗宠' if pet else '竞技', balance)
                    app._log('[%s领奖] %s；奖励编号%s，物品%s' % (
                        title, message, result.get('rewardId'), result.get('items', [])))
                    app.root.after(0, lambda text=message: status.config(text=text))
                elif action == 'apply':
                    message = '槽%s：%s' % (save, apply_arena(flow, cur, pet, app._log))
                    app._log('[%s报名] %s' % (title, message))
                    app.root.after(0, lambda text=message: status.config(text=text))
                else:
                    automatic(flow, cur, pet, app._log, stop, update, mode=selected_mode, limit=maximum, top_n=chosen_top_n, target=chosen_target)
            except Exception as error:
                text = str(error)
                app._log('[%s] %s' % (title, text))
                app.root.after(0, lambda: status.config(text=text + '；本次已停止。'))
            finally:
                if flow:
                    flow.disconnect()
                def finish():
                    for button in buttons:
                        button.config(state='normal')
                    stop_button.config(state='disabled')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    apply_button = ttk.Button(controls, text='报名', width=6, command=lambda: run('apply'))
    apply_button.pack(side='left', padx=4)
    buttons.append(apply_button)
    for label, action in (('开始挑战', 'auto'), ('赛季领奖', 'claim')):
        button = ttk.Button(controls, text=label, command=lambda action=action: run(action),
                            **({'width': 8} if action == 'claim' else {}))
        # 竞技场和斗宠大会都有“开始挑战”，在“我的日常”里用页签标题区分。
        button.daily_label = "%s·%s" % (title, label)
        button.pack(side='left', padx=4)
        buttons.append(button)
    stop_button = ttk.Button(controls, text='本局结束后停止', command=stop.set, state='disabled')
    stop_button.pack(side='left', padx=4)
    ttk.Label(page, text='报名时间：周六10:00至周日22:00；参赛时间：下周一00:00至周日23:00。非报名时段提交会被服务端拒绝。',
              foreground='#b35c00', wraplength=680).pack(anchor='w')
    ttk.Label(page, text='按所选方式选择对手；普通开局和胜利结算在同一连接完成，不运行实际战斗模拟、不使用扫荡参数。免费次数用完停止，不购买次数。', wraplength=680).pack(anchor='w')
    if pet:
        ttk.Label(page, text='报名阵容自动读取当前配队（clientStore.petArena）；游戏内未配队时从宠物栏选择3只30级以上宠物。', wraplength=680).pack(anchor='w')
    if not pet:
        ttk.Label(page, text='神秘竞技者仅限单人存档，使用独立结算接口，消耗竞技场免费次数；不运行实际战斗模拟。', wraplength=680).pack(anchor='w')
