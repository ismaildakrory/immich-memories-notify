#!/usr/bin/env bash
# ============================================================
# Immich Memories Notify — First-Run Setup Script
# ============================================================
# Run this once before `docker compose up` to generate your
# .env file and optionally a bundled ntfy service.
#
# Usage:
#   bash setup.sh
# ============================================================

set -euo pipefail

# --- Colors -------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

print_header() {
    echo ""
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo -e "${CYAN}${BOLD}  Immich Memories Notify — Setup${NC}"
    echo -e "${CYAN}${BOLD}========================================${NC}"
    echo ""
}

print_step() {
    echo ""
    echo -e "${BOLD}${YELLOW}▶ $1${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_info() {
    echo -e "  ${CYAN}ℹ${NC} $1"
}

prompt() {
    # prompt <var_name> <question> [default]
    local var_name="$1"
    local question="$2"
    local default="${3:-}"
    local prompt_text

    if [ -n "$default" ]; then
        prompt_text="$question [${default}]: "
    else
        prompt_text="$question: "
    fi

    echo -ne "  ${BOLD}${prompt_text}${NC}"
    read -r input
    if [ -z "$input" ] && [ -n "$default" ]; then
        input="$default"
    fi
    eval "$var_name='$input'"
}

prompt_yn() {
    # prompt_yn <var_name> <question> [default y/n]
    local var_name="$1"
    local question="$2"
    local default="${3:-n}"
    local display
    if [ "$default" = "y" ]; then
        display="Y/n"
    else
        display="y/N"
    fi
    echo -ne "  ${BOLD}${question} [${display}]: ${NC}"
    read -r input
    input="${input:-$default}"
    if [[ "$input" =~ ^[Yy] ]]; then
        eval "$var_name=y"
    else
        eval "$var_name=n"
    fi
}

# ============================================================
print_header

# --- Check Docker access ------------------------------------
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}${BOLD}Error: cannot connect to the Docker daemon.${NC}"
    echo ""
    echo "  This is usually a permissions issue. Fix it by running:"
    echo ""
    echo -e "    ${BOLD}sudo usermod -aG docker \$USER${NC}"
    echo -e "    ${BOLD}newgrp docker${NC}"
    echo ""
    echo "  Then re-run: bash setup.sh"
    echo ""
    echo "  Alternatively, run setup with sudo:"
    echo -e "    ${BOLD}sudo bash setup.sh${NC}"
    echo ""
    exit 1
fi

echo "This script will help you configure Immich Memories Notify."
echo "It will generate your .env file and optionally set up a"
echo "bundled ntfy notification server."
echo ""
echo -e "${YELLOW}Press Enter to use default values shown in [brackets].${NC}"

# ============================================================
# Step 1 — Immich
# ============================================================
print_step "Step 1 — Immich Server"
echo ""
echo "  Enter the internal URL of your Immich server."
echo "  This is used by the notification script to fetch memories."
echo "  Example: http://192.168.1.10:2283"
echo ""

prompt IMMICH_URL "Immich internal URL" "http://192.168.8.30:2283"

echo ""
echo "  Enter the external URL (optional, used for deep links in notifications)."
echo "  Example: https://immich.yourdomain.com"
echo "  Leave blank to use internal URL for links."
echo ""

prompt IMMICH_EXTERNAL_URL "Immich external URL (optional)" ""

# ============================================================
# Step 2 — Timezone
# ============================================================
print_step "Step 2 — Timezone"
echo ""

# Try to detect current timezone
DETECTED_TZ=""
if command -v timedatectl &>/dev/null; then
    DETECTED_TZ=$(timedatectl show --property=Timezone --value 2>/dev/null || true)
elif [ -f /etc/timezone ]; then
    DETECTED_TZ=$(cat /etc/timezone)
elif [ -L /etc/localtime ]; then
    DETECTED_TZ=$(readlink /etc/localtime | sed 's|.*/zoneinfo/||')
fi

if [ -n "$DETECTED_TZ" ]; then
    print_info "Detected timezone: ${DETECTED_TZ}"
fi

DEFAULT_TZ="${DETECTED_TZ:-UTC}"
prompt TZ "Timezone" "$DEFAULT_TZ"

# ============================================================
# Step 3 — ntfy
# ============================================================
print_step "Step 3 — ntfy Notification Server"
echo ""
echo "  ntfy is the notification service that delivers messages to your phone."
echo "  You can either use your own ntfy server, or have this setup spin up"
echo "  a bundled ntfy instance automatically."
echo ""

prompt_yn USE_BUNDLED_NTFY "Use bundled ntfy (runs as a Docker container alongside this app)?" "y"

NTFY_URL=""
NTFY_EXTERNAL_URL=""
NTFY_CONTAINER_NAME="immich-memories-ntfy"

if [ "$USE_BUNDLED_NTFY" = "y" ]; then
    echo ""
    print_info "Bundled ntfy will be available internally at http://localhost:8090"
    NTFY_URL="http://localhost:8090"

    echo ""
    echo "  Enter the external URL for ntfy (used for deep links — the address"
    echo "  your phone uses to reach this server)."
    echo "  Example: https://ntfy.yourdomain.com or http://your-server-ip:8090"
    echo ""
    prompt NTFY_EXTERNAL_URL "ntfy external URL" "http://localhost:8090"

    # Ask for ntfy port (in case 8090 is taken)
    echo ""
    prompt NTFY_PORT "ntfy host port" "8090"

else
    echo ""
    echo "  Enter the URL of your existing ntfy server."
    echo "  Example: https://ntfy.yourdomain.com or https://ntfy.sh"
    echo ""
    prompt NTFY_URL "ntfy internal URL" ""

    echo ""
    echo "  Enter the external URL for ntfy (if different from internal, leave blank)."
    echo ""
    prompt NTFY_EXTERNAL_URL "ntfy external URL (optional)" ""
fi

# ============================================================
# Step 4 — Dashboard
# ============================================================
print_step "Step 4 — Dashboard Security (optional)"
echo ""
echo "  You can password-protect the dashboard with HTTP Basic Auth."
echo "  Leave blank to run without authentication (fine for local use)."
echo ""

prompt DASHBOARD_TOKEN "Dashboard password (leave blank for no auth)" ""

# ============================================================
# Generate files
# ============================================================
print_step "Generating configuration files..."

# --- .env ---------------------------------------------------
ENV_FILE=".env"

# Preserve existing .env if present (offer merge/overwrite)
if [ -f "$ENV_FILE" ]; then
    echo ""
    echo -e "  ${YELLOW}Warning:${NC} .env already exists."
    prompt_yn OVERWRITE_ENV "Overwrite existing .env?" "n"
    if [ "$OVERWRITE_ENV" != "y" ]; then
        echo ""
        print_info "Skipping .env generation. Your existing file is unchanged."
        echo ""
        echo "  If you want to update it manually, here are the values to set:"
        echo ""
        echo "    IMMICH_URL=${IMMICH_URL}"
        echo "    IMMICH_EXTERNAL_URL=${IMMICH_EXTERNAL_URL}"
        echo "    NTFY_URL=${NTFY_URL}"
        echo "    NTFY_EXTERNAL_URL=${NTFY_EXTERNAL_URL}"
        echo "    TZ=${TZ}"
        echo ""
        SKIP_ENV=y
    else
        SKIP_ENV=n
    fi
else
    SKIP_ENV=n
fi

if [ "$SKIP_ENV" != "y" ]; then
    cat > "$ENV_FILE" << EOF
# ============================================================
# Immich Memories Notify — Environment Variables
# Generated by setup.sh on $(date +%Y-%m-%d)
# ============================================================
#
# SECRETS: Keep this file private, never commit to git.
# Server URLs and API keys are configured here.
# Everything else (schedules, settings) is in config.yaml.
#
# ============================================================

# --- Server URLs -------------------------------------------
# Internal URL used by Docker containers to reach Immich
IMMICH_URL=${IMMICH_URL}

# External URL used for deep links in notifications (optional)
IMMICH_EXTERNAL_URL=${IMMICH_EXTERNAL_URL}

# Internal URL used by Docker containers to reach ntfy
NTFY_URL=${NTFY_URL}

# External URL used for deep links in notifications (optional)
NTFY_EXTERNAL_URL=${NTFY_EXTERNAL_URL}

# --- Timezone ----------------------------------------------
TZ=${TZ}

# --- Dashboard Authentication (optional) -------------------
# Leave blank to run dashboard without authentication
DASHBOARD_TOKEN=${DASHBOARD_TOKEN}
DASHBOARD_USER=admin

# --- User API Keys -----------------------------------------
# Add one entry per user, named after the user in config.yaml
# Example: IMMICH_API_KEY_USER1=your-key-here
#
# These will be configured through the dashboard wizard
# after you run: docker compose up -d dashboard

# --- ntfy Auth (if using password-protected ntfy) ----------
# Example: NTFY_PASSWORD_USER1=your-ntfy-password

# --- Setup Status ------------------------------------------
# Set to true once initial setup is complete (wizard won't reappear)
SETUP_COMPLETE=false
EOF
    print_ok ".env created"
fi

# --- docker-compose.override.yml (if bundled ntfy) ----------
if [ "$USE_BUNDLED_NTFY" = "y" ]; then
    # Generate ntfy server.yaml
    mkdir -p ntfy_config
    cat > ntfy_config/server.yaml << EOF
# ntfy server configuration
# Generated by setup.sh

# Base URL - used for attachment links sent to phones
# Set this to the external URL your phone uses to reach ntfy
base-url: "${NTFY_EXTERNAL_URL}"

# Auth database - required for attachment uploads
auth-file: /var/lib/ntfy/user.db
auth-default-access: deny-all

# Attachment storage
attachment-cache-dir: /var/lib/ntfy/attachments
attachment-total-size: 5G
attachment-file-size: 15M
attachment-expiry-duration: 3h

# Logging
log-level: warn
EOF
    print_ok "ntfy_config/server.yaml created"

    mkdir -p ntfy_data
    print_ok "ntfy_data/ directory created"

    # Generate docker-compose.override.yml
    cat > docker-compose.override.yml << EOF
# ============================================================
# Immich Memories Notify — Bundled ntfy Override
# Generated by setup.sh — do not commit to git
# ============================================================
#
# This file is auto-merged by Docker Compose with docker-compose.yml
# It adds the bundled ntfy notification server.
#
# ============================================================

services:
  ntfy:
    image: binwiederhier/ntfy
    container_name: ${NTFY_CONTAINER_NAME}
    command: serve
    environment:
      - TZ=\${TZ:-UTC}
    volumes:
      - ./ntfy_data:/var/lib/ntfy
      - ./ntfy_config/server.yaml:/etc/ntfy/server.yaml:ro
    ports:
      - "${NTFY_PORT:-8090}:80"
    restart: unless-stopped
EOF
    print_ok "docker-compose.override.yml created (ntfy on port ${NTFY_PORT:-8090})"
fi

# ============================================================
# Summary
# ============================================================
echo ""
echo -e "${GREEN}${BOLD}========================================${NC}"
echo -e "${GREEN}${BOLD}  Setup complete!${NC}"
echo -e "${GREEN}${BOLD}========================================${NC}"
echo ""
print_ok "Immich URL:          ${IMMICH_URL}"
if [ -n "$IMMICH_EXTERNAL_URL" ]; then
    print_ok "Immich external URL: ${IMMICH_EXTERNAL_URL}"
fi
print_ok "ntfy URL:            ${NTFY_URL}"
if [ -n "$NTFY_EXTERNAL_URL" ]; then
    print_ok "ntfy external URL:   ${NTFY_EXTERNAL_URL}"
fi
print_ok "Timezone:            ${TZ}"
echo ""

# ============================================================
# Offer to start services
# ============================================================
echo ""
prompt_yn START_NOW "Start services now (dashboard$([ "$USE_BUNDLED_NTFY" = "y" ] && echo " + ntfy"))" "y"

if [ "$START_NOW" = "y" ]; then
    echo ""
    print_step "Starting services..."
    echo ""

    if [ "$USE_BUNDLED_NTFY" = "y" ]; then
        echo -e "  ${BOLD}docker compose up -d ntfy${NC}"
        docker compose up -d ntfy
        echo ""
    fi

    echo -e "  ${BOLD}docker compose up -d --build dashboard${NC}"
    docker compose up -d --build dashboard
    echo ""

    # Detect host IP for dashboard URL
    HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    DASHBOARD_URL="http://${HOST_IP:-localhost}:5000"

    print_ok "Services started!"
    echo ""
    echo -e "  Open the dashboard: ${BOLD}${CYAN}${DASHBOARD_URL}${NC}"
    echo ""
    echo "  The setup wizard will appear automatically."
    echo "  After completing it, start the scheduler:"
    echo -e "  ${BOLD}docker compose up -d scheduler${NC}"
else
    echo ""
    echo "  When ready, start the services:"
    echo ""
    if [ "$USE_BUNDLED_NTFY" = "y" ]; then
        echo -e "    ${BOLD}docker compose up -d ntfy${NC}"
    fi
    echo -e "    ${BOLD}docker compose up -d dashboard${NC}"
    echo ""
    echo "  Then open: ${BOLD}http://localhost:5000${NC}"
    echo "  The setup wizard will appear automatically."
    echo ""
    echo "  After the wizard, start the scheduler:"
    echo -e "    ${BOLD}docker compose up -d scheduler${NC}"
fi
echo ""
