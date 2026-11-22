const fs=require('fs');
const p='C:/Users/13411/Desktop/software/frontend/src/App.vue';
let s=fs.readFileSync(p,'utf8');
s=s.replace('<ScenarioWorkspace v-if="project" :project-id="project.id" :csv="csv" @apply="applyScenario"/>','<ScenarioWorkspace v-if="project" :project-id="project.id" :csv="csv" :open-settings="scenarioSettingsOpen" @apply="applyScenario"/>');
fs.writeFileSync(p,s);
