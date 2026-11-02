# 造梦西游4 活动工具箱

基于 Python + Tkinter 的桌面工具箱，集成日常活动、竞技场、商店购买、九转金丹、限时活动等自动化辅助功能。

## 运行环境

- Windows 10/11 64 位
- Python 3.10+
- 安装依赖：

```bash
pip install -r requirements.txt
```

## 启动

```bash
python zm4_toolbox.py
```

启动自检（不进入常规界面，输出 JSON 报告）：

```bash
python zm4_toolbox.py --startup-check report.json
```

## 目录结构

- `zm4_toolbox.py`：主程序与页面注册
- `pypomelo/`：造四协议库
- `output_cg1_20260921_1_2/`：游戏配置（活动、任务、奖励、商城、装备），**必须与主程序保持同级**
- `jiuzhuan_*.py`、`jiuzhuan_rl_model/`：九转金丹相关模块与强化学习模型
- `question-model-solver-3.py`：旧版题目求解器
- `arena_daily.py` / `shop_purchase.py` / `limited_activity_pages.py`：竞技场、商店、限时活动
- `my_daily.py` / `halloween_activity.py` / `jiuzhuan_ui.py`：我的日常、万圣活动、九转界面
- `造梦西游4活动工具箱.spec`：PyInstaller 打包配置

## 依赖说明

- `requests`、`pycryptodome`、`Pillow`：基础依赖
- `torch`：仅九转强化学习模型推理需要，不使用该功能可不安装

## 安全说明

本仓库不包含账号密码、Cookie、个人配置、收藏、定时任务、运行日志或实测记录。
首次运行会在当前目录生成 `zm4_toolbox_config.json`、`my_daily_favorites.json` 等本地配置，已加入 `.gitignore`。

## 免责声明

本项目仅供学习与交流使用，请在遵守游戏用户协议的前提下自行承担使用风险。
