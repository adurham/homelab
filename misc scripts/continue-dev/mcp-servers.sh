#!/bin/bash
# =============================================================================
# MCP Server Management Script
# =============================================================================
# Start and manage Docker MCP servers for Continue.dev

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🐳 Managing Docker MCP Servers for Continue.dev${NC}"

# Check if Docker is running
if ! docker info >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not running. Please start Docker Desktop.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Docker is running${NC}"

# Function to start MCP gateway
start_mcp_gateway() {
    echo -e "${YELLOW}🚀 Starting MCP Gateway...${NC}"
    
    # Start MCP Docker gateway (this runs continuously)
    docker run -d \
        --name mcp-gateway \
        --rm \
        -p 3000:3000 \
        -v /var/run/docker.sock:/var/run/docker.sock \
        ghcr.io/modelcontextprotocol/docker-mcp-gateway:latest \
        || echo -e "${YELLOW}⚠️  MCP Gateway container not found, using continue-dev integration${NC}"
}

# Function to start individual MCP servers
start_mcp_servers() {
    echo -e "${YELLOW}🔧 Starting individual MCP servers...${NC}"
    
    # These commands assume the MCP servers are available via Docker
    # Brave Search
    echo -e "${YELLOW}📡 Starting Brave Search MCP...${NC}"
    docker run -d --name mcp-brave-search --rm \
        -e BRAVE_API_KEY="${BRAVE_API_KEY:-}" \
        mcp/brave-search:latest \
        || echo -e "${YELLOW}⚠️  Brave Search not available${NC}"
    
    # Context7
    echo -e "${YELLOW}📚 Starting Context7 MCP...${NC}"
    docker run -d --name mcp-context7 --rm \
        mcp/context7:latest \
        || echo -e "${YELLOW}⚠️  Context7 not available${NC}"
    
    # Memory
    echo -e "${YELLOW}🧠 Starting Memory MCP...${NC}"
    docker run -d --name mcp-memory --rm \
        -v "$(pwd)/.mcp-memory:/data" \
        mcp/memory:latest \
        || echo -e "${YELLOW}⚠️  Memory not available${NC}"
    
    # Sequential Thinking
    echo -e "${YELLOW}🧩 Starting Sequential Thinking MCP...${NC}"
    docker run -d --name mcp-sequential-thinking --rm \
        mcp/sequential-thinking:latest \
        || echo -e "${YELLOW}⚠️  Sequential Thinking not available${NC}"
}

# Function to check MCP server status
check_status() {
    echo -e "${YELLOW}🔍 Checking MCP server status...${NC}"
    
    # Check if Continue.dev can reach MCP servers
    if curl -s http://localhost:3000/health >/dev/null 2>&1; then
        echo -e "${GREEN}✅ MCP Gateway is running on port 3000${NC}"
    else
        echo -e "${YELLOW}⚠️  MCP Gateway not responding on port 3000${NC}"
        echo -e "${YELLOW}💡 MCP servers may be integrated directly through Continue.dev${NC}"
    fi
    
    # Check individual containers
    echo -e "${YELLOW}🐳 Checking Docker containers...${NC}"
    docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}" | grep mcp || echo "No MCP containers running"
}

# Main execution
case "${1:-status}" in
    "start")
        start_mcp_gateway
        start_mcp_servers
        check_status
        ;;
    "stop")
        echo -e "${YELLOW}🛑 Stopping MCP servers...${NC}"
        docker stop mcp-gateway mcp-brave-search mcp-context7 mcp-memory mcp-sequential-thinking 2>/dev/null || true
        echo -e "${GREEN}✅ MCP servers stopped${NC}"
        ;;
    "restart")
        $0 stop
        $0 start
        ;;
    "status"|"check")
        check_status
        ;;
    "logs")
        echo -e "${YELLOW}📋 MCP Gateway logs:${NC}"
        docker logs mcp-gateway 2>/dev/null || echo "No gateway logs available"
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|check|logs}"
        echo ""
        echo "Commands:"
        echo "  start   - Start MCP servers"
        echo "  stop    - Stop all MCP servers"
        echo "  restart - Restart MCP servers"
        echo "  status  - Check MCP server status"
        echo "  logs    - Show MCP gateway logs"
        exit 1
        ;;
esac

echo -e "${GREEN}🎉 MCP server management complete!${NC}"
