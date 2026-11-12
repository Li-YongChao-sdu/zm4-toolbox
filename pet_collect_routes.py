"""免费宠装采集；历史选择按账号/存档隔离，只有明确成功才记录派遣。"""
import json
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta

BASE = Path(__file__).resolve().parent
HISTORY = BASE / 'pet_collect_history.json'

def slots_of(state):
    slots = (state.get('petCollect') or {}).get('slots') or {}
    return slots if isinstance(slots, dict) else {str(i): s for i, s in enumerate(slots) if s}

def source(slot):
    data = slot.get('data') or {}
    pet, prop = data.get('pet') or {}, data.get('prop') or {}
    eid = pet.get('entityId') or slot.get('entityId')
    index = int(prop.get('index') or 0)
    return {'entityId': eid, 'prop_index': index} if eid and 1 <= index <= 5 else None

def used_count(entry, scene, state):
    stamp = int(state['serverTime'])
    day = (datetime.fromtimestamp(stamp/1000, timezone(timedelta(hours=8))).weekday()+1)%7
    record = scene['curRecord']
    key = '%s_%s_petCollect' % (record['_id'], day)
    buckets = [entry, entry.get('record', {}), scene, record, state]
    return max([int((b.get('everyWeekSetting') or {}).get(key, 0)) for b in buckets])

def work(app, request, entry, scene, action, pet_id, prop_index):
    rows = json.loads((BASE/'output_cg1_20260921_1_2/136___PetCollect.xml.json').read_text(encoding='utf-8'))['RECORD']
    config = next(r for r in rows if str(r['id']) == '1')
    names = {str(r['id']): r.get('name', r['id']) for r in json.loads((BASE/'output_cg1_20260921_1_2/132___Pet.xml.json').read_text(encoding='utf-8'))['RECORD']}
    props = {i: json.loads(config['item%d'%i]) for i in range(1,6)}
    route = 'scene.playerFourthHandler.'
    state = request(route+'getPetCollectData', {})
    slots = slots_of(state)
    used = used_count(entry, scene, state)
    pets = (scene['curRecord'].get('petList') or {}).get('pets') or []
    if isinstance(pets, dict): pets = list(pets.values())
    key = str(app.client.uid)+':'+str(scene['curRecord']['_id'])
    try: history = json.loads(HISTORY.read_text(encoding='utf-8'))
    except FileNotFoundError: history = {}
    today = datetime.fromtimestamp(int(state['serverTime'])/1000, timezone(timedelta(hours=8))).date().isoformat()
    daily = history.get(key+':daily') or {}
    if daily.get('date') == today: used = max(used, int(daily.get('used',0)))
    def save(records):
        history[key] = records
        history[key+':last'] = list(last)
        history[key+':daily'] = {'date':today, 'used':used}
        tmp = HISTORY.with_suffix('.tmp')
        tmp.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(tmp, HISTORY)
    records = list(history.get(key) or [])
    max_slot = int((state.get('petCollect') or {}).get('maxSlot', 0) or 0)
    last = [r for r in (history.get(key + ':last') or []) if isinstance(r, dict)]
    if max_slot:
        last = last[-max_slot:]
    if not last and max_slot:
        last = list(records[-max_slot:])
    # Official client also stores the previous choices; recover after an upgrade.
    stored = (scene['curRecord'].get('clientStore') or {}).get('petCollect') or {}
    if isinstance(stored, str): stored = json.loads(stored)
    for slot in list(slots.values()) + (list(stored.values()) if isinstance(stored, dict) else []):
        item = source(slot if 'data' in slot else {'data':slot})
        if item and not any(r['entityId'] == item['entityId'] for r in records): records.append(item)
    if records: save(records)
    def refresh():
        nonlocal state, slots
        state = request(route+'getPetCollectData', {}) 
        slots = slots_of(state)
    def claim_ready(only_pos=None):
        nonlocal state, slots
        ready = [(p, s) for p, s in slots.items()
                 if s and int(s.get('time', 0)) <= int(state['serverTime'])]
        if only_pos is not None:
            ready = [(p, s) for p, s in ready if str(p) == str(only_pos)]
        for pos, slot in ready:
            item = source(slot)
            if item:
                records[:] = [r for r in records if r['entityId'] != item['entityId']] + [item]
                if not any(r['entityId'] == item['entityId'] for r in last):
                    last.append(dict(item))
                if max_slot: last[:] = last[-max_slot:]
            if records: save(records)  # Persist identity BEFORE the slot disappears.
            result = request(route+'petCollectEnd', {'pos':int(pos), 'type':0})
            app._log('[宠物采集] 免费领取：'+json.dumps(result,ensure_ascii=False))
        if ready: refresh()
        return len(ready)
    if action == 'claim':
        selected = getattr(app, '_collect_selected_slot', None)
        if not any(str(p) == str(selected) and s and int(s.get('time', 0)) <= int(state['serverTime'])
                   for p, s in slots.items()):
            raise RuntimeError('请选中已完成的采集；全部领取请用“一键领取”')
        claim_ready(selected)
    elif action == 'claimall':
        if not claim_ready():
            app._log('[宠物采集] 没有已完成采集，不发送付费加速')
    def begin(eid, index):
        nonlocal used
        collect = state.get('petCollect') or {}
        if int(collect.get('v',-1)) != int(config['activeId']): raise RuntimeError('采集版本不一致，请更新配置')
        if used >= int(config['dayMax']): raise RuntimeError('今日免费采集次数已用完')
        pet = next((p for p in pets if p.get('entityId') == eid), None)
        prop = props[index]
        if not pet or int(pet.get('level',0)) < int(prop['level']): raise RuntimeError('宠物不存在或等级不足')
        if int(pet.get('status',0)) != 0: raise RuntimeError('该宠物正在出战，请手动收回后派遣')
        if any((source(s) or {}).get('entityId') == eid for s in slots.values()): raise RuntimeError('该宠物仍在采集')
        pos = next((i for i in range(int(collect.get('maxSlot',0))) if not slots.get(str(i))), None)
        if pos is None: raise RuntimeError('没有空闲采集槽位')
        request(route+'petCollectBegin', {'data':{'index':pos,'pet':pet,'prop':prop},'pos':pos,'entityId':eid,'index':index})
        used += 1
        refresh()
        slot = next((s for s in slots.values() if (source(s) or {}).get('entityId') == eid), None)
        if slot is None: raise RuntimeError('派遣回包后槽位未确认，不重复提交')
        actual_info = ((slot.get('data') or {}).get('prop') or {})
        actual = int(actual_info.get('index') or index)
        actual_name = actual_info.get('name') or props.get(actual, {}).get('name') or str(actual)
        item = {'entityId':eid,'prop_index':actual}
        records[:] = [r for r in records if r['entityId'] != eid] + [item]
        last[:] = [r for r in last if r['entityId'] != eid] + [item]
        if max_slot: last[:] = last[-max_slot:]
        save(records)
        if actual != index:
            app._log('[宠物采集] 注意：请求%s，服务器实际使用%s' % (prop['name'], actual_name))
        app._log('[宠物采集] 派遣成功：%s；%s分钟后免费领取'%(actual_name,config['collectTime']))
    if action == 'begin': begin(pet_id, prop_index)
    elif action == 'rebegin':
        if not last and not records:
            app._log('[宠物采集] 没有上次采集记录，按当前材料与等级自动选择宠物')
        sources = list(last) if last else list(records[-(max_slot or 3):])
        seen = set()
        sources = [s for s in sources if s.get('entityId') and
                   not (s['entityId'] in seen or seen.add(s['entityId']))]
        errors = []
        try:
            claimed = claim_ready()
        except Exception as error:
            claimed = 0
            errors.append('领取失败：%s' % error)
        started = 0
        for item in sources:
            eid = item['entityId']; index = int(item.get('prop_index') or 0)
            if not 1 <= index <= 5:
                errors.append('宠物%s的材料记录无效' % eid); continue
            if any((source(s) or {}).get('entityId') == eid for s in slots.values()):
                errors.append('宠物%s仍在采集' % eid); continue
            try:
                begin(eid, index); started += 1
            except Exception as error:
                errors.append(str(error))
                if '今日免费采集次数已用完' in str(error): break
        index = int(prop_index or 0)
        if 1 <= index <= 5:
            budget = int(config['dayMax']) - used
            free = int((state.get('petCollect') or {}).get('maxSlot', 0)) - len([s for s in slots.values() if s])
            prop = props[index]
            if budget > 0 and free > 0:
                busy = {(source(s) or {}).get('entityId') for s in slots.values()}
                candidates = sorted((p for p in pets
                    if int(p.get('level', 0)) >= int(prop['level'])
                    and int(p.get('status', 0)) == 0 and p.get('entityId') not in busy),
                    key=lambda p: -int(p.get('level', 0)))
                if not candidates:
                    app._log('[宠物采集] 没有满足%s等级要求（%s级）的可补位宠物' % (
                        prop['name'], prop['level']))
                for pet in candidates:
                    if budget <= 0 or free <= 0: break
                    try:
                        begin(pet['entityId'], index)
                        started += 1; budget -= 1; free -= 1
                        app._log('[宠物采集] 自动补位：%s' % (pet.get('newName') or pet.get('entityId')))
                    except Exception as error:
                        errors.append(str(error))
                        if '今日免费采集次数已用完' in str(error) or '没有空闲采集槽位' in str(error):
                            break
        if started == 0:
            raise RuntimeError(errors[0] if errors else '没有可再次采集的宠物')
        for error in errors:
            app._log('[宠物采集] 跳过再次采集：%s' % error)
        app._log('[宠物采集] 再次派遣完成：领取 %s 个，开始 %s 个槽位' % (claimed, started))
    app.root.after(0, lambda: app._show_pet_collect(state, pets, names, used))
    return {'state':state, 'used':used, 'records':records}
