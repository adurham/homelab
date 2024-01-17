# Consul server configuration
server = true

# Enable the UI
ui = true

# Datacenter name
datacenter = "homelab"

# Bind address - Bind to all interfaces
bind_addr = "0.0.0.0"

# Client address - to bind client interfaces
client_addr = "0.0.0.0"

# Number of servers to wait for before bootstrapping the cluster
bootstrap_expect = 3

# Data directory
data_dir = "/opt/consul"

# Enable Gossip encryption (replace with your own key)
encrypt = "TVdShmN3EIV73byugVK2HH82SnucAVIBkG9/Eux8+pA="

# Logs
log_level = "INFO"

# Protocol
protocol = 3

# Addresses of other nodes in the cluster for joining
# Uncomment and list all server nodes except the one the config is for
retry_join = ["amd-lxcnsl01.lab.amd-e.com", "amd-lxcnsl02.lab.amd-e.com", "amd-lxcnsl03.lab.amd-e.com"]
