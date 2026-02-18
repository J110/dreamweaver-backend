# Dream Valley — Environment Configuration Reference

> **Purpose**: Single source of truth for all deployment environments — testing (Render/Vercel) and production (GCP). Reference this before any deployment to ensure correct configuration.

---

## Environment Map

| | **Testing** | **Production** |
|---|---|---|
| **Frontend** | Vercel (auto-deploy) | GCP VM → PM2 → Next.js standalone |
| **Frontend URL** | `https://dreamweaver-web-*.vercel.app` | `https://dreamvalley.app` |
| **Backend** | Render (auto-deploy) | GCP VM → Docker Compose → FastAPI |
| **Backend URL** | `https://dreamweaver-api.onrender.com` | `https://api.dreamvalley.app` |
| **Deploy trigger** | `git push` to main | Manual SSH + commands |
| **SSL** | Managed by platform | Let's Encrypt (Certbot auto-renew) |
| **IP** | Dynamic (platform) | Static: `34.14.172.180` |

---

## 1. Testing Environment (Render + Vercel)

### 1.1 Frontend — Vercel

| Property | Value |
|----------|-------|
| Platform | Vercel |
| Repo | `J110/dreamweaver-web` (main branch) |
| Framework | Next.js 14 |
| Deploy trigger | Auto on `git push` to main |
| Build command | `npm run build` (default) |
| Output | Next.js default (not standalone) |

**Environment Variables (set in Vercel dashboard):**

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://dreamweaver-api.onrender.com` |

**What gets deployed:**
- `src/` — all Next.js pages and components
- `public/audio/pre-gen/*.mp3` — pre-generated audio files
- `public/covers/*.svg` — cover illustrations
- `src/utils/seedData.js` — seed content data

### 1.2 Backend — Render

| Property | Value |
|----------|-------|
| Platform | Render |
| Repo | `J110/dreamweaver-backend` (main branch) |
| Runtime | Python 3.11.7 |
| Deploy trigger | Auto on `git push` to main |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Config file | `render.yaml` |

**Environment Variables (set in Render dashboard):**

| Variable | Value | Notes |
|----------|-------|-------|
| `PYTHON_VERSION` | `3.11.7` | |
| `ENVIRONMENT` | `production` | |
| `DEBUG` | `false` | |
| `GROQ_API_KEY` | `gsk_...` | Set manually |
| `CORS_ORIGINS` | `*` | |
| `CHATTERBOX_URL` | `https://anmol-71634--dreamweaver-chatterbox-tts.modal.run` | Set manually |
| `DEFAULT_TTS_PROVIDER` | `edge-tts` | |
| `SECRET_KEY` | random string | Set manually |

**Render-specific behavior:**
- Free tier sleeps after 15 min inactivity (FastAPI has built-in keep-alive every 14 min)
- `$PORT` is injected by Render (not 8000)
- No persistent disk — audio files served from git repo
- Keep-alive detects `RENDER` env var automatically

### 1.3 Testing Deploy Process

```
Developer pushes to main branch
       │
       ├── Backend repo (J110/dreamweaver-backend)
       │   └── Render detects push → builds → deploys API
       │
       └── Frontend repo (J110/dreamweaver-web)
           └── Vercel detects push → builds → deploys web app
```

**No manual steps required.** Both platforms auto-deploy on push.

### 1.4 Testing Verification

```bash
# Backend health
curl https://dreamweaver-api.onrender.com/health

# Frontend (check in browser)
# https://dreamweaver-web-*.vercel.app
```

---

## 2. Production Environment (GCP)

### 2.1 Server Details

| Property | Value |
|----------|-------|
| Cloud | Google Cloud Platform |
| Project | `strong-harbor-472607-n4` |
| Instance | `dreamvalley-prod` |
| Zone | `asia-south1-a` (Mumbai) |
| Machine | `e2-small` (2 vCPU, 2 GB RAM) |
| Disk | 30 GB SSD |
| Static IP | `34.14.172.180` |
| OS | Ubuntu/Debian |

**SSH Access:**
```bash
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a
```

### 2.2 DNS Records (GoDaddy)

| Type | Name | Value |
|------|------|-------|
| A | `@` | `34.14.172.180` |
| A | `api` | `34.14.172.180` |
| MX | `@` | `mx1.improvmx.com` (priority 10) |
| MX | `@` | `mx2.improvmx.com` (priority 20) |
| TXT | `@` | SPF include for ImprovMX |

### 2.3 Process Architecture

```
                    Internet
                       │
                   ┌───┴───┐
                   │ Nginx │  (ports 80/443, SSL termination)
                   └───┬───┘
                       │
         ┌─────────────┼─────────────┐
         │                           │
   dreamvalley.app            api.dreamvalley.app
         │                           │
   ┌─────┴─────┐            ┌───────┴────────┐
   │ PM2       │            │ Docker Compose  │
   │ port 3000 │            │ port 8000       │
   │           │            │                 │
   │ Next.js   │            │ FastAPI         │
   │ standalone│            │ (uvicorn)       │
   └───────────┘            └─────────────────┘
```

**Process details:**

| Process | Manager | Port | Path | Start Command |
|---------|---------|------|------|---------------|
| Frontend | PM2 | 3000 | `/opt/dreamweaver-web/` | `node .next/standalone/server.js` |
| Backend | Docker Compose | 8000 | `/opt/dreamweaver-backend/` | `uvicorn app.main:app --host 0.0.0.0 --port 8000` |
| Nginx | systemd | 80/443 | `/etc/nginx/` | `systemctl start nginx` |
| Certbot | systemd timer | — | — | Auto-renewal |

### 2.4 Frontend — GCP (Next.js + PM2)

| Property | Value |
|----------|-------|
| Path | `/opt/dreamweaver-web/` |
| Build | `npm run build` (standalone output) |
| Runtime | `node .next/standalone/server.js` |
| Port | 3000 |
| Manager | PM2 |

**Environment Variable:**

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://api.dreamvalley.app` |

**CRITICAL — Post-build static asset copy:**
```bash
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
```
> Next.js standalone build does NOT include static assets. Skipping this step breaks all CSS, images, audio, and covers.

### 2.5 Backend — GCP (Docker Compose)

| Property | Value |
|----------|-------|
| Path | `/opt/dreamweaver-backend/` |
| Runtime | Docker (Python 3.11-slim) |
| Port | 8000 |
| Config | `docker-compose.yml` |
| Health check | `curl http://localhost:8000/health` |

**Environment Variables** (in `/opt/dreamweaver-backend/.env`):

| Variable | Value | Notes |
|----------|-------|-------|
| `APP_NAME` | `DreamValley` | |
| `ENVIRONMENT` | `production` | |
| `DEBUG` | `false` | |
| `GROQ_API_KEY` | `gsk_...` | Required for AI generation |
| `ANTHROPIC_API_KEY` | `sk-ant-...` | Optional |
| `MISTRAL_API_KEY` | `nkMw...` | Required for pipeline |
| `FIREBASE_CREDENTIALS_PATH` | `/app/firebase-credentials.json` | Inside Docker container |
| `STORAGE_BUCKET` | `dreamweaver-app.appspot.com` | Firebase Storage |
| `CORS_ORIGINS` | `https://dreamvalley.app` | Strict in production |
| `MAX_CONTENT_PER_DAY_FREE` | `3` | |
| `MAX_CONTENT_PER_DAY_PREMIUM` | `10` | |
| `SECRET_KEY` | strong random string | JWT signing |
| `ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `1440` | 24 hours |
| `CHATTERBOX_URL` | `https://anmol-71634--dreamweaver-chatterbox-tts.modal.run` | Modal TTS |
| `DEFAULT_TTS_PROVIDER` | `edge-tts` | |

### 2.6 Nginx Configuration

| Domain | Upstream | Rate Limit | SSL Cert |
|--------|----------|------------|----------|
| `dreamvalley.app` | `http://127.0.0.1:3000` | 50 req/s (burst 100) | `/etc/letsencrypt/live/dreamvalley.app/` |
| `api.dreamvalley.app` | `http://127.0.0.1:8000` | 30 req/s (burst 60) | `/etc/letsencrypt/live/api.dreamvalley.app/` |
| `www.dreamvalley.app` | 301 → `dreamvalley.app` | — | Same as above |

**Static asset caching (Nginx):**

| Path | Cache Duration | Notes |
|------|---------------|-------|
| `/_next/static/` | 365 days | Hashed filenames, immutable |
| `/audio/` | 365 days | Pre-gen audio, immutable |
| `/covers/` | 30 days | SVG covers |
| `/audio/pre-gen/` (API) | 365 days | Served directly from disk by Nginx |
| `/*.ico,svg,png` | 30 days | Favicons, logos |

**API backend special Nginx rule:**
```nginx
location /audio/pre-gen/ {
    alias /opt/dreamweaver-backend/audio/pre-gen/;
    expires 365d;
    add_header Cache-Control "public, immutable";
}
```
> Audio files on the API subdomain are served directly by Nginx from disk, bypassing FastAPI entirely.

---

## 3. Production Deploy Steps

### 3.1 Frontend Deploy (GCP)

```bash
# SSH into server
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a

# Fix permissions if needed
sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-web/

# Pull latest code
cd /opt/dreamweaver-web
git pull

# Build
npm run build

# CRITICAL: Copy static assets to standalone output
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static

# Restart
pm2 restart all

# Verify
curl -I https://dreamvalley.app
pm2 status
```

### 3.2 Backend Deploy (GCP)

```bash
# SSH into server
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a

# Pull latest code
cd /opt/dreamweaver-backend
git pull

# Rebuild and restart Docker
sudo docker-compose build --no-cache
sudo docker-compose up -d

# Verify
curl https://api.dreamvalley.app/health
sudo docker-compose ps
sudo docker-compose logs --tail=20
```

### 3.3 Deploy Both (Most Common)

```bash
# SSH in
gcloud compute ssh dreamvalley-prod \
  --project=strong-harbor-472607-n4 \
  --zone=asia-south1-a

# Backend first
cd /opt/dreamweaver-backend
git pull
sudo docker-compose build --no-cache
sudo docker-compose up -d

# Frontend
cd /opt/dreamweaver-web
sudo chown -R anmolmohan:anmolmohan /opt/dreamweaver-web/
git pull
npm run build
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
pm2 restart all

# Verify both
curl https://api.dreamvalley.app/health
curl -I https://dreamvalley.app
pm2 status
sudo docker-compose -f /opt/dreamweaver-backend/docker-compose.yml ps
```

---

## 4. Key Differences: Testing vs Production

| Aspect | Testing (Render/Vercel) | Production (GCP) |
|--------|------------------------|-------------------|
| **Deploy** | Auto on `git push` | Manual SSH + commands |
| **Frontend build** | Vercel default | Standalone + asset copy |
| **Backend runtime** | Render (uvicorn) | Docker Compose (uvicorn in container) |
| **Audio serving** | From git repo (public/) | Nginx direct from disk + Docker volume |
| **CORS** | `*` (allow all) | `https://dreamvalley.app` only |
| **SSL** | Platform-managed | Certbot (Let's Encrypt) |
| **Rate limiting** | None | Nginx: 30r/s API, 50r/s web |
| **Persistence** | None (Render free = ephemeral) | Docker volumes + disk |
| **Keep-alive** | FastAPI background task (14 min) | Not needed (always on) |
| **Token expiry** | 30 min | 1440 min (24 hr) |
| **Content limits** | Free: 1/day, Premium: 5/day | Free: 3/day, Premium: 10/day |
| **Firebase** | Not configured | Full auth + storage |
| **Security headers** | Platform defaults | Full Nginx headers (HSTS, CSP, etc.) |

---

## 5. Content Pipeline Deploy

When the automated pipeline runs (locally or on GCP), it pushes to both repos:

```
Pipeline output
     │
     ├── git push dreamweaver-backend (main)
     │   ├── Render: auto-deploys (testing)
     │   └── GCP: requires manual docker-compose rebuild
     │
     └── git push dreamweaver-web (main)
         ├── Vercel: auto-deploys (testing)
         └── GCP: requires manual npm run build + pm2 restart
```

**After pipeline run — deploy to testing:**
- Nothing to do! Render and Vercel auto-deploy.

**After pipeline run — deploy to production:**
```bash
# SSH in, then:
cd /opt/dreamweaver-web && git pull && npm run build && \
  cp -r public .next/standalone/public && \
  cp -r .next/static .next/standalone/.next/static && \
  pm2 restart all

# Backend only if content.json or API changes are needed:
cd /opt/dreamweaver-backend && git pull && \
  sudo docker-compose build --no-cache && \
  sudo docker-compose up -d
```

---

## 6. Health Checks

| Environment | Frontend | Backend |
|-------------|----------|---------|
| Testing | Open Vercel URL in browser | `curl https://dreamweaver-api.onrender.com/health` |
| Production | `curl -I https://dreamvalley.app` | `curl https://api.dreamvalley.app/health` |
| Local | `curl http://localhost:3000` | `curl http://localhost:8000/health` |

---

## 7. Monitoring Commands (Production Only)

```bash
# Process status
pm2 status                                    # Frontend
sudo docker-compose -f /opt/dreamweaver-backend/docker-compose.yml ps  # Backend

# Logs
pm2 logs dreamvalley-web --lines 50           # Frontend logs
sudo docker-compose -f /opt/dreamweaver-backend/docker-compose.yml logs --tail=50  # Backend logs
sudo tail -f /var/log/nginx/access.log        # Nginx access
sudo tail -f /var/log/nginx/error.log         # Nginx errors

# SSL certificates
sudo certbot certificates
sudo certbot renew --dry-run

# System resources
df -h && free -h
sudo docker stats --no-stream
```

---

## 8. Rollback Procedures

### Frontend Rollback
```bash
cd /opt/dreamweaver-web
git log --oneline -5           # Find previous good commit
git checkout <commit-hash> -- .
npm run build
cp -r public .next/standalone/public
cp -r .next/static .next/standalone/.next/static
pm2 restart all
```

### Backend Rollback
```bash
cd /opt/dreamweaver-backend
git log --oneline -5
git checkout <commit-hash> -- .
sudo docker-compose build --no-cache
sudo docker-compose up -d
```

---

*Last updated: 2026-02-18. Reference this document before every deployment.*
