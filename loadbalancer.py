#!/usr/bin/env python2

import requests
import json
import unicodedata
from subprocess import Popen, PIPE
import time
import networkx as nx
from sys import exit

# 方法：获取json数据
def getResponse(url,choice):

	response = requests.get(url)  #通过request接口获取
	if(response.ok):
		#获取不同类型的数据
		j_Data = json.loads(response.content)
		if(choice=="deviceInfo"):
			#交换机设备基本信息
			switch_Information(j_Data)
		elif(choice=="findSwitchLinks"):
			#两台交换机的路径
			find_Switch_Links(j_Data,switch[host_2])
		elif(choice=="linkTX"):
			#链路带宽信息
			link_TX(j_Data,portKey)

	else:
		response.raise_for_status()


def systemCommand(cmd):
	terminalProcess = Popen(cmd, stdout=PIPE, stderr=PIPE, shell=True)
	terminalOutput, stderr = terminalProcess.communicate()
	print ("\n***", terminalOutput, "\n")


# 定义流的格式的接口，构造流表时被调用
def flowRule(currentNode, flowCount, inPort, outPort, staticFlowURL):
	flow = {
		'switch':"00:00:00:00:00:00:00:" + currentNode,
	    "name":"flow" + str(flowCount),
	    "cookie":"0",
	    "priority":"32768",
	    "in_port":inPort,
		"eth_type": "0x0800",
		"ipv4_src": host_2,
		"ipv4_dst": host_1,
		"eth_src": deviceMAC[host_2],
		"eth_dst": deviceMAC[host_1],
	    "active":"true",
	    "actions":"output=" + outPort
	}

	jsonData = json.dumps(flow)

	cmd = "curl -X POST -d \'" + jsonData + "\' " + staticFlowURL
	systemCommand(cmd)
	flowCount = flowCount + 1
	flow = {
		'switch':"00:00:00:00:00:00:00:" + currentNode,
	    "name":"flow" + str(flowCount),
	    "cookie":"0",
	    "priority":"32768",
	    "in_port":outPort,
		"eth_type": "0x0800",
		"ipv4_src": host_1,
		"ipv4_dst": host_2,
		"eth_src": deviceMAC[host_1],
		"eth_dst": deviceMAC[host_2],
	    "active":"true",
	    "actions":"output=" + inPort
	}
	jsonData = json.dumps(flow)
	cmd = "curl -X POST -d \'" + jsonData + "\' " + staticFlowURL
	systemCommand(cmd)


# 遍历json数据来找出连接到目的主机的交换机
def switch_Information(data):
	global switch
	global deviceMAC
	global hostPorts
	switchDPID = ""
	for i in data:
		#逐条过滤信息IP，Mac
		if(i['ipv4']):
			ip = i['ipv4'][0].encode('ascii','ignore')
			mac = i['mac'][0].encode('ascii','ignore')
			deviceMAC[ip] = mac
			for j in i['attachmentPoint']:        # 找到相邻的结点
				for key in j:
					t = key.encode('ascii','ignore')
					if(t=="switchDPID"):       # 交换机-记录IP
						switchDPID = j[key].encode('ascii','ignore')
						switch[ip] = switchDPID
					elif(t=="port"):      # 端口号-记录该设备的端口号
						portNumber = j[key]
						switchShort = switchDPID.split(":")[7]
						hostPorts[ip+ "::" + switchShort] = str(portNumber)


# 寻找两个设备之间共同的交换机链路连接信息
def find_Switch_Links(data,s):

	global switchLinks  # 交换机直连链路信息
	global linkPorts   # 链路连接的对应port
	global G   # 网络拓扑

	links=[]

	for info in data:      # 逐条信息过滤
		src = info['src-switch'].encode('ascii','ignore')
		dst = info['dst-switch'].encode('ascii','ignore')

		src_Port = str(info['src-port'])
		dst_Port = str(info['dst-port'])

		srcTemp = src.split(":")[7]
		dstTemp = dst.split(":")[7]

		G.add_edge(int(srcTemp,16), int(dstTemp,16))      # 将链路信息加入网络拓扑图中

		tempSrcToDst = srcTemp + "::" + dstTemp
		tempDstToSrc = dstTemp + "::" + srcTemp

		portSrcToDst = str(src_Port) + "::" + str(dst_Port)
		portDstToSrc = str(dst_Port) + "::" + str(src_Port)

		linkPorts[tempSrcToDst] = portSrcToDst          # 记录链路port信息，源-目的
		linkPorts[tempDstToSrc] = portDstToSrc

		if (src==s):                # 如果找到了,就将该结点加入links
			links.append(dst)
		elif (dst==s):
			links.append(src)
		else:
			continue

	switchID = s.split(":")[7]
	switchLinks[switchID]=links      # 哈希保存每个交换机直连链路的信息


# 计算链路花费
def getLinkCost():
	global portKey
	global cost

	for key in path:            # 由目的主机开始计算， Djisktra深度遍历连通子图
		start = switch[host_2]
		src = switch[host_2]
		srcShortID = src.split(":")[7]
		mid = path[key][1].split(":")[7]  #记录下一个结点
		for link in path[key]:             # 对于每一个可能的出口链路都进行计算
			temp = link.split(":")[7]
			if srcShortID==temp:
				continue
			else:                        # 动态获取带宽信息
				portKey = srcShortID + "::" + temp
				stats = "http://localhost:8080/wm/statistics/bandwidth/" + src + "/0/json"
				getResponse(stats,"linkTX")
				srcShortID = temp
				src = link
		portKey = start.split(":")[7] + "::" + mid + "::" + switch[host_1].split(":")[7]
		finalLinkTX[portKey] = cost
		cost = 0
		portKey = ""



# 添加新的路由
def addFlow():
	#cmd = "curl -X DELETE -d \'{\"name\":\"flow1\"}\' http://127.0.0.1:8080/wm/staticflowpusher/json"
	flowCount = 1
	staticFlowURL = "http://127.0.0.1:8080/wm/staticflowpusher/json"
	shortestPath = min(finalLinkTX, key=finalLinkTX.get)   #找到最小带宽的链路，将数据包分发到该链路

	print ("\n\nShortest Path: ",shortestPath)

	currentNode = shortestPath.split("::",2)[0]       # 找到链路出、入port
	nextNode = shortestPath.split("::")[1]

	port = linkPorts[currentNode+"::"+nextNode]
	outPort = port.split("::")[0]   # 出端口
	inPort = hostPorts[host_2+"::"+switch[host_2].split(":")[7]]   # 入端口

	flowRule(currentNode,flowCount,inPort,outPort,staticFlowURL)    # 组装路由项，加入流表
	flowCount = flowCount + 2

	bestPath = path[shortestPath]
	previousNode = currentNode

	for currentNode in range(0,len(bestPath)):           # 对最优路径中的每个结点
		if previousNode == bestPath[currentNode].split(":")[7]:
			continue
		else:
			port = linkPorts[bestPath[currentNode].split(":")[7]+"::"+previousNode]
			inPort = port.split("::")[0]
			outPort = ""
			if(currentNode + 1<len(bestPath) and bestPath[currentNode]==bestPath[currentNode+1]):    # 重复
				currentNode  = currentNode + 1
				continue
			elif(currentNode+1<len(bestPath)):  # 还没到终点
				port = linkPorts[bestPath[currentNode].split(":")[7]+"::"+bestPath[currentNode+1].split(":")[7]]
				outPort = port.split("::")[0]
			elif(bestPath[currentNode]==bestPath[-1]):   # 最后一个
				outPort = str(hostPorts[host_1+"::"+switch[host_1].split(":")[7]])

			# 找到每一段链路的出入端口后，分发路由信息
			flowRule(bestPath[currentNode].split(":")[7],flowCount,str(inPort),str(outPort),staticFlowURL)
			flowCount = flowCount + 2
			previousNode = bestPath[currentNode].split(":")[7]       # 迭代到下一个


# 找到通往交换机的路由
def find_Route():
	pathKey = ""
	nodeList = []
	src = int(switch[host_2].split(":",7)[7],16)
	dst = int(switch[host_1].split(":",7)[7],16)
	print(src)
	print(dst)
	for currentPath in nx.all_shortest_paths(G, source=src, target=dst, weight=None):  # 可能有多条最短路径，无权图，仅计算跳数
		for node in currentPath:    # 每一条最短路径，记录下结点号
			tmp = ""
			if node < 17:
				pathKey = pathKey + "0" + str(hex(node)).split("x",1)[1] + "::"
				tmp = "00:00:00:00:00:00:00:0" + str(hex(node)).split("x",1)[1]
			else:
				pathKey = pathKey + str(hex(node)).split("x",1)[1] + "::"
				tmp = "00:00:00:00:00:00:00:" + str(hex(node)).split("x",1)[1]
			nodeList.append(tmp)

		pathKey=pathKey.strip("::")
		path[pathKey] = nodeList
		pathKey = ""
		nodeList = []

	print (path)


# 计算链路的带宽
def link_TX(data,key):
	global cost
	port = linkPorts[key]
	port = port.split("::")[0]
	for info in data:
		if info['port']==port:  # 累加带宽
			cost = cost + (int)(info['bits-per-second-tx'])


# main：负载均衡算法
def loadbalance():

	linkURL = "http://localhost:8080/wm/topology/links/json"
	getResponse(linkURL,"findSwitchLinks")

	#初始化，寻找路由，获取带宽cost，加入流表信息
	find_Route()
	getLinkCost()
	addFlow()

global host_1,host_2,host_3

host_1 = ""
host_2 = ""

print ("Enter Host 1:")
host_1 = int(input())
print ("\nEnter Host 2:")
host_2 = int(input())
print ("\nEnter Host 3 (host_2 neigboho):")
host_3 = int(input())

# 主机IP：10.0.0.主机号
host_1 = "10.0.0." + str(host_1)
host_2 = "10.0.0." + str(host_2)
host_3 = "10.0.0." + str(host_3)

while True:
	path = {}  # 交换机-交换机
	switchLinks = {}  # 交换机直连链路
	linkPorts = {}  # 链路结点
	finalLinkTX = {}  # 链路总带宽
	portKey = ""  # 计算各链路带宽时期的结点端口
	switch = {}   # 存储交换机信息
	deviceMAC = {}       # 交换机Mac信息
	hostPorts = {}    # 交换机-主机por
	cost = 0
	G = nx.Graph()
	try:
		enableStats = "http://localhost:8080/wm/statistics/config/enable/json"  # 使能数据
		requests.put(enableStats)
		deviceInfo = "http://localhost:8080/wm/device/"     # 设备信息（设备连接的交换机，IP，MAC地址信息等）
		getResponse(deviceInfo,"deviceInfo")
		loadbalance()  # 负载均衡
		#输出结果
		print ("\n\n############ RESULT ############\n\n")
		print ("Switch H4: ",switch[host_3], "\tSwitchH3: ", switch[host_2])
		print ("\n\nSwitch H1: ", switch[host_1])
		print ("\nIP & MAC\n\n", deviceMAC)
		print ("\nHost::Switch Ports\n\n", hostPorts)                             #输出结点相连的交换机-端口信息
		print ("\nLink Ports (SRC::DST - SRC PORT::DST PORT)\n\n", linkPorts)
		print ("\nPaths (SRC TO DST)\n\n",path)                                  #输出路径
		print ("\nFinal Link Cost (First To Second Switch)\n\n",finalLinkTX)       #最终链路cost
		print ("\n\n#######################################\n\n")
		time.sleep(80)
	except KeyboardInterrupt:
		break
		exit()
