/** Compare the implicit full-horizon stage with the equivalent frozen stage. */
export function stageSignature(stages:any[],hours:number,failedLines:number[]=[]){
 const value=stages.length?stages:[{name:'全时域',end_hour:hours,grid_ratio:1,emergency_ratio:1,failed_lines:failedLines}];
 return JSON.stringify(value.map(s=>({name:s.name?.trim(),end_hour:s.end_hour,grid_ratio:s.grid_ratio===undefined?1:s.grid_ratio,emergency_ratio:s.emergency_ratio===undefined?1:s.emergency_ratio,failed_lines:[...(s.failed_lines||[])].sort((a,b)=>a-b)})));
}
