# VPS-2 SkullTrading-App — operations runbook

Target host: `api.skulltrading.com` (Infomaniak Public Cloud "S" — 2 vCPU,
4 GB RAM, 80 GB SSD, Ubuntu 24.04 LTS).

Hostname convention: `vps2-skulltrading-app`.

The VPS-2 host is **dedicated to the commercial app**. The existing VPS-1
host that runs the personal trading bot is untouched.

---

## 1. Provisioning checklist

### 1.1 Order the VPS

- Infomaniak Public Cloud "S" — Ubuntu 24.04 LTS.
- Region: Switzerland (Geneva or Zurich; pick whichever has lower latency
  from your laptop and from the VPS-1 host).
- SSH public key uploaded at order time.

### 1.2 First login (one-time hardening)

Connect as the cloud-init user (usually `ubuntu`), then:

```bash
# Update everything
sudo apt update && sudo apt -y upgrade && sudo apt -y autoremove

# Create the service user
sudo adduser --disabled-password --gecos "" skull
sudo usermod -aG sudo skull
sudo mkdir -p /home/skull/.ssh
sudo cp ~/.ssh/authorized_keys /home/skull/.ssh/
sudo chown -R skull:skull /home/skull/.ssh
sudo chmod 700 /home/skull/.ssh && sudo chmod 600 /home/skull/.ssh/authorized_keys

# Lock down SSH
sudo sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#*KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh

# Firewall
sudo apt -y install ufw
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable

# fail2ban for SSH brute force
sudo apt -y install fail2ban
sudo systemctl enable --now fail2ban

# Automatic security updates
sudo apt -y install unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

Reconnect as `skull@vps2-skulltrading-app` and confirm `ubuntu` login is
no longer required.

### 1.3 Install Docker + Compose

```bash
sudo apt -y install ca-certificates curl gnupg
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list

sudo apt update
sudo apt -y install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker skull

# Re-login so the group change takes effect
exit
```

### 1.4 DNS

In your DNS zone for `skulltrading.com`:

- A record `api` → public IP of VPS-2.
- Wait for propagation (`dig api.skulltrading.com +short`).

### 1.5 Reverse proxy + TLS (Caddy)

Caddy is simpler than Nginx for our one-host case and handles
Let's Encrypt automatically.

```bash
sudo apt -y install debian-keyring debian-archive-keyring apt-transport-https
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | \
    sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | \
    sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt -y install caddy
```

`/etc/caddy/Caddyfile`:

```
api.skulltrading.com {
    encode zstd gzip

    # Hide details
    header -Server
    header Strict-Transport-Security "max-age=63072000; includeSubDomains"
    header X-Content-Type-Options "nosniff"
    header Referrer-Policy "no-referrer"

    reverse_proxy 127.0.0.1:8000 {
        header_up X-Real-IP {remote_host}
        health_uri /health
        health_interval 30s
    }
}
```

```bash
sudo systemctl reload caddy
```

### 1.6 Postgres + Redis (containers)

The app's local DB only holds the `signal_cache` and operational metrics.
Authoritative user data lives in Supabase.

```bash
sudo mkdir -p /srv/skulltrading-app
sudo chown -R skull:skull /srv/skulltrading-app
cd /srv/skulltrading-app
```

Copy `vps2-api/docker-compose.yml` and `vps2-api/.env.example`
from this repository to `/srv/skulltrading-app/`.

```bash
cp .env.example .env
chmod 600 .env
# Fill in the real values (see docs/BACKEND_V2.md)
docker compose up -d postgres redis
```

### 1.7 Deploy the FastAPI service

From your laptop:

```bash
cd vps2-api
rsync -avz --delete \
    --exclude='.venv' --exclude='__pycache__' --exclude='*.pyc' \
    ./ skull@api.skulltrading.com:/srv/skulltrading-app/api/
```

On the VPS:

```bash
cd /srv/skulltrading-app
docker compose up -d --build api
docker compose ps
docker compose logs -f api
```

Sanity check:

```bash
curl -s https://api.skulltrading.com/health | jq .
# {"status": "ok", "version": "...", "vps1_reachable": true}
```

### 1.8 Backups

Postgres dump every night to Infomaniak Swiss Backup (or S3-compatible):

`/etc/cron.daily/skulltrading-app-backup`:

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR=/var/backups/skulltrading-app
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date -u +%Y%m%dT%H%M%SZ)
docker compose -f /srv/skulltrading-app/docker-compose.yml exec -T postgres \
    pg_dump -U skull -F c skulltrading_app \
    > "$BACKUP_DIR/skulltrading_app_${TIMESTAMP}.dump"
# Keep 14 days
find "$BACKUP_DIR" -name "skulltrading_app_*.dump" -mtime +14 -delete
# Off-site (configure rclone remote 'swiss-backup' first)
rclone copy "$BACKUP_DIR" swiss-backup:skulltrading-app-backups \
    --include "skulltrading_app_${TIMESTAMP}.dump"
```

```bash
sudo chmod +x /etc/cron.daily/skulltrading-app-backup
```

### 1.9 Monitoring

Prometheus node + postgres exporters live in the docker-compose stack;
Grafana is on the same host on port `127.0.0.1:3000` (proxied through Caddy
at `grafana.skulltrading.com` with basic auth — optional). Start with the
Grafana dashboards in `ops/monitoring/`.

Alert channels: a Telegram bot you DM personally. Set up in Grafana
Alerting → Contact points.

Minimum alerts:
- HTTP error rate > 5 % for 5 min
- Endpoint p95 latency > 300 ms for 5 min
- VPS CPU > 80 % for 10 min
- Disk free < 15 %
- Webhook receive failures > 1 in 5 min

---

## 2. Day-to-day operations

### 2.1 Deploy a new version of the API

```bash
# On laptop
cd vps2-api
git pull
rsync -avz --delete ./ skull@api.skulltrading.com:/srv/skulltrading-app/api/

# On VPS
ssh skull@api.skulltrading.com
cd /srv/skulltrading-app
docker compose up -d --build api
docker compose logs -f --tail=100 api
```

Zero-downtime is *not* required for V1. Brief restarts (~2 s) are fine.

### 2.2 Restart everything safely

```bash
docker compose restart      # restarts every service
# Or selectively:
docker compose restart api
```

### 2.3 Check VPS-1 reachability

```bash
ssh skull@api.skulltrading.com
curl -s -H "X-Service-Token: $SERVICE_TOKEN" \
    "$VPS1_BASE_URL/api/v2/health-from-vps1" | jq .
```

### 2.4 Manually replay a missed signal

If a webhook from VPS-1 to VPS-2 was lost:

```bash
ssh skull@api.skulltrading.com
docker compose exec api python -m app.tools.replay_signal \
    --signal-id <id-on-vps1>
```

---

## 3. Incident response

### 3.1 The iOS app is showing stale signals

1. Check `https://api.skulltrading.com/health`.
2. `docker compose ps` on VPS-2 — is `api` healthy?
3. `docker compose logs --tail=200 api` — any errors?
4. Confirm VPS-1 is producing signals (check VPS-1 dashboard).
5. If VPS-1 is healthy and VPS-2 is reachable but new signals aren't
   showing up: the webhook is broken. Look at the VPS-1 logs for
   `emit_signal_to_app_vps` errors.

### 3.2 Push notifications stopped arriving

1. Check the `notify-subscribers` Edge Function logs in Supabase dashboard.
2. Verify the APNS certificate is not expired
   (Apple Developer → Keys → APNS Auth Key).
3. `APNS_USE_SANDBOX` must match the build channel
   (`sandbox` for TestFlight, `production` for App Store).

### 3.3 VPS-2 is down (host unresponsive)

The iOS app gracefully degrades: it shows cached signals from the device
and a "Reconnecting…" banner. VPS-1 keeps trading on its own (your bot
is unaffected).

1. Try `ssh skull@api.skulltrading.com`.
2. Infomaniak dashboard → VM status → reboot if needed.
3. Once back: `docker compose up -d` brings everything back.
4. Inspect any webhooks that arrived during the outage in the
   `signal_cache_dead_letter` table — these need manual replay.

### 3.4 VPS-1 is down (host unresponsive)

This is **your personal trading bot**, so this incident is critical for
you regardless of the app. The app side is graceful: VPS-2 keeps serving
the cached signals to subscribers. Once VPS-1 is back, new signals flow
again automatically.

### 3.5 Suspected credential leak

If you suspect the master encryption key (`binance_creds_v1`) has been
compromised:

1. Immediately revoke the Supabase service role key in the dashboard
   and rotate it.
2. Force-disable every active credential row:
   `UPDATE binance_credentials SET is_active = false;`
3. Notify users in-app: "For your security, please reconnect Binance."
4. Provision `binance_creds_v2` per the rotation procedure in
   `docs/BACKEND_V2.md`.

---

## 4. SLOs (informal, V1)

- API uptime ≥ 99.5 % monthly.
- Push notification arrival ≤ 5 s end-to-end (p95).
- Endpoint latency p95 ≤ 300 ms (excluding VPS-1 proxy calls).
- Webhook from VPS-1 to VPS-2 reliability ≥ 99 %.
