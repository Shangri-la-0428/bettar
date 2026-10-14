# 岩点素材来源与使用边界

核查日期：2026-10-14。本轮接入四类现成扫描模型；pocket（洞点）仍是明确标记的模板缺口，没有用其他形状冒充真实洞点。

## 已导入的四件扫描模型

来源为 [SetRsoft Climbing Holds 3D dataset](https://huggingface.co/datasets/setrsoft/climbing-holds)，发布方 SetRsoft。源项目说明目前是建设中的原始扫描数据。

| 原始编号 | 原型资产 ID | 本次暂定类型 | 目视分类依据 |
| --- | --- | --- | --- |
| [0000000012](https://huggingface.co/datasets/setrsoft/climbing-holds/tree/main/0000000012) | `setrsoft-12-jug` | jug／内扣大把手 | 可见凹入的唇沿，作为内扣抓握候选。 |
| [0000000025](https://huggingface.co/datasets/setrsoft/climbing-holds/tree/main/0000000025) | `setrsoft-25-crimp` | crimp／薄边 | 形体较薄，具有浅边沿。 |
| [0000000017](https://huggingface.co/datasets/setrsoft/climbing-holds/tree/main/0000000017) | `setrsoft-17-pinch` | pinch／捏点 | 块状形体有相对的侧面；可否捏握仍取决于实际宽度、朝向和手型。 |
| [0000000011](https://huggingface.co/datasets/setrsoft/climbing-holds/tree/main/0000000011) | `setrsoft-11-sloper` | sloper／圆滑点 | 较宽的圆凸表面，没有明显内扣。 |

四件原始 `metadata.json` 的 `type`、`model`、`size` 均为 `unknown`。以上分类是对多角度几何视图的暂定判断，不是作者或厂商确认的型号分类。25 的源 metadata 填写厂商为 EP Climbing，其余三件厂商未知；未独立核实品牌授权。

## 许可与尺寸

四件数据均随数据集声明采用 [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)。使用和再分发应保留署名、来源、许可证及改动说明；改编数据遵循相同许可。

[源 README](https://huggingface.co/datasets/setrsoft/climbing-holds/blob/main/README.md) 另行声明：部分岩点外形的知识产权仍属于厂商，数据面向教育和岩馆管理，禁止将品牌形状进行商业复制，例如打印后出售。这是来源方的权利声明；本项目没有核验各形状的权利状态，也没有取得厂商单独授权。数据集的开放许可不应被写成品牌外形的全面商业授权。

原始扫描缺少可核对的实物尺寸。glTF 的名义米制约定不能证明扫描已标定；原型里的尺寸、安装背面、接触区域及动作参数属于演示配置或人工标注。它们不是实物测量、摩擦测试、承载测试或厂商安装说明。

## 洞点缺口与已排查候选

洞点必须具有可供手指进入和抓握的凹腔。**安装螺栓沉孔不能仅因外观凹陷就标成 pocket。** SetRsoft `0000000026` 的大圆凹口与另一小孔符合安装孔的可能形态，现有证据不足以确认手指洞，故未作为洞点导入。

| 候选来源 | 本次核查结果 |
| --- | --- |
| [SarDou3D：Finger pocket hold pack](https://www.thingiverse.com/thing:6581243) | 作者明确说明是 12 个洞点及模具，由 BH Toolset 生成，页面许可为 CC BY-SA 4.0；属于作者设计模型，非实物扫描。网站最终提示 ZIP 准备失败，四个页面公开 STL 链接的正常下载均返回 403，未取得文件。 |
| [同作者 Cults 发布页](https://cults3d.com/en/3d-model/various/finger-pocket-hold-pack) | 正常浏览器停在 Cloudflare 安全验证，未绕过，未下载。 |
| [Thingiverse 5208225](https://www.thingiverse.com/thing:5208225) | 曾被厂商产品页引用；本次实际打开返回 404，不能据此核实原文件许可或取得模型。 |
| [Mserra3D：Climbing Hold 1 hand pocket v2](https://www.thingiverse.com/thing:6816226) | 标题称 pocket，但作者正文描述 pinch／crimp，类型证据矛盾；没有通过模型目视核验，未导入。 |
| [Cole W 原作者模型列表](https://www.printables.com/@ColeW_1097318/models) | 正常浏览器停在 Cloudflare 安全验证；未核实具体洞点文件及许可证，未下载。 |
| [Garage Holds](https://garage-holds.vercel.app)／[作者仓库](https://github.com/rileywhy/garage-holds) | 核查时公开库为 3 个 jug、1 个 pinch，Pocket 数量为 0；仓库未发现可用洞点素材。 |
| [tothrunner：Rock Climbing Hold: Pocket](https://makerworld.com/en/models/2717914-rock-climbing-hold-pocket) | 作者明确描述两三指洞腔，但页面 Standard Digital File License 禁止分享、托管、分发数字模型及衍生件，不适合作为可再分发的网页素材，未下载。 |

以上下载失败没有通过登录、验证码或访问限制绕过处理。原始文件哈希、来源 metadata 和多角度检查记录保存在 `work/external-holds/`；详细筛选记录为 `work/external-holds/inspection/research-selection.json`。

## 世界杯现场配色参考

2026-10-15 实际在浏览器查看以下三张官方／主办方现场照片。仅作设计观察，没有把照片下载或搬入产品。照片受照明、曝光和粉尘影响，下面的 HEX 是我们为原型拟定的近似配色，**不是赛事官方色号，也不是从照片测出的材料参数**。

| 照片与出处 | 目视观察及可借鉴之处 |
| --- | --- |
| Prague 2024：[USA Climbing 官方报道](https://usaclimbing.org/news/grossman-wins-gold-at-world-cup-prague-2024/)／[Grossman 现场原图](https://usaclimbing.org/wp-content/uploads/2024/09/Natalia-Grossman-Competes-in-the-IFSC-World-Cup-Prague-2024_Tall-2-e1727100207808.jpg) | 局部浅灰白墙、亮黄色大形体、灰蓝小点，背景舞台很暗。突出的大形体依靠亮色与背面的阴影形成体积感，小点与大块并非必须同色。照片是局部视角，不能据此还原整条线。 |
| Innsbruck 2025：[主办方赛事报道](https://www.worldclimbingseries.com/sport/news-detail/garnbret-celebrates-double-victory-in-innsbruck/)／[Nakamura 抱石决赛图，KVÖ/Valancic](https://www.worldclimbingseries.com/fileadmin/_processed_/d/7/csm_IFSC_WC_IBK25_BOULDER_FINALS_Nakamura__c__VALANCIC-0366_9224597576.jpg) | 淡白／淡青墙，青绿色大三角体积块带黑色分区，附着小点偏灰紫；邻近大点有蓝色与橙色分区。粉尘和磨痕可见，彩色块的边缘阴影清楚。分区颜色可以帮助读形状，但仅凭照片不能判定粗糙度或摩擦系数。 |
| Innsbruck 2025：[World Climbing 男子半决赛报道](https://www.worldclimbing.com/news/tight-leaderboard-as-anraku-and-lee-rise-above-the-field)／[Anraku 现场图](https://images.ifsc-climbing.org/ifsc/image/private/t_ratio1_1-size60-f_webp-c_fill/v1750939368/prd/gzsn8utqp0mhz3fhd7vj) | 淡灰墙配粉白大体积块和黑灰岩点／局部分区。即使墙和体积块都偏浅，侧向阴影、曲面和深色抓握部件仍使层次清楚。可作为不依赖满墙鲜艳色彩的对照。 |

适配现有暖象牙色界面的三组场景候选：

| 场景 | 墙面 | 大体积块 | 附着小点 | 落地垫 |
| --- | --- | --- | --- | --- |
| 浅灰与柠黄 | `#DDE1DD` | `#DDD942` | `#49637B` | `#46514E` |
| 暖白与青绿 | `#E6E8E4` | `#8DCD5B` | `#303B45` | `#4D5E59` |
| 灰墙与粉白 | `#CAD3D8` | `#F3F1E7` | `#303A43` | `#46545C` |

界面底色可保持暖象牙 `#F4F0E6`。场景用柔和侧光和接触阴影表现仰角、屋檐与内外拐角，墙面保持低彩度，避免每个墙面都随机换强色。岩点与体积块可独立配色；颜色不直接绑定点型、难度、可抓握权限或摩擦。哑光、非金属的渲染外观只是视觉选择，不能代替实际材质与接触属性。
