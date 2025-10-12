#!/bin/bash
# =============================================================================
# Bootstrap Script Test Suite
# =============================================================================
# This script tests the bootstrap.sh script against different Linux distributions
# using Docker containers to ensure cross-platform compatibility.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test configurations - using arrays instead of associative arrays for compatibility
DISTROS=("ubuntu" "debian" "centos-stream" "rocky" "alma" "fedora" "arch")
IMAGES=("ubuntu:22.04" "debian:11" "quay.io/centos/centos:stream9" "rockylinux:9" "almalinux:9" "fedora:38" "archlinux:latest")

echo -e "${BLUE}🧪 Testing bootstrap script against Linux distributions...${NC}"
echo ""

# Initialize test results
PASSED=0
FAILED=0

# Function to run test in Docker container
run_test() {
    local distro="$1"
    local image="$2"
    
    echo -e "${YELLOW}Testing $distro ($image)...${NC}"
    
    # Create a temporary directory for the test
    local test_dir=$(mktemp -d)
    cp bootstrap.sh "$test_dir/"
    
    # Set platform for Arch Linux (use x86_64 emulation)
    PLATFORM_FLAG=""
    if [[ "$image" == "archlinux:latest" ]]; then
        PLATFORM_FLAG="--platform linux/amd64"
    fi
    
    # Run the test in Docker
    if docker run --rm \
        $PLATFORM_FLAG \
        -v "$test_dir:/test" \
        -w /test \
        "$image" \
        bash -c "
            # Run bootstrap script (non-interactive) with longer timeout
            # Script now handles running as root properly
            timeout 600 bash bootstrap.sh 2>&1
        " > "$test_dir/test_output.log" 2>&1; then
        
        # Check if bootstrap completed successfully
        if grep -q "System bootstrap complete" "$test_dir/test_output.log"; then
            echo -e "${GREEN}✅ $distro: PASSED${NC}"
            PASSED=$((PASSED + 1))
        else
            echo -e "${RED}❌ $distro: FAILED - Bootstrap did not complete${NC}"
            FAILED=$((FAILED + 1))
            echo -e "${YELLOW}Last 15 lines of output:${NC}"
            tail -15 "$test_dir/test_output.log" | sed 's/^/  /'
            echo ""
        fi
    else
        echo -e "${RED}❌ $distro: FAILED - Docker run failed${NC}"
        FAILED=$((FAILED + 1))
        echo -e "${YELLOW}Last 15 lines of output:${NC}"
        tail -15 "$test_dir/test_output.log" | sed 's/^/  /'
        echo ""
    fi
    
    # Cleanup
    rm -rf "$test_dir"
    echo ""
}

# Check if Docker is available
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}❌ Docker is not installed or not in PATH${NC}"
    echo -e "${YELLOW}Please install Docker to run these tests${NC}"
    exit 1
fi

# Check if bootstrap script exists
if [ ! -f "bootstrap.sh" ]; then
    echo -e "${RED}❌ bootstrap.sh not found in current directory${NC}"
    exit 1
fi

echo -e "${BLUE}🐳 Pulling Docker images...${NC}"
for i in "${!DISTROS[@]}"; do
    distro="${DISTROS[$i]}"
    image="${IMAGES[$i]}"
    echo -e "${YELLOW}Pulling $image...${NC}"
    
    # Set platform for Arch Linux (use x86_64 emulation)
    pull_cmd="docker pull $image"
    if [[ "$image" == "archlinux:latest" ]]; then
        pull_cmd="docker pull --platform linux/amd64 $image"
    fi
    
    eval "$pull_cmd" >/dev/null 2>&1 || {
        echo -e "${RED}❌ Failed to pull $image${NC}"
        FAILED=$((FAILED + 1))
    }
done
echo ""

# Run tests
echo -e "${BLUE}🚀 Running bootstrap tests...${NC}"
for i in "${!DISTROS[@]}"; do
    distro="${DISTROS[$i]}"
    image="${IMAGES[$i]}"
    run_test "$distro" "$image"
done

# Summary
echo -e "${BLUE}📊 Test Results Summary:${NC}"
echo "=========================="
total=$((PASSED + FAILED))
echo -e "${BLUE}Summary: $PASSED passed, $FAILED failed out of $total tests${NC}"

if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}🎉 All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}⚠️  Some tests failed. Check the output above for details.${NC}"
    exit 1
fi
