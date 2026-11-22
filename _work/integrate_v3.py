from pathlib import Path
p=Path(r'C:\Users\13411\Desktop\software\frontend\src\App.vue')
s=p.read_text(encoding='utf-8')
repls=[
 ("<EngineeringWorkspace v-if=\"inventorySections.includes(subsection)\"", "<NetworkSummary v-if=\"subsection==='电网拓扑'\" :network=\"customNetwork\"/><EngineeringWorkspace v-if=\"inventorySections.includes(subsection)\""),
 ("<div v-show=\"subsection==='故障与恢复场景'&&operatingCondition==='极端保供'\"><ScenarioWorkspace", "<ScenarioDashboard v-if=\"subsection==='故障与恢复场景'\" :csv=\"csv\" :condition=\"operatingCondition\"/><div v-show=\"subsection==='故障与恢复场景'&&operatingCondition==='极端保供'\"><ScenarioWorkspace"),
 ("<template v-if=\"result\"><p class=\"notice\" v-if=\"activeProductionId", "<template v-if=\"result\"><ResultOverview :result=\"result\" :condition=\"operatingCondition\"/><p class=\"notice\" v-if=\"activeProductionId\""),
 ("<InvestmentWorkspace v-else-if=\"active==='源储协同配置'\" :project-id=\"project?.id||''\" :section=\"subsection\"/>", "<template v-else-if=\"active==='源储协同配置'\"><ConfigOverview :project-id=\"project?.id||''\" :section=\"subsection\" @navigate=\"subsection=$event\"/><InvestmentWorkspace :project-id=\"project?.id||''\" :section=\"subsection\"/></template>"),
 ("<article><h3>03 / 供需时序曲线</h3>", "<article v-show=\"workspacePanel==='明细'\"><h3>03 / 供需时序曲线</h3>"),
]
for old,new in repls:
    if old not in s:
        print('MISSING',old[:80])
    else:
        s=s.replace(old,new,1)
p.write_text(s,encoding='utf-8')
print('done')
