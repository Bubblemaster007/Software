from pathlib import Path
p=Path('frontend/src/DataWorkspace.vue');s=p.read_text(encoding='utf-8-sig')
s=s.replace('const pending=ref<{name:string;csv:string}|null>(null)','const pending=ref<{name:string;csv:string;source:any}|null>(null)')
s=s.replace('csv.value=pending.value.csv;appliedCsv.value=csv.value;pending.value=null;',"const imported=pending.value;csv.value=imported.csv;appliedCsv.value=csv.value;emit('source',imported.csv,imported.source);pending.value=null;")
start=s.index('async function upload(e:Event)');end=s.index('\n',start)
s=s[:start]+'''async function upload(e:Event){const input=e.target as HTMLInputElement;const request=++uploadRequest;pending.value=null;try{const f=input.files?.[0];if(!f)return;if(f.size>6000000)throw Error('CSV文件不得超过6MB');const bytes=await f.arrayBuffer();let text:string;try{text=new TextDecoder('utf-8',{fatal:true}).decode(bytes)}catch{text=new TextDecoder('gb18030',{fatal:true}).decode(bytes)}const response=await fetch('/api/source-import/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text,filename:f.name})});const data=await response.json();if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));if(request!==uploadRequest)return;pending.value={name:f.name,csv:data.csv,source:data.source_import};message.value='已识别历史数据并转换为标准四列，原始功率未缩放；请预览后明确应用。'}catch(e){if(request===uploadRequest)message.value=e instanceof Error?e.message:String(e)}finally{input.value=''}}'''+s[end:]
s=s.replace('<p>待导入{{preview.count}}条，当前工作区{{rows.length}}条。应用后替换当前源荷输入。</p>','<p>待导入{{preview.count}}条，当前工作区{{rows.length}}条。应用后替换当前源荷输入。</p><p>列映射：{{pending.source.column_mapping}}。附加列留在原文件中：{{pending.source.extra_columns.join("、")||"无"}}。</p><p>单位按原文件约定为kW，未自动缩放；请核实原始单位后应用。</p>')
p.write_text(s,encoding='utf-8')
p=Path('frontend/src/useEngineeringProject.ts');s=p.read_text(encoding='utf-8-sig');anchor='function applyHistoricalInput(value: string, source: any) {'
assert anchor in s
s=s.replace(anchor,anchor+'''
    if(source.kind==='external'){
      applyProjected(value);stages.value=[];eventCsv.value='';selectedScenario.value=null;failedLines.value='';
      sourceImport.value=source;sourceImportCsv.value=value;
      if(inspectTimeSeries(value).count>168)model.value='aggregate';
      projectMessage.value='历史文件已转换并应用；功率未缩放，请核实单位和资源参数后保存工程';return;
    }
''')
s=s.replace('model.value = "case33";\n    sourceImport.value = provenance;', 'model.value = inspectTimeSeries(value).count>168?"aggregate":"case33";\n    sourceImport.value = provenance;')
p.write_text(s,encoding='utf-8')
