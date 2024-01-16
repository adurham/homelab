# Consul client configuration
server = false

# Datacenter name
datacenter = "homelab"

# Bind address - Bind to all interfaces
bind_addr = "0.0.0.0"

# Client address - to bind client interfaces
client_addr = "0.0.0.0"

# Data directory
data_dir = "/opt/consul"

# Enable Gossip encryption (use the same key as the server nodes)
encrypt = "TVdShmN3EIV73byugVK2HH82SnucAVIBkG9/Eux8+pA="

# Logs
log_level = "INFO"

# Addresses of the server nodes in the cluster for joining (using FQDNs)
retry_join = ["amd-lxcnsl01.lab.amd-e.com", "amd-lxcnsl02.lab.amd-e.com", "amd-lxcnsl03.lab.amd-e.com"]
