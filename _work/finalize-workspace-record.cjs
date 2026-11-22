const fs=require('fs');
for(const file of ['软件开发进展.txt','docs/工程工作空间交付记录.md']){
 let s=fs.readFileSync(file,'utf8').replaceAll('701模块','702模块').replaceAll('701 模块','702 模块');
 s+='\n最终补验（2026-11-22）：修正空运行阶段与后端默认“全时域”阶段的等价比较，历史档案未改输入不再误报待复算；新增回归通过。原数据版本窗口已通过实际界面读取。最终启动地址 http://127.0.0.1:8832/ ，无新增控制台错误，最终截图 docs/ui-verification-20261122/balance-final-8832.jpg。\n';
 fs.writeFileSync(file,s);
}
const files=fs.readdirSync('frontend/src').filter(f=>fs.statSync('frontend/src/'+f).mtime>=new Date('2026-11-22T00:00:00+08:00')).map(f=>'frontend/src/'+f).concat(['backend/app.py','backend/workflow_progress.py','backend/test_workflow_progress.py','backend/test_workspace_metadata.py','frontend/scripts/test-workspace-architecture.mjs','frontend/scripts/test-workflow-progress.cjs','frontend/scripts/test-result-context.mjs','软件开发进展.txt','docs/平台菜单逻辑说明.txt','docs/工程工作空间交付记录.md']);
fs.writeFileSync('docs/本次修改文件清单.txt',files.join('\n')+'\n不含临时工作脚本、构建输出、数据库及原始数据。\n');
const external='C:/Users/13411/Desktop/末端保供项目/软件开发/平台菜单逻辑说明.txt';
console.log('菜单说明同步一致：'+(fs.readFileSync(external,'utf8')===fs.readFileSync('docs/平台菜单逻辑说明.txt','utf8')));
console.log('修改文件清单：'+files.length+'项；关键截图：'+fs.readdirSync('docs/ui-verification-20261122').length+'张');
