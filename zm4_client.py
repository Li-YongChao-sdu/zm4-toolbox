# -*- coding: utf-8 -*-
"""
造梦西游4 (ZM4) 协议层刷本模块
功能：登录、创建副本、完成副本、同步掉落、获取制作书等主线道具
"""
import sys
import os
import json
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pypomelo.login4399 import fetch_game_token
from pypomelo.flow import GameLoginFlow
from ptlogin_login import login_by_password
from zm4_version import enter_record

logger = logging.getLogger("zm4")

# ============ 常量 ============
ZM4_GAME_ID = "100036512"
ZM4_GATE_IPS = [
    "g1-zm4.4399zmxy.com",
    "g2-zm4.4399zmxy.com",
    "g3-zm4.4399zmxy.com",
    "g4-zm4.4399zmxy.com",
    "g5-zm4.4399zmxy.com",
    "g6-zm4.4399zmxy.com",
]
ZM4_PORT = 3010
ZM4_VERSION = 587  # 兼容旧调用；正式登录由zm4_version从官网检查并经服务器验证
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.101 Safari/537.36"


class ZM4Client:
    """造梦西游4 协议客户端"""

    def __init__(self, uid, username, cookies, record_index=0, user_agent=None):
        """
        初始化客户端
        :param uid: 用户UID
        :param username: 用户名
        :param cookies: 4399登录cookie字典
        :param record_index: 存档索引 (0-7)
        :param user_agent: User-Agent
        """
        self.uid = uid
        self.username = username
        self.cookies = cookies
        self.record_index = record_index
        self.user_agent = user_agent or DEFAULT_UA
        self.flow = None
        self.player_info = None
        self._connected = False

    @classmethod
    def from_password(cls, username, password, record_index=0, user_agent=None):
        """
        账密登录创建客户端（自动获取cookie+token）
        :param username: 4399账号
        :param password: 4399密码
        :param record_index: 存档索引 (0-7)
        :param user_agent: User-Agent
        :return: ZM4Client实例（尚未login，需调用.login()）
        """
        logger.info("账密登录: %s", username)
        res = login_by_password(username, password, verbose=False)
        if not res.get("ok"):
            if res.get("need_captcha"):
                raise RuntimeError("账密登录需要验证码，请先在浏览器登录一次或改用cookie")
            raise RuntimeError("账密登录失败: %s" % res.get("error", "未知错误"))

        cookies = res["cookies"]
        uid = str(res.get("uid", cookies.get("Puser", "")))
        logger.info("账密登录成功: uid=%s, USESSIONID=%s...", uid, cookies.get("USESSIONID", "")[:8])

        return cls(uid=uid, username=username, cookies=cookies,
                   record_index=record_index, user_agent=user_agent)

    @classmethod
    def from_cookie_string(cls, cookie_string, record_index=0, user_agent=None):
        """从浏览器复制的完整 Cookie 请求头创建客户端，不保存原始字符串。"""
        if not isinstance(cookie_string, str) or not cookie_string.strip():
            raise RuntimeError("请粘贴完整的4399 Cookie")

        raw = cookie_string.strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in (chr(34), chr(39)):
            raw = raw[1:-1].strip()
        if raw[:7].lower() == "cookie:":
            raw = raw[7:].strip()

        cookies = {}
        for part in raw.replace("\r", "").split(";"):
            part = part.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] == '"':
                value = value[1:-1]
            if name:
                cookies[name] = value

        required = ("USESSIONID", "Uauth", "Pauth", "Xauth", "Puser")
        missing = [name for name in required if not cookies.get(name)]
        if missing:
            raise RuntimeError("Cookie 缺少必要字段：%s" % ", ".join(missing))

        auth_parts = cookies["Pauth"].split("|")
        if len(auth_parts) < 2 or not auth_parts[0].isdigit():
            raise RuntimeError("Cookie 中的 Pauth 格式无效")

        uid = auth_parts[0]
        username = cookies["Puser"].strip()
        if not username or auth_parts[1] != username:
            raise RuntimeError("Cookie 中的 Pauth 与 Puser 不匹配")

        return cls(uid=uid, username=username, cookies=cookies,
                   record_index=record_index, user_agent=user_agent)

    def login(self):
        """登录游戏，进入指定存档"""
        logger.info("开始登录 ZM4, uid=%s, record=%d", self.uid, self.record_index)

        # 1. 获取游戏token
        token = fetch_game_token(self.uid, self.username, self.cookies, game_id=ZM4_GAME_ID)
        self.flow = GameLoginFlow(self.uid, token)

        # 2. queryEntry 获取场景服地址
        host = port = None
        for ip in ZM4_GATE_IPS:
            try:
                host, port = self.flow.query_entry(ip, ZM4_PORT, timeout=10)
                break
            except Exception as e:
                logger.warning("gate %s 失败: %s", ip, e)
                continue
        if not host:
            raise RuntimeError("所有gate服连接失败")

        # 3. auth 认证
        authenticated = self.flow.auth(host, port, timeout=15)
        if authenticated.get('code') != 200 or authenticated.get('error'):
            self.flow.disconnect()
            raise RuntimeError('游戏认证失败：%s' % authenticated.get('error', authenticated.get('code')))

        # 4. 选择存档
        try:
            entry_result = enter_record(self.flow, self.record_index, self.user_agent)
        except Exception:
            self.flow.disconnect()
            raise

        if entry_result.get("code") != 200:
            raise RuntimeError("进入存档失败: %s" % entry_result.get("error"))

        self.player_info = entry_result.get("record", {})
        p1 = self.player_info.get("p1", {})
        logger.info("登录成功, 角色: %s Lv.%s",
                    p1.get("kindName", "未知"), p1.get("level", "?"))

        # 5. 进入场景
        self.flow.request("scene.playerHandler.enterScene", None, timeout=15)
        time.sleep(0.5)

        self._connected = True
        return self.player_info

    def _get_player_attrs(self):
        """获取玩家属性，用于propertyP1Str"""
        p1 = self.player_info.get("p1", {}) if self.player_info else {}
        return {
            "hpMax": p1.get("hpMax", 0),
            "mpMax": p1.get("mpMax", 0),
            "atk": p1.get("atk", 0),
            "phyDef": p1.get("phyDef", 0),
            "reHP": p1.get("reHP", 0),
            "reMP": p1.get("reMP", 0),
            "experience": p1.get("experience", 0),
        }

    def create_copy(self, dungeon_id, cost_gem=0):
        """
        创建单人副本
        :param dungeon_id: 关卡ID
        :param cost_gem: 消耗宝石 (0=免费)
        :return: 创建结果 (含drops)
        """
        result = self.flow.request("scene.copyHandler.createSinglePlayerCopy", {
            "mid": dungeon_id,
            "costGem": cost_gem,
        }, timeout=15)
        if result.get("code") != 200:
            raise RuntimeError("创建副本失败: %s" % result.get("error"))
        return result

    def finish_dungeon(self, dungeon_id):
        """完成副本"""
        result = self.flow.request("scene.copyHandler.finishDungeon", {
            "dungeonId": dungeon_id,
        }, timeout=15)
        if result.get("code") != 200:
            raise RuntimeError("完成副本失败: %s" % result.get("error"))
        return result

    def sync_drop(self, drops, hit_combo=100, max_retry=2):
        """
        同步掉落（关键：mobIds/killMonsters只包含有掉落的怪物）
        :param drops: create_copy返回的drops对象
        :param hit_combo: 最大连击数
        :param max_retry: 最大重试次数
        :return: sync结果
        """
        copy_id = drops.get("copyId", 0)
        new_drops = drops.get("newDrops", [])
        attrs = self._get_player_attrs()

        pick_items = []
        mob_ids = []
        kill_monsters = []
        total_exp = 0
        total_sp = 0

        for d in new_drops:
            mid = d.get("monsterId", "0")
            idx = d.get("index", 0)
            total_exp += d.get("exp", 0)
            total_sp += d.get("spirit", 0)

            # 关键：只有有掉落的怪物才加入mobIds和killMonsters
            has_item = "item" in d and len(d["item"]) > 0
            if has_item:
                mob_ids.append(mid)
                kill_monsters.append("%s_%d" % (mid, idx))
                for item_id, item_list in d["item"].items():
                    for item in item_list:
                        pick_items.append(item)

        property_p1_str = "%d;%d;%d;%d;%d;%d" % (
            attrs["hpMax"], attrs["mpMax"], attrs["atk"],
            attrs["phyDef"], attrs["reHP"], attrs["reMP"],
        )

        sync_data = {
            "copyId": copy_id,
            "pickItems": pick_items,
            "mobIds": mob_ids,
            "killMonsters": kill_monsters,
            "completed": 1,
            "currentEXP": attrs["experience"],
            "pickExp": total_exp,
            "pickSp": total_sp,
            "propertyP1Str": property_p1_str,
            "propertyP2Total": 0,
            "hitCombo": hit_combo,
        }

        last_error = None
        for attempt in range(max_retry + 1):
            try:
                result = self.flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                if result.get("code") == 200:
                    return result
                last_error = result.get("error", "未知错误")
            except Exception as e:
                last_error = str(e)

            if attempt < max_retry:
                logger.warning("sync掉落失败(第%d次): %s, 重试中...", attempt + 1, last_error)
                time.sleep(1)

        raise RuntimeError("同步掉落失败: %s" % last_error)

    def farm_dungeon(self, dungeon_id, times=1, delay=0.3):
        """
        刷副本（完整流程：创建→完成→同步）
        :param dungeon_id: 关卡ID
        :param times: 刷的次数
        :param delay: 每次间隔秒数
        :return: 掉落统计 {物品ID: 数量}
        """
        drop_stats = {}
        success = 0
        fail = 0

        for i in range(times):
            try:
                # 1. 创建副本
                create_result = self.create_copy(dungeon_id)
                drops = create_result.get("drops", {})

                # 统计本次掉落
                new_drops = drops.get("newDrops", [])
                for d in new_drops:
                    if "item" in d:
                        for item_id, item_list in d["item"].items():
                            drop_stats[item_id] = drop_stats.get(item_id, 0) + len(item_list)

                time.sleep(delay)

                # 2. 完成副本
                self.finish_dungeon(dungeon_id)
                time.sleep(delay)

                # 3. 同步掉落
                self.sync_drop(drops)

                success += 1
                logger.info("[%d/%d] 副本成功, 当前掉落: %s", i + 1, times,
                            {k: v for k, v in list(drop_stats.items())[:5]})

                time.sleep(delay)

            except Exception as e:
                fail += 1
                logger.error("[%d/%d] 副本失败: %s", i + 1, times, e)
                time.sleep(1)

        logger.info("刷本完成: 成功%d, 失败%d", success, fail)
        return drop_stats, success, fail

    def use_item(self, item_id, num=1):
        """使用物品"""
        return self.flow.request("scene.playerHandler.useItem1", {
            "itemId": item_id,
            "pNum": num,
        }, timeout=10)

    def disconnect(self):
        """断开连接"""
        if self.flow:
            self.flow.disconnect()
        self._connected = False


def load_item_names(config_path=None):
    """加载物品名称表"""
    if config_path is None:
        config_path = r"D:\zmxy\zm5ConfigParser\新建文件夹\新建文件夹\zm4cofigparser\新建文件夹\output\147___Prop.xml.json"
    try:
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("RECORD", [])
        return {str(r["id"]): r.get("name", str(r["id"])) for r in records}
    except Exception as e:
        logger.warning("加载物品名称表失败: %s", e)
        return {}


if __name__ == "__main__":
    # 示例：账密登录刷金玉宫获取朱电武器制作书
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 方式1：账密登录（推荐，自动获取cookie）
    client = ZM4Client.from_password(
        username="你的4399账号",
        password="你的4399密码",
        record_index=3,  # 存档3
    )

    # 方式2：cookie登录（手动粘贴cookie）
    # COOKIES = {
    #     "USESSIONID": "你的USESSIONID",
    #     "Uauth": "你的Uauth",
    #     "Pauth": "你的Pauth",
    #     "Xauth": "你的Xauth",
    #     "Puser": "你的用户名",
    # }
    # client = ZM4Client(uid="你的UID", username="你的用户名", cookies=COOKIES, record_index=3)

    try:
        client.login()
        # 刷金玉宫(id=27) 10次
        stats, success, fail = client.farm_dungeon(27, times=10)

        print("\n=== 掉落统计 ===")
        names = load_item_names()
        for item_id, count in sorted(stats.items(), key=lambda x: -x[1]):
            name = names.get(str(item_id), item_id)
            print("  %s (%s): %d个" % (name, item_id, count))

    finally:
        client.disconnect()
