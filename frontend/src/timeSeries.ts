const header='timestamp,load_kw,wind_kw,pv_kw';
function hour(value:string,whole=true):number {
 const match=value.trim().match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?$/);
 if(!match)throw Error('时间须采用年-月-日 时:分格式');
 const [,y,m,d,h,minute,second='0',fraction='0']=match;
 const date=new Date(Date.UTC(+y,+m-1,+d,+h,+minute,+second));
 if(date.getUTCFullYear()!==+y||date.getUTCMonth()!==+m-1||date.getUTCDate()!==+d||+h>23||+minute>59||+second>59||(whole&&(+minute!==0||+second!==0)))throw Error('请输入有效的整点时间');
 if(whole&&Number(fraction)!==0)throw Error('请输入有效的整点时间');
 return date.getTime()+Number('0.'+fraction)*1000;
}
export function appendHours(csv:string,start:string,count:number):string {
 if(!Number.isInteger(count)||count<1||count>8760)throw Error('新增小时数须为1至8760的整数');
 const lines=csv.replace(/^\uFEFF/,'').trim().split(/\r?\n/).filter(line=>line.trim());
 if(lines.length&&lines[0]!==header)throw Error('当前CSV表头不正确，请先修正或导入标准CSV');
 const rows=lines.slice(1);if(rows.length+count>8760)throw Error('总时序不得超过8760小时');
 let next=hour(start);
 if(rows.length){
  const times=rows.map(row=>{const cells=row.split(',');if(cells.length!==4)throw Error('当前时序应为四列，请先修正数据');return hour(cells[0])});
  if(times.some((time,i)=>i>0&&time-times[i-1]!==3600000))throw Error('当前时序不连续，请先修正后再追加');
  next=times[times.length-1]+3600000;
 }
 const added=Array.from({length:count},(_,i)=>new Date(next+i*3600000).toISOString().slice(0,19).replace('T',' ')+',0,0,0');
 return [header,...rows,...added].join('\n')+'\n';
}

export interface TimeSeriesIssue {row:number;message:string}
export function inspectTimeSeries(csv:string):{count:number;issues:TimeSeriesIssue[];totalIssues:number}{
 const lines=csv.replace(/^\uFEFF/,'').trim().split(/\r?\n/);
 const issues:TimeSeriesIssue[]=[];let totalIssues=0;
 const issue=(row:number,message:string)=>{totalIssues++;if(issues.length<20)issues.push({row,message})};
 if(lines[0]!==header)issue(1,'表头须为timestamp,load_kw,wind_kw,pv_kw');
 const rows=lines.slice(1).map((line,i)=>({line,row:i+2})).filter(item=>item.line.trim());
 if(rows.length<2||rows.length>8760)issue(0,'需提供2至8760条逐小时数据');
 let previous:number|undefined;
 for(const {line,row} of rows){
  const cells=line.split(',');
  if(cells.length!==4){issue(row,'应包含时间、负荷、风电、光伏四列');previous=undefined;continue}
  try{const time=hour(cells[0],false);if(previous!==undefined&&time-previous!==3600000)issue(row,'与上一条有效时间不相差1小时，请检查重复、倒序或缺失时段');previous=time}catch{issue(row,'时间格式或日期无效，请使用年-月-日 时:分:秒');previous=undefined}
  cells.slice(1).forEach((cell,i)=>{if(!cell.trim()||!Number.isFinite(Number(cell))||Number(cell)<0)issue(row,['负荷','风电','光伏'][i]+'须为有限非负数，不能留空')});
 }
 return {count:rows.length,issues,totalIssues};
}

