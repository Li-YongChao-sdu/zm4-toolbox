import re
from functools import lru_cache
from typing import Dict, List, Tuple, Optional

# ==================== 1. 内嵌题库（豆包AI解析cg1后得出） ====================
MARKDOWN_CONTENT = """
# 生存大冒险 全题库（含判定条件）

- 属性: health=健康/体质, power=战力, wisdom=智慧, charm=魅力, luck=运气, smart=灵巧
- 判定条件: 你的对应属性 ≥ 要求值 才算答对，否则答错
- 答对得成功积分，答错得失败积分

## 1xxx 阶段（第1天·准备 | 成功积分6 / 失败积分3）

| ID | 题目 | 选项 | 判定条件(达标=答对) | 答对加成 | 答错惩罚 |
|----|------|------|--------------------|----------|----------|
| 1001 | 在你准备离开村子去冒险时，族长想交给你一个很危险的任务，并许诺完成任务后给你奖励，你会_ | 1. 坚定不移的接受任务 | power≥4 | power+1 | health-1 |
| 1001 | 在你准备离开村子去冒险时，族长想交给你一个很危险的任务，并许诺完成任务后给你奖励，你会_ | 2. 我拒绝接受任务，自己出去冒险 | charm≥4 | 无 | health-1 |
| 1001 | 在你准备离开村子去冒险时，族长想交给你一个很危险的任务，并许诺完成任务后给你奖励，你会_ | 3. 默默不做声 | luck≥4 | charm-1 | wisdom-1 |
| 1001 | 在你准备离开村子去冒险时，族长想交给你一个很危险的任务，并许诺完成任务后给你奖励，你会_ | 4. 推荐你的仇敌 | wisdom≥4 | wisdom+1 | charm-1 |

| 1002 | 冒险前，你决定到商店买些必需品，但是钱不太够，你会_ | 1. 卖掉护身符，购买漂亮的衣服 | luck≥4 | luck-1,smart+1 | charm-1 |
| 1002 | 冒险前，你决定到商店买些必需品，但是钱不太够，你会_ | 2. 卖掉鞋子，购买游戏攻略 | smart≥4 | smart-1,luck+1 | charm-1 |
| 1002 | 冒险前，你决定到商店买些必需品，但是钱不太够，你会_ | 3. 不买了，用废弃的强化石升级装备 | luck≥5 | power+1 | health-1 |
| 1002 | 冒险前，你决定到商店买些必需品，但是钱不太够，你会_ | 4. 借点钱买强化石 | charm≥3 | charm-1,power+1 | charm-1 |

| 1003 | 冒险前，族长准备送你一件礼物，你会选择_ | 1. 究天古剑 | power≥4 | power+1 | health-1,power-1 |
| 1003 | 冒险前，族长准备送你一件礼物，你会选择_ | 2. 绝世秘籍 | wisdom≥4 | health+1,power+1 | health-1,power+2 |
| 1003 | 冒险前，族长准备送你一件礼物，你会选择_ | 3. 宠物-招财猫 | charm≥4 | luck+1 | charm-1 |
| 1003 | 冒险前，族长准备送你一件礼物，你会选择_ | 4. 坐骑-小羊驼 | smart≥4 | smart+1 | charm-1 |

| 1004 | 在冒险准备前，突然发现自己没有一把称手的好武器，你会_ | 1. 出去抢一件 | power≥4 | charm-1 | health-1 |
| 1004 | 在冒险准备前，突然发现自己没有一把称手的好武器，你会_ | 2. 找族长借一件 | charm≥3 | power+1,smart-1 | 无 |
| 1004 | 在冒险准备前，突然发现自己没有一把称手的好武器，你会_ | 3. 随便墙角找了个棒子当武器，凑合用 | luck≥5 | power+1 | charm-1 |
| 1004 | 在冒险准备前，突然发现自己没有一把称手的好武器，你会_ | 4. 找村里的锻造大师学习锻造技术 | wisdom≥5 | power+2 | health-1,power-1 |

## 2xxx 阶段（第2天·游历 | 成功积分6 / 失败积分3）

| ID | 题目 | 选项 | 判定条件(达标=答对) | 答对加成 | 答错惩罚 |
|----|------|------|--------------------|----------|----------|
| 2001 | 你走在乡间的小路上，遇到了一个老人家摔倒在地。你会_ | 1. 盘膝在一旁打坐肯定是白骨精变的，打他 | wisdom≥4 且 power≥3 | wisdom+1 | health-1,charm-1 |
| 2001 | 你走在乡间的小路上，遇到了一个老人家摔倒在地。你会_ | 2. 扶他一把 | charm≥5 | health+1,charm+1 | health-1 |
| 2001 | 你走在乡间的小路上，遇到了一个老人家摔倒在地。你会_ | 3. 找个人来作证，再扶 | smart≥4 | 无 | charm-1 |
| 2001 | 你走在乡间的小路上，遇到了一个老人家摔倒在地。你会_ | 4. 肯定是碰瓷的，离得远远的 | health≥99 | 无 | charm-1,wisdom-1 |

| 2002 | 今夜失眠，来到屋顶数星星，正巧遇到圣诞老公公正在钻烟囱，你会_ | 1. 偷偷靠近偷走圣诞老公公的坐骑 | smart≥4 | smart+1 | charm-1 |
| 2002 | 今夜失眠，来到屋顶数星星，正巧遇到圣诞老公公正在钻烟囱，你会_ | 2. 看圣诞老公公不爽，上去一顿暴打 | power≥5 | power+1 | health-1 |
| 2002 | 今夜失眠，来到屋顶数星星，正巧遇到圣诞老公公正在钻烟囱，你会_ | 3. 含情脉脉上去跟圣诞老公公要礼包 | charm≥3 | wisdom+1,luck+1 | 无 |
| 2002 | 今夜失眠，来到屋顶数星星，正巧遇到圣诞老公公正在钻烟囱，你会_ | 4. 什么也不做，悄悄离去 | health≥99 | 无 | wisdom-1 |

| 2003 | 机缘巧合来到皇宫做客，但见皇宫中秘宝重重，飞天大盗闻风而动，你会_ | 1. 联合飞天大盗，一同盗宝 | smart≥5 | charm-1,power+2 | health-1 |
| 2003 | 机缘巧合来到皇宫做客，但见皇宫中秘宝重重，飞天大盗闻风而动，你会_ | 2. 找寻其踪迹，和他对战 | power≥4 且 smart≥3 | health-1,power+2 | 无 |
| 2003 | 机缘巧合来到皇宫做客，但见皇宫中秘宝重重，飞天大盗闻风而动，你会_ | 3. 以重宝设陷阱诱捕大盗 | wisdom≥5 | luck+1,wisdom+1 | charm-1 |
| 2003 | 机缘巧合来到皇宫做客，但见皇宫中秘宝重重，飞天大盗闻风而动，你会_ | 4. 向皇宫守卫举报 | charm≥5 | charm+1 | charm-1 |

| 2004 | 野外发现一颗雪莲幼苗，药香弥漫，你会_ | 1. 在旁边打坐，吸收药香 | health≥3 | health+1 | health-1 |
| 2004 | 野外发现一颗雪莲幼苗，药香弥漫，你会_ | 2. 采摘回家培养 | smart≥5 | health+1,wisdom+1 | health-1 |
| 2004 | 野外发现一颗雪莲幼苗，药香弥漫，你会_ | 3. 做个记号，等它成熟了再来采摘 | wisdom≥5 | health+1,wisdom+1 | 无 |
| 2004 | 野外发现一颗雪莲幼苗，药香弥漫，你会_ | 4. 此处灵气浓郁，定有其他草药，四处搜寻 | luck≥5 | health+2 | health-1,smart-1 |

| 2005 | 你来到须弥山角，看到一艘远洋大船，你会_ | 1. 和航海家学习航行经验，再驾船出海 | wisdom≥4 | charm+1,wisdom+1 | charm-1 |
| 2005 | 你来到须弥山角，看到一艘远洋大船，你会_ | 2. 直接上船，出海寻宝 | luck≥5 | health-1 | health-1 |
| 2005 | 你来到须弥山角，看到一艘远洋大船，你会_ | 3. 邀上三五好友，一起出游 | charm≥4 且 luck≥4 | luck+1 | charm-1 |
| 2005 | 你来到须弥山角，看到一艘远洋大船，你会_ | 4. 在船底凿个洞 | charm≥4 | charm-1 | health-1 |

| 2006 | 偶遇一只造梦威廉，你会_ | 1. 抢走威廉的零食 | power≥4 | health+1 | health-1 |
| 2006 | 偶遇一只造梦威廉，你会_ | 2. 投稿生存大冒险题目 | wisdom≥4 | power+1 | wisdom+1 |
| 2006 | 偶遇一只造梦威廉，你会_ | 3. 和威廉比比谁帅 | charm≥4 | charm+1 | 无 |
| 2006 | 偶遇一只造梦威廉，你会_ | 4. 问威廉要更新剧透 | luck≥4 | wisdom+1 | 无 |

| 2007 | 来到神兽森林中，看到一只蓝色水鼠在丛林中跳跃，你会_ | 1. 定是妖怪，上前打他！ | health≥99 | 无 | health-1 |
| 2007 | 来到神兽森林中，看到一只蓝色水鼠在丛林中跳跃，你会_ | 2. 和它谈天谈地聊心情，将其收服 | charm≥5 | power+1,charm+1 | health-1 |
| 2007 | 来到神兽森林中，看到一只蓝色水鼠在丛林中跳跃，你会_ | 3. 动物都要喝水，守株待兔，在水中埋伏它。 | luck≥5 | power+1,luck+1 | health-1 |
| 2007 | 来到神兽森林中，看到一只蓝色水鼠在丛林中跳跃，你会_ | 4. 奇珍重宝多有异兽相伴，跟随它。 | smart≥5 | power+1,smart+1 | health-1,smart-1 |

| 2008 | 你来到长安城，你第一件想去做的事是_ | 1. 城中如此繁华，四处逛逛 | wisdom≥4 | wisdom+1 | charm-1 |
| 2008 | 你来到长安城，你第一件想去做的事是_ | 2. 买把好武器防身 | charm≥4 且 luck≥3 | power+1 | charm-1 |
| 2008 | 你来到长安城，你第一件想去做的事是_ | 3. 去告示栏看看 | power≥4 | charm+1 | health-1 |
| 2008 | 你来到长安城，你第一件想去做的事是_ | 4. 探查城中密道 | smart≥4 且 charm≥3 | smart+1,power+1 | smart-1 |

| 2009 | 路过玄武门时，道路旁矗立一座玄武石像，你会_ | 1. 战乱后的玄武门建筑破损，石像却完好无损，一定暗藏玄机！ | wisdom≥5 | power+1 | 无 |
| 2009 | 路过玄武门时，道路旁矗立一座玄武石像，你会_ | 2. 在石像上刻字：XX到此一游 | luck≥5 | charm-1 | charm-1 |
| 2009 | 路过玄武门时，道路旁矗立一座玄武石像，你会_ | 3. 和石像合影留恋 | charm≥4 | charm+1 | charm-1 |
| 2009 | 路过玄武门时，道路旁矗立一座玄武石像，你会_ | 4. 目不斜视，径直走过 | smart≥4 | 无 | smart-1 |

| 2010 | 在城中闲逛时，看到有联盟正在招人，受邀加入后你会_ | 1. 去联盟药园逛逛 | smart≥5 | charm+1,smart+1 | 无 |
| 2010 | 在城中闲逛时，看到有联盟正在招人，受邀加入后你会_ | 2. 和其他盟友切磋PK | power≥5 | power+1,charm+1 | 无 |
| 2010 | 在城中闲逛时，看到有联盟正在招人，受邀加入后你会_ | 3. 为联盟贡献出份力 | luck≥4 | power+1 | 无 |
| 2010 | 在城中闲逛时，看到有联盟正在招人，受邀加入后你会_ | 4. 宣传自己的联盟，招募更多人加入 | charm≥4 且 wisdom≥3 | charm+2 | charm-1 |

## 3xxx 阶段（第3天·修行 | 成功积分9 / 失败积分4）

| ID | 题目 | 选项 | 判定条件(达标=答对) | 答对加成 | 答错惩罚 |
|----|------|------|--------------------|----------|----------|
| 3001 | 你来到了普陀山脚，四头虫在和一个黑影打斗，你会_ | 1. 帮四头虫 | power≥6 且 smart≥5 | power+1,charm-1 | health-1 |
| 3001 | 你来到了普陀山脚，四头虫在和一个黑影打斗，你会_ | 2. 帮黑影 | power≥7 | health+1 | health-1 |
| 3001 | 你来到了普陀山脚，四头虫在和一个黑影打斗，你会_ | 3. 帮忙调解 | charm≥7 | charm+1 | health-2 |
| 3001 | 你来到了普陀山脚，四头虫在和一个黑影打斗，你会_ | 4. 转身逃开 | smart≥6 | 无 | health-1,power-1 |

| 3002 | 在登山途中，电闪雷鸣，天昏地暗，前方出现一道黑影，你将会_ | 1. 大喊：造梦威廉在此，何方妖怪？还不速速退下！ | charm≥5 且 luck≥4 | 无 | health-1,charm-1 |
| 3002 | 在登山途中，电闪雷鸣，天昏地暗，前方出现一道黑影，你将会_ | 2. 什么也不说，冲向黑影给他一拳 | power≥6 | power-1,health+1 | health-2 |
| 3002 | 在登山途中，电闪雷鸣，天昏地暗，前方出现一道黑影，你将会_ | 3. 问道：阁下有什么难处，还望道来，若力所能及，定当相助 | charm≥6 | health+1 | health-1,smart-1 |
| 3002 | 在登山途中，电闪雷鸣，天昏地暗，前方出现一道黑影，你将会_ | 4. 转身逃开 | smart≥6 | smart-1 | health-2 |

| 3003 | 你来到朱雀街，这里是牛妖特处士看守，你会_ | 1. 冲上去和特处士血拼 | power≥6 | power+1 | health-2 |
| 3003 | 你来到朱雀街，这里是牛妖特处士看守，你会_ | 2. 去找个帮手 | charm≥5 且 wisdom≥4 | charm+1 | health-2 |
| 3003 | 你来到朱雀街，这里是牛妖特处士看守，你会_ | 3. 先藏起来，等特处士睡着了，再冲上去 | wisdom≥5 且 smart≥4 | health-1,smart+1 | health-2 |
| 3003 | 你来到朱雀街，这里是牛妖特处士看守，你会_ | 4. 绕路而走，打个酱油 | smart≥4 且 luck≥4 | health-1 | health-1,smart-1 |

| 3004 | 迎着清霜，看着明月，路过双叉岭，忽见一彪悍虎精，身着锁甲，爪子沾血，目放凶光，你会_ | 1. 勇者无畏，拿出兵器，前去和他较量一番 | power≥6 | power+1 | health-2 |
| 3004 | 迎着清霜，看着明月，路过双叉岭，忽见一彪悍虎精，身着锁甲，爪子沾血，目放凶光，你会_ | 2. 后退几步，寻到一个好地势与他作战 | smart≥5 且 wisdom≥4 | smart+1 | health-2 |
| 3004 | 迎着清霜，看着明月，路过双叉岭，忽见一彪悍虎精，身着锁甲，爪子沾血，目放凶光，你会_ | 3. 转动脑筋，寻找虎精的破绽，然后发动攻击 | wisdom≥5 且 power≥4 | wisdom+1 | health-2 |
| 3004 | 迎着清霜，看着明月，路过双叉岭，忽见一彪悍虎精，身着锁甲，爪子沾血，目放凶光，你会_ | 4. 和虎精套近乎，见机行事 | charm≥5 且 luck≥4 | charm+1 | health-1,charm-1 |

| 3005 | 在山崖上遇到一名仙风道骨的老者正在打坐，你将会_ | 1. 盘膝在一旁打坐 | health≥1 | wisdom+1 | 无 |
| 3005 | 在山崖上遇到一名仙风道骨的老者正在打坐，你将会_ | 2. 二话不说，上去给他一拳 | power≥7 | power+1 | health-1 |
| 3005 | 在山崖上遇到一名仙风道骨的老者正在打坐，你将会_ | 3. 唤醒老者，询问如何下山 | health≥1 | smart+1 | 无 |
| 3005 | 在山崖上遇到一名仙风道骨的老者正在打坐，你将会_ | 4. 什么也不做，悄悄离去 | health≥1 | luck+1 | 无 |

| 3006 | 来到天庭，正逢蟠桃大会前夕，七仙女进蟠桃园采摘仙桃。你将会_ | 1. 帮七仙女一起摘仙桃 | charm≥6 | charm+2 | 无 |
| 3006 | 来到天庭，正逢蟠桃大会前夕，七仙女进蟠桃园采摘仙桃。你将会_ | 2. 调戏一下 | health≥99 | 无 | health-1 |
| 3006 | 来到天庭，正逢蟠桃大会前夕，七仙女进蟠桃园采摘仙桃。你将会_ | 3. 问问蟠桃大会有没请我 | luck≥6 | 无 | 无 |
| 3006 | 来到天庭，正逢蟠桃大会前夕，七仙女进蟠桃园采摘仙桃。你将会_ | 4. 偷个桃吃 | health≥99 | 无 | health-1 |

| 3007 | 时光荏苒，岁月如梭。菩萨见人间疾苦，特在须弥山化腐朽为神奇，造下时光之舟，你会_ | 1. 跟船长讨要时光之礼 | charm≥7 | power+2 | power+1 |
| 3007 | 时光荏苒，岁月如梭。菩萨见人间疾苦，特在须弥山化腐朽为神奇，造下时光之舟，你会_ | 2. 时光重现，再次体验曾经的辉煌战斗 | power≥7 | power+1,wisdom+1 | wisdom+1 |
| 3007 | 时光荏苒，岁月如梭。菩萨见人间疾苦，特在须弥山化腐朽为神奇，造下时光之舟，你会_ | 3. 在时光商店购买物品 | luck≥6 | luck+1 | 无 |
| 3007 | 时光荏苒，岁月如梭。菩萨见人间疾苦，特在须弥山化腐朽为神奇，造下时光之舟，你会_ | 4. 观察时光之舟 | wisdom≥6 | wisdom+1 | 无 |

| 3008 | 你来到须弥山，看到一个幼童手中的气球飞走了，嚎嚎大哭起来。你会_ | 1. 翻个跟头拿走气球，占为己有 | health≥99 | 无 | health-1,charm-1 |
| 3008 | 你来到须弥山，看到一个幼童手中的气球飞走了，嚎嚎大哭起来。你会_ | 2. 帮幼童取回气球 | smart≥6 | charm+1,luck+1 | smart-1 |
| 3008 | 你来到须弥山，看到一个幼童手中的气球飞走了，嚎嚎大哭起来。你会_ | 3. 做鬼脸哄哄幼童 | charm≥5 | charm+1 | charm-1 |
| 3008 | 你来到须弥山，看到一个幼童手中的气球飞走了，嚎嚎大哭起来。你会_ | 4. 视而不见 | luck≥5 | charm-1 | health-1 |

| 3009 | 在联盟集会所前遇到观音菩萨，她邀请你加入联盟阵营。你决定加入_ | 1. 加入青龙阵营 | luck≥6 | luck+1 | 无 |
| 3009 | 在联盟集会所前遇到观音菩萨，她邀请你加入联盟阵营。你决定加入_ | 2. 加入白虎阵营 | power≥6 | power+1 | 无 |
| 3009 | 在联盟集会所前遇到观音菩萨，她邀请你加入联盟阵营。你决定加入_ | 3. 加入朱雀阵营 | smart≥6 | smart+1 | 无 |
| 3009 | 在联盟集会所前遇到观音菩萨，她邀请你加入联盟阵营。你决定加入_ | 4. 加入玄武阵营 | health≥6 | health+1 | 无 |

| 3010 | 途经锦绣峰，原本风光秀丽的景色被通天巨树遮掩，你会 | 1. 此树必有妖异，钻进树洞查看 | luck≥6 | health+1 | charm-1 |
| 3010 | 途经锦绣峰，原本风光秀丽的景色被通天巨树遮掩，你会 | 2. 爬上树梢看风景 | smart≥6 | charm-1 | health-1,smart-1 |
| 3010 | 途经锦绣峰，原本风光秀丽的景色被通天巨树遮掩，你会 | 3. 骑上危月燕飞到树顶，和芙蓉仙子对决 | power≥6 | charm+1 | health-1,power-1 |
| 3010 | 途经锦绣峰，原本风光秀丽的景色被通天巨树遮掩，你会 | 4. 千年巨树，必然成精，和巨树聊天 | charm≥6 | wisdom+1 | health-1 |

| 3011 | 听闻须弥山中有一座罗汉堂，内有十八座罗汉，你会_ | 1. 挑战托塔罗汉 | power≥5 且 wisdom≥4 | charm+1 | health-1 |
| 3011 | 听闻须弥山中有一座罗汉堂，内有十八座罗汉，你会_ | 2. 在罗汉堂中打坐 | wisdom≥6 | health+1,wisdom+1 | health+1 |
| 3011 | 听闻须弥山中有一座罗汉堂，内有十八座罗汉，你会_ | 3. 在罗汉雕像前跪拜 | luck≥6 | luck+1 | health-1 |
| 3011 | 听闻须弥山中有一座罗汉堂，内有十八座罗汉，你会_ | 4. 拜欢喜罗汉为师 | charm≥6 | power+1 | charm-1 |

| 3012 | 深夜， 你路过一间关着门的老旧的破庙，你会_ | 1. 用力踹门而入 | luck≥5 | health-1,power-1 | health-1,smart-1 |
| 3012 | 深夜， 你路过一间关着门的老旧的破庙，你会_ | 2. 轻声敲门，请求借住一宿 | wisdom≥6 | wisdom+1 | 无 |
| 3012 | 深夜， 你路过一间关着门的老旧的破庙，你会_ | 3. 嗅一嗅是否有妖气 | health≥5 | health-1 | health-1,power-1,smart-1 |
| 3012 | 深夜， 你路过一间关着门的老旧的破庙，你会_ | 4. 破庙有鬼，先跑为妙 | smart≥5 | wisdom+1 | smart-1 |

| 3013 | 来到平安村，只见有一小童被关在铁笼中，有一鱼精看守，你会_ | 1. 拿起兵器决战斑衣鳜婆，解救小童 | power≥6 | charm+1,health+1 | health-2 |
| 3013 | 来到平安村，只见有一小童被关在铁笼中，有一鱼精看守，你会_ | 2. 趁斑衣鳜婆睡觉时，偷偷救出小童 | smart≥6 | smart+1 | health-1,smart-1 |
| 3013 | 来到平安村，只见有一小童被关在铁笼中，有一鱼精看守，你会_ | 3. 和斑衣鳜婆搭讪，让她放了小童 | charm≥6 | power+1 | health-1,charm-1 |
| 3013 | 来到平安村，只见有一小童被关在铁笼中，有一鱼精看守，你会_ | 4. 不管他，离开平安村 | luck≥5 | luck+1,charm-1 | health-1 |

| 3014 | 来到兜率宫，见到炉中正在炼丹，你会_ | 1. 赶走童子，打开炼丹炉，服用仙丹 | power≥5 且 luck≥5 | power+1,health+1 | health-1 |
| 3014 | 来到兜率宫，见到炉中正在炼丹，你会_ | 2. 帮童子炼丹 | charm≥6 | power+1,health+1 | 无 |
| 3014 | 来到兜率宫，见到炉中正在炼丹，你会_ | 3. 跳入炼丹炉中 | smart≥5 且 luck≥5 | power+1,smart+1 | health-1,smart-1 |
| 3014 | 来到兜率宫，见到炉中正在炼丹，你会_ | 4. 一脚踢翻炼丹炉 | health≥99 | luck+1,charm-1 | charm-2 |

| 3015 | 你在和伙伴们协力攻打凶兽涛杌时遇到有人利用邪恶的力量——外挂（非法辅助）抢走击败奖励，你会_ | 1. 找到证据，并向群主（GM）举报 | health≥1 | power+1,wisdom+1 | 无 |
| 3015 | 你在和伙伴们协力攻打凶兽涛杌时遇到有人利用邪恶的力量——外挂（非法辅助）抢走击败奖励，你会_ | 2. 联系盟主，将开外挂的人踢出联盟 | health≥1 | charm+1,wisdom+1 | 无 |
| 3015 | 你在和伙伴们协力攻打凶兽涛杌时遇到有人利用邪恶的力量——外挂（非法辅助）抢走击败奖励，你会_ | 3. 为了击败奖励，我也来用外挂 | health≥99 | 无 | health-9,charm-9 |
| 3015 | 你在和伙伴们协力攻打凶兽涛杌时遇到有人利用邪恶的力量——外挂（非法辅助）抢走击败奖励，你会_ | 4. 什么也不做，自个生闷气 | health≥99 | 无 | health-1,wisdom-1 |

## 4xxx 阶段（第4天·强敌 | 成功积分12 / 失败积分6）

| ID | 题目 | 选项 | 判定条件(达标=答对) | 答对加成 | 答错惩罚 |
|----|------|------|--------------------|----------|----------|
| 4001 | 观音正在阻止通天教主释放十二祖巫，你加入任何一方都将直接影响结局。你会_ | 1. 与观音合作，阻止十二祖巫被释放，维护世界和平 | power≥9 | charm+2 | health-2 |
| 4001 | 观音正在阻止通天教主释放十二祖巫，你加入任何一方都将直接影响结局。你会_ | 2. 与通天教主合作，释放十二祖巫，制造洪荒大劫，好浑水摸鱼 | charm≥8 且 power≥6 | smart+2,charm-1 | health-1,charm-1 |
| 4001 | 观音正在阻止通天教主释放十二祖巫，你加入任何一方都将直接影响结局。你会_ | 3. 谁给的好处多，就跟谁合作 | wisdom≥8 且 power≥6 | power+2,charm-1 | health-2,charm-2 |
| 4001 | 观音正在阻止通天教主释放十二祖巫，你加入任何一方都将直接影响结局。你会_ | 4. 只是路过，打个酱油 | smart≥8 且 luck≥6 | health-1,smart+1 | health-2 |

| 4002 | 在阻止通天教主释放十二祖巫过程中，师徒几人走散了，唐僧受了伤，寻求你的帮助。你会_ | 1. 送唐僧去看大夫 | charm≥8 | luck+1 | health-1 |
| 4002 | 在阻止通天教主释放十二祖巫过程中，师徒几人走散了，唐僧受了伤，寻求你的帮助。你会_ | 2. 替唐僧去寻找他的徒弟 | smart≥9 | power+1,smart+1 | health-2 |
| 4002 | 在阻止通天教主释放十二祖巫过程中，师徒几人走散了，唐僧受了伤，寻求你的帮助。你会_ | 3. 把唐僧的行踪情报卖给通天教主 | wisdom≥8 | power+1,charm-1 | health-1 |
| 4002 | 在阻止通天教主释放十二祖巫过程中，师徒几人走散了，唐僧受了伤，寻求你的帮助。你会_ | 4. 把唐僧赶走 | health≥99 | 无 | health-1 |

| 4003 | 初到琉璃宫中，不见前路，却有妖怪腾空走动，你会_ | 1. 观察妖怪走动路线，谨慎跟上 | smart≥8 且 wisdom≥6 | wisdom+1,smart+1 | health-1 |
| 4003 | 初到琉璃宫中，不见前路，却有妖怪腾空走动，你会_ | 2. 勇往直前，无畏无惧 | luck≥9 | luck+1 | health-2 |
| 4003 | 初到琉璃宫中，不见前路，却有妖怪腾空走动，你会_ | 3. 此处无路，另寻他法 | wisdom≥8 且 smart≥6 | wisdom+1,smart-1 | health-1 |
| 4003 | 初到琉璃宫中，不见前路，却有妖怪腾空走动，你会_ | 4. 上前与妖怪大战三百回合 | power≥8 | health-1,power+1 | health-1 |

| 4004 | 在林间小路上遇到一只哮天犬，你会_ | 1. 踹它一脚 | health≥99 | 无 | health-1,smart-1 |
| 4004 | 在林间小路上遇到一只哮天犬，你会_ | 2. 帮它寻找主人二郎神 | smart≥8 | smart+1 | wisdom-1 |
| 4004 | 在林间小路上遇到一只哮天犬，你会_ | 3. 给它一根肉骨头 | charm≥8 | charm+1,power+1 | charm-1 |
| 4004 | 在林间小路上遇到一只哮天犬，你会_ | 4. 不管它 | luck≥8 | health+1 | charm-1 |

| 4005 | 无意发现一处修炼佳境--螺旋地狱，你会_ | 1. 实力总是在不断的战斗中获得提升，毅然进入 | power≥9 | power+1,wisdom+1 | health-2,power+1 |
| 4005 | 无意发现一处修炼佳境--螺旋地狱，你会_ | 2. 此处血气浓郁，阴森可怖，不宜久留，撤！ | smart≥8 | smart+1 | health-1,smart-1 |
| 4005 | 无意发现一处修炼佳境--螺旋地狱，你会_ | 3. 五毒罗盘似有异象，上前研究 | luck≥7 且 wisdom≥6 | health+1,wisdom+1 | 无 |
| 4005 | 无意发现一处修炼佳境--螺旋地狱，你会_ | 4. 拜五毒阎罗为师，学习各种技艺 | charm≥9 | power+1,wisdom+1,smart+1,charm+1 | health-2 |

| 4006 | 下山途中，你遇到一名纹丝不动的老者独自坐在一副棋盘前，你会_ | 1. 坐下来和他对弈 | wisdom≥9 | power+1,wisdom+1 | charm-1 |
| 4006 | 下山途中，你遇到一名纹丝不动的老者独自坐在一副棋盘前，你会_ | 2. 拍一拍他的肩膀看看是不是还活着 | power≥8 | charm+1 | health-1 |
| 4006 | 下山途中，你遇到一名纹丝不动的老者独自坐在一副棋盘前，你会_ | 3. 寻找一位能和他对弈的棋手 | smart≥8 | charm+1 | 无 |
| 4006 | 下山途中，你遇到一名纹丝不动的老者独自坐在一副棋盘前，你会_ | 4. 随便挪动一颗棋子 | luck≥9 | power+1,wisdom+1 | health-1 |

| 4007 | 机缘巧合来到幻镜阁，发现百眼魔君以八卦为阵，布下幻镜迷宫，拦住去路，你会_ | 1. 勇闯幻境阁，决战百眼魔君 | power≥9 | power+1 | health-1 |
| 4007 | 机缘巧合来到幻镜阁，发现百眼魔君以八卦为阵，布下幻镜迷宫，拦住去路，你会_ | 2. 上前研究，揣摩八卦阵 | wisdom≥8 | wisdom+1 | health-1,charm-1 |
| 4007 | 机缘巧合来到幻镜阁，发现百眼魔君以八卦为阵，布下幻镜迷宫，拦住去路，你会_ | 3. 在八卦阵内四处转悠 | luck≥8 | luck+1 | health-2 |
| 4007 | 机缘巧合来到幻镜阁，发现百眼魔君以八卦为阵，布下幻镜迷宫，拦住去路，你会_ | 4. 说服百眼魔君，要求放行 | charm≥9 | charm+1 | smart-1 |

## 5xxx 阶段（第5-7天·终章 | 成功积分19 / 失败积分9（答对无属性加成，答错一律health-3））

| ID | 题目 | 选项 | 判定条件(达标=答对) | 答对加成 | 答错惩罚 |
|----|------|------|--------------------|----------|----------|
| 5001 | 你来到了碧游宫。看见了通天教主。教主说："你是谁，想不想跟我一样获得通天的法力？你会_ | 1. 果断拒绝，并拿起武器与通天教主大战三百回合 | power≥10 | 无 | health-3 |
| 5001 | 你来到了碧游宫。看见了通天教主。教主说："你是谁，想不想跟我一样获得通天的法力？你会_ | 2. 叩头拜师，向通天教主学习绝世魔功 | power≥7 且 wisdom≥9 | 无 | health-3 |
| 5001 | 你来到了碧游宫。看见了通天教主。教主说："你是谁，想不想跟我一样获得通天的法力？你会_ | 3. 假装同意，趁机偷袭 | wisdom≥9 且 luck≥7 | 无 | health-3 |
| 5001 | 你来到了碧游宫。看见了通天教主。教主说："你是谁，想不想跟我一样获得通天的法力？你会_ | 4. 拒绝合作，掉头就离开 | smart≥9 且 wisdom≥7 | 无 | health-3 |

| 5002 | 你所在的未央宫即将崩塌，前方金光灿灿的怪物正是金之祖巫。接下来，你会_ | 1. 勇闯未央宫，决战金之祖巫 | power≥10 | 无 | health-3 |
| 5002 | 你所在的未央宫即将崩塌，前方金光灿灿的怪物正是金之祖巫。接下来，你会_ | 2. 土豪爷爷，我要跟你做朋友 | charm≥10 | 无 | health-3 |
| 5002 | 你所在的未央宫即将崩塌，前方金光灿灿的怪物正是金之祖巫。接下来，你会_ | 3. 将金之祖巫引到玄武门 | smart≥9 且 wisdom≥7 | 无 | health-3 |
| 5002 | 你所在的未央宫即将崩塌，前方金光灿灿的怪物正是金之祖巫。接下来，你会_ | 4. 溜之大吉 | smart≥9 且 luck≥7 | 无 | health-3 |

| 5003 | 木之祖巫的藤蔓爬满了神光金岭，最后一座宝塔摇摇欲坠。你会_ | 1. 火烧神光金岭，灭掉木之祖巫 | wisdom≥9 且 luck≥7 | 无 | health-3 |
| 5003 | 木之祖巫的藤蔓爬满了神光金岭，最后一座宝塔摇摇欲坠。你会_ | 2. 登至塔顶，决战木之祖巫 | power≥9 且 smart≥7 | 无 | health-3 |
| 5003 | 木之祖巫的藤蔓爬满了神光金岭，最后一座宝塔摇摇欲坠。你会_ | 3. 等木之祖巫离开，修葺破损的寺庙与宝塔 | health≥99 | 无 | health-3 |
| 5003 | 木之祖巫的藤蔓爬满了神光金岭，最后一座宝塔摇摇欲坠。你会_ | 4. 吃个桃，压压惊 | health≥99 | 无 | health-3 |

| 5004 | 经过普陀山脚，发现湖中央的漩涡底下，正是法华灵洞。接下来，你会_ | 1. 乘船去湖中心一探究竟 | luck≥8 且 smart≥8 | 无 | health-3 |
| 5004 | 经过普陀山脚，发现湖中央的漩涡底下，正是法华灵洞。接下来，你会_ | 2. 潜入湖底，决战水之祖巫 | power≥10 | 无 | health-3 |
| 5004 | 经过普陀山脚，发现湖中央的漩涡底下，正是法华灵洞。接下来，你会_ | 3. 大喊大叫，把怪物引出来 | power≥7 且 wisdom≥9 | 无 | health-3 |
| 5004 | 经过普陀山脚，发现湖中央的漩涡底下，正是法华灵洞。接下来，你会_ | 4. 找东海龙宫的伙伴来帮忙 | charm≥10 | 无 | health-3 |

| 5005 | 看到金顶云海正被火之祖巫吞噬，沦为一片火海。你会_ | 1. 赶紧灭火 | charm≥9 且 smart≥7 | 无 | health-3 |
| 5005 | 看到金顶云海正被火之祖巫吞噬，沦为一片火海。你会_ | 2. 逃之夭夭 | smart≥10 | 无 | health-3 |
| 5005 | 看到金顶云海正被火之祖巫吞噬，沦为一片火海。你会_ | 3. 隔岸观火 | wisdom≥10 | 无 | health-3 |
| 5005 | 看到金顶云海正被火之祖巫吞噬，沦为一片火海。你会_ | 4. 冲入火海，决战火之祖巫 | power≥10 | 无 | health-3 |
"""


# ==================== 2. 解析器 ====================
def parse_condition(cond_str: str):
    """解析条件如 'power≥4' 或 'wisdom≥4 且 power≥3'，返回 [(attr, op, val), ...]"""
    if not cond_str or cond_str.strip() == "":
        return []
    # 替换符号
    s = cond_str.replace("≥", ">=").replace("≤", "<=").replace("且", " and ")
    # 按 and 分割
    parts = s.split(" and ")
    conds = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # 匹配 attr op val
        m = re.match(r"(\w+)\s*(>=|<=|>|<)\s*(\d+)", p)
        if m:
            attr, op, val = m.groups()
            conds.append((attr, op, int(val)))
    return conds


def parse_effect(eff_str: str):
    """解析效果如 'power+1' 或 'health-1,power+2'，返回 dict"""
    if not eff_str or eff_str.strip() == "" or eff_str.strip() == "无":
        return {}
    eff = {}
    for part in eff_str.split(","):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(\w+)([+-])(\d+)", part)
        if m:
            attr, op, val = m.groups()
            delta = int(val) if op == "+" else -int(val)
            eff[attr] = eff.get(attr, 0) + delta
    return eff


def parse_markdown(md: str) -> Dict[str, List[Dict]]:
    """解析 Markdown 题库，返回 {question_id: [option1, option2, ...]}"""
    lines = md.splitlines()
    question_db = {}
    current_phase = None
    succ_score = 0
    fail_score = 0

    # 先找阶段积分
    for line in lines:
        if "## " in line and "xxx" in line:
            # 例如 "## 1xxx 阶段（第1天·准备 | 成功积分6 / 失败积分3）"
            m = re.search(r"成功积分(\d+).*失败积分(\d+)", line)
            if m:
                succ_score = int(m.group(1))
                fail_score = int(m.group(2))

        # 匹配表格行
        # 格式: | 1001 | 题目... | 1. 选项... | power≥4 | power+1 | health-1 |
        m = re.match(
            r"^\|\s*(\d{4})\s*\|\s*.*?\s*\|\s*(\d+)\.\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|$",
            line,
        )
        if m:
            q_id, opt_idx, opt_text, cond_str, succ_eff, fail_eff = m.groups()
            # 阶段积分由 q_id 开头决定，优先用匹配的，如果没匹配到则用 current_phase
            # 更精确：根据 q_id 首字符设置
            first_char = q_id[0]
            if first_char == "1" or first_char == "2":
                s_score, f_score = 6, 3
            elif first_char == "3":
                s_score, f_score = 9, 4
            elif first_char == "4":
                s_score, f_score = 12, 6
            elif first_char == "5":
                s_score, f_score = 19, 9
            else:
                s_score, f_score = succ_score, fail_score

            conds = parse_condition(cond_str)
            succ_eff_dict = parse_effect(succ_eff)
            fail_eff_dict = parse_effect(fail_eff)

            opt = {
                "opt_idx": int(opt_idx),
                "text": opt_text.strip(),
                "cond": conds,
                "succ_eff": succ_eff_dict,
                "fail_eff": fail_eff_dict,
                "succ_score": s_score,
                "fail_score": f_score,
            }
            if q_id not in question_db:
                question_db[q_id] = []
            question_db[q_id].append(opt)

    return question_db


# ==================== 3. 核心求解器 ====================
class Solver:
    def __init__(self, question_db: Dict[str, List[Dict]]):
        self.db = question_db
        self.attr_names = ["health", "power", "wisdom", "charm", "luck", "smart"]

    def check_condition(self, conds: List[Tuple[str, str, int]], state: Dict[str, int]) -> bool:
        for attr, op, val in conds:
            cur = state.get(attr, 0)
            if op == ">=" and cur < val:
                return False
            elif op == "<=" and cur > val:
                return False
            elif op == ">" and cur <= val:
                return False
            elif op == "<" and cur >= val:
                return False
        return True

    def apply_effect(self, state: Dict[str, int], eff: Dict[str, int]) -> Dict[str, int]:
        new_state = state.copy()
        for k, v in eff.items():
            new_state[k] = new_state.get(k, 0) + v
        return new_state

    def solve(self, initial: Dict[str, int], question_ids: List[str], survive_questions: int = 9):
        """
        survive_questions: 前N题不死的路径优先（默认前9题）；若所有路径前N题内都死，也输出死亡前最高分。
        返回 (max_score, detailed_path, died_early)
          died_early=True 表示最优路径在前 survive_questions 题内就死亡了。
        """
        if initial.get("health", 0) <= 0:
            print("【警告】初始 health <= 0，角色已死亡，无法求解。")
            return -float("inf"), [], True

        init_tuple = tuple(initial.get(attr, 0) for attr in self.attr_names)

        @lru_cache(None)
        def dfs(idx: int, state_tuple: Tuple[int, ...]):
            """
            返回 (得分, 是否在前N题内死亡, 路径元组)
            比较优先级：前N题不死 > 得分高
            """
            if idx >= len(question_ids):
                return 0, False, ()

            current_state = dict(zip(self.attr_names, state_tuple))
            q_id = question_ids[idx]
            options = self.db.get(q_id, [])
            best = None  # (score, died_early, path)

            for opt in options:
                is_success = self.check_condition(opt["cond"], current_state)
                if is_success:
                    gain = opt["succ_score"]
                    eff = opt["succ_eff"]
                    result = "成功"
                else:
                    gain = opt["fail_score"]
                    eff = opt["fail_eff"]
                    result = "失败"

                new_state = self.apply_effect(current_state, eff)
                new_tuple = tuple(new_state.get(attr, 0) for attr in self.attr_names)
                died = new_state.get("health", 0) <= 0

                if died:
                    # 死亡：路径在此终止，当前题得分照算
                    total = gain
                    died_early = idx < survive_questions
                    this_path = ((opt["opt_idx"], result, gain, new_tuple),)
                else:
                    sub_score, sub_died, sub_path = dfs(idx + 1, new_tuple)
                    total = gain + sub_score
                    died_early = sub_died
                    this_path = ((opt["opt_idx"], result, gain, new_tuple),) + sub_path

                candidate = (total, died_early, this_path)
                # 比较规则：前N题不死的优先；同为死/同为不死，则比总分
                if best is None:
                    best = candidate
                else:
                    best_not_died = not best[1]
                    cand_not_died = not candidate[1]
                    if cand_not_died and not best_not_died:
                        best = candidate
                    elif cand_not_died == best_not_died and candidate[0] > best[0]:
                        best = candidate

            return best

        max_score, died_early, path = dfs(0, init_tuple)

        # 解码路径（path 可能短于 question_ids，说明中途死亡了）
        detailed_path = []
        state = initial.copy()
        for step, (q_id, (opt_idx, result, gain, new_tuple)) in enumerate(zip(question_ids, path)):
            opts = self.db.get(q_id, [])
            opt_text = ""
            for o in opts:
                if o["opt_idx"] == opt_idx:
                    opt_text = o["text"]
                    break

            state_after = dict(zip(self.attr_names, new_tuple))
            step_died = state_after.get("health", 0) <= 0

            detailed_path.append(
                {
                    "step": step + 1,
                    "q_id": q_id,
                    "opt_idx": opt_idx,
                    "opt_text": opt_text,
                    "result": result,
                    "gain": gain,
                    "state_before": state.copy(),
                    "state_after": state_after.copy(),
                    "died": step_died,
                }
            )
            if step_died:
                break
            state = state_after

        return max_score, detailed_path, died_early


# ==================== 4. 运行入口 ====================
if __name__ == "__main__":
    # 解析题库
    db = parse_markdown(MARKDOWN_CONTENT)

    # ---- 在这里换你的初始属性和题目序列 ----
    #  ---初始属性需要去主文件（版本号.swf）里获取，需要去modules.question.model文件夹里的QuesModelManager.as里的函数“initDate(param1:Object) :void"的开头增加”
	#---{ExternalInterface.call("console.log","===== 生存大冒险初始化 =====");}
        #---{ ExternalInterface.call("console.log","day=" + param1.day);}
        #---{ ExternalInterface.call("console.log","survivalAttr=" + JSON.stringify(param1.survivalAttr));}
       #---{  ExternalInterface.call("console.log","survivalInfo=" + JSON.stringify(param1.survivalInfo));}“
  #  ----ps:如果FFDEC忘了给你加头文件”import flash.external.ExternalInterface;“，记得自己手动补上去-----
   # ----- 真实初始属性 顺序：health, power, wisdom, charm, luck, smart -----
    role_attr_map = {
        # A 小唐
        "A": {"health":3, "power":4, "wisdom":5, "charm":5, "luck":4, "smart":3},
        # B 小猴
        "B": {"health":4, "power":5, "wisdom":4, "charm":3, "luck":4, "smart":4},
        # C 小猪
        "C": {"health":6, "power":4, "wisdom":3, "charm":3, "luck":3, "smart":3},
        # D 小沙
        "D": {"health":3, "power":3, "wisdom":4, "charm":3, "luck":3, "smart":6},
        # E 小白
        "E": {"health":4, "power":3, "wisdom":4, "charm":4, "luck":5, "smart":4},
        # F 小玉
        "F": {"health":3, "power":3, "wisdom":4, "charm":5, "luck":3, "smart":6},
        # G 小吒
        "G": {"health":5, "power":4, "wisdom":4, "charm":4, "luck":3, "smart":4},
    }

   # 中文名 -> 代号 反向映射
    name_to_code = {
        "小唐":"A", "小猴":"B", "小猪":"C",
        "小沙":"D", "小白":"E", "小玉":"F", "小吒":"G",
    }

    # ---------- 控制台输入角色 ----------
    while True:
        raw = input("请输入角色（代号A-G 或 中文名，ABCDEFG依次叫 小唐 小猴 小猪 小沙 小白 小玉 小吒）: ").strip()
        # 先按代号匹配
        if raw.upper() in role_attr_map:
            select_role = raw.upper()
            break
        # 再按中文名匹配
        if raw in name_to_code:
            select_role = name_to_code[raw]
            break
        print(f"输入无效！可用代号：A/B/C/D/E/F/G，可用中文名：{','.join(name_to_code.keys())}")

    initial_attrs = role_attr_map[select_role]
    role_name = {v:k for k,v in name_to_code.items()}[select_role]

    # ---------- 控制台输入题目序列 ----------
    while True:
        raw_ids = input('请输入题目ID序列，用逗号分隔（如 1001,2005,2003）: ').strip()
        # 支持中英文逗号、引号、空格
        raw_ids = raw_ids.replace('"', '').replace("'", '').replace('，', ',').replace(' ', '')
        question_ids = [x for x in raw_ids.split(',') if x]
        # 校验每个ID是否在题库中
        invalid = [qid for qid in question_ids if qid not in db]
        if invalid:
            print(f"以下题目ID不在题库中：{invalid}，请重新输入")
            continue
        if len(question_ids) == 0:
            print("未输入任何题目ID，请重新输入")
            continue
        break

         # 求解（前9题不死优先；做不到也输出死亡前最高分）
    solver = Solver(db)
    max_score, path, died_early = solver.solve(initial_attrs, question_ids, survive_questions=9)

    if not path:
        print(f"\n选中角色：{select_role} - {role_name}，题目数：{len(question_ids)}")
        print("结果：初始状态已死亡，无法求解。")
    else:
        died_step = next((s["step"] for s in path if s["died"]), None)
        total_steps = len(path)
        if died_step:
            status = f"第{died_step}题后死亡（共存活{total_steps}题）"
        else:
            status = f"全程存活（共{total_steps}题）"

        early_warn = "  ⚠ 注意：最优路径在前9题内就死亡了，已为你取死亡前最高分。" if died_early else ""

        print(f"\n选中角色：{select_role} - {role_name}，题目数：{len(question_ids)}，最大总分: {max_score}{early_warn}")
        print(f"存活状态：{status}")
        print("=" * 60)
        for step_info in path:
            state = step_info["state_before"]
            state_str = ", ".join(f"{k}={v}" for k, v in state.items())
            death_mark = " 【角色死亡，冒险结束】" if step_info["died"] else ""
            print(
                f"第{step_info['step']}题 (ID:{step_info['q_id']}) 选 选项{step_info['opt_idx']}: {step_info['opt_text']}{death_mark}"
            )
            print(f"  当前属性: {state_str}")
            print(f"  判定结果: {step_info['result']}，本轮得分: {step_info['gain']}")
            print("-" * 40)

