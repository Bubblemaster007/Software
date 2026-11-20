"""Build an offline comparison report from immutable calculation records."""
from html import escape
import hashlib,json

def comparison_report(a,b):
 def show(value):
  if value is None:return '未记录'
  if isinstance(value,(dict,list)):return json.dumps(value,ensure_ascii=False)
  return str(value)
 def table(headers,rows):
  return '<table><tr>'+''.join('<th>'+escape(h)+'</th>' for h in headers)+'</tr>'+''.join('<tr>'+''.join('<td>'+escape(show(cell))+'</td>' for cell in row)+'</tr>' for row in rows)+'</table>'
 checks=[('网络拓扑与参数','network'),('输入时序','input_csv'),('模型','model'),('算法版本','algorithm'),('网络接入与电压约束','network_parameters'),('支路容量','branch_limit_kw'),('全局故障支路','failed_lines'),('运行阶段','stages'),('故障场景','scenario_id'),('生产序列引用','production_sequence_id')]
 def condition(record,key):
  if key=='network_parameters':return {'wind_node':18,'pv_node':30,'voltage_min_pu':.95,'voltage_max_pu':1.05,'linear_voltage_guard_pu':.955,**record.get(key,{})}
  return record.get(key)
 differences=[label for label,key in checks if condition(a,key)!=condition(b,key)]
 notice=('两次计算条件不同：'+'、'.join(differences)+'。数值仅供并列查看，不能直接归因于配置改善。') if differences else '输入时序、模型版本、支路约束、运行阶段、故障场景及生产序列引用一致，可结合资源参数差异评估效果。'
 html='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>末端保供计算对比报告</title><style>body{font:14px sans-serif;color:#234;max-width:1200px;margin:32px auto}table{border-collapse:collapse;width:100%;margin:18px 0}td,th{border:1px solid #bcd;padding:8px;text-align:left;word-break:break-word}th{background:#eaf3f3}.notice{background:#eef5f5;padding:16px}p{line-height:1.8}@media print{body{margin:10px}}</style><h1>末端保供计算对比报告</h1><p class="notice">'+escape(notice)+'</p>'
 html+='<h2>计算来源</h2>'+table(['项目','基准计算','对比计算'],[(label,a.get(key),b.get(key)) for label,key in [('计算编号','id'),('计算时间','created'),('工程编号','project_id'),('工程版本','project_revision'),('模型','model'),('算法版本','algorithm'),('适用范围','scope'),('故障场景','scenario_id'),('生产序列','production_sequence_id')]])
 html+='<h2>汇总指标</h2>'
 metrics=[('最大功率缺额 / kW','max_power_deficit_kw'),('缺供电量 / kWh','expected_energy_deficit_kwh'),('关键负荷电量满足率 / 比例','critical_load_supply_ratio'),('缺供时段占比 / 比例','loss_of_load_probability')]
 values=[]
 for label,key in metrics:
  x=a['metrics'].get(key);y=b['metrics'].get(key)
  values.append((label,x,y,y-x if isinstance(x,(int,float)) and isinstance(y,(int,float)) else '未记录'))
 html+=table(['指标','基准','对比','变化（对比−基准）'],values)
 html+='<h2>资源参数</h2>'+table(['参数（功率kW、能量kWh、其余比例）','基准','对比'],[(key,a['parameters'].get(key),b['parameters'].get(key)) for key in dict.fromkeys([*a['parameters'],*b['parameters']])])
 html+='<p>负荷分类依据各次计算的关键与重要负荷占比。占比变化时，分类满足率不能直接解释为同一批负荷的改善。缺供时段占比属于单轨迹统计，不表示经校准的灾害概率；规划与动态稳定结论须另行复核。</p>'
 html+='<h2>运行与故障条件</h2>'+table(['条件','基准','对比'],[(label,a.get(key),b.get(key)) for label,key in checks if key!='input_csv'])
 html+='<h2>输入源荷校验值</h2>'+table(['类型','SHA256'],[(label,hashlib.sha256(r.get('input_csv','').encode('utf-8')).hexdigest()) for label,r in [('基准',a),('对比',b)]])
 html+='<p>报告由两份已保存计算快照生成，不触发重新计算。完整逐时曲线和场景容量请结合各自计算报告与CSV复核。</p></html>'
 return html
