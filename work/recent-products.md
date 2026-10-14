# 较新 AI 定线案例核验简记

核验日期：2026-09-13。公共只读检索与源码阅读；未部署、运行模型或实攀。Foltyn 2026 论文由其他子任务单独核验。本简记用于主文档整合，不是用户交付。

## 1. BetaZero：最值得新增的跨墙生成工程案例

- [仓库](https://github.com/EvanMcCormick37/ml-homewall-climb-generator)，[免费在线应用](https://betazero.live)，[作者 2026-02-12 技术复盘](https://evmojo37.substack.com/p/betazero-v2-a-diffusion-model-for)。读取时 main 为 `6f0acb414a5f1ab070aa62d02ac98f2602011821`，提交时间 2026-05-14。
- 范围是**现存岩点中选点**：用户上传喷点墙图片，标记岩点，生成和人工修改候选；也支持标准板。没有从库存自由选取岩点并输出新安装位置/朝向的证据。
- 作者复盘：原先用 30 条实攀线加 40 条未试攀构想训练 LSTM，重复点、绕路和多样性差；后来通过 BoardLib 获得 20 万+ TB2/Kilter 路线，用条件 U-Net DDPM 学习岩点集合，避免依赖未标注的动作顺序。投影需要融入去噪过程，最后一步才强行吸附效果差。该部分是作者经验，不是对照实验结论。
- **以当前源码为准，根目录架构文档已滞后。** 当前 [ddpm_model.py](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/app/services/utils/ddpm_model.py) 使用 1D 卷积 U-Net、残差相加 skip、条件嵌入、classifier-free guidance。生成张量为 20 个槽位，每槽 7 个岩点属性加 5 个角色/空位通道；属性为位置 x/y、受 useability 缩放的 pull_x/pull_y、is_foot、pinch、flat。条件是 grade、quality、ascents、angle；当前用户生成把后两项分别固定为 3.0、1000，主要开放等级和角度。
- 当前 [generation_utils.py](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/app/services/utils/generation_utils.py) 已按手点/脚点采用不同属性距离权重投影，**不能写成仍然只按几何距离投影**。还有 evolutionary diffusion：每步每组生成多个候选，留下平均最近属性距离最低者，再复制加噪；末尾去重、补起终点。这是与目标墙匹配的搜索，不是可达性、难度或好玩程度的评估器。
- [预处理代码](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/model-training/boardlib_preprocessing.py) 含利用历史路线等级推导单点 useability、用手脚使用次数推导 is_foot 的弱标签逻辑，也允许默认/人工属性。不能把这些描述成经过标定的抓握力或真实物理模型。
- 可复用资产：MIT 全栈应用、点位编辑/数据结构、BoardLib 导入、条件扩散与投影代码、训练探索 notebooks、SQLite、Docker。Git tree 确认主 DDPM 权重 87,027,568 字节及 scaler 文件在库中；未下载执行权重。训练 notebooks 是探索记录，不能承诺一键复现论文级结果。
- 缺失：未找到跨墙独立测试集、真人盲测统计、等级误差、身体尺寸泛化、安全评测。2 月作者已承认 jug 可能误映射为脚点；当前属性投影是在解决该问题，但没有公开量化证据说明解决程度。最可学的是**标准板预训练 → 目标墙属性约束 → 候选池 → 人工筛选与修改**，不能当成通用定线已成熟。

## 2. ClimbingBoardGPT：小模型及评测脚手架

- [仓库与结果](https://github.com/psark007/ClimbingBoardGPT)，当前 main `adfcf3622a8701f6336746d1c0210d5518882a97`，2026-07-21。固定 TB2 12×12 mirror 与 Kilter 16×12 original；同样是在既有点位中选点。
- 约 141 万参数 decoder-only Transformer 生成路线，约 117 万参数 encoder 预测等级；按板、角度、等级、带角色的岩点 ID token 建模。岩点按角色和坐标规范排序，[源码明确](https://github.com/psark007/ClimbingBoardGPT/blob/main/src/climbingboardgpt/tokenization.py)这是序列表示，并非攀爬动作顺序。
- README 训练/验证/测试合计为 256,831 / 31,985 / 32,269 **路线–角度样本**；不是同数量独立路线。当前 [划分脚本](https://github.com/psark007/ClimbingBoardGPT/blob/main/scripts/01_tokenize_routes.py) 按 `(board_key, uuid)` 分组，避免同一路线不同角度跨训练与测试，不能指控它采用随机行拆分泄漏。
- 作者报告每板 200 条生成候选，TB2/Kilter 结构有效率 91.5%/86.0%；请求等级在 critic ±1 V 内占 73.0%/79.5%。[评测脚本](https://github.com/psark007/ClimbingBoardGPT/blob/main/scripts/04_evaluate_generated_routes.py)确认前者仅为起终点、单板、点数、无重复等检查；后者来自训练的等级模型，不是实攀验证。Jaccard 新颖性也不等于动作新颖或有趣。
- 可复用 MIT 的数据规范化、分组划分、tokenizer、训练脚本、生成、结构/新颖性/critic 排序、UI；原始数据库与训练权重不在 Git。没有公开真人生成线质量盲测。适合作为 baseline 与实验脚手架，不能把高结构有效率说成高质量定线成功率。

## 3. Doom Climb：轻量模型进真实消费应用

- [App Store](https://apps.apple.com/us/app/doom-climb/id6761698469)，[开发者发布与答疑](https://www.reddit.com/r/kilterboard/comments/1u0qydv/upgraded_kilter_app/)。2026 年应用。端侧 Core ML 生成、编辑、蓝牙点灯、训练记录、无需账户；免费。当前美国商店只有 1 个评分，不足以证明大规模采用。
- 作者解释通过 BoardLib 获得约 13 万条 Kilter 数据，按最低评分和完攀人数筛到约 6 万，在笔记本用 PyTorch 训练，在手机本地运行。**精确网络架构、参数、数据切分和质量基准未披露**；可靠写法是端侧神经网络，不把未核实的 GPT 架构当事实。
- 作者公开点名 [BoardLib](https://github.com/lemeryfertitta/BoardLib)、[hangtime-grip-connect](https://github.com/Stevie-Ray/hangtime-grip-connect)、[fake_kilter_board](https://github.com/1-max-1/fake_kilter_board) 为数据和蓝牙开发参考；这些才是可复用公开工程资产，Doom Climb 本身没有找到模型源码。
- 有真实用户反馈 8×12 家用板显示点位与点灯不一致，作者承认发布讨论当时仅标准 12×12 commercial Kilter 完全正确。只能据此认定当时的适配缺陷，不能假定截至今天仍未修复；也没有独立高质量路线成功率。它证明的是从生成到手机/实体板闭环可做，并提示布局与 LED 映射需要单独验收。

## 对战略文档的影响

1. 应把较新一代的路径具体化：小型领域 Transformer、连续条件扩散加属性投影、端侧推理与蓝牙闭环。它们已有可读代码或真实上架应用，早年算法不足以代表现状。
2. BetaZero 提供了固定板数据迁移到新喷点墙的现实起点；它仍然选择既有岩点，不能直接外推为自由摆点、复杂折面、绳攀的成熟解法。
3. 建议复用生成器与数据工程，把新的投入放到评价层：按墙/岩点配置留出测试、多体型实攀、候选接受率、修改量、风格/动作达成、等级偏差。现成几何/结构/critic 分数可以筛候选，但不能代替这些验收。
