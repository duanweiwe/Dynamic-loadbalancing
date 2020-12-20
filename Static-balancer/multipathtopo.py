from mininet.topo import Topo
from mininet.net import Mininet
from mininet.node import CPULimitedHost
from mininet.node import Controller, RemoteController
from mininet.link import TCLink
from mininet.util import dumpNodeConnections
from mininet.log import setLogLevel
from mininet.cli import CLI

class MultiPath(Topo):
    "four hosts, 2 v 2, 2 paths"

    def __init__(self):
        Topo.__init__(self)

        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        h4 = self.addHost('h4')
        s1 = self.addSwitch('s1')
        s2 = self.addSwitch('s2')
        s3 = self.addSwitch('s3')
        s4 = self.addSwitch('s4')

        self.addLink(h1, s1)
        self.addLink(h2, s1)

        self.addLink(s1, s2, bw=10)
        self.addLink(s1, s3, bw=10)

        self.addLink(s2, s4, bw=10)
        self.addLink(s3, s4, bw=10)

        self.addLink(s4, h3)
        self.addLink(s4, h4)

topos = {'multipath': (lambda: MultiPath())}

if __name__ == '__main__':
    net = Mininet(topo=MultiPath(), link=TCLink, controller=lambda name: RemoteController(name, ip='192.168.154.1', port=6653), autoSetMacs=True)
    net.start()
    dumpNodeConnections(net.hosts)
    # net.pingAll()
    # h1 = net.get('h1')
    # print h1.cmd('ip add')
    CLI(net)
    net.stop()

