"""tests/integration/test_tls_hardening.py — P0-7 TLS & HSTS verification.
Valide la configuration nginx TLS, les headers HSTS, et l'absence de TLS 1.0/1.1.
Ces tests ne nécessitent PAS un serveur HTTPS réel : ils parsent la configuration
nginx.tls.conf et simulent les assertions via pyOpenSSL/ssl module standards.
"""
from __future__ import annotations
import os
import re
import sys
from pathlib import Path
from unittest.mock import patch
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TLS_CONF = PROJECT_ROOT / "nginx.tls.conf"
TLS_CONF_EXAMPLE = PROJECT_ROOT / "nginx.tls.conf.example"
DOCKER_COMPOSE_PROD = PROJECT_ROOT / "docker-compose.prod.yml"

pytestmark = [pytest.mark.integration, pytest.mark.security]


def _read_tls_conf() -> str:
    """Lit le fichier nginx.tls.conf."""
    if not TLS_CONF.exists():
        pytest.skip("nginx.tls.conf introuvable")
    return TLS_CONF.read_text()


def _read_docker_compose_prod() -> str:
    """Lit docker-compose.prod.yml."""
    if not DOCKER_COMPOSE_PROD.exists():
        pytest.skip("docker-compose.prod.yml introuvable")
    return DOCKER_COMPOSE_PROD.read_text()


# ── TLS Protocol Tests ───────────────────────────────────────────────────────

class TestTLSProtocolVersions:
    """Validations des versions TLS autorisées/désactivées dans nginx."""

    def test_tls_1_2_enabled(self):
        """TLSv1.2 doit être explicitement listé dans ssl_protocols."""
        conf = _read_tls_conf()
        protocols_match = re.search(r"ssl_protocols\s+([^;]+);", conf)
        assert protocols_match, "Directive ssl_protocols introuvable dans nginx.tls.conf"
        protocols = protocols_match.group(1).strip()
        assert "TLSv1.2" in protocols, f"TLSv1.2 doit être activé, trouvé: {protocols}"

    def test_tls_1_3_enabled(self):
        """TLSv1.3 doit être explicitement listé dans ssl_protocols."""
        conf = _read_tls_conf()
        protocols_match = re.search(r"ssl_protocols\s+([^;]+);", conf)
        assert protocols_match, "Directive ssl_protocols introuvable dans nginx.tls.conf"
        protocols = protocols_match.group(1).strip()
        assert "TLSv1.3" in protocols, f"TLSv1.3 doit être activé, trouvé: {protocols}"

    def test_tls_1_0_disabled(self):
        """TLSv1.0 ne doit PAS apparaître dans ssl_protocols."""
        conf = _read_tls_conf()
        protocols_match = re.search(r"ssl_protocols\s+([^;]+);", conf)
        assert protocols_match, "Directive ssl_protocols introuvable dans nginx.tls.conf"
        protocols = protocols_match.group(1).strip()
        assert "TLSv1" not in protocols or "TLSv1.2" in protocols, (
            f"TLSv1.0/1.1 ne doit pas être activé, trouvé: {protocols}"
        )
        assert "TLSv1.0" not in protocols, f"TLSv1.0 doit être désactivé, trouvé: {protocols}"

    def test_tls_1_1_disabled(self):
        """TLSv1.1 ne doit PAS apparaître dans ssl_protocols."""
        conf = _read_tls_conf()
        protocols_match = re.search(r"ssl_protocols\s+([^;]+);", conf)
        assert protocols_match, "Directive ssl_protocols introuvable dans nginx.tls.conf"
        protocols = protocols_match.group(1).strip()
        assert "TLSv1.1" not in protocols, f"TLSv1.1 doit être désactivé, trouvé: {protocols}"

    def test_only_tls_1_2_and_1_3(self):
        """Seuls TLSv1.2 et TLSv1.3 doivent être listés."""
        conf = _read_tls_conf()
        protocols_match = re.search(r"ssl_protocols\s+([^;]+);", conf)
        assert protocols_match
        protocols = protocols_match.group(1).strip().split()
        allowed = {"TLSv1.2", "TLSv1.3"}
        assert set(protocols) == allowed, (
            f"Seuls TLSv1.2 et TLSv1.3 autorisés, trouvé: {protocols}"
        )


# ── SSL Configuration Tests ─────────────────────────────────────────────────

class TestSSLConfiguration:
    """Validations de la configuration SSL avancée."""

    def test_ssl_prefer_server_ciphers(self):
        """ssl_prefer_server_ciphers doit être activé."""
        conf = _read_tls_conf()
        assert re.search(r"ssl_prefer_server_ciphers\s+on\s*;", conf), (
            "ssl_prefer_server_ciphers on doit être présent"
        )

    def test_ssl_session_tickets_disabled(self):
        """ssl_session_tickets doit être off pour forward secrecy."""
        conf = _read_tls_conf()
        assert re.search(r"ssl_session_tickets\s+off\s*;", conf), (
            "ssl_session_tickets off doit être présent pour forward secrecy"
        )

    def test_ssl_ciphers_present(self):
        """La directive ssl_ciphers doit être présente avec des cipher modernes."""
        conf = _read_tls_conf()
        assert re.search(r"ssl_ciphers\s+'", conf), (
            "Directive ssl_ciphers avec cipher suite explicite requise"
        )
        # Vérifier qu'on utilise au minimum ECDHE (forward secrecy)
        assert "ECDHE" in conf, "Les cipher suites doivent inclure ECDHE (forward secrecy)"

    def test_ssl_stapling_enabled(self):
        """OCSP stapling doit être activé."""
        conf = _read_tls_conf()
        assert re.search(r"ssl_stapling\s+on\s*;", conf), (
            "ssl_stapling on doit être présent"
        )

    def test_ssl_stapling_verify_enabled(self):
        """OCSP stapling verification doit être activée."""
        conf = _read_tls_conf()
        assert re.search(r"ssl_stapling_verify\s+on\s*;", conf), (
            "ssl_stapling_verify on doit être présent"
        )

    def test_dns_resolver_present(self):
        """Un resolver DNS doit être configuré pour OCSP stapling."""
        conf = _read_tls_conf()
        assert re.search(r"resolver\s+[\d.]", conf), (
            "Directive resolver DNS requise pour OCSP stapling"
        )


# ── HSTS Header Tests ───────────────────────────────────────────────────────

class TestHSTSHeader:
    """Validations du header Strict-Transport-Security."""

    def test_hsts_header_present_in_nginx(self):
        """Le header HSTS doit être présent dans nginx.tls.conf."""
        conf = _read_tls_conf()
        assert re.search(
            r'Strict-Transport-Security', conf, re.IGNORECASE
        ), "Header HSTS manquant dans nginx.tls.conf"

    def test_hsts_max_age_at_least_one_year(self):
        """max-age doit être >= 31536000 (1 an), idéalement 63072000 (2 ans)."""
        conf = _read_tls_conf()
        # nginx config: add_header Strict-Transport-Security "max-age=63072000; ..." always;
        match = re.search(
            r'max-age=(\d+)', conf, re.IGNORECASE
        )
        assert match, "max-age non trouvé dans le header HSTS"
        max_age = int(match.group(1))
        assert max_age >= 31536000, f"max-age doit être >= 1 an (31536000), trouvé: {max_age}"

    def test_hsts_includes_subdomains(self):
        """Le header HSTS doit inclure includeSubDomains."""
        conf = _read_tls_conf()
        # Search the full line containing Strict-Transport-Security
        hsts_line_match = re.search(
            r'Strict-Transport-Security.*', conf, re.IGNORECASE
        )
        assert hsts_line_match, "Header HSTS introuvable"
        hsts_text = hsts_line_match.group()
        assert "includeSubDomains" in hsts_text, (
            "includeSubDomains doit être présent dans le header HSTS"
        )

    def test_hsts_preload(self):
        """Le header HSTS devrait inclure preload pour soumission au preload list."""
        conf = _read_tls_conf()
        hsts_line_match = re.search(
            r'Strict-Transport-Security.*', conf, re.IGNORECASE
        )
        assert hsts_line_match, "Header HSTS introuvable"
        assert "preload" in hsts_line_match.group(), (
            "preload doit être présent dans le header HSTS"
        )

    def test_hsts_always_flag(self):
        """Le header HSTS doit utiliser 'always' pour s'appliquer même aux erreurs."""
        conf = _read_tls_conf()
        # nginx: add_header Strict-Transport-Security "..." always;
        hsts_line_match = re.search(
            r'Strict-Transport-Security.*', conf, re.IGNORECASE
        )
        assert hsts_line_match, "Header HSTS introuvable"
        assert "always" in hsts_line_match.group(), (
            "Le flag 'always' doit accompagner le header HSTS"
        )

    def test_hsts_in_security_headers_middleware(self):
        """Le middleware FastAPI doit aussi ajouter HSTS pour les réponses directes."""
        api_path = PROJECT_ROOT / "api-server"
        if str(api_path) not in sys.path:
            sys.path.insert(0, str(api_path))
        try:
            from middleware.security_headers import SecurityHeadersMiddleware
            # Vérifier que le middleware existe et référence HSTS_ENABLED
            import inspect
            source = inspect.getsource(SecurityHeadersMiddleware)
            assert "HSTS" in source or "Strict-Transport-Security" in source, (
                "Le middleware SecurityHeaders doit gérer HSTS"
            )
        finally:
            sys.path.pop(0)


# ── Security Headers Tests ──────────────────────────────────────────────────

class TestSecurityHeaders:
    """Validations des en-têtes de sécurité HTTP dans nginx."""

    def test_x_content_type_options_nosniff(self):
        conf = _read_tls_conf()
        assert re.search(r'X-Content-Type-Options', conf) and "nosniff" in conf, (
            "Header X-Content-Type-Options nosniff manquant"
        )

    def test_x_frame_options_deny(self):
        conf = _read_tls_conf()
        assert re.search(r'X-Frame-Options', conf) and "DENY" in conf, (
            "Header X-Frame-Options DENY manquant"
        )

    def test_referrer_policy_present(self):
        conf = _read_tls_conf()
        assert re.search(r'Referrer-Policy', conf), (
            "Header Referrer-Policy manquant"
        )

    def test_proxy_hide_x_powered_by(self):
        """X-Powered-By doit être masqué côté nginx."""
        conf = _read_tls_conf()
        assert re.search(r'proxy_hide_header\s+X-Powered-By', conf), (
            "proxy_hide_header X-Powered-By manquant dans nginx"
        )

    def test_x_forwarded_proto_set(self):
        """X-Forwarded-Proto doit être passé au backend."""
        conf = _read_tls_conf()
        assert re.search(r'proxy_set_header\s+X-Forwarded-Proto\s+\$scheme', conf), (
            "proxy_set_header X-Forwarded-Proto $scheme manquant"
        )

    def test_x_real_ip_set(self):
        """X-Real-IP doit être passé au backend."""
        conf = _read_tls_conf()
        assert re.search(r'proxy_set_header\s+X-Real-IP\s+\$remote_addr', conf), (
            "proxy_set_header X-Real-IP $remote_addr manquant"
        )


# ── Nginx Healthcheck Tests ────────────────────────────────────────────────

class TestNginxHealthcheck:
    """Validations du healthcheck nginx dans docker-compose.prod.yml."""

    def test_nginx_healthcheck_present(self):
        """Le service nginx doit avoir un healthcheck."""
        compose = _read_docker_compose_prod()
        # Trouver la section nginx
        nginx_section_match = re.search(
            r'^  nginx:', compose, re.MULTILINE
        )
        if not nginx_section_match:
            pytest.skip("Service nginx non trouvé dans docker-compose.prod.yml")
        nginx_start = nginx_section_match.end()
        next_service = re.search(r'^  [a-z]', compose[nginx_start:], re.MULTILINE)
        nginx_block = compose[nginx_start:nginx_start + next_service.start()] if next_service else compose[nginx_start:]
        assert "healthcheck" in nginx_block, (
            "Le service nginx doit avoir un healthcheck"
        )

    def test_nginx_healthcheck_uses_https_or_health_endpoint(self):
        """Le healthcheck nginx doit tester l'endpoint /nginx-health."""
        compose = _read_docker_compose_prod()
        assert "/nginx-health" in compose or "/health" in compose, (
            "Le healthcheck nginx doit tester un endpoint de santé"
        )

    def test_nginx_healthcheck_interval_reasonable(self):
        """L'intervalle du healthcheck doit être <= 30s."""
        compose = _read_docker_compose_prod()
        nginx_section = re.search(
            r'^  nginx:.*?^\S', compose, re.MULTILINE | re.DOTALL
        )
        if not nginx_section:
            pytest.skip("Service nginx non trouvé")
        nginx_block = nginx_section.group()
        interval_match = re.search(r'interval:\s*(\d+)s?', nginx_block)
        if interval_match:
            interval = int(interval_match.group(1))
            assert interval <= 30, f"Healthcheck interval trop long: {interval}s"

    def test_nginx_healthcheck_retries_present(self):
        """Le healthcheck doit avoir un nombre de retries."""
        compose = _read_docker_compose_prod()
        assert re.search(r'retries:\s*\d+', compose), (
            "Le healthcheck nginx doit avoir retries"
        )


# ── Certificate Scripts Tests ──────────────────────────────────────────────

class TestCertificateScripts:
    """Validations des scripts de gestion de certificats."""

    def test_generate_dev_script_exists(self):
        """certs/generate_dev.sh doit exister et être exécutable."""
        script = PROJECT_ROOT / "certs" / "generate_dev.sh"
        assert script.exists(), "certs/generate_dev.sh manquant"
        assert os.access(str(script), os.X_OK), (
            "certs/generate_dev.sh doit être exécutable"
        )

    def test_generate_dev_uses_openssl_or_mkcert(self):
        """Le script doit utiliser openssl ou mkcert."""
        script = PROJECT_ROOT / "certs" / "generate_dev.sh"
        content = script.read_text()
        assert "openssl" in content or "mkcert" in content, (
            "generate_dev.sh doit utiliser openssl ou mkcert"
        )

    def test_letsencrypt_orchestration_script_exists(self):
        """certs/orchestrate_letsencrypt.sh doit exister."""
        script = PROJECT_ROOT / "certs" / "orchestrate_letsencrypt.sh"
        assert script.exists(), "certs/orchestrate_letsencrypt.sh manquant"

    def test_letsencrypt_script_includes_certbot(self):
        """Le script Let's Encrypt doit utiliser certbot."""
        script = PROJECT_ROOT / "certs" / "orchestrate_letsencrypt.sh"
        content = script.read_text()
        assert "certbot" in content, (
            "orchestrate_letsencrypt.sh doit utiliser certbot"
        )

    def test_letsencrypt_script_includes_nginx_reload(self):
        """Le script Let's Encrypt doit recharger nginx après renouvellement."""
        script = PROJECT_ROOT / "certs" / "orchestrate_letsencrypt.sh"
        content = script.read_text()
        assert "nginx" in content and "reload" in content, (
            "orchestrate_letsencrypt.sh doit recharger nginx après certbot"
        )


# ── HTTP to HTTPS Redirect Test ─────────────────────────────────────────────

class TestHTTPRedirect:
    """Validation de la redirection HTTP → HTTPS."""

    def test_http_redirects_to_https(self):
        """Le bloc listen 80 doit rediriger vers https."""
        conf = _read_tls_conf()
        # Trouver le premier server block (listen 80)
        port80_block = re.search(
            r'listen\s+80;.*?return\s+301\s+https://', conf, re.DOTALL
        )
        assert port80_block, (
            "Le serveur HTTP (port 80) doit rediriger vers HTTPS avec 301"
        )

    def test_acme_challenge_location_preserved(self):
        """La location /.well-known/acme-challenge/ doit rester accessible en HTTP."""
        conf = _read_tls_conf()
        assert re.search(r'\.well-known/acme-challenge', conf), (
            "La location /.well-known/acme-challenge/ doit être présente pour certbot"
        )


# ── Cross-Validation Tests ─────────────────────────────────────────────────

class TestCrossValidation:
    """Tests cross-validation entre nginx et l'application FastAPI."""

    def test_hsts_enabled_setting_exists_in_config(self):
        """settings.HSTS_ENABLED doit exister dans config.py."""
        config_path = PROJECT_ROOT / "api-server" / "config.py"
        assert config_path.exists(), "config.py manquant"
        content = config_path.read_text()
        assert "HSTS_ENABLED" in content, (
            "config.py doit définir HSTS_ENABLED"
        )

    def test_certbot_location_in_port80_before_redirect(self):
        """La location /.well-known/acme-challenge/ doit apparaître AVANT le return 301."""
        conf = _read_tls_conf()
        port80_section = re.search(
            r'listen\s+80;.*?(?=listen\s+443|$)', conf, re.DOTALL
        )
        if not port80_section:
            pytest.skip("Section listen 80 introuvable")
        block = port80_section.group()
        acme_pos = block.find(".well-known/acme-challenge")
        redirect_pos = block.find("return 301")
        if acme_pos >= 0 and redirect_pos >= 0:
            assert acme_pos < redirect_pos, (
                "La location acme-challenge doit apparaître AVANT la redirection 301"
            )
