# bettar 前端

本地三维定线工作台，使用 Vite、TypeScript 和 Three.js。数据全部来自 Python 本地服务；没有模拟通过结果或模型 API。

```sh
cd web
npm install
npm run dev
```

浏览器：<http://127.0.0.1:5173>。Vite 将 `/api` 代理至 `http://127.0.0.1:8765`；启动 Python 服务的方法见项目根目录文档。

```sh
npm run build
```

生成条件与当前结果包分开：选择器修改的是下一次生成参数，既有方案始终使用自己的请求。点位编辑创建派生候选，保留原候选和旧评价；新版本重新检查前不显示计算骨架。导入经过服务端校验，导出由服务端重建规范结果包。固定模式禁止点位编辑。

显示的岩点是与库存尺寸一致的合成几何代理。人体仅显示后端返回的有效关节点。接触环是目标位置，不能据此认定承重；没有关节点时不创建示意人体。场景不播放状态之间的插值动画。设计反馈明确区分于真人试爬记录。


默认工作场景为“完整混合线路”：同一候选库、人体、倾角、起终点和移手数量下，对比混合节奏、后段力量、持续收尾三个计划；每个计划拥有独立结果包。支持 8／10／12 次移手，阶段按钮按报告的事件范围定位，动作列表不限制八步。`route-design.ts` 渲染阶段目标／估计、基线与前序负荷曲线、后段增量和逐动作状态；所有数值为未校准模型指数，不显示疲劳百分比、真实功率或攀爬等级。

完整线路的 `reference_layout` 是可选安装位置池。画布只安装候选实际使用的岩点及必要支撑体积块，同线统一颜色，以标签区分手／脚／共用、移手次序与起终点。旧方案的未用安装点默认隐藏，取消“仅显示当前线路”后以灰色显示；选择库存不自动把它加入线路。岩点库按 Jug、Crimp、Pinch、Sloper、Pocket 家族与小脚点、体积结构筛选，手脚用途、具体接触面的肢体权限、安装方向分别表达。旧 `directional_edge` 和 `rail` 保持兼容，显示为抓边及长条抓边形态。标准库现为九模板、34 件默认库存，新增 Crimp 薄抓边与 Pocket 凹入指洞／外缘踩踏面。

默认加载 `GET /api/route-examples` 的 `{examples:[{id,label,bundle}]}`；生成对照调用 `POST /api/route-comparison`，共享 `{body_id,angle_deg,hand_moves,seed,budget}`。单计划通过 `POST /api/request` 的 `profile="route"`、`route_program="mixed_flow"|"power_finish"|"sustained_finish"` 获得请求，再调用 `/api/generate`。四手风格实验及标准库、竞赛、基础算例保留为可切换场景；`/api/style-examples` 与 `/api/style-comparison` 仍适用于四手基线。

分类与属性依据见根 README 的“岩点模型与素材路线”；接口、历史模型公式及验证边界见 [实现契约](../work/implementation-contract.md)。`outputs/style-study/`、`outputs/catalog-study/` 的测试数和截图是各自历史轮次的证据，不代表当前完整线路扩展已经通过相同验收。
