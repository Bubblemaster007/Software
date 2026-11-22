import {ref,watch,onBeforeUnmount,type Ref} from 'vue';
export function useWorkflowProgress(project:Ref<any>,route:Ref<string>){
 const snapshot=ref<any>(null),ready=ref(false),error=ref(false);let generation=0;let timer:ReturnType<typeof setTimeout>|undefined;let controller:AbortController|undefined;
 async function refresh(){
  clearTimeout(timer);controller?.abort();const g=++generation,id=project.value?.id;
  if(!id){snapshot.value=null;ready.value=false;return}
  controller=new AbortController();
  try{const r=await fetch('/api/workflow-progress/'+encodeURIComponent(id),{signal:controller.signal});if(!r.ok)throw Error('进度读取失败');const data=await r.json();if(g!==generation||id!==project.value?.id)return;snapshot.value=data;ready.value=true;error.value=false}
  catch(e){if(g!==generation)return;error.value=true;ready.value=false}
  finally{if(g===generation)timer=setTimeout(refresh,3000)}
 }
 watch(()=>project.value?.id,()=>{snapshot.value=null;ready.value=false;error.value=false;refresh()},{immediate:true});
 watch([()=>project.value?.revision,route],refresh);
 onBeforeUnmount(()=>{++generation;clearTimeout(timer);controller?.abort()});
 return {snapshot,ready,error,refresh};
}
