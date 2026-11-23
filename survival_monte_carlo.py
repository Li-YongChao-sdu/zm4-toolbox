"""生存大冒险：一周 7 次总分的蒙特卡洛模拟。

对比两种答题算法：
  1. 保命优先：前 9 题尽量不死，死亡即停止（旧算法）。
  2. 积分最大化：不考虑生命值，死亡后继续答完剩余题目（新算法）。

用法：
  python survival_monte_carlo.py
  python survival_monte_carlo.py --trials 200000 --seed 20261123

假设（可用命令行参数调整）：
  - 每天随机一个角色，7 个角色等概率。
  - 每天题目固定为：1xxx 抽 1 题、2xxx 抽 2 题、3xxx 抽 3 题、4xxx 抽 3 题、5xxx 抽 1 题。
  - 同一阶段内不放回抽取，并随机打乱顺序；不同天之间独立。
"""

import argparse
import concurrent.futures
import importlib.util
import math
import os
import random
import statistics
import time
from pathlib import Path

ATTRS = ["health", "power", "wisdom", "charm", "luck", "smart"]
ATTR_INDEX = {name: index for index, name in enumerate(ATTRS)}
COUNTS = {"1": 1, "2": 2, "3": 3, "4": 3, "5": 1}
DAYS = 7
NEG_INF = -10 ** 9


def load_question_db():
    solver_path = Path(__file__).with_name("question-model-solver-3.py")
    spec = importlib.util.spec_from_file_location("zm4_survival_solver", solver_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_markdown(module.MARKDOWN_CONTENT)


def compile_options(db):
    """把题库编译为纯元组，避免模拟时反复查字典。"""
    compiled = {}
    for qid, options in db.items():
        rows = []
        for option in options:
            cond = []
            for attr, op, value in option["cond"]:
                if op != ">=":
                    raise ValueError("当前题库只支持 >= 条件，发现: %s %s %s" % (attr, op, value))
                cond.append((ATTR_INDEX[attr], int(value)))
            succ_eff = tuple(int(option["succ_eff"].get(attr, 0)) for attr in ATTRS)
            fail_eff = tuple(int(option["fail_eff"].get(attr, 0)) for attr in ATTRS)
            rows.append((tuple(cond), succ_eff, fail_eff,
                         int(option["succ_score"]), int(option["fail_score"])))
        compiled[qid] = tuple(rows)
    return compiled


def scores(state, qids, compiled):
    """一次遍历同时算出两种算法的分数。

    返回 (保命优先分数, 积分最大化分数)。
    保命优先：前 9 题存活优先；若都活不过 9 题，取死亡前最高分。
    积分最大化：死亡不停止，求 10 题总分最大。
    """
    if len(qids) != 10:
        raise ValueError("当前模拟按每天 10 题设计，实际为 %d 题" % len(qids))
    if state[0] <= 0:
        return NEG_INF, NEG_INF

    max_states = {state: 0}       # 所有路径：状态 -> 最高累计分
    safe_states = {state: 0}      # 前 9 题仍存活的路径：状态 -> 最高累计分
    dead_best = NEG_INF           # 前 9 题死亡路径的最高分（死亡即停止）
    safe_final = NEG_INF          # 活过前 9 题后，第 10 题的最高总分

    for index, qid in enumerate(qids):
        options = compiled[qid]
        max_next = {}
        safe_next = {}
        for current, max_total in max_states.items():
            safe_total = safe_states.get(current)
            h, p, w, c, l, sm = current
            for cond, succ_eff, fail_eff, succ_score, fail_score in options:
                success = True
                for attr_index, value in cond:
                    if current[attr_index] < value:
                        success = False
                        break
                if success:
                    gain = succ_score
                    effect = succ_eff
                else:
                    gain = fail_score
                    effect = fail_eff
                new_state = (
                    h + effect[0], p + effect[1], w + effect[2],
                    c + effect[3], l + effect[4], sm + effect[5],
                )
                new_total = max_total + gain
                if new_total > max_next.get(new_state, NEG_INF):
                    max_next[new_state] = new_total

                if safe_total is not None:
                    safe_total_new = safe_total + gain
                    if index < 9:
                        if new_state[0] <= 0:
                            if safe_total_new > dead_best:
                                dead_best = safe_total_new
                        elif safe_total_new > safe_next.get(new_state, NEG_INF):
                            safe_next[new_state] = safe_total_new
                    elif safe_total_new > safe_final:
                        safe_final = safe_total_new

        max_states = max_next
        if index < 9:
            safe_states = safe_next

    safe_result = safe_final if safe_states else dead_best
    return safe_result, max(max_states.values())


def sample_day(rng, roles, pools):
    state = rng.choice(roles)
    qids = []
    for phase, count in COUNTS.items():
        picked = rng.sample(pools[phase], count)
        rng.shuffle(picked)
        qids.extend(picked)
    return state, tuple(qids)


ROLES = [
    (3, 4, 5, 5, 4, 3),  # 小唐
    (4, 5, 4, 3, 4, 4),  # 小猴
    (6, 4, 3, 3, 3, 3),  # 小猪
    (3, 3, 4, 3, 3, 6),  # 小沙
    (4, 3, 4, 4, 5, 4),  # 小白
    (3, 3, 4, 5, 3, 6),  # 小玉
    (5, 4, 4, 4, 3, 4),  # 小吒
]


def simulate_chunk(trials, seed):
    db = load_question_db()
    compiled = compile_options(db)
    pools = {phase: sorted(qid for qid in db if qid.startswith(phase)) for phase in COUNTS}
    rng = random.Random(seed)
    safe_totals = []
    max_totals = []
    for _ in range(trials):
        safe_week = 0
        max_week = 0
        for _ in range(DAYS):
            state, qids = sample_day(rng, ROLES, pools)
            safe_daily, max_daily = scores(state, qids, compiled)
            safe_week += safe_daily
            max_week += max_daily
        safe_totals.append(safe_week)
        max_totals.append(max_week)
    return safe_totals, max_totals


def simulate(trials, seed, workers):
    if workers <= 1:
        return simulate_chunk(trials, seed)

    chunks = []
    base = trials // workers
    remainder = trials % workers
    for index in range(workers):
        count = base + (1 if index < remainder else 0)
        if count:
            chunks.append((count, seed + index * 7919))

    safe_totals = []
    max_totals = []
    start = time.time()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(simulate_chunk, count, chunk_seed)
                   for count, chunk_seed in chunks]
        for done, future in enumerate(concurrent.futures.as_completed(futures), 1):
            safe_part, max_part = future.result()
            safe_totals.extend(safe_part)
            max_totals.extend(max_part)
            print("  已完成 %d/%d 个分片 (%.1fs)" % (done, len(futures), time.time() - start), flush=True)
    return safe_totals, max_totals


def summary(name, totals, thresholds):
    count = len(totals)
    mean = statistics.fmean(totals)
    stdev = statistics.pstdev(totals)
    result = {"name": name, "mean": mean, "std": stdev,
              "min": min(totals), "max": max(totals),
              "p10": percentile(totals, 10), "p50": percentile(totals, 50),
              "p90": percentile(totals, 90)}
    for threshold in thresholds:
        hits = sum(1 for value in totals if value >= threshold)
        probability = hits / count
        result["p%d" % threshold] = probability
        result["se%d" % threshold] = math.sqrt(probability * (1 - probability) / count)
    return result


def percentile(values, pct):
    ordered = sorted(values)
    if not ordered:
        return 0
    position = (len(ordered) - 1) * pct / 100.0
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def paired_difference(max_totals, safe_totals, threshold):
    diffs = [(1 if a >= threshold else 0) - (1 if b >= threshold else 0)
             for a, b in zip(max_totals, safe_totals)]
    mean = statistics.fmean(diffs)
    if len(diffs) > 1:
        stderr = statistics.stdev(diffs) / math.sqrt(len(diffs))
    else:
        stderr = 0.0
    return mean, stderr


def main():
    parser = argparse.ArgumentParser(description="生存大冒险一周总分蒙特卡洛模拟")
    parser.add_argument("--trials", type=int, default=10000, help="模拟周数，默认 10000")
    parser.add_argument("--seed", type=int, default=20261123, help="随机种子")
    parser.add_argument("--workers", type=int, default=None,
                        help="并行进程数，默认 min(8, CPU 核心数)")
    parser.add_argument("--thresholds", default="480,620", help="分数线，逗号分隔")
    args = parser.parse_args()
    thresholds = [int(x) for x in args.thresholds.split(",") if x.strip()]
    workers = args.workers if args.workers else min(8, os.cpu_count() or 1)

    print("模拟周数: %d, 并行进程: %d" % (args.trials, workers))
    print("每天: 随机角色(7选1) + 1/2/3/3/1 题，阶段内不放回、随机顺序，天与天独立")
    print("开始模拟...", flush=True)
    safe_totals, max_totals = simulate(args.trials, args.seed, workers)
    safe = summary("保命优先", safe_totals, thresholds)
    maximum = summary("积分最大化", max_totals, thresholds)

    print("\n" + "=" * 74)
    print("%-12s %10s %10s %10s %10s" % ("算法", "周均分", "标准差", "最低", "最高"))
    print("-" * 74)
    for item in (safe, maximum):
        print("%-12s %10.2f %10.2f %10d %10d" % (
            item["name"], item["mean"], item["std"], item["min"], item["max"]))
    print("-" * 74)
    print("%-12s %10s %10s %10s" % ("算法", "P10", "P50", "P90"))
    for item in (safe, maximum):
        print("%-12s %10.1f %10.1f %10.1f" % (item["name"], item["p10"], item["p50"], item["p90"]))

    print("\n" + "=" * 74)
    print("分数线概率（括号内为蒙特卡洛标准误）")
    print("-" * 74)
    for threshold in thresholds:
        print("总分 >= %d" % threshold)
        for item in (safe, maximum):
            print("  %-12s %8.2f%%  (±%.2f%%)" % (
                item["name"], item["p%d" % threshold] * 100,
                item["se%d" % threshold] * 100))
        diff, stderr = paired_difference(max_totals, safe_totals, threshold)
        low = (diff - 1.96 * stderr) * 100
        high = (diff + 1.96 * stderr) * 100
        print("  差值(积分最大化 - 保命优先): %+.2f 个百分点, 95%%CI [%+.2f, %+.2f]"
              % (diff * 100, low, high))
        print()


if __name__ == "__main__":
    main()
