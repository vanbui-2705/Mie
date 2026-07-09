from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_reverse_proxy_configs_are_present() -> None:
    caddyfile = ROOT / "deploy" / "caddy" / "Caddyfile"
    nginx_conf = ROOT / "deploy" / "nginx" / "nginx.conf"
    prod_compose = ROOT / "docker-compose.prod.yml"

    assert caddyfile.exists()
    assert nginx_conf.exists()
    assert prod_compose.exists()
    assert "reverse_proxy backend:8000" in caddyfile.read_text(encoding="utf-8")
    assert "reverse_proxy frontend:3000" in caddyfile.read_text(encoding="utf-8")
    assert "proxy_pass http://backend_upstream" in nginx_conf.read_text(encoding="utf-8")
    assert "proxy_pass http://frontend_upstream" in nginx_conf.read_text(encoding="utf-8")
