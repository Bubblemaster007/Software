$p='C:\Users\13411\Desktop\software\frontend\src\App.vue'
$s=[IO.File]::ReadAllText($p)
$idx=$s.IndexOf('<div v-show="subsection===')
if($idx -ge 0 -and $s.IndexOf('<ScenarioDashboard') -lt 0){$insert="<ScenarioDashboard v-if=\"subsection==='故障与恢复场景'\" :csv=\"csv\" :condition=\"operatingCondition\"/>";$s=$s.Insert($idx,$insert)}
$needle='<template v-if="result"><p class="notice" v-if="activeProductionId'
if($s.Contains($needle)){$s=$s.Replace($needle,'<template v-if="result"><ResultOverview :result="result" :condition="operatingCondition"/><p class="notice" v-if="activeProductionId')}
$needle='<EngineeringWorkspace v-if="inventorySections.includes(subsection)"'
if($s.Contains($needle)){$networkInsert="<NetworkSummary v-if=\"subsection==='电网拓扑'\" :network=\"customNetwork\"/><EngineeringWorkspace v-if=\"inventorySections.includes(subsection)\"";$s=$s.Replace($needle,$networkInsert)}
$configInsert="<template v-else-if=\"active==='源储协同配置'\"><ConfigOverview :project-id=\"project?.id||''\" :section=\"subsection\" @navigate=\"subsection=`$event\"/><InvestmentWorkspace :project-id=\"project?.id||''\" :section=\"subsection\"/></template>"
$s=[regex]::Replace($s,'<InvestmentWorkspace v-else-if="active===.*?/>',$configInsert,1)
$s=$s.Replace('<article><h3>03 / 供需时序曲线</h3>','<article v-show="workspacePanel===\'明细\'"><h3>03 / 供需时序曲线</h3>')
[IO.File]::WriteAllText($p,$s,[Text.Encoding]::UTF8)
Write-Output 'integrated'
