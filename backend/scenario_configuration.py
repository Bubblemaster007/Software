"""Read-only freshness evidence for explicitly confirmed frontend scenarios."""
import json
def csv_signature(value):
 value=value.encode('utf-16-le');result=2166136261
 for index in range(0,len(value),2):result=((result^(value[index]+256*value[index+1]))*16777619)&0xffffffff
 return format(result,'x')
def configuration_matches(config,state):
 snapshot=config.get('snapshot',{})
 return bool(snapshot) and snapshot.get('csvSignature')==csv_signature(state.get('csv','')) and snapshot.get('network')==state.get('network') and snapshot.get('condition')==state.get('operatingCondition') and snapshot.get('scenarioId')==state.get('scenarioId') and snapshot.get('productionId')==state.get('productionSequenceId') and snapshot.get('failedLines',[])==([int(n.strip()) for n in state.get('failedLines','').split(',') if n.strip()]) and snapshot.get('stages',[])==state.get('stages',[])
