// Public reference photographs are linked to their original editorial sources.
// They are not bundled assets, reconstructed measurements, or training data.
export const competitionReferences = [
  {
    event: 'Bern 2023 · 世锦赛',
    title: '大曲面决定身体位置',
    image: 'https://live.staticflickr.com/65535/53107394800_82fbf3806d.jpg',
    url: 'https://www.flickr.com/photos/ifsclimbing/53107394800/',
    credit: '© Lena Drapella / IFSC',
    observation: '大型蓝色曲面点横向分布，手脚使用不同边缘。单个中心点不足以表达接触选择。',
  },
  {
    event: 'Innsbruck 2025 · 世界杯',
    title: '几何体与小点协同工作',
    image: 'https://www.worldclimbingseries.com/fileadmin/_processed_/d/7/csm_IFSC_WC_IBK25_BOULDER_FINALS_Nakamura__c__VALANCIC-0366_9224597576.jpg',
    url: 'https://www.worldclimbingseries.com/sport/news-detail/garnbret-celebrates-double-victory-in-innsbruck/',
    credit: '© KVÖ / Valancic',
    observation: '三角体上安装小点，表面区域和侧面朝向共同影响动作。本轮模板库支持小点安装在体积块的斜面上；多层装配与真实扫描仍未实现。',
  },
  {
    event: 'Seoul 2025 · 世锦赛',
    title: '接触姿态之外还有运动',
    image: 'https://live.staticflickr.com/65535/55062547745_0bef1576dd.jpg',
    url: 'https://www.flickr.com/photos/ifsclimbing/55062547745/',
    credit: '© Nakajima / Timmerman / IFSC',
    observation: '岩点装在凸出的几何体上，照片中双脚离开墙面。静态照片不能证明完整动作或受力过程。',
  },
];

export const boardReferences = [
  {
    name: 'T 板 / Tension Board 2',
    url: 'https://tensionclimbing.com/products/tb2-details',
    lesson: '固定岩点集提供 Mirror 与 Spray 两种布局。木质点与双纹理 PU 点、安装朝向和镜像选择共同构成训练条件。',
    gap: '需要板型与布局标识、接触面属性，以及只在支持的布局上使用镜像变换。',
  },
  {
    name: '月亮板 / MoonBoard',
    url: 'https://moonclimbing.com/using-your-moonboard',
    lesson: 'Setup 年份绑定岩点套装、位置和朝向。起终点、脚点规则及倾角让线路可复现；Benchmark 经过官方审核者遴选。',
    gap: '需要把布局版本、脚点规则与线路一起保存；模型预测的难度不能代替实攀与审核。',
  },
  {
    name: 'K 板 / Kilter Board',
    url: 'https://settercloset.com/pages/kb-app',
    lesson: 'Original／Home Wall、尺寸、岩点配置和倾角都影响线路上下文。应用将定线、完攀记录、线路评分和难度反馈连接起来。',
    gap: '需要真人试爬与难度反馈闭环；目前只记录设计意见，不将其计为完攀记录。',
  },
];
