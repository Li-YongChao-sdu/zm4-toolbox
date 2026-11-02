"""Open the separately distributed Moyuan research attachment."""
from pathlib import Path
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox


def attachment_directory():
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
    return base / "独立附件" / "魔渊回放研究室_附件"


def build_panel(app, parent):
    folder = attachment_directory()
    ttk.Label(parent, text="魔渊第九层录像研究室 · 独立附件", font=("Microsoft YaHei", 12, "bold")).pack(anchor="w", pady=(8, 12))
    ttk.Label(parent, text="读取榜单录像 → 导出自身快照 → 网页匹配与本地验证 → 导出实战操作 → 游戏内挑战。\n"
              "附件独立运行；使用本期 v5870 主文件，通过 Fiddler 替换加载。工具箱登录不会自动传入附件。",
              wraplength=650, justify="left").pack(anchor="w", pady=8)

    def open_item(relative=None):
        target = folder / relative if relative else folder
        if not target.exists():
            messagebox.showerror("附件未找到", "请将完整附件目录放在工具箱旁：\n%s\n\n缺少：%s" % (folder, target), parent=app.root)
            return
        try:
            os.startfile(str(target))
        except OSError as error:
            messagebox.showerror("打开附件失败", str(error), parent=app.root)

    actions = ttk.Frame(parent)
    actions.pack(fill="x", pady=10)
    for column, (title, relative) in enumerate((("打开研究室网页", "研究室.html"), ("查看完整流程", "开始前必读.md"), ("打开附件文件夹", None))):
        ttk.Button(actions, text=title, command=lambda name=relative: open_item(name)).grid(row=column // 2, column=column % 2, sticky="w", padx=(0, 12), pady=5)
    ttk.Label(parent, text="游戏内使用“导入回放/实战JSON”。实战持续预备与自动重试需手动开启；成功自动停止，F9急停。\n"
              "同分可能不替换服务器录像，需自行保留本次录制。其他配置仍需分别验证。",
              wraplength=650, justify="left").pack(anchor="w", pady=8)
    ttk.Label(parent, text="附件位置（可选中复制）：").pack(anchor="w", pady=(12, 3))
    path_text = tk.StringVar(value=str(folder))
    ttk.Entry(parent, textvariable=path_text, state="readonly").pack(fill="x", pady=3)
