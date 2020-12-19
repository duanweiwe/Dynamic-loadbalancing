import requests
import json
import numpy as np
import math
import time
import copy
import _thread
import operator


site="http://192.168.40.133:8080"
flow_count=[1]		#流计数 用于生成流的name字段 避免重复
					#直接定义变量flow_count putFlow内部发生莫名其妙错误 不知道为什么

#描述拓扑,计算新路由时比较方便,形如:{"switch_id1":{"switch_id2":{"src_port":s_port,"d_port":d_port,"bandWidth":bandWidth}}}
graph={}

#描述拓扑,寻找原始路由时比较方便，形如{"switch_id1":{"port_no":"switch_id2"}}
graph_port={}

#cookie与name对应关系 使用/wm/core/switch/1/flow/json获取的流表不包含name字段，所以要做映射
cookie2name={}

def empty(x):
	if(x):
		return False
	else:
		return True

def getTopo():
	#获取交换机DPID
	url=site+"/wm/topology/switchclusters/json"
	response = requests.get(url)
	if(response.ok):
		data=json.loads((response.content).decode("utf-8"))
		for dpid in list(data.values())[0]:
			graph[dpid]={}
			graph_port[dpid]={}
	else:
		print("get Topo error")
		exit()

	#获取链路
	url=site+"/wm/topology/links/json"
	response = requests.get(url)
	if(response.ok):
		data=json.loads((response.content).decode("utf-8"))
		for link in data:
			src=link['src-switch']
			src_port=str(link['src-port'])
			dst=link['dst-switch']
			dst_port=str(link['dst-port'])
			graph[src][dst]={"s_port":src_port,"d_port":dst_port,"bandWidth":0}
			graph[dst][src]={"s_port":dst_port,"d_port":src_port,"bandWidth":0}
			graph_port[src][src_port]=dst
			graph_port[dst][dst_port]=src	

	else:
		print("get Topo error")
		exit()




def DFS(graph,pre_path,flag,pre_node,end_node,paths):
	if(flag[pre_node]):
		return
	if(pre_node==end_node):
		pre_path.append(pre_node)
		paths.append(copy.copy(pre_path))
		pre_path.pop()
		return
	pre_path.append(pre_node)
	flag[pre_node]=True
	for node in graph[pre_node]:
		DFS(graph,pre_path,flag,node,end_node,paths)
	pre_path.pop()
	flag[pre_node]=False
	return

def get_score(path,paths,pack_bandwidth):
	#首先求瓶颈链路剩余带宽
	#print(path)
	path_bandwidth=[graph[path[i]][path[i+1]]["bandWidth"] for i in range(len(path)-1)]
	minBwRest=min(path_bandwidth)
	
	#平均链路带宽
	n=len(path)-1
	meanBwRest=sum(path_bandwidth)/n

	#所有链路剩余带宽标准差
	arr=[]
	for p in paths:
		if(path is p):
			temp_arr=[graph[path[i]][path[i+1]]["bandWidth"]-pack_bandwidth for i in range(len(path)-1)]
		else:
			temp_arr=[graph[path[i]][path[i+1]]["bandWidth"] for i in range(len(path)-1)]
		arr.extend(temp_arr)
	BwRestSd=np.std(arr,ddof=1)

	
	#加权计算三个参数
	a=0.2
	b=0.5
	c=0.3

	score=a*math.log(minBwRest+1,10)+b*math.log(meanBwRest+1,10)-c*math.log(BwRestSd+1,10)
	return score

def route(src_id,dst_id,pack_bandwidth):
	#print(src_id,dst_id)
	#查找发现所有路径
	paths=[]
	flag={key:False for key in graph}
	pre_path=[]
	DFS(graph,pre_path,flag,src_id,dst_id,paths)

	scores=[]
	for path in paths:
		score=get_score(path,paths,pack_bandwidth)
		scores.append(score)
	#print(scores)
	index=scores.index(max(scores))

	#print(paths[index])
	return paths[index]

#找出原先的路由
def findRoute(tables,src_ip,dst_ip,pack_bandwidth):
	#获取主机列表
	src_node=""
	dst_node=""
	url=site+"/wm/device/"
	response = requests.get(url)
	if(response.ok):
		data=json.loads((response.content).decode("utf-8"))
		for host in data:
			if(empty(host["ipv4"])):
				continue
			for ipv4 in host["ipv4"]:
				if(ipv4==src_ip):
					src_node=host["attachmentPoint"][0]["switchDPID"]
				elif(ipv4==dst_ip):
					dst_node=host["attachmentPoint"][0]["switchDPID"]
	else:
		print("get device error")
		exit()

	pre_route_table=[]
	#将所有流表找出
	pre_node=src_node
	while(True):
		if(pre_node=="break"):
			break
		for flow in tables[pre_node]["flows"]:
			if(flow["match"]["ipv4_src"]==src_ip and flow["match"]["ipv4_dst"]==dst_ip):
				output=flow["instructions"]["instruction_apply_actions"]["actions"].split("output=")[1]
				pre_route_table.append({"table":pre_node,"flow":flow,"output":output})
				if(pre_node==dst_node):
					pre_node="break"
					break
				pre_node=graph_port[pre_node][output]
				break
	
	#print(pre_route_table)

	#释放原先路由上的带宽
	for i in range(len(pre_route_table)-1):
		graph[pre_route_table[i]["table"]][pre_route_table[i+1]["table"]]["bandWidth"]+=pack_bandwidth

	return pre_route_table,src_node,dst_node

def putFlowTable(pre_tables,path,src_ip,dst_ip,src_mac,dst_mac):

	last_path=[x["table"] for x in pre_tables]
	if(operator.eq(last_path,path)):
		print("路由前后一致，不操作")
		return
	#对原先流表进行删除
	url=site+"/wm/staticflowpusher/json/delete"
	for temp in pre_route_table:
		if temp["flow"]["cookie"] in cookie2name:
			name=cookie2name[temp["flow"]["cookie"]]
			jsonData=json.dumps({"name":name})
			requests.post(url,jsonData)

	url=site+"/wm/staticflowpusher/json"
	#生成要下发流表
	jsonList=[]
	for i in range(len(path)):
		if(i!=(len(path)-1)):
			action=graph[path[i]][path[i+1]]["s_port"]
		else:
			action=pre_tables[-1]["output"]

		flow={
			"switch":path[i],
			"name":"flow"+str(flow_count[0]),
			"cookie":"0",
			"priority":"32768",
			"eth_type":"0x0800",
			"ipv4_src":src_ip,
			"ipv4_dst":dst_ip,
			"eth_src":src_mac,
			"eth_dst":dst_mac,
			"active":"true",
			"actions":"output="+action
			}
		flow_count[0]+=1
		jsonData=json.dumps(flow)
		jsonList.append(jsonData)
	
	#从尾端更新流表
	for jsonData in jsonList:
		print(str(jsonData))
		response=requests.post(url,str(jsonData))
	
	#更新cookie name映射
	url=site+"/wm/staticflowpusher/list/all/json"
	cookie2name.clear()
	response = requests.get(url)
	if(response.ok):
		data=json.loads((response.content).decode("utf-8"))
		for switch in data:
			for flow_item in data[switch]:
				flow_name=list(flow_item.keys())[0]
				cookie2name[flow_item[flow_name]["cookie"]]=flow_name
	else:
		print("get flowtable list error")
		exit()
	print(cookie2name)

#监听模块
def detect():
	totalBandWidth=10000000000	#总带宽 固定10Gbps
	while(True):
		#获取各链路带宽
		max=["","",-1]	#记录最拥塞的链路 三元组(switch_id,port,bandwidth)
		url=site+"/wm/statistics/bandwidth/all/all/json"
		response = requests.get(url)
		if(response.ok):
			data=json.loads((response.content).decode("utf-8"))
			#找到负载最大的链路
			for item in data:
				if(item["port"]=="local"):
					continue
				if(item["port"] not in graph_port[item["dpid"]]):		#主机-边缘交换机 略过
					continue
				end_point=graph_port[item["dpid"]][item["port"]]
				graph[item["dpid"]][end_point]["bandWidth"]=totalBandWidth-int(item["bits-per-second-tx"])
				if(int(item["bits-per-second-tx"])>max[2]):
					max=[item["dpid"],item["port"],int(item["bits-per-second-tx"])]
		else:
			print("get flow list error")
			exit()
		
		if(not max[0]):
			print("未发现数据流")
			time.sleep(2)
			return None,None,None,None,None,None
		#break	#测试用
		#判断触发条件
		if(max[2]>=totalBandWidth*0.5):
			break
		else:
			time.sleep(2)

	#print(max)
	#获取所有流表
	url=site+"/wm/core/switch/all/flow/json"
	response = requests.get(url)
	if(response.ok):
		tables=json.loads((response.content).decode("utf-8"))
	else:
		print("get all_flow list error")
		exit()
	
	#在相应的链路上选定一个流用作重路由
	max_flow=[{},-1]	#记录带宽最大的流(flow,max_bandwidth)二元组

	for flow in tables[max[0]]["flows"]:
		#找出flow中output为max[1] 且 eth_type为0x0800
		output=flow["instructions"]["instruction_apply_actions"]["actions"].split("output=")[1]
		if(output==max[1] and flow["match"]["eth_type"]=="0x0x800"):
			key=flow["match"]["ipv4_src"]+flow["match"]["ipv4_dst"]
			if(key not in flow_bw[max[0]] or flow_bw[max[0]][key]["bandwidth"]==0):
				continue
			bw=flow_bw[max[0]][key]["bandwidth"]
			#print(bw)
			if(bw>max_flow[1]):
				max_flow[0]=flow
				max_flow[1]=bw
			
			#max_flow[0]=flow		#测试用
			#max_flow[1]=max[2]

	if(max_flow[0]):
		src_ip=max_flow[0]["match"]["ipv4_src"]
		dst_ip=max_flow[0]["match"]["ipv4_dst"]
		src_mac=max_flow[0]["match"]["eth_src"]
		dst_mac=max_flow[0]["match"]["eth_dst"]
		#返回流流表、src_ip,dst_ip,src_mac,dst_mac
		return tables,src_ip,dst_ip,src_mac,dst_mac,max_flow[1]
	else:

		print("未侦听到拥塞")
		time.sleep(2)
		return None,None,None,None,None,None


def getFlowData():
	global flow_bw
	while(True):
		response = requests.get("http://192.168.40.133:8080/wm/core/switch/all/flow/json")
		last_record=flow_bw
		new_record={}
		if (response.ok):
			jsData = json.loads(response.content)
			for switch in jsData:
				if(switch not in new_record):
					new_record[switch]={}
				for flow in jsData[switch]['flows']:
					if (flow['match'] and flow['match']['eth_type']=="0x0x800"):
	#					print switch, flow['match']['ipv4_src'], flow['match']['ipv4_dst'], flow['byteCount']
						key=flow['match']['ipv4_src']+flow['match']['ipv4_dst']
						if(switch not in last_record or key not in last_record[switch]):
							new_record[switch][key]={"bandwidth":int(flow['byteCount'])*8,"byte":int(flow['byteCount'])}
						else:
							new_record[switch][key]={"bandwidth":(int(flow['byteCount'])-last_record[switch][key]["byte"])*8,"byte":int(flow['byteCount'])}
			
			flow_bw=new_record
			#print(flow_bw)
			#print("")
		else:
			response.raise_for_status()

		time.sleep(1)
#main
getTopo()

#启动带宽侦听功能
url=site+"/wm/statistics/config/enable/json"
ret=requests.post(url)

flow_bw={}
try:
	_thread.start_new_thread(getFlowData,())
except:
	print("create thread error")
	exit()

while(True):
	#监控模块
	tables,src_ip,dst_ip,src_mac,dst_mac,pack_bandwidth=detect()
	if(tables is None):
		continue
	#查找出原先的路由
	pre_route_table,src_id,dst_id=findRoute(tables,src_ip,dst_ip,pack_bandwidth)
	#重新计算路由
	path=route(src_id,dst_id,pack_bandwidth)
	#下发新流表 删除旧流表
	putFlowTable(pre_route_table,path,src_ip,dst_ip,src_mac,dst_mac)
	time.sleep(2)