const fs=require('fs');
const p='C:/Users/13411/Desktop/software/frontend/src/ConfigOverview.vue';
let s=fs.readFileSync(p,'utf8');
s=s.replace("@click=\"emit('navigate','配置结果')\">应用方案", "@click=\"emit('navigate','配置结果')\">查看配置结果");
s=s.replace(':class="{active:section===target||label===section}" @click="emit(\'navigate\',target as string)"',':class="{active:activeTab===label}" @click="selectTab(label,target as string)"');
s=s.replace('>优化计算</button>','>进入优化结果</button>');
fs.writeFileSync(p,s);
