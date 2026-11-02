"""Discover the official ZM4 client version; accept it only after server entry succeeds."""
import json
import logging
from pathlib import Path
import re
import sys
import threading
import time
from urllib.parse import urljoin, urlparse
import requests

PAGE = 'https://www.4399.com/flash/151038.htm'
BOOTSTRAP_VERSION = 587
_BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
_CACHE = _BASE / 'zm4_version_cache.json'
_LOCK = threading.RLock()
_candidate = None
_checked_at = 0
_last_failure = 0
_source = None
_log = logging.getLogger('zm4.version')

class EmptySaveSlot(RuntimeError):
    """The server explicitly confirmed this slot has never been created."""

def _cached_version():
    try:
        saved = json.loads(_CACHE.read_text(encoding='utf8'))
        value = saved.get('verifiedVersion')
        if isinstance(value, int) and 100 <= value <= 9999:
            return value
    except (OSError, ValueError, TypeError):
        pass
    return BOOTSTRAP_VERSION

def _discover():
    headers = {'User-Agent': 'Mozilla/5.0', 'Referer': PAGE}
    with requests.Session() as session:
        page = session.get(PAGE, headers=headers, timeout=(5, 8))
        page.raise_for_status()
        # Match ZM4's exact official directory, not other games on this shared page.
        links = re.findall(r'https://sda\.4399\.com/4399swf/upload_swf/ftp15/csya/20150127/1/v\d+[^\s\x22\x27<>]*\.htm', page.text)
        links = list(dict.fromkeys(links))
        if len(links) != 1:
            raise ValueError('官网造四客户端入口不唯一或格式已变化')
        launcher = session.get(links[0], headers=headers, timeout=(5, 8))
        launcher.raise_for_status()
        movies = re.findall(r'(?:src|value)\s*=\s*[\x22\x27]([^\x22\x27]*v(\d{4,5})\.swf)[\x22\x27]', launcher.text, re.I)
        builds = {int(build) for _, build in movies}
        if len(builds) != 1:
            raise ValueError('官方启动页未提供唯一客户端版本')
        movie = urljoin(links[0], movies[0][0])
        if urlparse(movie).hostname != 'sda.4399.com':
            raise ValueError('客户端资源不是官方域名')
        # v5870/v5872 are builds of V58.7. This is a candidate until entry accepts it.
        version = builds.pop() // 10
        return version, {'page': PAGE, 'launcher': links[0], 'movie': movie}

def get_client_version(force=False):
    global _candidate, _checked_at, _last_failure, _source
    with _LOCK:
        now = time.time()
        if not force and _candidate is not None and now - _checked_at < 6 * 3600:
            return _candidate
        if not force and now - _last_failure < 60:
            return _candidate or _cached_version()
        try:
            _candidate, _source = _discover()
            _checked_at = now
            _log.info('官网客户端候选版本：%s (%s)', _candidate, _source['movie'])
            return _candidate
        except Exception as error:
            _last_failure = now
            _log.warning('官网版本检查失败，使用最近已验证版本：%s', error)
            return _cached_version()

def _verified(version):
    with _LOCK:
        body = {'verifiedVersion': version, 'verifiedAt': time.time(), 'source': _source}
        try:
            temporary = _CACHE.with_suffix('.tmp')
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding='utf8')
            temporary.replace(_CACHE)
        except OSError as error:
            _log.warning('版本缓存保存失败：%s', error)

def enter_record(flow, slot, user_agent, timeout=15):
    version = get_client_version()
    reply = flow.request('connector.entryHandler.entry',
                         {'rid': slot, 'ver': version, 'userAgent': user_agent}, timeout=timeout)
    if isinstance(reply, dict) and reply.get('code') != 200 and '版本' in str(reply.get('error', '')):
        refreshed = get_client_version(force=True)
        if refreshed != version:
            version = refreshed
            reply = flow.request('connector.entryHandler.entry',
                                 {'rid': slot, 'ver': version, 'userAgent': user_agent}, timeout=timeout)
    if not isinstance(reply, dict) or reply.get('code') != 200 or reply.get('error'):
        error = reply.get('error') or str(reply.get('code')) if isinstance(reply, dict) else '无有效回包'
        if str(error).strip() == '没有创建该存档':
            _verified(version)
            raise EmptySaveSlot('槽%s：没有创建该存档' % slot)
        raise RuntimeError('槽%s读取失败（客户端版本%s）：%s' % (slot, version, error))
    _verified(version)
    return reply

def save_summary(entry, slot):
    if not isinstance(entry, dict) or entry.get('code') != 200 or entry.get('error'):
        detail = entry.get('error', '无有效回包') if isinstance(entry, dict) else '无有效回包'
        raise RuntimeError('槽%s读取失败：%s' % (slot, detail))
    if 'record' not in entry or not isinstance(entry['record'], dict):
        raise RuntimeError('槽%s存档回包缺少record，不能判定为空存档' % slot)
    record = entry['record']
    player = record.get('p1') or record.get('p2')
    if not player:
        if record and 'p1' not in record and 'p2' not in record:
            raise RuntimeError('槽%s存档结构异常，未返回角色字段' % slot)
        return {'index': slot, 'name': '空存档', 'level': '-', 'empty': True}
    if not isinstance(player, dict) or not player.get('kindName') or player.get('level') is None:
        raise RuntimeError('槽%s角色资料不完整，不能判定为空存档' % slot)
    return {'index': slot, 'name': player['kindName'], 'level': player['level'], 'empty': False}
