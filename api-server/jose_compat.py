"""
jose_compat.py — SUPPRIMÉ (Correctif P2 — Audit CTO)

Ce module était un shim de compatibilité python-jose -> PyJWT.
Il a été éliminé. Tous les sites d'import ont été migrés vers PyJWT direct :

    import jwt
    from jwt.exceptions import PyJWTError as JWTError

Ne pas réintroduire ce module. Voir PyJWT docs : https://pyjwt.readthedocs.io/
"""
# R2-FIX: remplacer le "raise ImportError nu" par __getattr__ 
# (évite le crash des outils statiques qui chargent tous les modules au scan)


def __getattr__(name: str):
    raise ImportError(
        f"jose_compat a été supprimé — impossible d'importer '{name}'. "
        "Utilisez : import jwt / from jwt.exceptions import PyJWTError as JWTError"
    )
