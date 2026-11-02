"""Experimental gamebox activity client; credentials are supplied, never persisted."""
import hashlib
import json
import random
import re
import threading

import requests

ENDPOINT = 'https://huodong2.4399.com/comm/qdlb/ajax_v4.php'
REFERER = 'https://huodong2.4399.com/comm/qdlb/share2.php?hdid=5&id=20570'


def parse_parameters(raw):
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('需要JSON对象')
    for name in ('scookie', 'device', 'ua', 'client_version'):
        if not isinstance(value.get(name), str) or not value[name].strip():
            raise ValueError('缺少真实App参数：' + name)
    if '\r' in value['ua'] or '\n' in value['ua']:
        raise ValueError('UA不能包含换行')
    if '4399GameCenter/' + value['client_version'] not in value['ua']:
        raise ValueError('UA与客户端版本不一致')
    if not value['scookie'].startswith('0|'):
        raise ValueError('需要App的scookie，不能使用网页Cookie代替')
    for name in ('st', 'sn'):
        if name in value and not isinstance(value[name], str):
            raise ValueError(name + '必须为字符串')
    return {name: value.get(name, '') for name in
            ('scookie', 'device', 'ua', 'client_version', 'st', 'sn')}


def request_once(parameters, action):
    """One request only; never retry a potentially completed write."""
    if action not in ('bag', 'sign'):
        raise ValueError('不支持的操作')
    form = {name: parameters[name] for name in
            ('scookie', 'device', 'client_version', 'st', 'sn')}
    form.update(hdid='5', ac=action, rand=str(random.random()))
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.post(ENDPOINT, data=form, timeout=(10, 25), headers={
                'User-Agent': parameters['ua'], 'Referer': REFERER,
                'X-Requested-With': 'XMLHttpRequest'})
            response.raise_for_status()
            result = response.json()
            if not isinstance(result, dict):
                raise ValueError('非对象响应')
            return result
    finally:
        form.clear()


def build_panel(app, parent):
    import tkinter as tk
    from tkinter import ttk
    box = ttk.LabelFrame(parent, text='游戏盒91122 · 洪荒大劫篇（实验功能）', padding=10)
    box.pack(fill='x', pady=8)
    ttk.Label(box, text='历史签到曾被活动限制拒绝，尚未验证成功。仅使用正常App提供的真实参数；'
              '本模块不自动登录或提取凭证。遇到活动受限请停止并联系官方。',
              wraplength=680).pack(anchor='w')
    ttk.Label(box, text='粘贴JSON：scookie、device、ua、client_version；可选st、sn。'
              '内容隐藏，仅保存在当前窗口内存，不写入配置或日志。',
              wraplength=680).pack(anchor='w', pady=6)
    raw = tk.StringVar()
    ttk.Entry(box, textvariable=raw, show='*').pack(fill='x')
    status = tk.StringVar(value='等待真实App参数；与顶部游戏账号登录独立。')
    ttk.Label(box, textvariable=status, wraplength=680).pack(anchor='w', pady=8)
    row = ttk.Frame(box)
    row.pack(anchor='w')
    state = {'busy': False, 'blocked': set()}
    controls = []

    def start(action):
        if state['busy']:
            return
        try:
            parameters = parse_parameters(raw.get())
        except (ValueError, TypeError):
            status.set('参数无效：需要真实App的scookie、device、ua、client_version，st/sn可选。')
            return
        # Keep an account-level refusal latch even if the supplied token changes.
        account = parameters['scookie'].split('|', 2)[1]
        key = hashlib.sha256(account.encode()).hexdigest()
        if key in state['blocked']:
            parameters.clear()
            status.set('此账号本次运行已收到活动限制，停止重试；请通过官方处理。')
            return
        state['busy'] = True
        for button in controls:
            button.configure(state='disabled')
        status.set('正在查询奖励袋…' if action == 'bag' else '正在提交一次免费签到…')

        def worker():
            try:
                result = request_once(parameters, action)
                code = str(result.get('key', result.get('code', '未知')))
                message = str(result.get('msg') or '')
                if code == 'custom_common_msg' or any(word in message for word in ('违规', '受限', '禁止')):
                    state['blocked'].add(key)
                    text = '服务器拒绝：活动受限。已停止此账号本次运行的后续请求。'
                elif code == '200':
                    text = ('奖励袋查询成功；此结果不能证明可签到。' if action == 'bag' else
                            '签到接口返回key=200；仍需在官方App核对今日状态及签到天数。')
                else:
                    text = '服务器未确认成功，业务码：' + (code if re.fullmatch(r'[\w-]{1,40}', code) else '未知')
                app._log('[游戏盒签到] ' + text)
            except requests.RequestException:
                text = '网络请求失败；未自动重试。若提交过签到，请先在App核对结果。'
                app._log('[游戏盒签到] ' + text)
            except Exception:
                text = '响应无法解析；未自动重试，请在App核对结果。'
                app._log('[游戏盒签到] ' + text)
            finally:
                parameters.clear()
                def finish(message=text):
                    state['busy'] = False
                    status.set(message)
                    for button in controls:
                        button.configure(state='normal')
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for title, action in (('查询奖励袋（只读）', 'bag'), ('提交一次免费签到', 'sign')):
        button = ttk.Button(row, text=title, command=lambda value=action: start(value))
        button.pack(side='left', padx=(0, 8))
        controls.append(button)
    clear = ttk.Button(row, text='清空参数', command=lambda: raw.set(''))
    clear.pack(side='left')
    controls.append(clear)
