"""security_overlay — Overlay de sécurité et facturation."""
from fastapi import FastAPI

from .guard import get_guard


def install_security_overlay(app: FastAPI):
    """
    Installe l'overlay de sécurité sur l'application FastAPI.
    Cette fonction est appelée par main.py pour activer les protections IA,
    les quotas et le kill-switch.
    """
    guard = get_guard()
    # On pourrait ici enregistrer des middlewares ou des routes spécifiques à l'overlay
    # Pour l'instant, l'initialisation du singleton guard suffit car il est utilisé 
    # via des dépendances ou des appels directs dans les services.
    return guard

__all__ = ["install_security_overlay", "get_guard"]
