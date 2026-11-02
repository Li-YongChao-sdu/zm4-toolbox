"""造四群组签到：独立OAuth登录、加入状态检测及两阶段签到。"""
import hashlib
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import requests

GROUP_ID = '82186'
GROUP_NAME = '造四·洪荒大劫篇'
ORIGIN = 'https://my.4399.com'
LOGIN_ORIGIN = 'https://ptlogin.4399.com'
CLIENT_ID = '530a1a19a7e98daf50946b1ee883916a'
# Official App request format; contains no account/session credential.
APP_UA = ('app.4399.forums%2F1.9.4%28android%3B2509FPN0BC%3B9%3B1600x900'
          '%3BWIFI%3B2137070%7C59d09eaabb0dcc9368b96d32bdd87fa1%3B172%3Bceshi4399%29')
WEB_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36'
CHINA = timezone(timedelta(hours=8))


class FormParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.active = False
        self.action = None
        self.fields = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'form':
            self.active = attrs.get('id') == 'authorizeForm'
            if self.active:
                self.action = attrs.get('action')
        if self.active and tag == 'input' and attrs.get('name') and attrs.get('type') != 'submit':
            self.fields[attrs['name']] = attrs.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.active = False


class JoinButtonParser(HTMLParser):
    """Read the desktop button's actual class/text, including inline hidden state."""
    def __init__(self):
        super().__init__()
        self.button = None
        self.inside = False
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        hidden = bool(self.stack and self.stack[-1][1])
        style = re.sub(r'\s+', '', attrs.get('style', '').lower())
        hidden |= 'display:none' in style or 'visibility:hidden' in style or 'hidden' in attrs
        hidden |= bool(set(attrs.get('class', '').split()) & {'hidden', 'hide'})
        if tag not in {'input', 'img', 'br', 'hr', 'meta', 'link', 'wbr', 'source', 'area', 'base', 'embed', 'param', 'track', 'col'}:
            self.stack.append((tag, hidden))
        if attrs.get('id') == 'joinMtagBtn':
            self.button = {'classes': attrs.get('class', '').split(), 'hidden': hidden, 'text': ''}
            self.inside = True

    def handle_data(self, data):
        if self.inside:
            self.button['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.inside = False
        for index in range(len(self.stack)-1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break


class ForumClient:
    def __init__(self, log):
        self.session = requests.Session()
        # Independent of system capture proxies; HTTPS verification stays enabled.
        self.session.trust_env = False
        self.session.headers['User-Agent'] = APP_UA
        self.log = log
        self.uid = ''
        self.username = ''
        self.server_now = None

    def close(self):
        self.session.close()

    def request(self, method, url, **kwargs):
        try:
            response = self.session.request(method, url, timeout=25, **kwargs)
            response.raise_for_status()
        except requests.RequestException as error:
            # Request exception strings can contain login URLs or parameters.
            raise RuntimeError('群组网络请求失败（%s）' % type(error).__name__) from None
        try:
            self.server_now = parsedate_to_datetime(response.headers['Date']).astimezone(CHINA)
        except (KeyError, ValueError, TypeError, OverflowError):
            pass
        response.encoding = 'utf-8'
        return response

    def json_post(self, path, data, headers=None):
        response = self.request('POST', ORIGIN + path, data=data, headers=headers)
        try:
            reply = response.json()
        except ValueError:
            raise RuntimeError('群组接口返回非JSON数据，已停止') from None
        if not isinstance(reply, dict):
            raise RuntimeError('群组接口返回格式异常')
        if reply.get('code') != 100:
            # Only known business message, never raw request/response or tokens.
            msg = re.sub('<[^>]+>', '', str(reply.get('msg') or '请求失败'))[:180]
            raise RuntimeError('%s：code=%s，%s' % (path, reply.get('code'), msg))
        return reply.get('result') or {}

    def api(self, path, **params):
        data = dict(app_id='25', uid=self.uid or '0', uri=path, uuid=str(uuid.uuid4()))
        data.update(params)
        return self.json_post(path, data)

    def authenticate(self, credentials):
        # This registered OAuth callback must exactly match the official App.
        # We read its Location without navigating to the HTTP callback.
        params = dict(client_id=CLIENT_ID, redirect_uri='http://my.4399.com/ok.html',
                      response_type='CODE', auth_action='ORILOGIN', show_topbar='false',
                      isInputRealname='0', isValidRealname='0', sdk='login')
        if credentials['mode'] == 'cookie':
            raw = credentials['cookie'].strip().strip('"')
            if raw.lower().startswith('cookie:'):
                raw = raw[7:].strip()
            for part in raw.split(';'):
                if '=' in part:
                    name, value = part.strip().split('=', 1)
                    self.session.cookies.set(name, value, domain='.4399.com', path='/')
            self._identity()
            try:
                self.sign_state()
                self.log('[群组签到] Cookie认证成功')
                return
            except RuntimeError:
                pass
            response = self.request('GET', LOGIN_ORIGIN + '/oauth2/authorize.do',
                                    params=params, allow_redirects=False)
        else:
            from ptlogin_login import encrypt_password
            page = self.request('GET', LOGIN_ORIGIN + '/oauth2/authorize.do', params=params)
            form = FormParser()
            form.feed(page.text)
            if not form.action:
                raise RuntimeError('未获取到官方账号登录表单')
            target = urljoin(LOGIN_ORIGIN, form.action)
            if urlsplit(target).netloc != 'ptlogin.4399.com':
                raise RuntimeError('登录表单目标域名异常，已停止')
            form.fields.update(username=credentials['username'],
                               password=encrypt_password(credentials['password'])
                               if form.fields.get('sec') == '1' else credentials['password'])
            self.session.headers['Referer'] = page.url
            response = self.request('POST', target, data=form.fields,
                                    headers={'Referer': page.url}, allow_redirects=False)
        location = urlsplit(response.headers.get('Location', ''))
        if location.netloc != 'my.4399.com' or location.path != '/ok.html':
            if re.search(r'name=["\']captcha["\']|请输入验证码', response.text):
                raise RuntimeError('群组登录需要验证码，请在浏览器完成登录后尝试Cookie模式')
            raise RuntimeError('未取得群组授权码，请检查账密或更换有效Cookie')
        codes = parse_qs(location.query).get('code') or []
        if not codes:
            raise RuntimeError('授权响应缺少code，已停止')
        self.uid = '0'
        self.api('/fapi/user-code', code=codes[0])
        self._identity()
        if not self.uid or not self.username:
            raise RuntimeError('授权码交换返回成功，但未取得Pauth登录凭证，已停止')
        if credentials['mode'] != 'cookie' and self.username != credentials['username']:
            raise RuntimeError('群组登录返回账号与输入账号不一致，已停止')
        self.log('[群组签到] 独立OAuth登录成功，无需App或模拟器')

    def _identity(self):
        pauth = next((c.value for c in self.session.cookies if c.name == 'Pauth'), '')
        parts = unquote(pauth).strip('"').split('|')
        self.uid = parts[0] if parts else ''
        self.username = parts[1] if len(parts) > 1 else ''

    def sign_state(self):
        return self.api('/fapi/user-forumsSign', getInfo='1', limit='25', offset='0',
                        order='lp', ouid='0', page='1', preview='1')

    def member(self):
        offset = 0
        for number in range(1, 101):
            result = self.api('/fapi/user-mtag', limit='25', offset=str(offset),
                              start=str(offset), order='lp', ouid='0',
                              page=str(number), preview='1', recom='0')
            rows = result.get('list') or []
            for row in rows:
                if str(row.get('tagid')) == GROUP_ID:
                    return row
            actual_limit = int(result.get('limit') or len(rows) or 25)
            total_pages = int(result.get('totalPage') or
                              ((int(result.get('count') or 0) + actual_limit-1)//actual_limit) or 1)
            if number >= total_pages:
                return None
            if not rows:
                raise RuntimeError('群组分页返回空列表，无法可靠判断加入状态')
            offset += actual_limit
        raise RuntimeError('群组列表超过100页，无法可靠判断加入状态')

    def web_joined(self):
        page = self.request('GET', ORIGIN + '/forums/mtag-' + GROUP_ID,
                            headers={'User-Agent': WEB_UA})
        parser = JoinButtonParser()
        parser.feed(page.text)
        button = parser.button
        if not button or button['hidden']:
            return None
        if 'hasjoin' in button['classes'] and '已加入' in button['text']:
            return True
        if 'hasjoin' not in button['classes'] and '加入' in button['text']:
            return False
        return None

    def check(self):
        member = self.member()
        web = self.web_joined()
        if web is not None and web != bool(member):
            raise RuntimeError('接口和网页加入状态不一致，请刷新后再执行')
        return member, web

    def join(self):
        member, web = self.check()
        if member:
            self.log('[群组签到] 已加入洪荒大劫篇，无需重复加入')
            return member, web
        if web is not False:
            raise RuntimeError('网页未确认加入按钮，停止自动加入')
        self.json_post('/forums/operate-joinMtag', {'tagid': GROUP_ID, '_AJAX_': '1'},
                       headers={'Referer': ORIGIN + '/forums/mtag-' + GROUP_ID,
                                'X-Requested-With': 'XMLHttpRequest'})
        member, web = self.check()
        if not member or web is not True:
            raise RuntimeError('加入请求已提交，但两种方式未同时确认成功')
        self.log('[群组签到] 已加入洪荒大劫篇，两种方式复核成功')
        return member, web

    def signed_today(self, member):
        try:
            stamp = float(member.get('lastSign') or 0)
            if stamp > 10**11:
                stamp /= 1000
            now = self.server_now or datetime.now(CHINA)
            return stamp > 0 and datetime.fromtimestamp(stamp, CHINA).date() == now.date()
        except (ValueError, TypeError, OverflowError, OSError):
            return False

    def web_state(self, submit=False):
        return self.json_post('/forums/grade-signIn',
                              dict(tagid=GROUP_ID, _AJAX_='1', sign='1' if submit else '0'),
                              headers={'Referer': ORIGIN + '/forums/mtag-' + GROUP_ID,
                                       'User-Agent': WEB_UA,
                                       'X-Requested-With': 'XMLHttpRequest'})

    def run(self):
        before, web = self.check()
        if not before:
            raise RuntimeError('尚未加入洪荒大劫篇，请先点击“加入造四群组”')
        if web is None:
            self.log('[群组签到] 网页按钮状态未知；接口已确认加入')
        grade = before.get('grade_info') or {}
        initial_exp = int(grade.get('exper') or 0)
        level = int(grade.get('level') or before.get('grade_mtag') or 0)
        if self.signed_today(before):
            return before, web, '今日已签到；未重复提交'
        state = self.sign_state()
        target_high = any(str(row.get('tagid')) == GROUP_ID
                          for row in state.get('height_level') or [])
        self.log('[群组签到] 第1阶段：一键群组签到，当前等级%d' % level)
        if target_high:
            if state.get('can_sign'):
                reply = self.api('/fapi/user-forumsSign', getInfo='0', limit='25',
                                 offset='0', order='lp', ouid='0', page='1', preview='1')
                self.log('[群组签到] 一键签到返回成功；失败条目数%d' % len(reply.get('sign_fail') or []))
            after = self.member()
            if not after:
                raise RuntimeError('签到后无法读取造四群组信息')
            end_exp = int((after.get('grade_info') or {}).get('exper') or 0)
            if self.signed_today(after) or end_exp > initial_exp:
                return after, self.web_joined(), '一键签到已复核：经验%d→%d' % (initial_exp, end_exp)
            raise RuntimeError('一键接口已调用，但未确认造四签到成功；请重新检查状态')
        target_low = any(str(row.get('tagid')) == GROUP_ID
                         for row in state.get('low_level') or [])
        if not target_low or not level:
            raise RuntimeError('本群等级与一键签到分类不一致，已停止')
        self.log('[群组签到] 第2阶段：等级不足，使用网页签到')
        web_before = self.web_state()
        # isSigned is known to remain false after successful web signing.
        if web_before.get('isSigned'):
            return before, web, '网页提示今日已签到；未重复提交'
        self.web_state(submit=True)
        verified = self.web_state()
        after = self.member()
        if not after:
            raise RuntimeError('网页签到后无法读取造四群组信息')
        end_exp = int((after.get('grade_info') or {}).get('exper') or 0)
        days_before = int(web_before.get('totalDays') or 0)
        days_after = int(verified.get('totalDays') or 0)
        if self.signed_today(after) or (end_exp > initial_exp and days_after > days_before):
            return after, self.web_joined(), '网页签到已复核：经验%d→%d；累计%d天' % (initial_exp, end_exp, days_after)
        raise RuntimeError('网页接口返回成功，但经验/签到记录未确认变化，请检查状态')


def capture_credentials(app, require_same_account=False):
    """Snapshot Tk fields on the UI thread, never in a network worker."""
    mode = app.var_login_mode.get()
    credentials = dict(mode=mode, username=app.entry_user.get().strip(),
                       password=app.entry_pass.get(), cookie=app.entry_cookie.get().strip())
    if mode == 'cookie' and not credentials['cookie']:
        raise RuntimeError('请在顶部粘贴有效Cookie')
    if mode != 'cookie' and (not credentials['username'] or not credentials['password']):
        raise RuntimeError('请在顶部填写账号和密码')
    if require_same_account:
        expected = str(getattr(app.client, 'username', '') or '')
        if mode != 'cookie' and credentials['username'] != expected:
            raise RuntimeError('顶部账号与当前游戏账号不一致，群组签到已跳过')
        credentials['expected_username'] = expected
    return credentials


def execute(app, credentials):
    """Shared one-click daily entry; never run concurrently with the standalone tab."""
    lock = app._forum_execution_lock
    if not lock.acquire(blocking=False):
        credentials.clear()
        raise RuntimeError('群组签到页面正在执行，本轮一键日常跳过群组签到')
    client = ForumClient(app._log)
    try:
        client.authenticate(credentials)
        expected = credentials.get('expected_username')
        if expected and client.username != expected:
            raise RuntimeError('群组认证账号与当前游戏账号不一致，已停止')
        member, web, text = client.run()
        app._log('[群组签到] ' + text)
        return member, web, text
    finally:
        client.close()
        credentials.clear()
        lock.release()


def build_panel(app, parent):
    import tkinter as tk
    from tkinter import messagebox, ttk
    parent.rowconfigure(0, weight=1)
    parent.columnconfigure(0, weight=1)
    canvas = tk.Canvas(parent, highlightthickness=0, borderwidth=0)
    vertical = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
    horizontal = ttk.Scrollbar(parent, orient='horizontal', command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    canvas.grid(row=0, column=0, sticky='nsew')
    vertical.grid(row=0, column=1, sticky='ns')
    horizontal.grid(row=1, column=0, sticky='ew')
    frame = ttk.Frame(canvas, padding=10)
    content = canvas.create_window((0, 0), window=frame, anchor='nw')

    def resize(event=None):
        canvas.itemconfigure(content, width=max(canvas.winfo_width(), frame.winfo_reqwidth()))
        canvas.configure(scrollregion=canvas.bbox('all'))

    def wheel(event):
        widget = event.widget
        while widget is not None and widget != parent:
            widget = getattr(widget, 'master', None)
        if widget != parent:
            return
        if event.delta:
            steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
            canvas.yview_scroll(steps, 'units')
            return 'break'

    frame.bind('<Configure>', resize)
    canvas.bind('<Configure>', resize)
    app.root.bind('<MouseWheel>', wheel, add='+')
    app._forum_execution_lock = threading.Lock()
    ttk.Label(frame, text='造四·洪荒大劫篇群组签到', font=('Microsoft YaHei', 12, 'bold')).pack(anchor='w', pady=(0, 8))
    ttk.Checkbutton(frame, text='纳入每日一键日常', variable=app.var_daily_forum).pack(anchor='w', pady=5)
    ttk.Label(frame, text='使用顶部登录区的账号密码或Cookie；无需选择游戏存档。\n先尝试一键群组签到；本群等级不足4级时，自动改走网页签到并复核。', wraplength=680).pack(anchor='w', pady=5)
    ttk.Label(frame, text='一键接口会同时处理账号已加入的其他符合等级群组；网页补签仅处理造四。此处不执行付费补签。', wraplength=680, foreground='gray').pack(anchor='w', pady=5)
    info = tk.StringVar(value='待检查：洪荒大劫篇（82186）')
    result = tk.StringVar(value='先检查是否加入；未加入可点击独立加入按钮。')
    ttk.Label(frame, textvariable=info, wraplength=680, justify='left').pack(anchor='w', pady=10)
    buttons = ttk.Frame(frame)
    buttons.pack(anchor='w', pady=5)
    ttk.Label(frame, textvariable=result, wraplength=680, justify='left').pack(anchor='w', pady=10)
    cache = {'client': None, 'key': None, 'busy': False}
    controls = []

    def show(member, web, username):
        grade = (member or {}).get('grade_info') or {}
        text = ('账号：%s\n接口列表：%s；网页按钮：%s\n等级：%s　经验：%s　连续签到：%s天' % (
            username, '已加入' if member else '未加入',
            '已加入' if web is True else '未加入' if web is False else '未知',
            grade.get('level', '—'), grade.get('exper', '—'), grade.get('continueDay', '—')))
        info.set(text)

    def start(action):
        if cache['busy']:
            return
        try:
            credentials = capture_credentials(app)
        except RuntimeError as error:
            messagebox.showwarning('群组签到', str(error))
            return
        if not app._forum_execution_lock.acquire(blocking=False):
            credentials.clear()
            messagebox.showinfo('群组签到', '每日一键日常正在执行群组签到，请稍候')
            return
        mode = credentials['mode']
        raw = repr((mode, credentials['cookie'] if mode == 'cookie' else
                    (credentials['username'], credentials['password'])))
        key = hashlib.sha256(raw.encode('utf-8')).hexdigest()
        cache['busy'] = True
        for button in controls:
            button.config(state='disabled')
        result.set('正在登录群组并执行，请稍候…')

        def worker():
            member = web = None
            username = credentials['username']
            try:
                if cache['key'] != key or cache['client'] is None:
                    if cache['client']:
                        cache['client'].close()
                    cache.update(client=None, key=None)
                    client = ForumClient(app._log)
                    try:
                        client.authenticate(credentials)
                    except Exception:
                        client.close()
                        raise
                    cache.update(client=client, key=key)
                client = cache['client']
                username = client.username
                if action == 'check':
                    member, web = client.check()
                    text = '两种加入状态检测完成' if web is not None else '接口已检测；网页按钮未知'
                elif action == 'join':
                    member, web = client.join()
                    text = '已加入造四群组（接口与网页复核）'
                else:
                    member, web, text = client.run()
                app._log('[群组签到] ' + text)
            except Exception as error:
                # API wrappers redact URLs and credentials before raising.
                text = '停止：' + (str(error) if isinstance(error, RuntimeError) else type(error).__name__)
                app._log('[群组签到] ' + text)
                if cache['client']:
                    cache['client'].close()
                cache.update(client=None, key=None)
            finally:
                credentials.clear()
                app._forum_execution_lock.release()
                def finish(message=text, row=member, state=web, account=username):
                    cache['busy'] = False
                    for button in controls:
                        button.config(state='normal')
                    if row is not None or state is not None:
                        show(row, state, account)
                    result.set(message)
                app.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    for title, action in [('检查是否加入', 'check'), ('加入造四群组', 'join'),
                          ('执行签到（一键→网页）', 'sign')]:
        button = ttk.Button(buttons, text=title, command=lambda value=action: start(value))
        button.pack(side='left', padx=(0, 8))
        controls.append(button)
