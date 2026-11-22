const fs=require('fs');
let p=fs.readFileSync('frontend/src/useEngineeringProject.ts','utf8');
p=p.replace("const target=resolveWorkspace(menu,section);workspaceId.value=target.id;",'const target=resolveWorkspace(menu,section);');
p=p.replace("active.value=target.menu;subsection.value=section||target.defaultView;","workspaceId.value=target.id;active.value=target.menu;subsection.value=section||target.defaultView;");
p=p.replace("if(check.totalIssues)return", "if(check.count<2||check.count>8760)return '时序须为2–8760小时';if(check.totalIssues)return");
// Keep imports and exposed template API limited to actual dependencies.
function pruneImports(source,body){const ts=require('../frontend/node_modules/typescript');const ast=ts.createSourceFile('temp.ts',source,ts.ScriptTarget.Latest,true);return ast.statements.filter(ts.isImportDeclaration).map(n=>{if(!n.importClause)return n.getText(ast);const c=n.importClause;const names=[];if(c.name&&new RegExp('\\b'+c.name.text+'\\b').test(body))names.push(c.name.text);let text=names.join(',');if(c.namedBindings&&ts.isNamedImports(c.namedBindings)){const elements=c.namedBindings.elements.filter(e=>new RegExp('\\b'+e.name.text+'\\b').test(body));if(elements.length)text+=(text?',':'')+'{'+elements.map(e=>e.getText(ast)).join(',')+'}'}return text?'import '+(c.isTypeOnly?'type ':'')+text+' from '+n.moduleSpecifier.getText(ast)+';':''}).filter(Boolean).join('\n')}
const body=p.slice(p.indexOf('export function useEngineeringProject'));
p=pruneImports(p,body)+'\n'+body;
fs.writeFileSync('frontend/src/useEngineeringProject.ts',p);
let app=fs.readFileSync('frontend/src/App.vue','utf8');
app=app.replace('ref="dataWorkspace" v-else','ref="dataWorkspace" managed v-else');
// Remove the unused duplicate DataWorkspace from the former global parameter window.
app=app.replace(/<ParameterDialog v-model:open="dataParametersOpen"[\s\S]*?<\/ParameterDialog>/,'');
app=app.replace(':stages="stages.length"',':stages="stages.length" :progress="engineeringProgress" :project="project"');
app=app.replace('<ReportWorkspace v-else-if="active===\'方案与报告\'"', '<ReportWorkspace :section="subsection" v-else-if="active===\'方案与报告\'"');
// Show condition guidance as a compact selector; it never relabels stored runs.
app=app.replace('<details class="scenario-guide"><summary>工况选择与操作说明</summary><article>', '<article class="scenario-guide">');
app=app.replace('⑤ 平衡结果在本页对应结果区及方案与报告中查看；修改参数后须重新生成和计算。</p></article></details>', '⑤ 结果在平衡工作区及成果管理中查看。</p></article>');
const first=app.indexOf('<details class="scenario-guide"');
app=app.replace('<h3>场景配置与计算流程</h3>','');
app=app.replace(/<p>① 查看来源：[\s\S]*?⑤ 结果在平衡工作区及成果管理中查看。<\/p>/,'');
app=app.replace("工况选择 ","运行工况 ");
// Additional global menu entry preserves ledger economic parameters without a duplicate instance.
app=app.replace('<ParameterDialog v-model:open="scenarioLibraryOpen"', '<ParameterDialog v-model:open="scenarioLibraryOpen"');
// Template-aware pruning of imports and controller destructuring.
function pruneVue(source){const script=source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];const template=source.slice(source.indexOf('<template>'));let body=script.replace(/^import .*;\r?\n/gm,'');body=body.replace(/const \{([^}]+)\}=context;/,(_,list)=>'const {'+list.split(',').filter(n=>new RegExp('\\b'+n.trim()+'\\b').test(template)).join(',')+'}=context;');body=body.replace(/const \{([^}]+)\}=useEngineeringContext\(\);/,(_,list)=>'const {'+list.split(',').filter(n=>new RegExp('\\b'+n.trim()+'\\b').test(template)).join(',')+'}=useEngineeringContext();');return source.replace(script,'\n'+pruneImports(script,body+template)+'\n'+body+'\n')}
fs.writeFileSync('frontend/src/App.vue',pruneVue(app));fs.writeFileSync('frontend/src/BalanceWorkspace.vue',pruneVue(fs.readFileSync('frontend/src/BalanceWorkspace.vue','utf8')));
let r=fs.readFileSync('frontend/src/ReportWorkspace.vue','utf8').replace('projectId:string}>','projectId:string;section?:string}>');
r=r.replace('<article id="report-archive">','<article v-show="!section||section===\'计算档案\'" id="report-archive">').replace('<article id="report-comparison">','<article v-show="!section||section===\'方案对比\'" id="report-comparison">').replace('<article id="report-plans">','<article v-show="!section||[\'方案对比\',\'配置方案\'].includes(section)" id="report-plans">');fs.writeFileSync('frontend/src/ReportWorkspace.vue',r);
let d=fs.readFileSync('frontend/src/DataWorkspace.vue','utf8');
d=d.replace("const csv=defineModel<string>({required:true});", "const appliedCsv=defineModel<string>({required:true});const csv=ref(appliedCsv.value);watch(appliedCsv,v=>{csv.value=v;dataEditorOpen.value=false});");
d=d.replace('section?:string;source?:any;','section?:string;source?:any;managed?:boolean;');
d=d.replace("function openEditor(){if(","function openEditor(){if(");
d=d.replace('else dataEditorOpen.value=true}',"else {csv.value=appliedCsv.value;dataEditorOpen.value=true}}");
d=d.replace("function openDatasetPicker(){datasetPickerOpen.value=true;dataEditorOpen.value=false}","function openDatasetPicker(){csv.value=appliedCsv.value;datasetPickerOpen.value=true;dataEditorOpen.value=false}\nfunction cancelEdit(){csv.value=appliedCsv.value;dataEditorOpen.value=false}\nfunction applyEdit(){if(inspectTimeSeries(csv.value).totalIssues){message.value='请先修正格式问题';return}appliedCsv.value=csv.value;dataEditorOpen.value=false;message.value='数据草稿已应用，尚未保存工程'}");
d=d.replace("csv.value=pending.value.csv;pending.value=null;", "csv.value=pending.value.csv;appliedCsv.value=csv.value;pending.value=null;");
d=d.replace('<div class="actions"><button @click="openDatasetPicker">','<div v-if="!managed" class="actions"><button @click="openDatasetPicker">');
d=d.replace('<button @click="datasetPickerOpen=false">关闭数据集选择</button>','<div class="actions"><strong>导入数据</strong><label class="button">选择外部 CSV<input type="file" accept=".csv" hidden @change="event=>{upload(event);dataEditorOpen=true;datasetPickerOpen=false}" :disabled="disabled"></label><button @click="datasetPickerOpen=false;openEditor()">手动创建 / 编辑</button><button @click="datasetPickerOpen=false">关闭</button></div><p>选择以下数据集，或导入外部文件、编辑当前数据。只有明确应用才更新工程输入。</p>');
d=d.replace('<div v-show="dataEditorOpen"><div class="actions">','<div v-show="dataEditorOpen"><div class="actions"><button @click="cancelEdit">取消编辑</button><button class="primary" @click="applyEdit" :disabled="disabled||!!inspection.totalIssues">应用数据草稿</button>');
d=d.replace('<div v-show="dataEditorOpen">','<div v-show="dataEditorOpen"><SeriesPreview :csv="csv"/>');
d=d.replace('dataEditorOpen=!dataEditorOpen','dataEditorOpen?cancelEdit():openEditor()');
// Excel-style paste from a selected table cell, retaining headers and validation.
d=d.replace('function edit(row:number',`function pasteCells(row:number,col:number,event:ClipboardEvent){const text=event.clipboardData?.getData('text');if(!text||!/[\\t\\n]/.test(text))return;event.preventDefault();const all=rows.value.map(r=>[...r]);for(const [i,line] of text.trimEnd().split(/\\r?\\n/).entries()){if(row+i>=all.length)break;for(const [j,value] of line.split('\\t').entries())if(col+j<4)all[row+i][col+j]=value.trim()}csv.value=fields.join(',')+'\\n'+all.map(r=>r.join(',')).join('\\n')+'\\n'}\nfunction edit(row:number`);
d=d.replace('@input="edit(page*24+i,j,$event)"','@input="edit(page*24+i,j,$event)" @paste="pasteCells(page*24+i,j,$event)"');
fs.writeFileSync('frontend/src/DataWorkspace.vue',d);
