const fs=require('fs');let s=fs.readFileSync('frontend/src/App.vue','utf8');
const script=s.slice(0,s.indexOf('</script>')+9);const root=s.lastIndexOf('<template>\n  <EngineeringLayout');if(root<0)throw Error('找不到完整主模板');
let template=s.slice(root);const marker=template.indexOf('v-for="r in result.rows.slice(0, 168)"');if(marker<0)throw Error('找不到原明细表');
const start=template.lastIndexOf('<div v-else>',marker),end=template.indexOf('</div>',marker)+6;
template=template.slice(0,start)+'<div v-else><DataDetails :rows="detailRows"/></div>'+template.slice(end);
fs.writeFileSync('frontend/src/App.vue',script+'\n'+template);
