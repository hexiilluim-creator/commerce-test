"""services/ssrf_guard.py — Validation anti-SSRF pour les URLs configurées par les tenants.

Contexte (AUDIT FIX, CRITICAL) : plusieurs endpoints permettent à un marchand
de configurer une URL externe (API stock, test de connecteur) que le backend
va ensuite appeler lui-même — depuis le réseau interne, avec potentiellement
une clé API secrète dans les headers. Sans validation, n'importe quel tenant
authentifié peut faire pointer cette URL vers :
  - 169.254.169.254 (métadonnées cloud AWS/GCP/Azure — vol de credentials IAM)
  - localhost / 127.0.0.1 / services internes du réseau Docker (Redis, DB admin...)
  - des plages IP privées (RFC1918) non censées être joignables depuis l'extérieur

Ce module résout le hostname AVANT l'appel HTTP et rejette toute IP privée,
loopback, link-local ou réservée — y compris via DNS rebinding (on résout et
on vérifie l'IP réellement utilisée, pas juste le nom d'hôte apparent).
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class SSRFBlocked(Exception):
    """Levée quand une URL configurée par un tenant pointe vers une cible interdite."""


_BLOCKED_HOSTNAMES = {"localhost", "metadata.google.internal"}


def assert_safe_external_url(url: str) -> None:
    """Lève SSRFBlocked si `url` ne doit pas être appelée depuis le backend.

    À appeler juste avant tout httpx.get/post sur une URL fournie par un
    tenant. Ne protège pas contre les redirections HTTP — les appelants
    doivent utiliser httpx avec follow_redirects=False (comportement par
    défaut de httpx.AsyncClient).
    """
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise SSRFBlocked(f"Schéma non autorisé : {parsed.scheme!r}")

    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlocked("URL sans hostname")

    if hostname.lower() in _BLOCKED_HOSTNAMES:
        raise SSRFBlocked(f"Hostname interdit : {hostname}")

    # Résolution DNS explicite — on valide l'IP réellement contactée, pas le
    # nom d'hôte, pour se prémunir du DNS rebinding (un nom en apparence
    # externe qui résout vers une IP interne).
    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise SSRFBlocked(f"Résolution DNS impossible pour {hostname}: {exc}") from exc

    for family, _, _, _, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise SSRFBlocked(
                f"URL résout vers une IP interne/réservée non autorisée : {hostname} -> {ip}"
            )
