# Provisioning the Oracle always-free VM (Phase 0)

The one manual, human-driven step. Everything after this is scripted. Target: an
Ampere **A1.Flex ARM** instance from Oracle's *always-free* tier — 4 OCPU / 24 GB,
always-on (no sleep), enough to run the whole `docker-compose` stack (Postgres +
pgvector, Redis, Neo4j, and the API with its ~3.2 GB of local models) unchanged.

## 1. Create the instance

OCI Console → **Compute → Instances → Create instance**:

- **Shape:** Ampere → `VM.Standard.A1.Flex`, **4 OCPU / 24 GB**. If you get
  *"Out of host capacity"*, retry in another Availability Domain, then another
  home region; 2 OCPU / 12 GB is enough if 4/24 is unavailable.
- **Image:** Canonical **Ubuntu 22.04** (aarch64).
- **SSH keys:** paste your **public** key.
- **Boot volume:** 50 GB is plenty (free tier allows 200 GB total).

## 2. Open only 80/443

- **VCN → Security List → Ingress rules:**
  - TCP **22** from **your IP only** (not `0.0.0.0/0`).
  - TCP **80** and **443** from `0.0.0.0/0`.
  - Remove everything else.
- Oracle's Ubuntu images also ship a locked-down host firewall; open 80/443 on it
  (step 4 below).

## 3. First SSH + Docker

```bash
ssh ubuntu@<VM_IP>
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu && newgrp docker
docker --version && docker compose version
```

## 4. Host firewall (open 80/443)

```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 5. Harden

```bash
sudo apt-get update && sudo apt-get -y install fail2ban
sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
sudo systemctl enable --now fail2ban
```

## 6. Swap (safety margin for build spikes)

```bash
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 7. Clone + configure

```bash
git clone https://github.com/krish2105/masar-ai.git ~/masar && cd ~/masar
cp .env.example .env && chmod 600 .env
# Edit .env — at minimum:
#   GROQ_API_KEY, GEMINI_API_KEY        (free, no card)
#   CORS_ORIGINS=https://masar-ai-xi.vercel.app
#   MASAR_HOSTNAME=masar-api.duckdns.org   (a free DuckDNS subdomain → <VM_IP>)
#   NEO4J_PASSWORD=<something long>
```

## Gate

```bash
ssh ubuntu@<VM_IP> 'docker compose version && free -h && sudo iptables -L INPUT -n | grep -E "80|443"'
```

Docker Compose v2 prints, ~24G (or 12G) memory, ACCEPT rules for 80 and 443.
You're ready for **[go-live](README.md#going-live)**.
