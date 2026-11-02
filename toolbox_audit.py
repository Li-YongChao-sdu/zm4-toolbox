"""本地运行日志和被动掉落统计；不发送额外游戏请求。

请求线程只做「入队」，落盘（JSONL / 运行日志）、SQLite 写入与报表重算全部由
后台单线程批量处理，避免刷图时把网络线程卡住。
"""
import atexit
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import signal
import sqlite3
import sys
import threading
import time
from datetime import datetime
from functools import lru_cache

_LOCK = threading.RLock()
_ERROR = None
_SECRET = re.compile(r'password|passwd|cookie|token|pauth|uauth|xauth|session|secret', re.I)

_QUEUE = queue.Queue()
_STOP = threading.Event()
_WORKER = None
_WORKER_LOCK = threading.Lock()

FLUSH_INTERVAL = 0.5     # JSONL/日志批量落盘间隔（秒）
REPORT_INTERVAL = 30.0   # 掉落报表最小重算间隔（秒）


def directory():
    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    return base / 'logs'


def clean(value):
    if isinstance(value, dict):
        return {str(k): '[已隐藏]' if _SECRET.search(str(k)) else clean(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value


def _set_error(error):
    global _ERROR
    with _LOCK:
        _ERROR = str(error)


def take_error():
    global _ERROR
    with _LOCK:
        error, _ERROR = _ERROR, None
        return error


def _wilson(hits, total):
    z = 1.959963984540054
    p = hits / total
    den = 1 + z*z/total
    center = (p + z*z/(2*total))/den
    half = z*math.sqrt(p*(1-p)/total + z*z/(4*total*total))/den
    return max(0, center-half), min(1, center+half)


@lru_cache(maxsize=1)
def _names():
    config = Path(__file__).parent / 'output_cg1_20260921_1_2'
    result = {}
    for suffix in ('Dungeon', 'Monster', 'Prop', 'Equipment', 'Feather', 'Soul'):
        table = {}
        for path in config.glob('*___' + suffix + '.xml.json'):
            for row in json.loads(path.read_text(encoding='utf-8')).get('RECORD', []):
                if isinstance(row, dict) and isinstance(row.get('name'), str):
                    table[str(row.get('id'))] = row['name']
        result[suffix] = table
    return result


# ---------------- 批量落盘 / 后台写线程 ----------------

def _write_lines(path, lines):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a', encoding='utf-8') as stream:
            stream.write(''.join(lines))
    except Exception as error:
        _set_error(error)


def _flush_jsonl(pending):
    for day, rows in pending.items():
        text = [json.dumps({'time': stamp, 'kind': kind, **clean(body)},
                           ensure_ascii=False, default=str) + '\n'
                for stamp, kind, body in rows]
        _write_lines(directory() / ('运行详情_' + day + '.jsonl'), text)
    pending.clear()


def _flush_ui(pending):
    for day, rows in pending.items():
        text = [prefix + str(line) + '\n' for prefix, line in rows]
        _write_lines(directory() / ('运行日志_' + day + '.log'), text)
    pending.clear()


def _ensure_worker():
    global _WORKER
    if _WORKER is not None and _WORKER.is_alive():
        return
    with _WORKER_LOCK:
        if _WORKER is None or not _WORKER.is_alive():
            _STOP.clear()
            _install_signal_handlers()
            _WORKER = threading.Thread(target=_worker_loop, name='audit-writer', daemon=True)
            _WORKER.start()


_SIGNAL_READY = False


def _install_signal_handlers():
    """SIGINT/SIGTERM/SIGBREAK 也能冲刷一次；只在主线程注册。"""
    global _SIGNAL_READY
    if _SIGNAL_READY or threading.current_thread() is not threading.main_thread():
        return
    _SIGNAL_READY = True
    for name in ('SIGINT', 'SIGTERM', 'SIGBREAK'):
        number = getattr(signal, name, None)
        if number is None:
            continue
        try:
            signal.signal(number, _on_signal)
        except (ValueError, OSError):
            pass


def _on_signal(number, frame):
    flush_now(timeout=3)
    try:
        signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)
    except Exception:
        os._exit(1)


def _enqueue(item):
    try:
        _ensure_worker()
        _QUEUE.put(item)
    except Exception as error:
        _set_error(error)


def _worker_loop():
    pending_jsonl, pending_ui = {}, {}
    try:
        db = _catchup(_open_db())
    except Exception as error:
        _set_error(error)
        db = None
    dirty = 0
    last_flush = time.monotonic()
    last_report = 0.0        # 首个样本产生后立即出第一份报表，之后按 REPORT_INTERVAL 节流

    def flush_pending():
        nonlocal last_flush
        if pending_jsonl:
            _flush_jsonl(pending_jsonl)
        if pending_ui:
            _flush_ui(pending_ui)
        last_flush = time.monotonic()

    while True:
        try:
            item = _QUEUE.get(timeout=0.25)
        except queue.Empty:
            item = None
        if item is not None:
            kind = item[0]
            if kind == 'jsonl':
                pending_jsonl.setdefault(item[1], []).append(item[2])
            elif kind == 'ui':
                pending_ui.setdefault(item[1], []).append(item[2])
            elif kind == 'stats':
                db, dirty = _store_stats(db, item[1], item[2], item[3], dirty)
        if (pending_jsonl or pending_ui) and (time.monotonic() - last_flush >= FLUSH_INTERVAL
                                              or _QUEUE.empty()):
            flush_pending()
        if dirty and _QUEUE.empty() and time.monotonic() - last_report >= REPORT_INTERVAL:
            db = _report(db)
            dirty = 0
            last_report = time.monotonic()
        if _STOP.is_set() and _QUEUE.empty():
            flush_pending()
            if dirty and db is not None:
                db = _report(db)
                flush_pending()          # _report 里的 ui_log 也要落盘
            if db is not None:
                db.close()
            return


def flush_now(timeout=5):
    """把队列里的内容立即写完（关窗 / 刷取结束时调用），可重复调用。"""
    _STOP.set()
    worker = _WORKER
    if worker is not None and worker.is_alive() and threading.current_thread() is not worker:
        worker.join(timeout=timeout)


atexit.register(flush_now)


def record(kind, body):
    now = datetime.now()
    _enqueue(('jsonl', now.strftime('%Y%m%d'),
              (now.astimezone().isoformat(timespec='microseconds'), kind, body)))


def ui_log(text):
    now = datetime.now()
    _enqueue(('ui', now.strftime('%Y%m%d'),
              (now.strftime('[%H:%M:%S] '), str(text))))


# ---------------- 掉落统计（后台线程内） ----------------

def _open_db():
    folder = directory()
    folder.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(folder / '掉落统计.sqlite3', timeout=10)
    # WAL 让读写互不阻塞；统计场景掉电最多丢最后几条
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=NORMAL')
    except sqlite3.DatabaseError:
        pass
    db.execute('CREATE TABLE IF NOT EXISTS samples (id TEXT PRIMARY KEY, conditions TEXT, group_id TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS exposures (sample TEXT, source TEXT, PRIMARY KEY(sample,source))')
    db.execute('CREATE TABLE IF NOT EXISTS items (sample TEXT, source TEXT, category TEXT, item TEXT, quantity INTEGER, PRIMARY KEY(sample,source,category,item))')
    # 报表聚合依赖这些索引，旧库打开时自动补齐
    db.execute('CREATE INDEX IF NOT EXISTS ix_samples_group ON samples(group_id)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_exposures_sample ON exposures(sample)')
    db.execute('CREATE INDEX IF NOT EXISTS ix_items_sample ON items(sample)')
    db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
    db.commit()
    return db


def _pending_report(db):
    """上次退出前没来得及重算的样本（例如被强杀、断电）。"""
    try:
        total = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
        row = db.execute("SELECT value FROM meta WHERE key='reported_samples'").fetchone()
        return total > (int(row[0]) if row else 0)
    except sqlite3.Error:
        return False


def _catchup(db):
    """启动时补算一份报表，减少「最后几把没进 CSV」。"""
    if _pending_report(db):
        ui_log('检测到上次未并入报表的样本，启动时补算一次')
        db = _report(db)
    return db


def _parse_stats(context, payload, response):
    drops = response.get('drops')
    if not isinstance(drops, dict) or not isinstance(drops.get('newDrops'), list):
        return None
    if response.get('code') != 200 or response.get('error') or not drops.get('copyId'):
        return None
    # 缺失回包不计入样本；明确的空newDrops仍计入副本样本。
    mid = drops.get('id', (payload or {}).get('mid', '未知'))
    condition = {'day': datetime.now().strftime('%Y-%m-%d'), 'mid': str(mid),
                 'role': drops.get('role1'), 'mode': drops.get('mode'),
                 'vip': context.get('vip'),
                 'dropProbability': drops.get('dropProbability'),
                 'buffs': sorted([{'buffId': b.get('buffId'), 'type': b.get('type'),
                                   'number': b.get('number')} for b in drops.get('buffs', [])
                                  if isinstance(b, dict)], key=lambda b: str(b))}
    condition_json = json.dumps(condition, ensure_ascii=False, sort_keys=True, default=str)
    group = hashlib.sha256(condition_json.encode()).hexdigest()
    sample = hashlib.sha256(json.dumps([context.get('account'), context.get('slot'),
                                        mid, drops['copyId']], default=str).encode()).hexdigest()
    totals = {}
    monsters = set()
    for drop in drops['newDrops']:
        if not isinstance(drop, dict) or 'monsterId' not in drop:
            raise ValueError('掉落数组缺少怪物信息，跳过本次统计')
        monster = str(drop['monsterId'])
        monsters.add(monster)
        repetitions = int(drop.get('count', 1))
        for category in ('item', 'equip', 'feather', 'soul', 'petCrystal'):
            values = drop.get(category) or {}
            if not isinstance(values, dict):
                raise ValueError('未知掉落结构，跳过本次统计')
            for item_id, picks in values.items():
                picks = picks if isinstance(picks, list) else [picks]
                amount = sum(int(x.get('count', 1)) if isinstance(x, dict) else 1 for x in picks) * repetitions
                if amount <= 0:
                    continue
                for source in ('副本', '怪物:' + monster):
                    key = (source, category, str(item_id))
                    totals[key] = totals.get(key, 0) + amount
    return condition_json, group, sample, totals, monsters


def _store_stats(db, context, payload, response, dirty):
    try:
        parsed = _parse_stats(context, payload, response)
    except Exception as error:
        _set_error(error)
        record('statistics_error', {'error': str(error)})
        return db, dirty
    if not parsed:
        return db, dirty
    condition_json, group, sample, totals, monsters = parsed
    if db is None:
        db = _open_db()
    try:
        with db:
            inserted = db.execute('INSERT OR IGNORE INTO samples VALUES (?,?,?)',
                                  (sample, condition_json, group)).rowcount
            if not inserted:
                return db, dirty
            for source in ['副本'] + ['怪物:' + m for m in sorted(monsters)]:
                db.execute('INSERT INTO exposures VALUES (?,?)', (sample, source))
            for (source, category, item), quantity in totals.items():
                db.execute('INSERT INTO items VALUES (?,?,?,?,?)',
                           (sample, source, category, item, quantity))
    except Exception as error:
        _set_error(error)
        record('statistics_error', {'error': str(error)})
        return db, dirty
    return db, dirty + 1


_REPORT_SQL = '''WITH g AS (
    SELECT s.group_id AS gid, e.source AS src, COUNT(*) AS total
    FROM samples s JOIN exposures e ON e.sample = s.id
    GROUP BY 1, 2
), a AS (
    SELECT s.group_id AS gid, s.conditions AS conditions, i.source AS src,
           i.category AS cat, i.item AS item, COUNT(*) AS hits, SUM(i.quantity) AS qty
    FROM items i JOIN samples s ON s.id = i.sample
    GROUP BY 1, 2, 3, 4, 5
)
SELECT a.conditions, a.src, a.cat, a.item, a.hits, a.qty, COALESCE(g.total, 0) AS total
FROM a LEFT JOIN g ON g.gid = a.gid AND g.src = a.src
ORDER BY a.gid, a.src, a.cat, a.item'''


def _report(db):
    """按分组重算整份 CSV；分母用「分组×来源」的曝光总数，不再逐行子查询。"""
    try:
        if db is None:
            db = _open_db()
        started = time.monotonic()
        rows = db.execute(_REPORT_SQL).fetchall()
        names = _names()
        temporary = directory() / '掉落概率统计.csv.tmp'
        temporary.parent.mkdir(parents=True, exist_ok=True)
        with temporary.open('w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['日期', '关卡ID', '关卡名称', '来源', '怪物名称', '类型', '物品ID', '物品名称', '样本数', '有掉落局数',
                             '至少一件的估计概率', '95%区间下限', '95%区间上限', '平均分配数量', '条件'])
            for conditions, source, category, item, hits, quantity, total in rows:
                if not total:
                    continue
                cond = json.loads(conditions)
                low, high = _wilson(hits, total)
                item_name = next((names[t][item] for t in ('Prop', 'Equipment', 'Feather', 'Soul')
                                  if item in names[t]), '')
                monster_name = names['Monster'].get(source.split(':')[-1], '')
                writer.writerow([cond['day'], cond['mid'], names['Dungeon'].get(cond['mid'], ''),
                                 source, monster_name, category, item, item_name, total, hits,
                                 hits/total, low, high, quantity/total, conditions])
        try:
            os.replace(temporary, directory() / '掉落概率统计.csv')
        except PermissionError:
            # Excel占用报表时立即另存，不等待。
            fallback = directory() / ('掉落概率统计_更新_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.csv')
            os.replace(temporary, fallback)
            ui_log('掉落统计报表被占用，已另存：' + str(fallback))
        # 记账：这批样本已经进过报表，下次启动不必补算
        total = db.execute('SELECT COUNT(*) FROM samples').fetchone()[0]
        db.execute("INSERT OR REPLACE INTO meta VALUES('reported_samples', ?)", (str(total),))
        db.commit()
        ui_log('掉落报表已更新：%d 行，耗时 %.0f ms' % (len(rows), (time.monotonic() - started) * 1000))
    except Exception as error:
        _set_error(error)
        record('statistics_error', {'error': str(error)})
    return db


def _stats(context, route, payload, response):
    drops = response.get('drops')
    if not isinstance(drops, dict) or not isinstance(drops.get('newDrops'), list):
        return
    if response.get('code') != 200 or response.get('error') or not drops.get('copyId'):
        return
    _enqueue(('stats', dict(context), payload, response))


# ---------------- 请求流包装 ----------------

class AuditFlow:
    def __init__(self, flow, account, slot):
        self._flow = flow
        self.context = {'account': hashlib.sha256(str(account).encode()).hexdigest()[:16], 'slot': slot}

    def __getattr__(self, name):
        return getattr(self._flow, name)

    def query_entry(self, *args, **kwargs):
        try:
            result = self._flow.query_entry(*args, **kwargs)
            record('connection', {'context': self.context, 'result': result})
            return result
        except Exception as error:
            record('exception', {'context': self.context, 'route': 'queryEntry', 'error': str(error)})
            raise

    def auth(self, *args, **kwargs):
        try:
            result = self._flow.auth(*args, **kwargs)
            # 捕获所有推送，不替换原有回调。
            self._flow.game._audit_push = lambda route, body: record('push', {
                'context': dict(self.context), 'route': route, 'response': body})
            record('auth', {'context': self.context, 'response': result})
            return result
        except Exception as error:
            record('exception', {'context': self.context, 'route': 'auth', 'error': str(error)})
            raise

    def request(self, route, payload, **kwargs):
        started = time.monotonic()
        try:
            response = self._flow.request(route, payload, **kwargs)
        except Exception as error:
            record('exception', {'context': self.context, 'route': route,
                                  'request': payload, 'error': str(error)})
            raise
        record('request', {'context': self.context, 'route': route, 'request': payload,
                           'response': response, 'seconds': time.monotonic()-started})
        if isinstance(response, dict):
            if route == 'scene.playerHandler.enterScene':
                user = response.get('user') or {}
                self.context['vip'] = user.get('vipLevel', user.get('vip'))
            try:
                _stats(self.context, route, payload if isinstance(payload, dict) else {}, response)
            except Exception as error:
                _set_error(error)
                record('statistics_error', {'route': route, 'error': str(error)})
        return response
