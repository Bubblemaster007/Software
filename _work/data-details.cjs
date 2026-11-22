const fs=require('fs');let app=fs.readFileSync('frontend/src/App.vue','utf8');app=app.replace('import ParameterDialog',"import DataDetails from './DataDetails.vue';\nimport {computed} from 'vue';\nimport ParameterDialog");
app=app.replace('</script>',`const detailRows=computed(()=>workspaceId.value.startsWith('data.')?csv.value.trim().split(/\\r?\\n/).slice(1).filter(Boolean).map(line=>{const cells=line.split(',');return {timestamp:cells[0],load_kw:cells[1],wind_kw:cells[2],pv_kw:cells[3]}}):result.value?.rows||[]);\n</script>`);
const start=app.indexOf('<div v-else>\n        <table v-if="result?.rows?.length">');
if(start>=0){const end=app.indexOf('</div>\n    </template>',start);app=app.slice(0,start)+'<div v-else><DataDetails :rows="detailRows"/></div>\n    '+app.slice(end+7)}else{
 // Match the explicit final details branch only, after the stage panel.
 const marker=app.indexOf('v-for="r in result.rows.slice(0, 168)"');if(marker<0)throw Error('明细模板未找到');let start=app.lastIndexOf('<div v-else>',marker),end=app.indexOf('</div>',marker)+6;app=app.slice(0,start)+'<div v-else><DataDetails :rows="detailRows"/></div>'+app.slice(end);
}
fs.writeFileSync('frontend/src/App.vue',app);
