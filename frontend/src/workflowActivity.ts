import {ref} from 'vue';
export const workflowActivity=ref<Record<string,number>>({});
/** Keep synchronous HTTP computations visible even when their view is closed. */
export function beginWorkflowActivity(projectId:string|undefined,stage:string){
 if(!projectId)return ()=>{};
 const key=projectId+':'+stage;workflowActivity.value[key]=(workflowActivity.value[key]||0)+1;let finished=false;
 return ()=>{if(finished)return;finished=true;workflowActivity.value[key]=Math.max(0,(workflowActivity.value[key]||0)-1)};
}
