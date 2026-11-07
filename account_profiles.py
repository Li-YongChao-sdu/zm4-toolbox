"""手动保存账号；凭据使用Windows当前用户DPAPI加密，不进入日常配置。"""
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import sys
import uuid
from tkinter import ttk, messagebox


class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def _protect(raw, decrypt=False):
    if os.name != 'nt': raise RuntimeError('账号加密保存需要Windows')
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        method = crypt.CryptUnprotectData
        method.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = method(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        method = crypt.CryptProtectData
        method.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = method(ctypes.byref(source), 'ZM4 account', None, None, None, 1, ctypes.byref(output))
    if not ok: raise RuntimeError('Windows账号加密/解密失败，错误码%d' % ctypes.get_last_error())
    try: return ctypes.string_at(output.data, output.size)
    finally: kernel.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))


class AccountProfiles:
    def _build_account_profiles(self, parent):
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        self._account_directory = base / 'accounts'
        row = ttk.Frame(parent)
        row.grid(row=3, column=0, columnspan=6, sticky='ew', pady=(6, 0))
        parent.columnconfigure(0, weight=1)
        ttk.Label(row, text='已存账号：').pack(side='left')
        self._account_choice = ttk.Combobox(row, state='readonly', width=18)
        self._account_choice.pack(side='left', padx=4)
        ttk.Button(row, text='载入账号', command=self._load_account_profile).pack(side='left', padx=3)
        ttk.Button(row, text='保存当前账号', command=self._save_account_profile).pack(side='left', padx=3)
        ttk.Button(row, text='删除所选', command=self._delete_account_profile).pack(side='left', padx=3)
        ttk.Button(row, text='刷新', command=self._refresh_account_profiles).pack(side='left', padx=3)
        ttk.Label(row, text='登录成功后自动加密保存Cookie；密码不落盘',
                  style='Muted.TLabel').pack(side='left', padx=6)
        self._refresh_account_profiles()

    def _account_path(self, username):
        return self._account_directory / (hashlib.sha256(username.encode('utf8')).hexdigest() + '.json')

    def _refresh_account_profiles(self):
        previous = self._account_choice.get()
        self._account_files = {}
        if self._account_directory.exists():
            for path in sorted(self._account_directory.glob('*.json')):
                try:
                    record = json.loads(path.read_text(encoding='utf8'))
                    username = record.get('username')
                    if record.get('format') == 'zm4-dpapi-v1' and isinstance(username, str) and username:
                        if path.name == self._account_path(username).name: self._account_files[username] = path
                except (OSError, ValueError): pass
        names = sorted(self._account_files)
        self._account_choice.config(values=names)
        self._account_choice.set(previous if previous in names else names[0] if names else '')

    def _write_profile(self, payload):
        username = payload['username']
        encrypted = base64.b64encode(_protect(json.dumps(payload, ensure_ascii=False).encode('utf8'))).decode('ascii')
        record = {'format': 'zm4-dpapi-v1', 'username': username, 'encrypted': encrypted}
        self._account_directory.mkdir(parents=True, exist_ok=True)
        destination = self._account_path(username)
        temporary = destination.with_suffix('.%s.tmp' % uuid.uuid4().hex)
        try:
            temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf8')
            os.replace(temporary, destination)
        finally:
            if temporary.exists(): temporary.unlink()
        self._refresh_account_profiles(); self._account_choice.set(username)
        return username

    def _save_account_profile(self):
        if str(self.btn_login.cget('state')) == 'disabled': return
        try:
            from zm4_client import ZM4Client
            mode = self.var_login_mode.get()
            username = self.entry_user.get().strip()
            password = self.entry_pass.get()
            cookie = self.entry_cookie.get().strip()
            if mode == 'cookie':
                username = ZM4Client.from_cookie_string(cookie).username
                password = ''
            elif not username or not password:
                raise RuntimeError('请输入账号密码后保存，或切换Cookie模式保存')
            elif cookie and ZM4Client.from_cookie_string(cookie).username != username:
                raise RuntimeError('备用Cookie与账号不一致，请清空或更换后保存')
            if self.client and self.client.username == username:
                cookie = '; '.join('%s=%s' % pair for pair in self.client.cookies.items())
            slot = self.current_save['index'] if self.client and self.client.username == username and self.current_save else None
            payload = {'username': username, 'mode': mode, 'password': password, 'cookie': cookie, 'slot': slot}
            self._log('[账号保存] 已加密保存账号%s及当前存档' % self._write_profile(payload))
        except Exception as error:
            messagebox.showerror('保存账号失败', str(error))

    def _auto_save_account(self, client=None, slot=None):
        """登录成功后静默保存该账号的最新Cookie，下次只填账号名即可登录。"""
        client = client or getattr(self, 'client', None)
        if not client or not getattr(client, 'username', None) or not getattr(client, 'cookies', None): return
        if slot is None and getattr(self, 'current_save', None): slot = self.current_save.get('index')
        payload = {'username': client.username, 'mode': 'cookie', 'password': '',
                   'cookie': '; '.join('%s=%s' % pair for pair in client.cookies.items()), 'slot': slot}
        try:
            self._write_profile(payload)
            self._log('[账号保存] 已自动加密保存账号%s的Cookie' % client.username)
        except Exception as error:
            self._log('[账号保存] 自动保存失败：%s' % error)

    def _saved_cookie_for(self, username):
        path = getattr(self, '_account_files', {}).get(username)
        if path is None: return ''
        try:
            record = json.loads(path.read_text(encoding='utf8'))
            payload = json.loads(_protect(base64.b64decode(record['encrypted'], validate=True), decrypt=True).decode('utf8'))
            if payload.get('username') != username: return ''
            return payload.get('cookie') or ''
        except Exception:
            return ''

    def _load_account_profile(self):
        if str(self.btn_login.cget('state')) == 'disabled': return
        username = self._account_choice.get()
        path = self._account_files.get(username)
        if path is None: return
        try:
            record = json.loads(path.read_text(encoding='utf8'))
            payload = json.loads(_protect(base64.b64decode(record['encrypted'], validate=True), decrypt=True).decode('utf8'))
            if payload.get('username') != username or payload.get('mode') not in ('password', 'cookie'):
                raise RuntimeError('账号文件格式不正确')
            self.entry_user.config(state='normal'); self.entry_pass.config(state='normal')
            for entry, text in ((self.entry_user, username), (self.entry_pass, payload.get('password', '')),
                                (self.entry_cookie, payload.get('cookie', ''))):
                entry.delete(0, 'end'); entry.insert(0, text)
            self.var_login_mode.set(payload['mode']); self._toggle_login_mode()
            self._loaded_account_slot = (username, payload.get('slot'))
            self._loaded_account_name = username
            # 载入后要求重新登录，防止仍对上一个账号执行活动。
            self.client = None; self.current_save = None; self.saves = []
            self.combo_save.config(values=()); self.save_var.set('')
            self.lbl_save_info.config(text='请登录读取此账号存档', foreground='gray')
            self.lbl_status.config(text='已载入%s，请点击登录' % username, foreground='orange')
            self._log('[账号保存] 已载入账号%s；Cookie失效时可更新后重新保存' % username)
        except Exception:
            messagebox.showerror('载入失败', '账号文件无法解密或格式不正确。请在保存它的Windows用户下使用，或重新输入账号后保存。')

    def _delete_account_profile(self):
        username = self._account_choice.get()
        path = self._account_files.get(username)
        if path is None: return
        if not messagebox.askyesno('删除保存账号', '删除本机保存的账号%s？' % username): return
        try:
            path.unlink(); self._refresh_account_profiles()
            self._log('[账号保存] 已删除本机账号记录%s' % username)
        except OSError:
            messagebox.showerror('删除失败', '无法删除账号文件，请检查目录权限')
