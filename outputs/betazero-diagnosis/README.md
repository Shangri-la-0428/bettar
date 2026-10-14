# BetaZero 原生墙面诊断 · 2026-10-15

结论：首轮全空的主因是上轮适配器选择了上游的非默认采样分支，而不是已经证明坐标转换错误或“18 点太少”。离线采样现已修复并保留旧分支复现。模型目前不升级为主生成器：修复解决了选点塌缩，却尚未显示优于匹配随机对照的线路价值。

## 先隔离采样，再比较墙面

固定相同生产权重、归一化参数、100 步、CFG=3、投影起点 0.8、横移 0；每组 V3/V4/V5 × 种子 0–9，共 30 个样本。表中“选点”是去重后的原始模型集合，尚未补入 bettar 起终点，也不是完整走法。

| 墙面 | 旧分支空输出 | 正常分支空输出 | 旧分支平均选点 | 正常分支平均选点 |
|---|---:|---:|---:|---:|
| bettar，18 点，25° | 24/30 | 0/30 | 0.20 | 7.37（6–10） |
| 原生 Kilter，642 点，25° | 24/30 | 0/30 | 0.23 | 10.03（6–13） |
| 原生 Kilter，642 点，40° | 0/30 | 0/30 | 4.57 | 12.03（9–18） |
| 作者 Ze Home Wall，204 点，30° | 16/30 | 0/30 | 0.73 | 9.10（4–13） |

Kilter 原数据库没有默认角度，所保存的 Kilter 示例为 40°；另外设置同为 25° 的组来隔离墙面差异。作者家用墙保留其默认 30°。原生墙读取整个 layout，保留所有岩点，与上游 manifold 加载一致，不按声明图片边界裁剪。[全部 240 次主对照](comparison.json)

上游正常 `deterministic=False` 分支每步抽新噪声。上轮为了固定种子选用了 `deterministic=True`；其生产代码把带有预测信号的上一轮 `noisy` 再作为噪声传入。这也不同于其说明文字和旧训练代码所说的“复用初始噪声”。固定 RNG 种子并每步抽新噪声，可以同时保持正常采样与复现能力。[生产采样代码](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/app/services/utils/generation_utils.py#L207-L243)、[默认参数](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/app/schemas/generate.py#L8-L13)

同为 25° 的两面墙，30 对样本在第一次投影之前的预测张量完全相同；旧分支有 29/30 在此时已经全部判为空。网络在这之前根本没有读取墙点集合，墙面只在后续最近邻投影中进入循环。因此不能用这批空输出来证明稀疏墙或属性转换是主因。后续仍可能恢复少量槽位，所以最终空样本数是 24 而非 29。

以哈希核验后的原生类和原生 `generate` 为参照，8 组（两墙 × 固定/随机横移 × 后端/网页参数）最终张量逐位一致。修复后的实际适配器另外复跑了 bettar 全部 30 个样本，逐位匹配本诊断。[原生复现证据及缓存准备方法](upstream-parity.json)、[最终验证](verification.json)

## 坐标与属性核对

- 原生约定是左下角原点、英尺、y 向上；bettar 的面内米制坐标换算与其一致。未发现用世界投影坐标、重复倾斜或整体单位错误。
- V3/V4/V5 对应 16/18/20；quality=3、ascents=1000 及其对数变换与原服务一致；墙角为实际 25°。
- bettar 的 18 点与条件全部位于原 scaler 的逐维数值范围内。这只排除了明显越界，不证明联合分布相同。
- `pinch` 按明确分类，`flat` 未标注为 false；原生 flat 指平直边，并非光滑摩擦面。中性 `useability=0.5` 是近似，不是实测抓握能力。
- 上游 `is_foot` 曾由历史脚用频率推断；bettar 用所选接触面的脚专用权限赋值，两者语义并不完全相同。当前手点的所选面只允许 LH/RH，不能默认为脚可用。

来源：[坐标](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-frontend/src/utils/coordinateSpace.ts#L1-L6)、[特征变换](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/app/services/utils/ddpm_model.py#L227-L250)、[历史脚用统计](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/model-training/boardlib_preprocessing.py#L246-L251)。

## 18 点与中性属性的剩余影响

在正确采样下，从原生 Kilter 固定抽取三个 18 点子集（每个 8 手点、10 脚点），各跑同样 30 样本。三组均 0 次空输出，平均分别选出 4.93、4.47、5.03 个不同点；平均重复槽位为 5.23、5.70、5.13，完整 642 点墙仅为 0.13。稀疏化会让不同预测落在同一岩点，确有信息损失，但不是 18 点硬性不能工作。

保持 Kilter 的位置、方向、脚点标记和 pinch，只把 useability 改为 0.5、flat 清零，平均选点从 10.03 变为 9.87，仍 0/30 空输出。这个联合干预不分别量化 useability 与 flat 的影响，也不能证明 bettar 的所有抓握标注准确。[120 次密度/属性对照](density-attributes.json)

另外使用上游网页参数 CFG=5、投影起点 0.5，以及原生随机横移：bettar、Kilter40°、Home30° 各 30 次均非空，平均选点 5.73、10.43、8.03。这是整体默认流程复核；它同时变更多个参数，不用于单独估计噪声的因果效果。[90 次网页默认对照](upstream-ui-defaults.json)、[上游网页设置](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-frontend/src/types/generate.ts#L26-L49)

## 选点恢复以后，线路仍需要脚点策略

修复采样后的 30 个模型集合原样保留；统一补入起终点、按原角色与权限转换，再与匹配手脚数量的随机集合独立搜索。两组都为 **0/30 完整走法**，全点基线仍完整。26 个模型样本未提供任何额外脚点，另外 4 个仅加入 `foot-2`，因此当前严格权限下无法形成足够的上行脚点链。[原权限复验 61 条记录](bettar-recheck/experiment.json)

再做一个明确分开的脚点补全诊断：保留两组各自手点选择，给两组同样开放墙上全部 10 个原合法脚点；不把手点改为脚点，不改墙位、人体、起终点、检查器或每案 60 秒预算。结果模型 **7/30**、配对随机 **9/30** 找到通过离散几何检查的完整走法。[脚点补全诊断](feet-ablation/experiment.json)

7/30 不是模型独立生成成功率，也不能与原方案 0/30 混计。9 对 7 不足以证明随机更强；但没有证据证明模型胜出。重复允许点集合仍全部计入样本分母，实际检查按集合复用，并非 30 条完全独立线路。所有几何通过仅指离散检查，静态支撑仍单列，真人试攀尚未进行。

进一步核对成功集合：模型的 7 次全部等于 **8 手点 + 10 脚点的全点基线**，复用同一条走法，并不是 7 条不同新线路。随机的 9 次包括相同的 7 次基线，以及两次同一套去掉 `hand-5` 的集合。所有成功走法的静态释放检查仅 2/13 通过。这个结果进一步限制了将模型当作新路线提案器的理由。

## 决定与代码边界

1. 已修正离线适配器为 `betazero-fixed-wall/2` 的 seeded-fresh 采样，原始权重不变。保留 `sampling_mode="recursive_noisy"` 复现首轮问题，来源字段明确区分 RNG 复现与上游 deterministic 分支。
2. BetaZero 暂留作离线研究对照和手点灵感来源，不升级为主生成器，不因这次恢复选点就投入重训。后续若继续，应先解决手脚角色与脚点补全，并在多面已有人类线路的墙上验证，而不是针对这一面墙反复调参。
3. 当前网页的首轮保存实验原样保留，属于旧采样证据。本报告与所有新结果单独存档；脚点补全不会冒充模型原始输出。脚点补全的效果也不是新受力算法或真人质量提升。

## 复现

使用已有可选 ML 环境与固定权重；原生 DB 首次仅下载约 0.77 MiB，不另下模型或照片。数据库来源为 pinned [storage.db](https://github.com/EvanMcCormick37/ml-homewall-climb-generator/blob/6f0acb414a5f1ab070aa62d02ac98f2602011821/climb-backend/data/storage.db)，SHA256 `9fcf87f93830e7d761fc6ba089de8463c5e574d75b35f6b8e46bbb9ea13f8ff5`。数据库留在忽略缓存；公开结果只使用白名单数值/岩点标识，不导出账户或分享字段。上游代码沿用其 MIT 署名，权重及原始数据不随仓库分发。

```sh
.runtime/venv-ml/bin/python scripts/diagnose_betazero.py --cases bettar18-25 kilter642-25 kilter642-40 home204-30 --modes recursive_noisy seeded_fresh
.runtime/venv-ml/bin/python scripts/diagnose_betazero.py --cases kilter18-subset0-25 kilter18-subset1-25 kilter18-subset2-25 kilter642-neutral-25 --modes seeded_fresh --output outputs/betazero-diagnosis/density-attributes.json
.runtime/venv-ml/bin/python scripts/diagnose_betazero.py --cases bettar18-25 kilter642-40 home204-30 --modes seeded_fresh --native-offset --guidance 5 --projection-start .5 --output outputs/betazero-diagnosis/upstream-ui-defaults.json
.venv/bin/python scripts/check_betazero_diagnosis.py --all-feet-ablation
BETTAR_TEST_MODEL=1 .venv/bin/python -m pytest -q tests/test_betazero_diagnosis.py tests/test_learned_generator.py
```

原生类复现测试还需要 `upstream-parity.json` 中列出的最小源缓存准备步骤；它先核验源摘要，再仅编译所需类，不执行上游模块初始化、不反序列化 scaler。原模型安装仍见仓库根目录 README。
