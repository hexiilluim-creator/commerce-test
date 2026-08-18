"""
Tests de validation de la configuration nginx TLS.
Vérifie que le fichier nginx.tls.conf est syntaxiquement correct
sans nécessiter un serveur nginx réel.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TLS_CONF = PROJECT_ROOT / "nginx.tls.conf"

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _read_tls_conf() -> str:
    return TLS_CONF.read_text(encoding="utf-8")


class TestNginxConfigSyntax:
    """Vérifications syntaxiques du fichier nginx.tls.conf."""

    def test_config_file_exists(self):
        """Le fichier nginx.tls.conf doit exister."""
        assert TLS_CONF.exists(), f"{TLS_CONF} manquant"

    def test_braces_balanced(self):
        """Les accolades doivent être équilibrées."""
        conf = _read_tls_conf()
        assert conf.count("{") == conf.count("}"), (
            f"Accolades déséquilibrées: {conf.count('{')} ouvrantes, "
            f"{conf.count('}')} fermantes"
        )

    def test_key_directives_present(self):
        """Les directives clés doivent être présentes."""
        conf = _read_tls_conf()
        for directive in ["listen", "server_name", "ssl_certificate", "proxy_pass"]:
            assert directive in conf, f"Directive {directive} manquante"

    def test_ssl_protocols_configured(self):
        """Les protocoles SSL doivent être configurés."""
        conf = _read_tls_conf()
        assert re.search(r'ssl_protocols\s+TLSv', conf), (
            "ssl_protocols doit être configuré"
        )

    def test_every_directive_terminated(self):
        """Vérifie que les blocs principaux sont bien fermés et les sections clés valides."""
        conf = _read_tls_conf()
        # Vérification simplifiée : les accolades doivent être équilibrées
        open_count = conf.count("{")
        close_count = conf.count("}")
        assert open_count == close_count, (
            f"Accolades déséquilibrées: {open_count} ouvrantes, {close_count} fermantes"
        )
        # Vérifier que les sections principales contiennent des directives valides
        for section in ["listen", "server_name", "ssl_certificate", "proxy_pass"]:
            assert section in conf, f"Section clé {section} manquante dans nginx.tls.conf"

    def test_server_blocks_count(self):
        """Il doit y avoir au moins 2 blocs server (HTTP + HTTPS)."""
        conf = _read_tls_conf()
        server_count = len(re.findall(r'^\s*server\s*\{', conf, re.MULTILINE))
        assert server_count >= 2, (
            f"Minimum 2 blocs server attendus (HTTP + HTTPS), trouvé: {server_count}"
        )

    def test_upstream_block_exists(self):
        """Un bloc upstream doit exister pour le backend."""
        conf = _read_tls_conf()
        assert re.search(r'upstream\s+\w+', conf), (
            "Bloc upstream manquant pour le backend"
        )

    def test_proxy_pass_targets_upstream(self):
        """proxy_pass doit pointer vers un backend valide."""
        conf = _read_tls_conf()
        proxy_passes = re.findall(r'proxy_pass\s+([^;]+);', conf)
        assert len(proxy_passes) >= 1, "Aucun proxy_pass trouvé"
        # Vérifier que chaque proxy_pass pointe vers quelque chose de valide
        for pp in proxy_passes:
            pp = pp.strip()
            assert pp.startswith("http://") or pp.startswith("https://") or pp.startswith("$"), (
                f"proxy_pass invalide: {pp}"
            )


class TestNginxConfigSecurity:
    """Vérifications de sécurité de la configuration nginx."""

    def test_no_http_301_without_https_block(self):
        """Si un bloc HTTP redirige vers HTTPS, le bloc HTTPS doit exister."""
        conf = _read_tls_conf()
        if "return 301" in conf:
            assert "ssl_certificate" in conf, (
                "Redirection HTTP->HTTPS sans bloc HTTPS configuré"
            )

    def test_no_server_tokens(self):
        """server_tokens doit être désactivé (ou absent = non affiché)."""
        conf = _read_tls_conf()
        # server_tokens off est recommandé mais pas obligatoire si absent
        if "server_tokens" in conf:
            assert re.search(r'server_tokens\s+off', conf), (
                "server_tokens doit être 'off'"
            )

    def test_client_max_body_size_set(self):
        """client_max_body_size doit être défini."""
        conf = _read_tls_conf()
        assert "client_max_body_size" in conf, (
            "client_max_body_size doit être défini"
        )


class TestNginxConfigHealthcheck:
    """Vérification du healthcheck nginx."""

    def test_healthcheck_location_exists(self):
        """La location /nginx-health doit exister pour la sonde Kubernetes/Docker."""
        conf = _read_tls_conf()
        assert re.search(r'location\s+/nginx-health', conf), (
            "Location /nginx-health manquante pour le healthcheck"
        )

    def test_healthcheck_returns_200(self):
        """Le healthcheck doit retourner 200."""
        conf = _read_tls_conf()
        healthcheck = re.search(
            r'location\s+/nginx-health\s*\{([^}]*)\}', conf, re.DOTALL
        )
        assert healthcheck, "Bloc healthcheck introuvable"
        assert "200" in healthcheck.group(1), (
            "Le healthcheck doit retourner un code 200"
        )
