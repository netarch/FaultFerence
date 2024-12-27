import sys
import networkx as nx

input_topo = sys.argv[1]
G = nx.read_edgelist(input_topo)
print("G", G.nodes(), G.edges())

interfaces = list ( range (3, 48, 2) )
print (interfaces)
int_ctr = 0
H1 = "h1"
H2 = "h2"
ip_addr = dict()
ip_addr[H1] = "192.168.101.0/24"
ip_addr[H2] = "192.168.200.0/24"
def GetLinkIpAddr(v1, v2):
    global interfaces
    global int_ctr
    interface = interfaces[int_ctr]
    last_byte = 4 * int_ctr
    network_ip = "172.31.0." + str(last_byte) + "/30"
    v1_ip = "172.31.0." + str(last_byte + 1) + "/30"
    v2_ip = "172.31.0." + str(last_byte + 2) + "/30"
    int_ctr += 1
    return network_ip, v1_ip, v2_ip, interface

def IsNodeA(node):
    return ('A' in node)

def IsNodeB(node):
    return ('B' in node)

# get ip address of next hop
def GetNextHopIp(G, node, next_hop):
    v1, v2 = node, next_hop
    if IsNodeB(node) and IsNodeA(next_hop):
        v1, v2 = next_hop, node
    network_ip, v1_ip, v2_ip, interface = G[node][next_hop]["ip"]
    if v1 == node:
        return v2_ip.split('/')[0]
    else:
        return v1_ip.split('/')[0]

def AddInitConfigA(config):
    print("vlan 100", file=config)
    print("interface Ethernet1", file=config)
    print("switchport access vlan 100", file=config)
    print("interface Vlan100", file=config)
    print("ip address 192.168.101.1/24\n", file=config)


def AddInitConfigB(config):
    print("vlan 200", file=config)
    print("interface Ethernet1", file=config)
    print("switchport access vlan 200", file=config)
    print("interface Vlan200", file=config)
    print("ip address 192.168.200.1/24\n", file=config)


with open("a.config", "w") as aconfig:
    with open("b.config", "w") as bconfig:
        AddInitConfigA(aconfig)
        AddInitConfigB(bconfig)
        for vrf in G.nodes():
            config = aconfig
            assert IsNodeA(vrf) or IsNodeB(vrf)
            if IsNodeB(vrf):
                config = bconfig
            if vrf != "A0" and vrf != "B0":
                print("vrf instance", vrf, file=config)
                print("ip routing vrf %s\n" % vrf, file=config)
            else:
                print("ip routing\n", file=config)

        print("", file=aconfig)
        print("", file=bconfig)
        for u, v in G.edges():
            v1, v2 = u, v
            if IsNodeB(u) and IsNodeA(v):
                v1, v2 = v, u
            assert ("A" in v1 and "B" in v2)

            network_ip, v1_ip, v2_ip, interface = GetLinkIpAddr(v1, v2)
            G[u][v]["ip"] = network_ip, v1_ip, v2_ip, interface

            print("\ninterface Ethernet%d" % interface, file=aconfig)
            print("no switchport", file=aconfig)
            if v1 != "A0":
                print("vrf %s" % v1, file=aconfig)
            print("ip address %s\n" % v1_ip, file=aconfig)
            # print("exit", file=aconfig)

            print("\ninterface Ethernet%d" % interface, file=bconfig)
            print("no switchport", file=bconfig)
            if v2 != "B0":
                print("vrf %s" % v2, file=bconfig)
            print("ip address %s\n" % v2_ip, file=bconfig)
            # print("exit", file=bconfig)

        G.add_node(H1)
        G.add_node(H2)
        G.add_edge(H1, "A0")
        G.add_edge(H2, "B0")
        for node in G.nodes():
            if node != H1 and node != H2:
                config = aconfig
                if IsNodeB(node):
                    config = bconfig
                for target in [H1, H2]:
                    paths = nx.all_shortest_paths(G, source=node, target=target)
                    next_hops = set([p[1] for p in paths])
                    for hop in next_hops:
                        if hop != target:
                            # print(node, hop, target)
                            other_ip = GetNextHopIp(G, node, hop)
                            # print("next hop id", node, hop, other_ip)
                            # ip route vrf B2 192.168.101.0/24 17.31.0.13
                            if node == "A0" or node == "B0":
                                # default vrf
                                print("ip route %s %s" % (ip_addr[target], other_ip), file=config)
                            else:
                                print("ip route vrf %s %s %s" % (node, ip_addr[target], other_ip), file=config)
