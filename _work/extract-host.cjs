const fs=require('fs'),ts=require('../frontend/node_modules/typescript');
let app=fs.readFileSync('frontend/src/App.vue','utf8');const script=app.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1];
const start=app.indexOf('<p v-if="error"');const end=app.indexOf('<template #right>');let host=app.slice(start,end);
const library=app.slice(app.lastIndexOf('<ParameterDialog v-model:open="scenarioLibraryOpen"'),app.lastIndexOf('</template>'));
host+=library;
const names=script.match(/const \{([^}]+)\}=context;/)[1];
function importsFor(source,body){const a=ts.createSourceFile('s.ts',source,ts.ScriptTarget.Latest,true);return a.statements.filter(ts.isImportDeclaration).flatMap(n=>{const c=n.importClause;if(!c)return [];let items=[];if(c.name&&new RegExp('\\b'+c.name.text+'\\b').test(body))items.push(c.name.text);if(c.namedBindings&&ts.isNamedImports(c.namedBindings)){const es=c.namedBindings.elements.filter(e=>new RegExp('\\b'+e.name.text+'\\b').test(body));if(es.length)items.push('{'+es.map(e=>e.getText(a)).join(',')+'}')}return items.length?['import '+(c.isTypeOnly?'type ':'')+items.join(',')+' from '+n.moduleSpecifier.getText(a)+';']:[]}).join('\n')}
const hostNames=names.split(',').filter(n=>new RegExp('\\b'+n+'\\b').test(host)).join(',');
const hostBody=`import {useEngineeringContext} from './useEngineeringProject';\nconst {${hostNames}}=useEngineeringContext();\nconst scenarioLibraryOpen=ref(false);const scenarioLibraryTab=ref('典型场景库');\nwatch(()=>project.value?.id,()=>{scenarioLibraryOpen.value=false;scenarioLibraryTab.value='典型场景库'});`;
fs.writeFileSync('frontend/src/WorkspaceHost.vue','<script setup lang="ts">\n'+importsFor(script,hostBody+host)+'\nimport {watch} from \'vue\';\n'+hostBody+'\n</script>\n<template>'+host+'</template>');
app=app.slice(0,start)+'<WorkspaceHost/>'+app.slice(end);
app=app.replace(library,'');app=app.replace("const scenarioLibraryOpen=ref(false);const scenarioLibraryTab=ref('典型场景库');",'');
const aScript=app.match(/<script setup lang="ts">([\s\S]*?)<\/script>/)[1],template=app.slice(app.indexOf('<template>'));
let body=aScript.replace(/^import .*;\r?\n/gm,'');
body=body.replace(/const \{([^}]+)\}=context;/,(_,list)=>'const {'+list.split(',').filter(n=>new RegExp('\\b'+n+'\\b').test(template)).join(',')+'}=context;');
app=app.replace(aScript,'\n'+importsFor(aScript,body+template)+"\nimport WorkspaceHost from './WorkspaceHost.vue';\n"+body+'\n');
fs.writeFileSync('frontend/src/App.vue',app);
