"""Editable radial networks; validation before solver construction."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from fastapi import APIRouter

router = APIRouter(prefix='/api/network')
class Node(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 node:int=Field(ge=1,le=99999)
 name:str=Field('',max_length=100)
 type:int=1
 pd_kw:float=Field(0,ge=0,le=1000000)
 qd_kvar:float=Field(0,ge=0,le=1000000)
 vm_init_pu:float=Field(1,ge=.8,le=1.2)
class Line(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 line:int=Field(ge=1,le=99999)
 name:str=Field('',max_length=100)
 from_node:int=Field(ge=1)
 to_node:int=Field(ge=1)
 r_ohm:float=Field(ge=0,le=1000)
 x_ohm:float=Field(ge=0,le=1000)
 capacity_kva:float|None=Field(None,gt=0,le=1000000)
 rate_a:float=Field(0,ge=0,le=1000000)
 status:int=Field(1,ge=0,le=1)
class Network(BaseModel):
 model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
 name:str=Field('自定义电网',min_length=1,max_length=100)
 source:str=Field('用户录入；参数需核实',max_length=1000)
 base_voltage_kv:float=Field(10,gt=0,le=500)
 nodes:list[Node]=Field(min_length=2,max_length=100)
 lines:list[Line]=Field(min_length=1,max_length=200)
 @model_validator(mode='after')
 def topology(self):
  ids={n.node for n in self.nodes}
  if len(ids)!=len(self.nodes) or 1 not in ids:raise ValueError('节点编号须唯一，且包含根节点1')
  if len({l.line for l in self.lines})!=len(self.lines):raise ValueError('线路编号不得重复')
  edges=set(); adjacency={n:[] for n in ids}
  for l in self.lines:
   if l.from_node not in ids or l.to_node not in ids or l.from_node==l.to_node:raise ValueError('线路端点须为两个已存在的不同节点')
   edge=tuple(sorted((l.from_node,l.to_node)))
   if edge in edges:raise ValueError('不支持重复或并联线路')
   edges.add(edge)
   if l.status:
    adjacency[l.from_node].append(l.to_node);adjacency[l.to_node].append(l.from_node)
  if sum(l.status for l in self.lines)!=len(ids)-1:raise ValueError('投运线路须构成连通辐射树；检修断线请使用故障设置')
  seen={1}; queue=[1]
  for n in queue:
   for other in adjacency[n]:
    if other not in seen:seen.add(other);queue.append(other)
  if seen!=ids:raise ValueError('投运网络存在孤立节点或环路')
  if sum(n.pd_kw for n in self.nodes)<=0:raise ValueError('节点有功负荷之和须大于0')
  # Normalize tree orientation away from root for the AC forward/backward sweep.
  depth={n:i for i,n in enumerate(queue)}
  for l in self.lines:
   if l.status and depth[l.from_node]>depth[l.to_node]:l.from_node,l.to_node=l.to_node,l.from_node
  return self
@router.post('/validate')
def validate(network:Network):return network.model_dump()
