#!/bin/python

import json
import os
import time
import networkx
from subprocess import run

# global variables
url_prefix = 'http://localhost:8080'

# basic get and post rely on util curl:

# return json object
def get(restful):
    url = url_prefix + restful
    proc = run(['curl', url], capture_output=True, check=True, text=True)
    return json.loads(proc.stdout)

# data : string
def post(restful, data):
    url = url_prefix + restful
    proc = run(['curl', '-X', 'post', '-d', data, url], capture_output=True, check=True, text=True)
    return json.loads(proc.stdout)

# flowEntryJson : string
def pushFlow(flowEntryJson):
    replyJson = post('/wm/staticflowpusher/json', flowEntryJson)
    if replyJson["status"] != "Entry pushed":
        print("flow push error:")
        print(replyJson)
        exit()

def delFlow(flowName):
    url = url_prefix + '/wm/staticflowpusher/json'
    proc = run(['curl', '-X', 'delete', '-d', '{{"name": "{}"}}'.format(flowName), url],
               capture_output=True, check=True, text=True)
    reply = json.loads(proc.stdout)
    if reply['status'] != "Entry {} deleted".format(flowName):
        print("flow delelte error:")
        print(reply)
        exit()

# int -> string
def nToDpid(n):
    id = hex(n).split('x')[1]
    if n < 16:
        return "00:00:00:00:00:00:00:0" + id
    else:
        return "00:00:00:00:00:00:00:" + id

# string -> int
def dpidToN(dpid):
    return int(dpid.split(':')[7], base=16)

# () -> {ip : (mac, attachedSwitch(int), attachedPort(int))}
def findHosts():
    # switches which have hosts attached to them:
    # {dpidToN : [ip]}
    switches = {}
    # {ip: (mac, switchN, port)}
    # hosts:
    hostsInfo = {}
    hostsJson = get('/wm/device/')

    for host in hostsJson:
        switchN = dpidToN(host['attachmentPoint'][0]['switchDPID'])
        hostsInfo[host['ipv4'][0]] = (host['mac'][0],
                                      switchN,
                                      host['attachmentPoint'][0]['port'])
        if switchN not in switches:
            switches[switchN] = []
        switches[switchN].append(host['ipv4'][0])

    return hostsInfo, switches

def findTopology():
    links = get('/wm/topology/links/json')
    graph = networkx.Graph()
    for link in links:
        n1 = dpidToN(link['src-switch'])
        n2 = dpidToN(link['dst-switch'])

        # graph with weight information and port information
        # may use true weight later
        graph.add_edge(n1, n2, weight=10,
                       ports={n1: link['src-port'], n2: link['dst-port']})

    return graph

# gate1 : int , gate2 : int
# return : how much flow did you add
def loadBalance(switches, hosts, graph, gate1, gate2):
    hostsOfGate1 = switches[gate1]
    hostsOfGate2 = switches[gate2]

    # record possible paths
    shortestPaths = networkx.all_shortest_paths(graph, source=gate1,
                                                target=gate2, weight='weight')
    paths = [p for p in shortestPaths]
    numPaths = len(paths)
    print(numPaths)

    flowCount = 0
    for h in hostsOfGate1:
        flow = {
            'switch': nToDpid(gate1),
            'name': 'myflow' + str(flowCount),
            'cookie': '0',
            'priority': '100',
            'eth_type': '0x0800',
            'ipv4_dst': h,
            'eth_dst': hosts[h][0],
            'active': 'true',
            'actions': 'output=' + str(hosts[h][2])
        }
        pushFlow(json.dumps(flow))
        flowCount += 1
        
    for h in hostsOfGate2:
        flow = {
            'switch': nToDpid(gate2),
            'name': 'myflow' + str(flowCount),
            'cookie': '0',
            'priority': '100',
            'eth_type': '0x0800',
            'ipv4_dst': h,
            'eth_dst': hosts[h][0],
            'active': 'true',
            'actions': 'output=' + str(hosts[h][2])
        }
        pushFlow(json.dumps(flow))
        flowCount += 1

    pathCount = 0
    for h1 in hostsOfGate1:
        pathCount += 1
        for h2 in hostsOfGate2:
            # which pass should you use:
            p = paths[pathCount % numPaths]
            # pathCount += 1

            plen = len(p)

            # the first node only needs to know how to go forward
            flow = {
                'switch': nToDpid(p[0]),
                'name': 'myflow' + str(flowCount),
                'cookie': '0',
                'priority': '100',
                'in_port': hosts[h1][2],
                'eth_type': '0x0800',
                'ipv4_src': h1,
                'ipv4_dst': h2,
                'eth_src': hosts[h1][0],
                'eth_dst': hosts[h2][0],
                'active': 'true',
                'actions': 'output=' + str(graph[p[0]][p[1]]['ports'][p[0]])
            }
            flowCount += 1
            pushFlow(json.dumps(flow))

            # the last node only needs to know how to go backward
            flow = {
                'switch': nToDpid(p[plen - 1]),
                'name': 'myflow' + str(flowCount),
                'cookie': '0',
                'priority': '100',
                'in_port': hosts[h2][2],
                'eth_type': '0x0800',
                'ipv4_src': h2,
                'ipv4_dst': h1,
                'eth_src': hosts[h2][0],
                'eth_dst': hosts[h1][0],
                'active': 'true',
                'actions': 'output=' + str(graph[p[plen-2]][p[plen-1]]['ports'][p[plen-1]])
            }
            flowCount += 1
            pushFlow(json.dumps(flow))

            # for all intermediate switches:
            for i in range(1, plen - 1):
                sw = p[i]
                flow1 = {
                    'switch': nToDpid(sw),
                    'name': 'myflow' + str(flowCount),
                    'cookie': '0',
                    'priority': '100',
                    'in_port': graph[p[i-1]][p[i]]['ports'][p[i]],
                    'eth_type': '0x0800',
                    'ipv4_src': h1,
                    'ipv4_dst': h2,
                    'eth_src': hosts[h1][0],
                    'eth_dst': hosts[h2][0],
                    'active': 'true',
                    'actions': 'output=' + str(graph[p[i]][p[i+1]]['ports'][p[i]])
                }
                flowCount += 1
                pushFlow(json.dumps(flow1))

                flow2 = {
                    'switch': nToDpid(sw),
                    'name': 'myflow' + str(flowCount),
                    'cookie': '0',
                    'priority': '100',
                    'in_port': graph[p[i]][p[i+1]]['ports'][p[i]],
                    'eth_type': '0x0800',
                    'ipv4_src': h2,
                    'ipv4_dst': h1,
                    'eth_src': hosts[h2][0],
                    'eth_dst': hosts[h1][0],
                    'active': 'true',
                    'actions': 'output=' + str(graph[p[i-1]][p[i]]['ports'][p[i]])
                }
                flowCount += 1
                pushFlow(json.dumps(flow2))
    return flowCount

def deleteFlows(nFlows):
    for i in range(nFlows):
        delFlow("myflow" + str(i))





# def findMetrics():
#     costs = get('/wm/statistics/bandwidth/00:00:00:00:00:00:00:01/1/json')
#     print(json.dumps(costs))


if __name__ == '__main__':
    try:
        print('trying to enable statistic collecting:')
        print(post('/wm/statistics/config/enable/json', ''))
        nFlows = 0
        while True:
            deleteFlows(nFlows)
            graph = findTopology()
            hosts, switches = findHosts()
            print(hosts)
            print(switches)
            nFlows = loadBalance(switches, hosts, graph, 1, 4)
            print('one loop finished')
            # exit()
            time.sleep(60)
    except KeyboardInterrupt:
        deleteFlows(nFlows)
        print('user keyboard interrupt. quit.')
        exit()
