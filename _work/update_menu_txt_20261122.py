from pathlib import Path
root=Path(__file__).resolve().parents[1]
primary=root/'docs/平台菜单逻辑说明.txt'
s=primary.read_text(encoding='utf-8-sig')
s=s.replace('更新日期：2026年11月22日（北京时间）','更新日期：2026年11月22日（北京时间，历史数据导入兼容修复后）')
s=s.replace('本说明覆盖新版工程工作空间；历史菜单名仅作兼容，不再全部显示为左侧入口。','本说明依据当前实际代码更新，覆盖菜单、工具栏、参数窗口、任务面板及历史数据导入。\n历史菜单名仅作兼容；注册表中的内部section不等于界面上全部可见的标签。')
s=s.replace('五、数据、工况和进度','五、历史数据导入、工况和工程进度')
anchor='6.22输入继续退役。balanceMode与model保持两层映射，高级模式仍调用各自原接口。'
replacement='''历史风光荷导入入口：数据准备 → 源荷与气象 → 源荷时序 → 导入数据。
  A. 选择已有数据集：阿拉山口2023/2024/2025，或ExtremeScene年度数据。
     设置起始小时和连续小时数 → 预览历史数据 → 应用所选风光荷与配套拓扑。
     默认预览8760小时；内置ExtremeScene数据集按既有规则将年度峰值映射至IEEE33基准，明确显示缩放来源。
  B. 选择外部CSV：读取文件 → 自动识别并预览 → 应用导入数据。
     兼容timestamp/time/datetime/时间/日期时间，load_kw/load/负荷，
     wind_kw/wind_power/风电，pv_kw/solar_power/pv_power/光伏；支持已列明的kW中文表头。
     列可以乱序，支持引号、BOM、逗号/制表符/分号及UTF-8/GB18030编码。
     标准输出：timestamp,load_kw,wind_kw,pv_kw，功率约定kW。
     支持带毫秒的ISO时间，以及明确年月日的常见日期写法。
     预览展示列映射、附加字段和单位说明；未经明确应用不替换工程输入。
     气象与质量标记列留在原文件，来源记录附加字段和SHA；不代表这些字段已接入算法。
     外部导入只标准化格式，不缩放功率、不排序、不插值、不删除时段。
     MW等未知单位表头、重复候选列、缺列、列数错误、空值/负值/非有限值及不连续时间明确报错。
     原始8784行闰年文件不会静默截成8760；请用数据集选择器明确选取连续窗口。
     外部文件应用保留当前网络及支路参数，解除旧场景/生产序列和运行阶段，保留历史计算档案。
     内置数据集应用会载入对应配套拓扑，并解除旧引用和阶段；两种路径不能混为相同网络操作。
  C. 手动创建/编辑：打开当前时序草稿，支持分页、逐格编辑、Excel矩形粘贴及新增时段。
     取消编辑恢复原输入；应用数据草稿通过格式检查后更新工作区，工程保存仍为独立操作。
年度数据超过168小时，导入后选择支持全年输入的汇总模型；节点网络模式原168小时限制不变。
外部ExtremeScene原文件按原功率导入，不自动套用内置数据集的IEEE33缩放系数。
标准化副本：C:/Users/13411/Desktop/software/data/import-ready/
  alashankou-2023_standard_kw.csv
  alashankou-2025_standard_kw.csv
  extreme-muswellbrook-2019_standard_kw.csv
以上副本均8760小时，带对应.source.json来源说明；原始文件未修改。
6.22输入继续退役。balanceMode与model保持两层映射，高级模式仍调用各自原接口。'''
assert anchor in s
s=s.replace(anchor,replacement)
insert='''
上下文工具及实际动作（区别于左侧导航）：
  源荷时序：导入数据、编辑数据、校验输入。
  电网拓扑：编辑网络模型、校验输入；设备属性和图形工具由拓扑组件提供。
  资源与负荷：各资源视图显示概览，通过“打开数据编辑器”编辑并独立保存台账。
  场景生成：步骤标签切换业务；各步骤自己的参数、生成、预览、应用按钮沿用实际接口。
  普通平衡：输入运行工况、计算模式、结果工况筛选、当前平衡结果、校验输入、参数设置、提交计算、导出结果CSV。
  高级平衡：只挂载当前所选模式组件，使用该模式原输入、参数、任务及结果机制；不以普通平衡参数代替。
  源储配置：配置参数、任务与详细结果；内部显示候选/目标/规划/协同/组网等适用分类。
  专项：承灾、黑启动提供参数设置；离网稳定资料未交付时仅保留草稿与待接入状态。
  底部面板：计算任务、数据明细、校验信息、分阶段指标。
  数据明细分页显示；当前数据工作区查看当前源荷，其余工作区以已选结果为依据。
  分阶段指标来自真实结果；选择阶段联动平衡图时间范围。无阶段结果时显示空状态。
  独立“任务日志”标签尚未完成，研究任务已有工作日志链接，不能描述成独立日志面板已交付。
'''
s=s.replace('三、新旧入口对应',insert+'\n三、新旧入口对应')
s=s.replace('DataWorkspace.vue、NetworkEditor.vue、EngineeringWorkspace.vue：源荷、拓扑和独立台账编辑。','DataWorkspace.vue、NetworkEditor.vue、EngineeringWorkspace.vue：源荷、拓扑和独立台账编辑。\nbackend/source_import.py：外部历史CSV识别、标准化、来源说明及预览接口。\nbackend/input_datasets.py、DatasetPicker.vue：内置历史数据目录、连续窗口及配套网络。\ntimeSeries.ts：前端时序格式与连续性检查，支持毫秒时间戳。')
s=s.replace('已执行TypeScript/Vite构建、四组前端检查、40项隔离后端回归。','界面重构阶段记录：TypeScript/Vite构建、四组前端检查、40项隔离后端回归通过。\n后续导入兼容修复记录：构建、25项后端回归及前端时序检查通过；运行中8833接口实际接收原文件返回8760行。\n阿拉山口2023/2025、ExtremeScene FY2019逐时间、逐功率对照一致，标准副本经前端格式检查均0问题。\n外部文件选择上传的浏览器完整交互本次尚未重新验收，接口/格式检查通过不替代该项。')
s=s.replace('关键截图：docs/ui-verification-20261122，含1440×900主要页面和1920×1080、1280×800平衡。','关键截图：C:/Users/13411/Desktop/software/docs/ui-verification-20261122/，共15张实际运行截图。\n覆盖首页、8760源荷、拓扑、场景、平衡、参数、任务、源储配置、成果及不同分辨率。\n最终重构平衡截图：balance-final-8832.jpg。上述为界面重构截图，导入兼容修复尚未另补浏览器截图。\n交付记录：docs/工程工作空间交付记录.md；导入修复记录：docs/历史数据导入兼容修复_20261122.txt。')
s='\n'.join(line for line in s.splitlines() if not line.startswith('2026-11-22导入更新：')).rstrip()+'\n'
targets=[primary,root/'docs/平台菜单逻辑说明_20261122.txt',Path('C:/Users/13411/Desktop/末端保供项目/软件开发/平台菜单逻辑说明.txt')]
for target in targets:target.write_text(s,encoding='utf-8')
assert all(target.read_bytes()==primary.read_bytes() for target in targets)
p=root/'软件开发进展.txt';progress=p.read_text(encoding='utf-8-sig')
progress=progress.replace('菜单层级说明：项目软件开发目录《平台菜单逻辑说明.txt》，软件docs目录留存同步副本。','菜单层级说明：项目软件开发目录《平台菜单逻辑说明.txt》与软件docs同名及20261122日期版已同步；正文包含当前菜单、导入兼容规则、工具动作和未验收边界。')
progress+='\n2026-11-22 菜单TXT同步更新：依据当前workspaceRegistry、命令注册和历史导入代码重写对应正文，纳入外部CSV列映射/编码/单位/预览应用、内置与外部数据缩放及网络差异、全年与网络模式限制、底部面板动作、截图路径和验证边界；删除重复的末尾导入补记。软件同名/日期版与项目目录三份TXT逐字一致。本次仅文档修改，完成内容核对和副本一致性检查，未重跑构建或算法测试。\n'
p.write_text(progress,encoding='utf-8')
print('Updated and verified 3 identical menu TXT copies; progress document synchronized.')
