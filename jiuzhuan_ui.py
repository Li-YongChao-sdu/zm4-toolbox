"""限时活动中的九转炼丹页面。"""
import sys
import importlib.util
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from jiuzhuan_service import MODELS, DEFAULT_MODEL, run


def accuracy_text(model):
    results = {
        '共同裁判': (
            '正式实测3/3达标并领取40个老君简令；其中1局续局，连续完整流程2/2。\n'
            '本地定向回归7/8＝87.5%；10月30日新种子配对11/12＝91.7%，提前中止。'),
        '诊断干预版（实验）': (
            '本地新种子配对10/12＝83.3%，同期共同裁判11/12；救回1局、退步2局。\n'
            '50组计划提前中止，只计12组完整配对；另两例已知失败回归2/2，未正式实测。'),
        '(花崎桜雪)预期最高分数': (
            '算法作者：花崎桜雪（原版）。独立本地50局：49/50＝98%；平均首次达标124.2秒，最慢157.0秒。\n'
            '终局平均69864分，范围41934～98421；1局有确定性预测差异，尚未正式实测。\n'
            '原版核心、权重与开局表保留；达到45000后仍持续规划最高分。'),
        '融合达标版（实验）': (
            '最新独立本地10局：10/10＝100%；平均达标116.9秒，最慢135.5秒，无同期原版对照。\n'
            '早期10组配对双方10/10；历史困难7组融合3/7、原版6/7；其中3组复测双方3/3。\n'
            '各批次分别统计，不合并；尚未正式实测，也未实施新的双策略共同决策。\n'
            '完整裁判记录保存在工具箱旁 jiuzhuan_judge_logs。'),
        '回收价值版': (
            '本地新样本：仅步数药渣48/50＝96%；独立步数＋合成药渣压力45/50＝90%。\n'
            '2026-10-29固定深度3实验；两种环境分开统计，未核实同版本正式实测汇总。'),
        '压力修正版': (
            '本地新样本：仅步数药渣49/50＝98%；独立步数＋合成药渣压力46/50＝92%。\n'
            '2026-10-29固定深度3实验；两种环境分开统计，未核实同版本正式实测汇总。'),
        '动态分支版': (
            '历史本地实验：仅步数药渣129/132＝97.7%；独立步数＋合成药渣压力118/132＝89.4%。\n'
            '原计划提前中止；2026-10-29固定深度3实验，不代表所有动态参数设置的达标率。'),
        '原 G2W 版': (
            '已记录服务器练习6局：5/6＝83.3%；失败局38769分。\n'
            '最近3局2/3达标，均低于300秒；练习统计不含正式奖励验证。'),
        '(羊肉串)冻结小模型（RL，需torch）': (
            '第三方 freeze-small-model 强化学习策略（创作者：羊肉串），纯神经网络前向推理（CPU）。\n'
            '服务器练习6局：6/6＝100% 达标，均分约50090（46622～54570），单局8～14秒。\n'
            '服务器正式1局：53186分达标，领取40个老君简令，点券未消耗。\n'
            '本地独立批量8192局（原作者评测种子）：97.4% 达标，均分45697；达标后随机落子收尾。'),
    }
    return (results.get(model, '暂无可核实的同版本测试汇总。') +
            '\n统计截至2026-10-30，达标指丹气≥45000；不同版本、样本和环境不能直接比较。'
            '\n本地药渣模拟不等于服务器分布；小样本不能证明总体97%～98%，不保证每局成功。')


def goal_text(model):
    if model == '(花崎桜雪)预期最高分数':
        return '花崎桜雪原版：按预期最高分数持续选点，直至棋盘结束或活动计时结束；45000后不随机收尾。'
    return '目标丹气 45000；达到后随机落子占满棋盘，立即结束并领取结算奖励。'


def torch_install_text():
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    state = '已安装，可直接使用' if importlib.util.find_spec('torch') else '未安装，选 RL 策略前需先安装'
    return (f'RL 策略需要 torch（CPU 版）。当前工具箱运行在 Python {ver}，torch {state}。\n'
            f'安装时的 Python 版本必须与运行版本一致：py -{ver} -m pip install torch '
            '--index-url https://download.pytorch.org/whl/cpu\n'
            '版本对照：Python 3.9 最高只能装 torch 2.8.0；3.10 及以上可装 2.15.0（3.12、3.15 已实测）；'
            '低于 3.9 不支持。\n'
            '说明：CPU 版即可，无需 CUDA，约 250MB；不同 Python 版本（如 3.12 与 3.15）环境互相独立，'
            '装在别的版本里本环境无法使用。')


class JiuZhuanPage:
    def _build_jiuzhuan_tab(self):
        tab = self._limited_page('九转炼丹', padding=12)
        self.var_jiuzhuan_model = tk.StringVar(value=DEFAULT_MODEL)
        self.var_jiuzhuan_practice = tk.BooleanVar(value=False)
        self._jiuzhuan_stop = threading.Event()
        self._jiuzhuan_running = False
        self.lbl_jiuzhuan_goal = ttk.Label(tab, text=goal_text(DEFAULT_MODEL), wraplength=850)
        self.lbl_jiuzhuan_goal.pack(anchor='w', pady=2)
        row = ttk.Frame(tab)
        row.pack(fill='x', pady=4)
        ttk.Label(row, text='策略：').pack(side='left')
        self.combo_jiuzhuan = ttk.Combobox(row, textvariable=self.var_jiuzhuan_model,
                                         values=list(MODELS), state='readonly', width=28)
        self.combo_jiuzhuan.pack(side='left', padx=5)
        ttk.Checkbutton(row, text='练习模式（不消耗正式次数，无奖励）',
                        variable=self.var_jiuzhuan_practice).pack(side='left', padx=8)
        self.jiuzhuan_info_frame = ttk.Frame(tab)
        self.lbl_jiuzhuan_accuracy = ttk.Label(self.jiuzhuan_info_frame,
                                             text=accuracy_text(DEFAULT_MODEL),
                                             foreground='#245b86', wraplength=850)
        self.lbl_jiuzhuan_accuracy.pack(anchor='w', pady=2)
        ttk.Label(self.jiuzhuan_info_frame, text=torch_install_text(), foreground='#5a5a5a',
                  wraplength=850, justify='left').pack(anchor='w', pady=2)
        self._jiuzhuan_info_open = tk.BooleanVar(value=False)
        self.btn_jiuzhuan_info = ttk.Checkbutton(tab, text='显示策略说明 / torch 安装',
                                                variable=self._jiuzhuan_info_open,
                                                command=self._toggle_jiuzhuan_info)
        self.btn_jiuzhuan_info.pack(anchor='w', pady=(2, 0))
        ttk.Label(self.jiuzhuan_info_frame,
                  text='新版配置 cg1_20261026_1。仅使用免费正式次数；不购买次数或净丹露。\n'
                  '运行期间请勿在其他客户端操作该账号。停止或网络异常后，请到游戏中核查未结算局。',
                  foreground='gray', wraplength=850).pack(anchor='w', pady=2)
        def update_model_info(*_):
            model = self.var_jiuzhuan_model.get()
            self.lbl_jiuzhuan_accuracy.config(text=accuracy_text(model))
            self.lbl_jiuzhuan_goal.config(text=goal_text(model))
        self.var_jiuzhuan_model.trace_add('write', update_model_info)
        self.lbl_jiuzhuan = ttk.Label(tab, text='尚未运行')
        self.lbl_jiuzhuan.pack(anchor='w', pady=4)
        buttons = ttk.Frame(tab)
        buttons.pack(anchor='w', pady=4)
        self.btn_jiuzhuan = ttk.Button(buttons, text='运行一次', command=self._do_jiuzhuan)
        self.btn_jiuzhuan.pack(side='left', padx=4)
        self.btn_jiuzhuan_resume = ttk.Button(buttons, text='继续未结算局',
                                            command=lambda: self._do_jiuzhuan(resume=True))
        self.btn_jiuzhuan_resume.pack(side='left', padx=4)
        ttk.Button(buttons, text='停止', command=self._jiuzhuan_stop.set).pack(side='left', padx=4)

    def _toggle_jiuzhuan_info(self):
        if self._jiuzhuan_info_open.get():
            self.jiuzhuan_info_frame.pack(anchor='w', fill='x', pady=4)
        else:
            self.jiuzhuan_info_frame.pack_forget()

    def _do_jiuzhuan(self, resume=False):
        if not self._ensure_login() or self._jiuzhuan_running:
            return
        if self._limited_config_expired('九转炼丹'):
            messagebox.showinfo('九转炼丹', '配置中的活动已结束')
            return
        practice = self.var_jiuzhuan_practice.get()
        label = self.var_jiuzhuan_model.get()
        if label not in MODELS:
            label = DEFAULT_MODEL
            self.var_jiuzhuan_model.set(label)
        slot = self.current_save['index']
        client = self.client
        self._jiuzhuan_running = True
        self._jiuzhuan_stop.clear()
        self.btn_jiuzhuan.config(state='disabled')
        self.btn_jiuzhuan_resume.config(state='disabled')
        self.combo_save.config(state='disabled')
        self.btn_login.config(state='disabled')
        def emit(stage, **data):
            if stage == 'move':
                if data['move'] % 10:
                    return
                text = '第%d步，丹气%d，耗时%.1f秒' % (data['move'], data['score'], data['elapsed'])
            elif stage == 'complete':
                text = '已结算：丹气%d，奖励%s，点券未变化' % (data['score'], data['reward'])
            elif stage == 'target_reached':
                text = '丹气%d，切换随机落子收尾，直到棋盘占满' % data['score']
            elif stage == 'waiting_settlement':
                text = '丹气%d，等待服务器计时结算' % data['score']
            else:
                text = {'started': '已开局：'+label, 'settlement': '收到结算回包',
                        'stopped': '已停止，请到游戏中核查未结算局'}.get(stage, stage)
            self._log('[九转炼丹] '+text)
            self.root.after(0, lambda t=text: self.lbl_jiuzhuan.config(text=t))
        def worker():
            connection = [None]
            def connect():
                if self.client is not client:
                    raise RuntimeError('账号已切换，停止当前九转任务')
                if connection[0]:
                    connection[0].disconnect()
                flow, _, scene = self._connect_and_enter(slot)
                connection[0] = flow
                return flow, scene
            try:
                flow, scene = connect()
                run(flow, scene, model_label=label, practice=practice,
                    stop=self._jiuzhuan_stop, emit=emit, reconnect=connect, resume=resume)
            except Exception as exc:
                self._log('[九转炼丹] '+str(exc)+'；未自动重试')
            finally:
                if connection[0]:
                    connection[0].disconnect()
                def done():
                    self._jiuzhuan_running = False
                    self.btn_jiuzhuan.config(state='normal')
                    self.btn_jiuzhuan_resume.config(state='normal')
                    self.combo_save.config(state='readonly')
                    self.btn_login.config(state='normal')
                self.root.after(0, done)
        threading.Thread(target=worker, daemon=True).start()
