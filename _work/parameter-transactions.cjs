const fs=require('fs'),ts=require('../frontend/node_modules/typescript');
let dialog=fs.readFileSync('frontend/src/ParameterDialog.vue','utf8').replace('<p>{{note}}</p>',"<p>{{note||(transactional?'取消或关闭放弃本次修改；应用只接受参数，不提交任务。':'此模块的保存与计算需通过明确操作执行。')}}</p>");
dialog=dialog.replace('<slot name="footer"><button @click="emit(\'update:open\',false)">完成编辑，返回工作区</button></slot>',`<slot name="footer"><template v-if="transactional"><button @click="emit('update:open',false)">取消</button><button class="primary" @click="emit('apply')">应用参数</button></template><button v-else @click="emit('update:open',false)">关闭</button></slot>`);
fs.writeFileSync('frontend/src/ParameterDialog.vue',dialog);
let report=[];
for(const name of ['SourceStudy','SourceAnalysis','SequenceWorkspace','ScenarioWorkspace','DeviceDispatch','RandomBalance','AnnualWorkspace','NativePipeline','DisasterWorkspace','RestorationWorkspace','StrategyWorkspace','ModuleWorkspace']){
 let source=fs.readFileSync('frontend/src/'+name+'.vue','utf8');const script=source.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];
 const start=source.indexOf('<ParameterDialog'),end=source.indexOf('</ParameterDialog>',start);if(start<0||end<0)throw Error(name+' 缺少参数窗口');const modal=source.slice(start,end);
 const ast=ts.createSourceFile('s.ts',script,ts.ScriptTarget.Latest,true,ts.ScriptKind.TS);const refNames=new Set();
 for(const n of ast.statements)if(ts.isVariableStatement(n))for(const d of n.declarationList.declarations)if(ts.isIdentifier(d.name)&&d.initializer&&/^ref(?:<|\()/.test(d.initializer.getText(ast)))refNames.add(d.name.text);
 const fields=[...new Set([...modal.matchAll(/v-model(?:\.[a-z]+)?="([a-zA-Z_$][\w$]*)/g)].map(m=>m[1]).filter(n=>refNames.has(n)&&!['settingsOpen','setupOpen','settingsTab','tab','editorSection'].includes(n)))];
 if(!fields.length){report.push(name+': 无可自动接入的局部参数，保留原语义');continue}
 const open=modal.match(/v-model:open="([\w]+)"/)[1];
 source=source.replace('<script setup lang="ts">',"<script setup lang=\"ts\">\nimport {useParameterTransaction} from './useParameterTransaction';");
 source=source.replace('</script>',`const commitSettings=useParameterTransaction(${open},{${fields.join(',')}});\n</script>`);
 source=source.replace('<ParameterDialog','<ParameterDialog transactional @apply="commitSettings()"');
 for(const n of ast.statements)if(ts.isFunctionDeclaration(n)&&n.name){const name=n.name.text;if(/^(run|generate|submit|calculate|save|queue)/.test(name)&&n.body){const marker=n.getText(ast).slice(0,n.getText(ast).indexOf('{')+1);source=source.replace(marker,marker+'commitSettings(false);')}}
 fs.writeFileSync('frontend/src/'+name+'.vue',source);report.push(name+': '+fields.join(', '));
}
fs.writeFileSync('docs/参数草稿事务范围.txt','参数窗口取消/应用接入范围（2026-11-22）\n'+report.join('\n')+'\n运行命令接受当前参数作为本次提交输入；应用按钮不提交计算。工程与台账保存机制保持独立。\n');
