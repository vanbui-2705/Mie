# Deploy FlowMeta Len VPS Free Bang Oracle Cloud

## Ket Luan Nhanh

Lua chon free phu hop nhat voi project nay la **Oracle Cloud Always Free Ampere A1**.

Ly do:

- Project can chay Docker Compose nhieu service: frontend, backend, worker, browser-worker, browserless, Postgres, Redis, Caddy/Nginx.
- Can RAM cho browser automation/Chrome.
- Cac free tier khac nhu Google e2-micro hoac AWS micro thuong qua yeu cho browser automation.

De xuat cau hinh:

```text
Oracle Cloud Always Free
Ubuntu 24.04 ARM64 hoac Ubuntu 22.04 ARM64
Ampere A1
2 OCPU / 12GB RAM
Neu tao duoc thi 4 OCPU / 24GB RAM
Boot volume 80GB-120GB
```

Luu y: Oracle Ampere la **ARM64**, nen cac Docker image browser phai ho tro ARM64.

## 1. Tao VPS Oracle Free

Vao:

```text
https://www.oracle.com/cloud/free/
```

Tao account Oracle Cloud.

Sau khi vao console:

```text
Compute -> Instances -> Create instance
```

Chon:

```text
Image: Ubuntu 24.04 hoac 22.04
Shape: Ampere A1 ARM
OCPU: 2
RAM: 12GB
```

Neu region cho phep:

```text
OCPU: 4
RAM: 24GB
```

Networking:

```text
Assign public IPv4: Yes
```

SSH key:

- Co the de Oracle generate key va tai private key ve.
- Hoac tu tao key tren may local:

```powershell
ssh-keygen -t ed25519 -C "flowmeta-prod" -f flowmeta_prod
```

Ket qua:

```text
flowmeta_prod      private key, giu kin
flowmeta_prod.pub  public key, dua len Oracle/VPS
```

## 2. Mo Port Tren Oracle

Vao:

```text
Virtual Cloud Network -> Security Lists
```

Hoac:

```text
Network Security Groups
```

Mo inbound:

```text
22 TCP    SSH
80 TCP    HTTP
443 TCP   HTTPS
```

Neu test truc tiep khong qua Caddy/Nginx, co the tam mo:

```text
3000 TCP  frontend
8000 TCP  backend
```

Production chuan chi nen public `80/443`.

## 3. SSH Vao VPS

Tren may local:

```powershell
ssh -i .\flowmeta_prod ubuntu@IP_VPS
```

Neu dung key Oracle tai ve thi thay `flowmeta_prod` bang file private key Oracle.

## 4. Cai Docker Tren VPS

Chay tren VPS:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y ca-certificates curl git ufw
```

Cai Docker:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
```

Thoat SSH va dang nhap lai:

```bash
exit
```

SSH lai, kiem tra:

```bash
docker version
docker compose version
```

## 5. Clone Project Len VPS

Tren VPS:

```bash
sudo mkdir -p /opt/flowmeta
sudo chown -R ubuntu:ubuntu /opt/flowmeta
git clone https://github.com/dinhquangtuy/Comment_Edit_Delete.git /opt/flowmeta
cd /opt/flowmeta
```

Neu code production dang o branch `dev-web-tool`:

```bash
git checkout dev-web-tool
```

Neu muon CD production chay tu `main`, hay merge branch vao `main` truoc khi deploy.

## 6. Tao File `.env` Production

Tren VPS:

```bash
cd /opt/flowmeta
cp .env.example .env
nano .env
```

Dien toi thieu:

```text
POSTGRES_DB=flowmeta
POSTGRES_USER=flowmeta
POSTGRES_PASSWORD=mat_khau_manh

FERNET_KEY=fernet_key_cua_ban
FLOWMETA_TOKEN_SECRET=chuoi_random_dai

APP_DOMAIN=domain-cua-ban.com
ACME_EMAIL=email-cua-ban@gmail.com

NEXT_PUBLIC_API_URL=https://domain-cua-ban.com
CORS_ORIGINS=https://domain-cua-ban.com
```

Tao `FERNET_KEY`:

```bash
python3 - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

Neu VPS chua co package `cryptography`, tao key tren may local cung duoc.

Vi Oracle Ampere la ARM64, can de y phan browser image:

```text
KASM_IMAGE=kasmweb/chromium:aarch64-1.19.0
BROWSERLESS_WS_URL=ws://browserless:3000/chromium
```

Neu Docker image browserless/kasm hien tai bao loi `no matching manifest for linux/arm64`, can doi image sang ban co ho tro ARM64.

## 7. Tro Domain Ve VPS

O noi mua domain, tao DNS record:

```text
A     @      IP_VPS
A     www    IP_VPS
```

Cho DNS cap nhat.

Kiem tra:

```bash
ping domain-cua-ban.com
```

## 8. Chay Production

Tren VPS:

```bash
cd /opt/flowmeta
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

Kiem tra container:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Xem log backend:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
```
Mo web:

```text
https://domain-cua-ban.com
```

## 9. Bootstrap Admin

Sau khi web len, tao mat khau admin:

```bash
curl -X POST https://domain-cua-ban.com/api/auth/bootstrap \
  -H "Content-Type: application/json" \
  -d '{"password":"mat-khau-admin-manh"}'
```

Dang nhap tren web bang:

```text
username: admin
password: mat-khau-admin-manh
```

## 10. Cau Hinh GitHub CD

Vao GitHub repo:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

Them cac secret:

```text
PROD_HOST=IP_VPS
PROD_USER=ubuntu
PROD_PATH=/opt/flowmeta
PROD_SSH_PORT=22
PROD_HEALTH_URL=https://domain-cua-ban.com/api/health
```

`PROD_SSH_KEY` la noi dung private key.

Tren may local Windows:

```powershell
Get-Content .\flowmeta_prod
```

Copy toan bo noi dung:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

Dan vao GitHub secret:

```text
PROD_SSH_KEY
```

## 11. Chay Deploy Tu GitHub Actions

Sau khi da co du secrets:

```bash
git add .
git commit -m "production deploy setup"
git push origin dev-web-tool
```

Neu CD dang chay tren branch `main`:

```bash
git checkout main
git merge dev-web-tool
git push origin main
```

GitHub Actions se chay workflow CD.

## Cau Hinh Khuyen Nghi Cho Project Nay

Ban dau nen de browser automation chay nhe:

```text
BROWSER_WORKER_CONCURRENCY=1
MAX_BROWSER_SESSIONS_GLOBAL=2
MAX_BROWSER_SESSIONS_PER_USER=1
```

Ly do:

- Chrome/browser automation ton RAM.
- Facebook de checkpoint neu chay nhieu session cung luc.
- Nen test on dinh truoc, sau do moi tang concurrency.

## Checklist Sau Khi Deploy

Kiem tra service:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Kiem tra API:

```bash
curl https://domain-cua-ban.com/api/health
```

Kiem tra log:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f browser-worker
```

Kiem tra web:

```text
https://domain-cua-ban.com
```

## Loi Thuong Gap

### Loi image khong ho tro ARM64

Thong bao co the gap:

```text
no matching manifest for linux/arm64
```

Cach xu ly:

- Doi image sang tag ARM64.
- Voi Kasm, thu:

```text
kasmweb/chromium:aarch64-1.19.0
```

- Voi Browserless, dung image Chromium co ho tro `linux/arm64`.

### Web khong vao duoc domain

Kiem tra:

- DNS A record da tro ve IP VPS chua.
- Oracle Security List da mo port `80/443` chua.
- Container Caddy co chay khong.

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f caddy
```

### Backend khong len

Kiem tra `.env`:

- `FERNET_KEY` co dung format khong.
- `POSTGRES_PASSWORD` co khop voi Postgres service khong.
- `CORS_ORIGINS` va `NEXT_PUBLIC_API_URL` co dung domain khong.

Xem log:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f backend
```
