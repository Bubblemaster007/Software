from pathlib import Path
p=Path('软件开发进展.txt');s=p.read_text(encoding='utf-8')
marker='一、当前总体进展'
current='历史数据导入（2026-11-22修复）：外部CSV可自动识别time/load/wind_power/solar_power及标准四列、列顺序、引号和常用分隔符；预览后明确应用。支持UTF-8/GB18030及毫秒时间戳。气象/质量附加列保留在原文件并记录字段，不自动接入算法；时间、功率不补值、不缩放，异常明确报错。年度输入自动选用汇总模式，网络168小时限制保持。\n\n'
assert marker in s
s=s.replace(marker,current+marker,1)
s+='\n2026-11-22 历史文件格式兼容修复：增加source_import.py预览接口，DataWorkspace读取原始历史列并按明确映射转换；修复毫秒日期校验。25项后端回归、前端时序及类型/生产构建通过；真实阿拉山口2023/2025与ExtremeScene FY2019原文件通过接口，8760行逐值逐时间一致。已生成data/import-ready副本，原始文件未改写。浏览器上传交互本次未验，详见docs/历史数据导入兼容修复_20261122.txt。\n'
p.write_text(s,encoding='utf-8')
for path in [Path('docs/平台菜单逻辑说明.txt'),Path('C:/Users/13411/Desktop/末端保供项目/软件开发/平台菜单逻辑说明.txt')]:
 s=path.read_text(encoding='utf-8');s+='\n2026-11-22导入更新：外部历史CSV支持time/load/wind_power/solar_power、多余气象列及UTF-8/GB18030，预览列映射后明确应用；标准化不改变功率与时间序列。超过168小时选汇总模式；网络原限制不变。\n';path.write_text(s,encoding='utf-8')
