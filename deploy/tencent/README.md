# Tencent Cloud LightHouse Deployment

This directory contains the production deployment path for:

- Tencent Cloud LightHouse
- Docker Compose
- Caddy reverse proxy with automatic HTTPS
- Tencent Cloud DNS / DNSPod domain records

Files:

- `docker-compose.tencent.yml`: app + reverse proxy stack
- `Caddyfile`: HTTPS reverse proxy
- `app.env.example`: application runtime variables
- `caddy.env.example`: domain variable for Caddy
- `server-setup.sh`: install Docker on Ubuntu
- `deploy.sh`: build and start the stack
- `update.sh`: refresh the running stack after `git pull`

Recommended runtime values:

- `APP_DOMAIN=zungit.com`
- `OFFER_AGENT_BASIC_AUTH_USER=jayz`
- `OFFER_AGENT_READ_ONLY=false`
