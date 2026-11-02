"""Read-only retrospective. This module performs no account or network operations."""
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk, scrolledtext


def show_script_index(app):
    """Locate historical experiments without importing or executing them."""
    root = Path(__file__).resolve().parent / "group_sign_review"
    entries = (
        ("probe_gamebox_sign.py", "早期实验：误用论坛Cookie作为scookie；不是可用登录方案。"),
        ("runtime_debug/probe_real_credential.py", "读取真实App桥接凭证，查询奖励袋。"),
        ("runtime_debug/probe_real_device.py", "增加真实设备参数、UA和活动初始化；只读查询曾成功。"),
        ("runtime_debug/test_free_sign_real.py", "实际提交过免费签到，被服务器活动限制拒绝。"),
        ("runtime_debug/probe_xiyang_readonly.py", "另一测试账号的只读实验。"),
        ("runtime_debug/test_xiyang_free_sign.py", "另一测试账号的签到实验，同样被活动限制拒绝。"),
    )
    window = tk.Toplevel(app.root)
    window.title("游戏盒签到 · 历史Python发包文件")
    window.geometry("920x560")
    ttk.Label(window, text="历史实验文件索引：没有成功签到记录。此窗口不执行脚本，也不读取登录凭证。",
              wraplength=850).pack(anchor="w", padx=12, pady=12)
    text = scrolledtext.ScrolledText(window, wrap="word", padx=10, pady=10)
    text.pack(fill="both", expand=True, padx=12)
    for relative, description in entries:
        path = root / relative
        text.insert("end", f"{'找到' if path.is_file() else '当前副本缺失'}：{relative}\n{description}\n位置：{path}\n\n")
    text.configure(state="disabled")
    status = ttk.Label(window, text="源码位于研究目录；发布副本可能没有附带实验文件。", wraplength=850)
    status.pack(anchor="w", padx=12, pady=8)

    def open_directory():
        if root.is_dir():
            os.startfile(str(root))
        else:
            status.configure(text="当前副本没有group_sign_review目录，请在原始源码目录查看。")

    ttk.Button(window, text="打开实验文件目录", command=open_directory).pack(pady=(0, 12))


FLOW = """游戏盒签到实验复盘（2026-10-20）

一、错误流程
1. 早期将网页Cookie键值串当作活动scookie，未核对游戏盒桥接格式。
2. 后来读取到真实App凭证、设备信息，并完成奖励袋只读查询。
3. 将只读接口key=200作为继续提交签到的条件，没有验证活动资格。
4. 测试账号A签到被明确拒绝后，又更换测试账号B提交；未及时停止，是判断失误。
5. 没有得到签到成功或天数增加的证据，不应将鉴权成功描述成签到功能成功。

二、相关代码（摘录说明，不可执行）
此前测试脚本的错误控制逻辑：

    if bag_response.get("key") == 200:
        # 随后直接提交签到 —— 此条件不足以证明具备签到资格。

App侧只读代码证据：
    onLoadCookieForJs()       提供活动页登录凭证
    getUniqueId()             提供App设备标识
    checkClient()             网页客户端环境判断
    checkEmulator()           按活动配置调用App环境检查
    onCheckEmulator()         App模拟器/分身检查

历史源码索引（实验材料，不作为可执行功能）：
    本地实验脚本（账号相关文件名已隐去）
    group_sign_review/Gamebox92AndroidBridge.java
    group_sign_review/Gamebox92LoginBridge.java
    group_sign_review/gamebox_mpage.js

三、账号受限结果（用户反馈“封号”）
测试账号A、测试账号B：只读查询成功；各自实际提交免费签到后，均收到活动限制提示。
用户随后提供了手机App同类提示及官方客服回复截图。
现有证据确认活动操作受限，不能据此确认整个游戏账号被封。
不能确认限制建立时间、具体触发条件、期限或解除结果。

四、官方回复要点
官方将手机刷设备、篡改设备、虚拟设备等列入违规行为，建议通过App中的
“立即反馈”提交复查，表示会在三个工作日内复查并通过游戏盒消息通知。
这不是保证三个工作日内解除限制。

五、当前状态
独立签到没有成功。本窗口只展示复盘，无登录、凭证提取、签到、领奖或重试功能。
本窗口不展示账号ID、昵称、密码、Cookie、token、authCode及完整设备标识。
"""

MESSAGES = """历史发送与返回消息（脱敏摘要，不是完整抓包）

【早期错误请求】
scookie使用了网页Cookie键值列表，和App实际桥接格式不一致。
返回曾出现key=1000及“未能识别到您的用户信息，请更换手机再尝试”。

【取得真实凭证，但未使用完整设备参数时】
POST https://huodong2.4399.com/comm/qdlb/ajax_v4.php
操作：ac=bag（奖励袋只读查询）
HTTP 200
{"key": 100, "msg": "你好，未能识别到您的用户信息，请更换手机再尝试"}

【补充App真实设备信息后的初始化】
GET https://huodong2.4399.com/comm/qdlb/share2.php
请求包含活动、客户端版本、App凭证及设备信息。
HTTP 200；当次解析到st、sn均为空；未收到会话Cookie。
此结果不证明已经完成正常活动页的全部初始化。

【测试账号A、测试账号B的只读请求】
POST https://huodong2.4399.com/comm/qdlb/ajax_v4.php
发送字段摘要：
  ac=bag, hdid=5, client_version=9.2.0.47
  scookie=[已脱敏], device=[已脱敏], rand=[随机值], st="", sn=""
请求头摘要：App提供的UA、活动页Referer、X-Requested-With。
HTTP 200；业务返回：
{"key": 200, "list": "[列表内容略]", "pre_list": "[列表内容略]"}
注意：list/pre_list的实际类型是列表；此处字符串仅是展示用占位。

【测试账号A、测试账号B的免费签到请求】
同一官方接口，操作改为ac=sign，其余使用当次真实App信息。
HTTP 200；两个账号均返回：
{
  "key": "custom_common_msg",
  "msg": "由于您涉嫌违规参与活动，暂时无法进行该操作，如有疑问请直接带问题截图联系客服（QQ：4006334399），添加时请备注问题。"
}

本轮请求没有成功签到，没有执行补签、加速、兑换或领取奖励。
以上仅保留必要字段与已有返回文字；没有完整原始报文，不应据此推断全部风控条件。
"""


def show_review(app):
    previous = getattr(app, "_gamebox_review_window", None)
    if previous is not None and previous.winfo_exists():
        previous.deiconify()
        previous.lift()
        previous.focus_set()
        return
    window = tk.Toplevel(app.root)
    app._gamebox_review_window = window
    window.title("游戏盒签到 · 测试复盘与发送返回消息")
    window.geometry("920x720")
    window.minsize(620, 420)
    notebook = ttk.Notebook(window)
    notebook.pack(fill="both", expand=True, padx=10, pady=10)
    for title, content in (("错误流程与代码", FLOW), ("发送与返回消息", MESSAGES)):
        page = ttk.Frame(notebook)
        notebook.add(page, text=title)
        text = scrolledtext.ScrolledText(page, wrap="word", font=("Microsoft YaHei", 10),
                                        padx=12, pady=12)
        text.pack(fill="both", expand=True)
        text.insert("1.0", content)
        text.configure(state="disabled")
    page = ttk.Frame(notebook, padding=10)
    notebook.add(page, text="游戏盒截图")
    ttk.Label(page, text="用户提供的活动受限提示；下方聚焦原图弹窗区域，未改写文字。",
              wraplength=700).pack(anchor="w", pady=(0, 8))
    viewport = ttk.Frame(page)
    viewport.pack(fill="both", expand=True)
    viewport.rowconfigure(0, weight=1)
    viewport.columnconfigure(0, weight=1)
    canvas = tk.Canvas(viewport, highlightthickness=0, background="#252525")
    vertical = ttk.Scrollbar(viewport, orient="vertical", command=canvas.yview)
    horizontal = ttk.Scrollbar(viewport, orient="horizontal", command=canvas.xview)
    canvas.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    canvas.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    try:
        from PIL import Image, ImageTk
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "assets", "gamebox_activity_restricted.jpg")
        with Image.open(path) as original:
            photo = ImageTk.PhotoImage(original, master=window)
        # Clip by the canvas viewport; retain the original evidence image unchanged.
        canvas.create_image(-45, -620, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, 770, 565))
        window._gamebox_evidence_photo = photo
    except Exception:
        canvas.create_text(15, 15, anchor="nw", width=540,
                           text="截图暂无法显示。请确认assets中的原图存在，并已安装Pillow。",
                           fill="white")
        canvas.configure(scrollregion=(0, 0, 580, 100))
    ttk.Button(window, text="关闭", command=window.destroy).pack(pady=(0, 10))
