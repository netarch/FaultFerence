scp a.config alice:/mnt/flash/a.config
scp b.config bob:/mnt/flash/b.config

ssh alice "configure replace checkpoint:alice-clean-slate"
ssh alice "copy flash:a.config running-config"

ssh bob "configure replace checkpoint:bob-clean-slate"
ssh bob "copy flash:b.config running-config"

# Alice host
sudo ip netns add alice-host
sudo ip link set enp4s0f1 netns alice-host
sudo ip netns exec alice-host bash

sudo ip addr add 192.168.100.2/24 dev enp4s0f1
sudo ip link set enp4s0f1 up
# sudo ip route add 192.168.200.0/24 via 192.168.101.1 dev enp4s0f1
sudo ip route add 192.168.0.0/16 via 192.168.100.1 dev enp4s0f1
exit

# Alice host2
sudo ip netns add alice-host2
sudo ip link set enp76s0f1 netns alice-host2
sudo ip netns exec alice-host2 bash

sudo ip addr add 192.168.150.2/24 dev enp76s0f1
sudo ip link set enp76s0f1 up
sudo ip route add 192.168.0.0/16 via 192.168.150.1 dev enp76s0f1
exit

# Bob host
sudo ip netns add bob-host
sudo ip link set enp76s0f0 netns bob-host
sudo ip netns exec bob-host bash

sudo ip addr add 192.168.200.2/24 dev enp76s0f0
sudo ip link set enp76s0f0 up
# sudo ip route add 192.168.101.0/24 via 192.168.200.1 dev enp76s0f0
sudo ip route add 192.168.0.0/16 via 192.168.200.1 dev enp76s0f0
exit

# Bob host2
sudo ip netns add bob-host2
sudo ip link set enp13s0f1 netns bob-host2
sudo ip netns exec bob-host2 bash

sudo ip addr add 192.168.250.2/24 dev enp13s0f1
sudo ip link set enp13s0f1 up
sudo ip route add 192.168.0.0/16 via 192.168.250.1 dev enp13s0f1
exit
