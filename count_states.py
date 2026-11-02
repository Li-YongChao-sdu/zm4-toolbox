"""Switch-save count refresh. One captured slot, one connection, guarded UI callbacks."""
import ast
import copy
import inspect
import textwrap
import threading
import types

class Cancelled(Exception): pass

def usage(scene):
    history = (scene.get('curRecord') or {}).get('copyHistory')
    if not isinstance(history, (dict, list)):
        raise RuntimeError('服务器未返回关卡次数记录，不能按已用0次处理')
    result = {}
    entries = history.items() if isinstance(history, dict) else enumerate(history)
    for key, row in entries:
        if isinstance(row, dict):
            mid = row.get('id', row.get('mid', key if isinstance(history, dict) else None))
            count = row.get('num', row.get('dailyCount', row.get('count')))
        elif isinstance(history, dict):
            mid, count = key, row
        else:
            raise RuntimeError('关卡次数格式异常')
        if mid is None or count is None:
            raise RuntimeError('关卡次数记录缺少ID或次数')
        mid, count = int(mid), int(count)
        if count < 0: raise RuntimeError('关卡已用次数为负数')
        result[mid] = count
    return result


def refresh(app):
    app._count_generation = getattr(app, '_count_generation', 0) + 1
    generation, client = app._count_generation, app.client
    slot = app.current_save['index'] if app.current_save else None
    def current():
        return (app._count_generation == generation and app.client is client and
                app.current_save is not None and app.current_save['index'] == slot)
    def post(callback):
        app.root.after(0, lambda: callback() if current() else None)
    app._main_daily_counts = None
    app._all_count_snapshot = None
    # Clear every named counter before network I/O; never retain the previous slot's numbers.
    for name, widget in vars(app).copy().items():
        if name.startswith('lbl_') and any(s in name for s in ('remain','dailycount','power','week','quota','zhuanlun','wanted')):
            try: widget.config(text='槽%s：正在刷新…' % slot)
            except Exception: pass
    for variable in getattr(app, 'mount_remain_labels', {}).values(): variable.set('正在刷新…')
    for group in getattr(app, 'special_groups', {}).values(): group['remaining'].config(text='正在刷新…')
    for _, label, button in getattr(app, 'event_dungeon_rows', {}).values():
        label.config(text='正在刷新…'); button.config(state='disabled')
    for callback in getattr(app, '_count_state_listeners', []): callback(None)
    if slot is None or app.current_save.get('empty') or app.current_save.get('unavailable'):
        return
    class Root:
        def after(self, delay, callback, *args):
            return app.root.after(delay, lambda: callback(*args) if current() else None)
        def __getattr__(self, name): return getattr(app.root, name)
    class Flow:
        def request(self, route, body, **kwargs):
            if not current(): raise Cancelled()
            allowed = ('scene.playerThirdHandler.getTimeGiftInfo', 'scene.holidayHandler.getPanTaoActInfo',
                       'scene.taskHandler.lookupWantedTask', 'scene.taskHandler.lookupShenYuWantedTask')
            if route not in allowed: raise RuntimeError('次数刷新禁止调用：' + route)
            return flow.request(route, body, **kwargs)
        def disconnect(self): pass
    class Snapshot:
        root = Root()
        def __setattr__(self, name, value):
            if current(): setattr(app, name, value)
        def __getattr__(self, name):
            value = getattr(app, name)
            if inspect.ismethod(value) and value.__self__ is app:
                return types.MethodType(value.__func__, self)
            return value
        def _connect_and_enter(self, *args):
            if not current(): raise Cancelled()
            return Flow(), entry, scene
        def _log(self, text):
            if current(): app._log(text)
    def worker():
        nonlocal flow, entry, scene
        try:
            flow, entry, raw = app._connect_and_enter(slot)
            if not current(): return
            scene = copy.deepcopy(raw)
            cur = scene.get('curRecord') or {}
            counts = usage(scene)
            history = [{'id': mid, 'num': num, 'dailyCount': num} for mid, num in counts.items()]
            cur['copyHistory'] = history
            scene.setdefault('record', {})['levels'] = history
            cur['dailyCount'] = {str(mid): num for mid, num in counts.items()}
            def basic():
                app._all_count_snapshot = {'slot': slot, 'counts': counts, 'scene': raw}
                app._cache_main_dailycount(raw, slot)
                for label_name in ('lbl_nm_power','lbl_sj_power'):
                    getattr(app, label_name).config(text='当前体力: %s' % cur.get('collectPower', '未知'))
                app.lbl_sj_week.config(text='镜域周剩余: %d' % app._get_jingyu_week_remain(cur))
                for callback in getattr(app, '_count_state_listeners', []): callback(raw)
            post(basic)
            proxy = Snapshot()
            # Reuse each page's existing read-only count renderer, including shared group rules.
            methods = ('_do_pet_check', '_do_beiming_check', '_do_mount_check',
                       '_taigu_check_worker', '_luoxuan_check_worker', '_luohan_check_worker',
                       '_special_check_worker', '_event_dungeons_refresh_worker',
                       '_timeboat_check_worker', '_time_check_worker', '_do_daily_task_check',
                       '_count_wanted_worker', '_shenyu_wanted_refresh_worker')
            for name in methods:
                if not current(): return
                try:
                    if name == '_time_check_worker' and not hasattr(app, 'time_gift_items'):
                        continue
                    method = getattr(app, name)
                    if name.startswith('_do_'):
                        node = ast.parse(textwrap.dedent(inspect.getsource(method))).body[0]
                        nested = next(x for x in node.body if isinstance(x, ast.FunctionDef) and x.name == 'worker')
                        nested.args.args.insert(0, ast.arg(arg='self'))
                        module = ast.fix_missing_locations(ast.Module(body=[nested], type_ignores=[]))
                        env = dict(method.__func__.__globals__)
                        env['_count_generation'] = generation
                        env['slot'] = slot
                        exec(compile(module, '<count-refresh>', 'exec'), env)
                        env['worker'](proxy)
                    else:
                        method.__func__(proxy)
                except Cancelled: return
                except Exception as error:
                    if current(): app._log('[次数刷新] %s：%s' % (name, error))
            if current(): app._log('[次数刷新] 槽%s：主线、噩梦、神域/镜域、宠物装备、坐骑、太古、螺旋、罗汉、地藏/虚空藏、活动副本及日常任务状态已刷新。' % slot)
        except Exception as error:
            if current():
                app._log('[次数刷新] 槽%s读取失败：%s；不沿用旧存档次数。' % (slot, error))
                def failed():
                    for name, widget in vars(app).copy().items():
                        if name.startswith('lbl_') and any(s in name for s in ('remain','dailycount','power','week','quota','zhuanlun','wanted')):
                            try: widget.config(text='槽%s：读取失败，请刷新' % slot)
                            except Exception: pass
                post(failed)
        finally:
            if flow:
                try: flow.disconnect()
                except Exception: pass
    flow = entry = scene = None
    threading.Thread(target=worker, daemon=True).start()
