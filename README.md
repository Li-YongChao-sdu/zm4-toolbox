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

九转 RL 策略自检（需已安装 torch）：

```bash
python zm4_toolbox.py --jiuzhuan-rl-check report.json
```

## 目录结构

- `zm4_toolbox.py`：主程序与页面注册
- `pypomelo/`：造四协议库
- `output_cg1_20260921_1_2/`：游戏配置（活动、任务、奖励、商城、装备），**必须与主程序保持同级**
- `jiuzhuan_*.py`、`jiuzhuan_rl_model/`：九转金丹相关模块与强化学习模型
- `question-model-solver-3.py`：生存大冒险题目求解器与题库模型
- `survival_monte_carlo.py`：生存大冒险一周总分的蒙特卡洛模拟与双策略对比
- `arena_daily.py` / `shop_purchase.py` / `limited_activity_pages.py`：竞技场、商店、限时活动
- `my_daily.py` / `halloween_activity.py` / `jiuzhuan_ui.py`：我的日常、万圣活动、九转界面
- `造梦西游4活动工具箱.spec`：PyInstaller 打包配置

## 依赖说明

- `requests`、`pycryptodome`、`Pillow`：基础依赖
- `torch`：仅九转强化学习模型推理需要，不使用该功能可不安装

### 打包版使用九转 RL 策略

打包版不内置 `torch`（体积过大），但可以读取本机已安装的 torch：

1. 安装与本工具箱内置解释器相同版本的 Python（当前为 3.15）；
2. 执行 `python -m pip install torch --index-url https://download.pytorch.org/whl/cpu`；
3. 重新打开工具箱，选择「九转金丹」中的 RL 策略即可，程序会自动从注册表定位该 Python 的 `site-packages`。

可用以下命令验证：

```bash
造梦西游4活动工具箱.exe --jiuzhuan-rl-check report.json
```

报告 `ok=true` 即表示 torch 与模型加载正常。

## 生存大冒险双策略蒙特卡洛对比

`survival_monte_carlo.py` 模拟一周 7 次生存大冒险的总分，对比两种答题策略：

- **保命优先**：前 9 题尽量不死，死亡即停止（旧算法）。
- **积分最大化**：不考虑生命值，死亡后继续答完剩余题目（新算法）。

工具箱内加载今日题目后会并列显示两套方案；「我的日常」只保留「生存大冒险」（默认保命优先）和「积分最大化答题」两个入口。

模拟假设：

- 每天随机一个角色，7 个角色等概率；
- 每天按 `1xxx` 抽 1 题、`2xxx` 抽 2 题、`3xxx` 抽 3 题、`4xxx` 抽 3 题、`5xxx` 抽 1 题；
- 同一阶段内不放回、随机顺序，天与天独立；
- 判定条件、属性变化和得分使用 `question-model-solver-3.py` 的题库模型。

运行：

```bash
# 默认 1 万周，自动使用多进程
python survival_monte_carlo.py

# 更高精度
python survival_monte_carlo.py --trials 100000 --workers 8
```

1 万周配对模拟结果（随机种子 `20261123`）：

| 指标 | 保命优先 | 积分最大化 |
|---|---:|---:|
| 周均分 | 568.98 | 569.76 |
| 标准差 | 33.36 | 33.14 |
| P10 / P50 / P90 | 525 / 570 / 612 | 526 / 570 / 612 |
| P(总分 ≥ 480) | 99.63% | 99.66% |
| P(总分 ≥ 620) | 6.31% | 6.46% |

- 480 分低于 P10，两种策略都接近必达。
- 620 分刚好在 P90 以上，两种策略都只有约 6.4% 的概率。
- 积分最大化的提升很小：480 线 +0.03 个百分点（95%CI `-0.00 ~ +0.06`），620 线 +0.15 个百分点（95%CI `+0.07 ~ +0.23`）。原因是保命策略在最优路径上很少被迫死亡，只有少数“死亡后还能靠其他属性拿分”的日子才有额外收益。

以上是模型估计，实际概率会随服务端角色权重和题目抽取规则变化。修改脚本中的 `ROLES` 或 `COUNTS` 即可调整假设。

## 福果来（限时活动）

在「限时活动」页面运行，或在「一键运行 / 我的日常」中选择「福果来（600分）」。免费开图后等待10秒，再提交600分结算并领取菩提果×30、菩提之心×1；领奖后重登核对背包、次数、点券及累计消费。

- 每天仅领取1次免费奖励；已领即跳过，不购买300点券额外次数。
- 需要20级及至少2个道具背包空格。活动截止2026年12月17日23:59:59（北京时间），以本地最新官方活动配置为准。
- `fuguolai_activity.py` 与 `fuguolai_config.json` 必须与主程序一并保留。后者内置官方 cg1_20261123_1 的活动、关卡及奖励配置，兼容已有配置刷新缓存。
- 超时、断线、账号/存档切换或服务器拒绝时停止，不补交、不中途重登后重发领奖。

## 安全说明

本仓库不包含账号密码、Cookie、个人配置、收藏、定时任务、运行日志或实测记录。
首次运行会在当前目录生成 `zm4_toolbox_config.json`、`my_daily_favorites.json` 等本地配置，已加入 `.gitignore`。

## 免责声明

本项目仅供学习与交流使用，请在遵守游戏用户协议的前提下自行承担使用风险。
