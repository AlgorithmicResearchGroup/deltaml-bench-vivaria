#!/bin/bash
# Automated Tailscale HTTPS Setup for Vivaria
# This script configures Vivaria to be accessible via Tailscale with valid HTTPS certificates

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration - adjusted for this machine's structure
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VIVARIA_DIR="$SCRIPT_DIR"  # We're already in the vivaria directory
DOCKER_COMPOSE_FILE="$VIVARIA_DIR/docker-compose.yml"

# Functions
print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Check prerequisites
print_step "Checking prerequisites..."

# Check if Tailscale is installed
if ! command -v tailscale &> /dev/null; then
    print_error "Tailscale is not installed. Please install Tailscale first."
    echo "Visit: https://tailscale.com/download"
    exit 1
fi

# Check if Tailscale is connected
if ! tailscale status &> /dev/null; then
    print_error "Tailscale is not connected. Please run: tailscale up"
    exit 1
fi

# Get Tailscale hostname
print_step "Getting Tailscale configuration..."
TAILSCALE_HOSTNAME=$(tailscale status --json | python3 -c "import sys, json; data = json.load(sys.stdin); print(data['Self']['DNSName'].rstrip('.'))")
TAILSCALE_IP=$(tailscale ip -4)

if [ -z "$TAILSCALE_HOSTNAME" ]; then
    print_error "Could not determine Tailscale hostname"
    exit 1
fi

print_success "Tailscale hostname: $TAILSCALE_HOSTNAME"
print_success "Tailscale IP: $TAILSCALE_IP"

# Change to vivaria directory
cd "$VIVARIA_DIR"

# Generate Tailscale certificates
print_step "Generating Tailscale HTTPS certificates..."
if [ -f "$TAILSCALE_HOSTNAME.crt" ] && [ -f "$TAILSCALE_HOSTNAME.key" ]; then
    print_warning "Certificates already exist. Regenerating..."
    rm -f "$TAILSCALE_HOSTNAME.crt" "$TAILSCALE_HOSTNAME.key"
fi

sudo tailscale cert "$TAILSCALE_HOSTNAME"

if [ ! -f "$TAILSCALE_HOSTNAME.crt" ] || [ ! -f "$TAILSCALE_HOSTNAME.key" ]; then
    print_error "Failed to generate Tailscale certificates"
    exit 1
fi

print_success "Certificates generated successfully"

# Create Caddyfile
print_step "Creating Caddyfile for HTTPS on port 4000..."
cat > Caddyfile << EOF
:4000 {
    tls /certs/$TAILSCALE_HOSTNAME.crt /certs/$TAILSCALE_HOSTNAME.key

    handle /api/* {
        uri strip_prefix /api
        reverse_proxy http://server:4001
        encode gzip
    }

    handle {
        root * /srv
        file_server
        encode gzip
    }
}
EOF

print_success "Caddyfile created"

# Backup original docker-compose.yml
print_step "Backing up docker-compose.yml..."
cp "$DOCKER_COMPOSE_FILE" "$DOCKER_COMPOSE_FILE.backup.$(date +%Y%m%d_%H%M%S)"

# Update docker-compose.yml
print_step "Updating docker-compose.yml..."

# Check if Python is available for YAML manipulation
if command -v python3 &> /dev/null; then
    python3 << EOF
import yaml
import sys

# Read the docker-compose file
with open("$DOCKER_COMPOSE_FILE", 'r') as f:
    config = yaml.safe_load(f)

# Update UI service configuration
if 'services' in config and 'ui' in config['services']:
    ui_service = config['services']['ui']

    # Update environment
    if 'environment' not in ui_service:
        ui_service['environment'] = {}
    ui_service['environment']['VIVARIA_UI_HOSTNAME'] = 'https://$TAILSCALE_HOSTNAME:4000'
    ui_service['environment']['VIVARIA_API_URL'] = 'http://server:4001'

    # Update volumes
    if 'volumes' not in ui_service:
        ui_service['volumes'] = []

    # Remove old volume entries if they exist
    ui_service['volumes'] = [v for v in ui_service['volumes']
                            if not any(x in v for x in ['Caddyfile', '.crt:', '.key:'])]

    # Add new volumes
    ui_service['volumes'].extend([
        './Caddyfile:/etc/caddy/Caddyfile',
        './$TAILSCALE_HOSTNAME.crt:/certs/$TAILSCALE_HOSTNAME.crt:ro',
        './$TAILSCALE_HOSTNAME.key:/certs/$TAILSCALE_HOSTNAME.key:ro'
    ])

    # Update ports to bind to all interfaces
    if 'ports' in ui_service:
        ui_service['ports'] = ['0.0.0.0:4000:4000']

# Update server service ports
if 'services' in config and 'server' in config['services']:
    if 'ports' in config['services']['server']:
        config['services']['server']['ports'] = ['0.0.0.0:4001:4001']

# Write back the updated configuration
with open("$DOCKER_COMPOSE_FILE", 'w') as f:
    yaml.dump(config, f, default_flow_style=False, sort_keys=False)

print("Docker Compose configuration updated successfully")
EOF
    print_success "docker-compose.yml updated"
else
    print_warning "Python3 not found. Please manually update docker-compose.yml"
    echo "Add these lines to the ui service volumes section:"
    echo "  - ./Caddyfile:/etc/caddy/Caddyfile"
    echo "  - ./$TAILSCALE_HOSTNAME.crt:/certs/$TAILSCALE_HOSTNAME.crt:ro"
    echo "  - ./$TAILSCALE_HOSTNAME.key:/certs/$TAILSCALE_HOSTNAME.key:ro"
fi

# Restart UI service
print_step "Restarting Vivaria UI service..."
sudo docker compose down ui
sudo docker compose up -d ui

# Wait for service to be healthy
print_step "Waiting for service to be healthy..."
for i in {1..30}; do
    if sudo docker compose ps ui | grep -q "healthy\|running"; then
        print_success "UI service is healthy"
        break
    fi
    sleep 2
done

# Update viv CLI configuration
print_step "Updating viv CLI configuration..."
if command -v viv &> /dev/null; then
    viv config set apiUrl "http://$TAILSCALE_HOSTNAME:4001"
    viv config set uiUrl "https://$TAILSCALE_HOSTNAME:4000"
    print_success "viv CLI configured"
else
    print_warning "viv CLI not found. Install it with: pip install viv-cli"
fi

# Test the connection
print_step "Testing HTTPS connection..."
if curl -s -f -k "https://$TAILSCALE_HOSTNAME:4000" > /dev/null 2>&1; then
    print_success "HTTPS connection successful!"
else
    print_warning "Could not verify HTTPS connection. This might be normal if the service is still starting."
fi

# Print summary
echo
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}✓ Tailscale HTTPS Setup Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo
echo -e "${CYAN}Access Vivaria at:${NC}"
echo -e "  ${BLUE}Web UI:${NC} https://$TAILSCALE_HOSTNAME:4000"
echo -e "  ${BLUE}API:${NC}    http://$TAILSCALE_HOSTNAME:4001"
echo
echo -e "${CYAN}From your laptop, configure viv CLI:${NC}"
echo -e "  viv config set apiUrl http://$TAILSCALE_HOSTNAME:4001"
echo -e "  viv config set uiUrl https://$TAILSCALE_HOSTNAME:4000"
echo
echo -e "${YELLOW}Note:${NC} The HTTPS certificate is valid and trusted by Tailscale."
echo -e "      You should not see any certificate warnings in your browser."