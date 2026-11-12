"""Craft UI operations: fresh sessions, frozen identity and main-thread UI updates."""
import math
import threading
import time
from tkinter import messagebox
from toolbox_identity import identity_busy, same_identity, require_identity, lock_controls

def _counts(scene):
    bag = (scene.get('curRecord') or {}).get('itemsBag')
    if not isinstance(bag, dict) or not isinstance(bag.get('items'), (list, dict)):
        raise RuntimeError('未收到道具背包，停止打造')
    rows = bag['items'].values() if isinstance(bag['items'], dict) else bag['items']
    result = {}
    for row in rows:
        key = str(row.get('id', row.get('itemId', '')))
        result[key] = result.get(key, 0) + int(row.get('count', row.get('num', 0)) or 0)
    return result

def _checked(flow, route, body):
    result = flow.request(route, body, timeout=15)
    if not isinstance(result, dict) or result.get('code') != 200 or result.get('error'):
        raise RuntimeError(str(result.get('error') or result.get('code')) if isinstance(result, dict) else '请求回包异常')
    return result

def _close(flow):
    if flow is not None:
        try: flow.disconnect()
        except Exception: pass

def refresh_materials(app):
    if not app._ensure_login(): return
    if identity_busy(app) or getattr(app, '_craft_refresh_running', False):
        app._log('[打造] 当前任务运行中，请稍后刷新材料')
        return
    client, slot = app.client, app.current_save['index']
    book = app._craft_book_ids.get(app.var_craft_book.get(), 119460002)
    app._craft_refresh_running = True
    def worker():
        flow = None
        try:
            flow, _, scene = app._connect_and_enter(slot, expected_client=client)
            counts = _counts(scene)
            text = '制作书(%s): %d本 | 七彩晶: %d/120 | 玉荧草: %d/60' % (book, counts.get(str(book), 0), counts.get('103000004', 0), counts.get('102000004', 0))
            color = 'black'
        except Exception as error:
            text, color = '刷新失败: ' + str(error), 'red'
        finally:
            _close(flow)
        def finish():
            app._craft_refresh_running = False
            if same_identity(app, client, slot): app.lbl_craft_mats.config(text=text, foreground=color)
        app.root.after(0, finish)
    try: threading.Thread(target=worker, daemon=True).start()
    except Exception:
        app._craft_refresh_running = False
        raise

def run_craft(app):
    if not app._ensure_login(): return
    if identity_busy(app) or getattr(app, '_craft_refresh_running', False):
        app._log('[打造] 已有任务运行，请先等待结束')
        return
    try:
        book_id = int(app._craft_book_ids[app.var_craft_book.get()])
        maximum = int(app.var_craft_maxrun.get())
        if not 1 <= maximum <= 9999: raise ValueError('最大次数须为1～9999')
        targets = {}
        for name, (selected, minimum) in app.craft_attr_vars.items():
            if selected.get():
                value = float(minimum.get())
                if not math.isfinite(value) or value < 0: raise ValueError('词条下限须为非负有限数值')
                targets[name] = value
    except Exception as error:
        messagebox.showwarning('打造参数不正确', str(error)); return
    client, slot = app.client, app.current_save['index']
    app.running = True
    app._craft_job_active = True
    lock_controls(app, True)
    app.text_craft_log.delete('1.0', 'end')
    def log(text):
        app._log(text)
        def show():
            if same_identity(app, client, slot):
                app.text_craft_log.insert('end', text + '\n'); app.text_craft_log.see('end')
        app.root.after(0, show)
    def finish():
        app.running = False
        app._craft_job_active = False
        lock_controls(app, False)
    def worker():
        flow = None
        try:
            for index in range(maximum):
                if not app.running: break
                require_identity(app, client, slot)
                # enterScene is called once per new session, never twice on a live session.
                flow, _, scene = app._connect_and_enter(slot, expected_client=client)
                counts = _counts(scene)
                if counts.get(str(book_id), 0) < 1 or counts.get('103000004', 0) < 120 or counts.get('102000004', 0) < 60:
                    log('[打造] 制作书或材料不足，停止；未发送打造请求'); break
                result = _checked(flow, 'scene.equipHandler.makingItem', {'makeId': book_id})
                item = result.get('item')
                if not isinstance(item, dict) or not item.get('entityId') or not item.get('id'):
                    raise RuntimeError('打造回包缺少装备标识，停止，不出售')
                passed = all(float(item.get(name, 0)) >= value for name, value in targets.items())
                if not targets or passed:
                    log('[打造] 第%d次装备已保留，entityId=%s' % (index + 1, item['entityId'])); break
                log('[打造] 第%d次未达标，出售本次新装备' % (index + 1))
                _checked(flow, 'scene.playerHandler.sellItem', {'itemId': item['id'], 'entityId': item['entityId'], 'bagType': 0})
                _close(flow); flow = None
                time.sleep(1)
            log('[打造] 流程结束')
        except Exception as error:
            log('[打造] 已停止：' + str(error) + '；不自动重试')
        finally:
            _close(flow)
            app.root.after(0, finish)
    try: threading.Thread(target=worker, daemon=True).start()
    except Exception:
        finish(); raise
