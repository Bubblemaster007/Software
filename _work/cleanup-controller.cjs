const fs=require('fs'),ts=require('../frontend/node_modules/typescript');
let p=fs.readFileSync('frontend/src/useEngineeringProject.ts','utf8');
p=p.replace(/const currentDataGroup=computed\([^\n]*\);\n/,'');
p=p.replace(/const balanceView=computed\([^\n]*\);\n/,'').replace(/const currentNavigation=computed\([^\n]*\);\n/,'').replace(/const currentGroup=computed\([^\n]*\);\n/,'');
p=p.replace(/async function continueWorkflow\(\)[\s\S]*?(?=function normalizeStages)/,'');
p=p.replace("const chartMode=ref('供需平衡');\n",'').replace("const menus=['工程工作台'", "const menus=['工程工作台'");
p=p.replace(/const menus=\[[^\n]*?\];const active=/,"const active=");
p=p.replace("const chart=ref<HTMLElement>();let plot:ECharts|undefined;let chartRequest=0;",'');
p=p.replace("const desktopMenu=ref('');\n",'').replace("const resultDetail=ref('分阶段指标');\n",'');
p=p.replace(/async function draw\(\)\{\}\n/,'').replace(/await draw\(\)/g,'');
p=p.replace('watch([active,chartMode,subsection,balanceMode],draw);','');
// Expose only the connection API consumed by the entry point and workspace hosts.
const users=['App.vue','WorkspaceHost.vue','BalanceWorkspace.vue','TaskPanel.vue'];const used=new Set();
for(const file of users){const s=fs.readFileSync('frontend/src/'+file,'utf8');for(const m of s.matchAll(/const \{([^}]+)\}=(?:context|useEngineeringContext\(\));/g))for(const name of m[1].split(','))used.add(name.trim())}
p=p.replace(/return \{resultRange,[^\n]+\};/,'return {'+[...used].join(',')+'};');
const ast=ts.createSourceFile('controller.ts',p,ts.ScriptTarget.Latest,true);const body=p.slice(p.indexOf('export function useEngineeringProject'));
let imports=[];for(const n of ast.statements)if(ts.isImportDeclaration(n)){const c=n.importClause;if(!c)continue;const parts=[];if(c.name&&new RegExp('\\b'+c.name.text+'\\b').test(body))parts.push(c.name.text);if(c.namedBindings&&ts.isNamedImports(c.namedBindings)){const elements=c.namedBindings.elements.filter(e=>new RegExp('\\b'+e.name.text+'\\b').test(body));if(elements.length)parts.push('{'+elements.map(e=>e.getText(ast)).join(',')+'}')}if(parts.length)imports.push('import '+(c.isTypeOnly?'type ':'')+parts.join(',')+' from '+n.moduleSpecifier.getText(ast)+';')}
fs.writeFileSync('frontend/src/useEngineeringProject.ts',imports.join('\n')+'\n'+body);
let app=fs.readFileSync('frontend/src/App.vue','utf8');app=app.replace("import StudyTasks from './StudyTasks.vue';","import TaskPanel from './TaskPanel.vue';");
app=app.replace(/<template v-if="layout.bottom.value==='计算任务'">[\s\S]*?<\/template><ul v-else-if/,`<template v-if="layout.bottom.value==='计算任务'"><TaskPanel/></template><ul v-else-if`);fs.writeFileSync('frontend/src/App.vue',app);
