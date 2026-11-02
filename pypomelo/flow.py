"""完整登录/进游戏编排(对应 AS 的两阶段连接)。

流程:
  1. (可选) 用 4399 cookie 换游戏 token: login4399.fetch_game_token()
  2. TLS 连 gate 服 -> 握手 -> request("gate.gateHandler.queryEntry", {uid})
     -> 返回 {host, port}
  3. 断开 gate, TLS 连场景服 host:port -> 握手
  4. request("connector.entryHandler.auth", {token, userAgent}) -> 进存档
  5. 之后 request/on 正常发日常任务、收推送

注意: PomeloClient 的回调都跑在【接收线程】里, 所以握手回调里只能"发出请求立刻返回",
不能在里面同步等待响应, 否则接收线程被堵死读不到回包(死锁)。
"""

import threading
import time

from .client import PomeloClient
from .login4399 import DEFAULT_UA


class GameLoginFlow:
    def __init__(self, uid, token, user_agent=DEFAULT_UA,
                 proto_cache_path=None):
        self.uid = uid
        self.token = token
        self.user_agent = user_agent
        self.proto_cache_path = proto_cache_path
        self.gate = None
        self.game = None
        self._copy_created_at = {}

    # 进游戏后(主线程)用的同步请求
    def _request_sync(self, client, route, data, timeout=15):
        done = threading.Event()
        box = {}

        def cb(body):
            box["body"] = body
            done.set()

        client.request(route, data, cb)
        if not done.wait(timeout):
            raise TimeoutError("等待 %s 响应超时" % route)
        return box["body"]

    # ---- 阶段1: gate 服 queryEntry ----
    def query_entry(self, gate_host, gate_port, timeout=15):
        self.gate = PomeloClient(proto_cache_path=self.proto_cache_path)
        done = threading.Event()
        entry = {}

        def on_query_resp(body):
            entry["resp"] = body
            done.set()

        def on_handshake(resp):
            # 接收线程里: 只发请求, 立即返回, 不等待
            self.gate.request(
                "gate.gateHandler.queryEntry", {"uid": self.uid}, on_query_resp)

        self.gate.connect(gate_host, gate_port, user={},
                          handshake_cb=on_handshake)
        if not done.wait(timeout + 5):
            raise TimeoutError("gate 握手/queryEntry 超时")
        body = entry["resp"]
        host, port = body["host"], body["port"]
        self.gate.disconnect()
        self.gate = None
        return host, port

    # ---- 阶段2: 场景服 auth ----
    def auth(self, host, port, timeout=15):
        self.game = PomeloClient(proto_cache_path=self.proto_cache_path)
        done = threading.Event()
        result = {}

        def on_auth_resp(body):
            result["body"] = body
            done.set()

        def on_handshake(resp):
            self.game.request(
                "connector.entryHandler.auth",
                {"token": self.token, "userAgent": self.user_agent},
                on_auth_resp)

        self.game.connect(host, port, user={}, handshake_cb=on_handshake)
        if not done.wait(timeout + 5):
            raise TimeoutError("场景服握手/auth 超时")
        body = result["body"]
        if isinstance(body, dict) and body.get("code") == 50:
            raise RuntimeError("auth 被拒: %s" % body.get("error"))
        return body

    # ---- 一把连到底 ----
    def login(self, gate_host, gate_port, timeout=15):
        host, port = self.query_entry(gate_host, gate_port, timeout)
        return self.auth(host, port, timeout)

    # ---- 进游戏后发请求(主线程调用) ----
    def request(self, route, data, timeout=15):
        if not self.game:
            raise RuntimeError("尚未登录进游戏")
        settle = route == 'scene.copyHandler.syncDropInfoNew' and isinstance(data, dict)
        if settle:
            created = self._copy_created_at.get(str(data.get('copyId')))
            if created is not None:
                wait = 1.25 - (time.monotonic() - created)
                if wait > 0:
                    time.sleep(wait)
        # 超时/断线直接抛出，绝不在结果未知时重复提交。
        result = self._request_sync(self.game, route, data, timeout)
        if route == 'scene.copyHandler.createSinglePlayerCopy' and isinstance(result, dict):
            drops = result.get('drops') or {}
            if result.get('code') == 200 and not result.get('error') and drops.get('copyId'):
                self._copy_created_at[str(drops['copyId'])] = time.monotonic()
                if len(self._copy_created_at) > 64:
                    self._copy_created_at.pop(next(iter(self._copy_created_at)))
        if (settle and int(data.get('completed', 0) or 0) != 0
                and isinstance(result, dict) and result.get('code') == 500
                and str(result.get('error', '')).strip() == '通关数据异常'):
            from toolbox_audit import record
            record('settlement_retry', {'route': route, 'request': data, 'firstResponse': result})
            time.sleep(.25)
            result = self._request_sync(self.game, route, data, timeout)
            record('settlement_retry_result', {'route': route, 'response': result})
        return result

    def on(self, route, callback):
        if not self.game:
            raise RuntimeError("尚未登录进游戏")
        self.game.on(route, callback)

    def disconnect(self):
        if self.game:
            self.game.disconnect()
        if self.gate:
            self.gate.disconnect()
