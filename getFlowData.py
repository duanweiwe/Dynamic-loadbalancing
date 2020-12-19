#!/usr/bin/env python

import requests
import json

def getFlowData():

	global flowBandwidth;

	flowBandwidth = {}

	response = requests.get("http://localhost:8080/wm/core/switch/all/flow/json")#获取流数据

	if (response.ok):
		jsData = json.loads(response.content)#下载到本地
		for switch in jsData:
			for flow in jsData[switch]['flows']:
				if (flow['match']):
#					print switch, flow['match']['ipv4_src'], flow['match']['ipv4_dst'], flow['byteCount']
					if (not switch in flowBandwidth):
						flowBandwidth[switch] = {};
					flowBandwidth[switch][flow['match']['ipv4_src'] + ' ' + flow['match']['ipv4_dst']] = flow['byteCount']

	else:
		response.raise_for_status()




# Main
global flowBandwidth

getFlowData()

#print flowBandwidth
