const fs=require('fs');let d=fs.readFileSync('frontend/src/DeviceDispatch.vue','utf8').replace("import StudyTasks from './StudyTasks.vue';",'');
d=d.replace('const props=defineProps<{projectId:string}>();', 'const props=defineProps<{projectId:string}>();const emit=defineEmits<{task:[id:string]}>();');
d=d.replace('if(current===token)backgroundJob.value=j.id;', "if(current===token){backgroundJob.value=j.id;emit('task',j.id)}");
d=d.replace('<StudyTasks v-if="backgroundJob" :project-id="projectId" :focus-id="backgroundJob"/>', '<button v-if="backgroundJob" @click="emit(\'task\',backgroundJob)">查看当前后台调度任务</button>');
d=d.replace('系统与接口 → 计算任务','视图 → 计算任务面板');fs.writeFileSync('frontend/src/DeviceDispatch.vue',d);
let p=fs.readFileSync('frontend/src/useEngineeringProject.ts','utf8');p=p.replace('const validation = ref<string[]>([]);','const taskFocus=ref(\'\');\n  const validation = ref<string[]>([]);');
p=p.replace('validation.value = [];',"validation.value = [];taskFocus.value='';");p=p.replace('return {\n','return {\n    taskFocus,');fs.writeFileSync('frontend/src/useEngineeringProject.ts',p);
let b=fs.readFileSync('frontend/src/BalanceWorkspace.vue','utf8');b=b.replace('const {','const {taskFocus,layout,');b=b.replace('<DeviceDispatch\n', '<DeviceDispatch @task="id=>{taskFocus=id;layout.bottom.value=\'计算任务\'}"\n');fs.writeFileSync('frontend/src/BalanceWorkspace.vue',b);
let t=fs.readFileSync('frontend/src/TaskPanel.vue','utf8').replace('const { project,', 'const { taskFocus,project,');t=t.replace(':project-id="project?.id || \'\'"', ':focus-id="taskFocus" :project-id="project?.id || \'\'"');fs.writeFileSync('frontend/src/TaskPanel.vue',t);
