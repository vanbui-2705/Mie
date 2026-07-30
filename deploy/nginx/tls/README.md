# TLS for the nginx profile

`deploy/nginx/nginx.conf` ends its `http` block with:

```nginx
include /etc/nginx/tls/*.conf;
```

This directory is mounted there. It ships **no** `.conf` file, so the nginx
profile starts as plain HTTP on `${NGINX_PORT:-8080}` — meant to sit behind a
load balancer or Caddy that already terminates TLS.

To let nginx itself terminate TLS:

1. Put the certificate and key where nginx can read them, e.g.
   `deploy/nginx/tls/certs/fullchain.pem` and `privkey.pem` (obtained with
   certbot on the host, or copied from your CA).
2. Copy `server-tls.conf.example` to `server-tls.conf` in this directory.
3. Publish 443 for the nginx service and reload:
   `docker compose --profile nginx exec nginx nginx -s reload`

`server-tls.conf` also turns the port-80 server into a redirect, so edit both
files together — leaving the plain server in `nginx.conf` serving the app on 80
defeats the point.

**The default production path in this repo is Caddy** (`docker-compose.prod.yml`),
which gets certificates over ACME with no manual step. Use the nginx profile
only if you specifically need nginx.
