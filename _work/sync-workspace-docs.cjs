const fs=require('fs');
const menu=fs.readFileSync('docs/平台菜单逻辑说明_20261122.txt','utf8');
fs.copyFileSync('docs/平台菜单逻辑说明.txt','_work/平台菜单逻辑说明-before-20261122.txt');
fs.writeFileSync('docs/平台菜单逻辑说明.txt',menu);
const external='C:/Users/13411/Desktop/末端保供项目/软件开发/平台菜单逻辑说明.txt';
if(fs.existsSync(external))fs.writeFileSync(external,menu);
let lines=fs.readFileSync('软件开发进展.txt','utf8').split(/\r?\n/);
lines[0]='末端保供型局域电力系统软件平台——开发进展';lines[1]='最后更新：2026年11月22日（北京时间）';
lines=lines.map(line=>{
 if(line.startsWith('平衡分析已替换旧长页：'))return '平衡分析现整合为单一工作区：模式/输入工况/参数/校验/提交/结果选择在工具栏，中央显示真实档案图形，任务与明细进入底部面板。取消原三页重复导航；逐设备、随机、年度、原生模式沿用原组件与接口，完整高级页面细拆尚待验收。';
 if(line.startsWith('页面布局参考用户四张软件示意图，'))return '页面按2026-11-22新版工程工作空间任务书重构：EngineeringLayout深蓝标题、工程/编辑/视图/帮助、浅色流程导航、上下文工具、默认折叠可调侧/底面板及纯信息状态栏。低频工程操作归入菜单，底部重复保存/继续按钮移除。稳定工作区ID与旧入口集中兼容，命令替换中文操作分支。平衡默认只显示选中图形，确定性口径保持时段占比/累计电量，缺失指标明确未计算。源荷、网络、台账及主要参数按需编辑；取消/应用不隐式提交计算。工况为可选档案元数据，旧档案缺失保持未知。通用可关闭文档、独立日志、台账拓扑双向定位及全部高级/专项模式细拆尚未完成全面验收。';
 return line.replace('载入会替换工作区输入、清空运行阶段与旧结果引用，不自动保存或运行。','载入替换工作区输入并清空阶段、旧场景/生产序列引用；已查看结果保留并标记历史输入，不自动运行。');
});
lines.push('','','2026-11-22 工程工作空间结构重构（本次实际交付）',
'1. 提取布局、业务挂接、平衡工作区、工程共享控制、稳定注册表、命令和参数事务；App原多段全局样式移除，统一主题及布局CSS。',
'2. 合并场景/平衡/成果入口；保留台账、数据版本、全部计算模式、专项及交接。数据版本通过工程菜单打开。',
'3. 保留8760小时年度图；源荷支持草稿取消/应用和矩形粘贴；资源台账默认概览、编辑器按需；网络浏览只读属性，支持缩放、平移、适应窗口和全屏。',
'4. 参数取消/接受事务覆盖主要工作区与源储配置。策略计算关闭窗口后保留结果；参数变化提示旧结果；增加基准及请求隔离。',
'5. 可选operating_condition只记录工况，不改算法；档案可按真实标签筛选，策略/复核继承源标签，旧任务未知。缺失指标不补0。',
'6. 进度核对当前引用和快照，混合任务按真实时间排序；原生快照核对参数及网络适用性；历史场景数量不再等于应用完成。',
'7. 实际通过：vue-tsc与Vite（701模块，ECharts分包超500kB非阻断警告）；四组前端检查；40项隔离后端回归。失败路径故意打印异常日志，最终OK。',
'8. computer-use完成1440/1920/1280实机检查。验证工程“工作空间验证_20261122_阿拉山口48h_参数未校准”使用2023年前48小时真实历史窗口；资源/故障参数只作软件验证。场景537ba01ff3e44f1f8543e2978b6ec56e，平衡d0c0f2e87e334a619a791e274526d166，复算be0ed644cd1c4f2ca54f5ed035950a48；CSV已实际下载。原阿拉山口8760输入未替换。',
'9. 截图、旧新入口、文件职责、测试与剩余项见docs/工程工作空间交付记录.md和新版菜单说明。新版全部7阶段尚未整体验收；课题3资料继续留空，未将未验证组合写成完成。');
fs.writeFileSync('软件开发进展.txt',lines.join('\n'));
const files=fs.readdirSync('frontend/src').filter(f=>fs.statSync('frontend/src/'+f).mtime>=new Date('2026-11-22T00:00:00+08:00')).map(f=>'frontend/src/'+f).concat(['backend/app.py','backend/workflow_progress.py','backend/test_workflow_progress.py','backend/test_workspace_metadata.py','frontend/scripts/test-workspace-architecture.mjs','frontend/scripts/test-workflow-progress.cjs','frontend/scripts/test-result-context.mjs','软件开发进展.txt','docs/平台菜单逻辑说明.txt']);
fs.writeFileSync('docs/本次修改文件清单.txt',files.join('\n')+'\n不含临时工作脚本、构建输出、数据库及原始数据。\n');
console.log('已同步软件与项目目录菜单说明、正文进展和文件清单');
