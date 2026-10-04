#!/usr/bin/env bash
# Install Docker Engine and Compose v2 on a fresh Ubuntu server.
#
# For Alibaba Cloud ECS, run this over SSH as the non-root user before the
# first `bash deploy/deploy.sh`:
#
#     bash deploy/bootstrap-docker.sh
#
# Uses Docker's official apt repository rather than Ubuntu's `docker.io` package.
# Ubuntu's build is behind, and its Compose v1 (`docker-compose`, with a hyphen)
# is not what deploy.sh calls - the script needs `docker compose` from the v2
# plugin, which only the official repository provides.

set -euo pipefail

say() { printf '\n\033[1m==> %s\033[0m\n' "$1"; }
fail() { printf '\033[31mFAILED: %s\033[0m\n' "$1" >&2; exit 1; }

# --- Check we are on a supported OS -----------------------------------------
say "Checking the operating system"
if [ ! -r /etc/os-release ]; then
  fail "/etc/os-release not readable - is this a Linux server?"
fi
. /etc/os-release
echo "  detected: ${PRETTY_NAME:-unknown}"

case "${ID:-}" in
  ubuntu)
    echo "  Ubuntu is supported."
    ;;
  debian)
    echo "  Debian is supported by these instructions."
    ;;
  *)
    fail "This script targets Ubuntu or Debian. You have '${ID:-unknown}'.
  On Alibaba Cloud Linux the package names differ - choose the Ubuntu image
  when creating the instance and this problem does not exist."
    ;;
esac

case "${VERSION_ID:-}" in
  18.04|20.04|22.04|24.04) : ;;
  *) echo "  WARNING: untested on Ubuntu ${VERSION_ID:-unknown}. Continuing anyway." ;;
esac

# --- Refuse to run as root silently ----------------------------------------
# Running as root works, but the deploy user should own the Docker socket, or
# every later command needs sudo and the habit of typing it grows.
if [ "$(id -u)" = "0" ]; then
  echo "  WARNING: running as root. The deploy user will still need to be added"
  echo "           to the docker group below."
fi

DEPLOY_USER="${SUDO_USER:-${USER:-root}}"

# --- Add the official Docker repository -------------------------------------
say "Adding Docker's apt repository"
sudo apt-get update -qq
sudo apt-get install -y -qq ca-certificates curl gnupg

sudo install -m 0755 -d /etc/apt/keyrings
# The signed-by path is what makes this safe against a repo that changes its
# key: only the key Docker ships in the image can authorise these packages.
sudo curl -fsSL "https://download.docker.com/linux/${ID}/gpg" -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

ARCH="$(dpkg --print-architecture)"
CODENAME="${UBUNTU_CODENAME:-${VERSION_CODENAME}}"
echo "deb [arch=${ARCH} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/${ID} ${CODENAME} stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
echo "  repository: ${ID} ${CODENAME} (${ARCH})"

# --- Install ----------------------------------------------------------------
say "Installing Docker Engine, Compose v2 and buildx"
sudo apt-get update -qq
sudo apt-get install -y -qq \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin

sudo systemctl enable --now docker

# --- Let the deploy user talk to Docker without sudo -------------------------
say "Adding ${DEPLOY_USER} to the docker group"
sudo usermod -aG docker "${DEPLOY_USER}"

# --- Verify, and fail loudly if any of it did not take ----------------------
say "Verifying"
docker --version || fail "docker is not on PATH"
docker compose version || fail "docker compose (v2) is unavailable"

if docker info > /dev/null 2>&1; then
  echo "  ${DEPLOY_USER} can already talk to the Docker daemon."
else
  echo "  The group change takes effect at next login. Reconnect (or run 'newgrp docker')"
  echo "  before continuing - the next step will fail with a permission error otherwise."
fi

running="$(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo unknown)"
echo "  daemon version: ${running}"

# --- Confirm the host can actually build this app ---------------------------
say "Sanity check: can this machine build the image?"
if command -v git > /dev/null 2>&1; then
  echo "  git present: $(git --version)"
else
  echo "  WARNING: git is not installed. The deploy script runs 'git pull'."
  echo "           Install it with: sudo apt-get install -y git"
fi

printf '\n\033[1;32mDocker is ready.\033[0m\n\n'
cat <<'NEXT'
Next steps:

  1. Clone the repository
       git clone https://github.com/Kingkamarasl/hrcloudpay.git
       cd hrcloudpay

  2. Create the environment file
       cp deploy/.env.production.example .env
       chmod 600 .env
     Then edit .env and fill in SECRET_KEY and DB_PASSWORD. Everything else has
     a working default; see the comments in that file for what silently breaks
     if you leave it alone.

  3. Deploy
       bash deploy/deploy.sh

Two things the script cannot do for you, and both matter:

  * Point hrcloudpay.com's DNS A record at this server's public IP BEFORE
    running step 3. Caddy obtains its certificate on first start and ACME
    validates over plain HTTP, so a domain that does not resolve yet means a
    failed issuance that has to be retried.

  * Open ports 80 and 443 in the Alibaba Cloud *security group*, and restrict
    port 22 to your own IP. The security group is a separate layer from anything
    on the server itself - a closed security group looks exactly like a broken
    application.
NEXT