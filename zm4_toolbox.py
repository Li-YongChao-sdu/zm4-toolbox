# -*- coding: utf-8 -*-
"""
造梦西游4 - 活动工具箱（集成版）
功能：活动、日常与副本辅助；包含地藏冥殿 / 虚空藏院协议结算领奖验证
"""
import sys
import os
import json
import threading
import copy
from datetime import datetime, timedelta
from toolbox_audit import AuditFlow, ui_log, take_error, directory as audit_directory, flush_now as flush_audit

# 配置中的普通补给，包含烤熟的桃子和萝卜；活动蟠桃不在此列。
SUPPLY_DROP_IDS = frozenset({"120100001", "120200001", "120100002",
                             "120200002", "120100003", "120200003"})


def _load_soul_name_map():
    """魂器名称表（188___Soul），用于掉落日志显示中文名。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "output_cg1_20260921_1_2", "188___Soul.xml.json")
    names = {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("RECORD", data if isinstance(data, list) else [])
        if isinstance(records, dict):
            records = [records]
        for r in records:
            if isinstance(r, dict):
                names[str(r.get("id"))] = r.get("name", "?")
    except Exception:
        pass
    return names


SOUL_NAME_MAP = _load_soul_name_map()


def soul_items(drop):
    """取出单条掉落的魂器实例：soul 字段格式为 {魂器ID: [实例串, ...]}。"""
    souls = drop.get("soul") or {}
    if not isinstance(souls, dict):
        return []
    result = []
    for soul_id, instances in souls.items():
        for inst in (instances if isinstance(instances, list) else [instances]):
            result.append((str(soul_id), inst))
    return result


def collect_soul_pickups(new_drops, pick_items, drop_stats=None):
    """把魂器实例并入 pickItems（魂器与普通道具都通过 pickItems 提交）。"""
    picked = []
    for drop in new_drops or []:
        for soul_id, inst in soul_items(drop):
            pick_items.append(inst)
            picked.append((soul_id, inst))
            if drop_stats is not None:
                drop_stats[soul_id] = drop_stats.get(soul_id, 0) + 1
    return picked


# 进关时 createSinglePlayerCopy 的 drops.newDrops 就是服务端当场生成的完整掉落表，
# 字段按品类命名：item(道具) / equip(装备) / feather(羽毛) / soul(魂器) / 晶核……
# 这里把「{道具id: [实例串…]}」形态的分组统一取出来，避免只捡 item 而漏掉其它品类。
DROP_META_KEYS = {"exp", "spirit", "index", "monsterId", "count", "fuIntegral", "score"}


def drop_groups(drop):
    """单条掉落里所有可拾取分组：[(字段名, {道具id: [实例串…]})]。"""
    if not isinstance(drop, dict):
        return []
    return [(key, value) for key, value in drop.items()
            if key not in DROP_META_KEYS and isinstance(value, dict) and value]



class GlobalPickupFilter:
    """每个游戏连接统一过滤可选择拾取的普通补给。"""
    def __init__(self, flow, enabled):
        self._flow = flow
        self._enabled = enabled
        self.before_create = None
        self._blocked_pick_ids = set()

    def __getattr__(self, name):
        return getattr(self._flow, name)

    def request(self, route, payload, **kwargs):
        if route == 'scene.copyHandler.createSinglePlayerCopy' and self.before_create:
            self.before_create(payload)
        if self._enabled() and isinstance(payload, dict) and "pickItems" in payload:
            payload = dict(payload)
            payload["pickItems"] = [item for item in payload["pickItems"]
                                    if not self._is_blocked(item)]
        result = self._flow.request(route, payload, **kwargs)
        drops = result.get("drops") if isinstance(result, dict) else None
        if isinstance(drops, dict):
            for drop in drops.get("newDrops", []):
                for item_id, values in (drop.get("item") or {}).items():
                    if str(item_id) in SUPPLY_DROP_IDS:
                        for item in values if isinstance(values, list) else [values]:
                            self._blocked_pick_ids.add(self._pick_key(item))
            if self._enabled():
                result = copy.deepcopy(result)
                for drop in result["drops"].get("newDrops", []):
                    if isinstance(drop.get("item"), dict):
                        drop["item"] = {item_id: values for item_id, values in drop["item"].items()
                                        if str(item_id) not in SUPPLY_DROP_IDS}
        return result

    @staticmethod
    def _pick_key(item):
        if isinstance(item, dict):
            return str(item.get("pickId", item.get("entityId", item.get("id", ""))))
        return str(item)

    def _is_blocked(self, item):
        key = self._pick_key(item)
        item_id = str(item.get("itemId", item.get("id", ""))) if isinstance(item, dict) else key
        return item_id in SUPPLY_DROP_IDS or key in self._blocked_pick_ids

FOREST_PETS = {
    2000100: ("鼠仔", "吱吱鼠"),
    2000500: ("猴丸", "咚咚猴"),
    2000800: ("雪团", "瑞雪兽"),
    2000900: ("鱼丸", "泡泡鱼"),
    2001000: ("孤犬", "寂寞狗"),
    2001800: ("炎马", "咴咴马"),
}

MAIN_LEVELS = [
    (65, "金蟾宝宫"),
    (64, "伏龙宝树"),
    (63, "天禄金山"),
    (62, "血河池"),
    (61, "万世冥阁"),
    (60, "幽都鬼城"),
    (59, "桃止山"),
    (58, "业火莲台"),
    (57, "九泉"),
    (56, "罗酆谷"),
    (55, "往生路"),
    (54, "彼岸花海"),
    (53, "抱犊山"),
    (52, "梦影寺"),
    (51, "岁暮荒园"),
    (50, "罗浮山"),
    (49, "播冢山巅"),
    (48, "通冥铁索"),
    (47, "孤魂岭"),
    (46, "不周山"),
    (45, "幕山"),
    (44, "寒暑水"),
    (43, "七叶树窟"),
    (42, "菩提道场"),
    (41, "蓝毗尼园"),
    (40, "凌云渡"),
    (39, "星域"),
    (38, "钟晷极地"),
    (37, "太虚星河"),
    (36, "夙夜径"),
    (35, "壶中洞天"),
    (34, "幻境阁"),
    (33, "蜃楼城"),
    (32, "冻天"),
    (31, "寒山坡"),
    (30, "苍梧渊"),
    (29, "云川"),
    (28, "浮天台"),
    (27, "金玉宫"),
    (26, "琉璃宫"),
    (25, "万妖穴"),
    (24, "七星洞"),
    (23, "蝙蝠窟"),
    (22, "桃花谷"),
    (21, "水帘洞"),
    (20, "花果山"),
    (19, "傲来国"),
    (18, "百仙园"),
    (17, "金沙村"),
    (16, "冥海"),
    (15, "万佛朝阁"),
    (14, "锦绣峰"),
    (13, "五台山口"),
    (12, "金顶云海"),
    (11, "清音阁"),
    (10, "峨眉山道"),
    (9, "法华灵洞"),
    (8, "九龙宝殿"),
    (7, "普陀山脚"),
    (6, "神光金岭"),
    (5, "双溪寺"),
    (4, "九华山麓"),
    (3, "未央宫"),
    (2, "朱雀街"),
    (1, "玄武门"),
]

# 新存档逐关实测：这些隐藏关是下一关的前置；其他隐藏分支不进入自动路线。
MAINLINE_REQUIRED_HIDDEN = {
    9: 1001, 19: 1009, 23: 1012, 40: 1020, 43: 1021,
    45: 1022, 47: 1025, 48: 1026, 49: 1028, 50: 1029,
    51: 1030, 52: 1033, 53: 1034, 54: 1035, 55: 1037,
    56: 1038, 57: 1040, 58: 1042, 59: 1043, 60: 1044,
    61: 1046, 62: 1047, 63: 1048, 64: 1049, 65: 1051,
}

# 只自动执行已用账号完整验证过的日常任务路由。
DAILY_TASK_TESTED_ROUTES = {
    20002: ((2132, False),),             # 悲鸣冰川：四头虫
    20004: ((2133, False),),             # 悲鸣冰川：八头虫
    20008: ((2021, False), (2024, False), (2036, False)),  # 神兽森林→森林水底→赤鲤巢穴
    20006: ((2134, False),),              # 四阶九头虫
    20018: ((460, True), (461, True)),   # 噩梦不周山及隐藏BOSS；两关都带W
    20024: ((2102, False), (2103, False)),  # 迷雾沮泽藤蔓层→藤蔓1boss：枯叶螳螂
    20030: ((2114, False),),             # 空桑谷盘根窟：土魔猿
    20009: ((360, True),),               # 噩梦夙夜径：角木蛟
    20032: ((501, True), (10260, True)), # 噩梦通冥铁索及隐藏BOSS
}
DAILY_TASK_BATCH_PICKUP_IDS = {20009, 20030, 20032}

# 镜域（周挑战，0体力，每周10次共享，90001-90012）
JINGYU_LEVELS = [
    (90012, "云水镜(镜梵天)"),
    (90011, "永生泉隐藏"),
    (90010, "永生泉"),
    (90009, "神域金木"),
    (90008, "厄夜地宫"),
    (90007, "无极深渊隐藏"),
    (90006, "无极深渊"),
    (90005, "曼陀罗崖"),
    (90004, "浩瀚舍沙"),
    (90003, "碧落海隐藏"),
    (90002, "碧落海"),
    (90001, "逆星台"),
]

# 神域（消耗120体力，9001-9018）
SHENYU_LEVELS = [
    (9017, "云水镜"),
    (9014, "永生泉"),
    (9012, "神域金木"),
    (9009, "厄夜地宫"),
    (9007, "无极深渊"),
    (9005, "曼陀罗崖"),
    (9004, "浩瀚舍沙"),
    (9002, "碧落海"),
    (9001, "逆星台"),
]

# 神域普通关 -> 隐藏关/BOSS房入口候选；一次前置通关只进入一个隐藏房
SHENYU_HIDDEN_MAP = {
    9002: [(9003, "碧落海-隐藏")],
    9005: [(9006, "曼陀罗崖BOSS")],
    9007: [(9008, "无极深渊-隐藏")],
    # TaskType 100026 的 targetId=9011；最终BOSS湿婆·恶掉湮灭魂铃。
    # 9010 是湿婆分身，先进入会占用本次前置关的隐藏入口。
    9009: [(9011, "厄夜地宫-湿婆·恶（湮灭魂铃）")],
    9012: [(9013, "神域金木BOSS")],
    9014: [(9015, "永生泉BOSS"), (9016, "永生泉-隐藏")],
    9017: [(9018, "云水镜BOSS")],
}

NIGHTMARE_LEVELS = [
    (602, "噩梦金蟾宝宫", 60),
    (601, "噩梦伏龙宝树", 60),
    (600, "噩梦天禄金山", 60),
    (515, "噩梦血河池", 120),
    (514, "噩梦万世冥阁", 60),
    (513, "噩梦幽都鬼城", 60),
    (512, "噩梦桃止山", 60),
    (511, "噩梦业火莲台", 60),
    (510, "噩梦九泉", 60),
    (509, "噩梦罗酆谷", 60),
    (508, "噩梦往生路", 60),
    (507, "噩梦彼岸花海", 60),
    (506, "噩梦抱犊山", 60),
    (505, "噩梦梦影寺", 60),
    (504, "噩梦岁暮荒园", 60),
    (503, "噩梦罗浮山", 60),
    (502, "噩梦播冢山巅", 60),
    (501, "噩梦通冥铁索", 60),
    (500, "噩梦孤魂岭", 60),
    (460, "噩梦不周山", 60),
    (450, "噩梦幕山", 60),
    (440, "噩梦寒暑水", 60),
    (430, "噩梦七叶树窟", 60),
    (420, "噩梦菩提道场", 60),
    (410, "噩梦蓝毗尼园", 60),
    (400, "噩梦凌云渡", 60),
    (380, "噩梦钟晷极地", 60),
    (370, "噩梦太虚星河", 60),
    (360, "噩梦夙夜径", 60),
    (350, "噩梦壶中洞天", 60),
    (340, "噩梦幻境阁", 60),
    (330, "噩梦蜃楼城", 60),
    (320, "噩梦冻天", 60),
    (310, "噩梦寒山坡", 60),
    (300, "噩梦苍梧渊", 60),
]

import time
import importlib.util
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAILY_TASK_BATCH_FILE = os.path.join(BASE_DIR, "daily_task_batches.json")
PET_EQUIP_BATCH_FILE = os.path.join(BASE_DIR, "pet_equip_batches.json")
MOUNT_COPY_BATCH_FILE = os.path.join(BASE_DIR, "mount_copy_batches.json")
PET_EQUIP_STAGE_IDS = {
    "fish": (2036, 2037, 2038, 2043),
    "kong": (2112, 2113, 2114, 2115),
    "yue": (2122, 2123, 2124, 2125),
    "yun": (2142, 2143, 2144, 2145),
    "wan": (7002, 7003, 7004, 7005),
}
sys.path.insert(0, BASE_DIR)

from zm4_client import ZM4Client

# ========== 生存大冒险求解器 ==========
SOLVER_PATH = os.path.join(BASE_DIR, "question-model-solver-3.py")
if os.path.exists(SOLVER_PATH):
    _spec = importlib.util.spec_from_file_location("solver3", SOLVER_PATH)
    _solver_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_solver_mod)
    parse_markdown = _solver_mod.parse_markdown
    MARKDOWN_CONTENT = _solver_mod.MARKDOWN_CONTENT
    Solver = _solver_mod.Solver
else:
    Solver = None
    _solver_db = None

# 题目配置
CONFIG_DIR = os.path.join(BASE_DIR, "output_cg1_20260921_1_2")
THEME_CHALLENGE_FALLBACK = {
    1: [(1, 2071, "水火不容"), (2, 2072, "兄妹齐心"), (3, 2073, "九死一生"), (4, 2117, "九死一生")],
    2: [(1, 2068, "两只老虎"), (2, 2069, "天河双鱼"), (3, 2070, "千年守望"), (4, 2116, "千年守望")],
    3: [(1, 2077, "妖僧父子"), (2, 2078, "坠道仙童"), (3, 2079, "千丝百眼"), (4, 2119, "千丝百眼")],
    4: [(1, 2074, "阴魂不散"), (2, 2075, "怒目邪猴"), (3, 2076, "手足情深"), (4, 2118, "手足情深")],
}


def _config_records(data):
    records = data.get("RECORD", []) if isinstance(data, dict) else []
    if isinstance(records, dict):
        return [records]
    return records if isinstance(records, list) else []


def _load_theme_challenge_config():
    """从本地游戏配置读取轮换锚点、四组关卡和关卡名称。"""
    rotation_start = datetime(2022, 5, 6).date()
    groups = THEME_CHALLENGE_FALLBACK
    try:
        with open(os.path.join(CONFIG_DIR, "026___Common.xml.json"), "r", encoding="utf-8") as f:
            common_records = _config_records(json.load(f))
        if common_records:
            value = common_records[0].get("DungeonThemeStart")
            if value:
                rotation_start = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").date()

        with open(os.path.join(CONFIG_DIR, "036___Dungeon.xml.json"), "r", encoding="utf-8") as f:
            dungeon_records = _config_records(json.load(f))
        dungeon_names = {
            str(record.get("id")): record.get("name", "")
            for record in dungeon_records if isinstance(record, dict)
        }

        with open(os.path.join(CONFIG_DIR, "044___DungeonThemeList.xml.json"), "r", encoding="utf-8") as f:
            theme_records = _config_records(json.load(f))
        configured_groups = {}
        for record in theme_records:
            if not isinstance(record, dict):
                continue
            group_id = int(record.get("id", 0))
            dungeon_ids = [int(value) for value in str(record.get("dungeon", "")).split(";") if value]
            levels = [int(value) for value in str(record.get("dungeonLevel", "")).split(";") if value]
            if group_id and len(dungeon_ids) == len(levels):
                configured_groups[group_id] = [
                    (level, dungeon_id, dungeon_names.get(str(dungeon_id), "副本%d" % dungeon_id))
                    for level, dungeon_id in zip(levels, dungeon_ids)
                ]
        if len(configured_groups) == len(THEME_CHALLENGE_FALLBACK):
            groups = configured_groups
    except Exception:
        # 配置文件暂不可用时仍能按已核实的四组表显示。
        pass
    return rotation_start, groups


THEME_ROTATION_START, THEME_CHALLENGE_GROUPS = _load_theme_challenge_config()


def get_theme_rotation_period(now=None):
    """按 DungeonThemeStart 锚点，每周五轮换一组，返回当前组与周期日期。"""
    now = now or datetime.now()
    today = now.date()
    if today < THEME_ROTATION_START:
        return None
    group_ids = sorted(THEME_CHALLENGE_GROUPS)
    if not group_ids:
        return None
    week_index = (today - THEME_ROTATION_START).days // 7
    period_start = THEME_ROTATION_START + timedelta(days=week_index * 7)
    group_id = group_ids[week_index % len(group_ids)]
    return group_id, period_start, period_start + timedelta(days=6)


QUESTION_MAP = {}
if os.path.exists(CONFIG_DIR):
    try:
        with open(os.path.join(CONFIG_DIR, "154___Question.xml.json"), "r", encoding="utf-8") as f:
            qdata = json.load(f)
        qrecs = qdata.get("RECORD", [])
        if isinstance(qrecs, dict):
            qrecs = [qrecs]
        QUESTION_MAP = {str(r["id"]): r for r in qrecs}
    except:
        pass

ATTR_NAMES = {
    "born": "出身", "health": "健康", "power": "力量",
    "wisdom": "智慧", "charm": "魅力", "luck": "运气", "smart": "聪明"
}
ROLE_NAME_MAP = {"小唐": "A", "小猴": "B", "小猪": "C", "小沙": "D", "小白": "E", "小玉": "F", "小吒": "G"}
ROLE_ID_MAP = {1: "B", 2: "A", 3: "C", 4: "D", 5: "E", 6: "F", 7: "G"}
CODE_NAME_MAP = {v: k for k, v in ROLE_NAME_MAP.items()}

def get_role_code(attr):
    born = attr.get("born", "")
    if born in ROLE_NAME_MAP:
        return ROLE_NAME_MAP[born]
    return ROLE_ID_MAP.get(attr.get("id", 0), "?")

# ========== 活动配置 ==========
XIJING_ID = 2138
YUTU_ID = 2161
YUTU_MAX_SCORE = 4100

# 地藏 / 虚空藏特殊掉落副本。关卡配置显示每日各3次，且不消耗点券。
SPECIAL_DUNGEONS = [
    {"id": 6021, "name": "地藏冥殿", "boss": "宝珠地藏",
     "kills": [3902], "item_id": "174600017", "item_name": "宝珠舍利", "daily_max": 3},
    {"id": 6022, "name": "地藏冥殿", "boss": "宝印地藏",
     "kills": [4098], "item_id": "174600018", "item_name": "宝印舍利", "daily_max": 3},
    {"id": 6023, "name": "地藏冥殿", "boss": "日光地藏",
     "kills": [4132, 4133], "item_id": "174600019", "item_name": "日光舍利", "daily_max": 3},
    {"id": 6024, "name": "地藏冥殿", "boss": "檀陀地藏",
     "kills": [4172, 4173], "item_id": "174600020", "item_name": "檀陀舍利", "daily_max": 3},
    {"id": 6025, "name": "地藏冥殿", "boss": "持地地藏",
     "kills": [4218], "item_id": "174600021", "item_name": "持地舍利", "daily_max": 3},
    {"id": 6026, "name": "虚空藏院", "boss": "金刚虚空藏",
     "kills": [4273, 4274, 4275, 4276], "item_id": "174600022", "item_name": "金刚塔刹", "daily_max": 3},
]

for _special_info in SPECIAL_DUNGEONS:
    _special_info["shared_ids"] = tuple(range(6021, 6026)) if _special_info["id"] < 6026 else (6026,)

# 月宫厨房博饼奖励表
MOON_KITCHEN_REWARDS = {
    1: {"name": "罚黑", "mooncake": 1, "prob": "30.4%"},
    2: {"name": "一秀", "mooncake": 5, "prob": "37.3%"},
    3: {"name": "二举", "mooncake": 10, "prob": "20.0%"},
    4: {"name": "四进", "mooncake": 20, "prob": "4.1%"},
    5: {"name": "三红", "mooncake": 40, "prob": "5.4%"},
    6: {"name": "对堂", "mooncake": 80, "prob": "1.5%"},
    7: {"name": "状元", "mooncake": 160, "prob": "1.2%"},
    8: {"name": "状元插金花", "mooncake": 320, "prob": "0.1%"},
}


from limited_activity_pages import LimitedActivityPages
from account_profiles import AccountProfiles
from my_daily import MyDailyWindow, load_schedule, save_schedule, schedule_path, update_schedule_identity


from jiuzhuan_ui import JiuZhuanPage
from halloween_activity import HalloweenPage


class ToolBoxApp(HalloweenPage, JiuZhuanPage, LimitedActivityPages, AccountProfiles):
    def __init__(self, root):
        self.root = root
        self.root.title("造梦西游4 - 活动工具箱 v5.0（2026-10-30版）")
        screen_w, screen_h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        try:
            import ctypes
            from ctypes import wintypes
            work = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work), 0):
                screen_w, screen_h = work.right - work.left, work.bottom - work.top
        except (AttributeError, OSError):
            pass
        self.root.geometry('%dx%d' % (min(1180, max(320, screen_w - 40)),
                                      min(800, max(240, screen_h - 70))))
        self.root.minsize(min(640, max(320, screen_w - 40)),
                          min(420, max(240, screen_h - 70)))

        self.client = None
        self.saves = []
        self.current_save = None
        self._solver_db = parse_markdown(MARKDOWN_CONTENT) if Solver else None
        self._survival_data = None
        self._dice_stop_event = threading.Event()
        self._forest_stop_event = threading.Event()

        self._build_ui()
        self._quick_restore()
        self.root.protocol("WM_DELETE_WINDOW", self._close_toolbox)

    def _build_ui(self):
        # Full-window viewport: every existing page remains reachable at small sizes.
        viewport = ttk.Frame(self.root)
        viewport.pack(fill='both', expand=True)
        viewport.rowconfigure(0, weight=1)
        viewport.columnconfigure(0, weight=1)
        self._ui_canvas = tk.Canvas(viewport, highlightthickness=0, borderwidth=0)
        self._ui_canvas.grid(row=0, column=0, sticky='nsew')
        self._ui_vscroll = ttk.Scrollbar(viewport, orient='vertical', command=self._ui_canvas.yview)
        self._ui_vscroll.grid(row=0, column=1, sticky='ns')
        self._ui_hscroll = ttk.Scrollbar(viewport, orient='horizontal', command=self._ui_canvas.xview)
        self._ui_hscroll.grid(row=1, column=0, sticky='ew')
        self._ui_canvas.configure(yscrollcommand=self._ui_vscroll.set, xscrollcommand=self._ui_hscroll.set)
        self._ui_host = ttk.Frame(self._ui_canvas)
        self._ui_window = self._ui_canvas.create_window(0, 0, window=self._ui_host, anchor='nw')
        self._ui_host.bind('<Configure>', self._resize_ui_viewport)
        self._ui_canvas.bind('<Configure>', self._resize_ui_viewport)
        self.root.bind('<MouseWheel>', self._scroll_ui_viewport, add='+')
        self.root.bind('<Shift-MouseWheel>', self._scroll_ui_viewport, add='+')
        # 顶部登录区
        login_frame = ttk.LabelFrame(self._ui_host, text="登录", padding=8)
        login_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(login_frame, text="账号:").grid(row=0, column=0, sticky="e", padx=3)
        self.entry_user = ttk.Entry(login_frame, width=18)
        self.entry_user.grid(row=0, column=1, padx=3)

        ttk.Label(login_frame, text="密码:").grid(row=0, column=2, sticky="e", padx=3)
        self.entry_pass = ttk.Entry(login_frame, width=18, show="*")
        self.entry_pass.grid(row=0, column=3, padx=3)

        self.btn_login = ttk.Button(login_frame, text="登录并读取存档", command=self._do_login)
        self.btn_login.grid(row=0, column=4, padx=8)

        self.lbl_status = ttk.Label(login_frame, text="未登录", foreground="gray")
        self.lbl_status.grid(row=0, column=5, padx=8)

        self.var_login_mode = tk.StringVar(value="password")
        mode_bar = ttk.Frame(login_frame)
        mode_bar.grid(row=1, column=0, columnspan=6, sticky="w", pady=(6, 0))
        ttk.Radiobutton(mode_bar, text="账号密码登录", variable=self.var_login_mode, value="password",
                        command=self._toggle_login_mode).pack(side="left", padx=4)
        ttk.Radiobutton(mode_bar, text="Cookie登录", variable=self.var_login_mode, value="cookie",
                        command=self._toggle_login_mode).pack(side="left", padx=8)
        self.cookie_login_frame = ttk.Frame(login_frame)
        self.cookie_login_frame.grid(row=2, column=0, columnspan=6, sticky="ew", pady=(6, 0))
        self.cookie_login_frame.columnconfigure(1, weight=1)
        ttk.Label(self.cookie_login_frame, text="Cookie：").grid(row=0, column=0, padx=3)
        self.entry_cookie = ttk.Entry(self.cookie_login_frame, width=80, show="*")
        self.entry_cookie.grid(row=0, column=1, sticky="ew", padx=3)
        ttk.Button(self.cookie_login_frame, text="粘贴Cookie", command=self._paste_login_cookie).grid(row=0, column=2, padx=4)
        ttk.Label(self.cookie_login_frame, text="浏览器登录4399后粘贴完整Cookie；仅点击“保存当前账号”时加密保存到本机账号目录。",
                  foreground="gray").grid(row=1, column=0, columnspan=3, sticky="w", pady=3)
        self.cookie_login_frame.grid_remove()
        self._build_account_profiles(login_frame)

        # 存档选择区
        save_frame = ttk.LabelFrame(self._ui_host, text="选择存档（所有功能共享）", padding=8)
        save_frame.pack(fill="x", padx=10, pady=5)

        self.save_var = tk.StringVar()
        self.combo_save = ttk.Combobox(save_frame, textvariable=self.save_var,
                                       state="readonly", width=50)
        self.combo_save.pack(side="left", padx=5)
        self.combo_save.bind("<<ComboboxSelected>>", self._on_save_select)

        self.lbl_save_info = ttk.Label(save_frame, text="登录后选择存档", foreground="gray")
        self.lbl_save_info.pack(side="left", padx=10)
        self.var_auto_daily_before_battle = tk.BooleanVar(value=False)
        self._auto_daily_before_battle = False
        self.var_auto_daily_before_battle.trace_add('write', lambda *_:
            setattr(self, '_auto_daily_before_battle', self.var_auto_daily_before_battle.get()))
        ttk.Checkbutton(save_frame, text='开打前接取匹配每日任务',
                        variable=self.var_auto_daily_before_battle).pack(side='left', padx=8)


        # 多排导航：主页单独一排，其余页面分两排。
        self.nav_frame = ttk.Frame(self._ui_host, padding=(10, 2))
        self.nav_frame.pack(fill="x")
        style = ttk.Style(self.root)
        style.layout("Toolbox.TNotebook.Tab", [])
        self.notebook = ttk.Notebook(self._ui_host, style="Toolbox.TNotebook")
        self.notebook.pack(fill="both", expand=True, padx=10, pady=5)

        self._build_quick_tab()
        self._build_weekly_dungeon_tab()
        self._build_moyuan_tab()
        self._build_limited_events_tab()
        from super_gift import build_tab as build_super_gift_tab
        build_super_gift_tab(self)
        self._build_daily_tab()
        self._build_daily2_tab()
        from wash_ui import build_tab as build_wash_tab
        build_wash_tab(self)
        self._build_daily_task_tab()
        self._build_mainfarm_tab()
        self._build_mainline_clear_tab()
        self._build_nightmare_tab()
        self._build_shenyu_jingyu_tab()
        # 加载制作书列表和装备属性范围
        self._craft_book_options = []
        self._craft_book_ids = {}
        self._craft_equip_attrs = {}
        try:
            import json as _json
            _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "craft_books.json")
            if os.path.exists(_bp):
                with open(_bp, 'r', encoding='utf-8') as _f:
                    _books = _json.load(_f)
                for _b in sorted(_books, key=lambda x: x['id']):
                    if str(_b.get('propType')) == '19':
                        _opt = "%s (%d)" % (_b['name'], _b['id'])
                        self._craft_book_options.append(_opt)
                        self._craft_book_ids[_opt] = _b['id']
        except Exception as _e:
            print("加载制作书列表失败:", _e)
        if not self._craft_book_options:
            self._craft_book_options = ["朱电寒髓杵 (119460002)"]
            self._craft_book_ids = {"朱电寒髓杵 (119460002)": 119460002}

        # 加载装备属性范围映射
        try:
            _ap = os.path.join(os.path.dirname(os.path.abspath(__file__)), "book_equip_attrs.json")
            if os.path.exists(_ap):
                with open(_ap, 'r', encoding='utf-8') as _f:
                    self._craft_equip_attrs = _json.load(_f)
        except Exception as _e:
            print("加载装备属性范围失败:", _e)

        self._build_craft_tab()
        self._build_hideboss_tab()
        from horse_capture_ui import build_capture_tab
        build_capture_tab(self)
        self._build_pet_equip_tab()
        self._build_mounts_tab()
        self._build_timeboat_tab()
        self._build_navigation()

        # 底部日志区（固定在窗口底部，不随页面滚动）
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=5)
        log_frame.pack(side="bottom", fill="x", expand=False, padx=10, pady=5,
                       before=viewport)

        self.text_log = scrolledtext.ScrolledText(log_frame, wrap="word", font=("Consolas", 9), height=6)
        self.text_log.pack(fill="both", expand=True)
        ttk.Label(log_frame, text="运行日志及掉落统计自动保存：" + str(audit_directory()),
                  foreground="gray", wraplength=900).pack(anchor="w")

        # 全局过滤开关（固定在日志上方，不随页面滚动）
        global_bar = ttk.Frame(self.root)
        global_bar.pack(side="bottom", fill="x", padx=10, before=viewport)
        ttk.Checkbutton(global_bar, text="全局过滤：不拾取桃子 / 萝卜 / 蓝瓶 / 蓝壶",
                        variable=self.var_skip_supply_pickups).pack(side="left")
        ttk.Label(global_bar, text="包括烤熟的桃子和萝卜；对所有副本和一键运行生效。固定领奖不属于可选择拾取。",
                  foreground="#666").pack(side="left", padx=8)

    def _resize_ui_viewport(self, event=None):
        canvas = self._ui_canvas
        width, height = max(1, canvas.winfo_width()), max(1, canvas.winfo_height())
        if hasattr(self, 'nav_buttons'):
            columns = min(13, max(4, (width - 20) // 100))
            if columns != getattr(self, '_nav_columns', None):
                self._nav_columns = columns
                for col in range(13):
                    self.nav_frame.columnconfigure(col, weight=1 if col < columns else 0, minsize=0, uniform='nav' if col < columns else '')
                for index, button in enumerate(self.nav_buttons):
                    row = 0 if index == 0 else 1 + (index - 1) // columns
                    col = 0 if index == 0 else (index - 1) % columns
                    button.grid_configure(row=row, column=col, columnspan=columns if index == 0 else 1)
        wanted_w = max(width, self._ui_host.winfo_reqwidth())
        wanted_h = max(height, self._ui_host.winfo_reqheight())
        canvas.itemconfigure(self._ui_window, width=wanted_w, height=wanted_h)
        canvas.configure(scrollregion=(0, 0, wanted_w, wanted_h))

    def _scroll_ui_viewport(self, event):
        try:
            widget = self.root.winfo_containing(event.x_root, event.y_root)
            if widget is None or widget.winfo_toplevel() is not self.root:
                return
            pointer = widget
            while pointer is not None and pointer is not self._ui_canvas:
                if pointer.winfo_class() in ('Text', 'Listbox', 'Treeview', 'TCombobox', 'TSpinbox', 'Canvas'):
                    return
                pointer = getattr(pointer, 'master', None)
            if pointer is None:
                return
            delta = -int(event.delta / 120) if abs(event.delta) >= 120 else (-1 if event.delta > 0 else 1)
            if event.state & 1:
                self._ui_canvas.xview_scroll(delta, 'units')
            else:
                self._ui_canvas.yview_scroll(delta, 'units')
            return 'break'
        except tk.TclError:
            return

    def _build_navigation(self):
        self.nav_buttons = []
        tabs = self.notebook.tabs()
        for col in range(13):
            self.nav_frame.columnconfigure(col, weight=1, uniform="nav")
        for index, tab_id in enumerate(tabs):
            title = self.notebook.tab(tab_id, "text")
            row = 0 if index == 0 else 1 + (index - 1) // 13
            col = 0 if index == 0 else (index - 1) % 13
            button = tk.Button(self.nav_frame, text=title, font=("微软雅黑", 9),
                               height=1 if index == 0 else 2,
                               wraplength=80,
                               command=lambda i=index: self.notebook.select(i))
            button.grid(row=row, column=col, columnspan=13 if index == 0 else 1,
                        sticky="ew", padx=2, pady=2)
            self.nav_buttons.append(button)
        self.notebook.bind("<<NotebookTabChanged>>", self._sync_navigation)
        self.notebook.select(0)
        self._sync_navigation()

    def _sync_navigation(self, event=None):
        selected = self.notebook.index(self.notebook.select())
        for index, button in enumerate(self.nav_buttons):
            button.config(relief="sunken" if index == selected else "raised",
                          bg="#dcecff" if index == selected else "#f3f3f3")

    # ========== 首页配置 ==========
    QUICK_CONFIG_FILE = os.path.join(BASE_DIR, "zm4_toolbox_config.json")
    QUICK_TASKS = (
        ("daily", "日常助手", "_do_daily", "btn_daily_run"),
        ("treasure", "造梦寻宝", "_treasure_run", "btn_treasure_run"),
        ("dice", "4399冒险投一次", "_dice_roll", "btn_dice_roll"),
        ("mainfarm", "主线刷取", "_do_mainfarm", "btn_mainfarm_run"),
        ("mainline", "主线通关", "_do_mainline_clear", "btn_mainline_run"),
        ("nightmare", "噩梦副本", "_do_nightmare", "btn_nightmare_run"),
        ("shenyu", "神域/镜域", "_do_shenyu_jingyu", "btn_sj_run"),
        ("hideboss", "隐藏BOSS", "_do_hideboss", "btn_hide_run"),
        ("taigu", "太古秘境", "_do_taigu_run", "btn_taigu_run"),
        ("pet", "宠物装备", "_do_pet_equip", "btn_pet_run"),
        ("beiming", "悲鸣冰川", "_do_beiming_run", "btn_beiming_run"),
        ("mount", "坐骑副本", "_do_mount_run", "btn_mount_run"),
        ("luoxuan", "螺旋地狱", "_do_luoxuan_run", "btn_luoxuan_run"),
        ("luohan", "罗汉堂", "_do_luohan_run", "btn_luohan_run"),
        ("special", "地藏/虚空藏", "_do_special_run", "btn_special_run"),
        ("online_dice", "挂机领骰子", "_dice_start", "btn_dice_start"),
    )
    QUICK_PREPARE = {
        "pet": ("_do_pet_check", "btn_pet_check"),
        "beiming": ("_do_beiming_check", "btn_beiming_check"),
        "mount": ("_do_mount_check", "btn_mount_check"),
        "luoxuan": ("_do_luoxuan_check", "btn_luoxuan_check"),
        "luohan": ("_do_luohan_check", "btn_luohan_check"),
        "special": ("_do_special_check", "btn_special_check"),
    }

    def _build_quick_tab(self):
        page = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(page, text="一键运行")
        ttk.Label(page, text="「我的日常」为独立窗口，点击下方按钮打开。",
                  font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Button(page, text="打开「我的日常」窗口",
                   command=self._open_my_daily_window).pack(anchor="w")
        ttk.Label(page, text="窗口关闭不会退出工具箱；再次点击本页按钮即可重新打开。",
                  foreground="#666").pack(anchor="w", pady=(10, 0))
        self.quick_window = tk.Toplevel(self.root)
        self.quick_window.withdraw()
        self.quick_window.title("一键运行 - 造梦西游4 活动工具箱")
        self.quick_window.minsize(720, 480)
        self.quick_window.geometry("900x560")
        self.quick_window.protocol("WM_DELETE_WINDOW", self.quick_window.withdraw)
        tab = ttk.Frame(self.quick_window, padding=12)
        tab.pack(fill="both", expand=True)
        ttk.Label(tab, text="保存各页面设置，勾选要依次运行的项目。",
                  font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(0, 10))
        self._skip_supply_pickups = False
        self.var_skip_supply_pickups = tk.BooleanVar(value=False)
        self.var_skip_supply_pickups.trace_add("write", self._update_global_pickup_filter)
        panel = ttk.LabelFrame(tab, text="运行清单", padding=10)
        panel.pack(fill="x")
        self.quick_task_vars = {}
        for index, (key, label, _, _) in enumerate(self.QUICK_TASKS):
            var = tk.BooleanVar(value=False)
            self.quick_task_vars[key] = var
            ttk.Checkbutton(panel, text=label, variable=var).grid(
                row=index // 4, column=index % 4, sticky="w", padx=14, pady=5)
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=12)
        ttk.Button(actions, text="保存当前配置", command=self._quick_save).pack(side="left", padx=4)
        self.btn_quick_run = ttk.Button(actions, text="一键运行已勾选", command=self._quick_run, state="disabled")
        self.btn_quick_run.pack(side="left", padx=4)
        self.btn_quick_stop = ttk.Button(actions, text="停止后续项目", command=self._quick_stop, state="disabled")
        self.btn_quick_stop.pack(side="left", padx=4)
        self.lbl_quick_status = ttk.Label(tab, text="登录后可运行", foreground="gray")
        self.lbl_quick_status.pack(anchor="w", pady=5)
        ttk.Label(tab, text="账号和密码不会保存。执行中的项目先完成；需要确认的操作仍会弹出确认框。",
                  foreground="#666").pack(anchor="w")

    def _update_global_pickup_filter(self, *_):
        self._skip_supply_pickups = bool(self.var_skip_supply_pickups.get())

    @staticmethod
    def _quick_walk_vars(value, path=(), depth=0):
        if isinstance(value, tk.Variable):
            yield list(path), value
        elif depth < 4 and isinstance(value, dict):
            for key, child in value.items():
                yield from ToolBoxApp._quick_walk_vars(child, path + (str(key),), depth + 1)
        elif depth < 4 and isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                yield from ToolBoxApp._quick_walk_vars(child, path + (str(index),), depth + 1)

    def _quick_save(self):
        variables = []
        for name, value in self.__dict__.items():
            if name in ("save_var", "quick_task_vars"):
                continue
            for path, variable in self._quick_walk_vars(value, (name,)):
                try:
                    variables.append({"path": path, "value": variable.get()})
                except tk.TclError:
                    pass
        entries = {}
        for name in ("entry_peach3", "entry_peach9", "entry_yutu_score"):
            widget = getattr(self, name, None)
            if widget is not None:
                entries[name] = widget.get()
        data = {"version": 2,
                "save_index": self.current_save["index"] if self.current_save else getattr(self, "_quick_saved_save", None),
                "tasks": {key: var.get() for key, var in self.quick_task_vars.items()},
                "variables": variables, "entries": entries}
        try:
            with open(self.QUICK_CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            self.lbl_quick_status.config(text="配置已保存，下次启动自动恢复", foreground="green")
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc))

    def _open_quick_window(self):
        window = getattr(self, "quick_window", None)
        if window is None or not window.winfo_exists():
            return
        window.deiconify()
        window.lift()
        window.focus_force()

    MY_DAILY_FAVORITES = os.path.join(BASE_DIR, "my_daily_favorites.json")

    def _schedule_file(self):
        return schedule_path(self.MY_DAILY_FAVORITES)

    def _open_my_daily_window(self):
        window = getattr(self, "my_daily_window", None)
        if window is None:
            window = MyDailyWindow(self, self.QUICK_TASKS, self.MY_DAILY_FAVORITES)
            self.my_daily_window = window
        window.open()

    def _schedule_check(self):
        """工具箱内定时器：每天到点自动登录并执行收藏勾选项目。"""
        data = load_schedule(self._schedule_file())
        today = datetime.now().strftime("%Y-%m-%d")
        if data["enabled"] and data["last_date"] != today and datetime.now().strftime("%H:%M") >= data["time"]:
            data["last_date"] = today
            try:
                save_schedule(self._schedule_file(), data)
            except OSError as exc:
                self._log("[我的日常] 定时状态写入失败：%s" % exc)
            self._log("[我的日常] 定时触发：每天 %s" % data["time"])
            self._open_my_daily_window()
            self.my_daily_window.auto_run(quit_after=False)
        self.root.after(30_000, self._schedule_check)

    def _start_scheduled_task_run(self):
        """Windows 计划任务入口：启动后自动登录并执行一次，结束后退出。"""
        data = load_schedule(self._schedule_file())
        data["last_date"] = datetime.now().strftime("%Y-%m-%d")
        try:
            save_schedule(self._schedule_file(), data)
        except OSError:
            pass
        self._open_my_daily_window()
        self.my_daily_window.auto_run(quit_after=True)

    def _schedule_abort(self, message):
        self._log(message)
        if getattr(self, "_schedule_quit_on_fail", False):
            self._schedule_quit_on_fail = False
            self.root.after(1500, self._close_toolbox)

    def _schedule_ensure_login(self, callback):
        if self.client and self.current_save is not None and not self.current_save.get("unavailable"):
            self.root.after(0, callback)
            return
        username = getattr(self, "_loaded_account_name", "") or load_schedule(self._schedule_file())["account"]
        if not username:
            self._schedule_abort("[我的日常] 自动登录跳过：没有保存过账号")
            return
        cookie = self._saved_cookie_for(username)
        if not cookie:
            self._schedule_abort("[我的日常] 自动登录跳过：账号%s没有保存Cookie" % username)
            return
        self._schedule_login_callbacks = getattr(self, "_schedule_login_callbacks", [])
        self._schedule_login_callbacks.append(callback)
        self._log("[我的日常] 自动登录账号%s" % username)
        self.lbl_status.config(text="定时登录中...", foreground="orange")

        def worker():
            try:
                client = ZM4Client.from_cookie_string(cookie, record_index=0)
                saves = self._list_saves(client)
                self.root.after(0, lambda: self._on_login_success(client, saves))
            except Exception as error:
                message = str(error)
                self.root.after(0, lambda text=message: self._schedule_login_failed(text))

        threading.Thread(target=worker, daemon=True).start()

    def _schedule_login_failed(self, error):
        self._schedule_login_callbacks = []
        self.lbl_status.config(text="登录失败", foreground="red")
        self._schedule_abort("[我的日常] 自动登录失败：%s" % error)

    def _close_toolbox(self):
        self._dice_stop_event.set()
        self._forest_stop_event.set()
        self._jiuzhuan_stop.set()
        self._quick_save()
        flush_audit()          # 关窗前把日志/统计队列写完
        self.root.destroy()

    def _quick_restore(self):
        try:
            with open(self.QUICK_CONFIG_FILE, "r", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return
        self._quick_saved_save = data.get("save_index")
        for key, selected in (data.get("tasks") or {}).items():
            if key in self.quick_task_vars:
                self.quick_task_vars[key].set(bool(selected))
        for row in data.get("variables") or []:
            if row.get("path") == ["var_xingtian_difficulty"]:
                row["value"] = {"第1档（2050，锁定属性）": "普通",
                                "第2档（2051，锁定属性）": "噩梦",
                                "最高档（2081，不锁属性）": "地狱"}.get(row.get("value"), row.get("value"))
        for row in data.get("variables") or []:
            if row.get("path") == ["var_craft_book"]:
                self.var_craft_book.set(row.get("value"))
                self._on_craft_book_select()
                break
        combo_choices = {}
        def collect_choices(widget):
            for child in widget.winfo_children():
                if isinstance(child, ttk.Combobox) and str(child.cget("state")) == "readonly":
                    combo_choices[str(child.cget("textvariable"))] = tuple(child.cget("values"))
                collect_choices(child)
        collect_choices(self.root)
        legacy_before_battle = int(data.get("version") or 1) < 2
        for row in data.get("variables") or []:
            path = row.get("path") or []
            if not path or path[0] in ("save_var", "quick_task_vars"):
                continue
            if legacy_before_battle and path == ["var_auto_daily_before_battle"]:
                continue          # 旧版本默认勾选的战前接任务，升级后一律回到未勾选
            obj = getattr(self, path[0], None)
            for part in path[1:]:
                if isinstance(obj, dict):
                    obj = next((v for k, v in obj.items() if str(k) == part), None)
                elif isinstance(obj, (list, tuple)) and part.isdigit() and int(part) < len(obj):
                    obj = obj[int(part)]
                else:
                    obj = None
                    break
            if isinstance(obj, tk.Variable):
                choices = combo_choices.get(str(obj))
                if choices and str(row.get("value")) not in choices:
                    continue          # 旧版本保存的选项文案已被弃用，丢弃该值，保留当前默认项
                try:
                    obj.set(row.get("value"))
                except tk.TclError:
                    pass
        for name, value in (data.get("entries") or {}).items():
            if name in ("entry_peach3", "entry_peach9", "entry_yutu_score"):
                widget = getattr(self, name, None)
                if widget is not None:
                    widget.delete(0, "end")
                    widget.insert(0, str(value))
        self.lbl_quick_status.config(text="已恢复上次配置，登录后可运行", foreground="green")

    def _quick_run(self):
        queue = [spec for spec in self.QUICK_TASKS if self.quick_task_vars[spec[0]].get()]
        if self._start_quick_queue(queue, "一键运行"):
            self._quick_save()

    def _start_quick_queue(self, queue, source="一键运行"):
        """按给定任务依次执行；一键运行与我的日常共用。"""
        if not self._ensure_login():
            return False
        if self.btn_quick_stop.instate(["!disabled"]):
            messagebox.showinfo(source, "已有任务在运行，请等当前项目结束。")
            return False
        if not queue:
            messagebox.showinfo(source, "请先勾选要运行的项目")
            return False
        self._quick_queue = list(queue)
        self._quick_source = source
        self._quick_stopping = False
        self.btn_quick_run.config(state="disabled")
        self.btn_quick_stop.config(state="normal")
        self._log("%s 已选 %d 项，依次执行" % (self._quick_tag(), len(self._quick_queue)))
        self.root.after(0, self._quick_next)
        return True

    def _quick_tag(self):
        return "[%s]" % getattr(self, "_quick_source", "一键运行")

    def _quick_stop(self):
        self._quick_stopping = True
        self.lbl_quick_status.config(text="当前项目结束后停止", foreground="orange")

    def _quick_next(self):
        if self._quick_stopping or not self._quick_queue:
            stopped = self._quick_stopping
            self._log(self._quick_tag() + (" 已停止后续项目" if stopped else " 全部结束"))
            self.lbl_quick_status.config(text="已停止" if stopped else "全部结束", foreground="green")
            self.btn_quick_run.config(state="normal")
            self.btn_quick_stop.config(state="disabled")
            if getattr(self, "_quick_quit_after", False):
                self._quick_quit_after = False
                self.root.after(1500, self._close_toolbox)
            return
        item = self._quick_queue.pop(0)
        if isinstance(item, tuple):
            key, label, method_name, button_name = item
            run = getattr(self, method_name)
            button = getattr(self, button_name, None)
            prepare = self.QUICK_PREPARE.get(key)
        else:
            key, label, run, button = item.key, item.label, item.run, item.button
            prepare = None
        if button is not None and button.instate(["disabled"]) and prepare:
            prepare_method, _ = prepare
            self._log(self._quick_tag() + (" %s：先检测剩余次数" % label))
            getattr(self, prepare_method)()
            self.root.after(300, lambda: self._quick_after_prepare(label, run, button, 0))
            return
        if button is None or button.instate(["disabled"]):
            self._log(self._quick_tag() + (" 跳过 %s：当前不可运行" % label))
            self.root.after(0, self._quick_next)
            return
        self.lbl_quick_status.config(text="正在执行：%s" % label, foreground="orange")
        self._log(self._quick_tag() + (" 开始：%s" % label))
        try:
            run()
        except Exception as exc:
            self._log(self._quick_tag() + (" %s 启动失败：%s" % (label, exc)))
            self.root.after(0, self._quick_next)
            return
        # 收藏自其他页面的按钮最多等待 10 分钟，避免按钮一直禁用时卡住队列。
        remain = None if isinstance(item, tuple) else 600000
        self.root.after(200, lambda: self._quick_wait(label, button, remain))

    def _quick_after_prepare(self, label, run, button, waited_ms):
        if self._quick_stopping:
            self.root.after(0, self._quick_next)
            return
        if not button.instate(["disabled"]):
            self.lbl_quick_status.config(text="正在执行：%s" % label, foreground="orange")
            self._log(self._quick_tag() + (" 开始：%s" % label))
            try:
                run()
            except Exception as exc:
                self._log(self._quick_tag() + (" %s 启动失败：%s" % (label, exc)))
                self.root.after(0, self._quick_next)
                return
            self.root.after(200, lambda: self._quick_wait(label, button))
        elif waited_ms >= 60000:
            self._log(self._quick_tag() + (" 跳过 %s：检测超时或不可运行" % label))
            self.root.after(0, self._quick_next)
        else:
            self.root.after(350, lambda: self._quick_after_prepare(label, run, button, waited_ms + 350))

    def _quick_wait(self, label, button, remain=None):
        if button.instate(["disabled"]):
            if remain is None:
                self.root.after(350, lambda: self._quick_wait(label, button))
            elif remain > 0:
                self.root.after(350, lambda: self._quick_wait(label, button, remain - 350))
            else:
                self._log(self._quick_tag() + (" %s：等待超时，继续下一项" % label))
                self.root.after(0, self._quick_next)
        else:
            self._log(self._quick_tag() + (" 结束：%s" % label))
            self.root.after(0, self._quick_next)

    # ========== 主题挑战轮换 ===========
    def _build_theme_challenge_tab(self):
        tab = self._daily2_page("主题挑战", padding=12)

        header = ttk.Frame(tab)
        header.pack(fill="x", pady=(0, 8))
        self.lbl_theme_title = ttk.Label(header, text="读取本周轮换...",
                                         font=("微软雅黑", 14, "bold"), foreground="#8a4b08")
        self.lbl_theme_title.pack(side="left", anchor="w")
        ttk.Button(header, text="刷新时间", command=self._refresh_theme_challenge_display).pack(side="right")

        self.lbl_theme_period = ttk.Label(tab, text="", font=("微软雅黑", 10))
        self.lbl_theme_period.pack(anchor="w", pady=(0, 10))

        list_frame = ttk.LabelFrame(tab, text="本周开放关卡", padding=8)
        list_frame.pack(fill="x", pady=5)
        self.theme_challenge_tree = ttk.Treeview(
            list_frame, columns=("level", "name", "dungeon_id"), show="headings", height=4
        )
        self.theme_challenge_tree.heading("level", text="星级")
        self.theme_challenge_tree.heading("name", text="主题")
        self.theme_challenge_tree.heading("dungeon_id", text="关卡 ID")
        self.theme_challenge_tree.column("level", width=100, anchor="center")
        self.theme_challenge_tree.column("name", width=260, anchor="center")
        self.theme_challenge_tree.column("dungeon_id", width=120, anchor="center")
        self.theme_challenge_tree.tag_configure("four_star", foreground="#9a5310")
        self.theme_challenge_tree.pack(fill="x")
        theme_actions = ttk.Frame(tab)
        theme_actions.pack(anchor="w", pady=8)
        ttk.Label(theme_actions, text="执行次数：").pack(side="left")
        self.var_theme_times = tk.StringVar(value="3")
        self.theme_times_choice = ttk.Combobox(theme_actions, textvariable=self.var_theme_times,
                                              values=("1", "2", "3"), state="readonly", width=5)
        self.theme_times_choice.pack(side="left", padx=6)
        self.btn_theme_run = ttk.Button(theme_actions, text="执行选中关卡", command=self._do_theme_challenge)
        self.btn_theme_run.pack(side="left", padx=6)
        self.lbl_theme_result = ttk.Label(tab, text="选择本周关卡后可单独执行。", wraplength=820)
        self.lbl_theme_result.pack(anchor="w")

        self.lbl_theme_updated = ttk.Label(tab, text="", foreground="gray")
        self.lbl_theme_updated.pack(anchor="w", pady=(8, 0))
        ttk.Label(
            tab,
            text="每周五轮换；执行前核对服务器当前主题。可选执行1～3次，默认3次；每次核对免费次数并重登核对背包，不购买次数。",
            foreground="gray", wraplength=820, justify="left"
        ).pack(anchor="w", pady=(6, 0))

        self._refresh_theme_challenge_display()
        self._schedule_theme_rotation_refresh()
        return tab

    def _refresh_theme_challenge_display(self):
        now = datetime.now()
        period = get_theme_rotation_period(now)
        for item in self.theme_challenge_tree.get_children():
            self.theme_challenge_tree.delete(item)

        if period is None:
            self.lbl_theme_title.config(text="主题挑战尚未开放")
            self.lbl_theme_period.config(text="轮换起始日：%s" % THEME_ROTATION_START.strftime("%Y-%m-%d"))
        else:
            group_id, period_start, period_end = period
            self.lbl_theme_title.config(text="当前第 %d 组主题挑战" % group_id)
            next_update = period_start + timedelta(days=7)
            self.lbl_theme_period.config(
                text="轮换周期：%s（周五）至 %s（周四）  |  下次更新：%s（周五）" % (
                    period_start.strftime("%Y-%m-%d"),
                    period_end.strftime("%Y-%m-%d"),
                    next_update.strftime("%Y-%m-%d"),
                )
            )
            for level, dungeon_id, name in sorted(THEME_CHALLENGE_GROUPS[group_id]):
                tags = ("four_star",) if level == 4 else ()
                self.theme_challenge_tree.insert(
                    "", "end", values=("%d 星" % level, name, dungeon_id), tags=tags
                )

        self.lbl_theme_updated.config(text="计算时间：%s（本机时间）" % now.strftime("%Y-%m-%d %H:%M:%S"))

    def _do_theme_challenge(self):
        if not self._ensure_login():
            return
        selected = self.theme_challenge_tree.selection()
        if not selected:
            messagebox.showinfo("主题挑战", "请先选择列表中的一至四星关卡。")
            return
        mid = int(self.theme_challenge_tree.item(selected[0], "values")[2])
        try:
            times = int(self.var_theme_times.get())
            if times not in (1, 2, 3):
                raise ValueError
        except ValueError:
            messagebox.showwarning("主题挑战", "执行次数请选择1～3次。")
            return
        slot = self.current_save["index"]
        self.btn_theme_run.config(state="disabled")
        self.theme_times_choice.config(state="disabled")
        self.lbl_theme_result.config(text="正在连接并读取服务器当前主题…")

        def worker():
            flow = verify = None
            text = ""
            completed = 0
            try:
                from mainfarm_routes import clear_stage, dungeon_rows
                for attempt in range(times):
                    flow, _, before = self._connect_and_enter(slot)
                    listed = flow.request("scene.copyHandler.getDungeonThemeList", {}, timeout=15)
                    if listed.get("code") != 200 or listed.get("error"):
                        raise RuntimeError(listed.get("error", "读取当前主题失败"))
                    group = int(listed["id"])
                    available = {row[1] for row in THEME_CHALLENGE_GROUPS.get(group, [])}
                    if mid not in available:
                        raise RuntimeError("所选关卡与服务器当前主题不符，请刷新轮换列表")
                    all_ids = {row[1] for rows in THEME_CHALLENGE_GROUPS.values() for row in rows}
                    history = before.get("curRecord", {}).get("copyHistory")
                    if not isinstance(history, list):
                        raise RuntimeError("未读到挑战次数，已停止")
                    used = sum(int(row.get("num", 0)) for row in history
                               if int(row.get("id", 0)) in all_ids)
                    maximum = int(dungeon_rows()[mid]["dailyCountMax"])
                    if used >= maximum:
                        text = "已完成%d/%d次；今日免费次数已用完，已停止。" % (completed, times)
                        self._log("[主题挑战] " + text)
                        break
                    def inventory(scene):
                        result = {}
                        for bag_name in ("itemsBag", "equipsBag"):
                            bag = scene["curRecord"].get(bag_name) or {}
                            rows = bag.get("items") or []
                            for item in (rows.values() if isinstance(rows, dict) else rows):
                                key = str(item["id"])
                                result[key] = result.get(key, 0) + int(item.get("count", 1))
                        return result
                    initial = inventory(before)
                    self._log("[主题挑战] 槽%s，关卡%s，剩余免费次数%s，costGem=0" %
                              (slot, mid, maximum-used))
                    result = clear_stage(flow, before, mid, pick_equips=True)
                    self._log("[主题挑战] 结算回包：%s" % result["settled"])
                    flow.disconnect()
                    flow = None
                    verify, _, after = self._connect_and_enter(slot)
                    final = inventory(after)
                    changes = {key: final.get(key, 0)-initial.get(key, 0)
                               for key in final.keys() | initial.keys()
                               if final.get(key, 0) != initial.get(key, 0)}
                    self._log("[主题挑战] 重登背包变化：%s" % changes)
                    if any(before["user"].get(key) != after["user"].get(key)
                           for key in ("gem", "usedGem")):
                        raise RuntimeError("点券或累计消费发生变化，请核查")
                    completed += 1
                    text = "已完成%d/%d次，已重登记录背包变化；点券未变。" % (completed, times)
                    verify.disconnect()
                    verify = None
                    self._log("[主题挑战] " + text)
            except Exception as error:
                text = "已完成%d/%d次；已停止：%s" % (completed, times, error)
                self._log("[主题挑战] " + text)
            finally:
                for connection in (flow, verify):
                    if connection:
                        connection.disconnect()
                def finish():
                    self.btn_theme_run.config(state="normal")
                    self.theme_times_choice.config(state="readonly")
                    self.lbl_theme_result.config(text=text)
                self.root.after(0, finish)
        threading.Thread(target=worker, daemon=True).start()

    def _schedule_theme_rotation_refresh(self):
        now = datetime.now()
        days_until_friday = (4 - now.weekday()) % 7
        next_friday = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=days_until_friday)
        if next_friday <= now:
            next_friday += timedelta(days=7)
        delay_ms = max(1000, int((next_friday - now).total_seconds() * 1000))
        self._theme_rotation_after_id = self.root.after(delay_ms, self._on_theme_rotation_boundary)

    def _on_theme_rotation_boundary(self):
        self._refresh_theme_challenge_display()
        self._schedule_theme_rotation_refresh()

    # ========== 生存大冒险标签页 ==========
    def _build_survival_tab(self):
        tab = self._daily2_page("生存大冒险", padding=10)

        # 角色信息
        role_frame = ttk.LabelFrame(tab, text="今日角色", padding=8)
        role_frame.pack(fill="x", pady=5)

        self.lbl_survival_role = ttk.Label(role_frame, text="等待加载...", font=("微软雅黑", 11, "bold"))
        self.lbl_survival_role.pack(anchor="w")
        self.lbl_survival_attrs = ttk.Label(role_frame, text="", foreground="#333")
        self.lbl_survival_attrs.pack(anchor="w", pady=3)

        # 按钮区
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill="x", pady=5)

        self.btn_load_survival = ttk.Button(btn_frame, text="加载今日题目",
                                            command=self._load_survival, state="disabled")
        self.btn_load_survival.pack(side="left", padx=3)

        self.btn_auto_answer = ttk.Button(btn_frame, text="一键自动答题(免费)",
                                          command=self._auto_answer, state="disabled")
        self.btn_auto_answer.pack(side="left", padx=3)

        ttk.Label(btn_frame, text="⚠ 免费答题，不消耗点券", foreground="green").pack(side="left", padx=10)

        # 结果区
        result_frame = ttk.LabelFrame(tab, text="最优答题序列", padding=5)
        result_frame.pack(fill="both", expand=True, pady=5)

        self.text_survival = scrolledtext.ScrolledText(result_frame, wrap="word", font=("Consolas", 9))
        self.text_survival.pack(fill="both", expand=True)

    # ========== 仙境危机标签页 ==========
    def _daily2_page(self, title, padding=10):
        return self._scroll_notebook_page(self.daily2_notebook, title, padding)

    def _limited_page(self, title, padding=10):
        return self._scroll_notebook_page(self.limited_event_notebook, title, padding)

    def _scroll_notebook_page(self, notebook, title, padding=10):
        outer = ttk.Frame(notebook)
        notebook.add(outer, text=title)
        outer.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        vertical = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        content = ttk.Frame(canvas, padding=padding)
        window = canvas.create_window((0, 0), window=content, anchor="nw")

        def resize(event=None):
            width = max(canvas.winfo_width(), content.winfo_reqwidth())
            height = max(canvas.winfo_height(), content.winfo_reqheight())
            canvas.itemconfigure(window, width=width, height=height)
            canvas.configure(scrollregion=(0, 0, width, height))

        def wheel(event):
            widget = event.widget
            # 列表及文本框继续使用自身滚动行为。
            if isinstance(widget, (ttk.Treeview, tk.Listbox, tk.Text)):
                return
            while widget is not None and widget != outer:
                widget = getattr(widget, "master", None)
            if widget != outer or not event.delta:
                return
            if canvas.yview() == (0.0, 1.0):
                return
            canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
            return "break"

        content.bind("<Configure>", resize)
        canvas.bind("<Configure>", resize)
        self.root.bind("<MouseWheel>", wheel, add="+")
        return content

    def _build_daily2_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="日常助手2")
        self.daily2_notebook = ttk.Notebook(tab)
        self.daily2_notebook.pack(fill="both", expand=True)
        self._build_survival_tab()
        self._build_treasure_tab()
        self._build_theme_challenge_tab()
        self._build_dice_online_tab()
        self._build_luoxuan_tab()
        self._build_luohan_tab()
        self._build_special_dungeon_tab()
        self._build_taigu_tab()
        wanted_tab = ttk.Frame(self.daily2_notebook, padding=10)
        self.daily2_notebook.add(wanted_tab, text="悬赏任务")
        self._build_wanted_panel(wanted_tab)

    def _build_limited_events_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="限时活动")
        navigation = ttk.Frame(tab)
        navigation.pack(fill="x", pady=(0, 6))
        ttk.Label(navigation, text="选择活动：").pack(side="left")
        selector = ttk.Combobox(navigation, state="readonly", width=32)
        selector.pack(side="left", padx=6)
        self.limited_event_notebook = ttk.Notebook(tab)
        self.limited_event_notebook.pack(fill="both", expand=True)
        self._build_halloween_tab()
        self._build_jiuzhuan_tab()
        self._build_nian_tab()
        self._build_pingyi_tab()
        self._build_horse_collect_tab()
        from moyuan_weekly import build_panel as build_moyuan_panel
        build_moyuan_panel(self, self._limited_page("魔渊诛邪（前八层）"))
        pages = list(self.limited_event_notebook.tabs())
        # 已下线活动仍构建控件（保持按钮属性存在），但页面固定隐藏、不进入活动下拉框
        self._build_million_soul_tab()
        self._build_pet_collect_tab()
        for page in self.limited_event_notebook.tabs():
            if page not in pages:
                self.limited_event_notebook.hide(page)
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "output_cg1_20260921_1_2", "002___Activity.xml.json")
        with open(config_path, encoding="utf-8") as file:
            activities = {int(row['id']): row for row in json.load(file)['RECORD']}
        self._limited_page_deadlines = {"万圣节": datetime(2026, 11, 15, 23, 59, 59), "九转炼丹": datetime(2026, 11, 11, 23, 59, 59)}
        self._limited_page_deadlines["挑战屏翳"] = datetime(2026, 11, 1, 23, 59, 59)
        with open(os.path.join(os.path.dirname(config_path), '136___PetCollect.xml.json'), encoding='utf-8') as file:
            collect_rows = {str(row['id']): row for row in json.load(file)['RECORD']}
            pet_collect = collect_rows['1']
        for title, ids in {"宠物加速养成": (int(pet_collect['activeId']),),
                           "骑装加速养成": (int(collect_rows['2']['activeId']),),
                           "重阳签到": (904,), "挑战年兽": (262, 263, 869),
                           "挑战刑天": (101, 106, 599),
                           "仙境危机": (1179,), "玉兔逐月": (1439,),
                           "月宫厨房": (1440,), "国庆签到·千万灵魂": (1430,),
                           "活动副本（往期）": (674, 675, 1180, 1181)}.items():
            ends = [datetime.strptime(activities[i]['underTime'], '%Y/%m/%d-%H:%M:%S')
                    for i in ids if i in activities]
            if ends: self._limited_page_deadlines[title] = max(ends)
        show_expired = tk.BooleanVar(value=False)
        visible = []
        def update_pages():
            from datetime import timezone
            now = datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
            visible.clear()
            for page in pages:
                title = self.limited_event_notebook.tab(page, 'text').removesuffix('（已过期）')
                deadline = self._limited_page_deadlines.get(title)
                expired = deadline is not None and now > deadline
                self.limited_event_notebook.tab(page, text=title + ('（已过期）' if expired else ''))
                if expired and not show_expired.get():
                    self.limited_event_notebook.hide(page)
                else:
                    self.limited_event_notebook.add(page)
                    visible.append(page)
            # 过期页面只在勾选后显示，并排在末尾。
            visible.sort(key=lambda page: self.limited_event_notebook.tab(page, 'text').endswith('（已过期）'))
            for index, page in enumerate(visible): self.limited_event_notebook.insert(index, page)
            selector.config(values=[self.limited_event_notebook.tab(page, 'text') for page in visible])
            current = self.limited_event_notebook.select()
            if current not in visible and visible:
                self.limited_event_notebook.select(visible[0])
            if visible: selector.current(visible.index(self.limited_event_notebook.select()))
        ttk.Checkbutton(navigation, text="显示已过期活动", variable=show_expired,
                        command=update_pages).pack(side="left", padx=8)
        ttk.Label(tab, text="活动时间使用2026年10月12日官方配置，按北京时间判断；过期活动默认隐藏。",
                  foreground='gray', wraplength=900).pack(side='bottom', anchor='w', pady=4)
        selector.bind("<<ComboboxSelected>>", lambda event: self.limited_event_notebook.select(visible[selector.current()]))
        def sync_selector(event):
            current = self.limited_event_notebook.select()
            if current in visible: selector.current(visible.index(current))
        self.limited_event_notebook.bind("<<NotebookTabChanged>>", sync_selector)
        update_pages()

    def _limited_config_expired(self, title):
        from datetime import timezone
        deadline = getattr(self, '_limited_page_deadlines', {}).get(title)
        return deadline is not None and datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None) > deadline

    def _build_xianjing_tab(self):
        tab = self._limited_page("仙境危机", padding=10)

        # 操作区
        action_frame = ttk.LabelFrame(tab, text="摘桃子设置", padding=10)
        action_frame.pack(fill="x", pady=5)

        ttk.Label(action_frame, text="三千年蟠桃:").grid(row=0, column=0, padx=3)
        self.entry_peach3 = ttk.Entry(action_frame, width=5)
        self.entry_peach3.insert(0, "20")
        self.entry_peach3.grid(row=0, column=1, padx=3)

        ttk.Label(action_frame, text="九千年蟠桃:").grid(row=0, column=2, padx=3)
        self.entry_peach9 = ttk.Entry(action_frame, width=5)
        self.entry_peach9.insert(0, "1")
        self.entry_peach9.grid(row=0, column=3, padx=3)

        self.btn_pick = ttk.Button(action_frame, text="一键摘桃子", command=self._do_pick, state="disabled")
        self.btn_pick.grid(row=0, column=5, padx=8)

        ttk.Label(action_frame, text="⚠ 每天1次 | 上限49+1 | 超上限有风险", foreground="orange").grid(row=0, column=6, padx=8)

        # 说明
        info_frame = ttk.LabelFrame(tab, text="说明", padding=8)
        info_frame.pack(fill="x", pady=5)
        ttk.Label(info_frame, text="• 横版关卡 id=2138\n• 创建副本→触发蟠桃篮模式→完成副本→结算领取\n• 九千年蟠桃通过完整参数useItem1解锁，不消耗实际道具",
                  justify="left").pack(anchor="w")

    # ========== 限时活动副本 ==========
    def _build_event_dungeon_tab(self):
        tab = self._limited_page("活动副本（往期）", padding=12)
        ttk.Label(tab, text="挑战萌哥默认用完当天剩余免费次数（最多3次）；王母试炼执行1次。普通与困难共享次数。",
                  foreground="blue").pack(anchor="w", pady=(0, 8))
        ttk.Label(tab, text="挑战萌哥拾取副本掉落；王母试炼还需发送专用领奖请求。均固定 costGem=0。",
                  foreground="gray").pack(anchor="w", pady=(0, 10))
        self.event_dungeon_specs = {
            "挑战萌哥": {"mids": (2083, 2084), "shared": (2083, 2084),
                         "activities": (674, 675), "max": 3, "reward_route": False},
            "王母试炼": {"mids": (2140, 2141), "shared": (2140, 2141, 2174, 2175),
                         "activities": (1180, 1181), "max": 1, "reward_route": True},
        }
        self.event_dungeon_rows = {}
        for name, spec in self.event_dungeon_specs.items():
            frame = ttk.LabelFrame(tab, text=name, padding=10)
            frame.pack(fill="x", pady=5)
            is_wangmu = spec["reward_route"]
            ttk.Label(frame, text="属性模式：" if is_wangmu else "难度：").pack(side="left")
            choice = tk.StringVar(value="不锁定属性" if is_wangmu else "困难")
            modes = ttk.Combobox(frame, textvariable=choice,
                                 values=("锁定属性", "不锁定属性") if is_wangmu else ("普通", "困难"),
                                 state="readonly", width=8)
            modes.pack(side="left", padx=5)
            status = ttk.Label(frame, text="待刷新", width=40)
            status.pack(side="left", padx=10)
            button = ttk.Button(frame, text="自动通关一次" if is_wangmu else "执行剩余免费次数", state="disabled",
                                command=lambda n=name: self._do_event_dungeon(n))
            button.pack(side="left", padx=5)
            self.event_dungeon_rows[name] = (choice, status, button)
        ttk.Button(tab, text="刷新活动副本次数", command=self._refresh_event_dungeons).pack(anchor="w", pady=10)
        ttk.Label(tab, text="挑战萌哥活动配置截止 10 月 7 日；王母试炼的副本请求已实测，开放情况每次以服务器回包为准。",
                  foreground="gray").pack(anchor="w")

    def _event_dungeon_used(self, scene, spec):
        shared = set(spec["shared"])
        return sum(int(record.get("num", 0)) for record in
                   scene.get("curRecord", {}).get("copyHistory", [])
                   if int(record.get("id", -1)) in shared)

    def _event_dungeon_config(self, name, mid):
        spec = self.event_dungeon_specs[name]
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
        with open(os.path.join(config_dir, "036___Dungeon.xml.json"), encoding="utf-8") as f:
            dungeons = json.load(f)["RECORD"]
        with open(os.path.join(config_dir, "002___Activity.xml.json"), encoding="utf-8") as f:
            activities = json.load(f)["RECORD"]
        dungeon = next((x for x in dungeons if int(x.get("id", -1)) == mid), None)
        if spec["reward_route"]:
            with open(os.path.join(config_dir, "129___PanTaoHelp.xml.json"), encoding="utf-8") as f:
                help_rows = json.load(f)["RECORD"]
            help_row = next(x for x in help_rows if int(x["id"]) == 3)
            activity_id = int(help_row["activityId"])
        else:
            activity_id = spec["activities"][spec["mids"].index(mid)]
        activity = next((x for x in activities if int(x.get("id", -1)) == activity_id), None)
        if not dungeon or not activity:
            raise RuntimeError("活动或副本配置缺失")
        if (int(dungeon.get("consumePointTicket", -1)) != 0 or
                int(dungeon.get("consumePower", 0)) != -1 or
                int(dungeon.get("dailyCountMax", -1)) != spec["max"] or
                (not spec["reward_route"] and int(activity.get("dungeonId", -1)) != mid) or
                mid not in spec["shared"] or
                tuple(int(x) for x in dungeon.get("shareDungeonID", "").split(";") if x) != spec["shared"]):
            raise RuntimeError("免费入口或共享次数配置与实测不符")
        begin = datetime.strptime(activity["shelfTime"], "%Y/%m/%d-%H:%M:%S")
        end = datetime.strptime(activity["underTime"], "%Y/%m/%d-%H:%M:%S")
        if not begin <= datetime.now() <= end:
            raise RuntimeError("活动配置不在开放日期内")
        return dungeon

    @staticmethod
    def _wangmu_event_pair(activity_info):
        if activity_info.get("code") != 200:
            raise RuntimeError("读取王母事件失败，未进入副本")
        event = (activity_info.get("panTaoAct") or {}).get("event") or []
        if not isinstance(event, list) or not event:
            raise RuntimeError("服务器未下发王母事件，未进入副本")
        try:
            pair = tuple(int(x) for x in str(event[0]).split(";"))
        except ValueError:
            raise RuntimeError("王母事件关卡格式异常，未进入副本")
        if pair not in ((2140, 2141), (2174, 2175)):
            raise RuntimeError("王母事件关卡尚未确认：%s" % (pair,))
        return pair

    def _refresh_event_dungeons(self):
        if not self._ensure_login():
            return
        threading.Thread(target=self._event_dungeons_refresh_worker, daemon=True).start()

    def _event_dungeons_refresh_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        if not getattr(self, "event_dungeon_specs", None):
            return  # 该页已随过期活动下线，无需刷新
        try:
            flow, _, scene = self._connect_and_enter()
            for name, spec in self.event_dungeon_specs.items():
                used = self._event_dungeon_used(scene, spec)
                try:
                    self._event_dungeon_config(name, spec["mids"][1])
                    available = used < spec["max"]
                    status = "今日 %d/%d，剩余 %d 次" % (used, spec["max"], max(0, spec["max"] - used))
                    if spec["reward_route"]:
                        pair = self._wangmu_event_pair(flow.request("scene.holidayHandler.getPanTaoActInfo", {}, timeout=15))
                        status = ("东方朔" if pair[0] == 2140 else "仙桃灵妖") + "；" + status
                except Exception as e:
                    available = False
                    status = "当前不可挑战：%s" % e
                self._count_after(_count_generation, 0, lambda n=name, a=available, t=status: self._show_event_dungeon_status(n, a, t))
            flow.disconnect()
        except Exception as e:
            self._log("[活动副本] 刷新失败：%s" % e)

    def _show_event_dungeon_status(self, name, available, status):
        _, label, button = self.event_dungeon_rows[name]
        label.config(text=status)
        button.config(state="normal" if available else "disabled")

    def _do_event_dungeon(self, name):
        if not self._ensure_login():
            return
        choice, _, button = self.event_dungeon_rows[name]
        mid = self.event_dungeon_specs[name]["mids"][0 if choice.get() in ("普通", "锁定属性") else 1]
        button.config(state="disabled")
        threading.Thread(target=self._event_dungeon_worker, args=(name, mid), daemon=True).start()

    def _event_dungeon_worker(self, name, mid):
        try:
            attempts = 3 if name == "挑战萌哥" else 1
            for number in range(attempts):
                self._log("[活动副本] %s：第%d次免费挑战检查" % (name, number + 1))
                if not self._event_dungeon_once(name, mid):
                    break
                if number + 1 < attempts:
                    time.sleep(5)
        finally:
            self._event_dungeons_refresh_worker()

    def _event_dungeon_once(self, name, mid):
        flow = after_flow = None
        try:
            spec = self.event_dungeon_specs[name]
            self._event_dungeon_config(name, mid)
            flow, _, scene = self._connect_and_enter()
            used = self._event_dungeon_used(scene, spec)
            if used >= spec["max"]:
                self._log("[活动副本] %s 共享免费次数已用完：%d/%d" % (name, used, spec["max"]))
                return False
            before_items = {str(x.get("id", x.get("itemId", ""))):
                            self._special_item_count(scene, x.get("id", x.get("itemId", "")))
                            for x in scene["curRecord"].get("itemsBag", {}).get("items", [])}
            xianqi_before = None
            if spec["reward_route"]:
                activity_info = flow.request("scene.holidayHandler.getPanTaoActInfo", {}, timeout=15)
                pair = self._wangmu_event_pair(activity_info)
                mode_index = spec["mids"].index(mid)
                mid = pair[mode_index]
                self._event_dungeon_config(name, mid)
                xianqi_before = int((activity_info.get("panTaoAct") or {}).get("xianqi", 0))
                self._log("[王母试炼] 服务器事件%s，本次进入%d" % (pair, mid))
            p1 = scene["curRecord"]["p1"]
            created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                   {"mid": mid, "costGem": 0}, timeout=15)
            if created.get("code") != 200:
                raise RuntimeError("创建副本失败：%s" % created.get("error", created))
            drops = created.get("drops") or {}
            copy_id = drops.get("copyId")
            if not copy_id:
                raise RuntimeError("创建副本未返回 copyId")
            pick_items, mob_ids, kill_monsters = [], [], []
            pick_exp = pick_spirit = 0
            planned = {}
            for drop in drops.get("newDrops") or []:
                monster = str(drop.get("monsterId", "0"))
                pick_exp += int(drop.get("exp", 0) or 0)
                pick_spirit += int(drop.get("spirit", 0) or 0)
                for _field, group in drop_groups(drop):
                    mob_ids.append(monster)
                    kill_monsters.append("%s_%s" % (monster, drop.get("index", 0)))
                    for item_id, items in group.items():
                        for item in items:
                            pick_items.append(item)
                            count = int(item.get("count", 1) or 1) if isinstance(item, dict) else 1
                            planned[str(item_id)] = planned.get(str(item_id), 0) + count
            self._log("[活动副本] %s %s：预生成可拾取道具 %s" %
                      (name, mid, planned or "无"))
            if not spec["reward_route"]:
                dead = flow.request("scene.copyHandler.bossDead", None, timeout=15)
                if dead.get("code") != 200:
                    raise RuntimeError("Boss 死亡通知失败：%s" % dead)
            finished = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
            if finished.get("code") != 200:
                raise RuntimeError("通关请求失败：%s" % finished)
            payload = {
                "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                "killMonsters": kill_monsters, "completed": 1,
                "currentEXP": p1["experience"], "pickExp": pick_exp, "pickSp": pick_spirit,
                "propertyP1Str": ";".join(str(p1[k]) for k in
                    ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
                "propertyP2Total": 0, "hitCombo": 100,
            }
            if not spec["reward_route"]:
                settled = flow.request("scene.copyHandler.syncDropInfoNew", payload, timeout=20)
                if settled.get("code") != 200:
                    raise RuntimeError("拾取结算失败：%s" % settled.get("error", settled))
            rewards = []
            if spec["reward_route"]:
                claimed = flow.request("scene.copyHandler.getXianJinDungeonRewards",
                                       {"id": mid, "pickItems": []}, timeout=20)
                if claimed.get("code") != 200:
                    raise RuntimeError("通关已结算，但专用领奖失败：%s" % claimed.get("error", claimed))
                rewards = claimed.get("items") or []
                self._log("[活动副本] %s 领奖回包：%s" % (name, rewards))
            after_flow, _, after_scene = self._connect_and_enter()
            after_used = self._event_dungeon_used(after_scene, spec)
            self._log("[活动副本] %s 共享次数：%d → %d" % (name, used, after_used))
            if after_used != used + 1:
                raise RuntimeError("次数未增加1，停止后续挑战")
            expected = dict(planned)
            xianqi_reward = 0
            if spec["reward_route"]:
                for reward in rewards:
                    item_id = str(reward.get("id"))
                    if item_id == "900000023":
                        xianqi_reward += int(reward.get("count", 0))
                        continue
                    expected[item_id] = expected.get(item_id, 0) + int(reward.get("count", 0))
                if xianqi_before is not None:
                    activity_after = after_flow.request("scene.holidayHandler.getPanTaoActInfo", {}, timeout=15)
                    if activity_after.get("code") == 200:
                        xianqi_after = int((activity_after.get("panTaoAct") or {}).get("xianqi", 0))
                        xianqi_delta = xianqi_after - xianqi_before
                        self._log("[活动副本核验] 仙气：%d → %d（增加 %d；领奖回包 %d）%s" %
                                  (xianqi_before, xianqi_after, xianqi_delta, xianqi_reward,
                                   "" if xianqi_delta == xianqi_reward else "，与回包不一致"))
                    else:
                        self._log("[活动副本核验] 仙气查询失败；只确认领奖回包 %d" % xianqi_reward)
                elif xianqi_reward:
                    self._log("[活动副本核验] 仙气未取得领奖前基线；只确认领奖回包 %d" % xianqi_reward)
            for item_id, count in expected.items():
                old = before_items.get(item_id, 0)
                new = self._special_item_count(after_scene, item_id)
                delta = new - old
                self._log("[活动副本核验] 道具 %s：%d → %d（增加 %d；回包/掉落 %d）%s" %
                          (item_id, old, new, delta, count,
                           "" if delta == count else "，与回包不一致"))
            return after_used < spec["max"]
        except Exception as e:
            self._log("[活动副本] %s %s 失败：%s" % (name, mid, e))
            return False
        finally:
            for connection in (flow, after_flow):
                if connection:
                    connection.disconnect()

    # ========== 玉兔逐月标签页 ==========
    def _build_yutu_tab(self):
        tab = self._limited_page("玉兔逐月", padding=10)
        subpages = ttk.Notebook(tab)
        subpages.pack(fill="both", expand=True)
        capture_page = ttk.Frame(subpages, padding=8)
        tab = ttk.Frame(subpages, padding=8)
        subpages.add(tab, text="逐月挑战")
        subpages.add(capture_page, text="捕捉玉兔")
        from yutu_capture import build_panel
        build_panel(self, capture_page)

        action_frame = ttk.LabelFrame(tab, text="玉兔逐月设置", padding=10)
        action_frame.pack(fill="x", pady=5)

        ttk.Label(action_frame, text="目标分数:").grid(row=0, column=0, padx=3)
        self.entry_yutu_score = ttk.Entry(action_frame, width=8)
        self.entry_yutu_score.insert(0, "4100")
        self.entry_yutu_score.grid(row=0, column=1, padx=3)

        self.var_yutu_times = tk.IntVar(value=1)
        ttk.Label(action_frame, text="挑战次数:").grid(row=0, column=2, padx=3)
        ttk.Spinbox(action_frame, from_=1, to=2, textvariable=self.var_yutu_times, width=5).grid(row=0, column=3, padx=3)

        self.btn_yutu = ttk.Button(action_frame, text="一键玉兔逐月", command=self._do_yutu, state="disabled")
        self.btn_yutu.grid(row=0, column=4, padx=8)

        ttk.Label(action_frame, text="⚠ 每天2次，4100分拿满奖励", foreground="orange").grid(row=0, column=5, padx=8)

        # 奖励预览
        reward_frame = ttk.LabelFrame(tab, text="4100分奖励预览", padding=8)
        reward_frame.pack(fill="x", pady=5)

        tree = ttk.Treeview(reward_frame, columns=("name", "count"), show="headings", height=3)
        tree.heading("name", text="物品")
        tree.heading("count", text="数量")
        tree.column("name", width=200)
        tree.column("count", width=80, anchor="center")
        tree.insert("", "end", values=("月饼 (143200001)", 1))
        tree.insert("", "end", values=("一袋仙宫面粉 (143200010)", 2))
        tree.insert("", "end", values=("月饼礼包 (199200051)", 1))
        tree.pack(fill="x")

        info_frame = ttk.LabelFrame(tab, text="说明", padding=8)
        info_frame.pack(fill="x", pady=5)
        ttk.Label(info_frame, text="• 关卡 id=2161，60秒跳跃游戏\n• 直接发送4100分结算，无需实际操作\n• 结算路由: scene.copyHandler.getDumpActRewards",
                  justify="left").pack(anchor="w")

    # ========== 月宫厨房标签页 ==========
    def _build_moon_tab(self):
        tab = self._limited_page("月宫厨房", padding=10)

        # 操作区
        action_frame = ttk.LabelFrame(tab, text="博饼操作", padding=10)
        action_frame.pack(fill="x", pady=5)

        self.btn_moon = ttk.Button(action_frame, text="一键博饼", command=self._do_moon_kitchen, state="disabled")
        self.btn_moon.pack(side="left", padx=5)

        ttk.Label(action_frame, text="次数(0=跑完免费):").pack(side="left", padx=2)
        self.var_moon_count = tk.StringVar(value="0")
        ttk.Entry(action_frame, textvariable=self.var_moon_count, width=5).pack(side="left", padx=2)

        self.var_moon_use_flour = tk.BooleanVar(value=False)
        ttk.Checkbutton(action_frame, text="消耗面粉继续", variable=self.var_moon_use_flour).pack(side="left", padx=8)

        self.lbl_moon_flour = ttk.Label(action_frame, text="面粉: 未知 | 免费已用: 未知", foreground="blue", font=("微软雅黑", 10, "bold"))
        self.lbl_moon_flour.pack(side="left", padx=10)

        self.lbl_moon_status = ttk.Label(action_frame, text="", foreground="gray")
        self.lbl_moon_status.pack(side="left", padx=10)

        # 当前骰子显示区
        dice_frame = ttk.LabelFrame(tab, text="本次博饼骰子", padding=10)
        dice_frame.pack(fill="x", pady=5)

        self.lbl_dice = ttk.Label(dice_frame, text="🎲 🎲 🎲 🎲 🎲 🎲", font=("微软雅黑", 24, "bold"))
        self.lbl_dice.pack(pady=5)

        self.lbl_dice_result = ttk.Label(dice_frame, text="等待博饼...", font=("微软雅黑", 14, "bold"), foreground="orange")
        self.lbl_dice_result.pack(pady=5)

        # 结果显示区
        result_frame = ttk.LabelFrame(tab, text="博饼记录", padding=8)
        result_frame.pack(fill="both", expand=True, pady=5)

        self.text_moon = scrolledtext.ScrolledText(result_frame, wrap="word", font=("Consolas", 9))
        self.text_moon.pack(fill="both", expand=True)

        # 奖励概率表
        prob_frame = ttk.LabelFrame(tab, text="奖励概率表", padding=5)
        prob_frame.pack(fill="x", pady=5)

        tree = ttk.Treeview(prob_frame, columns=("name", "mooncake", "prob"), show="headings", height=8)
        tree.heading("name", text="奖项")
        tree.heading("mooncake", text="月饼")
        tree.heading("prob", text="概率")
        tree.column("name", width=120, anchor="center")
        tree.column("mooncake", width=80, anchor="center")
        tree.column("prob", width=80, anchor="center")
        for rid in sorted(MOON_KITCHEN_REWARDS.keys(), reverse=True):
            r = MOON_KITCHEN_REWARDS[rid]
            tree.insert("", "end", values=(r["name"], r["mooncake"], r["prob"]))
        tree.pack(fill="x")

    # ========== 通用方法 ==========
    def _log(self, msg):
        ui_log(msg)
        audit_error = take_error()
        def _append():
            self.text_log.insert("end", msg + "\n")
            if audit_error:
                self.text_log.insert("end", "[日志保存] " + audit_error + "；游戏流程继续。\n")
            self.text_log.see("end")
        self.root.after(0, _append)

    def _toggle_login_mode(self):
        cookie_mode = self.var_login_mode.get() == "cookie"
        self.entry_user.config(state="disabled" if cookie_mode else "normal")
        self.entry_pass.config(state="disabled" if cookie_mode else "normal")
        if cookie_mode:
            self.cookie_login_frame.grid()
            self.entry_cookie.focus_set()
        else:
            self.cookie_login_frame.grid_remove()

    def _paste_login_cookie(self):
        try:
            value = self.root.clipboard_get().strip()
        except tk.TclError:
            messagebox.showinfo("粘贴Cookie", "剪贴板里没有文本，请先复制完整Cookie")
            return
        self.entry_cookie.delete(0, tk.END)
        self.entry_cookie.insert(0, value)

    def _do_login(self):
        username = self.entry_user.get().strip()
        password = self.entry_pass.get().strip()
        mode = self.var_login_mode.get()
        cookie_text = self.entry_cookie.get().strip()
        saved_name = getattr(self, "_loaded_account_name", "") or ""
        if mode == "cookie":
            if not cookie_text and saved_name:
                # 界面上只显示账号名，实际用本机已加密保存的Cookie登录
                cookie_text = self._saved_cookie_for(saved_name)
                username = saved_name
                if cookie_text:
                    self._log("[登录] 使用已存账号%s的Cookie登录" % saved_name)
            if not cookie_text:
                messagebox.showwarning("提示", "请粘贴完整的4399 Cookie，或先载入已保存账号")
                return
        elif not username or not password:
            messagebox.showwarning("提示", "请输入账号和密码")
            return

        self.btn_login.config(state="disabled")
        self.lbl_status.config(text="登录中...", foreground="orange")
        self.root.update_idletasks()

        def worker():
            try:
                if mode == "cookie":
                    client = ZM4Client.from_cookie_string(cookie_text, record_index=0)
                else:
                    try:
                        client = ZM4Client.from_password(username, password, record_index=0)
                    except Exception as error:
                        if "验证码" not in str(error) or not cookie_text:
                            raise
                        fallback = ZM4Client.from_cookie_string(cookie_text, record_index=0)
                        if fallback.username != username:
                            raise RuntimeError("账号密码登录需要验证码；备用Cookie与输入账号不一致，请粘贴同一账号的Cookie") from None
                        self._log("[登录] 账号密码触发验证码，改用同一账号的备用Cookie")
                        client = fallback
                saves = self._list_saves(client)
                self.root.after(0, lambda: self._on_login_success(client, saves))
            except Exception as error:
                message = str(error)
                self.root.after(0, lambda text=message: self._on_login_fail(text))

        threading.Thread(target=worker, daemon=True).start()

    def _list_saves(self, client):
        saves = []
        from pypomelo.login4399 import fetch_game_token
        from pypomelo.flow import GameLoginFlow
        from zm4_client import ZM4_GAME_ID, ZM4_GATE_IPS, ZM4_PORT
        from zm4_version import enter_record, save_summary, get_client_version, EmptySaveSlot

        token = fetch_game_token(client.uid, client.username, client.cookies, game_id=ZM4_GAME_ID)
        self._log('[登录] 自动检查登录协议版本：%s' % get_client_version())
        failures = []

        for i in range(8):
            flow = AuditFlow(GameLoginFlow(client.uid, token), client.uid, None)
            host = port = None
            for ip in ZM4_GATE_IPS:
                try:
                    host, port = flow.query_entry(ip, ZM4_PORT, timeout=10)
                    break
                except:
                    continue
            if not host:
                flow.disconnect()
                failures.append('槽%s：所有gate连接失败' % i)
                saves.append({'index': i, 'name': '读取失败', 'level': '-', 'unavailable': True})
                continue
            try:
                auth = flow.auth(host, port, timeout=15)
                if auth.get('code') != 200 or auth.get('error'):
                    raise RuntimeError('游戏认证失败：%s' % auth.get('error', auth.get('code')))
                entry = enter_record(flow, i, client.user_agent)
                saves.append(save_summary(entry, i))
            except EmptySaveSlot:
                saves.append({'index': i, 'name': '空存档', 'level': '-', 'empty': True})
            except Exception as error:
                message = str(error)
                self._log('[存档] 槽%s读取失败：%s' % (i, message))
                if '版本不匹配' in message:
                    raise
                failures.append('槽%s：%s' % (i, message))
                saves.append({'index': i, 'name': '读取失败', 'level': '-', 'unavailable': True})
            finally:
                flow.disconnect()
        if not any(not save.get('unavailable') for save in saves):
            raise RuntimeError('存档读取全部失败；并非空存档。' + '；'.join(failures[:3]))
        return saves

    def _on_login_success(self, client, saves):
        self.client = client
        self.saves = saves
        self.btn_login.config(state="normal")
        self.lbl_status.config(text="登录成功: %s" % client.username, foreground="green")

        save_strs = ["槽%d: %s Lv.%s" % (s["index"], s["name"], s["level"]) for s in saves]
        self.combo_save["values"] = save_strs
        if save_strs:
            first = next((i for i, save in enumerate(saves) if not save.get('unavailable') and not save.get('empty')), 0)
            self.combo_save.current(first)
            self.current_save = saves[first]
            saved_index = getattr(self, "_quick_saved_save", None)
            loaded_account, loaded_slot = getattr(self, '_loaded_account_slot', (None, None))
            if loaded_account == client.username and isinstance(loaded_slot, int): saved_index = loaded_slot
            if getattr(self, "_schedule_login_callbacks", None):
                schedule_slot = load_schedule(self._schedule_file()).get("slot")
                if isinstance(schedule_slot, int):
                    saved_index = schedule_slot
            for position, save in enumerate(saves):
                if save["index"] == saved_index and not save.get('unavailable'):
                    self.combo_save.current(position)
                    self.current_save = save
                    break
            self.lbl_save_info.config(text="当前: 槽%d %s Lv.%s" % (
                self.current_save["index"], self.current_save["name"], self.current_save["level"]),
                foreground="green")
            self._enable_all_buttons()
            self.lbl_treasure_status.config(text="点击读取寻宝状态", foreground="gray")
            self.lbl_dice_online.config(text="点击读取在线状态", foreground="gray")
            self._mainline_reset_display()
            self._daily_task_reset_display()
            from count_states import refresh
            refresh(self)

        self._log("[登录] 成功: %s，共%d个存档" % (client.username, len(saves)))
        self._auto_save_account(client)
        slot = self.current_save.get("index") if self.current_save else None
        update_schedule_identity(self.MY_DAILY_FAVORITES, client.username, slot)
        callbacks = getattr(self, "_schedule_login_callbacks", None)
        if callbacks:
            self._schedule_login_callbacks = []
            for callback in callbacks:
                self.root.after(0, callback)

    def _on_login_fail(self, error):
        self.btn_login.config(state="normal")
        self.lbl_status.config(text="登录失败", foreground="red")
        if "验证码" in error:
            self.var_login_mode.set("cookie")
            self._toggle_login_mode()
            error += "\n已切换到Cookie登录。请在浏览器登录4399，复制该账号完整Cookie后粘贴，再点击登录。"
        messagebox.showerror("登录失败", error)

    def _on_save_select(self, event=None):
        if getattr(self, "_jiuzhuan_running", False) or getattr(self, "_halloween_busy", False):
            return
        idx = self.combo_save.current()
        if idx >= 0:
            self.current_save = self.saves[idx]
            self._main_daily_counts = None
            self.lbl_main_dailycount.config(text="当前dailyCount：正在读取")
            self.lbl_treasure_status.config(text="点击读取寻宝状态", foreground="gray")
            self.lbl_dice_online.config(text="点击读取在线状态", foreground="gray")
            self.lbl_save_info.config(text="当前: 槽%d %s Lv.%s" % (
                self.current_save["index"], self.current_save["name"], self.current_save["level"]),
                foreground="green")
            self._enable_all_buttons()
            self._mainline_reset_display()
            self._daily_task_reset_display()
            from count_states import refresh
            refresh(self)
            if self.client: self._auto_save_account(self.client)

    def _refresh_finished_counts(self, slot, client):
        if self.client is client and self.current_save and self.current_save['index'] == slot:
            from count_states import refresh
            refresh(self)

    def _count_after(self, generation, delay, callback, *args):
        def guarded():
            if generation == getattr(self, '_count_generation', 0):
                callback(*args)
        return self.root.after(delay, guarded)

    def _enable_all_buttons(self):
        if self.btn_quick_stop.instate(["disabled"]):
            self.btn_quick_run.config(state="normal")
        self.btn_load_survival.config(state="normal")
        self.btn_daily_run.config(state="normal")
        self.btn_treasure_check.config(state="normal")
        self.btn_treasure_run.config(state="normal")
        self.btn_dice_check.config(state="normal")
        if not self.btn_dice_stop.instate(["!disabled"]):
            self.btn_dice_start.config(state="normal")
            self.btn_dice_roll.config(state="normal")
        self.btn_daily_task_check.config(state="normal")
        self.btn_daily_task_accept.config(state="normal")
        self.btn_daily_task_complete.config(state="normal")
        self.btn_daily_task_claim.config(state="normal")
        self.btn_daily_task_batch1.config(state="normal")
        self.btn_daily_task_batch2.config(state="normal")
        self.btn_daily_task_batch3.config(state="normal")
        self.btn_daily_task_save1.config(state="normal")
        self.btn_daily_task_save2.config(state="normal")
        self.btn_daily_task_save3.config(state="normal")
        self.btn_pet_batch1.config(state="normal")
        self.btn_pet_batch2.config(state="normal")
        self.btn_pet_batch3.config(state="normal")
        self.btn_pet_save1.config(state="normal")
        self.btn_pet_save2.config(state="normal")
        self.btn_pet_save3.config(state="normal")
        self._pet_batch_update_labels()
        self.btn_mount_batch1.config(state="normal")
        self.btn_mount_batch2.config(state="normal")
        self.btn_mount_batch3.config(state="normal")
        self.btn_mount_save1.config(state="normal")
        self.btn_mount_save2.config(state="normal")
        self.btn_mount_save3.config(state="normal")
        self._mount_batch_update_labels()
        self.btn_mainfarm_run.config(state="normal")
        self.btn_mainline_check.config(state="normal")
        self.btn_mainline_run.config(state="normal")
        self.btn_nightmare_run.config(state="normal")
        self.btn_sj_run.config(state="normal")
        self.btn_hide_run.config(state="normal")
        if self.btn_horse_capture_stop.instate(["disabled"]):
            self.btn_horse_capture_run.config(state="normal")

    def _ensure_login(self):
        if self.client and self.current_save is not None:
            if self.current_save.get('unavailable') or self.current_save.get('empty'):
                messagebox.showwarning('存档不可用', '请选择已成功读取且有角色的存档')
                return False
            return True
        messagebox.showwarning("请先登录", "请先登录账号并选择存档")
        return False

    def _connect_and_enter(self, save_index=None):
        """连接游戏服并进入存档，返回flow"""
        from pypomelo.login4399 import fetch_game_token
        from pypomelo.flow import GameLoginFlow
        from zm4_client import ZM4_GAME_ID, ZM4_GATE_IPS, ZM4_PORT
        from zm4_version import enter_record

        selected_slot = self.current_save['index'] if save_index is None else save_index
        token = fetch_game_token(self.client.uid, self.client.username,
                                 self.client.cookies, game_id=ZM4_GAME_ID)
        flow = GlobalPickupFilter(AuditFlow(GameLoginFlow(self.client.uid, token), self.client.uid,
                                  selected_slot),
                                  lambda: getattr(self, "_skip_supply_pickups", False))
        host = port = None
        for ip in ZM4_GATE_IPS:
            try:
                host, port = flow.query_entry(ip, ZM4_PORT, timeout=10)
                break
            except:
                continue
        if not host:
            flow.disconnect()
            raise RuntimeError("所有gate服连接失败")
        try:
            auth = flow.auth(host, port, timeout=15)
            if auth.get('code') != 200 or auth.get('error'):
                raise RuntimeError('游戏认证失败：%s' % auth.get('error', auth.get('code')))
            # 魂器独立背包 soulBag 只随登录后的 onSendRecord 推送下发，curRecord 里没有。
            self._soul_bag = None
            try:
                flow.on("onSendRecord", self._capture_soul_bag)
            except Exception:
                pass
            entry = enter_record(flow, selected_slot,
                                 self.client.user_agent)
            enter_result = flow.request("scene.playerHandler.enterScene", None)
            if enter_result.get('code') != 200 or enter_result.get('error') or not enter_result.get('curRecord'):
                raise RuntimeError('进入场景失败：%s' % enter_result.get('error', enter_result.get('code')))
            if getattr(self, '_auto_daily_before_battle', False):
                # 战前自动接取：登录快照只取一次，本次会话内自己接过的任务单独记账，避免重复 startTask
                self._prebattle_accepted = set()
                def before_create(payload):
                    if isinstance(payload, dict) and payload.get('mid') is not None:
                        self._accept_matching_daily(flow, int(payload['mid']), selected_slot, enter_result)
                flow.before_create = before_create
            return flow, entry, enter_result
        except Exception:
            flow.disconnect()
            raise

    def _capture_soul_bag(self, body):
        """登录后 onSendRecord 推送里带独立魂器背包 soulBag（curRecord 里没有这一项）。"""
        if isinstance(body, dict) and isinstance(body.get("soulBag"), dict):
            self._soul_bag = body["soulBag"]

    @staticmethod
    def _soul_bag_summary(bag):
        """魂器背包摘要：(容量, 已用, 剩余)。"""
        bag = bag or {}
        items = bag.get("items") or []
        used = len(items)
        cap = bag.get("itemCount")
        free = bag.get("freeCount")
        if free is None and isinstance(cap, int):
            free = max(0, cap - used)
        return cap, used, free

    def _confirm_new_souls(self, reply, tag, prop_map):
        """结算回包 add.newSouls 才是真正进了魂器背包的魂器，返回条数。"""
        add = (reply or {}).get("add") or {}
        news = add.get("newSouls") or []
        n = 0
        for s in news:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id"))
            n += 1
            self._log("    ✔ %s魂器入包: %s(%s) entityId=%s" % (
                tag, prop_map.get(sid, sid), sid, s.get("entityId")))
        return n

    # ========== 生存大冒险 ==========
    def _load_survival(self):
        if not self.client or self.current_save is None:
            return
        self.btn_load_survival.config(state="disabled")
        self.text_survival.delete("1.0", "end")
        self._log("[生存大冒险] 加载题目中...")

        def worker():
            try:
                flow, entry, _ = self._connect_and_enter()
                info = flow.request("scene.holidayHandler.getSurvivalInfo", {})
                day = info.get("day", 1)
                attr = info.get("survivalAttr", {})
                qinfo = info.get("survivalInfo", {})
                qids = [str(q) for q in qinfo.get("question", [])]
                cur_q = qinfo.get("curQ", 0)

                if cur_q == 0:
                    try:
                        begin = flow.request("scene.holidayHandler.beginSurvival", {"day": day, "type": 1})
                        if begin.get("code") == 200:
                            if begin.get("survivalAttr"):
                                attr = begin["survivalAttr"]
                            if begin.get("survivalInfo"):
                                qinfo = begin["survivalInfo"]
                                qids = [str(q) for q in qinfo.get("question", [])]
                    except:
                        pass

                self._survival_data = {"day": day, "attr": attr, "qids": qids, "flow": flow, "cur_q": cur_q}
                self.root.after(0, lambda: self._on_survival_loaded(attr, qids, day, cur_q))
            except Exception as e:
                import traceback
                error = str(e) + "\n" + traceback.format_exc()
                self.root.after(0, lambda error=error: self._on_survival_fail(error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_survival_loaded(self, attr, qids, day, cur_q=0):
        self.btn_load_survival.config(state="normal")
        role_code = get_role_code(attr)
        role_name = CODE_NAME_MAP.get(role_code, attr.get("born", "未知"))
        progress = "（已答%d题）" % cur_q if cur_q > 0 else ""
        self.lbl_survival_role.config(text="角色: %s (代号%s, 第%d天)%s" % (role_name, role_code, day, progress))

        attr_str = "  ".join("%s=%s" % (ATTR_NAMES.get(k, k), v) for k, v in attr.items() if k not in ("id", "born"))
        self.lbl_survival_attrs.config(text=attr_str)

        self.text_survival.insert("end", "=" * 50 + "\n")
        self.text_survival.insert("end", "题目序列: %s\n" % qids)
        self.text_survival.insert("end", "=" * 50 + "\n")

        if role_code == "?" or not Solver:
            self.text_survival.insert("end", "无法计算最优解\n")
            return

        try:
            solver = Solver(self._solver_db)
            initial = {k: attr.get(k, 0) for k in ["health", "power", "wisdom", "charm", "luck", "smart"]}
            max_score, path, died_early = solver.solve(initial, qids, survive_questions=9)

            self.text_survival.insert("end", "\n【最优解】总分: %d 分\n" % max_score)
            died_step = next((s["step"] for s in path if s["died"]), None)
            self.text_survival.insert("end", "存活: %s\n" % ("第%d题后死亡" % died_step if died_step else "全程存活"))
            self.text_survival.insert("end", "-" * 50 + "\n")

            for step in path:
                death_mark = " 【死亡】" if step["died"] else ""
                self.text_survival.insert("end", "第%d题 选%d: %s%s\n" % (
                    step["step"], step["opt_idx"], step["opt_text"][:25], death_mark))
                self.text_survival.insert("end", "  判定: %s, +%d分\n" % (step["result"], step["gain"]))

            self.btn_auto_answer.config(state="normal")
            self._log("[生存大冒险] 加载成功，角色=%s，最优=%d分" % (role_name, max_score))
        except Exception as e:
            self.text_survival.insert("end", "计算失败: %s\n" % e)

    def _on_survival_fail(self, error):
        self.btn_load_survival.config(state="normal")
        self._log("[生存大冒险] 失败: %s" % error[:100])
        messagebox.showerror("错误", error)

    def _auto_answer(self):
        if not self._survival_data:
            return
        data = self._survival_data
        cur_q = data.get("cur_q", 0)
        if cur_q >= len(data["qids"]):
            messagebox.showinfo("提示", "今日题目已全部答完")
            return

        if not messagebox.askyesno("确认", "从第%d题开始自动答题？\n免费，不消耗点券" % (cur_q + 1)):
            return

        self.btn_auto_answer.config(state="disabled")
        solver = Solver(self._solver_db)
        attr = data["attr"]
        initial = {k: attr.get(k, 0) for k in ["health", "power", "wisdom", "charm", "luck", "smart"]}
        max_score, path, died_early = solver.solve(initial, data["qids"], survive_questions=9)

        def worker():
            flow = data["flow"]
            day = data["day"]
            self._log("[生存大冒险] 开始自动答题（从第%d题）" % (cur_q + 1))
            total = 0
            for i, step in enumerate(path):
                if i < cur_q:
                    continue
                try:
                    result = flow.request("scene.holidayHandler.answerSurvival", {
                        "answer": step["opt_idx"], "day": day
                    })
                    if result.get("code") != 200:
                        self._log("  第%d题失败: %s" % (i + 1, result.get("error")))
                        break
                    score = result.get("rewardTip", {}).get("integral", 0)
                    total += int(score) if score else 0
                    self._log("  第%d题 选%d → +%s (累计%d)" % (i + 1, step["opt_idx"], score, total))
                    if step["died"]:
                        self._log("  角色死亡，停止")
                        break
                except Exception as e:
                    self._log("  第%d题异常: %s" % (i + 1, e))
                    break
            self._log("[生存大冒险] 完成，总积分: %d" % total)
            self.root.after(0, lambda: self.btn_auto_answer.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ========== 仙境危机 ==========
    def _do_pick(self):
        if not self.client or self.current_save is None:
            return
        peach3 = int(self.entry_peach3.get() or 0)
        peach9 = int(self.entry_peach9.get() or 0)

        if not messagebox.askyesno("确认",
            "确定摘桃子吗？\n存档: %s\n%d个三千年 + %d个九千年\n每天1次" % (
                self.current_save["name"], peach3, peach9)):
            return

        self.btn_pick.config(state="disabled")

        def worker():
            try:
                self._log("[仙境危机] 开始: 槽%d %s" % (self.current_save["index"], self.current_save["name"]))
                flow, entry, _ = self._connect_and_enter()
                p1 = entry.get("record", {}).get("p1", {})
                self._log("  角色: %s Lv.%s" % (p1.get("kindName", "?"), p1.get("level", "?")))

                self._log("  创建副本...")
                create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {
                    "mid": XIJING_ID, "costGem": 0
                })
                if create_result.get("code") != 200:
                    raise RuntimeError("创建失败: %s" % create_result.get("error"))

                # 计算需要触发多少次useItem1（三千年超过20的部分，每次+1上限，最多到30）
                basket_needed = max(0, peach3 - 20)
                if peach9 > 0:
                    basket_needed = max(basket_needed, 1)
                # 不设硬上限，自动计算（过高服务器会返回空）

                if basket_needed > 0:
                    self._log("  触发蟠桃篮模式 %d 次(三千年上限+%d, 解锁九千年)..." % (basket_needed, basket_needed))
                    for i in range(basket_needed):
                        try:
                            flow.request("scene.playerHandler.useItem1", {
                                "way": 1, "itemId": 169000001, "propType": 69, "pNum": 0
                            }, timeout=15)
                        except Exception as e:
                            self._log("  useItem1异常: %s" % e)

                self._log("  完成副本...")
                flow.request("scene.copyHandler.finishDungeon", {"dungeonId": XIJING_ID})

                self._log("  结算领取 %d三千年+%d九千年..." % (peach3, peach9))
                pick_items = [143300021] * peach3 + [143400004] * peach9
                reward = flow.request("scene.copyHandler.getXianJinDungeonRewards", {
                    "id": XIJING_ID, "pickItems": pick_items
                })

                if reward.get("code") == 200:
                    items = reward.get("items", [])
                    got3 = sum(it.get("count",0) for it in items if str(it.get("id"))=="143300021")
                    got9 = sum(it.get("count",0) for it in items if str(it.get("id"))=="143400004")
                    self._log("[仙境危机] 成功！实际获得 %d三千年+%d九千年蟠桃" % (got3, got9))
                    messagebox.showinfo("成功", "摘桃子成功！\n获得 %d三千年 + %d九千年" % (got3, got9))
                else:
                    self._log("[仙境危机] 失败: %s" % reward.get("error"))
                    messagebox.showerror("失败", reward.get("error", "未知错误"))

                flow.disconnect()
            except Exception as e:
                self._log("[仙境危机] 异常: %s" % e)
                messagebox.showerror("错误", str(e))
            finally:
                self.root.after(0, lambda: self.btn_pick.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ========== 玉兔逐月 ==========
    def _do_yutu(self):
        if not self.client or self.current_save is None:
            return
        score = int(self.entry_yutu_score.get() or 4100)
        times = self.var_yutu_times.get()

        if not messagebox.askyesno("确认",
            "确定玉兔逐月吗？\n存档: %s\n分数: %d\n次数: %d\n每天2次免费" % (
                self.current_save["name"], score, times)):
            return

        self.btn_yutu.config(state="disabled")

        def worker():
            try:
                self._log("[玉兔逐月] 开始: 槽%d %s，目标%d分，%d次" % (
                    self.current_save["index"], self.current_save["name"], score, times))
                flow, entry, _ = self._connect_and_enter()

                total_items = {}
                for i in range(times):
                    self._log("  第%d次: 创建副本..." % (i + 1))
                    create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {
                        "mid": YUTU_ID, "costGem": 0
                    })
                    if create_result.get("code") != 200:
                        self._log("  创建失败: %s" % create_result.get("error"))
                        break

                    self._log("  第%d次: 结算 %d分..." % (i + 1, score))
                    reward = flow.request("scene.copyHandler.getDumpActRewards", {
                        "id": YUTU_ID, "killMonsters": [], "score": score
                    }, timeout=15)

                    if reward.get("code") == 200:
                        copy_num = reward.get("copyNum", "?")
                        items = reward.get("items", [])
                        self._log("  第%d次成功！copyNum=%s, 奖励: %s" % (
                            i + 1, copy_num, json.dumps(items, ensure_ascii=False)))
                        for it in items:
                            iid = str(it.get("id"))
                            cnt = it.get("count", 1)
                            total_items[iid] = total_items.get(iid, 0) + cnt
                    else:
                        self._log("  第%d次失败: %s" % (i + 1, reward.get("error")))
                        break

                self._log("[玉兔逐月] 完成，累计奖励: %s" % json.dumps(total_items, ensure_ascii=False))
                if total_items:
                    messagebox.showinfo("成功", "玉兔逐月完成！\n累计奖励: %s" % json.dumps(total_items, ensure_ascii=False))
                flow.disconnect()
            except Exception as e:
                self._log("[玉兔逐月] 异常: %s" % e)
                messagebox.showerror("错误", str(e))
            finally:
                self.root.after(0, lambda: self.btn_yutu.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ========== 月宫厨房 ==========
    def _do_moon_kitchen(self):
        if not self.client or self.current_save is None:
            return

        if not messagebox.askyesno("确认",
            "确定月宫厨房博饼吗？\n存档: %s\n将消耗免费次数（用完自动停止）" % self.current_save["name"]):
            return

        self.btn_moon.config(state="disabled")
        self.text_moon.delete("1.0", "end")
        self.lbl_dice.config(text="🎲 🎲 🎲 🎲 🎲 🎲")
        self.lbl_dice_result.config(text="博饼中...", foreground="orange")

        def worker():
            try:
                self._log("[月宫厨房] 开始: 槽%d %s" % (self.current_save["index"], self.current_save["name"]))
                flow, entry, enter_result = self._connect_and_enter()

                # 从enterScene返回值获取面粉数量
                flour_count = self._get_flour_count(enter_result)
                autumn_num = self._get_autumn_num(entry)
                self.root.after(0, lambda fc=flour_count, an=autumn_num: self.lbl_moon_flour.config(
                    text="面粉: %d | 免费已用: %d" % (fc, an)))
                self._log("[月宫厨房] 面粉数量: %d, 免费已用: %d" % (flour_count, autumn_num))

                total_mooncake = 0
                round_num = 0
                target_count = 0
                try:
                    target_count = int(self.var_moon_count.get())
                except:
                    target_count = 0
                use_flour = self.var_moon_use_flour.get()
                self._log("[月宫厨房] 目标次数: %s (0=自动跑完免费), 消耗面粉: %s" % (target_count, use_flour))

                while True:
                    round_num += 1
                    result = flow.request("scene.holidayHandler.midAutumnActivity", {}, timeout=15)

                    if result.get("code") != 200:
                        self._log("[月宫厨房] 第%d次失败: %s" % (round_num, result.get("error")))
                        break

                    reward_id = result.get("rewardId", 0)
                    autumn_num = result.get("autumnNum", 0)
                    action_type = result.get("actionType", 0)
                    dice = result.get("randomNum", [])
                    reward = MOON_KITCHEN_REWARDS.get(reward_id, None)

                    # 检测异常情况（背包满等）
                    if reward is None or reward_id == 0:
                        error_msg = result.get("error", "未知错误")
                        self._log("[月宫厨房] 异常: rewardId=%s, error=%s, 完整返回: %s" % (
                            reward_id, error_msg, json.dumps(result, ensure_ascii=False)))
                        self.root.after(0, lambda: self.lbl_dice_result.config(
                            text="失败: %s" % error_msg, foreground="red"))
                        messagebox.showwarning("提示", "博饼失败！\n原因: %s\n\n可能是背包满了，请清理背包后重试。" % error_msg)
                        break

                    total_mooncake += reward["mooncake"]

                    # 详细日志（含原始返回）
                    self._log("[月宫厨房] 原始返回: %s" % json.dumps(result, ensure_ascii=False))

                    # 更新骰子显示
                    dice_str = " ".join("⚀⚁⚂⚃⚄⚅"[d-1] if 1 <= d <= 6 else "?" for d in dice)
                    result_text = "[%s] %d月饼" % (reward["name"], reward["mooncake"])
                    self.root.after(0, lambda ds=dice_str, rt=result_text: self._update_dice_display(ds, rt))

                    # 更新面粉和已用次数显示
                    if action_type == 1:
                        autumn_num += 1
                    elif action_type == 2 and flour_count > 0:
                        flour_count -= 1
                    self.root.after(0, lambda fc=flour_count, an=autumn_num: self.lbl_moon_flour.config(
                        text="面粉: %d | 免费已用: %d" % (fc, an)))

                    type_str = "免费" if action_type == 1 else "消耗面粉"
                    msg = "第%d次: [%s] 骰子=%s → %d月饼 (已用%d次, %s)" % (
                        round_num, reward["name"], dice, reward["mooncake"], autumn_num, type_str)
                    self.text_moon.insert("end", msg + "\n")
                    self.text_moon.see("end")
                    self._log("[月宫厨房] %s" % msg)

                    # actionType=2表示消耗面粉
                    if action_type == 2:
                        if not use_flour:
                            self._log("[月宫厨房] 免费次数用完，未勾选消耗面粉，停止")
                            break
                        if flour_count <= 0:
                            self._log("[月宫厨房] 面粉用完，停止")
                            break

                    # 指定次数达到
                    if target_count > 0 and round_num >= target_count:
                        self._log("[月宫厨房] 达到指定次数%d，停止" % target_count)
                        break

                    # 安全上限
                    if round_num >= 100:
                        self._log("[月宫厨房] 达到安全上限100次，停止")
                        break

                    time.sleep(0.3)

                self.text_moon.insert("end", "\n" + "=" * 50 + "\n")
                self.text_moon.insert("end", "完成！共%d次，累计%d个月饼\n" % (round_num, total_mooncake))
                self._log("[月宫厨房] 完成，共%d次，累计%d月饼" % (round_num, total_mooncake))
                self.root.after(0, lambda: self.lbl_dice_result.config(
                    text="完成！%d次共%d月饼" % (round_num, total_mooncake), foreground="green"))
                messagebox.showinfo("完成", "月宫厨房完成！\n共%d次，累计%d个月饼" % (round_num, total_mooncake))

                flow.disconnect()
            except Exception as e:
                self._log("[月宫厨房] 异常: %s" % e)
                error = str(e)[:30]
                self.root.after(0, lambda error=error: self.lbl_dice_result.config(text="异常: %s" % error, foreground="red"))
                messagebox.showerror("错误", str(e))
            finally:
                self.root.after(0, lambda: self.btn_moon.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _get_flour_count(self, enter_result):
        """从enterScene返回值获取面粉数量"""
        try:
            cur_record = enter_result.get("curRecord", {})
            if isinstance(cur_record, dict):
                items_bag = cur_record.get("itemsBag", {})
                if isinstance(items_bag, dict):
                    items = items_bag.get("items", [])
                    if isinstance(items, list):
                        for item in items:
                            if str(item.get("id", "")) == "143200010":
                                return item.get("count", 0)
        except Exception as e:
            self._log("[月宫厨房] 获取面粉数量异常: %s" % e)
        return 0

    def _get_autumn_num(self, entry):
        """从entry数据里获取月宫厨房已用次数"""
        try:
            record = entry.get("record", {})
            if isinstance(record, dict):
                return record.get("autumnNum", 0)
        except:
            pass
        return 0

    def _update_dice_display(self, dice_str, result_text):
        """更新骰子显示"""
        self.lbl_dice.config(text=dice_str)
        self.lbl_dice_result.config(text=result_text, foreground="orange")


    # ========== 神兽森林捕宠 ==========
    def _build_forest_tab(self):
        tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(tab, text="神兽森林")
        ttk.Label(tab, text="木灵葫芦捕捉神兽森林宠物；每次进入神兽森林尝试一次。",
                  font=("微软雅黑", 11, "bold")).pack(anchor="w", pady=(0, 10))
        options = ttk.LabelFrame(tab, text="捕捉设置", padding=10)
        options.pack(fill="x")
        self._forest_target_labels = {
            "%s / %s (%d)" % (names[0], names[1], pet_id): pet_id
            for pet_id, names in FOREST_PETS.items()
        }
        self.var_forest_target = tk.StringVar(value=next(iter(self._forest_target_labels)))
        ttk.Label(options, text="目标宠物").grid(row=1, column=0, padx=5, pady=5)
        ttk.Combobox(options, textvariable=self.var_forest_target, state="readonly", width=24,
                     values=tuple(self._forest_target_labels)).grid(
                         row=1, column=1, padx=5, sticky="w")
        self.var_forest_attempts = tk.IntVar(value=1)
        ttk.Label(options, text="尝试次数").grid(row=0, column=0, padx=5, pady=5)
        ttk.Spinbox(options, from_=1, to=100, textvariable=self.var_forest_attempts, width=7).grid(
            row=0, column=1, padx=5)
        self.var_forest_autobuy = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="葫芦不足时自动用灵魂购买", variable=self.var_forest_autobuy).grid(
            row=0, column=2, padx=12, sticky="w")
        self.var_forest_buy_limit = tk.IntVar(value=0)
        ttk.Label(options, text="最多购买").grid(row=0, column=3, padx=5)
        ttk.Spinbox(options, from_=0, to=100, textvariable=self.var_forest_buy_limit, width=7).grid(
            row=0, column=4, padx=5)
        ttk.Label(options, text="个（4000 灵魂/个）").grid(row=0, column=5, padx=5)
        self.var_forest_unlimited = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="持续捕捉，直到达标或手动停止", variable=self.var_forest_unlimited).grid(
            row=1, column=2, columnspan=4, padx=12, sticky="w")
        filters = ttk.LabelFrame(tab, text="筛选条件（填 0 表示不限）", padding=8)
        filters.pack(fill="x", pady=6)
        self.var_forest_filter = tk.BooleanVar(value=False)
        self.var_forest_baby = tk.BooleanVar(value=True)
        ttk.Checkbutton(filters, text="启用筛选；不达标自动放生", variable=self.var_forest_filter).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=5, pady=4)
        ttk.Checkbutton(filters, text="只保留宝宝", variable=self.var_forest_baby).grid(
            row=0, column=3, columnspan=2, sticky="w", padx=5)
        self.var_forest_minimums = {}
        for index, (label, field) in enumerate((
            ("潜力", "capacity"), ("根骨", "bone"), ("灵力", "wakan"),
            ("生命资质", "hpQualification"), ("攻击资质", "atkQualification"),
            ("防御资质", "defQualification"))):
            variable = tk.IntVar(value=0)
            self.var_forest_minimums[field] = variable
            row, column = 1 + index // 3, (index % 3) * 2
            ttk.Label(filters, text=label).grid(row=row, column=column, padx=5, pady=4, sticky="e")
            ttk.Spinbox(filters, from_=0, to=9999, textvariable=variable, width=7).grid(
                row=row, column=column + 1, padx=5, sticky="w")
        actions = ttk.Frame(tab)
        actions.pack(fill="x", pady=10)
        self.btn_forest_run = ttk.Button(actions, text="开始捕捉", command=self._forest_run, state="disabled")
        self.btn_forest_run.pack(side="left", padx=4)
        self.btn_forest_stop = ttk.Button(actions, text="停止（完成当前次）", command=self._forest_stop,
                                          state="disabled")
        self.btn_forest_stop.pack(side="left", padx=4)
        self.lbl_forest_status = ttk.Label(tab, text="登录并选择存档后可使用", foreground="gray")
        self.lbl_forest_status.pack(anchor="w", pady=5)
        result_frame = ttk.LabelFrame(tab, text="本轮捕获结果", padding=6)
        result_frame.pack(fill="both", expand=True, pady=8)
        self.tree_forest_result = ttk.Treeview(
            result_frame, columns=("attempt", "target", "result", "kind", "talent", "qualification", "entity"),
            show="headings", height=7)
        for key, title, width in (
            ("attempt", "第几次", 65), ("target", "目标宠物", 160),
            ("result", "结果", 110), ("kind", "类型", 65),
            ("talent", "天赋（潜力/根骨/灵力）", 265),
            ("qualification", "资质（生命/攻击/防御）", 300),
            ("entity", "宠物实例", 125)):
            self.tree_forest_result.heading(key, text=title)
            self.tree_forest_result.column(key, width=width, anchor="center")
        self.tree_forest_result.pack(fill="both", expand=True)
        ttk.Label(tab, text="木灵葫芦有失败概率；默认不购买。购买只使用灵魂，不使用点券。",
                  foreground="#666").pack(anchor="w")

    def _forest_describe_pet(self, pet):
        if not hasattr(self, "_forest_pet_configs"):
            with open(os.path.join(CONFIG_DIR, "132___Pet.xml.json"), encoding="utf-8") as file:
                records = _config_records(json.load(file))
            self._forest_pet_configs = {str(row.get("id")): row for row in records}
        config = self._forest_pet_configs.get(str(pet.get("id"))) or {}
        pet_type = int(config.get("type", -1))
        kind = {0: "普通", 1: "宝宝"}.get(pet_type, "未知")
        talents = []
        for label, field, maximum in (
            ("潜力", "capacity", "capacityMax"),
            ("根骨", "bone", "boneMax"),
            ("灵力", "wakan", "wakanMax")):
            talents.append("%s %s/%s" % (label, pet.get(field, "?"), config.get(maximum, "?")))
        qualifications = []
        for label, field in (("生命", "hpQualification"), ("攻击", "atkQualification"),
                             ("防御", "defQualification")):
            bounds = str(config.get(field, "")).split(";")
            maximum = bounds[1] if len(bounds) > 1 else "?"
            qualifications.append("%s %s/%s" % (label, pet.get(field, "?"), maximum))
        return kind, "；".join(talents), "；".join(qualifications)

    def _forest_stop(self):
        self._forest_stop_event.set()
        self._log("[神兽森林] 已请求停止，当前次结束后停止")

    def _forest_run(self):
        if not self._ensure_login():
            return
        try:
            attempts = int(self.var_forest_attempts.get())
            buy_limit = int(self.var_forest_buy_limit.get())
            minimums = {field: int(variable.get()) for field, variable in self.var_forest_minimums.items()}
        except (ValueError, tk.TclError):
            messagebox.showwarning("神兽森林", "请填写有效的尝试次数、购买上限和筛选数值")
            return
        if not 1 <= attempts <= 100 or not 0 <= buy_limit <= 100 or any(
                value < 0 or value > 9999 for value in minimums.values()):
            messagebox.showwarning("神兽森林", "尝试次数为 1～100，最多购买为 0～100，筛选数值为 0～9999")
            return
        auto_buy = bool(self.var_forest_autobuy.get())
        target_id = self._forest_target_labels.get(self.var_forest_target.get())
        if target_id is None:
            messagebox.showwarning("神兽森林", "请选择目标宠物")
            return
        filtering = bool(self.var_forest_filter.get())
        unlimited = bool(self.var_forest_unlimited.get())
        if unlimited and not filtering:
            messagebox.showwarning("神兽森林", "持续捕捉需要启用筛选，以便达标后自动停止")
            return
        if auto_buy and buy_limit:
            if not messagebox.askyesno("确认购买上限", "最多购买 %d 个木灵葫芦，合计最多消耗 %d 灵魂。继续吗？" %
                                       (buy_limit, buy_limit * 4000)):
                return
        self._forest_stop_event.clear()
        for row in self.tree_forest_result.get_children():
            self.tree_forest_result.delete(row)
        self.btn_forest_run.config(state="disabled")
        self.btn_forest_stop.config(state="normal")
        save_index = self.current_save["index"]
        threading.Thread(target=self._forest_worker,
                         args=(save_index, attempts, auto_buy, buy_limit, target_id,
                               filtering, bool(self.var_forest_baby.get()), minimums, unlimited),
                         daemon=True).start()

    def _forest_worker(self, save_index, attempts, auto_buy, buy_limit, target_id,
                       filtering, baby_only, minimums, unlimited):
        caught = failed = bought = released = 0
        target_name = "%s / %s" % FOREST_PETS[target_id]
        flow = None
        gem_balance = None
        try:
            attempt = 0
            while unlimited or attempt < attempts:
                if self._forest_stop_event.is_set():
                    break
                attempt += 1
                flow, entry, scene = self._connect_and_enter(save_index)
                record = scene.get("curRecord") or entry.get("record") or {}
                items = (record.get("itemsBag") or {}).get("items") or []
                if isinstance(items, dict):
                    items = list(items.values())
                gourds = sum(int(item.get("count") or 0) for item in items
                             if str(item.get("id")) == "156100001")
                if gourds == 0:
                    if not auto_buy or bought >= buy_limit:
                        self._log("[神兽森林] 木灵葫芦不足，停止")
                        break
                    spirit = int(record.get("spirit") or 0)
                    if spirit < 4000:
                        self._log("[神兽森林] 灵魂不足 4000，停止")
                        break
                    purchase = flow.request("scene.itemHandler.generalShop",
                                            {"goodsId": 11, "type": 0, "num": 1}, timeout=15)
                    if purchase.get("code") != 200 or str(purchase.get("itemId")) != "156100001":
                        raise RuntimeError("购买木灵葫芦失败：%s" % purchase.get("error", purchase.get("code")))
                    if int(purchase.get("spirit", -1)) != spirit - 4000:
                        raise RuntimeError("购买后的灵魂余额不符合预期，已停止")
                    bought += 1
                    if gem_balance is not None and purchase.get("gem") != gem_balance:
                        raise RuntimeError("点券余额发生变化，已停止")
                    gem_balance = purchase.get("gem")
                    self._log("[神兽森林] 灵魂购买木灵葫芦 1 个，剩余灵魂 %d" % purchase["spirit"])
                created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                       {"mid": 2021, "costGem": 0}, timeout=20)
                if created.get("code") != 200:
                    raise RuntimeError("进入神兽森林失败：%s" % created.get("error", created.get("code")))
                if gem_balance is not None and created.get("gem") != gem_balance:
                    raise RuntimeError("点券余额发生变化，已停止")
                gem_balance = created.get("gem")
                result = flow.request("scene.animalHandler.catchPet",
                                      {"cType": 2, "copyId": 2021, "itemId": 156100001, "pId": target_id},
                                      timeout=15)
                if result.get("code") != 200 or str(result.get("itemId")) != "156100001":
                    raise RuntimeError("捕捉请求失败：%s" % result.get("error", result.get("code")))
                passes = False
                if result.get("pet"):
                    caught += 1
                    pet = result["pet"]
                    kind, talents, qualifications = self._forest_describe_pet(pet)
                    passes = not filtering or ((not baby_only or kind == "宝宝") and all(
                        int(pet.get(field) or 0) >= minimum for field, minimum in minimums.items()))
                    outcome = "达标保留" if filtering and passes else "成功"
                    if filtering and not passes:
                        entity_id = pet.get("entityId")
                        if not entity_id:
                            raise RuntimeError("新宠物缺少实例 ID，已停止，未放生")
                        freed = flow.request("scene.animalHandler.freePet",
                                             {"entityId": entity_id}, timeout=15)
                        if freed.get("code") != 200 or freed.get("entityId") != entity_id:
                            raise RuntimeError("放生未确认成功，已停止：%s" %
                                               freed.get("error", freed.get("code")))
                        released += 1
                        outcome = "未达标放生"
                    pet_name = FOREST_PETS[target_id][1] if str(pet.get("id")) in (
                        str(target_id + 10), str(target_id + 11)) else FOREST_PETS[target_id][0]
                    self._log("[神兽森林] 第%d次%s：%s，%s (%s)，%s；%s" %
                              (attempt, outcome, kind, pet_name, pet.get("id"),
                               talents, qualifications))
                    values = (attempt, target_name, outcome, kind, talents, qualifications,
                              pet.get("entityId", ""))
                    self.root.after(0, lambda values=values: self.tree_forest_result.insert(
                        "", "end", values=values))
                else:
                    failed += 1
                    self._log("[神兽森林] 第%d次未捕捉到宠物，已消耗葫芦" % attempt)
                    self.root.after(0, lambda attempt=attempt: self.tree_forest_result.insert(
                        "", "end", values=(attempt, target_name, "未捕获", "", "", "", "")))
                flow.disconnect()
                flow = None
                total = "持续" if unlimited else str(attempts)
                status = "已尝试 %d/%s，捕获 %d，放生 %d，失败 %d，购买 %d" % (
                    attempt, total, caught, released, failed, bought)
                self.root.after(0, lambda status=status: self.lbl_forest_status.config(
                    text=status, foreground="green"))
                if filtering and passes:
                    break
            if flow:
                flow.disconnect()
                flow = None
            flow, entry, scene = self._connect_and_enter(save_index)
            record = scene.get("curRecord") or entry.get("record") or {}
            pet_list = record.get("petList") or {}
            pets = pet_list.get("pets") or [] if isinstance(pet_list, dict) else pet_list
            self._log("[神兽森林] 重登核对：宠物栏 %d 只，剩余灵魂 %s" %
                      (len(pets), record.get("spirit")))
        except Exception as exc:
            self._log("[神兽森林] 停止：%s" % exc)
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self.btn_forest_run.config(state="normal"))
            self.root.after(0, lambda: self.btn_forest_stop.config(state="disabled"))

    # ========== 造梦寻宝 ==========
    def _build_treasure_tab(self):
        tab = self._daily2_page("造梦寻宝", padding=12)
        ttk.Label(tab, text="按免费冷却逐个开箱，间隔至少3.5秒；获得迷宫宝箱后自动停止。", foreground="#333").pack(anchor="w", pady=5)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=8)
        self.btn_treasure_check = ttk.Button(buttons, text="读取寻宝状态", command=self._treasure_check, state="disabled")
        self.btn_treasure_check.pack(side="left", padx=4)
        self.btn_treasure_run = ttk.Button(buttons, text="自动寻宝", command=self._treasure_run, state="disabled")
        self.btn_treasure_run.pack(side="left", padx=4)
        self.lbl_treasure_status = ttk.Label(tab, text="登录并选择存档后读取状态", foreground="gray")
        self.lbl_treasure_status.pack(anchor="w", pady=6)
        ttk.Label(tab, text="背包无空位、已获得宝箱或开满 8 次时自动停止；不清除冷却，不花点券。",
                  foreground="#666").pack(anchor="w", pady=4)

    @staticmethod
    def _treasure_state(entry, scene):
        record = scene.get("curRecord") or entry.get("record") or {}
        info = record.get("treasureInfo") or entry.get("record", {}).get("treasureInfo") or {}
        bag = record.get("itemsBag") or {}
        items = bag.get("items") or []
        return info, bag, items

    def _treasure_status_text(self, info, bag, items):
        opened = info.get("openNum") or []
        return "已开 %d/8 箱：%s  |  背包 %d/%s  |  %s" % (
            len(opened), ", ".join(map(str, opened)) or "无", len(items),
            bag.get("itemCount", "?"), "已找到迷宫宝箱" if info.get("itemId") else "尚未找到")

    def _treasure_check(self):
        if not self._ensure_login():
            return
        self.btn_treasure_check.config(state="disabled")
        save_index = self.current_save["index"]

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(save_index)
                info, bag, items = self._treasure_state(entry, scene)
                status = self._treasure_status_text(info, bag, items)
                self.root.after(0, lambda status=status: self.lbl_treasure_status.config(text=status, foreground="green"))
                self._log("[造梦寻宝] " + status)
            except Exception as exc:
                self._log("[造梦寻宝] 读取失败：%s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_treasure_check.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _treasure_run(self):
        if not self._ensure_login():
            return
        self.btn_treasure_run.config(state="disabled")
        self.btn_treasure_check.config(state="disabled")
        save_index = self.current_save["index"]

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(save_index)
                info, bag, items = self._treasure_state(entry, scene)
                capacity = int(bag.get("itemCount") or 0)
                if not info or not capacity:
                    raise RuntimeError("未读到寻宝状态或背包容量，已停止")
                if len(items) >= capacity:
                    self._log("[造梦寻宝] 背包已满，请先腾出空位")
                    return
                opened = {int(x) for x in (info.get("openNum") or [])}
                open_times = getattr(self, "_treasure_open_times", None)
                if open_times is None:
                    open_times = self._treasure_open_times = {}
                cooldown_until = (time.monotonic() + max(0, float(info["cdTime"]) / 1000)
                                  if info.get("cdTime") is not None and float(info["cdTime"]) >= 0
                                  else None)
                self._log("[造梦寻宝] 开始：%s；每次回包后至少间隔3.5秒" % self._treasure_status_text(info, bag, items))
                while not info.get("itemId") and len(opened) < 8:
                    now = time.monotonic()
                    server_wait = (cooldown_until - now if cooldown_until is not None else
                                   (int(info.get("nextTime") or 0) - time.time() * 1000) / 1000)
                    interval_wait = open_times.get(save_index, now - 3.5) + 3.5 - now
                    wait = max(0, server_wait + 0.3, interval_wait)
                    if wait > 30:
                        self._log("[造梦寻宝] 剩余冷却约 %.0f 秒，请稍后重试" % wait)
                        break
                    if wait:
                        time.sleep(wait)
                    box = next(i for i in range(1, 9) if i not in opened)
                    # Record even failed/ambiguous attempts; never immediately retry a box.
                    open_times[save_index] = time.monotonic()
                    try:
                        result = flow.request("scene.playerSecondHandler.getTreasures", {"openNum": box}, timeout=15)
                    finally:
                        open_times[save_index] = time.monotonic()
                    cooldown_until = (time.monotonic() + max(0, float(result["cdTime"]) / 1000)
                                      if result.get("cdTime") is not None and float(result["cdTime"]) >= 0
                                      else None)
                    if result.get("code") != 200 or not result.get("openNum"):
                        self._log("[造梦寻宝] %d 号箱开启失败：%s" % (box, result.get("error", result.get("code"))))
                        break
                    info.update(result)
                    opened = {int(x) for x in info["openNum"]}
                    self._log("[造梦寻宝] 第 %d 次，%d 号箱：%s" % (
                        len(opened), box, "获得迷宫宝箱" if info.get("itemId") else "空箱"))
                flow.disconnect()
                flow = None
                flow, entry, scene = self._connect_and_enter(save_index)
                info, bag, items = self._treasure_state(entry, scene)
                found = [item for item in (items.values() if isinstance(items, dict) else items)
                         if str(item.get("id")) == "197100003"]
                status = self._treasure_status_text(info, bag, items)
                self.root.after(0, lambda status=status: self.lbl_treasure_status.config(text=status, foreground="green"))
                self._log("[造梦寻宝] 重登核对：%s；背包迷宫宝箱：%s" % (
                    status, found[0].get("count") if found else "未查到"))
            except Exception as exc:
                self._log("[造梦寻宝] 异常：%s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_treasure_run.config(state="normal"))
                self.root.after(0, lambda: self.btn_treasure_check.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ========== 4399 冒险：在线领骰子 / 单次投掷 ==========
    def _build_dice_online_tab(self):
        tab = self._daily2_page("4399冒险", padding=12)
        ttk.Label(tab, text="保持协议连接累计在线时间，免费领取骰子。每 3 分钟开放一档，共 6 档。",
                  foreground="#333").pack(anchor="w", pady=5)
        buttons = ttk.Frame(tab)
        buttons.pack(fill="x", pady=8)
        self.btn_dice_check = ttk.Button(buttons, text="读取在线状态", command=self._dice_check, state="disabled")
        self.btn_dice_check.pack(side="left", padx=4)
        self.btn_dice_start = ttk.Button(buttons, text="挂机领骰子", command=self._dice_start, state="disabled")
        self.btn_dice_start.pack(side="left", padx=4)
        self.btn_dice_stop = ttk.Button(buttons, text="停止挂机", command=self._dice_stop, state="disabled")
        self.btn_dice_stop.pack(side="left", padx=4)
        self.btn_dice_roll = ttk.Button(buttons, text="投一次骰子", command=self._dice_roll, state="disabled")
        self.btn_dice_roll.pack(side="left", padx=4)
        self.lbl_dice_online = ttk.Label(tab, text="登录并选择存档后读取状态", foreground="gray")
        self.lbl_dice_online.pack(anchor="w", pady=6)
        ttk.Label(tab, text="挂机期间保持工具箱打开；不会提前领取、自动投骰子或花点券。",
                  foreground="#666").pack(anchor="w", pady=4)

    @staticmethod
    def _dice_item_count(record):
        items = (record.get("itemsBag") or {}).get("items") or []
        if isinstance(items, dict):
            items = items.values()
        return sum(int(item.get("count") or 0) for item in items
                   if str(item.get("id")) == "143200006")

    @staticmethod
    def _dice_online_status(info, count=None):
        grid = info.get("gridInfo") or {}
        claimed = grid.get("gridIds") or {}
        seconds = int(grid.get("time") or 0)
        result = "在线 %d分%02d秒；已领 %d/6 档" % (
            seconds // 60, seconds % 60,
            sum(bool(claimed.get(str(i))) for i in range(11, 17)))
        if count is not None:
            result += "；背包骰子 %d 个" % count
        return result

    def _dice_check(self):
        if not self._ensure_login():
            return
        self.btn_dice_check.config(state="disabled")
        save_index = self.current_save["index"]

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(save_index)
                record = scene.get("curRecord") or entry.get("record") or {}
                info = flow.request("scene.holidayHandler.getGridActiveInfoNew", {"gridKey": 4399}, timeout=15)
                if info.get("code") != 200:
                    raise RuntimeError(info.get("error", info.get("code")))
                status = self._dice_online_status(info, self._dice_item_count(record))
                self.root.after(0, lambda status=status: self.lbl_dice_online.config(text=status, foreground="green"))
                self._log("[4399冒险] " + status)
            except Exception as exc:
                self._log("[4399冒险] 读取失败：%s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_dice_check.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _dice_stop(self):
        self._dice_stop_event.set()
        self._log("[4399冒险] 已请求停止，当前请求结束后断开连接")

    def _dice_start(self):
        if not self._ensure_login():
            return
        self._dice_stop_event.clear()
        self.btn_dice_start.config(state="disabled")
        self.btn_dice_check.config(state="disabled")
        self.btn_dice_roll.config(state="disabled")
        self.btn_dice_stop.config(state="normal")
        save_index = self.current_save["index"]

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(save_index)
                record = scene.get("curRecord") or entry.get("record") or {}
                bag = record.get("itemsBag") or {}
                capacity = int(bag.get("itemCount") or 0)
                items = bag.get("items") or []
                if not capacity or len(items) >= capacity:
                    raise RuntimeError("背包已满或容量未知，请先腾出空位")
                dice_count = self._dice_item_count(record)
                self._log("[4399冒险] 槽%d开始协议挂机，当前骰子 %d 个" % (save_index, dice_count))
                while not self._dice_stop_event.is_set():
                    info = flow.request("scene.holidayHandler.getGridActiveInfoNew", {"gridKey": 4399}, timeout=15)
                    if info.get("code") != 200:
                        raise RuntimeError("读取在线状态失败：%s" % info.get("error", info.get("code")))
                    grid = info.get("gridInfo") or {}
                    claimed = grid.get("gridIds") or {}
                    seconds = int(grid.get("time") or 0)
                    status = self._dice_online_status(info, dice_count)
                    self.root.after(0, lambda status=status: self.lbl_dice_online.config(text=status, foreground="green"))
                    if all(claimed.get(str(i)) for i in range(11, 17)):
                        self._log("[4399冒险] 今日 6 档骰子已全部领取")
                        break
                    due = [i for i in range(11, 17)
                           if seconds >= (i - 11) * 180 and not claimed.get(str(i))]
                    if due:
                        reward = flow.request("scene.holidayHandler.getGridActiveItemNew", {"isAll": 0}, timeout=15)
                        if reward.get("code") != 200 or reward.get("itemId") != 143200006:
                            raise RuntimeError("免费领取失败：%s" % reward.get("error", reward.get("code")))
                        dice_count += int(reward.get("itemNum") or 0)
                        self._log("[4399冒险] 免费领取骰子 %d 个，背包预计 %d 个" % (
                            int(reward.get("itemNum") or 0), dice_count))
                        continue
                    if self._dice_stop_event.wait(10):
                        break
                self._log("[4399冒险] 挂机结束")
            except Exception as exc:
                self._log("[4399冒险] 挂机停止：%s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_dice_stop.config(state="disabled"))
                self.root.after(0, lambda: self.btn_dice_start.config(state="normal"))
                self.root.after(0, lambda: self.btn_dice_check.config(state="normal"))
                self.root.after(0, lambda: self.btn_dice_roll.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _dice_roll(self):
        if not self._ensure_login():
            return
        self.btn_dice_roll.config(state="disabled")
        save_index = self.current_save["index"]

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(save_index)
                record = scene.get("curRecord") or entry.get("record") or {}
                if self._dice_item_count(record) < 1:
                    raise RuntimeError("背包没有 4399 冒险骰子")
                result = flow.request("scene.holidayHandler.goGrid", {"gridKey": 4399}, timeout=15)
                if result.get("code") != 200:
                    raise RuntimeError(result.get("error", result.get("code")))
                self._log("[4399冒险] 投掷一次成功：%s" % json.dumps(result, ensure_ascii=False))
                info = flow.request("scene.holidayHandler.getGridActiveInfoNew", {"gridKey": 4399}, timeout=15)
                status = self._dice_online_status(info, self._dice_item_count(record) - 1)
                self.root.after(0, lambda status=status: self.lbl_dice_online.config(text=status, foreground="green"))
            except Exception as exc:
                self._log("[4399冒险] 投骰失败：%s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_dice_roll.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    # ========== 日常助手标签页 ==========
    def _build_gamebox_sign_info(self, parent):
        import webbrowser

        ttk.Label(parent, text="4399游戏盒 · 页游签到礼包",
                  font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(0, 10))
        ttk.Label(parent, text="当前状态：实验发包模块已接入，尚未验证签到成功", foreground="#a33",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor="w", pady=5)
        from gamebox_sign import build_panel as build_gamebox_panel
        build_gamebox_panel(self, parent)
        sections = (
            ("使用方式", "请在真实安卓手机的官方4399游戏盒中登录，搜索91122，"
             "进入造梦西游online洪荒大劫篇活动，按页面规则操作。"
             "电脑浏览器打开官网仅用于查看或下载游戏盒。"),
            ("与群组签到的区别", "本页说明的是游戏盒页游签到礼包活动。"
             "旁边的群组签到属于另一项功能，签到状态和奖励不能相互替代。"),
            ("已有测试结果（2026-10-20）", "实验中曾读取到App登录凭证，"
             "并完成只读接口查询；免费签到请求被服务器以“涉嫌违规参与活动”拒绝。"
             "尚未取得签到成功或签到天数增加的证据。"),
            ("活动限制", "官方回复将虚拟设备列为违规参与情形。"
             "只读查询成功不代表通过签到资格检查。若出现活动受限提示，"
             "请停止重试，按App中的立即反馈或客服指引申请复查；解除时间以官方为准。"),
        )
        for title, body in sections:
            box = ttk.LabelFrame(parent, text=title, padding=10)
            box.pack(fill="x", pady=6)
            ttk.Label(box, text=body, wraplength=600, justify="left").pack(anchor="w")
        ttk.Button(parent, text="打开4399游戏盒官网",
                   command=lambda: webbrowser.open("https://app.4399.cn/")).pack(
                       anchor="w", pady=10)
        def open_gamebox_review():
            from gamebox_review import show_review
            show_review(self)

        ttk.Button(parent, text="点击查看：发送返回消息、错误流程及截图",
                   command=open_gamebox_review).pack(anchor="w", pady=(0, 10))
        def open_gamebox_scripts():
            from gamebox_review import show_script_index
            show_script_index(self)

        ttk.Button(parent, text="查找历史Python发包文件（不执行）",
                   command=open_gamebox_scripts).pack(anchor="w", pady=(0, 10))

    def _build_daily_tab(self):
        self.var_daily_forum = tk.BooleanVar(value=True)
        group = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(group, text="日常助手")
        self.daily_notebook = ttk.Notebook(group)
        self.daily_notebook.pack(fill="both", expand=True)
        page = ttk.Frame(self.daily_notebook)
        self.daily_notebook.add(page, text="一键日常")
        fulushou_page = ttk.Frame(self.daily_notebook, padding=10)
        self.daily_notebook.add(fulushou_page, text="福禄寿190")
        gift_page = ttk.Frame(self.daily_notebook, padding=10)
        self.daily_notebook.add(gift_page, text="三日福利")
        from forum_daily import build_panel as build_forum_panel
        forum_page = ttk.Frame(self.daily_notebook)
        self.daily_notebook.add(forum_page, text="群组签到")
        build_forum_panel(self, forum_page)
        gamebox_page = self._scroll_notebook_page(
            self.daily_notebook, "游戏盒签到（实验）")
        self._build_gamebox_sign_info(gamebox_page)
        garden_page = self._scroll_notebook_page(self.daily_notebook, "联盟药园")
        from league_garden import build_panel as build_garden_panel
        build_garden_panel(self, garden_page)
        welfare_page = self._scroll_notebook_page(self.daily_notebook, "联盟Buff")
        from league_welfare import build_panel as build_welfare_panel
        build_welfare_panel(self, welfare_page)
        inventory_page = self._scroll_notebook_page(self.daily_notebook, "背包/仓库")
        from inventory_warehouse import build_panel as build_inventory_panel
        build_inventory_panel(self, inventory_page)
        xumi_page = ttk.Frame(self.daily_notebook)
        self.daily_notebook.add(xumi_page, text="须弥山城东/南/北")
        from xumi_daily import build_panel as build_xumi_daily
        build_xumi_daily(self, xumi_page)
        page.rowconfigure(0, weight=1)
        page.columnconfigure(0, weight=1)
        canvas = tk.Canvas(page, highlightthickness=0, borderwidth=0)
        vertical = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        horizontal = ttk.Scrollbar(page, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        tab = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=tab, anchor="nw")

        def resize_daily(event=None):
            canvas.itemconfigure(window, width=max(canvas.winfo_width(), tab.winfo_reqwidth()))
            canvas.configure(scrollregion=canvas.bbox("all"))

        def scroll_daily(event):
            widget = event.widget
            while widget is not None and widget != page:
                widget = getattr(widget, "master", None)
            if widget != page:
                return
            if event.delta:
                steps = -int(event.delta / 120) or (-1 if event.delta > 0 else 1)
                canvas.yview_scroll(steps, "units")
                return "break"

        tab.bind("<Configure>", resize_daily)
        canvas.bind("<Configure>", resize_daily)
        self.root.bind("<MouseWheel>", scroll_daily, add="+")

        # 一键日常按钮区
        action_frame = ttk.LabelFrame(tab, text="一键日常（不消耗点券）", padding=10)
        action_frame.pack(fill="x", pady=5)

        self.var_daily_liveness = tk.BooleanVar(value=True)
        self.var_daily_vip = tk.BooleanVar(value=True)
        self.var_daily_union = tk.BooleanVar(value=True)
        self.var_daily_mail = tk.BooleanVar(value=True)
        self.var_daily_yanwu = tk.BooleanVar(value=True)
        self.var_daily_teacher = tk.BooleanVar(value=True)
        self.var_daily_secret_shop = tk.BooleanVar(value=True)
        self.var_daily_arena = tk.BooleanVar(value=True)
        self.var_daily_petarena = tk.BooleanVar(value=True)
        from daily_liveness import build_tab
        build_tab(self)
        from material_collect import build_tab as build_material_collect
        build_material_collect(self)
        from daily_secret_shop import build_tab as build_secret_shop
        build_secret_shop(self)
        from shop_purchase import build_tab as build_shop_purchase
        build_shop_purchase(self)
        from arena_daily import build_tabs
        build_tabs(self)

        ttk.Checkbutton(action_frame, text="活跃奖励", variable=self.var_daily_liveness).grid(row=0, column=0, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="VIP每日礼包", variable=self.var_daily_vip).grid(row=0, column=1, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="联盟灵气贡献", variable=self.var_daily_union).grid(row=0, column=2, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="领取邮件奖励", variable=self.var_daily_mail).grid(row=1, column=0, sticky="w", padx=5, pady=3)

        ttk.Checkbutton(action_frame, text="演武堂点赞", variable=self.var_daily_yanwu).grid(row=1, column=1, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="造四群组签到", variable=self.var_daily_forum).grid(row=1, column=2, sticky="w", padx=5, pady=3)

        ttk.Checkbutton(action_frame, text="师徒每日学艺（1000灵魂）", variable=self.var_daily_teacher).grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="神秘商店（消耗灵魂）", variable=self.var_daily_secret_shop).grid(row=2, column=2, sticky="w", padx=5, pady=3)

        ttk.Checkbutton(action_frame, text="竞技场", variable=self.var_daily_arena).grid(row=3, column=0, sticky="w", padx=5, pady=3)
        ttk.Checkbutton(action_frame, text="斗宠大会", variable=self.var_daily_petarena).grid(row=3, column=1, sticky="w", padx=5, pady=3)

        self.btn_daily_run = ttk.Button(action_frame, text="开始一键日常", command=self._do_daily, state="disabled")
        self.btn_daily_run.grid(row=0, column=3, rowspan=4, padx=15)

        ttk.Label(action_frame, text="⚠ 全部不消耗点券", foreground="green").grid(row=0, column=4, rowspan=4, padx=10)

        # 状态显示区
        status_frame = ttk.LabelFrame(tab, text="当前状态", padding=8)
        status_frame.pack(fill="x", pady=5)

        self.lbl_daily_status = ttk.Label(status_frame, text="登录并选择存档后可使用", foreground="gray")
        self.lbl_daily_status.pack(anchor="w")

        fulushou_frame = ttk.LabelFrame(fulushou_page, text="福禄寿190", padding=10)
        fulushou_frame.pack(fill="x", pady=5)
        self._build_fulushou_panel(fulushou_frame)

        # 三日福利（活动451 周末双倍）
        gift_frame = ttk.LabelFrame(gift_page, text="三日福利（周末双倍 451）", padding=10)
        gift_frame.pack(fill="x", pady=(0, 10))
        self.lbl_timeboat_gift = ttk.Label(gift_frame, text="状态: 待检测", wraplength=160)
        self.lbl_timeboat_gift.pack(pady=5)
        ttk.Button(gift_frame, text="刷新福利状态", command=self._do_timeboat_check).pack(fill="x", pady=5)
        self.btn_timeboat_gift = ttk.Button(gift_frame, text="领取三日福利", command=self._do_timeboat_gift)
        self.btn_timeboat_gift.pack(fill="x", pady=5)
        ttk.Label(gift_frame, text="周五~周日可领；活动451，走 rewardGiftByFree", foreground="gray", wraplength=160).pack(pady=(0, 5))


        # 说明区
        info_frame = ttk.LabelFrame(tab, text="功能说明", padding=8)
        info_frame.pack(fill="both", expand=True, pady=5)

        info_text = (
            "勾选需要执行的项目，再点击“开始一键日常”。\n"
            "群组签到：先尝试一键接口，等级不足走网页签到；未加入时在群组签到子标签中加入。\n"
            "邮件奖励：领取带附件邮件，领取成功会同时移除邮件；纯文字邮件保留。\n"
            "活跃奖励、神秘商店、竞技场、斗宠大会的开关已统一放在上方，次数和打法在各自子标签设置。\n"
            "活跃奖励勾选后会在一键日常最后重新读取状态并领取。\n"
            "竞技场、斗宠大会是否参与、挑战次数和挑战方式，在各自子标签中设置。\n"
            "演武堂点赞：读取各角色榜首，自动赠送一次免费爱心并接收奖励。\n"
            "神秘商店次数按VIP自动判断，购买消耗灵魂。\n"
            "师徒每日学艺：有师父且今日未学时执行，仅1000灵魂分支，不使用点券学艺。\n"
            "福禄寿190、三日福利在各自子标签中操作。\n"
            "竞技场和斗宠大会只使用免费次数，不购买额外次数。"
        )
        ttk.Label(info_frame, text=info_text, justify="left", foreground="#333", wraplength=680).pack(anchor="w")

    def _do_daily(self):
        if not self.client or self.current_save is None:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        forum_credentials = None
        if self.var_daily_forum.get():
            try:
                from forum_daily import capture_credentials
                forum_credentials = capture_credentials(self, require_same_account=True)
            except RuntimeError as error:
                self._log("[群组签到] 本轮跳过：%s" % error)
        self.btn_daily_run.config(state="disabled")
        save_index = self.current_save["index"]

        def worker():
            try:
                self._log("[日常助手] 开始: 槽%d %s" % (self.current_save["index"], self.current_save["name"]))
                if forum_credentials is not None:
                    self._log("\n--- 造四群组签到 ---")
                    try:
                        from forum_daily import execute as execute_forum_daily
                        execute_forum_daily(self, forum_credentials)
                    except Exception as error:
                        message = str(error) if isinstance(error, RuntimeError) else type(error).__name__
                        self._log("[群组签到] 已停止：%s" % message)
                flow, entry, scene = self._connect_and_enter(save_index)
                cur = scene.get("curRecord", {})
                user = cur.get("user", {})

                if self.var_daily_mail.get():
                    self._log("\n--- 领取邮件奖励 ---")
                    try:
                        from daily_mail import claim_mail_rewards
                        claim_mail_rewards(flow, self._log)
                    except Exception as error:
                        self._log("  邮件奖励已停止：%s" % error)

                if self.var_daily_teacher.get():
                    try:
                        from daily_teacher import learn
                        learn(flow, entry, scene, self._log)
                    except Exception as error:
                        self._log("[师徒学艺] 已停止：%s" % error)

                if self.var_daily_yanwu.get():
                    try:
                        from daily_yanwu import give_love
                        give_love(flow, entry, scene, self._log)
                    except Exception as error:
                        self._log("[演武堂] 点赞停止：%s" % error)

                if self.var_daily_secret_shop.get():
                    try:
                        from daily_secret_shop import buy
                        buy(flow, scene, None, self._log, entry=entry)
                    except Exception as error:
                        self._log("[神秘商店] 已停止：%s" % error)

                # 2. VIP每日礼包
                if self.var_daily_vip.get():
                    self._log("\n--- VIP每日礼包 ---")
                    try:
                        r = flow.request("scene.vipHandler.getDailyReward", {}, timeout=15)
                        if r.get("code") == 200:
                            items = r.get("items", [])
                            power = r.get("collectPower", 0)
                            self._log("  领取成功! 获得: %s, 聚集力+%d" % (json.dumps(items, ensure_ascii=False), power))
                        else:
                            self._log("  领取失败: %s" % r.get("error"))
                    except Exception as e:
                        self._log("  VIP礼包异常: %s" % e)

                # 3. 联盟灵气贡献
                if self.var_daily_union.get():
                    self._log("\n--- 联盟灵气贡献 ---")
                    try:
                        r = flow.request("scene.leagueHandler.playerDevoteLeague", {"type": 1}, timeout=15)
                        if r.get("code") == 200:
                            total_spirit = r.get("totalSpirit", 0)
                            self._log("  贡献成功! 联盟总灵气: %s" % total_spirit)
                        else:
                            self._log("  贡献失败: %s" % r.get("error"))
                    except Exception as e:
                        self._log("  联盟贡献异常: %s" % e)

                from arena_daily import automatic
                for pet, enabled, title in (
                    (False, self.var_daily_arena.get(), "竞技场"),
                    (True, self.var_daily_petarena.get(), "斗宠大会"),
                ):
                    if enabled:
                        self._log("\n--- %s ---" % title)
                        try:
                            automatic(flow, cur, pet, self._log, mode=(self.var_petarena_mode if pet else self.var_arena_mode).get(), limit=(self.var_petarena_times if pet else self.var_arena_times).get(), top_n=(self.var_petarena_top_n if pet else self.var_arena_top_n).get(), target=((self.get_petarena_target if pet else self.get_arena_target)() if (self.var_petarena_mode if pet else self.var_arena_mode).get() == '指定对手（手动字段）' else None))
                        except Exception as error:
                            self._log("  %s停止: %s" % (title, error))

                flow.disconnect()
                if self.var_daily_liveness.get():
                    self._log("\n--- 日常收尾：活跃奖励 ---")
                    try:
                        from daily_liveness import execute
                        execute(self, save_index)
                    except Exception as error:
                        self._log("  活跃奖励异常：%s" % error)
                self._log("\n[日常助手] 完成!")
            except Exception as e:
                self._log("[日常助手] 异常: %s" % e)
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self.btn_daily_run.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()




    # ========== 日常任务：预读列表、选择接取、已验证路线自动完成 ==========
    def _build_daily_task_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="日常任务")
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "output_cg1_20260921_1_2")
        self._daily_task_defs = {}
        self._daily_task_equity = {}
        self._daily_task_vip_extra = {}
        self._daily_task_load_error = None
        try:
            with open(os.path.join(config_dir, "210___TaskType.xml.json"), "r", encoding="utf-8") as file:
                records = json.load(file).get("RECORD", [])
            for row in records:
                if isinstance(row, dict) and str(row.get("taskClass")) == "2":
                    self._daily_task_defs[int(row["id"])] = row
            with open(os.path.join(config_dir, "102___LevelEquity.xml.json"), "r", encoding="utf-8") as file:
                equity = json.load(file).get("RECORD", [])
            self._daily_task_equity = {int(row["id"]): int(row["dailyTaskNum"])
                                       for row in equity if isinstance(row, dict)}
            with open(os.path.join(config_dir, "236___VIP.xml.json"), encoding="utf-8") as file:
                vip_rows = json.load(file).get("RECORD", [])
            self._daily_task_vip_extra = {int(row["id"]): int(row["dailyTaskNum"])
                                          for row in vip_rows if isinstance(row, dict)}
        except (OSError, ValueError, KeyError) as exc:
            self._daily_task_load_error = str(exc)

        self._daily_task_snapshot = {}
        self._daily_task_batches = self._daily_task_batches_load()
        left = ttk.LabelFrame(tab, text="当前日常任务列表", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        filter_row = ttk.Frame(left)
        filter_row.pack(fill="x", pady=(0, 6))
        ttk.Label(filter_row, text="分类筛选").pack(side="left")
        self.var_daily_task_category = tk.StringVar(value="全部")
        category_box = ttk.Combobox(
            filter_row, textvariable=self.var_daily_task_category,
            values=("全部", "普通", "宠物", "噩梦", "其他"),
            state="readonly", width=10,
        )
        category_box.pack(side="left", padx=(6, 0))
        category_box.bind("<<ComboboxSelected>>", lambda event: self._daily_task_render_tree())
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_frame)
        scroll.pack(side="right", fill="y")
        self.daily_task_tree = ttk.Treeview(
            tree_frame, columns=("id", "name", "type", "state", "route"),
            show="headings", yscrollcommand=scroll.set, height=18,
        )
        scroll.config(command=self.daily_task_tree.yview)
        for column, title, width in (("id", "编号", 65), ("name", "任务", 180),
                                     ("type", "类别", 80), ("state", "状态", 100),
                                     ("route", "自动路线", 80)):
            self.daily_task_tree.heading(column, text=title)
            self.daily_task_tree.column(column, width=width, anchor="w")
        self.daily_task_tree.pack(side="left", fill="both", expand=True)
        self.daily_task_tree.bind("<<TreeviewSelect>>", self._daily_task_on_select)
        self._daily_task_render_tree()

        right = ttk.Frame(tab, width=270)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        initial_hint = ("配置读取失败：%s" % self._daily_task_load_error
                        if self._daily_task_load_error else "选择存档后自动读取任务")
        self.lbl_daily_task_quota = ttk.Label(right, text=initial_hint, foreground="blue",
                                               wraplength=250, justify="left")
        self.lbl_daily_task_quota.pack(anchor="w", pady=(0, 12))
        self.btn_daily_task_check = ttk.Button(right, text="刷新任务列表",
                                               command=self._do_daily_task_check, state="disabled")
        self.btn_daily_task_check.pack(fill="x", pady=3)
        self.btn_daily_task_batch1 = ttk.Button(
            right, text="任务批量接取1",
            command=lambda: self._daily_task_batch_accept(1), state="disabled")
        self.btn_daily_task_batch1.pack(fill="x", pady=3)
        self.btn_daily_task_batch2 = ttk.Button(
            right, text="任务批量接取2",
            command=lambda: self._daily_task_batch_accept(2), state="disabled")
        self.btn_daily_task_batch2.pack(fill="x", pady=3)
        self.btn_daily_task_batch3 = ttk.Button(
            right, text="任务批量接取3",
            command=lambda: self._daily_task_batch_accept(3), state="disabled")
        self.btn_daily_task_batch3.pack(fill="x", pady=3)
        save_row = ttk.Frame(right)
        save_row.pack(fill="x", pady=3)
        self.btn_daily_task_save1 = ttk.Button(
            save_row, text="存为批量1", width=8, state="disabled",
            command=lambda: self._daily_task_save_batch(1))
        self.btn_daily_task_save1.pack(side="left", expand=True, fill="x", padx=(0, 2))
        self.btn_daily_task_save2 = ttk.Button(
            save_row, text="存为批量2", width=8, state="disabled",
            command=lambda: self._daily_task_save_batch(2))
        self.btn_daily_task_save2.pack(side="left", expand=True, fill="x", padx=2)
        self.btn_daily_task_save3 = ttk.Button(
            save_row, text="存为批量3", width=8, state="disabled",
            command=lambda: self._daily_task_save_batch(3))
        self.btn_daily_task_save3.pack(side="left", expand=True, fill="x", padx=(2, 0))
        self.lbl_daily_task_batch = ttk.Label(
            right, text="批量任务：Ctrl/Shift 多选后保存到批量1、2或3。",
            foreground="gray", wraplength=250, justify="left")
        self.lbl_daily_task_batch.pack(anchor="w", pady=(0, 4))
        self.btn_daily_task_accept = ttk.Button(right, text="接取所选任务",
                                                command=lambda: self._daily_task_action("accept"),
                                                state="disabled")
        self.btn_daily_task_accept.pack(fill="x", pady=3)
        self.btn_daily_task_complete = ttk.Button(right, text="自动完成并领奖",
                                                  command=lambda: self._daily_task_action("complete"),
                                                  state="disabled")
        self.btn_daily_task_complete.pack(fill="x", pady=3)
        self.btn_daily_task_claim = ttk.Button(right, text="一键领取已完成任务",
                                               command=lambda: self._daily_task_action("claim"),
                                               state="disabled")
        self.btn_daily_task_claim.pack(fill="x", pady=3)
        self.lbl_daily_task_detail = ttk.Label(right, text="选中任务可查看前置条件和路线。",
                                                wraplength=250, justify="left")
        self.lbl_daily_task_detail.pack(anchor="w", pady=(16, 10))
        ttk.Label(right, text="自动完成仅开放已实测路线。接取会占用当日日常任务次数；通关不使用点券。",
                  wraplength=250, justify="left", foreground="gray").pack(anchor="w")

    def _daily_task_render_tree(self):
        selected = list(self.daily_task_tree.selection())
        self.daily_task_tree.delete(*self.daily_task_tree.get_children())
        category = {"0": "噩梦", "1": "宠物", "2": "普通"}
        kind_order = {"普通": 0, "宠物": 1, "噩梦": 2, "其他": 3}
        wanted = self.var_daily_task_category.get()
        states = self._daily_task_snapshot.get("states", {})
        rows = []
        for task_id, row in self._daily_task_defs.items():
            kind = category.get(str(row.get("dailyTaskType")), "其他")
            if wanted != "全部" and kind != wanted:
                continue
            rows.append((kind_order.get(kind, 3), task_id, kind, row))
        for _, task_id, kind, row in sorted(rows, key=lambda item: (item[0], item[1])):
            route = "已实测" if task_id in DAILY_TASK_TESTED_ROUTES else "待验证"
            self.daily_task_tree.insert(
                "", "end", iid=str(task_id),
                values=(task_id, row.get("name", "?"), kind,
                        states.get(task_id, "待读取"), route))
        for iid in selected:
            if self.daily_task_tree.exists(iid):
                self.daily_task_tree.selection_add(iid)
        if hasattr(self, "lbl_daily_task_detail"):
            self._daily_task_on_select()

    def _daily_task_selected_id(self):
        selection = self.daily_task_tree.selection()
        return int(selection[0]) if selection else None

    def _daily_task_action_buttons(self):
        return (self.btn_daily_task_check, self.btn_daily_task_accept,
                self.btn_daily_task_complete, self.btn_daily_task_claim,
                self.btn_daily_task_batch1, self.btn_daily_task_batch2,
                self.btn_daily_task_batch3,
                self.btn_daily_task_save1, self.btn_daily_task_save2,
                self.btn_daily_task_save3)

    # ---------- 批量接取：三组任务按账号/存档记忆 ----------
    def _daily_task_batches_load(self):
        try:
            with open(DAILY_TASK_BATCH_FILE, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {}
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, dict):
            return {}
        batches = {}
        for key, value in groups.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            batch = {}
            for group in ("1", "2", "3"):
                raw = value.get(group, [])
                ids = []
                if isinstance(raw, list):
                    for item in raw:
                        try:
                            task_id = int(item)
                        except (TypeError, ValueError):
                            continue
                        if task_id > 0 and task_id not in ids:
                            ids.append(task_id)
                batch[group] = ids
            batches[key] = batch
        return batches

    def _daily_task_batches_write(self):
        temporary = DAILY_TASK_BATCH_FILE + ".tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "groups": self._daily_task_batches},
                      file, ensure_ascii=False, indent=2)
        os.replace(temporary, DAILY_TASK_BATCH_FILE)

    def _daily_task_batch_key(self):
        if self.client is None or self.current_save is None:
            return None
        username = getattr(self.client, "username", None)
        if not username:
            return None
        return "%s::%d" % (username, int(self.current_save["index"]))

    def _daily_task_batch_ids(self, group):
        key = self._daily_task_batch_key()
        if not key:
            return []
        stored = self._daily_task_batches.get(key, {}).get(str(group), [])
        return [task_id for task_id in stored if task_id in self._daily_task_defs]

    def _daily_task_batch_update_labels(self):
        if not hasattr(self, "btn_daily_task_batch1"):
            return
        key = self._daily_task_batch_key()
        for group, button in ((1, self.btn_daily_task_batch1),
                              (2, self.btn_daily_task_batch2),
                              (3, self.btn_daily_task_batch3)):
            button.config(text="任务批量接取%d" % group)
        if not key:
            self.lbl_daily_task_batch.config(
                text="批量任务：登录并选择存档后再保存。")
        else:
            def summary(group):
                ids = self._daily_task_batch_ids(group)
                if not ids:
                    return "未设置"
                names = [str(self._daily_task_defs[tid].get("name", "?")) for tid in ids]
                text = "、".join(names[:3])
                if len(names) > 3:
                    text += " 等%d个" % len(names)
                return text

            self.lbl_daily_task_batch.config(
                text="批量1：%s\n批量2：%s\n批量3：%s\nCtrl/Shift 多选，保存会覆盖该组。" %
                     (summary(1), summary(2), summary(3)))

    def _daily_task_save_batch(self, group):
        if self.client is None or self.current_save is None:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        if getattr(self, "_daily_task_load_error", None):
            messagebox.showwarning("提示", "日常任务配置不可用，无法保存批量任务")
            return
        keys = [str(iid) for iid in self.daily_task_tree.selection()
                if str(iid).isdigit()]
        if not keys:
            messagebox.showwarning("提示", "请先在任务列表中选择任务（可 Ctrl/Shift 多选）")
            return
        order = {str(task_id): index for index, task_id in
                 enumerate(self.daily_task_tree.get_children())}
        task_ids = sorted({int(iid) for iid in keys},
                          key=lambda task_id: order.get(str(task_id), task_id))
        key = self._daily_task_batch_key()
        if not key:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        entry = self._daily_task_batches.setdefault(key, {"1": [], "2": [], "3": []})
        entry[str(group)] = task_ids
        try:
            self._daily_task_batches_write()
        except OSError as exc:
            messagebox.showerror("保存失败", "批量任务保存失败：%s" % exc)
            return
        self._daily_task_batch_update_labels()
        self._log("[日常任务] 批量%d已保存%d个任务：%s" %
                  (group, len(task_ids),
                   "、".join("%s(%d)" % (self._daily_task_defs[tid].get("name", "?"), tid)
                            for tid in task_ids)))

    def _daily_task_batch_accept(self, group):
        if not self._ensure_login():
            return
        if getattr(self, "_daily_task_load_error", None):
            messagebox.showwarning("提示", "日常任务配置不可用，无法批量接取")
            return
        if self.current_save is None:
            messagebox.showwarning("提示", "请先选择存档")
            return
        task_ids = self._daily_task_batch_ids(group)
        if not task_ids:
            messagebox.showwarning(
                "提示", "批量%d还没有任务。请先多选任务并点“存为批量%d”。" % (group, group))
            return
        slot = self.current_save["index"]
        for button in self._daily_task_action_buttons():
            button.config(state="disabled")
        self.combo_save.config(state="disabled")
        self.btn_login.config(state="disabled")

        def worker():
            flow = None
            accepted, skipped, failed = [], [], []
            quota_hit = False
            try:
                flow, entry, scene = self._connect_and_enter(slot)
                if entry.get("code") != 200 or not scene.get("curRecord"):
                    raise RuntimeError("当前槽位没有角色")
                snapshot = self._daily_task_make_snapshot(scene, slot)
                used, quota = snapshot["used"], snapshot["quota"]
                active, states = snapshot["active"], snapshot["states"]
                for index, task_id in enumerate(task_ids):
                    name = str(self._daily_task_defs.get(task_id, {}).get("name", "?"))
                    if task_id in active:
                        skipped.append((task_id, name, "已在任务中"))
                        self._log("[日常任务] 批量%d跳过%s（%d）：已在任务中" %
                                  (group, name, task_id))
                        continue
                    if quota and used >= quota:
                        quota_hit = True
                        skipped.append((task_id, name, "已达每日额度"))
                        for rest in task_ids[index + 1:]:
                            skipped.append(
                                (rest, str(self._daily_task_defs.get(rest, {}).get("name", "?")),
                                 "已达每日额度"))
                        break
                    state = states.get(task_id, "待读取")
                    if state != "可接":
                        skipped.append((task_id, name, state))
                        self._log("[日常任务] 批量%d跳过%s（%d）：%s" %
                                  (group, name, task_id, state))
                        continue
                    try:
                        started = flow.request("scene.taskHandler.startTask",
                                               {"taskId": task_id}, timeout=15)
                    except Exception as exc:
                        failed.append((task_id, name, str(exc)))
                        self._log("[日常任务] 批量%d接取%s（%d）异常：%s" %
                                  (group, name, task_id, exc))
                        continue
                    error = str(started.get("error") or started.get("code") or "")
                    if started.get("code") == 200 and not started.get("error"):
                        accepted.append((task_id, name))
                        used += 1
                        active[task_id] = {"taskId": task_id, "taskState": 0}
                        self._log("[日常任务] 批量%d已接取%s（%d），今日%d/%d" %
                                  (group, name, task_id, used, quota))
                    elif any(word in error for word in
                             ("已接", "已领取", "已经在任务", "任务已存在", "重复")):
                        active[task_id] = {"taskId": task_id}
                        skipped.append((task_id, name, "服务端已接"))
                        self._log("[日常任务] 批量%d跳过%s（%d）：服务端已接（%s）" %
                                  (group, name, task_id, error))
                    elif any(word in error for word in ("次数", "额度")):
                        quota_hit = True
                        skipped.append((task_id, name, "已达每日额度"))
                        self._log("[日常任务] 批量%d停止：%s" % (group, error))
                        break
                    else:
                        failed.append((task_id, name, error))
                        self._log("[日常任务] 批量%d接取%s（%d）失败：%s" %
                                  (group, name, task_id, error))
                if flow:
                    flow.disconnect()
                    flow = None
                flow, _, scene = self._connect_and_enter(slot)
                refreshed = self._daily_task_make_snapshot(scene, slot)
                self.root.after(0, lambda s=refreshed: self._daily_task_display_snapshot(s))
                summary = "批量%d完成：成功%d，跳过%d，失败%d" % (
                    group, len(accepted), len(skipped), len(failed))
                if quota_hit:
                    summary += "，已达每日额度"
                self._log("[日常任务] " + summary)
                if accepted:
                    self._log("[日常任务] 批量%d本次接取：%s" %
                              (group, "、".join("%s(%d)" % (name, tid)
                                               for tid, name in accepted)))
                if failed:
                    self._log("[日常任务] 批量%d失败项：%s" %
                              (group, "；".join("%s(%d):%s" % (name, tid, err)
                                               for tid, name, err in failed)))
            except Exception as exc:
                self._log("[日常任务] 批量%d停止: %s" % (group, exc))
                self.root.after(0, self._do_daily_task_check)
            finally:
                if flow:
                    flow.disconnect()
                for button in self._daily_task_action_buttons():
                    self.root.after(0, lambda btn=button: btn.config(state="normal"))
                self.root.after(0, lambda: self.combo_save.config(state="readonly"))
                self.root.after(0, lambda: self.btn_login.config(state="normal"))
                self.root.after(0, self._daily_task_batch_update_labels)

        threading.Thread(target=worker, daemon=True).start()

    def _daily_task_reset_display(self):
        self._daily_task_batch_update_labels()
        self._daily_task_snapshot = {}
        self.lbl_daily_task_quota.config(text="正在读取当前存档的日常任务…")
        for task_id in self._daily_task_defs:
            if self.daily_task_tree.exists(str(task_id)):
                self.daily_task_tree.set(str(task_id), "state", "待读取")
        self._daily_task_on_select()

    def _daily_task_on_select(self, event=None):
        task_id = self._daily_task_selected_id()
        if task_id is None:
            return
        row = self._daily_task_defs.get(task_id, {})
        state = self._daily_task_snapshot.get("states", {}).get(task_id, "待读取")
        route = "已实测" if task_id in DAILY_TASK_TESTED_ROUTES else "待验证，暂不自动完成"
        self.lbl_daily_task_detail.config(
            text="%s（%d）\n状态：%s\n等级要求：%s\n前置任务：%s\n关卡：%s\n自动路线：%s" %
                 (row.get("name", "?"), task_id, state, row.get("level", "?"),
                  row.get("preTaskId", "?"), row.get("dungeonId", "?"), route))

    def _daily_task_make_snapshot(self, scene, slot):
        cur = scene.get("curRecord", {})
        level = int(cur.get("p1", {}).get("level", 1) or 1)
        max_level = max(self._daily_task_equity, default=1)
        base_quota = self._daily_task_equity.get(min(level, max_level), 0)
        raw_vip = scene.get("user", {}).get("vipLevel")
        if raw_vip is None:
            raise RuntimeError("服务器未返回VIP等级，无法确认日常任务次数")
        vip = int(raw_vip)
        if vip not in self._daily_task_vip_extra:
            raise RuntimeError("VIP%d的日常任务次数配置缺失" % vip)
        vip_extra = self._daily_task_vip_extra[vip]
        quota = base_quota + vip_extra
        used = int(cur.get("dailyTasksNum", 0) or 0)
        old = {int(row.get("taskId")) for row in cur.get("oldTasks", [])
               if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()
               and int(row.get("num", 0) or 0) > 0}
        active = {int(row.get("taskId")): row for row in cur.get("curTasks", [])
                  if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()}
        claimed = {int(row.get("taskId")) for row in cur.get("dailyTasks", [])
                   if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()}
        states = {}
        for task_id, row in self._daily_task_defs.items():
            if task_id in active:
                states[task_id] = "可领奖" if active[task_id].get("taskState") == 1 else "进行中"
            elif task_id in claimed:
                states[task_id] = "今日已领"
            elif str(row.get("isClose", "0")) != "0":
                states[task_id] = "未开放"
            elif level < int(row.get("level", 1) or 1):
                states[task_id] = "等级不足"
            elif any(int(pre) not in old for pre in str(row.get("preTaskId", "1")).split(";")
                     if pre.isdigit() and int(pre) > 0):
                states[task_id] = "前置未完成"
            elif quota and used >= quota:
                states[task_id] = "次数用完"
            else:
                states[task_id] = "可接"
        return {"slot": slot, "level": level, "vip": vip,
                "base_quota": base_quota, "vip_extra": vip_extra,
                "quota": quota, "used": used, "states": states, "active": active}

    def _matching_daily_tasks(self, mid):
        matches = []
        for task_id, row in self._daily_task_defs.items():
            raw = row.get('dungeonIds')
            if not isinstance(raw, str) or raw in ('', '-1'):
                raw = str(row.get('dungeonId', ''))
            ids = {int(x) for x in raw.split(';') if x.isdigit() and int(x) > 0}
            if int(mid) in ids:
                matches.append(task_id)
        return sorted(matches, key=lambda task_id: (int(self._daily_task_defs[task_id].get('order', 0)), task_id))

    def _accept_matching_daily(self, flow, mid, slot, scene=None):
        if getattr(self, '_daily_task_load_error', None):
            raise RuntimeError('每日任务配置不可用，未开局；可取消自动接取后重试')
        matches = self._matching_daily_tasks(mid)
        if not matches:
            return
        # 不能在这里再调一次 enterScene：同一会话二次进入会被服务端拒绝（500 存档已登陆,请先退出），
        # 所以直接复用 _connect_and_enter 已拿到的快照。
        if not isinstance(scene, dict) or not scene.get('curRecord'):
            raise RuntimeError('开打前每日任务状态读取失败，未开局')
        snapshot = self._daily_task_make_snapshot(scene, slot)
        accepted = getattr(self, '_prebattle_accepted', None)
        if accepted is None:
            accepted = set()
            self._prebattle_accepted = accepted
        active = [task_id for task_id in matches
                  if task_id in snapshot['active'] or task_id in accepted]
        if active:
            self._log('[战前任务] 关卡%d已有匹配任务%s，不重复接取' % (mid, active))
            return
        candidates = [task_id for task_id in matches if snapshot['states'].get(task_id) == '可接']
        used = snapshot['used'] + len(accepted)
        if not candidates or (snapshot['quota'] and used >= snapshot['quota']):
            self._log('[战前任务] 关卡%d没有可接的匹配每日任务（等级/前置/额度/已领状态），继续原副本流程' % mid)
            return
        task_id = candidates[0]
        result = flow.request('scene.taskHandler.startTask', {'taskId': task_id}, timeout=15)
        error = str(result.get('error') or result.get('code') or '')
        if result.get('code') != 200 or result.get('error'):
            # 日常任务页/游戏内已经接过的任务，服务端会拒绝重复接取；这不算失败，继续原副本流程
            if any(word in error for word in ('已接', '已领取', '已经在任务', '任务已存在', '重复', '次数')):
                self._log('[战前任务] 关卡%d的任务%d服务端已在任务中或额度不足（%s），跳过接取继续开打'
                          % (mid, task_id, error))
                accepted.add(task_id)
                return
            raise RuntimeError('匹配每日任务%d接取失败，未开局：%s' % (task_id, error))
        accepted.add(task_id)
        self._log('[战前任务] 槽%s已接取%s（%d），随后进入关卡%d' %
                  (slot, self._daily_task_defs[task_id].get('name', ''), task_id, mid))

    def _daily_task_display_snapshot(self, snapshot):
        if self.current_save is None or self.current_save["index"] != snapshot["slot"]:
            return
        self._daily_task_snapshot = snapshot
        self.lbl_daily_task_quota.config(
            text="槽%d Lv.%d VIP%d：今日已接 %d/%d 次（基础%d＋VIP额外%d）" %
                 (snapshot["slot"], snapshot["level"], snapshot["vip"], snapshot["used"],
                  snapshot["quota"], snapshot["base_quota"], snapshot["vip_extra"]))
        for task_id, state in snapshot["states"].items():
            if self.daily_task_tree.exists(str(task_id)):
                self.daily_task_tree.set(str(task_id), "state", state)
        self._daily_task_on_select()

    def _do_daily_task_check(self):
        _count_generation = getattr(self, "_count_generation", 0)
        if not self.client or self.current_save is None:
            return
        slot = self.current_save["index"]
        self.btn_daily_task_check.config(state="disabled")
        self.lbl_daily_task_quota.config(text="正在读取槽%d的日常任务…" % slot)

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter(slot)
                if entry.get("code") != 200 or not scene.get("curRecord"):
                    raise RuntimeError("当前槽位没有角色")
                snapshot = self._daily_task_make_snapshot(scene, slot)
                if snapshot["slot"] == slot:
                    self._count_after(_count_generation, 0, lambda s=scene, i=slot: self._cache_main_dailycount(s, i))
                    self._count_after(_count_generation, 0, lambda: self._daily_task_display_snapshot(snapshot))
            except Exception as exc:
                if self.current_save and self.current_save["index"] == slot:
                    self._log("[日常任务] 读取失败: %s" % exc)
                    self._count_after(_count_generation, 0, self._daily_task_reset_display)
                    self._count_after(_count_generation, 0, lambda: self.lbl_daily_task_quota.config(text="读取失败，请刷新"))
            finally:
                if flow:
                    flow.disconnect()
                self._count_after(_count_generation, 0, lambda: self.btn_daily_task_check.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _daily_task_clear_copy(self, flow, scene, mid, use_w, batch_pickups=False):
        created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                               {"mid": mid, "costGem": 0}, timeout=15)
        if created.get("code") != 200:
            raise RuntimeError("关卡%d进入失败: %s" % (mid, created.get("error", created.get("code"))))
        drops = created.get("drops", {})
        pick_items, mob_ids, kill_monsters, drop_entries = [], [], [], []
        total_exp = total_sp = 0
        for drop in drops.get("newDrops", []):
            monster = drop.get("monsterId", "0")
            index = drop.get("index", 0)
            total_exp += drop.get("exp", 0)
            total_sp += drop.get("spirit", 0)
            has_item = False
            for values in drop.get("item", {}).values():
                has_item = True
                for pick_id in (values if isinstance(values, list) else [values]):
                    pick_items.append(pick_id)
                    drop_entries.append((pick_id, monster, index))
            if has_item:
                mob_ids.append(monster)
                kill_monsters.append("%s_%d" % (monster, index))
        time.sleep(2)
        dead = flow.request("scene.copyHandler.bossDead", None, timeout=10)
        time.sleep(0.5)
        finished = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
        time.sleep(0.5)
        if dead.get("code") != 200 or finished.get("code") != 200:
            raise RuntimeError("关卡%d结束失败: boss=%s, finish=%s" %
                               (mid, dead.get("code"), finished.get("code")))
        p1 = scene.get("curRecord", {}).get("p1", {})
        payload = {
            "copyId": drops.get("copyId", 0), "pickItems": pick_items,
            "mobIds": mob_ids, "killMonsters": kill_monsters,
            "completed": (1 | 16777216) if use_w else 1,
            "currentEXP": p1.get("experience", 0), "pickExp": total_exp, "pickSp": total_sp,
            "propertyP1Str": "%d;%d;%d;%d;%d;%d" % tuple(
                p1.get(key, 0) for key in ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
            "propertyP2Total": 0, "hitCombo": 100,
        }
        if use_w:
            payload["enterW"] = 1
        if batch_pickups and drop_entries:
            for start in range(0, len(drop_entries), 4):
                group = drop_entries[start:start + 4]
                pickup_payload = dict(payload)
                pickup_payload.pop("enterW", None)
                pickup_payload.update({
                    "pickItems": [item[0] for item in group],
                    "mobIds": [item[1] for item in group],
                    "killMonsters": [marker for item in group
                                     for marker in ("%s_%d" % (item[1], item[2]),) * 2],
                    "completed": 0,
                    "pickExp": total_exp if start == 0 else 0,
                    "pickSp": total_sp if start == 0 else 0,
                })
                pickup = flow.request("scene.copyHandler.syncDropInfoNew", pickup_payload, timeout=15)
                if pickup.get("code") != 200:
                    raise RuntimeError("关卡%d第%d批掉落拾取失败: %s" %
                                       (mid, start // 4 + 1, pickup.get("error", pickup.get("code"))))
            payload.update({"pickItems": [], "mobIds": [], "killMonsters": [],
                            "pickExp": 0, "pickSp": 0})
        settled = flow.request("scene.copyHandler.syncDropInfoNew", payload, timeout=15)
        if settled.get("code") != 200:
            raise RuntimeError("关卡%d结算失败: %s" % (mid, settled.get("error", settled.get("code"))))
        self._log("[日常任务] 关卡%d已结算" % mid)

    def _daily_task_action(self, action):
        if not self._ensure_login():
            return
        if action == "claim":
            claimable = [task_id for task_id, state
                         in self._daily_task_snapshot.get("states", {}).items()
                         if state == "可领奖"]
            if not claimable:
                messagebox.showwarning("提示", "当前没有已完成且未领取的任务")
                return
            task_id = None
        else:
            task_id = self._daily_task_selected_id()
            if task_id is None:
                messagebox.showwarning("提示", "请先选择日常任务")
                return
            status = self._daily_task_snapshot.get("states", {}).get(task_id)
            if action == "accept" and status != "可接":
                messagebox.showwarning("提示", "当前任务状态为%s，不能接取" % (status or "待读取"))
                return
            if action == "complete" and task_id not in DAILY_TASK_TESTED_ROUTES:
                messagebox.showwarning("提示", "该任务的自动通关路线尚未实测")
                return
            if action == "complete" and status not in ("可接", "进行中", "可领奖"):
                messagebox.showwarning("提示", "当前任务状态为%s，不能自动完成" % (status or "待读取"))
                return
        slot = self.current_save["index"]
        for button in self._daily_task_action_buttons():
            button.config(state="disabled")
        self.combo_save.config(state="disabled")
        self.btn_login.config(state="disabled")

        def worker():
            flow = None
            claimed_items = []
            try:
                flow, entry, scene = self._connect_and_enter(slot)
                if entry.get("code") != 200 or not scene.get("curRecord"):
                    raise RuntimeError("当前槽位没有角色")
                if action in ("accept", "complete"):
                    active = {int(row.get("taskId")): row
                              for row in scene.get("curRecord", {}).get("curTasks", [])
                              if isinstance(row, dict) and str(row.get("taskId", "")).isdigit()}
                    if task_id not in active:
                        snapshot = self._daily_task_make_snapshot(scene, slot)
                        if snapshot["used"] >= snapshot["quota"]:
                            raise RuntimeError("今日日常任务接取次数已用完（%d/%d）" %
                                               (snapshot["used"], snapshot["quota"]))
                        started = flow.request("scene.taskHandler.startTask", {"taskId": task_id}, timeout=15)
                        if started.get("code") != 200:
                            raise RuntimeError("接取任务%d失败: %s" %
                                               (task_id, started.get("error", started.get("code"))))
                        self._log("[日常任务] 已接取 %s（%d）" %
                                  (self._daily_task_defs[task_id].get("name", "?"), task_id))
                    if action == "complete" and active.get(task_id, {}).get("taskState") != 1:
                        for mid, use_w in DAILY_TASK_TESTED_ROUTES[task_id]:
                            self._daily_task_clear_copy(
                                flow, scene, mid, use_w,
                                batch_pickups=task_id in DAILY_TASK_BATCH_PICKUP_IDS)
                if action == "claim":
                    cur_tasks = scene.get("curRecord", {}).get("curTasks", [])
                    claim_ids = [int(row["taskId"]) for row in cur_tasks
                                 if isinstance(row, dict)
                                 and str(row.get("taskId", "")).isdigit()
                                 and row.get("taskState") == 1]
                    if not claim_ids:
                        raise RuntimeError("当前没有可领奖的已完成任务")
                    self._log("[日常任务] 一键领取 %d 个已完成任务：%s" %
                              (len(claim_ids), claim_ids))
                    for cid in claim_ids:
                        claimed = flow.request("scene.taskHandler.handoverTask",
                                               {"taskId": cid}, timeout=15)
                        if claimed.get("code") != 200:
                            self._log("[日常任务] 任务%d领奖失败：%s" %
                                      (cid, claimed.get("error", claimed.get("code"))))
                            continue
                        items = claimed.get("items", [])
                        claimed_items.extend(items)
                        self._log("[日常任务] 任务%d（%s）领奖成功：物品%s，经验%s，灵魂%s" %
                                  (cid, self._daily_task_defs.get(cid, {}).get("name", "?"),
                                   items, claimed.get("addExp", 0),
                                   claimed.get("addSpirit", 0)))
                elif action == "complete":
                    flow.disconnect()
                    flow, _, scene = self._connect_and_enter(slot)
                    current = next((row for row in scene.get("curRecord", {}).get("curTasks", [])
                                    if isinstance(row, dict) and row.get("taskId") == task_id), None)
                    if not current or current.get("taskState") != 1:
                        raise RuntimeError("任务%d尚未达到可领奖状态，保留当前进度" % task_id)
                    claimed = flow.request("scene.taskHandler.handoverTask", {"taskId": task_id}, timeout=15)
                    if claimed.get("code") != 200:
                        raise RuntimeError("任务%d领奖失败: %s" %
                                           (task_id, claimed.get("error", claimed.get("code"))))
                    claimed_items = claimed.get("items", [])
                    self._log("[日常任务] 任务%d领奖成功：物品%s，经验%s，灵魂%s" %
                              (task_id, claimed_items, claimed.get("addExp", 0),
                               claimed.get("addSpirit", 0)))
                flow.disconnect()
                flow, _, scene = self._connect_and_enter(slot)
                snapshot = self._daily_task_make_snapshot(scene, slot)
                self.root.after(0, lambda: self._daily_task_display_snapshot(snapshot))
                self._log("[日常任务] 槽%d当前已接 %d/%d 次" %
                          (slot, snapshot["used"], snapshot["quota"]))
                if claimed_items:
                    bag = scene.get("curRecord", {}).get("itemsBag", {}).get("items", [])
                    if isinstance(bag, dict):
                        bag = list(bag.values())
                    for reward in claimed_items:
                        reward_id = str(reward.get("id"))
                        count = sum(int(item.get("num", item.get("count", 0)) or 0)
                                    for item in bag if isinstance(item, dict)
                                    and str(item.get("id")) == reward_id)
                        self._log("[日常任务] 背包核对：道具%s当前%d个" % (reward_id, count))
            except Exception as exc:
                self._log("[日常任务] 操作停止: %s" % exc)
                self.root.after(0, self._do_daily_task_check)
            finally:
                if flow:
                    flow.disconnect()
                for button in self._daily_task_action_buttons():
                    self.root.after(0, lambda btn=button: btn.config(state="normal"))
                self.root.after(0, lambda: self.combo_save.config(state="readonly"))
                self.root.after(0, lambda: self.btn_login.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


    # ========== 主线刷取标签页 ==========
    def _build_mainfarm_tab(self):
        group = ttk.Frame(self.notebook)
        self.notebook.add(group, text="主线刷取")
        self.mainfarm_notebook = ttk.Notebook(group)
        self.mainfarm_notebook.pack(fill="both", expand=True)
        tab = ttk.Frame(self.mainfarm_notebook, padding=10)
        self.mainfarm_notebook.add(tab, text="主线刷取")

        # 左侧：关卡列表
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        list_frame = ttk.LabelFrame(left_frame, text="选择关卡（倒序排列）", padding=5)
        list_frame.pack(fill="both", expand=True)

        # 搜索框
        search_frame = ttk.Frame(list_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:").pack(side="left")
        self.var_main_search = tk.StringVar()
        self.var_main_search.trace_add("write", lambda *a: self._filter_main_levels())
        ttk.Entry(search_frame, textvariable=self.var_main_search, width=15).pack(side="left", padx=5)

        # 关卡列表
        list_box_frame = ttk.Frame(list_frame)
        list_box_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_box_frame)
        scrollbar.pack(side="right", fill="y")
        self.main_listbox = tk.Listbox(list_box_frame, yscrollcommand=scrollbar.set, width=30, height=20, exportselection=False)
        self.main_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.main_listbox.yview)

        # 填充关卡列表
        self._all_main_levels = MAIN_LEVELS
        self._filter_main_levels()

        # 右侧：设置
        right_frame = ttk.Frame(tab, width=250)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        setting_frame = ttk.LabelFrame(right_frame, text="刷取设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(setting_frame, text="刷取次数:").grid(row=0, column=0, sticky="w", pady=5)
        self.var_main_times = tk.IntVar(value=10)
        ttk.Spinbox(setting_frame, from_=1, to=10000, textvariable=self.var_main_times, width=10).grid(row=0, column=1, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=1, column=0, sticky="w", pady=5)
        self.var_main_delay = tk.DoubleVar(value=1.5)
        ttk.Spinbox(setting_frame, from_=0.2, to=10, increment=0.1, textvariable=self.var_main_delay, width=10).grid(row=1, column=1, pady=5)

        ttk.Label(setting_frame, text="次数按服务器通关记录读取", foreground="gray").grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        self.lbl_main_dailycount = ttk.Label(setting_frame, text="当前dailyCount: 未知")
        self.lbl_main_dailycount.grid(row=3, column=0, columnspan=2, sticky="w", pady=5)

        self.btn_mainfarm_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_mainfarm, state="disabled")
        self.btn_mainfarm_run.grid(row=4, column=0, columnspan=2, pady=10)

        self.var_main_hidden = tk.BooleanVar(value=False)
        ttk.Checkbutton(setting_frame, text="进入隐藏Boss房", variable=self.var_main_hidden).grid(row=5, column=0, columnspan=2, sticky="w")
        self.main_hidden_choice = ttk.Combobox(setting_frame, state="readonly", width=23)
        self.main_hidden_choice.grid(row=6, column=0, columnspan=2, pady=6)
        self.main_hidden_choice.bind("<<ComboboxSelected>>", lambda e: self._update_main_dailycount())
        self.main_listbox.bind("<<ListboxSelect>>", self._update_main_hidden_choices)
        from mainfarm_routes import REWARD_MODES
        self._main_reward_modes = REWARD_MODES
        self.var_main_reward_mode = tk.StringVar(value=next(iter(REWARD_MODES)))
        ttk.Label(setting_frame, text="奖励领取模式:").grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Combobox(setting_frame, textvariable=self.var_main_reward_mode,
                     values=list(REWARD_MODES), state="readonly", width=25).grid(
                         row=8, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Label(setting_frame, text="本关及隐藏BOSS房共用此设置", foreground="gray").grid(
            row=9, column=0, columnspan=2, sticky="w")

        # 掉落统计
        drop_frame = ttk.LabelFrame(right_frame, text="掉落统计", padding=10)
        drop_frame.pack(fill="both", expand=True)
        self.txt_main_drops = tk.Text(drop_frame, height=10, width=25)
        self.txt_main_drops.pack(fill="both", expand=True)

    def _filter_main_levels(self):
        keyword = self.var_main_search.get().lower()
        self.main_listbox.delete(0, tk.END)
        for mid, name in self._all_main_levels:
            if keyword in name.lower() or keyword in str(mid):
                self.main_listbox.insert(tk.END, "%d - %s" % (mid, name))
        if hasattr(self, "main_hidden_choice"):
            self._update_main_hidden_choices()

    def _update_main_hidden_choices(self, event=None):
        from mainfarm_routes import hidden_choices
        selected = self.main_listbox.curselection()
        self._main_hidden_rows = []
        if selected:
            mid = int(self.main_listbox.get(selected[0]).split(" - ", 1)[0])
            self._main_hidden_rows = hidden_choices(mid)
        self.main_hidden_choice.config(values=["%s - %s" % (r["id"], r["name"]) for r in self._main_hidden_rows])
        if self._main_hidden_rows:
            self.main_hidden_choice.current(len(self._main_hidden_rows) - 1)
        else:
            self.main_hidden_choice.set("")
        self._update_main_dailycount()

    def _cache_main_dailycount(self, scene, slot):
        if not self.current_save or self.current_save["index"] != slot:
            return
        record = scene.get("curRecord", {})
        history = record.get("copyHistory")
        if isinstance(history, dict):
            history = list(history.values())
        self._main_daily_counts = ({int(r["id"]): int(r.get("num", 0) or 0)
                                   for r in history if isinstance(r, dict) and
                                   str(r.get("id", "")).isdigit()}
                                  if isinstance(history, list) else None)
        self._update_main_dailycount()

    def _update_main_dailycount(self):
        if not hasattr(self, "lbl_main_dailycount"):
            return
        counts = getattr(self, "_main_daily_counts", None)
        selected = self.main_listbox.curselection()
        if counts is None:
            self.lbl_main_dailycount.config(text="当前dailyCount：尚未读取")
        elif not selected:
            self.lbl_main_dailycount.config(text="dailyCount：请选择关卡")
        else:
            mid = int(self.main_listbox.get(selected[0]).split(" - ", 1)[0])
            text = "本关dailyCount：%d" % counts.get(mid, 0)
            index = self.main_hidden_choice.current()
            rows = getattr(self, "_main_hidden_rows", [])
            if 0 <= index < len(rows):
                text += "；Boss：%d" % counts.get(int(rows[index]["id"]), 0)
            self.lbl_main_dailycount.config(text=text)

    def _do_mainfarm(self):
        if not self._ensure_login():
            return
        selected = self.main_listbox.curselection()
        if not selected:
            messagebox.showwarning("提示", "请选择关卡")
            return
        mid = int(self.main_listbox.get(selected[0]).split(" - ", 1)[0])
        hidden = None
        if self.var_main_hidden.get():
            index = self.main_hidden_choice.current()
            rows = getattr(self, "_main_hidden_rows", [])
            if index < 0 or index >= len(rows):
                messagebox.showwarning("提示", "该关卡没有已确认的隐藏房配置")
                return
            hidden = int(rows[index]["id"])
        times, delay = self.var_main_times.get(), self.var_main_delay.get()
        if times < 1 or delay < 0.2:
            messagebox.showwarning("提示", "次数至少1，间隔至少0.2秒")
            return
        self.btn_mainfarm_run.config(state="disabled")
        self.txt_main_drops.delete("1.0", tk.END)
        reward_mode = self._main_reward_modes.get(self.var_main_reward_mode.get(), "all")
        threading.Thread(target=self._mainfarm_worker,
                         args=(mid, hidden, times, delay, reward_mode), daemon=True).start()

    def _mainfarm_worker(self, mid, hidden, times, delay, reward_mode="all"):
        flow = None
        totals = {}
        try:
            self._log("[主线刷取] 正在加载模块及关卡配置...")
            from mainfarm_routes import clear_stage, REWARD_MODES
            with open(os.path.join(CONFIG_DIR, "150___Prop.xml.json"), encoding="utf-8") as file:
                names = {str(r["id"]): r.get("name", r["id"]) for r in json.load(file)["RECORD"]}
            flow, _, scene = self._connect_and_enter()
            baseline = scene
            slot = self.current_save["index"]
            self.root.after(0, lambda s=scene, i=slot: self._cache_main_dailycount(s, i))
            self._log("[主线刷取] 奖励模式：%s" % next(
                label for label, value in REWARD_MODES.items() if value == reward_mode))
            for i in range(times):
                stages = [(mid, hidden is not None)] + ([(hidden, False)] if hidden else [])
                for stage, enter_w in stages:
                    result = clear_stage(flow, scene, stage, enter_w, pick_equips=True,
                                         reward_mode=reward_mode)
                    for iid, count in result["counts"].items():
                        totals[iid] = totals.get(iid, 0) + count
                    self._log("[主线刷取] %d/%d 关卡%d已结算，道具：%s" % (i+1, times, stage, result["counts"]))
                text = "已成功结算的服务器掉落：\n" + "\n".join("%s (%s): %s" % (names.get(iid, iid), iid, count) for iid, count in sorted(totals.items()))
                if reward_mode != "all":
                    text = "本轮不领取道具。" + ("经验和灵魂照常结算。" if reward_mode == "exp_spirit" else "经验和灵魂也不领取。")
                self.root.after(0, lambda t=text: self._show_mainfarm_drops(t))
                if i + 1 < times:
                    time.sleep(delay)
            flow.disconnect()
            flow = None
            flow, _, after = self._connect_and_enter()
            self.root.after(0, lambda s=after, i=slot: self._cache_main_dailycount(s, i))
            def inventory_counts(snapshot):
                counts = {}
                for bag_name in ("itemsBag", "equipsBag"):
                    rows = ((snapshot.get("curRecord") or {}).get(bag_name) or {}).get("items") or []
                    for row in (rows.values() if isinstance(rows, dict) else rows):
                        key = str(row.get("id"))
                        counts[key] = counts.get(key, 0) + int(row.get("count", 1))
                return counts
            before_items, after_items = inventory_counts(baseline), inventory_counts(after)
            if reward_mode != "all" and before_items != after_items:
                raise RuntimeError("已关闭道具领取，但重登发现背包数量变化")
            if reward_mode == "none":
                old_record, new_record = baseline["curRecord"], after["curRecord"]
                if old_record.get("spirit") != new_record.get("spirit") or any(
                        old_record["p1"].get(key) != new_record["p1"].get(key)
                        for key in ("level", "experience")):
                    raise RuntimeError("已选择全部不领取，但重登发现经验或灵魂变化")
                self._log("[主线刷取核验] 重登确认道具、角色经验及灵魂均未增加")
            for iid, count in sorted(totals.items()):
                old = before_items.get(iid, 0)
                new = after_items.get(iid, 0)
                self._log("[主线刷取核验] %s：%d → %d，增加%d，掉落记录%d" %
                          (names.get(iid, iid), old, new, new-old, count))
            if any((baseline.get("user") or {}).get(key) != (after.get("user") or {}).get(key)
                   for key in ("gem", "usedGem")):
                raise RuntimeError("重登发现点券变化，请检查")
            self._log("[主线刷取核验] 点券：%s → %s" %
                      ((baseline.get("user") or {}).get("gem"), (after.get("user") or {}).get("gem")))
            self._log("[主线刷取] 完成%d轮" % times)
        except Exception as error:
            self._log("[主线刷取] 已停止：%s" % error)
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self.btn_mainfarm_run.config(state="normal"))

    def _show_mainfarm_drops(self, text):
        self.txt_main_drops.delete("1.0", tk.END)
        self.txt_main_drops.insert("1.0", text)

    # ========== 主线通关：按新存档实测路线逐关推进 ==========
    def _build_mainline_clear_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="主线通关")

        left = ttk.LabelFrame(tab, text="关卡通关记录", padding=8)
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(tree_frame)
        scroll.pack(side="right", fill="y")
        self.mainline_tree = ttk.Treeview(
            tree_frame, columns=("id", "name", "state"), show="headings",
            yscrollcommand=scroll.set, height=18,
        )
        scroll.config(command=self.mainline_tree.yview)
        for column, title, width in (("id", "关卡", 65), ("name", "名称", 150), ("state", "进度", 150)):
            self.mainline_tree.heading(column, text=title)
            self.mainline_tree.column(column, width=width, anchor="w")
        self.mainline_tree.pack(side="left", fill="both", expand=True)
        for mid, name in reversed(MAIN_LEVELS):
            hidden = MAINLINE_REQUIRED_HIDDEN.get(mid)
            state = "待读取" if not hidden else "待读取（隐藏%d）" % hidden
            self.mainline_tree.insert("", "end", iid="mainline-%d" % mid,
                                      values=(mid, name, state))

        right = ttk.Frame(tab, width=260)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)
        ttk.Label(right, text="按 1～65 关的实测顺序通关。\n必经隐藏关会自动接在前置关后。",
                  justify="left", wraplength=245).pack(anchor="w", pady=(0, 12))
        ttk.Label(right, text="通关到第几关：").pack(anchor="w")
        self.var_mainline_target = tk.IntVar(value=65)
        ttk.Spinbox(right, from_=1, to=65, textvariable=self.var_mainline_target,
                    width=8).pack(anchor="w", pady=(2, 10))
        self.btn_mainline_check = ttk.Button(right, text="读取当前进度",
                                             command=self._do_mainline_check, state="disabled")
        self.btn_mainline_check.pack(fill="x", pady=3)
        self.btn_mainline_run = ttk.Button(right, text="从未通关处继续",
                                           command=self._do_mainline_clear, state="disabled")
        self.btn_mainline_run.pack(fill="x", pady=3)
        self.btn_mainline_stop = ttk.Button(right, text="停止（完成当前关）",
                                            command=self._stop_mainline_clear, state="disabled")
        self.btn_mainline_stop.pack(fill="x", pady=3)
        self.lbl_mainline_status = ttk.Label(right, text="选择存档后读取进度", foreground="blue",
                                             wraplength=245, justify="left")
        self.lbl_mainline_status.pack(anchor="w", pady=(14, 8))
        ttk.Label(right,
                  text="结算带 W 标志。为保证通关，不拾取关卡掉落；不购买次数或背包空间。背包已满时会停止。",
                  wraplength=245, justify="left", foreground="gray").pack(anchor="w")
        self._mainline_stop_event = threading.Event()

    @staticmethod
    def _mainline_history(scene):
        from mainfarm_routes import dungeon_rows
        history = scene.get("curRecord", {}).get("copyHistory", [])
        if isinstance(history, dict):
            history = list(history.values())
        done = {int(row.get("id")) for row in history
                if isinstance(row, dict) and str(row.get("id", "")).isdigit()
                and int(row.get("num", 0) or 0) > 0}
        # 官方LevelModelManager会将Boss房的通关映射到specialDoor。
        configs = dungeon_rows()
        for mid in tuple(done):
            special = int(configs.get(mid, {}).get("specialDoor", 0) or 0)
            if special > 0 and special != 2001:
                done.add(special)
        return done

    def _mainline_reset_display(self):
        for mid, _ in MAIN_LEVELS:
            self.mainline_tree.set("mainline-%d" % mid, "state", "待读取")
        self.lbl_mainline_status.config(text="选择存档后读取进度")

    def _mainline_display(self, done):
        normal_count = sum(mid in done for mid in range(1, 66))
        highest_normal = max((mid for mid in done if 1 <= mid <= 65), default=0)
        hidden_count = sum(mid in done for mid in MAINLINE_REQUIRED_HIDDEN.values())
        for mid, _ in MAIN_LEVELS:
            hidden = MAINLINE_REQUIRED_HIDDEN.get(mid)
            if mid not in done:
                state = "未通"
            elif hidden and hidden not in done:
                state = "待打隐藏 %d" % hidden
            else:
                state = "已通" if not hidden else "已通 + 隐藏 %d" % hidden
            self.mainline_tree.set("mainline-%d" % mid, "state", state)
        self.lbl_mainline_status.config(
            text="主线记录到第%d关；普通记录%d/65；Boss记录%d/%d" %
                 (highest_normal, normal_count, hidden_count, len(MAINLINE_REQUIRED_HIDDEN)))

    def _do_mainline_check(self):
        if not self._ensure_login():
            return
        self.btn_mainline_check.config(state="disabled")

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter()
                if entry.get("code") != 200 or not scene.get("curRecord"):
                    raise RuntimeError("当前槽位没有角色")
                done = self._mainline_history(scene)
                self.root.after(0, lambda: self._mainline_display(done))
                self._log("[主线通关] 已读取槽%d的通关记录" % self.current_save["index"])
            except Exception as exc:
                self._log("[主线通关] 读取失败: %s" % exc)
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_mainline_check.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _stop_mainline_clear(self):
        self._mainline_stop_event.set()
        self._log("[主线通关] 已请求停止，当前关结算后退出")

    def _mainline_clear_copy(self, flow, scene, mid):
        self._log("[主线通关] 正在进入关卡%d" % mid)
        self.root.after(0, lambda m=mid: self.lbl_mainline_status.config(
            text="正在进入关卡%d…" % m))
        create = flow.request("scene.copyHandler.createSinglePlayerCopy",
                              {"mid": mid, "costGem": 0}, timeout=15)
        if create.get("code") != 200 or create.get("error"):
            raise RuntimeError("关卡%d进入失败: %s" % (mid, create.get("error", create.get("code"))))
        drops = create.get("drops", {})
        if not drops.get("copyId"):
            raise RuntimeError("关卡%d未返回副本ID" % mid)
        time.sleep(0.5)
        dead = flow.request("scene.copyHandler.bossDead", None, timeout=10)
        finish = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
        if dead.get("code") != 200 or finish.get("code") != 200 or dead.get("error") or finish.get("error"):
            raise RuntimeError("关卡%d结束失败: boss=%s, finish=%s" %
                               (mid, dead.get("code"), finish.get("code")))
        p1 = scene.get("curRecord", {}).get("p1", {})
        sync = flow.request("scene.copyHandler.syncDropInfoNew", {
            "copyId": drops.get("copyId", 0), "pickItems": [], "mobIds": [],
            "killMonsters": [], "completed": 1 | 16777216, "enterW": 1,
            "currentEXP": p1.get("experience", 0), "pickExp": 0, "pickSp": 0,
            "propertyP1Str": "%d;%d;%d;%d;%d;%d" % tuple(
                p1.get(key, 0) for key in ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
            "propertyP2Total": 0, "hitCombo": 100,
        }, timeout=15)
        if sync.get("code") != 200 or sync.get("error"):
            raise RuntimeError("关卡%d结算失败: %s" % (mid, sync.get("error", sync.get("code"))))
        self._log("[主线通关] 关卡%d结算成功" % mid)

    def _do_mainline_clear(self):
        if not self._ensure_login():
            return
        try:
            target = self.var_mainline_target.get()
        except (tk.TclError, ValueError):
            messagebox.showwarning("提示", "请输入 1～65 的目标关卡")
            return
        if not 1 <= target <= 65:
            messagebox.showwarning("提示", "目标关卡必须在 1～65 之间")
            return
        slot = self.current_save["index"]
        self._log("[主线通关] 已开始，正在连接槽%d…" % slot)
        self.lbl_mainline_status.config(text="正在连接存档…")
        self._mainline_stop_event.clear()
        self.btn_mainline_run.config(state="disabled")
        self.btn_mainline_check.config(state="disabled")
        self.btn_mainline_stop.config(state="normal")
        self.combo_save.config(state="disabled")
        self.btn_login.config(state="disabled")

        def worker():
            flow = None
            try:
                flow, entry, scene = self._connect_and_enter()
                if entry.get("code") != 200 or not scene.get("curRecord"):
                    raise RuntimeError("当前槽位没有角色")
                done = self._mainline_history(scene)
                self.root.after(0, lambda: self._mainline_display(done.copy()))
                self._log("[主线通关] 槽%d：从未通关处推进到第%d关" % (slot, target))
                if 1 in done:
                    first_task = next((task for task in scene.get("curRecord", {}).get("curTasks", [])
                                       if isinstance(task, dict) and task.get("taskId") == 1), None)
                    if first_task and first_task.get("taskState") == 1:
                        claim = flow.request("scene.taskHandler.handoverTask", {"taskId": 1}, timeout=15)
                        if claim.get("code") != 200:
                            raise RuntimeError("第一关主线任务领奖失败: %s" % claim.get("error", claim.get("code")))
                        self._log("[主线通关] 已领取第一关主线任务奖励")
                for mid in range(1, target + 1):
                    if self._mainline_stop_event.is_set():
                        break
                    hidden = MAINLINE_REQUIRED_HIDDEN.get(mid)
                    need_normal = mid not in done
                    need_hidden = hidden is not None and hidden not in done
                    if not need_normal and not need_hidden:
                        continue
                    if need_normal or need_hidden:
                        if not need_normal:
                            self._log("[主线通关] 重打第%d关后立即进入隐藏关%d" % (mid, hidden))
                        self._mainline_clear_copy(flow, scene, mid)
                        done.add(mid)
                    if need_hidden:
                        if self._mainline_stop_event.is_set():
                            break
                        self._mainline_clear_copy(flow, scene, hidden)
                        done.add(hidden)
                    self.root.after(0, lambda snapshot=done.copy(): self._mainline_display(snapshot))
                    if mid == 1:
                        flow.disconnect()
                        flow, _, scene = self._connect_and_enter()
                        first_task = next((task for task in scene.get("curRecord", {}).get("curTasks", [])
                                           if isinstance(task, dict) and task.get("taskId") == 1), None)
                        if first_task and first_task.get("taskState") == 1:
                            claim = flow.request("scene.taskHandler.handoverTask", {"taskId": 1}, timeout=15)
                            if claim.get("code") != 200:
                                raise RuntimeError("第一关主线任务领奖失败: %s" % claim.get("error", claim.get("code")))
                            self._log("[主线通关] 已领取第一关主线任务奖励")

                flow.disconnect()
                flow = None
                verify_flow, _, verify_scene = self._connect_and_enter()
                try:
                    verified = self._mainline_history(verify_scene)
                    self.root.after(0, lambda: self._mainline_display(verified))
                    normal = sum(mid in verified for mid in range(1, target + 1))
                    required = sum(hidden in verified for mid, hidden in MAINLINE_REQUIRED_HIDDEN.items()
                                   if mid <= target)
                    needed = sum(mid <= target for mid in MAINLINE_REQUIRED_HIDDEN)
                    self._log("[主线通关] 重新登录核对：普通关%d/%d，必经隐藏关%d/%d" %
                              (normal, target, required, needed))
                finally:
                    verify_flow.disconnect()
            except Exception as exc:
                self._log("[主线通关] 已停止: %s" % exc)
                self.root.after(0, lambda message=str(exc): self.lbl_mainline_status.config(
                    text="已停止：" + message, foreground="red"))
            finally:
                if flow:
                    flow.disconnect()
                self.root.after(0, lambda: self.btn_mainline_run.config(state="normal"))
                self.root.after(0, lambda: self.btn_mainline_check.config(state="normal"))
                self.root.after(0, lambda: self.btn_mainline_stop.config(state="disabled"))
                self.root.after(0, lambda: self.combo_save.config(state="readonly"))
                self.root.after(0, lambda: self.btn_login.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


    # ========== 噩梦/神域刷取标签页 ==========
    def _build_nightmare_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="噩梦")
        from official_sweep import add_mode_controls
        add_mode_controls(self, tab, "nightmare")

        # 左侧：关卡列表
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        list_frame = ttk.LabelFrame(left_frame, text="选择关卡（倒序，显示体力消耗）", padding=5)
        list_frame.pack(fill="both", expand=True)

        # 搜索框
        search_frame = ttk.Frame(list_frame)
        search_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(search_frame, text="搜索:").pack(side="left")
        self.var_nm_search = tk.StringVar()
        self.var_nm_search.trace_add("write", lambda *a: self._filter_nm_levels())
        ttk.Entry(search_frame, textvariable=self.var_nm_search, width=15).pack(side="left", padx=5)

        # 关卡列表
        list_box_frame = ttk.Frame(list_frame)
        list_box_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_box_frame)
        scrollbar.pack(side="right", fill="y")
        self.nm_listbox = tk.Listbox(list_box_frame, yscrollcommand=scrollbar.set, width=35, height=20, exportselection=False)
        self.nm_listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.nm_listbox.yview)

        self._all_nm_levels = NIGHTMARE_LEVELS
        self._filter_nm_levels()

        # 右侧：设置
        right_frame = ttk.Frame(tab, width=260)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        # 体力显示
        power_frame = ttk.LabelFrame(right_frame, text="体力状态", padding=10)
        power_frame.pack(fill="x", pady=(0, 10))
        self.lbl_nm_power = ttk.Label(power_frame, text="当前体力: 未知", font=("Arial", 12, "bold"))
        self.lbl_nm_power.pack(anchor="w")
        ttk.Label(power_frame, text="60体力关: 最多10次", foreground="gray").pack(anchor="w")
        ttk.Label(power_frame, text="120体力关: 最多5次", foreground="gray").pack(anchor="w")
        ttk.Label(power_frame, text="噩梦: 60/120体力", foreground="gray").pack(anchor="w")

        # 刷取设置
        setting_frame = ttk.LabelFrame(right_frame, text="刷取设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(setting_frame, text="刷取次数:").grid(row=0, column=0, sticky="w", pady=5)
        self.var_nm_times = tk.IntVar(value=1)
        ttk.Spinbox(setting_frame, from_=1, to=100, textvariable=self.var_nm_times, width=10).grid(row=0, column=1, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=1, column=0, sticky="w", pady=5)
        self.var_nm_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_nm_delay, width=10).grid(row=1, column=1, pady=5)

        ttk.Label(setting_frame, text="⚠ 体力不足自动停止", foreground="red").grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        self.btn_nightmare_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_nightmare, state="disabled")
        self.btn_nightmare_run.grid(row=3, column=0, columnspan=2, pady=10)

        boss_frame = ttk.LabelFrame(right_frame, text="BOSS房 / 隐藏BOSS房", padding=8)
        boss_frame.pack(fill="x", pady=(0, 10))
        self.nm_boss_choice = ttk.Combobox(boss_frame, state="disabled", width=29)
        self.nm_boss_choice.pack(fill="x")
        self.lbl_nm_boss_hint = ttk.Label(boss_frame, text="选择关卡后显示目标房间。", wraplength=235, justify="left")
        self.lbl_nm_boss_hint.pack(anchor="w", pady=(6, 0))
        self._nm_boss_targets = []
        self.nm_listbox.bind("<<ListboxSelect>>", self._update_nm_boss_choices)
        self.nm_boss_choice.bind("<<ComboboxSelected>>", self._update_nm_boss_hint)

        # 掉落统计
        drop_frame = ttk.LabelFrame(right_frame, text="掉落统计", padding=10)
        drop_frame.pack(fill="both", expand=True)
        self.txt_nm_drops = tk.Text(drop_frame, height=8, width=28)
        self.txt_nm_drops.pack(fill="both", expand=True)

    def _filter_nm_levels(self):
        keyword = self.var_nm_search.get().lower()
        self.nm_listbox.delete(0, tk.END)
        for mid, name, power in self._all_nm_levels:
            text = "%d - %s (%d体力)" % (mid, name, power)
            if keyword in name.lower() or keyword in str(mid):
                self.nm_listbox.insert(tk.END, text)
        if hasattr(self, "nm_boss_choice"):
            self._update_nm_boss_choices()

    def _update_nm_boss_choices(self, event=None):
        selection = self.nm_listbox.curselection()
        if not selection:
            self._nm_boss_mid = None
            self._nm_boss_targets = []
            self.nm_boss_choice.config(values=(), state="disabled")
            self.nm_boss_choice.set("")
            self.lbl_nm_boss_hint.config(text="请选择关卡。")
            return
        mid = int(self.nm_listbox.get(selection[0]).split(" - ", 1)[0])
        # 同一关卡的重复选择事件不重置已选中的隐藏分支。
        if getattr(self, "_nm_boss_mid", None) == mid:
            self._update_nm_boss_hint()
            return
        targets = {
            310: [(10160, "辟尘/辟暑/辟寒大王", True)],
            340: [(10170, "蜘蛛精隐藏房", True)],
            370: [(10190, "女魃", True)],
            460: [(461, "四剑归一", True)],
            501: [(10260, "亚窳（BOSS房）", False), (10270, "波儿象（隐藏BOSS房）", True)],
            504: [(10300, "冥蛊师（BOSS房）", False), (10310, "蛇骨婆母（隐藏BOSS房）", True)],
            507: [(10340, "花妖曼珠（BOSS房）", False), (10350, "叶妖沙华（隐藏BOSS房）", True)],
            510: [(10360, "摆渡冥将（BOSS房）", False), (10370, "九渊鬼王（隐藏BOSS房）", True)],
            513: [(10380, "幽冥鬼母（BOSS房）", False), (10390, "幽冥鬼子（隐藏BOSS房）", True)],
            515: [(516, "血海真身（二阶段）", True)],
            601: [(10400, "伏藏龙（BOSS房）", False), (10410, "魔将百臂（隐藏BOSS房）", True)],
        }.get(mid, [])
        self._nm_boss_mid = mid
        self._nm_boss_targets = targets
        if targets:
            self.nm_boss_choice.config(values=["%s (%d)" % (name, bid) for bid, name, _ in targets], state="readonly")
            self.nm_boss_choice.current(0)
        else:
            self.nm_boss_choice.config(values=(), state="disabled")
            self.nm_boss_choice.set("本关BOSS")
        self._update_nm_boss_hint()

    def _update_nm_boss_hint(self, event=None):
        targets = getattr(self, "_nm_boss_targets", [])
        index = self.nm_boss_choice.current()
        if targets and 0 <= index < len(targets):
            bid, name, enter_w = targets[index]
            text = "目标：%s。每轮先结算前置关（enterW=%d），再进入所选房间%d；一次前置只选一个分支。" % (name, int(enter_w), bid)
        else:
            text = "BOSS在本关内，直接通关；不进入配置标为废弃的独立房间。"
        self.lbl_nm_boss_hint.config(text=text)

    def _do_nightmare(self):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        selection = self.nm_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请选择关卡")
            return
        mid = int(self.nm_listbox.get(selection[0]).split(" - ", 1)[0])
        level_name, power_cost = next((name, power) for bid, name, power in self._all_nm_levels if bid == mid)
        from official_sweep import dispatch
        if dispatch(self, "nightmare", [mid], self.var_nm_times.get()):
            return
        if getattr(self, "_nm_boss_mid", None) != mid:
            self._update_nm_boss_choices()
        targets = self._nm_boss_targets
        target = None
        if targets:
            index = self.nm_boss_choice.current()
            if not 0 <= index < len(targets):
                messagebox.showwarning("提示", "请选择目标BOSS房")
                return
            target = targets[index]
        try:
            times, delay = int(self.var_nm_times.get()), float(self.var_nm_delay.get())
            if times < 1 or delay < 0.5:
                raise ValueError()
        except (ValueError, tk.TclError):
            messagebox.showwarning("提示", "次数至少1次，间隔至少0.5秒")
            return
        self.btn_nightmare_run.config(state="disabled")
        self.txt_nm_drops.delete("1.0", tk.END)
        threading.Thread(target=self._nightmare_worker, args=(mid, level_name, power_cost, target, times, delay), daemon=True).start()

    def _nightmare_worker(self, mid, level_name, power_cost, target, times, delay):
        from mainfarm_routes import clear_stage
        flow = None
        totals = {}
        success = 0
        try:
            names = {}
            for filename in ("150___Prop.xml.json", "046___Equipment.xml.json"):
                with open(os.path.join(CONFIG_DIR, filename), encoding="utf-8") as file:
                    names.update({str(r["id"]): r.get("name", str(r["id"])) for r in json.load(file)["RECORD"]})
            flow, _, scene = self._connect_and_enter()
            self._log("[噩梦刷取] %s，目标：%s，共%d轮" % (level_name, target[1] if target else "本关BOSS", times))
            for i in range(times):
                baseline = scene
                power = int(scene.get("curRecord", {}).get("collectPower", 0))
                if power < power_cost:
                    self._log("[噩梦刷取] 体力不足，停止")
                    break
                counts = {}
                stages = [(mid, target[2] if target else True)]
                if target:
                    stages.append((target[0], True))
                for stage, enter_w in stages:
                    result = clear_stage(flow, scene, stage, enter_w=enter_w, pick_equips=True)
                    for iid, count in result["counts"].items():
                        counts[iid] = counts.get(iid, 0) + count
                    self._log("[噩梦刷取] %d/%d 关卡%d已结算，enterW=%d" % (i+1, times, stage, int(enter_w)))
                flow.disconnect(); flow = None
                flow, _, scene = self._connect_and_enter()
                before_user, after_user = baseline.get("user", {}), scene.get("user", {})
                if any(before_user.get(k) != after_user.get(k) for k in ("gem", "usedGem")):
                    raise RuntimeError("点券数量发生变化，已停止")
                def inventory(snapshot):
                    values = {}
                    for key in ("itemsBag", "equipsBag"):
                        items = snapshot.get("curRecord", {}).get(key, {}).get("items") or []
                        if isinstance(items, dict):
                            items = items.values()
                        for item in items:
                            iid = str(item["id"])
                            values[iid] = values.get(iid, 0) + int(item.get("count", 1) or 1)
                    return values
                old, new = inventory(baseline), inventory(scene)
                for iid, count in counts.items():
                    delta = new.get(iid, 0) - old.get(iid, 0)
                    if delta != count:
                        raise RuntimeError("%s入包核对不符：记录%d，实际增加%d" % (names.get(iid, iid), count, delta))
                    totals[iid] = totals.get(iid, 0) + count
                remaining = scene.get("curRecord", {}).get("collectPower", 0)
                self.root.after(0, lambda n=remaining: self.lbl_nm_power.config(text="当前体力: %d" % n))
                self._log("[噩梦核验] 第%d轮奖励已入包，体力%d→%d，点券未消耗" % (i+1, power, remaining))
                success += 1
                text = "\n".join("%s (%s): %d" % (names.get(iid, iid), iid, count) for iid, count in sorted(totals.items()))
                def show(t=text):
                    self.txt_nm_drops.delete("1.0", tk.END)
                    self.txt_nm_drops.insert("1.0", t)
                self.root.after(0, show)
                if i+1 < times:
                    time.sleep(delay)
            self._log("[噩梦刷取] 完成%d轮" % success)
        except Exception as error:
            self._log("[噩梦刷取] 已停止：%s" % error)
        finally:
            if flow:
                flow.disconnect()
            self.root.after(0, lambda: self.btn_nightmare_run.config(state="normal"))

# ========== 神域/镜域标签页 ==========
    def _build_shenyu_jingyu_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="神域/镜域")
        from official_sweep import add_mode_controls
        add_mode_controls(self, tab, "shenyu")

        # 左侧：神域关卡
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))

        sy_frame = ttk.LabelFrame(left_frame, text="神域（消耗120体力）", padding=5)
        sy_frame.pack(fill="both", expand=True)

        self.sy_listbox = tk.Listbox(sy_frame, width=25, height=15, exportselection=False)
        self.sy_listbox.pack(fill="both", expand=True)
        for mid, name in SHENYU_LEVELS:
            self.sy_listbox.insert(tk.END, "%d - %s" % (mid, name))

        # 中间：镜域关卡
        mid_frame = ttk.Frame(tab)
        mid_frame.pack(side="left", fill="both", expand=True, padx=5)

        jy_frame = ttk.LabelFrame(mid_frame, text="镜域（0体力，周10次共享）", padding=5)
        jy_frame.pack(fill="both", expand=True)

        self.jy_listbox = tk.Listbox(jy_frame, width=25, height=15, exportselection=False)
        self.jy_listbox.pack(fill="both", expand=True)
        for mid, name in JINGYU_LEVELS:
            self.jy_listbox.insert(tk.END, "%d - %s" % (mid, name))

        # 右侧：设置
        right_frame = ttk.Frame(tab, width=240)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        # 状态显示
        status_frame = ttk.LabelFrame(right_frame, text="状态", padding=10)
        status_frame.pack(fill="x", pady=(0, 10))
        self.lbl_sj_power = ttk.Label(status_frame, text="当前体力: 未知", font=("Arial", 11, "bold"))
        self.lbl_sj_power.pack(anchor="w")
        self.lbl_sj_week = ttk.Label(status_frame, text="镜域周剩余: 未知", font=("Arial", 11, "bold"), foreground="green")
        self.lbl_sj_week.pack(anchor="w", pady=(5, 0))

        # 刷取设置
        setting_frame = ttk.LabelFrame(right_frame, text="刷取设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(setting_frame, text="刷取次数:").grid(row=0, column=0, sticky="w", pady=5)
        self.var_sj_times = tk.IntVar(value=1)
        ttk.Spinbox(setting_frame, from_=1, to=50, textvariable=self.var_sj_times, width=10).grid(row=0, column=1, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=1, column=0, sticky="w", pady=5)
        self.var_sj_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_sj_delay, width=10).grid(row=1, column=1, pady=5)

        ttk.Label(setting_frame, text="⚠ 体力/次数不足自动停止", foreground="red").grid(row=2, column=0, columnspan=2, sticky="w", pady=5)

        self.btn_sj_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_shenyu_jingyu, state="disabled")
        self.btn_sj_run.grid(row=3, column=0, columnspan=2, pady=10)

        boss_frame = ttk.LabelFrame(right_frame, text="神域BOSS选择", padding=8)
        boss_frame.pack(fill="x", pady=(0, 10))
        self.sj_boss_choice = ttk.Combobox(boss_frame, state="disabled", width=27)
        self.sj_boss_choice.pack(fill="x")
        self.lbl_sj_boss_hint = ttk.Label(boss_frame, text="选择神域关卡后显示目标BOSS。", wraplength=210, justify="left")
        self.lbl_sj_boss_hint.pack(anchor="w", pady=(6, 0))
        self.sy_listbox.bind("<<ListboxSelect>>", self._update_sj_boss_choices)
        self.jy_listbox.bind("<<ListboxSelect>>", self._select_sj_mirror)
        self.sj_boss_choice.bind("<<ComboboxSelected>>", self._update_sj_boss_hint)
        self._sj_boss_targets = []

        # 掉落统计
        drop_frame = ttk.LabelFrame(right_frame, text="掉落统计", padding=10)
        drop_frame.pack(fill="both", expand=True)
        self.txt_sj_drops = tk.Text(drop_frame, height=8, width=26)
        self.txt_sj_drops.pack(fill="both", expand=True)

    def _select_sj_mirror(self, event=None):
        if self.jy_listbox.curselection():
            self.sy_listbox.selection_clear(0, tk.END)
            self._sj_boss_targets = []
            self.sj_boss_choice.config(values=(), state="disabled")
            self.sj_boss_choice.set("")
            self.lbl_sj_boss_hint.config(text="镜域按所选关卡执行，不使用神域BOSS选择。")

    def _update_sj_boss_choices(self, event=None):
        selection = self.sy_listbox.curselection()
        if not selection:
            return
        self.jy_listbox.selection_clear(0, tk.END)
        mid, _ = SHENYU_LEVELS[selection[0]]
        targets = {
            9002: [(9002, "吉祥天女（enterW=0）"), (9003, "海皇摩蹉（隐藏，enterW=1）")],
            9005: [(9006, "雪山神女")],
            9007: [(9007, "鸠摩罗（enterW=0）"), (9008, "伽内什（隐藏，enterW=1）")],
            9009: [(9011, "湿婆·善/恶（魂铃，推荐）"), (9010, "湿婆分身（不掉魂铃）")],
            9012: [(9013, "达刹")],
            9014: [(9015, "妙音天女"), (9016, "伐楼拿")],
            9017: [(9018, "梵天")],
        }.get(mid, [])
        self._sj_boss_targets = targets
        self._sj_boss_mid = mid
        if targets:
            self.sj_boss_choice.config(values=["%s (%d)" % (name, bid) for bid, name in targets], state="readonly")
            self.sj_boss_choice.current(0)
        else:
            self.sj_boss_choice.config(values=(), state="disabled")
            self.sj_boss_choice.set("本关BOSS")
        self._update_sj_boss_hint()

    def _update_sj_boss_hint(self, event=None):
        targets = getattr(self, "_sj_boss_targets", [])
        index = self.sj_boss_choice.current()
        if not targets:
            text = "直接刷所选关卡的BOSS，无独立隐藏房。"
        elif 0 <= index < len(targets):
            bid, name = targets[index]
            if bid == getattr(self, "_sj_boss_mid", None):
                text = "本次目标：%s。直接结算本关，enterW=0，不进入隐藏房；每轮消耗120体力。" % name
            else:
                text = "本次目标：%s。每轮先以enterW=1通关前置，再仅进入所选BOSS房；消耗120体力。" % name
            if bid == 9010:
                text += "分身会占用隐藏入口，本轮不会再打9011。"
        else:
            text = "请选择目标BOSS。"
        self.lbl_sj_boss_hint.config(text=text)

    def _get_jingyu_week_remain(self, cur):
        """计算镜域周剩余次数：10 - 所有90001-90012关卡的num之和"""
        copy_history = cur.get("copyHistory", [])
        used = 0
        for h in copy_history:
            if isinstance(h, dict):
                hid = int(h.get("id", 0))
                if 90001 <= hid <= 90012:
                    used += int(h.get("num", 0))
        return max(0, 10 - used)

    def _do_shenyu_jingyu(self):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return

        # 判断选的是神域还是镜域
        sy_sel = self.sy_listbox.curselection()
        jy_sel = self.jy_listbox.curselection()

        if sy_sel and jy_sel:
            messagebox.showwarning("提示", "只能选择神域或镜域中的一个关卡")
            return
        if not sy_sel and not jy_sel:
            messagebox.showwarning("提示", "请选择关卡")
            return

        if sy_sel:
            mid, level_name = SHENYU_LEVELS[sy_sel[0]]
            power_cost = 120
            mode = "神域"
        else:
            mid, level_name = JINGYU_LEVELS[jy_sel[0]]
            power_cost = 0
            mode = "镜域"

        from official_sweep import dispatch
        if dispatch(self, "shenyu", [mid], self.var_sj_times.get()):
            return

        selected_bosses = []
        selected_target = None
        if mode == "神域":
            if getattr(self, "_sj_boss_mid", None) != mid:
                self._update_sj_boss_choices()
            targets = getattr(self, "_sj_boss_targets", [])
            if targets:
                index = self.sj_boss_choice.current()
                if index < 0 or index >= len(targets):
                    messagebox.showwarning("提示", "请选择目标BOSS")
                    return
                selected_target = targets[index]
                if selected_target[0] != mid:
                    selected_bosses = [selected_target]
        times = self.var_sj_times.get()
        delay = self.var_sj_delay.get()

        self.btn_sj_run.config(state="disabled")
        self.txt_sj_drops.delete("1.0", tk.END)

        def worker():
            try:
                flow, entry, scene = self._connect_and_enter()
                cur = scene.get("curRecord", {})
                p1 = cur.get("p1", {})
                current_exp = p1.get("experience", 0)
                property_p1_str = "%d;%d;%d;%d;%d;%d" % (p1.get("hpMax",0), p1.get("mpMax",0), p1.get("atk",0), p1.get("phyDef",0), p1.get("reHP",0), p1.get("reMP",0))

                current_power = cur.get("collectPower", 0)
                week_remain = self._get_jingyu_week_remain(cur)
                self.root.after(0, lambda p=current_power: self.lbl_sj_power.config(text="当前体力: %d" % p))
                self.root.after(0, lambda w=week_remain: self.lbl_sj_week.config(text="镜域周剩余: %d" % w))
                self._log("[%s刷取] 开始: %s (%d), %s, %d次" % (mode, level_name, mid, "120体力/次" if power_cost>0 else "0体力", times))

                self._log("[神域目标] %s" % (selected_target[1] if selected_target else "所选关卡本身"))

                # 魂器独立背包 soulBag 只随登录后的 onSendRecord 推送下发，稍等再读
                for _ in range(10):
                    if getattr(self, "_soul_bag", None):
                        break
                    time.sleep(0.3)
                soul_cap, soul_used, soul_free = self._soul_bag_summary(getattr(self, "_soul_bag", None))
                soul_confirmed = 0
                soul_dropped = 0
                if soul_cap:
                    self._log("[魂器背包] 容量%s 已用%d 剩余%s" % (soul_cap, soul_used, soul_free))
                else:
                    self._log("[魂器背包] 未读到 soulBag 推送，无法核对魂器入包")

                # 道具背包余量预检：道具落在 itemsBag，格子不足时结算会 500 且掉落直接丢失
                ib = cur.get("itemsBag") or {}
                bag_cap = ib.get("itemCount") or 0
                bag_used = len(ib.get("items") or [])
                bag_free = max(0, bag_cap - bag_used)
                self._log("[道具背包] 已用%d/%d 剩余%d" % (bag_used, bag_cap, bag_free))
                if bag_cap and bag_free < 5:
                    self._log("[%s刷取] 道具背包剩余不足5格，已停止（避免结算500丢掉落），请先清理背包" % mode)
                    flow.disconnect()
                    return

                # 加载道具名称
                prop_map = {}
                try:
                    config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
                    for fname in ("150___Prop.xml.json", "188___Soul.xml.json"):
                        with open(os.path.join(config_dir, fname), encoding='utf-8') as f:
                            prop_data = json.load(f)
                        records = prop_data.get('RECORD', prop_data if isinstance(prop_data, list) else [])
                        if isinstance(records, dict): records = [records]
                        for r in records:
                            if isinstance(r, dict): prop_map[str(r.get('id'))] = r.get('name', '?')
                except: pass

                drop_stats = {}
                success = 0
                fail = 0
                power_used = 0

                for i in range(times):
                    # 检查体力
                    if power_cost > 0 and current_power < power_cost:
                        self._log("  体力不足(%d<%d)，停止" % (current_power, power_cost))
                        break
                    # 检查镜域周次数
                    if power_cost == 0 and week_remain <= 0:
                        self._log("  镜域周次数已用完，停止")
                        break

                    try:
                        create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {
                            "mid": mid, "costGem": 0
                        }, timeout=15)
                        if create_result.get("code") != 200:
                            err = create_result.get("error", "")
                            fail += 1
                            self._log("  第%d次创建失败: %s" % (i+1, err))
                            if "前置" in err or "等级" in err or "次数" in err:
                                break
                            continue

                        drops = create_result.get("drops", {})
                        copy_id = drops.get("copyId", 0)
                        new_drops = drops.get("newDrops", [])

                        pick_items = []
                        mob_ids = []
                        kill_monsters = []
                        total_exp = 0
                        total_sp = 0

                        for d in new_drops:
                            d_mid = d.get("monsterId", "0")
                            d_idx = d.get("index", 0)
                            total_exp += d.get("exp", 0)
                            total_sp += d.get("spirit", 0)
                            for _field, group in drop_groups(d):
                                mob_ids.append(d_mid)
                                kill_monsters.append("%s_%d" % (d_mid, d_idx))
                                for item_id, item_list in group.items():
                                    for item in item_list:
                                        pick_items.append(item)
                                        drop_stats[item_id] = drop_stats.get(item_id, 0) + 1
                            for soul_id, soul_inst in soul_items(d):
                                mob_ids.append(d_mid)
                                kill_monsters.append("%s_%d" % (d_mid, d_idx))
                                pick_items.append(soul_inst)
                                drop_stats[soul_id] = drop_stats.get(soul_id, 0) + 1
                                soul_dropped += 1
                                sname = prop_map.get(soul_id, soul_id)
                                self._log("  ★ 魂器掉落: %s(%s) 实例=%s" % (sname, soul_id, soul_inst))

                        time.sleep(delay / 3)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.3)
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                        time.sleep(delay / 3)

                        sync_data = {
                            "copyId": copy_id,
                            "pickItems": pick_items,
                            "mobIds": mob_ids,
                            "killMonsters": kill_monsters,
                            "completed": 1,
                            "currentEXP": current_exp,
                            "pickExp": total_exp,
                            "pickSp": total_sp,
                            "propertyP1Str": property_p1_str,
                            "propertyP2Total": 0,
                            "hitCombo": 100,
                        }
                        # 普通关通关时提交 enterW=1，解锁本次隐藏房入口。
                        if mode == "神域" and selected_bosses:
                            sync_data["enterW"] = 1
                            sync_data["completed"] |= 16777216
                        elif mode == "神域":
                            sync_data["enterW"] = 0
                        sync_result = flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                        if sync_result.get("code") == 200:
                            success += 1
                            if power_cost > 0:
                                current_power -= power_cost
                                power_used += power_cost
                            else:
                                week_remain -= 1
                            self.root.after(0, lambda p=current_power: self.lbl_sj_power.config(text="当前体力: %d" % p))
                            self.root.after(0, lambda w=week_remain: self.lbl_sj_week.config(text="镜域周剩余: %d" % w))
                            soul_confirmed += self._confirm_new_souls(sync_result, "普通关", prop_map)

                            # 神域：自动打隐藏关/BOSS房
                            if mode == "神域" and selected_bosses:
                                for hidden_mid, hidden_name in selected_bosses:
                                    try:
                                        self._log("  -> 打隐藏关: %s (%d)" % (hidden_name, hidden_mid))
                                        h_create = flow.request("scene.copyHandler.createSinglePlayerCopy", {
                                            "mid": hidden_mid, "costGem": 0
                                        }, timeout=15)
                                        if h_create.get("code") != 200:
                                            self._log("    隐藏关创建失败: %s" % h_create.get("error", ""))
                                            continue
                                        h_drops = h_create.get("drops", {})
                                        h_copy_id = h_drops.get("copyId", 0)
                                        h_new_drops = h_drops.get("newDrops", [])

                                        h_pick = []
                                        h_mobs = []
                                        h_kills = []
                                        h_exp = 0
                                        h_sp = 0
                                        for d in h_new_drops:
                                            d_mid = d.get("monsterId", "0")
                                            d_idx = d.get("index", 0)
                                            h_exp += d.get("exp", 0)
                                            h_sp += d.get("spirit", 0)
                                            if "item" in d and len(d["item"]) > 0:
                                                h_mobs.append(d_mid)
                                                h_kills.append("%s_%d" % (d_mid, d_idx))
                                                for item_id, item_list in d["item"].items():
                                                    for item in item_list:
                                                        h_pick.append(item)
                                                        drop_stats[item_id] = drop_stats.get(item_id, 0) + 1
                                                        iname = prop_map.get(str(item_id), str(item_id))
                                                        self._log("    隐藏关掉落: %s(%s)" % (iname, item_id))
                                            for soul_id, soul_inst in soul_items(d):
                                                h_mobs.append(d_mid)
                                                h_kills.append("%s_%d" % (d_mid, d_idx))
                                                h_pick.append(soul_inst)
                                                drop_stats[soul_id] = drop_stats.get(soul_id, 0) + 1
                                                soul_dropped += 1
                                                sname = prop_map.get(soul_id, soul_id)
                                                self._log("    ★ 隐藏关魂器: %s(%s) 实例=%s" % (sname, soul_id, soul_inst))

                                        time.sleep(delay / 3)
                                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                                        time.sleep(0.3)
                                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": hidden_mid}, timeout=15)
                                        time.sleep(delay / 3)
                                        h_sync = flow.request("scene.copyHandler.syncDropInfoNew", {
                                            "copyId": h_copy_id, "pickItems": h_pick, "mobIds": h_mobs,
                                            "killMonsters": h_kills, "completed": 1,
                                            "currentEXP": current_exp, "pickExp": h_exp, "pickSp": h_sp,
                                            "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                                        }, timeout=15)
                                        if h_sync.get("code") != 200:
                                            self._log("    隐藏关sync失败: %s" % h_sync.get("error", ""))
                                        else:
                                            soul_confirmed += self._confirm_new_souls(h_sync, "隐藏关", prop_map)
                                        break
                                    except Exception as he:
                                        self._log("    隐藏关异常: %s" % he)
                                        break
                        else:
                            fail += 1
                            self._log("  第%d次同步失败: %s" % (i+1, sync_result.get("error")))

                        self._log("  [%d/%d] 成功%d 失败%d%s" % (i+1, times, success, fail, " 已用体力%d 剩余%d" % (power_used, current_power) if power_cost>0 else " 周剩余%d" % week_remain))

                        # 更新掉落统计
                        drop_text = ""
                        for iid, cnt in sorted(drop_stats.items(), key=lambda x: -x[1]):
                            drop_text += "%s: %d\n" % (iid, cnt)
                        self.root.after(0, lambda t=drop_text: self.txt_sj_drops.delete("1.0", tk.END) or self.txt_sj_drops.insert("1.0", t))

                        time.sleep(delay / 3)
                    except Exception as e:
                        fail += 1
                        self._log("  第%d次异常: %s" % (i+1, e))
                        time.sleep(1)

                self._log("[%s刷取] 完成! 成功%d 失败%d%s" % (mode, success, fail, " 消耗体力%d" % power_used if power_cost>0 else ""))
                self._log("[魂器] 本次掉落%d，确认入包%d" % (soul_dropped, soul_confirmed))
                if soul_dropped > soul_confirmed:
                    self._log("[魂器] 警告: 有%d件魂器未在 add.newSouls 中确认入包，建议去游戏中核对魂器背包" % (soul_dropped - soul_confirmed))
                flow.disconnect()
            except Exception as e:
                self._log("[%s刷取] 异常: %s" % (mode, e))
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self.btn_sj_run.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


# ========== 打造刷属性标签页 ==========
    def _build_craft_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="打造刷属性")

        # 制作书设置
        book_frame = ttk.LabelFrame(tab, text="制作书设置", padding=8)
        book_frame.pack(fill="x", pady=5)

        ttk.Label(book_frame, text="制作书:").grid(row=0, column=0, sticky="w", padx=5, pady=3)
        self.var_craft_book = tk.StringVar()
        self.craft_book_combo = ttk.Combobox(book_frame, textvariable=self.var_craft_book, width=35, state="readonly")
        self.craft_book_combo["values"] = self._craft_book_options
        self.craft_book_combo.current(0)
        self.craft_book_combo.grid(row=0, column=1, padx=5, pady=3, columnspan=3)
        self.craft_book_combo.bind("<<ComboboxSelected>>", self._on_craft_book_select)

        # 装备属性范围显示
        attr_frame = ttk.LabelFrame(tab, text="装备属性范围", padding=8)
        attr_frame.pack(fill="x", pady=5)
        self.lbl_craft_equip_name = ttk.Label(attr_frame, text="选择制作书后显示", foreground="gray")
        self.lbl_craft_equip_name.pack(anchor="w")
        self.text_craft_attrs = scrolledtext.ScrolledText(attr_frame, wrap="word", font=("Consolas", 9), height=5)
        self.text_craft_attrs.pack(fill="x", pady=3)

        # 词条设置（动态多词条）
        attr_frame = ttk.LabelFrame(tab, text="词条期待值（勾选要检测的词条，设定最低值）", padding=8)
        attr_frame.pack(fill="x", pady=5)

        # 动态词条检查区域
        self.craft_attr_container = ttk.Frame(attr_frame)
        self.craft_attr_container.pack(fill="x", pady=3)
        self.craft_attr_vars = {}

        # 通用设置
        common_frame = ttk.Frame(attr_frame)
        common_frame.pack(fill="x", pady=3)
        ttk.Label(common_frame, text="最大打造次数:").pack(side="left", padx=5)
        self.var_craft_maxrun = tk.StringVar(value="20")
        ttk.Entry(common_frame, textvariable=self.var_craft_maxrun, width=8).pack(side="left", padx=5)
        ttk.Label(common_frame, text="（所有勾选词条全部达标才保留）", foreground="gray").pack(side="left", padx=10)


        # 材料显示
        mat_frame = ttk.LabelFrame(tab, text="材料状态", padding=8)
        mat_frame.pack(fill="x", pady=5)
        self.lbl_craft_mats = ttk.Label(mat_frame, text="登录后显示材料", foreground="gray")
        self.lbl_craft_mats.pack(anchor="w")

        # 操作按钮
        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill="x", pady=10)
        ttk.Button(btn_frame, text="开始打造刷属性", command=self._do_craft, width=20).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="刷新材料", command=self._refresh_craft_mats, width=12).pack(side="left", padx=5)

        # 结果显示
        result_frame = ttk.LabelFrame(tab, text="打造记录", padding=8)
        result_frame.pack(fill="both", expand=True, pady=5)
        self.text_craft_log = scrolledtext.ScrolledText(result_frame, wrap="word", font=("Consolas", 9), height=8)
        self.text_craft_log.pack(fill="both", expand=True)

    def _on_craft_book_select(self, event=None):
        """选中制作书时显示装备属性范围，并动态生成词条检查项"""
        sel = self.var_craft_book.get()
        book_id = self._craft_book_ids.get(sel)
        if not book_id:
            return
        info = self._craft_equip_attrs.get(str(book_id))
        if not info:
            self.lbl_craft_equip_name.config(text="未找到装备信息", foreground="red")
            self.text_craft_attrs.delete("1.0", tk.END)
            # 清空词条检查项
            for w in self.craft_attr_container.winfo_children():
                w.destroy()
            self.craft_attr_vars = {}
            return
        self.lbl_craft_equip_name.config(
            text="%s (ID:%s, 品质:%s, 部位:%s)" % (
                info['equip_name'], info['equip_id'], info['quality'], info.get('part', '')),
            foreground="black"
        )
        self.text_craft_attrs.delete("1.0", tk.END)
        for attr, v in info['attrs'].items():
            if v['min'] == v['max']:
                line = "%s: %.2f (固定)\n" % (attr, v['min'])
            else:
                line = "%s: %.2f ~ %.2f\n" % (attr, v['min'], v['max'])
            self.text_craft_attrs.insert(tk.END, line)

        # 动态生成词条检查项
        for w in self.craft_attr_container.winfo_children():
            w.destroy()
        self.craft_attr_vars = {}

        attrs = list(info['attrs'].keys())
        cols = 4
        for i, attr in enumerate(attrs):
            row = i // cols
            col = (i % cols) * 3
            frame = ttk.Frame(self.craft_attr_container)
            frame.grid(row=row, column=col, sticky="w", padx=5, pady=2)

            check_var = tk.BooleanVar(value=False)
            cb = ttk.Checkbutton(frame, text=attr, variable=check_var)
            cb.pack(side="left")

            min_var = tk.StringVar(value="%.0f" % info['attrs'][attr]['max'])
            entry = ttk.Entry(frame, textvariable=min_var, width=8)
            entry.pack(side="left", padx=3)

            ttk.Label(frame, text="(%.0f~%.0f)" % (info['attrs'][attr]['min'], info['attrs'][attr]['max']),
                      foreground="gray", font=("Arial", 8)).pack(side="left")

            self.craft_attr_vars[attr] = (check_var, min_var)

    def _refresh_craft_mats(self):
        """刷新材料显示"""
        if not self.flow:
            self._log("[打造] 请先登录")
            return
        try:
            scene = self.flow.request("scene.playerHandler.enterScene", None, timeout=15)
            items = scene.get("curRecord", {}).get("itemsBag", {}).get("items", [])
            book_sel = self.var_craft_book.get()
            book_id = str(self._craft_book_ids.get(book_sel, 119460002))
            book_count = 0
            qicai = 0
            yuying = 0
            for item in items:
                iid = str(item.get("id", item.get("itemId", "")))
                if iid == book_id:
                    book_count = item.get("count", 0)
                if iid == "103000004":
                    qicai = item.get("count", 0)
                if iid == "102000004":
                    yuying = item.get("count", 0)
            self.lbl_craft_mats.config(
                text="制作书(%s): %d本 | 七彩晶: %d/120 | 玉荧草: %d/60" % (book_id, book_count, qicai, yuying),
                foreground="black"
            )
        except Exception as e:
            self.lbl_craft_mats.config(text="刷新失败: %s" % e, foreground="red")

    def _do_craft(self):
        """打造刷属性主逻辑"""
        if not self.flow:
            self._log("[打造] 请先登录并选择存档")
            return
        if self.running:
            self._log("[打造] 已有任务在运行")
            return
        self.running = True
        self.text_craft_log.delete("1.0", tk.END)

        def craft_worker():
            try:
                book_sel = self.var_craft_book.get()
                book_id = self._craft_book_ids.get(book_sel, 119460002)
                # 读取所有勾选的词条
                checked_attrs = {}
                for attr_name, (check_var, min_var) in self.craft_attr_vars.items():
                    if check_var.get():
                        try:
                            checked_attrs[attr_name] = float(min_var.get())
                        except:
                            checked_attrs[attr_name] = 0
                max_run = int(self.var_craft_maxrun.get())

                self._log("[打造] 制作书=%d 检测词条=%s 最大次数=%d" % (book_id, list(checked_attrs.keys()), max_run))
                self.text_craft_log.insert(tk.END, "制作书=%d 词条=%s\n" % (book_id, list(checked_attrs.keys())))
                self.text_craft_log.see(tk.END)

                for i in range(max_run):
                    if not self.running:
                        self._log("[打造] 已停止")
                        break

                    # 检查材料
                    scene = self.flow.request("scene.playerHandler.enterScene", None, timeout=15)
                    items = scene.get("curRecord", {}).get("itemsBag", {}).get("items", [])
                    book_count = 0
                    qicai = 0
                    yuying = 0
                    for item in items:
                        iid = str(item.get("id", item.get("itemId", "")))
                        if iid == str(book_id):
                            book_count = item.get("count", 0)
                        if iid == "103000004":
                            qicai = item.get("count", 0)
                        if iid == "102000004":
                            yuying = item.get("count", 0)

                    if book_count <= 0:
                        self._log("[打造] 制作书不足，停止")
                        self.text_craft_log.insert(tk.END, "[%d] 制作书不足，停止\n" % (i+1))
                        break
                    if qicai < 120 or yuying < 60:
                        self._log("[打造] 材料不足 (七彩晶=%d/120 玉荧草=%d/60)，停止" % (qicai, yuying))
                        self.text_craft_log.insert(tk.END, "[%d] 材料不足，停止\n" % (i+1))
                        break

                    # 打造
                    result = self.flow.request("scene.equipHandler.makingItem", {"makeId": book_id}, timeout=15)
                    if result.get("code") != 200:
                        self._log("[打造] 第%d次打造失败: %s" % (i+1, result.get("error")))
                        self.text_craft_log.insert(tk.END, "[%d] 打造失败: %s\n" % (i+1, result.get("error")))
                        break

                    item = result.get("item", {})
                    entity_id = item.get("entityId", "")
                    item_id = item.get("id", 0)

                    # 检查所有勾选的词条
                    all_pass = True
                    check_details = []
                    for attr_name, min_v in checked_attrs.items():
                        actual_val = item.get(attr_name, 0)
                        try:
                            actual_val = float(actual_val)
                        except:
                            actual_val = 0
                        passed = actual_val >= min_v
                        check_details.append("%s=%.1f%s%.1f" % (attr_name, actual_val, "✓" if passed else "✗", min_v))
                        if not passed:
                            all_pass = False

                    log_line = "[%d] 打造成功 id=%s %s" % (i+1, item_id, ", ".join(check_details))
                    self._log(log_line)

                    if not checked_attrs:
                        log_line += " (未勾选词条，保留)"
                        self.text_craft_log.insert(tk.END, log_line + "\n")
                        self.text_craft_log.see(tk.END)
                        break

                    if all_pass:
                        log_line += " ✓ 全部达标，保留!"
                        self.text_craft_log.insert(tk.END, log_line + "\n")
                        self.text_craft_log.see(tk.END)
                        self._log("[打造] 达标! 全部词条满足，装备已保留")
                        break
                    else:
                        log_line += " ✗ 未达标，出售"
                        self.text_craft_log.insert(tk.END, log_line + "\n")
                        self.text_craft_log.see(tk.END)

                        sell_result = self.flow.request("scene.playerHandler.sellItem", {
                            "itemId": item_id,
                            "entityId": entity_id,
                            "bagType": 0
                        }, timeout=15)
                        if sell_result.get("code") == 200:
                            self._log("[打造] 已出售 entityId=%s" % entity_id)
                        else:
                            self._log("[打造] 出售失败: %s" % sell_result)

                    time.sleep(1)

                self._log("[打造] 完成!")
                self.root.after(0, lambda: self._refresh_craft_mats())
            except Exception as e:
                self._log("[打造] 异常: %s" % e)
                import traceback
                traceback.print_exc()
            finally:
                self.running = False

        threading.Thread(target=craft_worker, daemon=True).start()



    # ========== 隐藏BOSS标签页 ==========
    def _build_hideboss_tab(self):
        tab = ttk.Frame(self.mainfarm_notebook, padding=10)
        self.mainfarm_notebook.add(tab, text="隐藏BOSS")

        # 左侧：关卡列表
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        list_frame = ttk.LabelFrame(left_frame, text="选择隐藏BOSS关卡", padding=5)
        list_frame.pack(fill="both", expand=True)

        self.hide_listbox = tk.Listbox(list_frame, width=40, height=15)
        self.hide_listbox.pack(fill="both", expand=True)

        HIDE_BOSS_ITEMS = [
            "7 普陀山脚 -> 普陀隐藏",
            "9 法华灵洞 -> 法华灵洞-BOSS",
            "13 五台山口 -> 五台隐藏",
            "19 傲来国 -> 傲来国-BOSS",
            "23 蝙蝠窟 -> 蝙蝠窟-BOSS",
            "31 寒山坡 -> 寒山隐藏",
            "34 幻境阁 -> 幻境阁隐藏",
            "37 太虚星河 -> 太虚星河隐藏",
            "40 凌云渡 -> 凌云渡",
            "43 七叶树窟 -> 七叶树窟",
            "45 幕山 -> 幕山",
            "47 孤魂岭 -> 孤魂岭-BOSS",
            "48 通冥铁索 -> 亚窳 + 波儿象(需enterW)",
            "49 播冢山巅 -> 播冢山巅-BOSS",
            "50 罗浮山 -> 罗浮山-BOSS",
            "51 岁暮荒园 -> 冥蛊师 + 蛇骨婆母(需enterW)",
            "52 梦影寺 -> 梦影寺-BOSS",
            "53 抱犊山 -> 抱犊山-BOSS",
            "54 彼岸花海 -> 花妖曼珠 + 叶妖沙华(需enterW)",
            "55 往生路 -> 往生路-BOSS",
            "56 罗酆谷 -> 罗酆谷-BOSS",
            "57 九泉 -> 摆渡冥将 + 九渊鬼王(需enterW)",
            "58 业火莲台 -> 业火莲台-BOSS",
            "59 桃止山 -> 桃止山-BOSS",
            "60 幽都鬼城 -> 幽冥鬼母 + 幽冥鬼子(需enterW)",
            "61 万世冥阁 -> 万世冥阁-BOSS",
            "62 血河池 -> 血河池二阶段",
            "63 天禄金山 -> 天禄金山_BOSS",
            "64 伏龙宝树 -> 伏藏龙 + 魔将百臂(需enterW)",
            "65 金蟾宝宫 -> 金蟾宝宫-BOSS",
            "9014 永生泉 -> 妙音天女(需enterW) + 伐楼拿",
            "501 噩梦通冥铁索 -> 噩梦亚窳 + 噩梦波儿象(需enterW)",
            "504 噩梦岁暮荒园 -> 噩梦冥蛊师 + 噩梦蛇鬼婆母(需enterW)",
        ]
        for item in HIDE_BOSS_ITEMS:
            self.hide_listbox.insert(tk.END, item)
        self.hide_listbox.selection_set(0)

        # 右侧：设置
        right_frame = ttk.Frame(tab, width=260)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        setting_frame = ttk.LabelFrame(right_frame, text="刷取设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        ttk.Label(setting_frame, text="刷取次数:").grid(row=0, column=0, sticky="w", pady=5)
        self.var_hide_times = tk.IntVar(value=1)
        ttk.Spinbox(setting_frame, from_=1, to=50, textvariable=self.var_hide_times, width=10).grid(row=0, column=1, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=1, column=0, sticky="w", pady=5)
        self.var_hide_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_hide_delay, width=10).grid(row=1, column=1, pady=5)

        self.var_hide_boss1 = tk.BooleanVar(value=True)
        self.var_hide_boss2 = tk.BooleanVar(value=True)
        ttk.Checkbutton(setting_frame, text="打隐藏BOSS1", variable=self.var_hide_boss1).grid(row=2, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Checkbutton(setting_frame, text="打隐藏BOSS2", variable=self.var_hide_boss2).grid(row=3, column=0, columnspan=2, sticky="w", pady=3)

        self.btn_hide_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_hideboss, state="disabled")
        self.btn_hide_run.grid(row=4, column=0, columnspan=2, pady=10)

        # 说明
        info_frame = ttk.LabelFrame(right_frame, text="说明", padding=8)
        info_frame.pack(fill="both", expand=True)
        info_text = (
            "隐藏BOSS进入机制:\n"
            "1. 先通关普通关卡\n"
            "2. 部分BOSS需在syncDrop时\n"
            "   带enterW=1才能进入\n"
            "3. 然后创建隐藏BOSS关卡\n"
            "4. 通关隐藏BOSS获取掉落\n"
            "\n"
            "掉落物: 武器宝箱等\n奖励模式沿用主线刷取设置"
        )
        ttk.Label(info_frame, text=info_text, justify="left", foreground="#333").pack(anchor="w")

    def _do_hideboss(self):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        selection = self.hide_listbox.curselection()
        if not selection:
            messagebox.showwarning("提示", "请选择关卡")
            return
        idx = selection[0]
        times = self.var_hide_times.get()
        delay = self.var_hide_delay.get()
        boss1 = self.var_hide_boss1.get()
        boss2 = self.var_hide_boss2.get()

        HIDE_CONFIG = [
            {"normal": 7, "boss1": 1005, "boss1_name": "普陀隐藏", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 9, "boss1": 1001, "boss1_name": "法华灵洞-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 13, "boss1": 1010, "boss1_name": "五台隐藏", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 19, "boss1": 1009, "boss1_name": "傲来国-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 23, "boss1": 1012, "boss1_name": "蝙蝠窟-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 31, "boss1": 1016, "boss1_name": "寒山隐藏", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 34, "boss1": 1017, "boss1_name": "幻境阁隐藏", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 37, "boss1": 1019, "boss1_name": "太虚星河隐藏", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 40, "boss1": 1020, "boss1_name": "凌云渡", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 43, "boss1": 1021, "boss1_name": "七叶树窟", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 45, "boss1": 1022, "boss1_name": "幕山", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": True},
            {"normal": 47, "boss1": 1025, "boss1_name": "孤魂岭-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 48, "boss1": 1026, "boss1_name": "亚窳", "boss2": 1027, "boss2_name": "波儿象", "need_enterw": True, "direct": False},
            {"normal": 49, "boss1": 1028, "boss1_name": "播冢山巅-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 50, "boss1": 1029, "boss1_name": "罗浮山-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 51, "boss1": 1030, "boss1_name": "冥蛊师", "boss2": 1031, "boss2_name": "蛇骨婆母", "need_enterw": True, "direct": False},
            {"normal": 52, "boss1": 1033, "boss1_name": "梦影寺-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 53, "boss1": 1034, "boss1_name": "抱犊山-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 54, "boss1": 1035, "boss1_name": "花妖曼珠", "boss2": 1036, "boss2_name": "叶妖沙华", "need_enterw": True, "direct": False},
            {"normal": 55, "boss1": 1037, "boss1_name": "往生路-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 56, "boss1": 1038, "boss1_name": "罗酆谷-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 57, "boss1": 1040, "boss1_name": "摆渡冥将", "boss2": 1041, "boss2_name": "九渊鬼王", "need_enterw": True, "direct": False},
            {"normal": 58, "boss1": 1042, "boss1_name": "业火莲台-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 59, "boss1": 1043, "boss1_name": "桃止山-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 60, "boss1": 1044, "boss1_name": "幽冥鬼母", "boss2": 1045, "boss2_name": "幽冥鬼子", "need_enterw": True, "direct": False},
            {"normal": 61, "boss1": 1046, "boss1_name": "万世冥阁-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 62, "boss1": 1047, "boss1_name": "血河池二阶段", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 63, "boss1": 1048, "boss1_name": "天禄金山_BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 64, "boss1": 1049, "boss1_name": "伏藏龙", "boss2": 1050, "boss2_name": "魔将百臂", "need_enterw": True, "direct": False},
            {"normal": 65, "boss1": 1051, "boss1_name": "金蟾宝宫-BOSS", "boss2": None, "boss2_name": "", "need_enterw": False, "direct": False},
            {"normal": 9014, "boss1": 9015, "boss1_name": "妙音天女", "boss2": 9016, "boss2_name": "伐楼拿", "need_enterw": True, "direct": False},
            {"normal": 501, "boss1": 10260, "boss1_name": "噩梦亚窳", "boss2": 10270, "boss2_name": "噩梦波儿象", "need_enterw": True, "direct": False},
            {"normal": 504, "boss1": 10300, "boss1_name": "噩梦冥蛊师", "boss2": 10310, "boss2_name": "噩梦蛇鬼婆母", "need_enterw": True, "direct": False},
        ]
        config = HIDE_CONFIG[idx]
        reward_label = self.var_main_reward_mode.get()
        reward_mode = self._main_reward_modes.get(reward_label, "all")

        self.btn_hide_run.config(state="disabled")

        def worker():
            try:
                flow, entry, cur = self._connect_and_enter()
                p1 = entry.get("record", {}).get("p1", {})
                current_exp = p1.get("experience", 0)
                property_p1_str = "%d;%d;%d;%d;%d;%d" % (p1.get("hpMax",0), p1.get("mpMax",0), p1.get("atk",0), p1.get("phyDef",0), p1.get("reHP",0), p1.get("reMP",0))

                self._log("[隐藏BOSS] 开始: 普通关%d, %s+%s, %d次" % (config["normal"], config["boss1_name"], config["boss2_name"], times))

                self._log("[隐藏BOSS] 奖励模式：%s" % reward_label)
                drop_stats = {}
                success = 0
                fail = 0

                def clear_copy(mid, enterw=False):
                    from mainfarm_routes import clear_stage
                    try:
                        result = clear_stage(flow, cur, mid, enterw, pick_equips=True,
                                             reward_mode=reward_mode)
                    except Exception as error:
                        return None, str(error)
                    for item_id, count in result["counts"].items():
                        drop_stats[item_id] = drop_stats.get(item_id, 0) + count
                    return result["settled"], ""

                for i in range(times):
                    try:
                        # 1. 通关普通关卡（direct关卡不需要通关普通关）
                        if not config.get("direct", False):
                            r, err = clear_copy(config["normal"], enterw=config["need_enterw"])
                            if r is None:
                                self._log("  第%d次 普通关创建失败: %s" % (i+1, err))
                                fail += 1
                                continue
                            if r.get("code") != 200:
                                self._log("  第%d次 普通关同步失败: %s" % (i+1, r.get("error")))
                            time.sleep(delay / 3)

                        # 2. 打隐藏BOSS1
                        if boss1 and config.get("boss1"):
                            r1, err1 = clear_copy(config["boss1"])
                            if r1 is None:
                                self._log("  第%d次 %s创建失败: %s" % (i+1, config["boss1_name"], err1))
                            elif r1.get("code") == 200:
                                self._log("  第%d次 %s 通关成功" % (i+1, config["boss1_name"]))
                            else:
                                self._log("  第%d次 %s 同步失败: %s" % (i+1, config["boss1_name"], r1.get("error")))
                            time.sleep(delay / 3)

                        # 3. 打隐藏BOSS2
                        if boss2 and config.get("boss2"):
                            r2, err2 = clear_copy(config["boss2"])
                            if r2 is None:
                                self._log("  第%d次 %s创建失败: %s" % (i+1, config["boss2_name"], err2))
                            elif r2.get("code") == 200:
                                self._log("  第%d次 %s 通关成功" % (i+1, config["boss2_name"]))
                            else:
                                self._log("  第%d次 %s 同步失败: %s" % (i+1, config["boss2_name"], r2.get("error")))

                        success += 1
                        self._log("  [%d/%d] 完成" % (i+1, times))
                        time.sleep(delay / 3)
                    except Exception as e:
                        fail += 1
                        self._log("  第%d次异常: %s" % (i+1, e))
                        time.sleep(1)

                self._log("[隐藏BOSS] 完成! 成功%d 失败%d" % (success, fail))
                if drop_stats:
                    self._log("  掉落统计:")
                    for iid, cnt in sorted(drop_stats.items(), key=lambda x: -x[1]):
                        self._log("    %s: %d" % (iid, cnt))
                flow.disconnect()
            except Exception as e:
                self._log("[隐藏BOSS] 异常: %s" % e)
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self.btn_hide_run.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


    # ========== 宠物装备副本标签页 ==========
    def _build_pet_equip_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="宠物装备副本")
        self.pet_equip_notebook = ttk.Notebook(tab)
        self.pet_equip_notebook.pack(fill="both", expand=True)
        self._pet_batches = self._pet_batches_load()
        groups = [
            ("fish", "神兽森林·鱼将军", [(2036, "赤鲤巢穴"), (2037, "黄尝巢穴"),
                                       (2038, "白鳝巢穴"), (2043, "乌鲳巢穴")]),
            ("kong", "空桑谷", [(2112, "桃花林 - 风魔猿"), (2113, "雷云台 - 雷魔猿"),
                               (2114, "盘根窟 - 土魔猿"), (2115, "流萤森 - 木魔猿")]),
            ("yue", "月华境", [(2122, "炼狱海 - 炎魔猪"), (2123, "幽野林 - 巨力猪"),
                              (2124, "风雪原 - 雪魔猪"), (2125, "碧水潭 - 水魔猪")]),
            ("yun", "云隐渊", [(2142, "云武台 - 金魔虎"), (2143, "熔心廊 - 火魔虎"),
                              (2144, "咒石岭 - 石魔虎"), (2145, "罡风崖 - 风魔虎")]),
            ("wan", "万灵馆", [(7002, "静行"), (7003, "静武"), (7004, "静磐"), (7005, "静幻")]),
        ]
        self.var_pet_fish_times = tk.IntVar(value=1)
        self.var_pet_wan_times = tk.IntVar(value=1)
        self.var_pet_normal_times = tk.IntVar(value=1)
        self._pet_layer_notebooks = {}
        self._pet_layer_targets = {}
        for key, title, levels in groups:
            group = ttk.Frame(self.pet_equip_notebook, padding=8)
            self.pet_equip_notebook.add(group, text=title)
            if key == "fish":
                self._pet_fish_group = str(group)
            if key == "wan":
                self._pet_wan_group = str(group)
            if key in ("kong", "yue", "yun"):
                setattr(self, "_pet_%s_group" % key, str(group))
            lbl = ttk.Label(group, text="避水珠: 待检测" if key == "fish" else ("挑战券: 待检测" if key == "wan" else "剩余次数: 待检测"), foreground="blue")
            lbl.pack(anchor="w", pady=6)
            setattr(self, "lbl_%s_remain" % key, lbl)
            layers = ttk.Notebook(group); layers.pack(fill="both", expand=True)
            self._pet_layer_notebooks[str(group)] = layers
            variables = {}; setattr(self, "pet_%s_vars" % key, variables)
            for mid, name in levels:
                page = ttk.Frame(layers, padding=12)
                layers.add(page, text=name.split(" - ", 1)[0])
                self._pet_layer_targets[str(page)] = mid
                var = tk.BooleanVar(value=False); variables[mid] = var
                ttk.Checkbutton(page, text="一键运行包含这一关", variable=var).pack(anchor="w", pady=6)
                ttk.Label(page, text="%s · %s（关卡%d）" % (title, name, mid)).pack(anchor="w", pady=8)
                note = "每轮消耗1张万灵馆挑战券；无每日次数限制，券用完停止，不使用点券补次数。" if key == "wan" else "本组共享每天2次免费机会；不消耗体力，掉落宠物装备材料。"
                if key == "fish":
                    note = "每次挑战消耗1颗避水珠；自动进入森林水底后挑战所选鱼将军，无需定水珠。拾取玲珑鳞和宠物装备；避水珠不足时停止。"
                ttk.Label(page, text=note, wraplength=800).pack(anchor="w", pady=6)
        settings = ttk.LabelFrame(tab, text="刷取设置", padding=10)
        settings.pack(fill="x", pady=(0, 8), before=self.pet_equip_notebook)
        settings_row = ttk.Frame(settings)
        settings_row.pack(fill="x")
        self.pet_fish_settings = ttk.Frame(settings_row)
        ttk.Label(self.pet_fish_settings, text="每个所选将军次数：").pack(side="left")
        ttk.Spinbox(self.pet_fish_settings, from_=1, to=9999, textvariable=self.var_pet_fish_times, width=7).pack(side="left", padx=6)
        ttk.Label(self.pet_fish_settings, text="每次1颗避水珠，用完停止").pack(side="left", padx=(0, 12))
        self.pet_wan_settings = ttk.Frame(settings_row)
        ttk.Label(self.pet_wan_settings, text="每个所选关卡次数：").pack(side="left")
        ttk.Spinbox(self.pet_wan_settings, from_=1, to=9999, textvariable=self.var_pet_wan_times, width=7).pack(side="left", padx=6)
        ttk.Label(self.pet_wan_settings, text="每次1张挑战券，用完停止").pack(side="left", padx=(0, 12))
        self.pet_normal_settings = ttk.Frame(settings_row)
        ttk.Label(self.pet_normal_settings, text="每个所选关卡次数：").pack(side="left")
        ttk.Spinbox(self.pet_normal_settings, from_=1, to=2, textvariable=self.var_pet_normal_times, width=7).pack(side="left", padx=6)
        ttk.Label(self.pet_normal_settings, text="每天2次，按剩余截断").pack(side="left", padx=(0, 12))
        ttk.Label(settings_row, text="间隔(秒)：").pack(side="left")
        self.var_pet_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(settings_row, from_=0.5, to=10, increment=0.5, textvariable=self.var_pet_delay, width=8).pack(side="left", padx=6)
        self.btn_pet_check = ttk.Button(settings_row, text="检测剩余次数", command=self._do_pet_check)
        self.btn_pet_check.pack(side="left", padx=8)
        self.btn_pet_run = ttk.Button(settings_row, text="刷取当前关卡", command=self._run_current_pet_layer, state="disabled")
        self.btn_pet_run.pack(side="left", padx=8)

        batch_row = ttk.Frame(settings)
        batch_row.pack(fill="x", pady=(6, 0))
        ttk.Label(batch_row, text="批量记忆：").pack(side="left")
        self.btn_pet_batch1 = ttk.Button(
            batch_row, text="宠物副本批量1",
            command=lambda: self._pet_batch_run(1), state="disabled")
        self.btn_pet_batch1.pack(side="left", padx=3)
        self.btn_pet_batch2 = ttk.Button(
            batch_row, text="宠物副本批量2",
            command=lambda: self._pet_batch_run(2), state="disabled")
        self.btn_pet_batch2.pack(side="left", padx=3)
        self.btn_pet_batch3 = ttk.Button(
            batch_row, text="宠物副本批量3",
            command=lambda: self._pet_batch_run(3), state="disabled")
        self.btn_pet_batch3.pack(side="left", padx=3)
        ttk.Label(batch_row, text="   ").pack(side="left")
        self.btn_pet_save1 = ttk.Button(
            batch_row, text="存为宠物1", width=9,
            command=lambda: self._pet_batch_save(1), state="disabled")
        self.btn_pet_save1.pack(side="left", padx=3)
        self.btn_pet_save2 = ttk.Button(
            batch_row, text="存为宠物2", width=9,
            command=lambda: self._pet_batch_save(2), state="disabled")
        self.btn_pet_save2.pack(side="left", padx=3)
        self.btn_pet_save3 = ttk.Button(
            batch_row, text="存为宠物3", width=9,
            command=lambda: self._pet_batch_save(3), state="disabled")
        self.btn_pet_save3.pack(side="left", padx=3)
        self.lbl_pet_batch = ttk.Label(
            settings, text="批量记忆：登录并选择存档后可保存。",
            foreground="gray", wraplength=900, justify="left")
        self.lbl_pet_batch.pack(anchor="w", pady=(4, 0))
        self.pet_equip_notebook.bind("<<NotebookTabChanged>>", self._update_pet_settings)
        self._update_pet_settings()

    def _update_pet_settings(self, event=None):
        fish = self.pet_equip_notebook.select() == self._pet_fish_group
        if fish:
            self.pet_fish_settings.pack(side="left", before=self.btn_pet_check, padx=6)
        else:
            self.pet_fish_settings.pack_forget()
        wan = self.pet_equip_notebook.select() == self._pet_wan_group
        if wan:
            self.pet_wan_settings.pack(side="left", before=self.btn_pet_check, padx=6)
        else:
            self.pet_wan_settings.pack_forget()
        normal = self.pet_equip_notebook.select() in (
            self._pet_kong_group, self._pet_yue_group, self._pet_yun_group)
        if normal:
            self.pet_normal_settings.pack(side="left", before=self.btn_pet_check, padx=6)
        else:
            self.pet_normal_settings.pack_forget()
        self.btn_pet_check.config(text="检测避水珠" if fish else ("检测挑战券" if wan else "检测剩余次数"))
        self.btn_pet_run.config(text="刷取当前将军" if fish else "刷取当前关卡")

    # ---------- 宠物副本批量：三组任务按账号/存档记忆 ----------
    def _pet_batches_load(self):
        try:
            with open(PET_EQUIP_BATCH_FILE, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {}
        groups = data.get("groups") if isinstance(data, dict) else None
        if not isinstance(groups, dict):
            return {}
        batches = {}
        for key, value in groups.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            batch = {}
            for group in ("1", "2", "3"):
                raw = value.get(group)
                if not isinstance(raw, dict):
                    raw = {}
                item = {}
                for section, allowed in PET_EQUIP_STAGE_IDS.items():
                    ids = []
                    raw_ids = raw.get(section, [])
                    if not isinstance(raw_ids, list):
                        raw_ids = []
                    for mid in raw_ids:
                        try:
                            mid = int(mid)
                        except (TypeError, ValueError):
                            continue
                        if mid in allowed and mid not in ids:
                            ids.append(mid)
                    item[section] = ids
                for field in ("fish_times", "wan_times", "normal_times"):
                    try:
                        times = int(raw.get(field, 1))
                    except (TypeError, ValueError):
                        times = 1
                    item[field] = max(1, min(9999, times))
                batch[group] = item
            batches[key] = batch
        return batches

    def _pet_batches_write(self):
        temporary = PET_EQUIP_BATCH_FILE + ".tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "groups": self._pet_batches},
                      file, ensure_ascii=False, indent=2)
        os.replace(temporary, PET_EQUIP_BATCH_FILE)

    def _pet_batch_key(self):
        if self.client is None or self.current_save is None:
            return None
        username = getattr(self.client, "username", None)
        if not username:
            return None
        return "%s::%d" % (username, int(self.current_save["index"]))

    def _pet_batch_data(self, group):
        key = self._pet_batch_key()
        if not key:
            return None
        raw = self._pet_batches.get(key, {}).get(str(group))
        if not isinstance(raw, dict):
            return None
        data = {}
        for section, allowed in PET_EQUIP_STAGE_IDS.items():
            raw_ids = raw.get(section, [])
            if not isinstance(raw_ids, list):
                raw_ids = []
            data[section] = [mid for mid in raw_ids if mid in allowed]
        for field in ("fish_times", "wan_times"):
            try:
                times = int(raw.get(field, 1))
            except (TypeError, ValueError):
                times = 1
            data[field] = max(1, min(9999, times))
        if not any(data[section] for section in PET_EQUIP_STAGE_IDS):
            return None
        return data

    def _pet_batch_update_labels(self):
        if not hasattr(self, "lbl_pet_batch"):
            return
        if not self._pet_batch_key():
            self.lbl_pet_batch.config(text="批量记忆：登录并选择存档后可保存。")
            return

        def summary(group):
            data = self._pet_batch_data(group)
            if not data:
                return "未设置"
            return "鱼%d 空%d 月%d 云%d 万%d（鱼×%d 万×%d 普通×%d）" % (
                len(data["fish"]), len(data["kong"]), len(data["yue"]),
                len(data["yun"]), len(data["wan"]),
                data["fish_times"], data["wan_times"], data.get("normal_times", 1))

        self.lbl_pet_batch.config(
            text="批量1：%s\n批量2：%s\n批量3：%s\n勾选关卡并设好次数后保存，点对应按钮直接刷取。" %
                 (summary(1), summary(2), summary(3)))

    def _pet_batch_save(self, group):
        if self.client is None or self.current_save is None:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        data = {}
        for section in PET_EQUIP_STAGE_IDS:
            variables = getattr(self, "pet_%s_vars" % section)
            data[section] = [mid for mid, var in variables.items() if var.get()]
        if not any(data[section] for section in PET_EQUIP_STAGE_IDS):
            messagebox.showwarning("提示", "请至少勾选一个关卡")
            return
        data["fish_times"] = data["wan_times"] = data["normal_times"] = 1
        try:
            if data["fish"]:
                data["fish_times"] = max(1, min(9999, int(self.var_pet_fish_times.get())))
            if data["wan"]:
                data["wan_times"] = max(1, min(9999, int(self.var_pet_wan_times.get())))
            if any(data[section] for section in ("kong", "yue", "yun")):
                data["normal_times"] = max(1, min(2, int(self.var_pet_normal_times.get())))
        except (ValueError, tk.TclError):
            messagebox.showwarning("提示", "刷取次数必须为正整数")
            return
        key = self._pet_batch_key()
        if not key:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        entry = self._pet_batches.setdefault(key, {})
        entry[str(group)] = data
        try:
            self._pet_batches_write()
        except OSError as exc:
            messagebox.showerror("保存失败", "宠物副本批量保存失败：%s" % exc)
            return
        self._pet_batch_update_labels()
        self._log("[宠物装备] 宠物副本批量%d已保存：鱼%d 空%d 月%d 云%d 万%d，鱼×%d 万×%d 普通×%d" %
                  (group, len(data["fish"]), len(data["kong"]), len(data["yue"]),
                   len(data["yun"]), len(data["wan"]),
                   data["fish_times"], data["wan_times"], data["normal_times"]))

    def _pet_batch_run(self, group):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        data = self._pet_batch_data(group)
        if not data:
            messagebox.showwarning(
                "提示", "宠物副本批量%d还没有选择。请先勾选关卡和次数并点“存为宠物%d”。" %
                        (group, group))
            return
        self._do_pet_equip(batch_data=data, batch_group=group)

    def _pet_action_buttons(self):
        return (self.btn_pet_check, self.btn_pet_run,
                self.btn_pet_batch1, self.btn_pet_batch2, self.btn_pet_batch3,
                self.btn_pet_save1, self.btn_pet_save2, self.btn_pet_save3)

    def _pet_collect_selection(self, selected_mid=None, batch_data=None):
        selected = []
        normal_times = 1
        if batch_data is not None:
            try:
                normal_times = max(1, min(2, int(batch_data.get("normal_times", 1))))
            except (TypeError, ValueError):
                normal_times = 1
            for section, label in (("kong", "空桑谷"), ("yue", "月华境"),
                                   ("yun", "云隐渊")):
                for mid in batch_data.get(section, []):
                    selected.extend([(mid, label, "normal")] * normal_times)
            wan_selected = list(batch_data.get("wan", []))
            fish_selected = list(batch_data.get("fish", []))
            wan_times = int(batch_data.get("wan_times", 1))
            fish_times = int(batch_data.get("fish_times", 1))
        else:
            kong_selected = [mid for mid, var in self.pet_kong_vars.items()
                             if mid == selected_mid or (selected_mid is None and var.get())]
            yue_selected = [mid for mid, var in self.pet_yue_vars.items()
                            if mid == selected_mid or (selected_mid is None and var.get())]
            yun_selected = [mid for mid, var in self.pet_yun_vars.items()
                            if mid == selected_mid or (selected_mid is None and var.get())]
            if any((kong_selected, yue_selected, yun_selected)):
                try:
                    normal_times = max(1, min(2, int(self.var_pet_normal_times.get())))
                except (ValueError, tk.TclError):
                    raise ValueError("普通副本刷取次数必须为正整数")
            for mid in kong_selected:
                selected.extend([(mid, "空桑谷", "normal")] * normal_times)
            for mid in yue_selected:
                selected.extend([(mid, "月华境", "normal")] * normal_times)
            for mid in yun_selected:
                selected.extend([(mid, "云隐渊", "normal")] * normal_times)
            wan_selected = [mid for mid, var in self.pet_wan_vars.items()
                            if mid == selected_mid or (selected_mid is None and var.get())]
            fish_selected = [mid for mid, var in self.pet_fish_vars.items()
                             if mid == selected_mid or (selected_mid is None and var.get())]
            wan_times = fish_times = 1
            if wan_selected:
                try:
                    wan_times = int(self.var_pet_wan_times.get())
                except (ValueError, tk.TclError):
                    raise ValueError("万灵馆刷取次数必须为正整数")
            if fish_selected:
                try:
                    fish_times = int(self.var_pet_fish_times.get())
                except (ValueError, tk.TclError):
                    raise ValueError("鱼将军刷取次数必须为正整数")
        if wan_selected:
            if wan_times < 1:
                raise ValueError("万灵馆刷取次数必须为正整数")
            for _ in range(wan_times):
                selected.extend((mid, "万灵馆", "wanling") for mid in wan_selected)
        if fish_selected:
            if fish_times < 1:
                raise ValueError("鱼将军刷取次数必须为正整数")
            for _ in range(fish_times):
                selected.extend((mid, "神兽森林鱼将军", "fish") for mid in fish_selected)
        if not selected:
            raise ValueError("请至少勾选一个关卡")
        return selected

    def _run_current_pet_layer(self):
        layers = self._pet_layer_notebooks.get(self.pet_equip_notebook.select())
        mid = self._pet_layer_targets.get(layers.select()) if layers else None
        if mid is not None:
            self._do_pet_equip(selected_mid=mid)

    def _do_pet_check(self):
        _count_generation = getattr(self, "_count_generation", 0)
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        for button in self._pet_action_buttons():
            button.config(state="disabled")
        self._log("[宠物装备] 检测剩余次数...")

        def worker():
            try:
                flow, _, scene = self._connect_and_enter()
                record = scene.get('curRecord', {})
                levels = record.get('copyHistory', [])
                from count_states import usage
                used_map = usage(scene)

                kong_ids = [2112, 2113, 2114, 2115]
                yue_ids = [2122, 2123, 2124, 2125]
                yun_ids = [2142, 2143, 2144, 2145]

                kong_used = sum(used_map.get(int(mid), 0) for mid in kong_ids)
                yue_used = sum(used_map.get(int(mid), 0) for mid in yue_ids)
                yun_used = sum(used_map.get(int(mid), 0) for mid in yun_ids)

                kong_remain = max(0, 2 - kong_used)
                yue_remain = max(0, 2 - yue_used)
                yun_remain = max(0, 2 - yun_used)

                self._count_after(_count_generation, 0, lambda: self.lbl_kong_remain.config(text="剩余次数: %d (已用%d)" % (kong_remain, kong_used)))
                self._count_after(_count_generation, 0, lambda: self.lbl_yue_remain.config(text="剩余次数: %d (已用%d)" % (yue_remain, yue_used)))
                self._count_after(_count_generation, 0, lambda: self.lbl_yun_remain.config(text="剩余次数: %d (已用%d)" % (yun_remain, yun_used)))

                self._log("[宠物装备] 空桑谷剩余%d, 月华境剩余%d, 云隐渊剩余%d" % (kong_remain, yue_remain, yun_remain))

                # 万灵馆挑战券数量
                cur = scene.get('curRecord', {})
                items_bag = cur.get('itemsBag', {}).get('items', [])
                if isinstance(items_bag, dict):
                    items_bag = list(items_bag.values())
                pearl_count = self._special_item_count(scene, "164300001")
                self._count_after(_count_generation, 0, lambda n=pearl_count: self.lbl_fish_remain.config(text="避水珠: %d颗（可刷%d次）" % (n, n)))
                ticket_count = 0
                for v in items_bag:
                    if isinstance(v, dict) and str(v.get('id')) == '143300002':
                        ticket_count += v.get('num', v.get('count', 0))
                self._count_after(_count_generation, 0, lambda: self.lbl_wan_remain.config(text="挑战券: %d张（可刷%d次）" % (ticket_count, ticket_count)))
                self._log("[宠物装备] 万灵馆挑战券: %d张" % ticket_count)
                flow.disconnect()
            except Exception as e:
                self._log("[宠物装备] 检测异常: %s" % e)
            finally:
                for button in self._pet_action_buttons():
                    self._count_after(_count_generation, 0,
                                      lambda btn=button: btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _do_pet_equip(self, selected_mid=None, batch_data=None, batch_group=None):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        try:
            selected = self._pet_collect_selection(selected_mid, batch_data)
        except ValueError as exc:
            messagebox.showwarning("提示", str(exc))
            return

        delay = self.var_pet_delay.get()
        for button in self._pet_action_buttons():
            button.config(state="disabled")
        suffix = "（宠物副本批量%d）" % batch_group if batch_group else ""
        self._log("[宠物装备] 开始刷取 %d 个关卡%s（普通副本按剩余次数自动截断）..." % (len(selected), suffix))

        _run_slot, _run_client = self.current_save['index'], self.client
        def worker():
            flow = None
            try:
                flow, _, scene = self._connect_and_enter(_run_slot)
                cur = scene.get('curRecord', {})
                p1 = cur.get('p1', {})
                current_exp = p1.get("experience", 0)
                property_p1_str = "%d;%d;%d;%d;%d;%d" % (p1.get("hpMax",0), p1.get("mpMax",0), p1.get("atk",0), p1.get("phyDef",0), p1.get("reHP",0), p1.get("reMP",0))

                # 道具名称映射
                prop_map = {}
                try:
                    import json as _json
                    _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2", "150___Prop.xml.json")
                    if os.path.exists(_bp):
                        with open(_bp, 'r', encoding='utf-8') as _f:
                            _pd = _json.load(_f)
                        _recs = _pd.get('RECORD', _pd if isinstance(_pd, list) else [])
                        if isinstance(_recs, dict):
                            _recs = [_recs]
                        for _r in _recs:
                            if isinstance(_r, dict):
                                prop_map[str(_r.get('id'))] = _r.get('name', '?')
                except:
                    pass

                drop_stats = {}
                success = 0
                fail = 0

                from count_states import usage
                used_map = usage(scene)
                normal_ids = {
                    "空桑谷": [2112, 2113, 2114, 2115],
                    "月华境": [2122, 2123, 2124, 2125],
                    "云隐渊": [2142, 2143, 2144, 2145],
                }
                budgets = {}
                for group, ids in normal_ids.items():
                    used = sum(used_map.get(int(mid), 0) for mid in ids)
                    budgets[group] = max(0, 2 - used)
                plan = []
                for mid, group, copy_type in selected:
                    if copy_type == "normal":
                        if budgets.get(group, 0) <= 0:
                            self._log("[宠物装备] %s剩余次数已用完，跳过关卡%d。" % (group, mid))
                            continue
                        budgets[group] -= 1
                    plan.append((mid, group, copy_type))
                if not plan:
                    self._log("[宠物装备] 剩余次数不足，没有可执行的关卡。")
                self._log("[宠物装备] 本次计划执行 %d 个关卡。" % len(plan))

                for idx, (mid, group, copy_type) in enumerate(plan):
                    name = prop_map.get(str(mid), str(mid))
                    self._log("[%d/%d] %s-%s(%d)" % (idx+1, len(plan), group, name, mid))
                    try:
                        if copy_type == "fish":
                            from mainfarm_routes import clear_stage
                            pearl_count = self._special_item_count(scene, "164300001")
                            if pearl_count < 1:
                                raise RuntimeError("避水珠不足，请先补充后再运行")
                            baseline = scene
                            clear_stage(flow, scene, 2024, enter_w=True)
                            result = clear_stage(flow, scene, mid, pick_equips=True)
                            flow.disconnect(); flow = None
                            flow, _, scene = self._connect_and_enter(_run_slot)
                            if self._special_item_count(scene, "164300001") != pearl_count - 1:
                                raise RuntimeError("避水珠扣除数量异常")
                            if self._special_item_count(scene, "164100002") != self._special_item_count(baseline, "164100002"):
                                raise RuntimeError("定水珠数量异常")
                            if any((scene.get("user") or {}).get(k) != (baseline.get("user") or {}).get(k) for k in ("gem", "usedGem")):
                                raise RuntimeError("点券数量异常")
                            for iid, count in result["counts"].items():
                                if str(iid) == "178100001" and self._special_item_count(scene, iid) - self._special_item_count(baseline, iid) != count:
                                    raise RuntimeError("玲珑鳞入包核验失败")
                                drop_stats[iid] = drop_stats.get(iid, 0) + count
                            equipment_ids = {str(x.get("entityId")) for x in (scene.get("curRecord", {}).get("equipsBag", {}).get("items") or [])}
                            for equipment in (result["settled"].get("add") or {}).get("newEquips") or []:
                                if str(equipment.get("entityId")) not in equipment_ids:
                                    raise RuntimeError("宠物装备入包核验失败")
                            self._log("  已重登核验：掉落%s；避水珠-1，定水珠和点券未消耗" % result["counts"])
                            self.root.after(0, lambda n=pearl_count-1: self.lbl_fish_remain.config(text="避水珠: %d颗（可刷%d次）" % (n, n)))
                            success += 1
                            time.sleep(delay)
                            continue
                        if copy_type == "wanling":
                            ticket_before = self._special_item_count(scene, "143300002")
                            if ticket_before < 1:
                                self._log("[万灵馆] 挑战券已用完，停止刷取")
                                break
                            wan_baseline = scene
                        create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                        if create_result.get("code") != 200:
                            self._log("  创建失败: %s" % create_result.get("error", ""))
                            fail += 1
                            if copy_type == "wanling":
                                break
                            time.sleep(delay)
                            continue

                        if copy_type == "wanling":
                            # 万灵馆：create→等3秒→bossDead→finish→petTrainReward领奖
                            time.sleep(3)
                            dead_result = flow.request("scene.copyHandler.bossDead", None, timeout=10)
                            if dead_result.get("code") != 200:
                                raise RuntimeError("万灵馆击杀确认失败：%s" % dead_result)
                            time.sleep(0.5)
                            finish_result = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                            if finish_result.get("code") != 200:
                                raise RuntimeError("万灵馆结算失败：%s" % finish_result)
                            time.sleep(0.5)
                            reward = flow.request("scene.playerFourthHandler.petTrainReward", {}, timeout=15)
                            if reward.get("code") == 200:
                                add_data = reward.get("add", {})
                                reward_items = reward.get("items", [])
                                flow.disconnect(); flow = None
                                flow, _, scene = self._connect_and_enter(_run_slot)
                                ticket_after = self._special_item_count(scene, "143300002")
                                if ticket_after != ticket_before - 1:
                                    raise RuntimeError("万灵馆挑战券扣除数量异常")
                                if any((scene.get("user") or {}).get(k) != (wan_baseline.get("user") or {}).get(k) for k in ("gem", "usedGem")):
                                    raise RuntimeError("万灵馆点券数量异常")
                                self.root.after(0, lambda n=ticket_after: self.lbl_wan_remain.config(text="挑战券: %d张（可刷%d次）" % (n, n)))
                                self._log("  领奖成功，重登确认挑战券-1，剩余%d张，点券未消耗" % ticket_after)
                                for k, v in add_data.items():
                                    if isinstance(v, (int, float)) and v > 0:
                                        drop_stats[k] = drop_stats.get(k, 0) + v
                                        rname = prop_map.get(str(k), str(k))
                                        self._log("    获得: %s(%s) x%d" % (rname, k, v))
                                if reward_items:
                                    for item in reward_items:
                                        iid = str(item["id"])
                                        count = int(item.get("count", 1))
                                        if self._special_item_count(scene, iid) - self._special_item_count(wan_baseline, iid) != count:
                                            raise RuntimeError("万灵馆奖励入包核验失败：%s" % iid)
                                        drop_stats[iid] = drop_stats.get(iid, 0) + count
                                    self._log("    奖励items: %s" % json.dumps(reward_items, ensure_ascii=False)[:200])
                                success += 1
                            else:
                                self._log("  领奖失败: %s" % reward.get("error", ""))
                                fail += 1
                                break
                        else:
                            # 普通宠物装备副本：create→bossDead→finish→syncDrop
                            drops = create_result.get("drops", {})
                            copy_id = drops.get("copyId", 0)
                            new_drops = drops.get("newDrops", [])

                            pick_items = []
                            mob_ids = []
                            kill_monsters = []
                            total_exp = 0
                            total_sp = 0
                            for d in new_drops:
                                d_mid = d.get("monsterId", "0")
                                d_idx = d.get("index", 0)
                                total_exp += d.get("exp", 0)
                                total_sp += d.get("spirit", 0)
                                for _field, group in drop_groups(d):
                                    mob_ids.append(d_mid)
                                    kill_monsters.append("%s_%d" % (d_mid, d_idx))
                                    for item_id, item_list in group.items():
                                        for item in item_list:
                                            pick_items.append(item)
                                        cnt = len(item_list) if isinstance(item_list, list) else 1
                                        drop_stats[item_id] = drop_stats.get(item_id, 0) + cnt

                            time.sleep(2)
                            flow.request("scene.copyHandler.bossDead", None, timeout=10)
                            time.sleep(0.5)
                            flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                            time.sleep(0.5)
                            sync_data = {
                                "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                                "killMonsters": kill_monsters, "completed": 1,
                                "currentEXP": current_exp, "pickExp": total_exp, "pickSp": total_sp,
                                "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                            }
                            sync_result = flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                            if sync_result.get("code") == 200:
                                self._log("  通关成功")
                                success += 1
                            else:
                                self._log("  同步失败: %s" % sync_result.get("error", ""))
                                fail += 1
                    except Exception as e:
                        self._log("  异常: %s" % e)
                        fail += 1
                        if copy_type in ("fish", "wanling"):
                            break
                    time.sleep(delay)

                self._log("[宠物装备] 完成! 成功%d 失败%d" % (success, fail))
                if drop_stats:
                    self._log("  掉落统计:")
                    for iid, cnt in sorted(drop_stats.items(), key=lambda x: -x[1]):
                        iname = prop_map.get(str(iid), iid)
                        self._log("    %s(%s): %d" % (iname, iid, cnt))
                flow.disconnect()
            except Exception as e:
                self._log("[宠物装备] 异常: %s" % e)
                import traceback
                self._log(traceback.format_exc())
            finally:
                if flow:
                    flow.disconnect()
                for button in self._pet_action_buttons():
                    self.root.after(0, lambda btn=button: btn.config(state="normal"))

                self.root.after(0, lambda: self._refresh_finished_counts(_run_slot, _run_client))

        threading.Thread(target=worker, daemon=True).start()




    # 次数规则取自 036___Dungeon：入口关与 BOSS 关 shareDungeonID 共享 dailyCountMax=3；
    # 中间层 dailyCountMax=999（不限次、不占用共享次数），因此计数只取入口 + BOSS。
    BEIMING_LAYERS = {
        "bingfeng": {
            "name": "冰封层", "reset_id": 2, "stone_id": "109000001", "stone_name": "冰晶",
            "need_level": 20, "daily_max": 3,
            "route_a": [2001, 2004, 2005, 2006],
            "route_b": [2132],
            "route_a_names": ["入口", "2层", "3层", "4层"],
            "route_b_names": ["BOSS层"],
            "count_ids": [2001, 2132],
        },
        "shuiyan": {
            "name": "水岩层", "reset_id": 3, "stone_id": "109100001", "stone_name": "雾晶",
            "need_level": 35, "daily_max": 3,
            "route_a": [2026, 2028, 2031, 2032],
            "route_b": [2133],
            "route_a_names": ["入口", "6层", "7层", "8层"],
            "route_b_names": ["BOSS层"],
            "count_ids": [2026, 2133],
        },
        "rongyan": {
            "name": "熔岩层", "reset_id": 4, "stone_id": "109200001", "stone_name": "炎晶",
            "need_level": 44, "daily_max": 3,
            "route_a": [2044, 2045, 2047, 2048],
            "route_b": [2134],
            "route_a_names": ["入口", "2层", "3层", "4层"],
            "route_b_names": ["BOSS层"],
            "count_ids": [2044, 2134],
        },
    }

    def _build_mounts_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="坐骑副本")
        from official_sweep import add_mode_controls
        add_mode_controls(self, tab, "mount")
        self.mount_notebook = ttk.Notebook(tab)
        self.mount_notebook.pack(fill="both", expand=True)
        self._mount_batches = self._mount_copy_batches_load()
        batch_row = ttk.Frame(tab)
        batch_row.pack(fill="x", pady=(4, 0), before=self.mount_notebook)
        ttk.Label(batch_row, text="批量记忆：").pack(side="left")
        self.btn_mount_batch1 = ttk.Button(
            batch_row, text="坐骑副本批量1",
            command=lambda: self._mount_batch_run(1), state="disabled")
        self.btn_mount_batch1.pack(side="left", padx=3)
        self.btn_mount_batch2 = ttk.Button(
            batch_row, text="坐骑副本批量2",
            command=lambda: self._mount_batch_run(2), state="disabled")
        self.btn_mount_batch2.pack(side="left", padx=3)
        self.btn_mount_batch3 = ttk.Button(
            batch_row, text="坐骑副本批量3",
            command=lambda: self._mount_batch_run(3), state="disabled")
        self.btn_mount_batch3.pack(side="left", padx=3)
        ttk.Label(batch_row, text="   ").pack(side="left")
        self.btn_mount_save1 = ttk.Button(
            batch_row, text="存为坐骑1", width=9,
            command=lambda: self._mount_batch_save(1), state="disabled")
        self.btn_mount_save1.pack(side="left", padx=3)
        self.btn_mount_save2 = ttk.Button(
            batch_row, text="存为坐骑2", width=9,
            command=lambda: self._mount_batch_save(2), state="disabled")
        self.btn_mount_save2.pack(side="left", padx=3)
        self.btn_mount_save3 = ttk.Button(
            batch_row, text="存为坐骑3", width=9,
            command=lambda: self._mount_batch_save(3), state="disabled")
        self.btn_mount_save3.pack(side="left", padx=3)
        self.lbl_mount_batch = ttk.Label(
            tab, text="批量记忆：登录并选择存档后可保存。",
            foreground="gray", wraplength=900, justify="left")
        self.lbl_mount_batch.pack(anchor="w", pady=(2, 4), before=self.mount_notebook)
        self.beiming_layer_vars = {}
        self.mount_pair_vars = {}
        self.mount_remain_labels = {}
        self._mount_layer_notebooks = {}
        self._mount_layer_targets = {}
        for key, title in [("beiming", "悲鸣冰川")] + [(k, v["name"]) for k, v in self.MOUNT_COPY_GROUPS.items()]:
            group = ttk.Frame(self.mount_notebook, padding=6)
            self.mount_notebook.add(group, text=title)
            layers = ttk.Notebook(group)
            layers.pack(fill="both", expand=True)
            self._mount_layer_notebooks[str(group)] = layers
            if key == "beiming":
                for layer_key, info in self.BEIMING_LAYERS.items():
                    if layer_key == "rongyan":
                        page = ttk.Frame(self.mount_notebook, padding=12)
                        self.mount_notebook.add(page, text="冰川（熔岩层）")
                        self._beiming_lava_page = page
                    else:
                        page = ttk.Frame(layers, padding=12)
                        layers.add(page, text=info["name"])
                    self._mount_layer_targets[str(page)] = ("beiming", layer_key)
                    var = tk.BooleanVar(value=False); self.beiming_layer_vars[layer_key] = var
                    ttk.Checkbutton(page, text="一键运行包含这一层", variable=var).pack(anchor="w", pady=6)
                    ttk.Label(page, text="%s：%s，等级要求%d级；路线A/B共享每天%d次。" %
                              (info["name"], info["stone_name"], info["need_level"], info["daily_max"]), wraplength=800).pack(anchor="w", pady=8)
                    lbl = ttk.Label(page, text="剩余次数: 待检测", foreground="blue")
                    lbl.pack(anchor="w", pady=6)
                    setattr(self, "lbl_beiming_%s_remain" % layer_key, lbl)
            else:
                info = self.MOUNT_COPY_GROUPS[key]
                self.mount_pair_vars[key] = {}
                self.mount_remain_labels[key] = tk.StringVar(value="剩余次数: 待检测")
                for normal, boss, name in info["pairs"]:
                    page = ttk.Frame(layers, padding=12); layers.add(page, text=name)
                    self._mount_layer_targets[str(page)] = ("mount", (key, (normal, boss)))
                    var = tk.BooleanVar(value=False); self.mount_pair_vars[key][(normal, boss)] = var
                    ttk.Checkbutton(page, text="一键运行包含这一层", variable=var).pack(anchor="w", pady=6)
                    route = "普通层%d → BOSS层%d" % (normal, boss) if boss else "普通层%d" % normal
                    ttk.Label(page, text="%s · %s：%s。全组共享每天%d次免费机会。" %
                              (info["name"], name, route, info["daily_max"]), wraplength=800).pack(anchor="w", pady=8)
                    ttk.Label(page, textvariable=self.mount_remain_labels[key], foreground="blue").pack(anchor="w", pady=6)
        controls = ttk.Frame(tab); controls.pack(fill="x", pady=(8, 0))
        self._beiming_controls = ttk.LabelFrame(controls, text="悲鸣冰川设置", padding=8)
        self._mount_controls = ttk.LabelFrame(controls, text="坐骑副本设置", padding=8)
        self.var_beiming_route = tk.StringVar(value="A")
        self.var_beiming_pick_equip = tk.BooleanVar(value=True)
        self.var_beiming_delay = tk.DoubleVar(value=2.0)
        self.var_beiming_times = tk.IntVar(value=1)
        self.var_mount_pick_equip = tk.BooleanVar(value=True)
        self.var_mount_delay = tk.DoubleVar(value=2.0)
        self.var_mount_times = tk.IntVar(value=1)
        for title, value in (("路线A（前四层）", "A"), ("路线B（BOSS层）", "B")):
            ttk.Radiobutton(self._beiming_controls, text=title, variable=self.var_beiming_route, value=value).pack(side="left", padx=4)
        for mode, frame, delay, equip, times in (
                ("beiming", self._beiming_controls, self.var_beiming_delay,
                 self.var_beiming_pick_equip, self.var_beiming_times),
                ("mount", self._mount_controls, self.var_mount_delay,
                 self.var_mount_pick_equip, self.var_mount_times)):
            ttk.Checkbutton(frame, text="拾取装备", variable=equip).pack(side="left", padx=8)
            ttk.Label(frame, text="间隔(秒)：").pack(side="left")
            ttk.Spinbox(frame, from_=0.5, to=10, increment=0.5, textvariable=delay, width=6).pack(side="left", padx=4)
            ttk.Label(frame, text="每层次数：").pack(side="left", padx=(8, 0))
            ttk.Spinbox(frame, from_=1, to=3, textvariable=times, width=4).pack(side="left", padx=4)
            check = ttk.Button(frame, text="检测剩余次数", command=self._do_beiming_check if mode == "beiming" else self._do_mount_check)
            check.pack(side="left", padx=6)
            run = ttk.Button(frame, text="刷取当前层", command=self._run_current_mount_layer, state="disabled")
            run.pack(side="left", padx=6)
            setattr(self, "btn_%s_check" % mode, check)
            setattr(self, "btn_%s_run" % mode, run)
        lava_controls = ttk.LabelFrame(self._beiming_lava_page, text="熔岩层刷取设置", padding=10)
        lava_controls.pack(fill="x", pady=12)
        for title, value in (("路线A（前四层）", "A"), ("路线B（BOSS层）", "B")):
            ttk.Radiobutton(lava_controls, text=title, variable=self.var_beiming_route, value=value).pack(anchor="w", pady=3)
        ttk.Checkbutton(lava_controls, text="拾取装备", variable=self.var_beiming_pick_equip).pack(anchor="w", pady=3)
        delay_row = ttk.Frame(lava_controls); delay_row.pack(anchor="w", pady=4)
        ttk.Label(delay_row, text="间隔(秒)：").pack(side="left")
        ttk.Spinbox(delay_row, from_=0.5, to=10, increment=0.5, textvariable=self.var_beiming_delay, width=8).pack(side="left")
        times_row = ttk.Frame(lava_controls); times_row.pack(anchor="w", pady=4)
        ttk.Label(times_row, text="每层次数：").pack(side="left")
        ttk.Spinbox(times_row, from_=1, to=3, textvariable=self.var_beiming_times, width=8).pack(side="left")
        buttons = ttk.Frame(lava_controls); buttons.pack(anchor="w", pady=6)
        ttk.Button(buttons, text="检测剩余次数", command=self._do_beiming_check).pack(side="left", padx=4)
        self.btn_beiming_lava_run = ttk.Button(buttons, text="刷取熔岩层", state="disabled",
            command=lambda: self._do_beiming_run(selected_key="rongyan"))
        self.btn_beiming_lava_run.pack(side="left", padx=4)
        self.mount_notebook.bind("<<NotebookTabChanged>>", self._sync_mount_controls)
        self._sync_mount_controls()

    # ---------- 坐骑副本批量：三组任务按账号/存档记忆 ----------
    def _mount_copy_batches_load(self):
        try:
            with open(MOUNT_COPY_BATCH_FILE, encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError):
            return {}
        groups = data.get("groups") if isinstance(data, dict) else None
        return groups if isinstance(groups, dict) else {}

    def _mount_copy_batches_write(self):
        temporary = MOUNT_COPY_BATCH_FILE + ".tmp"
        with open(temporary, "w", encoding="utf-8") as file:
            json.dump({"version": 1, "groups": self._mount_batches},
                      file, ensure_ascii=False, indent=2)
        os.replace(temporary, MOUNT_COPY_BATCH_FILE)

    def _mount_batch_key(self):
        if self.client is None or self.current_save is None:
            return None
        username = getattr(self.client, "username", None)
        if not username:
            return None
        return "%s::%d" % (username, int(self.current_save["index"]))

    def _mount_batch_data(self, group):
        key = self._mount_batch_key()
        if not key:
            return None
        raw = self._mount_batches.get(key, {}).get(str(group))
        if not isinstance(raw, dict):
            return None
        data = {"beiming": [k for k in raw.get("beiming", []) if k in self.BEIMING_LAYERS]}
        for group_key, info in self.MOUNT_COPY_GROUPS.items():
            allowed = [normal for normal, boss, name in info["pairs"]]
            ids = []
            for mid in raw.get(group_key, []):
                try:
                    mid = int(mid)
                except (TypeError, ValueError):
                    continue
                if mid in allowed and mid not in ids:
                    ids.append(mid)
            data[group_key] = ids
        if not any(data.values()):
            return None
        return data

    def _mount_batch_update_labels(self):
        if not hasattr(self, "lbl_mount_batch"):
            return
        if not self._mount_batch_key():
            self.lbl_mount_batch.config(text="批量记忆：登录并选择存档后可保存。")
            return

        def summary(group):
            data = self._mount_batch_data(group)
            if not data:
                return "未设置"
            return "悲%d 枯%d 迷%d 丰%d" % (
                len(data["beiming"]), len(data["kuyan"]),
                len(data["miwu"]), len(data["fenghua"]))

        self.lbl_mount_batch.config(
            text="批量1：%s\n批量2：%s\n批量3：%s\n勾选层级后保存，点对应按钮直接刷取。" %
                 (summary(1), summary(2), summary(3)))

    def _mount_batch_save(self, group):
        if self.client is None or self.current_save is None:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        data = {"beiming": [key for key, var in self.beiming_layer_vars.items() if var.get()]}
        for group_key, pairs in self.mount_pair_vars.items():
            data[group_key] = [normal for (normal, boss), var in pairs.items() if var.get()]
        if not any(data.values()):
            messagebox.showwarning("提示", "请至少勾选一个层级")
            return
        key = self._mount_batch_key()
        if not key:
            messagebox.showwarning("提示", "请先登录并选择存档")
            return
        entry = self._mount_batches.setdefault(key, {})
        entry[str(group)] = data
        try:
            self._mount_copy_batches_write()
        except OSError as exc:
            messagebox.showerror("保存失败", "坐骑副本批量保存失败：%s" % exc)
            return
        self._mount_batch_update_labels()
        self._log("[坐骑副本] 坐骑副本批量%d已保存：悲%d 枯%d 迷%d 丰%d" %
                  (group, len(data["beiming"]), len(data["kuyan"]),
                   len(data["miwu"]), len(data["fenghua"])))

    def _mount_batch_buttons(self):
        return (self.btn_mount_check, self.btn_mount_run,
                self.btn_mount_batch1, self.btn_mount_batch2, self.btn_mount_batch3,
                self.btn_mount_save1, self.btn_mount_save2, self.btn_mount_save3)

    def _mount_batch_set_state(self, state):
        for button in self._mount_batch_buttons():
            button.config(state=state)

    def _mount_batch_run(self, group):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        data = self._mount_batch_data(group)
        if not data:
            messagebox.showwarning(
                "提示", "坐骑副本批量%d还没有选择。请先勾选层级并点“存为坐骑%d”。" %
                        (group, group))
            return
        mids = [self.BEIMING_LAYERS[key]["route_a"][0] for key in data["beiming"]]
        for group_key, info in self.MOUNT_COPY_GROUPS.items():
            mids.extend(data[group_key])
        from official_sweep import dispatch
        if dispatch(self, "mount", mids):
            return
        self._mount_batch_set_state("disabled")
        self._log("[坐骑副本] 坐骑副本批量%d开始：悲%d 枯%d 迷%d 丰%d" %
                  (group, len(data["beiming"]), len(data["kuyan"]),
                   len(data["miwu"]), len(data["fenghua"])))

        def finish():
            self._mount_batch_set_state("normal")

        def run_copies():
            self._do_mount_run(batch_data=data, batch_group=group,
                               on_finished=finish, ignore_sweep=True)

        if data["beiming"]:
            self._do_beiming_run(selected_keys=data["beiming"],
                                 on_finished=run_copies, ignore_sweep=True)
        else:
            run_copies()

    def _sync_mount_controls(self, event=None):
        group = self.mount_notebook.select()
        if group == str(self._beiming_lava_page):
            self._beiming_controls.pack_forget()
            self._mount_controls.pack_forget()
            return
        layers = self._mount_layer_notebooks.get(group)
        target = self._mount_layer_targets.get(layers.select()) if layers else None
        self._beiming_controls.pack_forget()
        self._mount_controls.pack_forget()
        if target:
            (self._beiming_controls if target[0] == "beiming" else self._mount_controls).pack(fill="x")

    def _run_current_mount_layer(self):
        layers = self._mount_layer_notebooks.get(self.mount_notebook.select())
        target = self._mount_layer_targets.get(layers.select()) if layers else None
        if target and target[0] == "beiming":
            self._do_beiming_run(selected_key=target[1])
        elif target:
            self._do_mount_run(selected_pair=target[1])

    def _do_beiming_check(self):
        _count_generation = getattr(self, "_count_generation", 0)
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        self.btn_beiming_check.config(state="disabled")
        self._log("[悲鸣冰川] 检测剩余次数...")

        def worker():
            try:
                flow, entry, scene = self._connect_and_enter()
                record = scene.get('curRecord', {})
                levels = record.get('copyHistory', [])
                from count_states import usage
                used_map = usage(scene)

                for key, info in self.BEIMING_LAYERS.items():
                    all_ids = info.get("count_ids") or (info["route_a"] + info["route_b"])
                    used = sum(used_map.get(int(mid), 0) for mid in all_ids)
                    remain = max(0, info["daily_max"] - used)
                    lbl = getattr(self, "lbl_beiming_%s_remain" % key)
                    self._count_after(_count_generation, 0, lambda l=lbl, r=remain, u=used, n=info["name"]: l.config(text="剩余次数: %d (已用%d)" % (r, u)))
                    self._log("[悲鸣冰川] %s剩余%d (已用%d)" % (info["name"], remain, used))
                flow.disconnect()
            except Exception as e:
                self._log("[悲鸣冰川] 检测异常: %s" % e)
            finally:
                self._count_after(_count_generation, 0, lambda: self.btn_beiming_check.config(state="normal"))
                self._count_after(_count_generation, 0, lambda: self._set_beiming_run_state("normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_beiming_run_state(self, state):
        self.btn_beiming_run.config(state=state)
        self.btn_beiming_lava_run.config(state=state)

    def _do_beiming_run(self, selected_key=None, selected_keys=None,
                        on_finished=None, ignore_sweep=False):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return

        if selected_keys is not None:
            selected = [key for key in selected_keys if key in self.BEIMING_LAYERS]
        else:
            selected = []
            for key, var in self.beiming_layer_vars.items():
                if key == selected_key or (selected_key is None and var.get()):
                    selected.append(key)

        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个层级")
            return

        if not ignore_sweep:
            from official_sweep import dispatch
            if dispatch(self, "mount", [self.BEIMING_LAYERS[k]["route_a"][0] for k in selected]):
                return

        route = self.var_beiming_route.get()
        pick_equip = self.var_beiming_pick_equip.get()
        delay = self.var_beiming_delay.get()
        times = max(1, min(3, int(self.var_beiming_times.get())))

        self._set_beiming_run_state("disabled")
        self._log("[悲鸣冰川] 开始刷取: 路线%s, 拾取装备=%s, %d个层级，每层最多%d次（按剩余次数自动截断）"
                  % (route, pick_equip, len(selected), times))

        _run_slot, _run_client = self.current_save['index'], self.client
        def worker():
            try:
                flow, entry, scene = self._connect_and_enter(_run_slot)
                cur = scene.get('curRecord', {})
                p1 = scene.get('record', {}).get('p1', {})
                current_exp = p1.get("experience", 0)
                property_p1_str = "%d;%d;%d;%d;%d;%d" % (p1.get("hpMax",0), p1.get("mpMax",0), p1.get("atk",0), p1.get("phyDef",0), p1.get("reHP",0), p1.get("reMP",0))

                # 道具/装备名称映射
                prop_map = {}
                equip_map = {}
                try:
                    _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2", "150___Prop.xml.json")
                    if os.path.exists(_bp):
                        with open(_bp, 'r', encoding='utf-8') as _f:
                            _pd = json.load(_f)
                        _recs = _pd.get('RECORD', _pd if isinstance(_pd, list) else [])
                        if isinstance(_recs, dict):
                            _recs = [_recs]
                        for _r in _recs:
                            if isinstance(_r, dict):
                                prop_map[str(_r.get('id'))] = _r.get('name', '?')
                except:
                    pass
                try:
                    _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2", "046___Equipment.xml.json")
                    if os.path.exists(_bp):
                        with open(_bp, 'r', encoding='utf-8') as _f:
                            _pd = json.load(_f)
                        _recs = _pd.get('RECORD', _pd if isinstance(_pd, list) else [])
                        if isinstance(_recs, dict):
                            _recs = [_recs]
                        for _r in _recs:
                            if isinstance(_r, dict):
                                equip_map[str(_r.get('id'))] = _r.get('name', '?')
                except:
                    pass

                drop_stats = {}
                success = 0
                fail = 0

                from count_states import usage
                used_map = usage(scene)
                budgets = {}
                for key, info in self.BEIMING_LAYERS.items():
                    ids = info.get("count_ids") or (info["route_a"] + info["route_b"])
                    used = sum(used_map.get(int(mid), 0) for mid in ids)
                    budgets[key] = max(0, info["daily_max"] - used)
                plan = []
                for key in selected:
                    count = min(times, budgets.get(key, 0))
                    plan.extend([key] * count)
                    if count:
                        budgets[key] = budgets.get(key, 0) - count
                    else:
                        self._log("[悲鸣冰川] %s剩余次数已用完，跳过。"
                                  % self.BEIMING_LAYERS[key]["name"])
                if not plan:
                    self._log("[悲鸣冰川] 剩余次数不足，没有可执行的层级。")
                self._log("[悲鸣冰川] 本次计划执行 %d 轮。" % len(plan))

                for key in plan:
                    info = self.BEIMING_LAYERS[key]
                    mids = info["route_a"] if route == "A" else info["route_b"]
                    names = info["route_a_names"] if route == "A" else info["route_b_names"]
                    self._log("\n=== %s 路线%s（%s）===" % (info["name"], route, info["stone_name"]))

                    for idx, (mid, name) in enumerate(zip(mids, names)):
                        self._log("[%d/%d] %s-%s(%d)" % (idx+1, len(mids), info["name"], name, mid))
                        try:
                            create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                            if create_result.get("code") != 200:
                                self._log("  创建失败: %s" % create_result.get("error", ""))
                                fail += 1
                                time.sleep(delay)
                                continue

                            drops = create_result.get("drops", {})
                            copy_id = drops.get("copyId", 0)
                            new_drops = drops.get("newDrops", [])

                            pick_items = []
                            mob_ids = []
                            kill_monsters = []
                            total_exp = 0
                            total_sp = 0
                            for d in new_drops:
                                d_mid = d.get("monsterId", "0")
                                d_idx = d.get("index", 0)
                                total_exp += d.get("exp", 0)
                                total_sp += d.get("spirit", 0)
                                has_drop = False

                                # item字段
                                items = d.get("item", {})
                                if items:
                                    has_drop = True
                                    for item_id, item_list in items.items():
                                        for item in (item_list if isinstance(item_list, list) else [item_list]):
                                            pick_items.append(item)
                                        cnt = len(item_list) if isinstance(item_list, list) else 1
                                        drop_stats[item_id] = drop_stats.get(item_id, 0) + cnt

                                # equip字段（可选拾取）
                                equips = d.get("equip", {})
                                if equips and pick_equip:
                                    has_drop = True
                                    for equip_id, equip_list in equips.items():
                                        for equip in (equip_list if isinstance(equip_list, list) else [equip_list]):
                                            pick_items.append(equip)
                                        cnt = len(equip_list) if isinstance(equip_list, list) else 1
                                        drop_stats[equip_id] = drop_stats.get(equip_id, 0) + cnt
                                        ename = equip_map.get(equip_id, '?')
                                        self._log("    ★ 装备掉落: %s(%s)x%d" % (ename, equip_id, cnt))

                                # soul字段（魂器）不在普通副本拾取

                                if has_drop:
                                    mob_ids.append(d_mid)
                                    kill_monsters.append("%s_%d" % (d_mid, d_idx))

                            time.sleep(2)
                            flow.request("scene.copyHandler.bossDead", None, timeout=10)
                            time.sleep(0.5)
                            flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                            time.sleep(0.5)

                            # 中间层用enter_w标志，BOSS层不用
                            is_middle = (route == "A" and idx < len(mids) - 1)
                            completed = (1 | 16777216) if is_middle else 1

                            sync_data = {
                                "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                                "killMonsters": kill_monsters, "completed": completed,
                                "currentEXP": current_exp, "pickExp": total_exp, "pickSp": total_sp,
                                "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                            }
                            sync_result = flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                            if sync_result.get("code") == 200:
                                add_data = sync_result.get("add", {})
                                new_equips = add_data.get("newEquips", [])
                                if new_equips:
                                    self._log("    sync确认装备: %d件" % len(new_equips))
                                self._log("  通关成功")
                                success += 1
                            else:
                                self._log("  同步失败: %s" % sync_result.get("error", ""))
                                fail += 1
                        except Exception as e:
                            self._log("  异常: %s" % e)
                            fail += 1
                        time.sleep(delay)

                self._log("\n[悲鸣冰川] 完成! 成功%d 失败%d" % (success, fail))
                if drop_stats:
                    self._log("  掉落统计:")
                    for iid, cnt in sorted(drop_stats.items(), key=lambda x: -x[1]):
                        iname = prop_map.get(str(iid), equip_map.get(str(iid), iid))
                        self._log("    %s(%s): %d" % (iname, iid, cnt))
                flow.disconnect()
            except Exception as e:
                self._log("[悲鸣冰川] 异常: %s" % e)
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self._set_beiming_run_state("normal"))

                self.root.after(0, lambda: self._refresh_finished_counts(_run_slot, _run_client))
                if on_finished:
                    self.root.after(0, on_finished)

        threading.Thread(target=worker, daemon=True).start()



    # ========== 其他坐骑装备副本标签页 ==========
    # 次数规则取自 036___Dungeon：普通层 dailyCountMax=3，shareDungeonID 只包含四个普通层；
    # BOSS 层 dailyCountMax=-1（不单独计次，属于同一次通关的延续），因此不能并入 share_ids。
    MOUNT_COPY_GROUPS = {
        "kuyan": {
            "name": "枯焰流沙", "daily_max": 3,
            "pairs": [(2094,2095,"沙底层"), (2096,2097,"沙暴层"), (2098,2099,"寒沙层"), (2100,2101,"流沙层")],
            "share_ids": [2094,2096,2098,2100],
        },
        "miwu": {
            "name": "迷雾沮泽", "daily_max": 3,
            "pairs": [(2102,2103,"藤蔓层"), (2104,2105,"毒雾层"), (2106,2107,"沼泽层"), (2108,2109,"鬼火层")],
            "share_ids": [2102,2104,2106,2108],
        },
        "fenghua": {
            "name": "丰花原野", "daily_max": 3,
            "pairs": [(2128,None,"丰草层"), (2129,None,"繁花层"), (2130,None,"河谷层"), (2131,None,"云顶层")],
            "share_ids": [2128,2129,2130,2131],
        },
    }

    def _do_mount_check(self):
        _count_generation = getattr(self, "_count_generation", 0)
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return
        self.btn_mount_check.config(state="disabled")
        self._log("[坐骑副本2] 检测剩余次数...")

        def worker():
            try:
                flow, entry, scene = self._connect_and_enter()
                record = scene.get('curRecord', {})
                levels = record.get('copyHistory', [])
                from count_states import usage
                used_map = usage(scene)

                for key, info in self.MOUNT_COPY_GROUPS.items():
                    all_ids = info["share_ids"]
                    used = sum(used_map.get(int(mid), 0) for mid in all_ids)
                    remain = max(0, info["daily_max"] - used)
                    lbl = self.mount_remain_labels[key]
                    self._count_after(_count_generation, 0, lambda l=lbl, r=remain, u=used, n=info["name"]: l.set("剩余次数: %d (已用%d)" % (r, u)))
                    self._log("[坐骑副本2] %s剩余%d (已用%d)" % (info["name"], remain, used))
                flow.disconnect()
            except Exception as e:
                self._log("[坐骑副本2] 检测异常: %s" % e)
            finally:
                self._count_after(_count_generation, 0, lambda: self.btn_mount_check.config(state="normal"))
                self._count_after(_count_generation, 0, lambda: self.btn_mount_run.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _do_mount_run(self, selected_pair=None, batch_data=None, batch_group=None,
                      on_finished=None, ignore_sweep=False):
        if not self.current_save:
            messagebox.showwarning("提示", "请先选择存档")
            return

        selected = []  # (分组key, 普通层, BOSS层, 层级名)
        if batch_data is not None:
            for key, info in self.MOUNT_COPY_GROUPS.items():
                pairs = {normal: (normal, boss) for normal, boss, name in info["pairs"]}
                names = {normal: name for normal, boss, name in info["pairs"]}
                for normal_mid in batch_data.get(key, []):
                    pair = pairs.get(normal_mid)
                    if not pair:
                        continue
                    selected.append((key, pair[0], pair[1], names.get(normal_mid, info["name"])))
        else:
            for key, info in self.MOUNT_COPY_GROUPS.items():
                names = {normal: name for normal, boss, name in info["pairs"]}
                for (normal_mid, boss_mid), var in self.mount_pair_vars[key].items():
                    if (key, (normal_mid, boss_mid)) == selected_pair or (selected_pair is None and var.get()):
                        selected.append((key, normal_mid, boss_mid, names.get(normal_mid, info["name"])))

        if not selected:
            messagebox.showwarning("提示", "请至少勾选一个关卡")
            return

        if not ignore_sweep:
            from official_sweep import dispatch
            if dispatch(self, "mount", [normal for _, normal, _, _ in selected]):
                return

        delay = self.var_mount_delay.get()
        pick_equip = self.var_mount_pick_equip.get()
        times = max(1, min(3, int(self.var_mount_times.get())))
        self.btn_mount_run.config(state="disabled")
        self._log("[坐骑副本2] 开始刷取 %d 个关卡（每层最多%d次，按剩余次数自动截断）..."
                  % (len(selected), times))

        _run_slot, _run_client = self.current_save['index'], self.client
        def worker():
            try:
                flow, entry, scene = self._connect_and_enter(_run_slot)
                cur = scene.get('curRecord', {})
                p1 = scene.get('record', {}).get('p1', {})
                current_exp = p1.get("experience", 0)
                property_p1_str = "%d;%d;%d;%d;%d;%d" % (p1.get("hpMax",0), p1.get("mpMax",0), p1.get("atk",0), p1.get("phyDef",0), p1.get("reHP",0), p1.get("reMP",0))

                prop_map = {}
                equip_map = {}
                try:
                    _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2", "150___Prop.xml.json")
                    if os.path.exists(_bp):
                        with open(_bp, 'r', encoding='utf-8') as _f:
                            _pd = json.load(_f)
                        _recs = _pd.get('RECORD', _pd if isinstance(_pd, list) else [])
                        if isinstance(_recs, dict):
                            _recs = [_recs]
                        for _r in _recs:
                            if isinstance(_r, dict):
                                prop_map[str(_r.get('id'))] = _r.get('name', '?')
                except:
                    pass
                try:
                    _bp = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2", "046___Equipment.xml.json")
                    if os.path.exists(_bp):
                        with open(_bp, 'r', encoding='utf-8') as _f:
                            _pd = json.load(_f)
                        _recs = _pd.get('RECORD', _pd if isinstance(_pd, list) else [])
                        if isinstance(_recs, dict):
                            _recs = [_recs]
                        for _r in _recs:
                            if isinstance(_r, dict):
                                equip_map[str(_r.get('id'))] = _r.get('name', '?')
                except:
                    pass

                drop_stats = {}
                success = 0
                fail = 0

                from count_states import usage
                used_map = usage(scene)
                budgets = {}
                for key, info in self.MOUNT_COPY_GROUPS.items():
                    used = sum(used_map.get(int(mid), 0) for mid in info["share_ids"])
                    budgets[key] = max(0, info["daily_max"] - used)
                plan = []
                for key, normal_mid, boss_mid, group_name in selected:
                    count = min(times, budgets.get(key, 0))
                    for _ in range(count):
                        plan.append((normal_mid, group_name, "普通层"))
                        if boss_mid:
                            plan.append((boss_mid, group_name, "BOSS层"))
                    if count:
                        budgets[key] = budgets.get(key, 0) - count
                    else:
                        self._log("[坐骑副本2] %s剩余次数已用完，跳过%s。"
                                  % (self.MOUNT_COPY_GROUPS[key]["name"], group_name))
                if not plan:
                    self._log("[坐骑副本2] 剩余次数不足，没有可执行的关卡。")
                self._log("[坐骑副本2] 本次计划执行 %d 个关卡。" % len(plan))

                for idx, (mid, group, layer_type) in enumerate(plan):
                    self._log("[%d/%d] %s-%s(%d)" % (idx+1, len(plan), group, layer_type, mid))
                    try:
                        create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                        if create_result.get("code") != 200:
                            self._log("  创建失败: %s" % create_result.get("error", ""))
                            fail += 1
                            time.sleep(delay)
                            continue

                        drops = create_result.get("drops", {})
                        copy_id = drops.get("copyId", 0)
                        new_drops = drops.get("newDrops", [])

                        pick_items = []
                        mob_ids = []
                        kill_monsters = []
                        total_exp = 0
                        total_sp = 0
                        for d in new_drops:
                            d_mid = d.get("monsterId", "0")
                            d_idx = d.get("index", 0)
                            total_exp += d.get("exp", 0)
                            total_sp += d.get("spirit", 0)
                            has_drop = False

                            items = d.get("item", {})
                            if items:
                                has_drop = True
                                for item_id, item_list in items.items():
                                    for item in (item_list if isinstance(item_list, list) else [item_list]):
                                        pick_items.append(item)
                                    cnt = len(item_list) if isinstance(item_list, list) else 1
                                    drop_stats[item_id] = drop_stats.get(item_id, 0) + cnt

                            equips = d.get("equip", {})
                            if equips and pick_equip:
                                has_drop = True
                                for equip_id, equip_list in equips.items():
                                    for equip in (equip_list if isinstance(equip_list, list) else [equip_list]):
                                        pick_items.append(equip)
                                    cnt = len(equip_list) if isinstance(equip_list, list) else 1
                                    drop_stats[equip_id] = drop_stats.get(equip_id, 0) + cnt
                                    ename = equip_map.get(equip_id, '?')
                                    self._log("    ★ 装备掉落: %s(%s)x%d" % (ename, equip_id, cnt))

                            if has_drop:
                                mob_ids.append(d_mid)
                                kill_monsters.append("%s_%d" % (d_mid, d_idx))

                        time.sleep(2)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.5)
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                        time.sleep(0.5)

                        sync_data = {
                            "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                            "killMonsters": kill_monsters, "completed": 1,
                            "currentEXP": current_exp, "pickExp": total_exp, "pickSp": total_sp,
                            "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                        }
                        sync_result = flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                        if sync_result.get("code") == 200:
                            add_data = sync_result.get("add", {})
                            new_equips = add_data.get("newEquips", [])
                            if new_equips:
                                self._log("    sync确认装备: %d件" % len(new_equips))
                            self._log("  通关成功")
                            success += 1
                        else:
                            self._log("  同步失败: %s" % sync_result.get("error", ""))
                            fail += 1
                    except Exception as e:
                        self._log("  异常: %s" % e)
                        fail += 1
                    time.sleep(delay)

                self._log("\n[坐骑副本2] 完成! 成功%d 失败%d" % (success, fail))
                if drop_stats:
                    self._log("  掉落统计:")
                    for iid, cnt in sorted(drop_stats.items(), key=lambda x: -x[1]):
                        iname = prop_map.get(str(iid), equip_map.get(str(iid), iid))
                        self._log("    %s(%s): %d" % (iname, iid, cnt))
                flow.disconnect()
            except Exception as e:
                self._log("[坐骑副本2] 异常: %s" % e)
                import traceback
                self._log(traceback.format_exc())
            finally:
                self.root.after(0, lambda: self.btn_mount_run.config(state="normal"))

                self.root.after(0, lambda: self._refresh_finished_counts(_run_slot, _run_client))
                if on_finished:
                    self.root.after(0, on_finished)

        threading.Thread(target=worker, daemon=True).start()

    # ========== 太古秘境标签页 ==========
    def _build_taigu_tab(self):
        tab = self._daily2_page("太古秘境", padding=10)

        # 关卡列表
        taigu_levels = [
            (2146, "凤凰祭坛·鸿鹄"),
            (2160, "凤凰祭坛·紫凤"),
            (2147, "蛟龙祭坛·赢鱼"),
            (2162, "蛟龙祭坛·虺蛇"),
            (2155, "麒麟祭坛·当康"),
            (2163, "麒麟祭坛·驺吾"),
            (2158, "白泽祭坛·巫咸"),
            (2167, "白泽祭坛·仓颉"),
            (2150, "灵龟祭坛·灵龟"),
            (2168, "灵龟祭坛·龙龟"),
        ]
        self.taigu_levels = taigu_levels
        taigu_names = [name for _, name in taigu_levels]

        # 左侧：关卡选择
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 第1次
        f1 = ttk.LabelFrame(left_frame, text="第1次", padding=8)
        f1.pack(fill="x", pady=5)
        self.var_taigu_level1 = tk.StringVar(value=taigu_names[0])
        ttk.Combobox(f1, textvariable=self.var_taigu_level1, values=taigu_names, state="readonly", width=25).pack(padx=5, pady=5)

        # 第2次
        f2 = ttk.LabelFrame(left_frame, text="第2次（可重复）", padding=8)
        f2.pack(fill="x", pady=5)
        self.var_taigu_level2 = tk.StringVar(value=taigu_names[0])
        ttk.Combobox(f2, textvariable=self.var_taigu_level2, values=taigu_names, state="readonly", width=25).pack(padx=5, pady=5)

        # 右侧设置
        right_frame = ttk.Frame(tab, width=220)
        right_frame.pack(side="right", fill="y")

        setting_frame = ttk.LabelFrame(right_frame, text="设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        self.lbl_taigu_remain = ttk.Label(setting_frame, text="剩余次数: 待检测", foreground="blue")
        self.lbl_taigu_remain.grid(row=0, column=0, columnspan=2, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=1, column=0, sticky="w", pady=5)
        self.var_taigu_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_taigu_delay, width=10).grid(row=1, column=1, pady=5)

        self.btn_taigu_check = ttk.Button(setting_frame, text="检测剩余次数", command=self._do_taigu_check)
        self.btn_taigu_check.grid(row=2, column=0, columnspan=2, pady=5)

        self.btn_taigu_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_taigu_run, state="disabled")
        self.btn_taigu_run.grid(row=3, column=0, columnspan=2, pady=5)

        info_frame = ttk.LabelFrame(right_frame, text="说明", padding=10)
        info_frame.pack(fill="x", pady=(0, 10))
        ttk.Label(info_frame, text=(
            "太古秘境:\n- 十选二,可重复选同一关\n- 每天2次免费,共享次数\n- 掉落:太古币+对应精血\n- 不消耗体力\n\n先检测次数,再选关卡\n绝对不花点券!"
        ), justify="left").pack()

        return tab

    def _do_taigu_check(self):
        if not self._ensure_login():
            return
        self._log("[太古秘境] 检测剩余次数...")
        threading.Thread(target=self._taigu_check_worker, daemon=True).start()

    def _taigu_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        try:
            flow, _, scene = self._connect_and_enter()
            from count_states import usage
            used_map = usage(scene)
            info = self._taigu_limit_info()
            # 太古 10 关共享次数，计数落在实际打的关卡上（2146 自身通常为 0），必须按 shareDungeonID 求和
            used = sum(used_map.get(mid, 0) for mid in info["share_ids"])
            remain = max(0, info["daily_max"] - used)
            self._count_after(_count_generation, 0, lambda: self.lbl_taigu_remain.config(
                text="剩余次数: %d/%d（已用%d）" % (remain, info["daily_max"], used)))
            self._count_after(_count_generation, 0, lambda: self.btn_taigu_run.config(state="normal"))
            self._log("[太古秘境] 剩余次数: %d/%d（已用%d，共享 %d 关）" % (
                remain, info["daily_max"], used, len(info["share_ids"])))
            flow.disconnect()
        except Exception as e:
            self._log("[太古秘境] 检测异常: %s" % e)

    def _taigu_limit_info(self):
        """太古秘境次数规则取自 036___Dungeon（入口 2146 的 shareDungeonID + dailyCountMax）"""
        cached = getattr(self, "_taigu_limit_cache", None)
        if cached:
            return cached
        info = {"share_ids": [2146], "daily_max": 2}
        try:
            with open(os.path.join(CONFIG_DIR, "036___Dungeon.xml.json"), encoding="utf-8") as file:
                rows = json.load(file).get("RECORD", [])
            row = next((r for r in rows if isinstance(r, dict) and str(r.get("id")) == "2146"), None)
            if row:
                share = str(row.get("shareDungeonID") or "").replace(";", ",")
                ids = [int(x) for x in share.split(",") if x.strip().isdigit()]
                if ids:
                    info["share_ids"] = ids
                daily_max = int(row.get("dailyCountMax", 2))
                if daily_max > 0:
                    info["daily_max"] = daily_max
        except (OSError, ValueError, KeyError) as exc:
            self._log("[太古秘境] 次数配置读取失败，按 2146/2 次兜底：%s" % exc)
        self._taigu_limit_cache = info
        return info

    def _do_taigu_run(self):
        if not self._ensure_login():
            return
        # 从下拉框获取选择的关卡
        name1 = self.var_taigu_level1.get()
        name2 = self.var_taigu_level2.get()
        selected = []
        for mid, name in self.taigu_levels:
            if name == name1:
                selected.append((mid, name))
            if name == name2:
                selected.append((mid, name))
        if not selected:
            messagebox.showwarning("提示", "请选择关卡")
            return
        delay = self.var_taigu_delay.get()
        self.btn_taigu_run.config(state="disabled")
        self._log("[太古秘境] 开始刷取 %d 次..." % len(selected))
        threading.Thread(target=self._taigu_run_worker, args=(selected, delay), daemon=True).start()

    def _taigu_run_worker(self, selected, delay):
        try:
            flow, _, scene = self._connect_and_enter()
            cur = scene.get('curRecord', {})
            self._log("[太古秘境] 角色: %s Lv.%s" % (cur.get('p1', {}).get('kindName', '?'), cur.get('p1', {}).get('level', '?')))
            # 道具背包余量预检：太古每关至少 2~3 件道具，格子不足会结算 500 丢掉落
            ib = cur.get("itemsBag") or {}
            bag_cap = ib.get("itemCount") or 0
            bag_used = len(ib.get("items") or [])
            bag_free = max(0, bag_cap - bag_used)
            self._log("[道具背包] 已用%d/%d 剩余%d" % (bag_used, bag_cap, bag_free))
            if bag_cap and bag_free < 5:
                self._log("[太古秘境] 道具背包剩余不足5格，已停止，请先清理背包")
                flow.disconnect()
                return
            prop_map = {}
            try:
                config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
                # 150=道具  137=属性/专属晶核（petCrystal 分组用）
                for fname in ("150___Prop.xml.json", "137___PetCrystal.xml.json"):
                    with open(os.path.join(config_dir, fname), encoding='utf-8') as f:
                        prop_data = json.load(f)
                    records = prop_data.get('RECORD', prop_data if isinstance(prop_data, list) else [])
                    if isinstance(records, dict): records = [records]
                    for r in records:
                        if isinstance(r, dict): prop_map[str(r.get('id'))] = r.get('name', '?')
            except: pass
            drop_stats = {}
            success = 0
            fail = 0
            for idx, (mid, group) in enumerate(selected):
                name = prop_map.get(str(mid), str(mid))
                self._log("[%d/%d] %s-%s(%d)" % (idx+1, len(selected), group, name, mid))
                try:
                    create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                    if create_result.get("code") != 200:
                        self._log("  创建失败: %s" % create_result.get("error", ""))
                        fail += 1
                        time.sleep(delay)
                        continue
                    drops = create_result.get("drops", {})
                    copy_id = drops.get("copyId", 0)
                    new_drops = drops.get("newDrops", [])
                    pick_items = []
                    mob_ids = []
                    kill_monsters = []
                    for d in new_drops:
                        d_mid = d.get("monsterId", "0")
                        d_idx = d.get("index", 0)
                        for field, group in drop_groups(d):
                            mob_ids.append(d_mid)
                            kill_monsters.append("%s_%d" % (d_mid, d_idx))
                            tag = {"item": "道具", "equip": "装备", "feather": "羽毛", "soul": "魂器", "petCrystal": "晶核"}.get(field, field)
                            for item_id, item_list in group.items():
                                if isinstance(item_list, list): pick_items.extend(item_list)
                                else: pick_items.append(str(item_list))
                                cnt = len(item_list) if isinstance(item_list, list) else 1
                                drop_stats[item_id] = drop_stats.get(item_id, 0) + cnt
                                iname = prop_map.get(str(item_id), str(item_id))
                                self._log("    %s掉落: %s(%s) x%d" % (tag, iname, item_id, cnt))
                    time.sleep(3)
                    flow.request("scene.copyHandler.bossDead", None, timeout=10)
                    time.sleep(0.5)
                    flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                    time.sleep(0.5)
                    sync_result = flow.request("scene.copyHandler.syncDropInfoNew", {
                        "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                        "killMonsters": kill_monsters, "completed": 1,
                        "currentEXP": 0, "pickExp": 0, "pickSp": 0,
                        "propertyP1Str": "hpMax;mpMax;atk;phyDef;reHP;reMP",
                        "propertyP2Total": 0, "hitCombo": 100,
                    }, timeout=15)
                    if sync_result.get("code") == 200:
                        self._log("  通关成功")
                        success += 1
                        add = sync_result.get("add") or {}
                        for crystal in add.get("newPetCrystal") or []:
                            if isinstance(crystal, dict):
                                cid = str(crystal.get("id"))
                                self._log("  ✔ 晶核入包: %s(%s) entityId=%s 词条=%s" % (
                                    prop_map.get(cid, cid), cid, crystal.get("entityId"),
                                    json.dumps(crystal.get("attrs") or {}, ensure_ascii=False)))
                        for equip in add.get("newEquips") or []:
                            if isinstance(equip, dict):
                                eid = str(equip.get("id"))
                                self._log("  ✔ 装备入包: %s(%s) entityId=%s" % (
                                    prop_map.get(eid, eid), eid, equip.get("entityId")))
                        for soul in add.get("newSouls") or []:
                            if isinstance(soul, dict):
                                sid = str(soul.get("id"))
                                self._log("  ✔ 魂器入包: %s(%s) entityId=%s" % (
                                    prop_map.get(sid, sid), sid, soul.get("entityId")))
                    else:
                        self._log("  同步失败: %s" % sync_result.get("error", ""))
                        fail += 1
                except Exception as e:
                    self._log("  异常: %s" % e)
                    fail += 1
                time.sleep(delay)
            self._log("[太古秘境] 完成! 成功%d, 失败%d" % (success, fail))
            if drop_stats:
                self._log("[太古秘境] 掉落汇总:")
                for item_id, cnt in drop_stats.items():
                    iname = prop_map.get(str(item_id), str(item_id))
                    self._log("  %s(%s): %d个" % (iname, item_id, cnt))
            flow.disconnect()
        except Exception as e:
            self._log("[太古秘境] 运行异常: %s" % e)
        finally:
            self.root.after(0, lambda: self.btn_taigu_run.config(state="normal"))


    def _do_time_check(self):
        """刷新时光之舟状态"""
        if not self._ensure_login():
            return
        self._log("[时光之舟] 刷新状态...")
        threading.Thread(target=self._time_check_worker, daemon=True).start()

    def _time_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        try:
            flow, _, scene = self._connect_and_enter()
            try:
                info = flow.request("scene.playerThirdHandler.getTimeGiftInfo", {}, timeout=10)
                gift_data = info.get('timeGift', {})
                return_list = gift_data.get('returnTimeList', [])
                offline_time = gift_data.get('offlineTime', 0)
                self._log("[时光之舟] 已重置: %s, 离线时长: %s" % (return_list, offline_time))

                for rid, rname in self.time_gift_items:
                    if rid in return_list:
                        self._count_after(_count_generation, 0, lambda r=rid: self.time_status_labels[r].config(text=self.time_gift_items[[x[0] for x in self.time_gift_items].index(r)][1] + ": 已重置", foreground="gray"))
                        self._count_after(_count_generation, 0, lambda r=rid: self.time_buttons[r].config(state="disabled"))
                    else:
                        self._count_after(_count_generation, 0, lambda r=rid: self.time_status_labels[r].config(text=self.time_gift_items[[x[0] for x in self.time_gift_items].index(r)][1] + ": 可重置", foreground="green"))
                        self._count_after(_count_generation, 0, lambda r=rid: self.time_buttons[r].config(state="normal"))

                # 三日福利状态
                if offline_time and offline_time > 0:
                    self._count_after(_count_generation, 0, lambda: self.lbl_time_gift.config(text="状态: 可领取(%d分钟)" % offline_time, foreground="green"))
                    self._count_after(_count_generation, 0, lambda: self.btn_time_gift.config(state="normal"))
                else:
                    self._count_after(_count_generation, 0, lambda: self.lbl_time_gift.config(text="状态: 未到时间", foreground="gray"))
                    self._count_after(_count_generation, 0, lambda: self.btn_time_gift.config(state="disabled"))
            except Exception as e:
                self._log("[时光之舟] 获取状态异常: %s" % e)
            flow.disconnect()
        except Exception as e:
            self._log("[时光之舟] 刷新异常: %s" % e)

    def _do_time_reset(self, reset_id):
        """重置指定关卡"""
        if not self._ensure_login():
            return
        name_map = {1: "太古秘境", 2: "冰封层", 3: "水岩层", 4: "熔岩层"}
        rname = name_map.get(reset_id, str(reset_id))
        if not messagebox.askyesno("确认", "确定重置%s吗？（每天1次）" % rname):
            return
        self._log("[时光之舟] 重置%s..." % rname)
        threading.Thread(target=self._time_reset_worker, args=(reset_id, rname), daemon=True).start()

    def _time_reset_worker(self, reset_id, rname):
        try:
            flow, _, scene = self._connect_and_enter()
            result = flow.request("scene.playerThirdHandler.returnTime", {"id": reset_id}, timeout=10)
            if result.get('code') == 200:
                self._log("[时光之舟] %s重置成功!" % rname)
                self.root.after(0, lambda: self.time_status_labels[reset_id].config(text=rname + ": 已重置", foreground="gray"))
                self.root.after(0, lambda: self.time_buttons[reset_id].config(state="disabled"))
            else:
                self._log("[时光之舟] %s重置失败: %s" % (rname, result.get('error', '')))
            flow.disconnect()
        except Exception as e:
            self._log("[时光之舟] 重置异常: %s" % e)

    def _do_time_gift(self):
        """领取三日福利（周末双倍 活动451）"""
        if not self._ensure_login():
            return
        self._log("[三日福利] 领取周末双倍（活动451）...")
        threading.Thread(target=self._time_gift_worker, daemon=True).start()

    def _time_gift_worker(self):
        try:
            flow, _, scene = self._connect_and_enter()
            result = flow.request("scene.playerHandler.rewardGiftByFree", {"activeId": 451}, timeout=15)
            if result.get('code') == 200:
                self._log("[三日福利] 领取成功!")
                add_data = result.get('add', {})
                if add_data:
                    for k, v in add_data.items():
                        if isinstance(v, (int, float)) and v > 0:
                            self._log("  获得: %s x%d" % (k, v))
                self.root.after(0, lambda: self.lbl_time_gift.config(text="状态: 已领取", foreground="gray"))
                self.root.after(0, lambda: self.btn_time_gift.config(state="disabled"))
            elif "不能重复领取" in str(result.get('error', '')):
                self._log("[三日福利] 今日已领取，无需重复")
                self.root.after(0, lambda: self.lbl_time_gift.config(text="状态: 今日已领取", foreground="gray"))
                self.root.after(0, lambda: self.btn_time_gift.config(state="disabled"))
            else:
                self._log("[三日福利] 领取失败: %s" % result.get('error', ''))
            flow.disconnect()
        except Exception as e:
            self._log("[三日福利] 领取异常: %s" % e)

    # ========== 时光之舟标签页 ==========
    def _build_timeboat_tab(self):
        tab = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(tab, text="时光之舟")

        pages = ttk.Notebook(tab)
        pages.pack(fill="both", expand=True)
        reset_tab = ttk.Frame(pages, padding=5)
        pages.add(reset_tab, text="时光重现")

        # 从配置文件读取可重置项
        self.timeboat_items = []
        try:
            config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
            with open(os.path.join(config_dir, "221___TimeRepeat.xml.json"), encoding='utf-8') as f:
                tr_data = json.load(f)
            records = tr_data.get('RECORD', [])
            if isinstance(records, dict):
                records = [records]
            for r in records:
                if isinstance(r, dict):
                    rid = int(r.get('id', 0))
                    desc = r.get('describe', '')
                    # 提取名称
                    name = desc.replace("你确认重置", "").replace("挑战次数？", "").replace("可接受次数？", "")
                    rtype = int(r.get('type', 1))
                    level = int(r.get('level', 0))
                    self.timeboat_items.append((rid, name, rtype, level))
        except Exception as e:
            self._log("[时光之舟] 读取配置失败: %s" % e)
            # 默认项
            self.timeboat_items = [
                (1, "守卫须弥山", 1, 30), (2, "悲鸣冰川-冰封层", 1, 20),
                (3, "悲鸣冰川-水岩层", 1, 35), (4, "悲鸣冰川-熔岩层", 1, 44),
                (5, "福禄寿", 1, 20), (6, "螺旋地狱", 1, 20),
                (7, "日常任务", 2, 20), (8, "悬赏任务", 3, 26),
                (9, "罗汉堂", 1, 20), (10, "主题挑战", 1, 20),
                (11, "枯焰流沙", 1, 20), (12, "迷雾沮泽", 1, 20),
                (13, "空桑谷", 1, 80), (14, "地藏冥殿", 1, 60),
                (15, "月华境", 1, 80), (16, "丰花原野", 1, 20),
                (17, "云隐渊", 1, 80), (18, "太古秘境", 1, 80),
                (19, "虚空藏院", 1, 60),
            ]

        # 左侧：可重置项列表
        left_frame = ttk.Frame(reset_tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # 提示
        tip_frame = ttk.Frame(left_frame)
        tip_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(tip_frame, text="仅周五、周六、周日可用", foreground="red", font=("Arial", 10, "bold")).pack(side="left")
        self.lbl_timeboat_week = ttk.Label(tip_frame, text="", foreground="blue")
        self.lbl_timeboat_week.pack(side="left", padx=10)

        # 滚动区域
        canvas = tk.Canvas(left_frame)
        scrollbar = ttk.Scrollbar(left_frame, orient="vertical", command=canvas.yview)
        scroll_frame = ttk.Frame(canvas)
        scroll_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        self.timeboat_status_labels = {}
        self.timeboat_buttons = {}
        for i, (rid, name, rtype, level) in enumerate(self.timeboat_items):
            row_frame = ttk.Frame(scroll_frame)
            row_frame.pack(fill="x", pady=2)
            type_str = {1: "副本", 2: "日常", 3: "悬赏"}.get(rtype, "?")
            lbl = ttk.Label(row_frame, text="[%s] Lv.%d %s" % (type_str, level, name), width=30, anchor="w")
            lbl.pack(side="left", padx=5)
            status_lbl = ttk.Label(row_frame, text="待检测", width=10)
            status_lbl.pack(side="left", padx=5)
            self.timeboat_status_labels[rid] = status_lbl
            btn = ttk.Button(row_frame, text="重置", width=8, command=lambda r=rid, n=name: self._do_timeboat_reset(r, n))
            btn.pack(side="left", padx=5)
            self.timeboat_buttons[rid] = btn
            ttk.Button(row_frame, text="打开设置", width=9,
                       command=lambda r=rid: self._open_timeboat_settings(r)).pack(side="left", padx=5)

        # 右侧：重置操作
        right_frame = ttk.Frame(reset_tab, width=200)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        setting_frame = ttk.LabelFrame(right_frame, text="操作", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        self.btn_timeboat_check = ttk.Button(setting_frame, text="刷新状态", command=self._do_timeboat_check)
        self.btn_timeboat_check.pack(fill="x", pady=5)

        # 说明
        info_frame = ttk.LabelFrame(right_frame, text="说明", padding=10)
        info_frame.pack(fill="x")
        ttk.Label(info_frame, text=(
            "时光之舟:\n"
            "- 仅周五六日开放\n"
            "- 周五至周日共可重置4项\n"
            "- 重置后副本次数恢复\n"
            "- 三日福利已移至日常助手\n"
            "\n"
            "先刷新状态\n"
            "再点对应重置按钮"
        ), justify="left").pack()

        return tab

    def _build_fulushou_panel(self, parent):
        ttk.Label(parent, text="福禄寿每日各可挑战一次；结算分数固定为 190。", foreground="blue").pack(anchor="w", pady=(0, 10))
        self.fls_status = {}
        self.fls_buttons = {}
        for mid, name in ((2003, "福星"), (2020, "禄星"), (2046, "寿星")):
            row = ttk.Frame(parent)
            row.pack(fill="x", pady=4)
            ttk.Label(row, text=name, width=10).pack(side="left")
            status = ttk.Label(row, text="待刷新", width=20)
            status.pack(side="left", padx=8)
            self.fls_status[mid] = status
            button = ttk.Button(row, text="挑战并结算", state="disabled",
                                command=lambda m=mid, n=name: self._do_fulushou(m, n))
            button.pack(side="left")
            self.fls_buttons[mid] = button
        ttk.Button(parent, text="刷新挑战次数", command=self._refresh_fulushou).pack(anchor="w", pady=10)

    def _fulushou_counts(self, scene):
        history = scene.get("curRecord", {}).get("copyHistory", [])
        return {mid: int(next((r.get("num", 0) for r in history
                               if int(r.get("id", -1)) == mid), 0))
                for mid in (2003, 2020, 2046)}

    def _refresh_fulushou(self):
        if not self._ensure_login():
            return
        threading.Thread(target=self._fulushou_refresh_worker, daemon=True).start()

    def _fulushou_refresh_worker(self):
        try:
            _, _, scene = self._connect_and_enter()
            counts = self._fulushou_counts(scene)
            self.root.after(0, lambda: self._show_fulushou_counts(counts))
            self._log("[福禄寿] 当前挑战次数：%s" % counts)
        except Exception as e:
            self._log("[福禄寿] 刷新失败：%s" % e)

    def _show_fulushou_counts(self, counts):
        for mid, count in counts.items():
            self.fls_status[mid].config(text="今日 %d/1" % count)
            self.fls_buttons[mid].config(state="normal" if count < 1 else "disabled")

    def _do_fulushou(self, mid, name):
        if not self._ensure_login():
            return
        self.fls_buttons[mid].config(state="disabled")
        threading.Thread(target=self._fulushou_worker, args=(mid, name), daemon=True).start()

    def _fulushou_worker(self, mid, name):
        try:
            flow, _, scene = self._connect_and_enter()
            if self._fulushou_counts(scene)[mid] >= 1:
                self._log("[福禄寿] %s 今日次数已用完" % name)
                return
            cur = scene["curRecord"]
            p1 = cur["p1"]
            created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                   {"mid": mid, "costGem": 0}, timeout=15)
            if created.get("code") != 200:
                raise RuntimeError("创建副本失败：%s" % created)
            drops = created.get("drops") or {}
            copy_id = drops.get("copyId")
            if not copy_id:
                raise RuntimeError("创建副本未返回 copyId")
            dead = flow.request("scene.copyHandler.bossDead", None, timeout=15)
            if dead.get("code") != 200:
                raise RuntimeError("Boss 死亡通知失败：%s" % dead)
            finished = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
            if finished.get("code") != 200:
                raise RuntimeError("通关请求失败：%s" % finished)
            payload = {
                "copyId": copy_id, "pickItems": [], "mobIds": [], "killMonsters": [],
                "completed": 1, "currentEXP": p1["experience"], "pickExp": 0,
                "pickSp": 0, "propertyP1Str": ";".join(str(p1[k]) for k in
                    ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
                "propertyP2Total": 0, "hitCombo": 100, "score": 190,
            }
            if mid == 2046:
                payload.update({"deletedItems": {"sellItems": {}, "useItems": {}, "equipID": []},
                                "p1OnEquips": None, "p2OnEquips": None, "_mobNum": 190})
            settled = flow.request("scene.copyHandler.syncDropInfoNew", payload, timeout=20)
            if settled.get("code") != 200:
                raise RuntimeError("190 分结算失败：%s" % settled)
            self._log("[福禄寿] %s 190 分结算成功" % name)
        except Exception as e:
            self._log("[福禄寿] %s 挑战失败：%s" % (name, e))
        finally:
            self._fulushou_refresh_worker()

    def _build_wanted_panel(self, parent):
        config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
        self.wanted_task_defs = {}
        self.shenyu_wanted_defs = {}
        self.wanted_base_limit = None
        self.shenyu_week_limit = None
        self._wanted_vip_extra = {}
        self._shenyu_vip_extra = {}
        try:
            with open(os.path.join(config_dir, "026___Common.xml.json"), encoding="utf-8") as f:
                self.wanted_base_limit = int(json.load(f)["RECORD"]["wantedDayNum"])
            with open(os.path.join(config_dir, "175___ShenyuWanted.xml.json"), encoding="utf-8") as f:
                self.shenyu_week_limit = int(json.load(f)["RECORD"]["weekNum"])
            with open(os.path.join(config_dir, "236___Vip.xml.json"), encoding="utf-8") as f:
                vip_rows = [row for row in json.load(f)["RECORD"] if isinstance(row, dict)]
            self._wanted_vip_extra = {int(row["id"]): int(row.get("wantedDayNum", 0) or 0)
                                      for row in vip_rows}
            self._shenyu_vip_extra = {int(row["id"]): int(row.get("ShenyuWanted", 0) or 0)
                                      for row in vip_rows}
            with open(os.path.join(config_dir, "210___TaskType.xml.json"), encoding="utf-8") as f:
                task_rows = json.load(f)["RECORD"]
            with open(os.path.join(config_dir, "036___Dungeon.xml.json"), encoding="utf-8") as f:
                dungeon_rows = json.load(f)["RECORD"]
            with open(os.path.join(config_dir, "164___Reward.xml.json"), encoding="utf-8") as f:
                reward_rows = json.load(f)["RECORD"]
            with open(os.path.join(config_dir, "150___Prop.xml.json"), encoding="utf-8") as f:
                prop_rows = json.load(f)["RECORD"]
            dungeons = {int(d["id"]): d for d in dungeon_rows}
            rewards = {int(r["id"]): r for r in reward_rows}
            prop_names = {str(r["id"]): r.get("name", str(r["id"])) for r in prop_rows}
            for task in task_rows:
                if int(task.get("taskClass", -1)) == 4:
                    tid = int(task["id"])
                    reward_id = int(task.get("rewardId1", -1))
                    reward = rewards.get(reward_id, {})
                    item_ids = [x for x in str(reward.get("itemId", "")).split(";") if x and x != "-1"]
                    item_counts = [x for x in str(reward.get("num", "")).split(";") if x]
                    reward_labels = []
                    for index, item_id in enumerate(item_ids):
                        count = item_counts[index] if index < len(item_counts) else "1"
                        label = "%s×%s" % (prop_names.get(item_id, item_id), count)
                        if item_id == "199100031":
                            label += "（一级莲珠袋×2）"
                        elif item_id == "199100032":
                            label += "（随机一级莲珠袋×2或×3）"
                        reward_labels.append(label)
                    name = str(task.get("name", ""))
                    mid = int(task.get('dungeonId', -1))
                    target = int(task.get('targetId', -1))
                    stages = [mid]
                    if target != mid:
                        target_config = dungeons.get(target, {})
                        if str(target_config.get('comefromId')) == str(mid) or str(target_config.get('fromId')) == str(mid):
                            stages.append(target)
                    supported = (int(task.get('taskType', -1)) == 0 and
                                 int(task.get('targetNum', -1)) == 1 and stages[-1] == target and
                                 all(stage in dungeons and int(dungeons[stage].get('consumePointTicket', -1)) == 0
                                     and int(dungeons[stage].get('consumePower', 0)) == -1
                                     and int(dungeons[stage].get('clearType', -1)) in (1, 2, 4) for stage in stages))
                    self.shenyu_wanted_defs[tid] = {
                        "name": name if name and "�" not in name else "神域任务",
                        "mid": int(task.get("dungeonId", -1)),
                        "reward_item_ids": item_ids,
                        "reward_items": reward_labels,
                        "soul_stone": "197100008" in item_ids,
                        "target_mid": int(task.get("targetId", -1)),
                        "stages": stages, "supported": supported,
                        "reward_counts": {iid: int(item_counts[index]) if index < len(item_counts) else 1
                                          for index, iid in enumerate(item_ids)},
                    }
                    continue
                if int(task.get("taskClass", -1)) != 3:
                    continue
                tid = int(task["id"])
                mid = int(task.get("dungeonId", -1))
                dungeon = dungeons.get(mid, {})
                self.wanted_task_defs[tid] = {
                    "name": task.get("name", str(tid)), "mid": mid,
                    "dungeon_name": dungeon.get("name", str(mid)),
                    "clear_type": int(dungeon.get("clearType", -1)),
                    "supported": bool(dungeon and int(task.get("taskType", -1)) == 0
                        and int(task.get("targetId", -1)) == mid
                        and int(task.get("targetNum", -1)) == 1
                        and int(dungeon.get("consumePointTicket", -1)) == 0
                        and int(dungeon.get("consumePower", 0)) == -1
                        and int(dungeon.get("clearType", -1)) in (1, 4)),
                }
        except Exception as e:
            self._log("[悬赏] 读取任务配置失败：%s" % e)
        sections = ttk.Notebook(parent)
        sections.pack(fill="both", expand=True)
        normal_tab = ttk.Frame(sections, padding=5)
        shenyu_tab = ttk.Frame(sections, padding=5)
        sections.add(normal_tab, text="普通悬赏")
        sections.add(shenyu_tab, text="神域悬赏")
        ttk.Label(normal_tab, text="选择任务后可一键接取、通关、领奖；副本自身掉落不会领取。",
                  foreground="blue").pack(anchor="w", pady=(0, 8))
        ttk.Label(normal_tab, text="10148、10151、10153、10154 已逐项实测；双倍任务 10149 尚未逐项实测，接取占两次。",
                  foreground="brown").pack(anchor="w", pady=(0, 8))
        self.lbl_wanted_summary = ttk.Label(normal_tab, text="待刷新")
        self.lbl_wanted_summary.pack(anchor="w", pady=(0, 8))
        self.wanted_rows = {}
        for _ in range(8):
            row = ttk.Frame(normal_tab)
            row.pack(fill="x", pady=2)
            label = ttk.Label(row, text="", width=58, anchor="w")
            label.pack(side="left")
            accept = ttk.Button(row, text="接取并完成", state="disabled")
            accept.pack(side="left", padx=2)
            challenge = ttk.Button(row, text="继续完成", state="disabled")
            challenge.pack(side="left", padx=2)
            claim = ttk.Button(row, text="领奖", state="disabled")
            claim.pack(side="left", padx=2)
            self.wanted_rows[_] = (label, accept, challenge, claim)
        quick_row = ttk.Frame(normal_tab)
        quick_row.pack(anchor="w", pady=10)
        ttk.Button(quick_row, text="刷新悬赏状态", command=self._refresh_wanted).pack(side="left")
        self.btn_wanted_drain = ttk.Button(quick_row, text="打满今日次数（自动接取/通关/领奖）",
                                           command=self._do_wanted_drain)
        self.btn_wanted_drain.pack(side="left", padx=6)

        self._build_shenyu_panel(shenyu_tab)

    def _build_shenyu_panel(self, parent):
        if not hasattr(self, "shenyu_panels"):
            self.shenyu_panels = []
        panel = {}
        summary = ttk.Label(parent, text="选择此页后读取当前榜单")
        summary.pack(anchor="w", pady=(0, 8))
        soul_alert = ttk.Label(parent, text="魂石任务：待读取", foreground="#9b1c1c")
        soul_alert.pack(anchor="w", pady=(0, 8))
        tree = ttk.Treeview(parent, columns=("task", "dungeon", "reward", "status"),
                            show="headings", height=8)
        for key, title, width in (("task", "任务", 190), ("dungeon", "关卡", 80),
                                  ("reward", "任务奖励物品", 360), ("status", "状态", 110)):
            tree.heading(key, text=title)
            tree.column(key, width=width, anchor="w")
        tree.tag_configure("soul", background="#ffe4ad", foreground="#a00000")
        tree.pack(fill="both", expand=True)
        actions = ttk.Frame(parent)
        actions.pack(anchor="w", pady=8)
        panel.update({"parent": parent, "tree": tree, "summary": summary,
                      "soul_alert": soul_alert})
        refresh = ttk.Button(actions, text="刷新神域悬赏",
                             command=lambda: self._refresh_shenyu_wanted(panel))
        refresh.pack(side="left", padx=(0, 8))
        complete = ttk.Button(actions, text="完成选中任务并领奖", state="disabled",
                              command=lambda: self._do_shenyu_wanted_complete(panel))
        complete.pack(side="left")
        panel["complete"] = complete
        tree.bind("<<TreeviewSelect>>", lambda event: self._shenyu_wanted_select(panel))

        notebook = parent
        while notebook is not None and not isinstance(notebook, ttk.Notebook):
            notebook = getattr(notebook, "master", None)
        if notebook is not None:
            notebook.bind("<<NotebookTabChanged>>",
                          lambda event: self._refresh_shenyu_wanted(panel)
                          if notebook.select() == str(parent)
                          and self.client and self.current_save is not None else None,
                          add="+")
        self.shenyu_panels.append(panel)

    def _refresh_shenyu_wanted(self, panel=None):
        if not self._ensure_login():
            return
        for item in self.shenyu_panels:
            item["summary"].config(text="正在读取当前榜单…")
        threading.Thread(target=self._shenyu_wanted_refresh_worker, daemon=True).start()

    def _shenyu_wanted_refresh_worker(self):
        flow = None
        try:
            flow, _, scene = self._connect_and_enter()
            board = flow.request("scene.taskHandler.lookupShenYuWantedTask", {"force": 0}, timeout=15)
            if board.get("code") != 200:
                raise RuntimeError(board.get("error", board.get("code")))
            shenyu = (board.get("taskList") or {}).get("shenyu") or {}
            tasks = shenyu.get("tasks") or {}
            if not isinstance(tasks, dict):
                raise RuntimeError("神域任务列表格式异常")
            active = {int(x["taskId"]): int(x.get("taskState", 0))
                      for x in scene.get("curRecord", {}).get("curTasks", [])
                      if isinstance(x, dict) and "taskId" in x}
            snapshot = (list(tasks), int(shenyu.get("freeCnt", 0)), active,
                        int((scene.get("user") or {}).get("vipLevel") or 0))
            self.root.after(0, lambda data=snapshot: self._show_shenyu_wanted(data))
        except Exception as e:
            self._log("[神域悬赏] 读取失败：%s" % e)
            self.root.after(0, lambda error=str(e): self._show_shenyu_error(error))
        finally:
            if flow is not None:
                flow.disconnect()

    def _show_shenyu_wanted(self, snapshot):
        task_ids, free_used, active, vip = snapshot
        task_ids = list(dict.fromkeys([int(tid) for tid in task_ids] +
                                     [tid for tid in active if tid in self.shenyu_wanted_defs]))
        soul_ids = []
        rows = []
        for raw_id in task_ids:
            tid = int(raw_id)
            info = self.shenyu_wanted_defs.get(tid, {})
            soul = info.get("soul_stone", False)
            if soul:
                soul_ids.append(tid)
            status = "可领奖" if active.get(tid) == 1 else (
                "进行中" if tid in active else "榜单任务")
            reward = ", ".join(info.get("reward_items", [])) or "配置未找到"
            rows.append((tid, soul, (
                "%s%s（%d）" % ("★ 魂石任务 " if soul else "",
                             info.get("name", "神域任务"), tid),
                ' → '.join(map(str, info.get('stages', [info.get('mid', '?')]))), reward,
                status if info.get('supported') else '配置不支持')))
        base = self.shenyu_week_limit or 0
        extra = self._shenyu_vip_extra.get(vip, 0)
        if base:
            limit_text = ("，本周上限 %d（基础 %d + VIP%d 加成 %d）" % (base + extra, base, vip, extra)
                          if extra else "，本周上限 %d（基础 %d，VIP%d 无加成）" % (base, base, vip))
        else:
            limit_text = "，本周上限读取失败"
        summary_text = ("当前榜单 %d 项；本周已使用免费次数 %d%s" %
                        (len(task_ids), free_used, limit_text))
        soul_text = ("★ 魂石任务提醒：%s" % ", ".join(map(str, soul_ids))
                     if soul_ids else "当前榜单没有直接奖励魂石宝箱的任务")
        for panel in self.shenyu_panels:
            tree = panel["tree"]
            tree.delete(*tree.get_children())
            for tid, soul, values in rows:
                tree.insert("", "end", iid=str(tid), values=values,
                            tags=("soul",) if soul else ())
            panel["summary"].config(text=summary_text)
            panel["soul_alert"].config(text=soul_text)
            panel["complete"].config(state="disabled")

    def _show_shenyu_error(self, error):
        for panel in self.shenyu_panels:
            panel["summary"].config(text="读取失败：%s" % error)

    def _shenyu_wanted_select(self, panel):
        selected = panel["tree"].selection()
        panel["complete"].config(
            state="normal" if selected and self.shenyu_wanted_defs.get(int(selected[0]), {}).get('supported') else "disabled")

    def _do_shenyu_wanted_complete(self, panel=None):
        if not self._ensure_login():
            return
        if panel is None:
            panel = self.shenyu_panels[0]
        selected = panel["tree"].selection()
        if not selected:
            return
        task_id = int(selected[0])
        if not self.shenyu_wanted_defs.get(task_id, {}).get('supported'):
            return
        if not messagebox.askyesno("确认任务", "将实际接取并完成神域悬赏%d，消耗一次免费任务次数，继续吗？" % task_id):
            return
        panel["complete"].config(state="disabled")
        threading.Thread(target=self._shenyu_wanted_complete_worker,
                         args=(task_id, self.current_save['index']), daemon=True).start()

    def _shenyu_wanted_complete_worker(self, task_id, save_index=None):
        flow = None
        try:
            if save_index is None: save_index = self.current_save['index']
            flow, _, scene = self._connect_and_enter(save_index)
            board = flow.request("scene.taskHandler.lookupShenYuWantedTask", {"force": 0}, timeout=15)
            if board.get("code") != 200:
                raise RuntimeError("读取榜单失败：%s" % board.get("error", board))
            tasks = ((board.get("taskList") or {}).get("shenyu") or {}).get("tasks") or {}
            active = next((x for x in scene.get("curRecord", {}).get("curTasks", [])
                           if str(x.get("taskId")) == str(task_id)), None)
            if str(task_id) not in tasks and active is None:
                raise RuntimeError("任务已不在当前榜单")
            info = self.shenyu_wanted_defs[task_id]
            if not info.get('supported'): raise RuntimeError('任务或分支配置不支持')
            stages = info['stages']
            points_before = {key: scene['user'][key] for key in ('gem', 'usedGem')}
            config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output_cg1_20260921_1_2')
            with open(os.path.join(config_dir, '175___ShenyuWanted.xml.json'), encoding='utf-8') as file:
                base_limit = int(json.load(file)['RECORD']['weekNum'])
            with open(os.path.join(config_dir, '236___Vip.xml.json'), encoding='utf-8') as file:
                vip_rows = json.load(file)['RECORD']
            vip = int(scene['user']['vipLevel'])
            vip_config = next(row for row in vip_rows if int(row['id']) == vip)
            quota = base_limit + int(vip_config['ShenyuWanted'])
            shenyu_state = (board.get('taskList') or {}).get('shenyu') or {}
            if 'freeCnt' not in shenyu_state: raise RuntimeError('未读到免费次数，停止执行')
            if int(shenyu_state['freeCnt']) >= quota: raise RuntimeError('本周免费次数已用完，不购买次数')
            bag = scene['curRecord'].get('itemsBag') or {}
            needed = sum(self._special_item_count(scene, iid) == 0 for iid in info['reward_item_ids'])
            if int(bag.get('itemCount', 0))-len(bag.get('items') or []) < needed:
                raise RuntimeError('任务奖励所需背包空间不足，请先清理')
            before = {item_id: self._special_item_count(scene, item_id)
                      for item_id in info["reward_item_ids"]}
            if active is None:
                started = flow.request("scene.taskHandler.startTask", {"taskId": task_id}, timeout=15)
                if started.get("code") != 200:
                    raise RuntimeError("接取失败：%s" % started.get("error", started))
                active = {"taskState": 0}
                self._log("[神域悬赏] 任务%d接取成功。" % task_id)
            if int(active.get("taskState", 0)) == 0:
                from mainfarm_routes import clear_stage
                for mid in stages:
                    clear_stage(flow, scene, mid, enter_w=True, reward_mode='none')
                    self._log("[神域悬赏] 关卡%d免费结算成功，未拾取副本掉落。" % mid)
                flow.disconnect()
                flow, _, scene = self._connect_and_enter(save_index)
                active = next((x for x in scene.get("curRecord", {}).get("curTasks", [])
                               if str(x.get("taskId")) == str(task_id)), None)
            if not active or int(active.get("taskState", 0)) != 1:
                raise RuntimeError("任务未变为可领奖，请刷新榜单检查")
            claimed = flow.request("scene.taskHandler.handoverTask", {"taskId": task_id}, timeout=20)
            if claimed.get("code") != 200:
                raise RuntimeError("领奖失败：%s" % claimed.get("error", claimed))
            self._log("[神域悬赏] 任务%d领奖成功：%s" % (task_id, claimed.get("items")))
            flow.disconnect()
            flow, _, after = self._connect_and_enter(save_index)
            for item_id, before_count in before.items():
                after_count = self._special_item_count(after, item_id)
                self._log("[神域悬赏] 物品%s：%d → %d，增加%d。" %
                          (item_id, before_count, after_count, after_count - before_count))
                if after_count-before_count != info['reward_counts'][item_id]:
                    raise RuntimeError('重登后任务奖励数量与配置不符，请查看日志，不重试领奖')
            if points_before != {key: after['user'][key] for key in points_before}:
                raise RuntimeError('点券或累计消费发生变化，请核查')
            self._log('[神域悬赏] 任务%d全流程核验通过，点券未变。' % task_id)
        except Exception as e:
            self._log("[神域悬赏] 任务%d已停止：%s" % (task_id, e))
        finally:
            if flow is not None:
                try:
                    flow.disconnect()
                except Exception:
                    pass
            self.root.after(0, self._refresh_shenyu_wanted)

    def _wanted_state(self, flow, scene, refresh_board=True):
        board = flow.request("scene.taskHandler.lookupWantedTask",
                             {"isRefresh": 1 if refresh_board else 0}, timeout=15)
        if board.get("code") != 200:
            raise RuntimeError("查询悬赏榜单失败：%s" % board)
        cur = scene.get("curRecord", {})
        wanted = cur.get("wantedTask") or {}
        listed = board.get("taskList") or {}
        if isinstance(listed, dict):
            ids = listed.get("taskIdList") or []
            if isinstance(ids, str):
                ids = [x for x in ids.replace(";", ",").split(",") if x]
        else:
            ids = listed if isinstance(listed, list) else []
        active = {int(t["taskId"]): t for t in cur.get("curTasks", [])
                  if isinstance(t, dict) and "taskId" in t}
        completed = wanted.get("completeList") or listed.get("completeList") or []
        if isinstance(completed, str):
            completed = [x for x in completed.replace(";", ",").split(",") if x]
        completed = {int(x) for x in completed}
        ids = list(dict.fromkeys(int(x) for x in ids))
        # An accepted bounty may remain active after the board rotates.
        active = {tid: task for tid, task in active.items() if tid in self.wanted_task_defs}
        for tid in active:
            if tid not in ids:
                ids.append(tid)
        day_num = wanted.get("wantedDayNum", listed.get("wantedDayNum", "?"))
        double_reward = listed.get("doubleReward", wanted.get("doubleReward"))
        vip = int((scene.get("user") or {}).get("vipLevel") or 0)
        return ids, active, completed, day_num, double_reward, vip

    def _refresh_wanted(self):
        if not self._ensure_login():
            return
        threading.Thread(target=self._wanted_refresh_worker, daemon=True).start()

    def _wanted_refresh_worker(self):
        try:
            flow, _, scene = self._connect_and_enter()
            state = self._wanted_state(flow, scene)
            self.root.after(0, lambda: self._show_wanted_state(state))
            self._log("[悬赏] 榜单和任务状态已刷新")
        except Exception as e:
            self._log("[悬赏] 刷新失败：%s" % e)

    def _count_wanted_worker(self):
        """切档刷新复用：只读榜单，不主动刷新（isRefresh=0），避免消耗刷新次数"""
        flow, _, scene = self._connect_and_enter()
        state = self._wanted_state(flow, scene, refresh_board=False)
        self._show_wanted_state(state)

    def _show_wanted_state(self, state):
        ids, active, completed, day_num, double_reward, vip = state
        base = self.wanted_base_limit
        extra = self._wanted_vip_extra.get(vip, 0)
        if base:
            if extra:
                limit_text = " / 上限 %s（基础 %s + VIP%d 加成 %s）" % (base + extra, base, vip, extra)
            else:
                limit_text = " / 上限 %s（基础 %s，VIP%d 无加成）" % (base, base, vip)
        else:
            limit_text = ""
        self.lbl_wanted_summary.config(text="今日已接取：%s%s；当前任务：%s" %
                                       (day_num, limit_text, ", ".join(map(str, ids)) or "无"))
        for i, widgets in self.wanted_rows.items():
            label, accept, challenge, claim = widgets
            for button in (accept, challenge, claim):
                button.config(state="disabled", command=lambda: None)
            if i >= len(ids):
                label.config(text="")
                continue
            tid = ids[i]
            info = self.wanted_task_defs.get(tid, {})
            task = active.get(tid)
            ready = task is not None and int(task.get("taskState", 0)) == 1
            if ready:
                status = "可领奖"
            elif task:
                progress = (task.get("taskData") or {}).get("dungeonCnt", 0)
                status = "进行中 %s/1" % progress
            elif tid in completed:
                status = "已领奖"
            else:
                status = "榜单可接取（次数由服务器判定）"
            doubles = double_reward if isinstance(double_reward, list) else [double_reward]
            double_text = "  [双倍，接取占两次]" if str(tid) in [str(x) for x in doubles] else ""
            test_text = "已实测" if tid in (10148, 10151, 10153, 10154) else "未逐项实测"
            label.config(text="%s (%s) → %s (%s)  |  %s  [%s]%s" %
                         (info.get("name", "未知任务"), tid, info.get("dungeon_name", "未知副本"),
                          info.get("mid", "?"), status, test_text, double_text))
            if not info.get("supported"):
                continue
            if ready:
                claim.config(state="normal", command=lambda t=tid: self._wanted_action("claim", t))
            elif task:
                challenge.config(state="normal", command=lambda t=tid: self._wanted_action("challenge_claim", t))
            elif tid not in completed:
                accept.config(state="normal", command=lambda t=tid: self._wanted_action("all", t))

    def _wanted_action(self, action, tid):
        if not self._ensure_login():
            return
        for _, buttons in self.wanted_rows.items():
            for button in buttons[1:]:
                button.config(state="disabled")
        threading.Thread(target=self._wanted_action_worker, args=(action, tid), daemon=True).start()

    def _wanted_action_worker(self, action, tid):
        try:
            info = self.wanted_task_defs.get(tid, {})
            if not info.get("supported"):
                raise RuntimeError("任务配置不符合已确认的免费副本路线")
            flow, _, scene = self._connect_and_enter()
            ids, active, completed, day_num, double_reward, vip = self._wanted_state(flow, scene)
            task = active.get(tid)
            if action == "all":
                if tid not in ids or task or tid in completed:
                    raise RuntimeError("任务不在当前可接取榜单")
                doubles = double_reward if isinstance(double_reward, list) else [double_reward]
                cost = 2 if str(tid) in [str(x) for x in doubles] else 1
                base = self.wanted_base_limit or 0
                quota = base + self._wanted_vip_extra.get(vip, 0)
                used = int(day_num) if str(day_num).isdigit() else 0
                if quota and used + cost > quota:
                    self._log("[悬赏] 今日次数将超上限：已接取 %d + 本次 %d > 上限 %d（基础%d+VIP%d加成%d），仍提交由服务器判定"
                              % (used, cost, quota, base, vip, quota - base))
                if cost == 2:
                    self._log("[悬赏] 任务 %s 为双倍任务，接取将占用两次" % tid)
                result = flow.request("scene.taskHandler.startTask", {"taskId": tid}, timeout=15)
                if result.get("code") != 200:
                    raise RuntimeError("接取失败：%s" % result)
                self._log("[悬赏] 任务 %s 接取成功" % tid)
                action = "challenge_claim"
                task = {"taskState": 0}
            if action == "challenge_claim":
                if not task or int(task.get("taskState", 0)) != 0:
                    raise RuntimeError("任务不在进行中")
                cur = scene["curRecord"]
                p1 = cur["p1"]
                mid = info["mid"]
                created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                       {"mid": mid, "costGem": 0}, timeout=15)
                if created.get("code") != 200:
                    raise RuntimeError("创建副本失败：%s" % created)
                copy_id = (created.get("drops") or {}).get("copyId")
                if not copy_id:
                    raise RuntimeError("副本未返回 copyId")
                dead = flow.request("scene.copyHandler.bossDead", None, timeout=15)
                if dead.get("code") != 200:
                    raise RuntimeError("Boss 死亡通知失败：%s" % dead)
                finished = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                if finished.get("code") != 200:
                    raise RuntimeError("通关失败：%s" % finished)
                payload = {"copyId": copy_id, "pickItems": [], "mobIds": [], "killMonsters": [],
                           "completed": 16777217, "currentEXP": p1["experience"],
                           "pickExp": 0, "pickSp": 0,
                           "propertyP1Str": ";".join(str(p1[k]) for k in
                               ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
                           "propertyP2Total": 0, "hitCombo": 100}
                result = flow.request("scene.copyHandler.syncDropInfoNew", payload, timeout=20)
                if result.get("code") != 200:
                    raise RuntimeError("副本结算失败：%s" % result)
                self._log("[悬赏] 任务 %s 副本结算成功；未领取副本掉落" % tid)
                flow, _, scene = self._connect_and_enter()
                _, active, _, _, _, _ = self._wanted_state(flow, scene)
                task = active.get(tid)
                if not task or int(task.get("taskState", 0)) != 1:
                    raise RuntimeError("结算已提交，但任务尚未变为可领奖；请刷新状态后检查")
                action = "claim"
            if action == "claim":
                if not task or int(task.get("taskState", 0)) != 1:
                    raise RuntimeError("任务尚未达到可领奖状态")
                result = flow.request("scene.taskHandler.handoverTask", {"taskId": tid}, timeout=15)
                if result.get("code") != 200:
                    raise RuntimeError("任务领奖失败：%s" % result)
                self._log("[悬赏] 任务 %s 领奖成功：%s" %
                          (tid, {k: result.get(k) for k in ("items", "equips", "addExp", "addSpirit")}))
                try:
                    _, _, after_scene = self._connect_and_enter()
                    before_record = scene["curRecord"]
                    after_record = after_scene["curRecord"]
                    for reward in result.get("items", []):
                        item_id = reward.get("id")
                        expected = int(reward.get("count", 0))
                        before_count = self._special_item_count(scene, item_id)
                        after_count = self._special_item_count(after_scene, item_id)
                        delta = after_count - before_count
                        self._log("[悬赏核验] 物品 %s：%d → %d（增加 %d；回包 %d）%s" %
                                  (item_id, before_count, after_count, delta, expected,
                                   "" if delta == expected else "，与回包不一致"))
                    spirit_before = int(before_record.get("spirit", 0))
                    spirit_after = int(after_record.get("spirit", 0))
                    spirit_delta = spirit_after - spirit_before
                    self._log("[悬赏核验] 灵魂：%d → %d（增加 %d；回包 %s）%s" %
                              (spirit_before, spirit_after, spirit_after - spirit_before,
                               result.get("addSpirit", 0),
                               "" if spirit_delta == int(result.get("addSpirit", 0)) else "，与回包不一致"))
                    p1_before = before_record["p1"]
                    p1_after = after_record["p1"]
                    exp_delta = int(p1_after.get("experience", 0)) - int(p1_before.get("experience", 0))
                    same_level = p1_before.get("level") == p1_after.get("level")
                    exp_note = ("" if exp_delta == int(result.get("addExp", 0)) else "，与回包不一致") if same_level else "，等级变化时需结合升级经验核对"
                    self._log("[悬赏核验] 经验：等级 %s / %s → 等级 %s / %s（回包增加 %s）%s" %
                              (p1_before.get("level"), p1_before.get("experience"),
                               p1_after.get("level"), p1_after.get("experience"),
                               result.get("addExp", 0), exp_note))
                except Exception as verify_error:
                    self._log("[悬赏核验] 领奖已成功，但重新登录核对失败：%s" % verify_error)
            else:
                raise RuntimeError("未知操作")
        except Exception as e:
            self._log("[悬赏] %s 失败：%s" % (action, e))
        finally:
            self._wanted_refresh_worker()

    def _do_wanted_drain(self):
        if not self._ensure_login():
            return
        for _, buttons in self.wanted_rows.items():
            for button in buttons[1:]:
                button.config(state="disabled")
        self.btn_wanted_drain.config(state="disabled")
        threading.Thread(target=self._wanted_drain_worker, daemon=True).start()

    def _wanted_run_round(self, tid, info):
        """单轮：接取 → 通关 → 领奖（每轮独立会话，避免使用过期 curRecord）。"""
        flow, _, scene = self._connect_and_enter()
        _, active, _, _, _, _ = self._wanted_state(flow, scene)
        task = active.get(tid)
        if task is None:
            started = flow.request("scene.taskHandler.startTask", {"taskId": tid}, timeout=15)
            if started.get("code") != 200:
                raise RuntimeError("接取失败：%s" % started.get("error", started.get("code")))
            task = {"taskState": 0}
        if int(task.get("taskState", 0)) == 0:
            p1 = scene["curRecord"]["p1"]
            mid = info["mid"]
            created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                   {"mid": mid, "costGem": 0}, timeout=15)
            if created.get("code") != 200:
                raise RuntimeError("创建副本失败：%s" % created.get("error", created.get("code")))
            copy_id = (created.get("drops") or {}).get("copyId")
            if not copy_id:
                raise RuntimeError("副本未返回 copyId")
            flow.request("scene.copyHandler.bossDead", None, timeout=15)
            flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
            settled = flow.request("scene.copyHandler.syncDropInfoNew", {
                "copyId": copy_id, "pickItems": [], "mobIds": [], "killMonsters": [],
                "completed": 16777217, "currentEXP": p1["experience"], "pickExp": 0, "pickSp": 0,
                "propertyP1Str": ";".join(str(p1[k]) for k in
                    ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP")),
                "propertyP2Total": 0, "hitCombo": 100}, timeout=20)
            if settled.get("code") != 200:
                raise RuntimeError("副本结算失败：%s" % settled.get("error", settled.get("code")))
            flow.disconnect()
            flow, _, scene = self._connect_and_enter()
            _, active, _, _, _, _ = self._wanted_state(flow, scene)
            task = active.get(tid)
            if not task or int(task.get("taskState", 0)) != 1:
                raise RuntimeError("副本已结算，但任务尚未变为可领奖")
        claimed = flow.request("scene.taskHandler.handoverTask", {"taskId": tid}, timeout=20)
        if claimed.get("code") != 200:
            raise RuntimeError("领奖失败：%s" % claimed.get("error", claimed.get("code")))
        flow.disconnect()
        return claimed

    def _wanted_drain_worker(self):
        try:
            done = []
            for round_no in range(1, 16):
                flow, _, scene = self._connect_and_enter()
                ids, active, completed, day_num, double_reward, vip = self._wanted_state(flow, scene)
                flow.disconnect()
                base = self.wanted_base_limit or 0
                quota = base + self._wanted_vip_extra.get(vip, 0)
                used = int(day_num) if str(day_num).isdigit() else 0
                if not quota:
                    self._log("[悬赏] 无法确定今日上限，停止打满")
                    break
                if used >= quota:
                    self._log("[悬赏] 今日已打满：%d/%d（基础 %d + VIP%d 加成 %d）"
                              % (used, quota, base, vip, quota - base))
                    break
                doubles = [str(x) for x in (double_reward if isinstance(double_reward, list)
                                            else ([double_reward] if double_reward is not None else []))]
                tid = next((t for t, task in active.items()
                            if self.wanted_task_defs.get(t, {}).get("supported")
                            and int(task.get("taskState", 0)) in (0, 1)), None)
                cost = 0
                if tid is None:
                    tid = next((t for t in ids if t not in active and t not in completed
                                and self.wanted_task_defs.get(t, {}).get("supported")), None)
                    if tid is None:
                        self._log("[悬赏] 榜单没有可接的已确认任务，停止打满")
                        break
                    cost = 2 if str(tid) in doubles else 1
                    if used + cost > quota:
                        self._log("[悬赏] 剩余 %d 次不够接双倍任务（占 %d 次），停止打满"
                                  % (quota - used, cost))
                        break
                info = self.wanted_task_defs[tid]
                self._log("[悬赏] 第%d轮：任务%d%s（已用 %d/%d）"
                          % (round_no, tid, "（双倍占2次）" if cost == 2 else "", used, quota))
                self._wanted_run_round(tid, info)
                done.append(tid)
                self._log("[悬赏] 任务%d 已完成并领奖" % tid)
            if done:
                self._log("[悬赏] 本轮打满结束，共完成 %d 个任务：%s" % (len(done), done))
        except Exception as e:
            self._log("[悬赏] 打满失败：%s" % e)
        finally:
            self._wanted_refresh_worker()

    def _do_timeboat_check(self):
        if not self._ensure_login():
            return
        self._log("[时光之舟] 刷新状态...")
        threading.Thread(target=self._timeboat_check_worker, daemon=True).start()

    def _timeboat_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        try:
            flow, _, scene = self._connect_and_enter()
            # 检查今天星期几
            import datetime
            weekday = datetime.datetime.now().weekday()  # 0=周一, 4=周五, 5=周六, 6=周日
            week_names = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
            is_available = weekday >= 4  # 周五六日
            self._count_after(_count_generation, 0, lambda: self.lbl_timeboat_week.config(text="今天:%s %s" % (week_names[weekday], "可使用" if is_available else "不可用")))

            try:
                info = flow.request("scene.playerThirdHandler.getTimeGiftInfo", {}, timeout=10)
                gift_data = info.get('timeGift', {})
                return_list = gift_data.get('returnTimeList', [])
                offline_time = gift_data.get('offlineTime', 0)
                if not isinstance(return_list, list):
                    return_list = []
                remaining = max(0, 4 - len(return_list))
                self._log("[时光之舟] 已重置: %s, 剩余次数: %d, 离线: %s天" %
                          (return_list, remaining, offline_time))
                self._count_after(_count_generation, 0, lambda: self.lbl_timeboat_week.config(
                    text="今天:%s %s，剩余%d次" %
                         (week_names[weekday], "可使用" if is_available else "不可用", remaining)))

                for rid, name, rtype, level in self.timeboat_items:
                    if rid in return_list:
                        self._count_after(_count_generation, 0, lambda r=rid: self.timeboat_status_labels[r].config(text="已重置", foreground="gray"))
                        self._count_after(_count_generation, 0, lambda r=rid: self.timeboat_buttons[r].config(state="disabled"))
                    else:
                        if is_available and remaining > 0:
                            self._count_after(_count_generation, 0, lambda r=rid: self.timeboat_status_labels[r].config(text="可重置", foreground="green"))
                            self._count_after(_count_generation, 0, lambda r=rid: self.timeboat_buttons[r].config(state="normal"))
                        else:
                            self._count_after(_count_generation, 0, lambda r=rid, x=remaining: self.timeboat_status_labels[r].config(
                                text="次数已用完" if is_available and x == 0 else "未开放", foreground="gray"))
                            self._count_after(_count_generation, 0, lambda r=rid: self.timeboat_buttons[r].config(state="disabled"))

                # 三日福利（活动451 周末双倍）：无查询接口，按星期与领取返回判断
                gift_hint = "今日可领（周五/六/日）" if is_available else "未开放（仅周五~周日）"
                self._count_after(_count_generation, 0, lambda: self.lbl_timeboat_gift.config(
                    text=gift_hint, foreground="green" if is_available else "gray"))
                self._count_after(_count_generation, 0, lambda: self.btn_timeboat_gift.config(
                    state="normal" if is_available else "disabled"))
            except Exception as e:
                self._log("[时光之舟] 获取状态异常: %s" % e)
            flow.disconnect()
        except Exception as e:
            self._log("[时光之舟] 刷新异常: %s" % e)

    _TIMEBOAT_PAGE_MAP = {
        1: ("周本", "守卫须弥山城西"),
        2: ("坐骑副本", "悲鸣冰川", "冰封层"),
        3: ("坐骑副本", "悲鸣冰川", "水岩层"),
        4: ("坐骑副本", "冰川（熔岩层）"),
        5: ("日常助手", "福禄寿190"),
        6: ("日常助手2", "螺旋地狱"),
        7: ("日常任务",),
        8: ("日常助手2", "悬赏任务"),
        9: ("日常助手2", "罗汉堂"),
        10: ("日常助手2", "主题挑战"),
        11: ("坐骑副本", "枯焰流沙"),
        12: ("坐骑副本", "迷雾沮泽"),
        13: ("宠物装备副本", "空桑谷"),
        14: ("日常助手2", "地藏/虚空藏"),
        15: ("宠物装备副本", "月华境"),
        16: ("坐骑副本", "丰花原野"),
        17: ("宠物装备副本", "云隐渊"),
        18: ("日常助手2", "太古秘境"),
        19: ("日常助手2", "地藏/虚空藏"),
    }

    def _find_notebook_tab(self, parent, title):
        queue = [parent]
        while queue:
            widget = queue.pop(0)
            if isinstance(widget, ttk.Notebook):
                for tab_id in widget.tabs():
                    if str(widget.tab(tab_id, "text")) == title:
                        return widget, tab_id
            try:
                queue.extend(widget.winfo_children())
            except tk.TclError:
                continue
        return None, None

    def _open_timeboat_settings(self, reset_id):
        titles = self._TIMEBOAT_PAGE_MAP.get(reset_id)
        if not titles:
            messagebox.showinfo("时光之舟", "该重置项暂时没有对应的设置页面。", parent=self.root)
            return
        parent = self.root
        for title in titles:
            notebook, tab_id = self._find_notebook_tab(parent, title)
            if notebook is None:
                messagebox.showinfo("时光之舟", "未找到“%s”设置页面。" % title, parent=self.root)
                return
            notebook.select(tab_id)
            parent = notebook.nametowidget(tab_id)
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    def _do_timeboat_reset(self, reset_id, name):
        if not self._ensure_login():
            return
        if not messagebox.askyesno("确认", "确定重置%s吗？" % name):
            return
        self._log("[时光之舟] 重置%s..." % name)
        threading.Thread(target=self._timeboat_reset_worker, args=(reset_id, name), daemon=True).start()

    def _timeboat_reset_worker(self, reset_id, name):
        try:
            flow, _, scene = self._connect_and_enter()
            result = flow.request("scene.playerThirdHandler.returnTime", {"id": reset_id}, timeout=10)
            if result.get('code') == 200:
                self._log("[时光之舟] %s重置成功!" % name)
                self.root.after(0, lambda: self.timeboat_status_labels[reset_id].config(text="已重置", foreground="gray"))
                self.root.after(0, lambda: self.timeboat_buttons[reset_id].config(state="disabled"))
            else:
                self._log("[时光之舟] %s重置失败: %s" % (name, result.get('error', '')))
            flow.disconnect()
            if result.get('code') == 200:
                self._timeboat_check_worker()
        except Exception as e:
            self._log("[时光之舟] 重置异常: %s" % e)

    def _do_timeboat_gift(self):
        if not self._ensure_login():
            return
        self._log("[三日福利] 领取周末双倍（活动451）...")
        threading.Thread(target=self._timeboat_gift_worker, daemon=True).start()

    def _timeboat_gift_worker(self):
        try:
            flow, _, scene = self._connect_and_enter()
            result = flow.request("scene.playerHandler.rewardGiftByFree", {"activeId": 451}, timeout=15)
            if result.get('code') == 200:
                self._log("[三日福利] 领取成功!")
                add_data = result.get('add', {})
                if add_data:
                    for k, v in add_data.items():
                        if isinstance(v, (int, float)) and v > 0:
                            self._log("  获得: %s x%d" % (k, v))
                self.root.after(0, lambda: self.lbl_timeboat_gift.config(text="已领取", foreground="gray"))
                self.root.after(0, lambda: self.btn_timeboat_gift.config(state="disabled"))
            elif "不能重复领取" in str(result.get('error', '')):
                self._log("[三日福利] 今日已领取，无需重复")
                self.root.after(0, lambda: self.lbl_timeboat_gift.config(text="今日已领取", foreground="gray"))
                self.root.after(0, lambda: self.btn_timeboat_gift.config(state="disabled"))
            else:
                self._log("[三日福利] 领取失败: %s" % result.get('error', ''))
            flow.disconnect()
        except Exception as e:
            self._log("[三日福利] 领取异常: %s" % e)

    # ========== 螺旋地狱标签页 ==========
    def _build_luoxuan_tab(self):
        tab = self._daily2_page("螺旋地狱", padding=10)

        # 6个地狱关卡: (mid, 名称, BOSS数, 怪物ID列表, 默认次数)
        luoxuan_levels = [
            (2023, "转轮地狱", 1, [3189], 1),
            (2008, "蟾之地狱", 5, [3128, 3163, 3271, 3359, 3414], 0),
            (2009, "蛛之地狱", 15, [3127, 3133, 3134, 3162, 3168, 3169, 3270, 3272, 3273, 3358, 3360, 3361, 3430, 3431, 3432], 0),
            (2010, "蝎之地狱", 5, [3156, 3166, 3302, 3366, 3507], 0),
            (2011, "蚣之地狱", 5, [3154, 3164, 3300, 3365, 3532], 0),
            (2012, "蛇之地狱", 11, [3155, 3157, 3165, 3278, 3280, 3362, 3363, 3364, 3488, 3489, 3490], 0),
        ]
        self.luoxuan_levels = luoxuan_levels

        # 左侧：次数设置
        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        tip_frame = ttk.Frame(left_frame)
        tip_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(tip_frame, text="六地狱共享每天5次 | 转轮每天限1次 | 每关单独设次数", foreground="red").pack(anchor="w")

        # 次数设置列表
        list_frame = ttk.LabelFrame(left_frame, text="设置每关挑战次数", padding=8)
        list_frame.pack(fill="both", expand=True)

        self.luoxuan_count_vars = {}
        self.luoxuan_count_spins = {}
        for i, (mid, name, boss_num, monster_ids, default_cnt) in enumerate(luoxuan_levels):
            row_frame = ttk.Frame(list_frame)
            row_frame.pack(fill="x", pady=3)
            ttk.Label(row_frame, text="%s (%dBOSS)" % (name, boss_num), width=18).pack(side="left", padx=5)
            var = tk.IntVar(value=default_cnt)
            self.luoxuan_count_vars[mid] = var
            spin = ttk.Spinbox(row_frame, from_=0, to=5, textvariable=var, width=8)
            spin.pack(side="left", padx=5)
            self.luoxuan_count_spins[mid] = spin
            ttk.Label(row_frame, text="次", foreground="gray").pack(side="left")

        # 右侧设置
        right_frame = ttk.Frame(tab, width=240)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        setting_frame = ttk.LabelFrame(right_frame, text="设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        self.lbl_luoxuan_remain = ttk.Label(setting_frame, text="总剩余次数: 待检测", foreground="blue")
        self.lbl_luoxuan_remain.grid(row=0, column=0, columnspan=2, pady=5)

        self.lbl_luoxuan_total = ttk.Label(setting_frame, text="已设总次数: 1", foreground="green")
        self.lbl_luoxuan_total.grid(row=1, column=0, columnspan=2, pady=5)

        self.lbl_luoxuan_zhuanlun = ttk.Label(setting_frame, text="转轮剩余: 待检测", foreground="gray")
        self.lbl_luoxuan_zhuanlun.grid(row=2, column=0, columnspan=2, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=3, column=0, sticky="w", pady=5)
        self.var_luoxuan_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_luoxuan_delay, width=10).grid(row=3, column=1, pady=5)

        self.btn_luoxuan_check = ttk.Button(setting_frame, text="检测剩余次数", command=self._do_luoxuan_check)
        self.btn_luoxuan_check.grid(row=4, column=0, columnspan=2, pady=5)

        self.btn_luoxuan_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_luoxuan_run, state="disabled")
        self.btn_luoxuan_run.grid(row=5, column=0, columnspan=2, pady=5)

        # 说明
        info_frame = ttk.LabelFrame(right_frame, text="说明", padding=10)
        info_frame.pack(fill="x")
        ttk.Label(info_frame, text=(
            "每关单独设次数\n"
            "转轮默认1,其他0\n"
            "例:1转轮+4蛇\n\n"
            "通关流程:\n"
            "1.激活入口2007\n"
            "2.create目标地狱\n"
            "3.等3秒+bossDead\n"
            "4.finish+sync\n"
            "5.getSpecialDrop领奖\n\n"
            "困难难度需点券\n"
            "不建议碰"
        ), justify="left").pack()

        # 绑定次数变化事件
        for mid, var in self.luoxuan_count_vars.items():
            var.trace_add("write", lambda *a: self._update_luoxuan_total())

        return tab

    def _update_luoxuan_total(self):
        total = 0
        for mid, var in self.luoxuan_count_vars.items():
            try:
                total += int(var.get())
            except:
                pass
        self.lbl_luoxuan_total.config(text="已设总次数: %d" % total)

    def _do_luoxuan_check(self):
        if not self._ensure_login():
            return
        self._log("[螺旋地狱] 检测剩余次数...")
        threading.Thread(target=self._luoxuan_check_worker, daemon=True).start()

    def _luoxuan_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        try:
            flow, _, scene = self._connect_and_enter()
            cur = scene.get('curRecord', {})
            copy_history = cur.get('copyHistory', [])
            used_map = {}
            if isinstance(copy_history, list):
                for item in copy_history:
                    if isinstance(item, dict):
                        did = int(item.get('id', 0))
                        used_map[did] = int(item.get('num', 0))

            # 总次数（入口2007）
            total_used = used_map.get(2007, 0)
            total_max = 5
            total_remain = max(0, total_max - total_used)

            # 转轮次数
            zl_used = used_map.get(2023, 0)
            zl_remain = max(0, 1 - zl_used)

            self._count_after(_count_generation, 0, lambda: self.lbl_luoxuan_remain.config(
                text="总剩余次数: %d/%d" % (total_remain, total_max)))
            self._count_after(_count_generation, 0, lambda: self.lbl_luoxuan_zhuanlun.config(
                text="转轮剩余: %d/1" % zl_remain,
                foreground="green" if zl_remain > 0 else "red"))
            self._log("[螺旋地狱] 总已用%d/%d, 剩余%d次" % (total_used, total_max, total_remain))
            self._log("[螺旋地狱] 转轮已用%d, 剩余%d次" % (zl_used, zl_remain))

            # 更新次数上限
            for mid, spin in self.luoxuan_count_spins.items():
                self._count_after(_count_generation, 0, lambda s=spin: s.config(to=max(0, total_remain)))
            self._count_after(_count_generation, 0, lambda: self.btn_luoxuan_run.config(state="normal"))
            flow.disconnect()
        except Exception as e:
            self._log("[螺旋地狱] 检测异常: %s" % e)

    def _do_luoxuan_run(self):
        if not self._ensure_login():
            return
        # 收集要打的关卡和次数
        tasks = []
        total = 0
        for mid, name, boss_num, monster_ids, default_cnt in self.luoxuan_levels:
            cnt = self.luoxuan_count_vars[mid].get()
            if cnt > 0:
                tasks.append((mid, name, monster_ids, cnt))
                total += cnt
        if total == 0:
            messagebox.showwarning("提示", "请至少设置一个关卡的次数大于0")
            return
        delay = self.var_luoxuan_delay.get()
        self.btn_luoxuan_run.config(state="disabled")
        self._log("[螺旋地狱] 开始刷取, 共%d次: %s" % (total, ", ".join(["%sx%d" % (n, c) for m, n, mi, c in tasks])))
        threading.Thread(target=self._luoxuan_run_worker, args=(tasks, delay), daemon=True).start()

    def _luoxuan_run_worker(self, tasks, delay):
        try:
            flow, _, scene = self._connect_and_enter()
            cur = scene.get('curRecord', {})
            p1 = cur.get('p1', {})
            exp = p1.get('experience', 0)
            self._log("[螺旋地狱] 角色: %s Lv.%s" % (p1.get('kindName', '?'), p1.get('level', '?')))

            # 加载道具名称
            prop_map = {}
            try:
                config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
                with open(os.path.join(config_dir, "150___Prop.xml.json"), encoding='utf-8') as f:
                    prop_data = json.load(f)
                records = prop_data.get('RECORD', prop_data if isinstance(prop_data, list) else [])
                if isinstance(records, dict): records = [records]
                for r in records:
                    if isinstance(r, dict): prop_map[str(r.get('id'))] = r.get('name', '?')
            except: pass

            drop_stats = {}
            success = 0
            fail = 0
            task_idx = 0
            for mid, name, monster_ids, count in tasks:
                for i in range(count):
                    task_idx += 1
                    self._log("[%d] %s(%d) 第%d/%d次" % (task_idx, name, mid, i+1, count))
                    try:
                        # 步骤1: 激活入口2007
                        self._log("  [1/5] 激活入口2007...")
                        enter_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": 2007, "costGem": 0}, timeout=15)
                        if enter_result.get("code") != 200:
                            self._log("  入口激活失败: %s" % enter_result.get("error", ""))
                            fail += 1
                            time.sleep(delay)
                            continue
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": 2007}, timeout=15)
                        time.sleep(0.5)

                        # 步骤2: create目标地狱
                        self._log("  [2/5] create%s..." % name)
                        create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                        if create_result.get("code") != 200:
                            self._log("  关卡创建失败: %s" % create_result.get("error", ""))
                            fail += 1
                            time.sleep(delay)
                            continue
                        copy_id = create_result.get("drops", {}).get("copyId", 0)

                        # 步骤3: 等3秒 + bossDead
                        self._log("  [3/5] 等待3秒+bossDead...")
                        time.sleep(3)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.5)

                        # 步骤4: finish + sync
                        self._log("  [4/5] finish+sync...")
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                        time.sleep(0.5)
                        sync_result = flow.request("scene.copyHandler.syncDropInfoNew", {
                            "copyId": copy_id, "pickItems": [], "mobIds": [], "killMonsters": [],
                            "completed": 1, "currentEXP": exp, "pickExp": 0, "pickSp": 0,
                            "propertyP1Str": "hpMax;mpMax;atk;phyDef;reHP;reMP",
                            "propertyP2Total": 0, "hitCombo": 100,
                        }, timeout=15)
                        if sync_result.get("code") != 200:
                            self._log("  sync失败: %s" % sync_result.get("error", ""))

                        # 步骤5: getSpecialDrop领奖
                        self._log("  [5/5] getSpecialDrop领奖...")
                        reward = flow.request("scene.copyHandler.getSpecialDrop", {
                            "id": mid, "kills": monster_ids
                        }, timeout=15)
                        if reward.get("code") == 200:
                            items = reward.get("add", {}).get("items", [])
                            if items:
                                self._log("  获得物品:")
                                for it in items:
                                    iid = str(it.get('id', ''))
                                    cnt = it.get('count', 0)
                                    iname = prop_map.get(iid, iid)
                                    self._log("    %s(%s) x%d" % (iname, iid, cnt))
                                    drop_stats[iid] = drop_stats.get(iid, 0) + cnt
                            else:
                                self._log("  无物品掉落")
                            success += 1
                        else:
                            self._log("  领奖失败: %s" % reward.get("error", ""))
                            fail += 1
                    except Exception as e:
                        self._log("  异常: %s" % e)
                        fail += 1
                    time.sleep(delay)
            self._log("[螺旋地狱] 完成! 成功%d, 失败%d" % (success, fail))
            if drop_stats:
                self._log("[螺旋地狱] 掉落汇总:")
                for item_id, cnt in drop_stats.items():
                    iname = prop_map.get(str(item_id), str(item_id))
                    self._log("  %s(%s): %d个" % (iname, item_id, cnt))
            flow.disconnect()
        except Exception as e:
            self._log("[螺旋地狱] 运行异常: %s" % e)
        finally:
            self.root.after(0, lambda: self.btn_luoxuan_run.config(state="normal"))

    # ========== 罗汉堂标签页 ==========
    def _build_luohan_tab(self):
        tab = self._daily2_page("罗汉堂", padding=10)

        luohan_levels = [
            (6002, "坐鹿罗汉", [3305]),
            (6003, "欢喜罗汉", [3312]),
            (6004, "举钵罗汉", [3338, 3339]),
            (6005, "托塔罗汉", [3393, 3394, 3395]),
            (6006, "静坐罗汉", [3479, 3480]),
            (6007, "过江罗汉", [3613]),
            (6008, "布袋罗汉", [3621, 3622]),
            (6009, "骑象罗汉", [3628, 3630]),
            (6010, "芭蕉罗汉", [3632]),
            (6011, "看门罗汉", [3633, 3634]),
            (6012, "降龙罗汉", [3652]),
            (6013, "伏虎罗汉", [3653]),
            (6014, "探手罗汉", [3666]),
            (6015, "长眉罗汉", [3667]),
            (6016, "沉思罗汉", [3697]),
            (6017, "笑狮罗汉", [3765, 3766]),
            (6018, "挖耳罗汉", [3856]),
        ]
        self.luohan_levels = luohan_levels

        left_frame = ttk.Frame(tab)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        tip_frame = ttk.Frame(left_frame)
        tip_frame.pack(fill="x", pady=(0, 5))
        ttk.Label(tip_frame, text="18罗汉共享每天3次免费次数 | 可任选可重复 | 集齐法印进阶法宝", foreground="red").pack(anchor="w")

        list_frame = ttk.LabelFrame(left_frame, text="选择罗汉并分配次数（总共3次）", padding=8)
        list_frame.pack(fill="both", expand=True)

        self.luohan_count_vars = {}
        cols = 3
        for i, (mid, name, monster_ids) in enumerate(luohan_levels):
            row = i // cols
            col = i % cols
            cell_frame = ttk.Frame(list_frame)
            cell_frame.grid(row=row, column=col, sticky="w", padx=5, pady=3)
            ttk.Label(cell_frame, text=name, width=10).pack(side="left", padx=(0, 3))
            var = tk.IntVar(value=0)
            self.luohan_count_vars[mid] = var
            ttk.Spinbox(cell_frame, from_=0, to=3, textvariable=var, width=5).pack(side="left")
            ttk.Label(cell_frame, text="次", foreground="gray").pack(side="left", padx=(2, 0))

        right_frame = ttk.Frame(tab, width=220)
        right_frame.pack(side="right", fill="y")
        right_frame.pack_propagate(False)

        setting_frame = ttk.LabelFrame(right_frame, text="设置", padding=10)
        setting_frame.pack(fill="x", pady=(0, 10))

        self.lbl_luohan_remain = ttk.Label(setting_frame, text="剩余次数: 待检测", foreground="blue")
        self.lbl_luohan_remain.grid(row=0, column=0, columnspan=2, pady=5)

        self.lbl_luohan_total = ttk.Label(setting_frame, text="已设总次数: 0", foreground="green")
        self.lbl_luohan_total.grid(row=1, column=0, columnspan=2, pady=5)

        ttk.Label(setting_frame, text="间隔(秒):").grid(row=2, column=0, sticky="w", pady=5)
        self.var_luohan_delay = tk.DoubleVar(value=2.0)
        ttk.Spinbox(setting_frame, from_=0.5, to=10, increment=0.5, textvariable=self.var_luohan_delay, width=10).grid(row=2, column=1, pady=5)

        self.btn_luohan_check = ttk.Button(setting_frame, text="检测剩余次数", command=self._do_luohan_check)
        self.btn_luohan_check.grid(row=3, column=0, columnspan=2, pady=5)

        self.btn_luohan_run = ttk.Button(setting_frame, text="开始刷取", command=self._do_luohan_run, state="disabled")
        self.btn_luohan_run.grid(row=4, column=0, columnspan=2, pady=5)

        info_frame = ttk.LabelFrame(right_frame, text="说明", padding=10)
        info_frame.pack(fill="x")
        ttk.Label(info_frame, text=(
            "18罗汉共享3次\n可重复打同一罗汉\n例:3次全打降龙\n\n"
            "通关流程:\n1.create入口6001\n2.bossDead+finish\n"
            "3.create目标罗汉\n4.bossDead+finish\n5.syncDropInfoNew领奖\n\n"
            "掉落对应法印\n集齐3个进阶法宝"
        ), justify="left").pack()

        for mid, var in self.luohan_count_vars.items():
            var.trace_add("write", lambda *a, m=mid: self._on_luohan_count_change(m))

        return tab

    def _on_luohan_count_change(self, mid, *args):
        total = 0
        for m, var in self.luohan_count_vars.items():
            try:
                total += int(var.get())
            except:
                pass
        if total > 3:
            # 总和超限，把刚调整的这个弹回1格
            var = self.luohan_count_vars[mid]
            try:
                cur = int(var.get())
                var.set(max(0, cur - 1))
            except:
                pass
            return
        self._update_luohan_total()

    def _update_luohan_total(self):
        total = 0
        for mid, var in self.luohan_count_vars.items():
            try:
                total += int(var.get())
            except:
                pass
        color = "red" if total > 3 else "green"
        tip = " (超免费次数,将消耗点券)" if total > 3 else ""
        self.lbl_luohan_total.config(text="已设总次数: %d%s" % (total, tip), foreground=color)

    def _do_luohan_check(self):
        if not self._ensure_login():
            return
        self._log("[罗汉堂] 检测剩余次数...")
        threading.Thread(target=self._luohan_check_worker, daemon=True).start()

    def _luohan_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        try:
            flow, _, scene = self._connect_and_enter()
            cur = scene.get('curRecord', {})
            copy_history = cur.get('copyHistory', [])
            used_map = {}
            if isinstance(copy_history, list):
                for item in copy_history:
                    if isinstance(item, dict):
                        did = int(item.get('id', 0))
                        used_map[did] = int(item.get('num', 0))
            used = used_map.get(6001, 0)
            remain = max(0, 3 - used)
            self._count_after(_count_generation, 0, lambda: self.lbl_luohan_remain.config(text="剩余次数: %d (已用%d)" % (remain, used)))
            self._log("[罗汉堂] 入口6001已用%d次, 剩余%d次" % (used, remain))
            flow.disconnect()
            self._count_after(_count_generation, 0, lambda: self.btn_luohan_run.config(state="normal"))
        except Exception as e:
            self._log("[罗汉堂] 检测异常: %s" % e)
        finally:
            self._count_after(_count_generation, 0, lambda: self.btn_luohan_check.config(state="normal"))

    def _do_luohan_run(self):
        if not self._ensure_login():
            return
        tasks = []
        for mid, name, monster_ids in self.luohan_levels:
            cnt = int(self.luohan_count_vars[mid].get())
            if cnt > 0:
                tasks.append((mid, name, monster_ids, cnt))
        total = sum(c for _, _, _, c in tasks)
        if total == 0:
            messagebox.showwarning("提示", "请至少设置一个罗汉的挑战次数")
            return
        if total > 3:
            if not messagebox.askyesno("次数超限", "已设总次数%d次，超过每天3次免费。\n超出部分将消耗点券，是否继续？" % total):
                return
        delay = float(self.var_luohan_delay.get())
        self.btn_luohan_run.config(state="disabled")
        self._log("[罗汉堂] 开始刷取, 共%d次: %s" % (total, ", ".join(["%sx%d" % (n, c) for m, n, mi, c in tasks])))
        threading.Thread(target=self._luohan_run_worker, args=(tasks, delay), daemon=True).start()

    def _luohan_run_worker(self, tasks, delay):
        try:
            flow, _, scene = self._connect_and_enter()
            cur = scene.get('curRecord', {})
            p1 = cur.get('p1', {})
            exp = p1.get('experience', 0)
            property_p1_str = "%d;%d;%d;%d;%d;%d" % (
                p1.get('hpMax',0), p1.get('mpMax',0), p1.get('atk',0),
                p1.get('phyDef',0), p1.get('reHP',0), p1.get('reMP',0))
            self._log("[罗汉堂] 角色: %s Lv.%s" % (p1.get('kindName', '?'), p1.get('level', '?')))

            prop_map = {}
            try:
                config_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output_cg1_20260921_1_2")
                with open(os.path.join(config_dir, "150___Prop.xml.json"), encoding='utf-8') as f:
                    prop_data = json.load(f)
                records = prop_data.get('RECORD', prop_data if isinstance(prop_data, list) else [])
                if isinstance(records, dict): records = [records]
                for r in records:
                    if isinstance(r, dict): prop_map[str(r.get('id'))] = r.get('name', '?')
            except: pass

            drop_stats = {}
            success = 0
            fail = 0
            task_idx = 0
            for mid, name, monster_ids, count in tasks:
                for i in range(count):
                    task_idx += 1
                    self._log("[%d] %s(%d) 第%d/%d次" % (task_idx, name, mid, i+1, count))
                    try:
                        self._log("  [1/4] 打入口6001...")
                        enter_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": 6001, "costGem": 0}, timeout=15)
                        if enter_result.get("code") != 200:
                            self._log("  入口失败: %s" % enter_result.get("error", ""))
                            fail += 1
                            time.sleep(delay)
                            continue
                        time.sleep(1)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.5)
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": 6001}, timeout=15)
                        time.sleep(0.5)

                        self._log("  [2/4] create%s..." % name)
                        create_result = flow.request("scene.copyHandler.createSinglePlayerCopy", {"mid": mid, "costGem": 0}, timeout=15)
                        if create_result.get("code") != 200:
                            self._log("  关卡创建失败: %s" % create_result.get("error", ""))
                            fail += 1
                            time.sleep(delay)
                            continue
                        drops = create_result.get("drops", {})
                        copy_id = drops.get("copyId", 0)
                        new_drops = drops.get("newDrops", [])

                        self._log("  [3/4] bossDead+finish...")
                        time.sleep(1)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.5)
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=15)
                        time.sleep(0.5)

                        self._log("  [4/4] syncDropInfoNew领奖...")
                        pick_items = []
                        mob_ids = []
                        kill_monsters = []
                        total_exp = 0
                        total_sp = 0
                        for d in new_drops:
                            d_mid = d.get("monsterId", "0")
                            d_idx = d.get("index", 0)
                            total_exp += d.get("exp", 0)
                            total_sp += d.get("spirit", 0)
                            for _field, group in drop_groups(d):
                                mob_ids.append(d_mid)
                                kill_monsters.append("%s_%d" % (d_mid, d_idx))
                                for item_id, item_list in group.items():
                                    for item in item_list:
                                        pick_items.append(item)

                        sync_data = {
                            "copyId": copy_id, "pickItems": pick_items, "mobIds": mob_ids,
                            "killMonsters": kill_monsters, "completed": 1,
                            "currentEXP": exp, "pickExp": total_exp, "pickSp": total_sp,
                            "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                        }
                        sync_result = flow.request("scene.copyHandler.syncDropInfoNew", sync_data, timeout=15)
                        if sync_result.get("code") == 200:
                            success += 1
                            for d in new_drops:
                                for field, group in drop_groups(d):
                                    tag = {"item": "", "equip": "装备", "feather": "羽毛", "soul": "魂器"}.get(field, field)
                                    for item_id, item_list in group.items():
                                        cnt = len(item_list) if isinstance(item_list, list) else 1
                                        drop_stats[item_id] = drop_stats.get(item_id, 0) + cnt
                                        iname = prop_map.get(str(item_id), str(item_id))
                                        self._log("  获得%s: %s(%s) x%d" % (tag, iname, item_id, cnt))
                        else:
                            self._log("  sync失败: %s" % sync_result.get("error", ""))
                            fail += 1
                    except Exception as e:
                        self._log("  异常: %s" % e)
                        fail += 1
                    time.sleep(delay)

            self._log("[罗汉堂] 完成! 成功%d, 失败%d" % (success, fail))
            if drop_stats:
                self._log("[罗汉堂] 掉落汇总:")
                for item_id, cnt in drop_stats.items():
                    iname = prop_map.get(str(item_id), str(item_id))
                    self._log("  %s(%s): %d个" % (iname, item_id, cnt))
            flow.disconnect()
        except Exception as e:
            self._log("[罗汉堂] 运行异常: %s" % e)
        finally:
            self.root.after(0, lambda: self.btn_luohan_run.config(state="normal"))



    # ========== 地藏 / 虚空藏标签页 ==========
    def _build_special_dungeon_tab(self):
        tab = self._daily2_page("地藏/虚空藏", padding=10)

        ttk.Label(
            tab,
            text="五种地藏共享每日3次；虚空藏院单独每日3次。领奖消耗次数，不购买次数，不花点券。",
            foreground="red", wraplength=780, justify="left"
        ).pack(anchor="w", pady=(0, 8))

        self.special_groups = {}
        self.special_run_buttons = []
        for group, title, options in (
            ("dizang", "地藏冥府", [i for i in SPECIAL_DUNGEONS if i["id"] < 6026]),
            ("xukong", "虚空藏院", [i for i in SPECIAL_DUNGEONS if i["id"] == 6026]),
        ):
            panel = ttk.LabelFrame(tab, text=title, padding=10)
            panel.pack(fill="x", pady=6)
            ttk.Label(panel, text="选择BOSS：").grid(row=0, column=0, sticky="w")
            boss_var = tk.StringVar(value=options[0]["boss"])
            choice = ttk.Combobox(panel, textvariable=boss_var, values=[i["boss"] for i in options],
                                  state="readonly", width=18)
            choice.grid(row=0, column=1, padx=6, sticky="w")
            ttk.Label(panel, text="次数：").grid(row=0, column=2, sticky="w")
            count_var = tk.StringVar(value="1")
            ttk.Combobox(panel, textvariable=count_var, values=("1", "2", "3"),
                         state="readonly", width=5).grid(row=0, column=3, padx=6)
            reward = ttk.Label(panel, text="奖励：" + options[0]["item_name"])
            reward.grid(row=1, column=0, columnspan=2, sticky="w", pady=6)
            remaining = ttk.Label(panel, text="剩余次数：待检测", foreground="gray")
            remaining.grid(row=1, column=2, columnspan=2, sticky="w")
            button = ttk.Button(panel, text="执行所选BOSS", state="disabled",
                                command=lambda g=group: self._do_special_run(g))
            button.grid(row=0, column=4, padx=8)
            self.special_run_buttons.append(button)
            self.special_groups[group] = {"options": options, "boss_var": boss_var,
                                          "count_var": count_var, "remaining": remaining}
            def update_reward(event, items=options, var=boss_var, label=reward):
                info = next(i for i in items if i["boss"] == var.get())
                label.config(text="奖励：" + info["item_name"])
            choice.bind("<<ComboboxSelected>>", update_reward)
        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=5)
        self.btn_special_check = ttk.Button(controls, text="检测剩余次数", command=self._do_special_check)
        self.btn_special_check.pack(side="left")
        # 一键运行按单按钮等待结束，这里引用第一个执行按钮（无事用时两个按钮同步状态）。
        self.btn_special_run = self.special_run_buttons[0]

        info_frame = ttk.LabelFrame(tab, text="说明", padding=8)
        info_frame.pack(fill="x", pady=5)
        ttk.Label(
            info_frame,
            text=("流程：创建副本 → bossDead/结算 → 同步掉落 → getSpecialDrop领奖\n"
                  "此页调用通关结算协议，不执行客户端实时战斗。物品数量在领奖回包后显示；领奖前没有数量预览。"),
            justify="left", wraplength=780
        ).pack(anchor="w")
        return tab

    @staticmethod
    def _special_copy_usage(scene):
        history = scene.get("curRecord", {}).get("copyHistory", [])
        if isinstance(history, dict):
            history = list(history.values())
        used_map = {}
        if isinstance(history, list):
            for item in history:
                if isinstance(item, dict):
                    try:
                        used_map[int(item.get("id", 0))] = int(item.get("num", 0))
                    except (TypeError, ValueError):
                        continue
        return used_map

    @staticmethod
    def _special_item_count(scene, item_id):
        bag = scene.get("curRecord", {}).get("itemsBag", {})
        items = bag.get("items", {}) if isinstance(bag, dict) else bag
        if isinstance(items, list):
            total = 0
            for item in items:
                if not isinstance(item, dict):
                    continue
                found_id = item.get("id", item.get("itemId", ""))
                if str(found_id) == str(item_id):
                    try:
                        total += int(item.get("count", item.get("num", 1)) or 0)
                    except (TypeError, ValueError):
                        total += 1
            return total
        value = items.get(str(item_id), items.get(item_id, 0)) if isinstance(items, dict) else 0
        if isinstance(value, dict):
            return int(value.get("count", value.get("num", 0)) or 0)
        if isinstance(value, list):
            return sum(int(v.get("count", 1) or 0) if isinstance(v, dict) else 1 for v in value)
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _set_special_run_state(self, state):
        for button in self.special_run_buttons:
            button.config(state=state)

    def _update_special_remaining(self, used_map):
        for group in self.special_groups.values():
            info = group["options"][0]
            used = sum(used_map.get(mid, 0) for mid in info["shared_ids"])
            remain = max(0, info["daily_max"] - used)
            self.root.after(0, lambda label=group["remaining"], u=used, r=remain: label.config(
                text="剩余%d/3次（已用%d）" % (r, u), foreground="green" if r else "red"))

    def _do_special_check(self):
        if not self._ensure_login():
            return
        self.btn_special_check.config(state="disabled")
        self._log("[地藏/虚空藏] 只读取存档挑战次数...")
        threading.Thread(target=self._special_check_worker, daemon=True).start()

    def _special_check_worker(self):
        _count_generation = getattr(self, "_count_generation", 0)
        flow = None
        try:
            flow, _, scene = self._connect_and_enter()
            used_map = self._special_copy_usage(scene)
            if _count_generation != getattr(self, '_count_generation', 0):
                return
            self._update_special_remaining(used_map)
            for info in SPECIAL_DUNGEONS:
                used = sum(used_map.get(mid, 0) for mid in info["shared_ids"])
                remain = max(0, info["daily_max"] - used)
                self._log("[地藏/虚空藏] %s：已用%d/%d，剩余%d次" % (
                    info["name"], used, info["daily_max"], remain
                ))
            self._count_after(_count_generation, 0, lambda: self._set_special_run_state("normal"))
        except Exception as e:
            self._log("[地藏/虚空藏] 次数读取失败：%s" % e)
        finally:
            if flow:
                try:
                    flow.disconnect()
                except Exception:
                    pass
            self._count_after(_count_generation, 0, lambda: self.btn_special_check.config(state="normal"))

    def _do_special_run(self, group_name=None):
        if not self._ensure_login():
            return
        tasks = []
        groups = [self.special_groups[group_name]] if group_name else self.special_groups.values()
        for group in groups:
            info = next(i for i in group["options"] if i["boss"] == group["boss_var"].get())
            try:
                count = int(group["count_var"].get())
                if count not in (1, 2, 3):
                    raise ValueError
            except ValueError:
                messagebox.showwarning("次数不正确", "挑战次数请选择1～3。")
                return
            tasks.append((info, count))

        detail = "\n".join("%s（%s）：%d次" % (info["name"], info["boss"], count) for info, count in tasks)
        if not messagebox.askyesno(
            "确认消耗挑战次数",
            "将按以下次数实际创建副本并领奖：\n%s\n\n配置中的点券消耗为0；领奖会消耗挑战次数。继续吗？" % detail
        ):
            return

        self._set_special_run_state("disabled")
        self.btn_special_check.config(state="disabled")
        threading.Thread(target=self._special_run_worker, args=(tasks,), daemon=True).start()

    def _special_run_worker(self, tasks):
        flow = None
        verify_flow = None
        try:
            flow, entry, scene = self._connect_and_enter()
            cur = scene.get("curRecord", {})
            p1 = entry.get("record", {}).get("p1", cur.get("p1", {}))
            exp = int(p1.get("experience", 0) or 0)
            property_p1_str = ";".join(str(p1.get(key, 0)) for key in
                                       ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP"))
            initial_points = {key: scene["user"].get(key) for key in ("gem", "usedGem")}
            used_map = self._special_copy_usage(scene)
            for info, count in tasks:
                remain = max(0, info["daily_max"] - sum(used_map.get(mid, 0) for mid in info["shared_ids"]))
                requested_group = sum(n for candidate, n in tasks if candidate["shared_ids"] == info["shared_ids"])
                if requested_group > remain:
                    self._update_special_remaining(used_map)
                    self._log("[地藏/虚空藏] 已中止：%s只剩%d次，本次要求%d次；没有创建副本。" % (
                        info["name"], remain, requested_group
                    ))
                    return

            item_before = {info["id"]: self._special_item_count(scene, info["item_id"]) for info, _ in tasks}
            expected_items = {info["id"]: 0 for info, _ in tasks}
            results = []
            total = sum(count for _, count in tasks)
            self._log("[地藏/虚空藏] 开始协议流程验证，共%d次；创建参数costGem=0。" % total)
            for info, count in tasks:
                for index in range(count):
                    self._log("[%s] 第%d/%d次：创建副本..." % (info["name"], index + 1, count))
                    try:
                        create_result = flow.request(
                            "scene.copyHandler.createSinglePlayerCopy",
                            {"mid": info["id"], "costGem": 0}, timeout=15
                        )
                        if create_result.get("code") != 200:
                            self._log("  创建失败：%s" % create_result.get("error", create_result))
                            results.append((info, False))
                            continue

                        time.sleep(0.5)
                        flow.request("scene.copyHandler.bossDead", None, timeout=10)
                        time.sleep(0.3)
                        flow.request("scene.copyHandler.finishDungeon", {"dungeonId": info["id"]}, timeout=15)
                        time.sleep(0.3)

                        drops = create_result.get("drops", {})
                        sync_data = {
                            "copyId": drops.get("copyId", 0), "pickItems": [], "mobIds": [],
                            "killMonsters": [], "currentEXP": exp, "pickExp": 0, "pickSp": 0,
                            "propertyP1Str": property_p1_str, "propertyP2Total": 0, "hitCombo": 100,
                        }
                        sync_result = flow.request(
                            "scene.copyHandler.syncDropInfoNew", sync_data, timeout=15
                        )
                        if sync_result.get("code") not in (None, 200):
                            self._log("  同步结算失败；不重试领奖，以免重复消耗：%s" % sync_result.get("error", sync_result))
                            results.append((info, False))
                            continue

                        reward = flow.request("scene.copyHandler.getSpecialDrop", {
                            "id": info["id"], "kills": info["kills"]
                        }, timeout=15)
                        if reward.get("code") != 200:
                            self._log("  领奖失败/状态待核实（不自动重试）：%s" % reward.get("error", reward))
                            results.append((info, False))
                            continue

                        items = reward.get("add", {}).get("items", [])
                        for item in items if isinstance(items, list) else []:
                            item_id = str(item.get("id", ""))
                            item_count = int(item.get("count", 0) or 0)
                            if item_id == info["item_id"]:
                                expected_items[info["id"]] += item_count
                                self._log("  领奖回包：%s x%d" % (info["item_name"], item_count))
                            elif item_count:
                                self._log("  领奖回包：物品%s x%d" % (item_id, item_count))
                        if not items:
                            self._log("  领奖回包成功，但没有物品明细。")
                        results.append((info, True))
                    except Exception as e:
                        self._log("  流程中断，服务器是否已记次数需重新读取：%s" % e)
                        results.append((info, False))

            # 断开旧会话后重新登录；同一会话的curRecord可能仍是领奖前缓存。
            if flow:
                try:
                    flow.disconnect()
                finally:
                    flow = None
            # 领奖回包之外，再读新会话的服务器存档，核对背包与次数变化。
            verify_flow, _, verify_scene = self._connect_and_enter()
            if any(initial_points[key] != verify_scene["user"].get(key) for key in initial_points):
                raise RuntimeError("点券或累计消费发生变化，请核查")
            self._log("[地藏/虚空藏] 重登确认点券及累计消费未变")
            verify_used = self._special_copy_usage(verify_scene)
            self._update_special_remaining(verify_used)
            for info, _ in tasks:
                before = item_before.get(info["id"], 0)
                after = self._special_item_count(verify_scene, info["item_id"])
                actual_delta = after - before
                expected_delta = expected_items.get(info["id"], 0)
                self._log("[核验] %s背包数量：%d → %d（变化 %+d；领奖回包 %+d）" % (
                    info["item_name"], before, after, actual_delta, expected_delta
                ))
                if actual_delta != expected_delta:
                    self._log("[核验差异] %s背包变化与领奖回包不一致；不能确认本次奖励已入包。" % info["item_name"])
                requested = sum(count for task_info, count in tasks if task_info["shared_ids"] == info["shared_ids"])
                used_before = sum(used_map.get(mid, 0) for mid in info["shared_ids"])
                used_after = sum(verify_used.get(mid, 0) for mid in info["shared_ids"])
                if used_after - used_before != requested:
                    self._log("[核验差异] %s挑战次数变化%d次，设置为%d次。" % (
                        info["name"], used_after - used_before, requested
                    ))
                self._log("[核验] %s挑战记录：已用%d/%d，剩余%d次。" % (
                    info["name"], used_after, info["daily_max"],
                    max(0, info["daily_max"] - used_after)
                ))
            succeeded = sum(1 for _, ok in results if ok)
            self._log("[地藏/虚空藏] 流程结束：领奖回包成功%d次，失败或待核实%d次。" % (
                succeeded, len(results) - succeeded
            ))
        except Exception as e:
            self._log("[地藏/虚空藏] 验证异常：%s" % e)
        finally:
            for active_flow in (flow, verify_flow):
                if active_flow:
                    try:
                        active_flow.disconnect()
                    except Exception:
                        pass
            self.root.after(0, lambda: self._set_special_run_state("normal"))
            self.root.after(0, lambda: self.btn_special_check.config(state="normal"))


    # ========== 已实测的周本 ==========
    def _build_weekly_dungeon_tab(self):
        group = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(group, text="周本")
        self.weekly_notebook = ttk.Notebook(group)
        self.weekly_notebook.pack(fill="both", expand=True)

        def page(title):
            outer = ttk.Frame(self.weekly_notebook)
            self.weekly_notebook.add(outer, text=title)
            outer.rowconfigure(0, weight=1)
            outer.columnconfigure(0, weight=1)
            canvas = tk.Canvas(outer, highlightthickness=0)
            scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            content = ttk.Frame(canvas, padding=10)
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
            def wheel(event):
                widget = event.widget
                while widget is not None and widget != outer:
                    widget = getattr(widget, "master", None)
                if widget == outer and event.delta:
                    canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
                    return "break"
            self.root.bind("<MouseWheel>", wheel, add="+")
            return content

        self.weekly_buttons = {}
        for key, name, route, limit in (
            ("city", "守卫须弥山城西", "2126 前置关 → 2127 隐藏关", "每周1次"),
            ("bliss", "极乐试炼", "2173 → 宝箱领奖", "每周5次"),
        ):
            tab = page(name)
            ttk.Label(tab, text="%s；免费领奖配置：%s" % (route, limit), wraplength=650).pack(anchor="w", pady=10)
            button = ttk.Button(tab, text="挑战并领奖一次", command=lambda k=key: self._do_weekly_dungeon(k))
            button.pack(anchor="w", pady=5)
            self.weekly_buttons[key] = button
            if key == "bliss":
                button = ttk.Button(tab, text="连续挑战并领奖5次", command=lambda: self._do_weekly_dungeon("bliss", 5))
                button.pack(anchor="w", pady=5)
                self.weekly_buttons["bliss5"] = button
                ttk.Label(tab, text="最多执行5次，每次重新登录并核对奖励；服务器拒绝挑战或领奖时立即停止，不购买次数。", wraplength=650).pack(anchor="w", pady=8)
        from youye_weekly import build_panel
        build_panel(self, page("幽夜泽"))
        from league_boss import build_panel as build_league_panel
        build_league_panel(self, page("联盟BOSS梼杌"))
        from sailing_weekly import build_panel as build_sailing_panel
        build_sailing_panel(self, page("航海寻宝"))
        self._build_shenyu_panel(page("神域悬赏"))

    def _build_moyuan_tab(self):
        group = ttk.Frame(self.notebook, padding=10)
        self.notebook.add(group, text="魔渊诛邪")
        pages = ttk.Notebook(group)
        pages.pack(fill="both", expand=True)

        def page(title):
            outer = ttk.Frame(pages)
            pages.add(outer, text=title)
            outer.rowconfigure(0, weight=1)
            outer.columnconfigure(0, weight=1)
            canvas = tk.Canvas(outer, highlightthickness=0)
            scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=scroll.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            scroll.grid(row=0, column=1, sticky="ns")
            content = ttk.Frame(canvas, padding=10)
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))

            def wheel(event):
                widget = event.widget
                while widget is not None and widget != outer:
                    widget = getattr(widget, "master", None)
                if widget == outer and event.delta:
                    canvas.yview_scroll(-int(event.delta / 120) or (-1 if event.delta > 0 else 1), "units")
                    return "break"

            self.root.bind("<MouseWheel>", wheel, add="+")
            return content

        from moyuan_attachment_ui import build_panel as build_moyuan_attachment
        build_moyuan_attachment(self, page("第九层·研究室附件"))

    def _do_weekly_dungeon(self, key, times=1):
        if not self._ensure_login():
            return
        name = "守卫须弥山城西" if key == "city" else "极乐试炼"
        if not messagebox.askyesno("确认挑战", "将实际挑战%s并领取免费宝箱奖励，最多%d次，继续吗？" % (name, times)):
            return
        for button in self.weekly_buttons.values():
            button.config(state="disabled")
        save_index = self.current_save["index"]
        threading.Thread(target=self._weekly_dungeon_worker, args=(key, times, save_index), daemon=True).start()

    def _weekly_dungeon_worker(self, key, times=1, save_index=None):
        try:
            for index in range(times):
                self._log("[周本] 第%d/%d次" % (index + 1, times))
                self._weekly_dungeon_once(key, save_index)
                if index + 1 < times:
                    time.sleep(2)
        except Exception as error:
            self._log("[周本] 已停止后续挑战：%s" % error)
        finally:
            def enable():
                for button in self.weekly_buttons.values():
                    button.config(state="normal")
            self.root.after(0, enable)

    def _weekly_dungeon_once(self, key, save_index=None):
        name = "守卫须弥山城西" if key == "city" else "极乐试炼"
        stages = ((2126, 16777217), (2127, 1)) if key == "city" else ((2173, 16777217),)
        reward_id = 2127 if key == "city" else 2173
        reward_items = (105300014, 105600001, 197400003) if key == "city" else (143200019, 197200053)
        flow = None
        verify_flow = None
        try:
            flow, _, scene = self._connect_and_enter(save_index)
            initial_points = {key: scene["user"].get(key) for key in ("gem", "usedGem")}
            p1 = scene["curRecord"]["p1"]
            prop = ";".join(str(p1[k]) for k in ("hpMax", "mpMax", "atk", "phyDef", "reHP", "reMP"))
            expected = {}
            for item_id in reward_items:
                expected[str(item_id)] = self._special_item_count(scene, item_id)
            initial_gem = None
            self._log("[%s] 开始免费挑战，创建参数 costGem=0。" % name)
            for mid, completed in stages:
                created = flow.request("scene.copyHandler.createSinglePlayerCopy",
                                       {"mid": mid, "costGem": 0}, timeout=20)
                if created.get("code") != 200:
                    raise RuntimeError("关卡%d创建失败：%s" % (mid, created.get("error", created)))
                if initial_gem is None:
                    initial_gem = created.get("gem")
                elif initial_gem is not None and created.get("gem") != initial_gem:
                    raise RuntimeError("关卡创建后点券余额发生变化，已停止后续操作")
                drops = created.get("drops") or {}
                copy_id = drops.get("copyId")
                if not copy_id:
                    raise RuntimeError("关卡%d未返回copyId" % mid)
                pickup = []
                exp = spirit = 0
                for drop in drops.get("newDrops") or []:
                    mob = str(drop.get("monsterId", ""))
                    index = drop.get("index", 0)
                    exp += int(drop.get("exp", 0) or 0)
                    spirit += int(drop.get("spirit", 0) or 0)
                    for kind in ("item", "equip"):
                        for item_id, ids in (drop.get(kind) or {}).items():
                            for pick_id in (ids if isinstance(ids, list) else [ids]):
                                pickup.append((str(item_id), str(pick_id), mob, index))
                dead = flow.request("scene.copyHandler.bossDead", None, timeout=15)
                finished = flow.request("scene.copyHandler.finishDungeon", {"dungeonId": mid}, timeout=20)
                if dead.get("code") != 200 or finished.get("code") != 200:
                    raise RuntimeError("关卡%d通关失败：%s / %s" % (mid, dead.get("error"), finished.get("error")))
                for offset in range(0, len(pickup), 4):
                    batch = pickup[offset:offset + 4]
                    result = self._weekly_sync_drop(flow, copy_id, batch, 0, p1, prop,
                                                    exp if offset == 0 else 0,
                                                    spirit if offset == 0 else 0)
                    if result.get("code") != 200:
                        raise RuntimeError("关卡%d拾取失败：%s" % (mid, result.get("error", result)))
                result = self._weekly_sync_drop(flow, copy_id, [], completed, p1, prop,
                                                exp if not pickup else 0,
                                                spirit if not pickup else 0)
                if result.get("code") != 200:
                    raise RuntimeError("关卡%d结算失败：%s" % (mid, result.get("error", result)))
                self._log("[%s] 关卡%d通关结算成功。" % (name, mid))
            reward = flow.request("scene.copyHandler.getDungeonTreasure", {"id": reward_id}, timeout=20)
            if reward.get("code") != 200:
                raise RuntimeError("宝箱领取失败：%s" % reward.get("error", reward))
            self._log("[%s] 宝箱领取成功；重新登录核对背包。" % name)
            flow.disconnect()
            flow = None
            verify_flow, _, after = self._connect_and_enter(save_index)
            if any(initial_points[key] != after["user"].get(key) for key in initial_points):
                raise RuntimeError("点券或累计消费发生变化，停止后续挑战")
            for item_id in reward_items:
                before_count = expected[str(item_id)]
                after_count = self._special_item_count(after, item_id)
                self._log("[%s] 物品%d：%d → %d，增加%d。" %
                          (name, item_id, before_count, after_count, after_count - before_count))
        except Exception as e:
            self._log("[%s] 已停止：%s" % (name, e))
            raise
        finally:
            for connection in (flow, verify_flow):
                if connection is not None:
                    try:
                        connection.disconnect()
                    except Exception:
                        pass

    @staticmethod
    def _weekly_sync_drop(flow, copy_id, group, completed, p1, prop, exp, spirit):
        payload = {
            "copyId": copy_id,
            "pickItems": [item[1] for item in group],
            "mobIds": [item[2] for item in group],
            "killMonsters": [marker for item in group for marker in
                             ("%s_%s" % (item[2], item[3]), "%s_%s" % (item[2], item[3]))],
            "completed": completed, "currentEXP": p1["experience"],
            "pickExp": exp, "pickSp": spirit, "propertyP1Str": prop,
            "propertyP2Total": 0, "hitCombo": 100,
        }
        return flow.request("scene.copyHandler.syncDropInfoNew", payload, timeout=20)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        # Windows原生主题以对勾表示选中，避免clam主题显示叉号。
        available = style.theme_names()
        if "vista" in available:
            style.theme_use("vista")
        elif "xpnative" in available:
            style.theme_use("xpnative")
    except:
        pass
    app = ToolBoxApp(root)
    def report_error(kind, value, tb):
        import traceback
        text = ''.join(traceback.format_exception(kind, value, tb))
        log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else BASE_DIR
        try:
            with open(os.path.join(log_dir, 'toolbox_errors.log'), 'a', encoding='utf-8') as error_file:
                error_file.write('\n'+datetime.now().isoformat()+'\n'+text)
        except OSError:
            pass
        app._log('[程序异常] '+str(value)+'；详细信息见 toolbox_errors.log')
    root.report_callback_exception = report_error
    threading.excepthook = lambda args: report_error(args.exc_type, args.exc_value, args.exc_traceback)
    app.root.after(30_000, app._schedule_check)
    if "--schedule-run" in sys.argv:
        app.root.after(800, app._start_scheduled_task_run)
    if len(sys.argv) == 3 and sys.argv[1] == "--jiuzhuan-rl-check":
        # 九转 RL 策略离线检查：加载 torch 与模型权重后退出，不连接游戏。
        check_path = os.path.abspath(sys.argv[2])
        def finish_rl_check():
            report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
            try:
                from jiuzhuan_rl import warmup, _MODEL_DIR
                info = warmup()
                import torch
                report.update({"ok": True, "torch": torch.__version__,
                               "model_dir": str(_MODEL_DIR),
                               "info": info})
            except Exception as exc:
                report["error"] = str(exc)
            with open(check_path, "w", encoding="utf-8") as check_file:
                json.dump(report, check_file, ensure_ascii=False, indent=2)
            root.destroy()
        root.after(500, finish_rl_check)
    if len(sys.argv) == 3 and sys.argv[1] == "--startup-check":
        # 离线启动检查：实际创建所有页面后自动退出，不登录游戏。
        check_path = os.path.abspath(sys.argv[2])
        callback_errors = []
        root.report_callback_exception = lambda kind, value, tb: callback_errors.append(str(value))
        def finish_startup_check():
            mainfarm_check = {}
            try:
                from mainfarm_routes import dungeon_rows, hidden_choices, clear_stage
                mainfarm_check = {'module_loaded': callable(clear_stage),
                                  'dungeon_count': len(dungeon_rows()),
                                  'fulong_config': 64 in dungeon_rows(),
                                  'hidden_config_count': len(hidden_choices(51))}
                for index in range(app.main_listbox.size()):
                    app.main_listbox.selection_clear(0, tk.END)
                    app.main_listbox.selection_set(index)
                    app._update_main_hidden_choices()
                mainfarm_check['all_selections_ok'] = True
                mapped = app._mainline_history({'curRecord': {'copyHistory': [
                    {'id': 1001, 'num': 1}, {'id': 1033, 'num': 1}]}})
                mainfarm_check['boss_history_maps_to_normal'] = {9, 52}.issubset(mapped)
                if not mainfarm_check['boss_history_maps_to_normal']:
                    raise RuntimeError('Boss通关记录映射失败')
            except Exception as exc:
                callback_errors.append('主线自检：'+str(exc))
            report = {"ok": not callback_errors, "frozen": bool(getattr(sys, "frozen", False)),
                      "tabs": [app.notebook.tab(t, "text") for t in app.notebook.tabs()],
                      "wash_pages": len(app.wash_pages), "solver_loaded": Solver is not None,
                      "config_loaded": os.path.isdir(CONFIG_DIR), "errors": callback_errors,
                      "mainfarm_check": mainfarm_check}
            with open(check_path, "w", encoding="utf-8") as check_file:
                json.dump(report, check_file, ensure_ascii=False, indent=2)
            root.destroy()
        root.after(1500, finish_startup_check)
    root.mainloop()



if __name__ == "__main__":
    main()
