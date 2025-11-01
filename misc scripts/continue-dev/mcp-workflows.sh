#!/bin/bash
# =============================================================================
# MCP Workflow Helper Scripts
# =============================================================================
# Quick shortcuts for common MCP-powered workflows

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}🚀 MCP Workflow Helper for Continue.dev${NC}"

# Function to research a topic
research_topic() {
    local topic="$1"
    echo -e "${YELLOW}🔍 Starting MCP research workflow for: ${topic}${NC}"
    echo ""
    echo -e "${BLUE}📋 Step 1: Copy this command into Continue.dev:${NC}"
    echo -e "${GREEN}/mcp-research \"${topic}\"${NC}"
    echo ""
    echo -e "${BLUE}💡 This will:${NC}"
    echo "   - Search for current information using Brave Search"
    echo "   - Reference official documentation via Context7"
    echo "   - Save findings to Memory for future use"
    echo "   - Provide comprehensive research report"
    echo ""
}

# Function to debug an issue
debug_issue() {
    local issue="$1"
    echo -e "${YELLOW}🐛 Starting MCP debug workflow for: ${issue}${NC}"
    echo ""
    echo -e "${BLUE}📋 Step 1: Copy this command into Continue.dev:${NC}"
    echo -e "${GREEN}/mcp-debug \"${issue}\"${NC}"
    echo ""
    echo -e "${BLUE}💡 This will:${NC}"
    echo "   - Check Memory for similar past issues"
    echo "   - Search for current solutions"
    echo "   - Use Sequential Thinking for systematic analysis"
    echo "   - Provide step-by-step debugging plan"
    echo ""
    echo -e "${YELLOW}⚡ Step 2: After getting the plan, you can also use:${NC}"
    echo -e "${GREEN}/mcp-knowledge \"Save this debugging solution for future reference\"${NC}"
    echo ""
}

# Function to analyze architecture
architect_analysis() {
    local topic="$1"
    echo -e "${YELLOW}🏗️ Starting MCP architecture workflow for: ${topic}${NC}"
    echo ""
    echo -e "${BLUE}📋 Step 1: Copy this command into Continue.dev:${NC}"
    echo -e "${GREEN}/mcp-architect \"${topic}\"${NC}"
    echo ""
    echo -e "${BLUE}💡 This will:${NC}"
    echo "   - Use Sequential Thinking for systematic analysis"
    echo "   - Research current architectural patterns"
    echo "   - Reference official documentation"
    echo "   - Provide evidence-based recommendations"
    echo ""
    echo -e "${YELLOW}💡 Step 2: Save architectural decisions:${NC}"
    echo -e "${GREEN}/mcp-knowledge \"Document architectural decision: ${topic}\"${NC}"
    echo ""
}

# Function to analyze web content
analyze_web() {
    local url_or_topic="$1"
    echo -e "${YELLOW}🌐 Starting MCP web analysis workflow for: ${url_or_topic}${NC}"
    echo ""
    echo -e "${BLUE}📋 Step 1: Copy this command into Continue.dev:${NC}"
    if [[ "$url_or_topic" == http* ]]; then
        echo -e "${GREEN}/mcp-web-analyze \"Analyze this URL: ${url_or_topic}\"${NC}"
    else
        echo -e "${GREEN}/mcp-web-analyze \"Analyze web content about: ${url_or_topic}\"${NC}"
    fi
    echo ""
    echo -e "${BLUE}💡 This will:${NC}"
    echo "   - Search for relevant resources"
    echo "   - Fetch and analyze detailed content"
    echo "   - Extract key insights and patterns"
    echo "   - Save findings to Memory with categorization"
    echo ""
}

# Function to build knowledge base
build_knowledge() {
    local topic="$1"
    echo -e "${YELLOW}🧠 Starting MCP knowledge building workflow for: ${topic}${NC}"
    echo ""
    echo -e "${BLUE}📋 Step 1: Copy this command into Continue.dev:${NC}"
    echo -e "${GREEN}/mcp-knowledge \"Build comprehensive knowledge base for: ${topic}\"${NC}"
    echo ""
    echo -e "${BLUE}💡 This will:${NC}"
    echo "   - Research comprehensive information"
    echo "   - Analyze and synthesize findings"
    echo "   - Create organized knowledge collections"
    echo "   - Link related concepts for easy retrieval"
    echo ""
}

# Function to check MCP server status
check_mcp_status() {
    echo -e "${YELLOW}🔍 Checking MCP server status...${NC}"
    
    if docker info >/dev/null 2>&1; then
        echo -e "${GREEN}✅ Docker is running${NC}"
        
        # Check for MCP containers
        if docker ps | grep -q mcp; then
            echo -e "${GREEN}✅ MCP containers running:${NC}"
            docker ps --format "table {{.Names}}\\t{{.Status}}\\t{{.Ports}}" | grep mcp
        else
            echo -e "${YELLOW}⚠️  No MCP containers found${NC}"
            echo -e "${YELLOW}💡 Start MCP servers with:${NC}"
            echo -e "${GREEN}./misc scripts/continue-dev/mcp-servers.sh start${NC}"
        fi
    else
        echo -e "${RED}❌ Docker is not running${NC}"
        echo -e "${YELLOW}💡 Please start Docker Desktop${NC}"
    fi
}

# Main execution
case "${1:-help}" in
    "research")
        research_topic "${2:-your research topic}"
        ;;
    "debug")
        debug_issue "${2:-your debugging issue}"
        ;;
    "architect")
        architect_analysis "${2:-your architectural topic}"
        ;;
    "analyze-web")
        analyze_web "${3:-https://example.com or topic}"
        ;;
    "knowledge")
        build_knowledge "${2:-your knowledge topic}"
        ;;
    "status"|"check")
        check_mcp_status
        ;;
    "help"|*)
        echo "Usage: $0 {research|debug|architect|analyze-web|knowledge|status|help}"
        echo ""
        echo "Workflow Commands:"
        echo "  $0 research 'Terraform VMware best practices'"
        echo "  $0 debug 'Terraform apply vcenter_endpoint error'"
        echo "  $0 architect 'Multi-region Tanium deployment'"
        echo "  $0 analyze-web 'https://example.com'"
        echo "  $0 knowledge 'Homelab security patterns'"
        echo ""
        echo "Utility Commands:"
        echo "  $0 status    - Check MCP server status"
        echo "  $0 help      - Show this help"
        echo ""
        echo -e "${BLUE}💡 All commands will show you exactly what to copy into Continue.dev${NC}"
        echo ""
        ;;
esac
