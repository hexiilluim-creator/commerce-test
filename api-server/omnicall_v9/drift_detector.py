"""omnicall_v9/drift_detector.py — Fast-Track Plus : Détection de dérive.

Compare les sorties V8 et V9 en Shadow Mode pour identifier les divergences
de comportement avant le rollout actif.
"""
from __future__ import annotations

import difflib
import logging

logger = logging.getLogger("omnicall_v9.drift_detector")

class DriftDetector:
    def __init__(self, similarity_threshold: float = 0.85):
        self.similarity_threshold = similarity_threshold

    def analyze_divergence(
        self, 
        v8_output: str | dict[str, object], 
        v9_output: str | dict[str, object]
    ) -> dict[str, object]:
        """Calcule la similarité entre les deux versions."""
        s1 = str(v8_output)
        s2 = str(v9_output)
        
        ratio = difflib.SequenceMatcher(None, s1, s2).ratio()
        is_divergent = ratio < self.similarity_threshold
        
        if is_divergent:
            logger.warning(
                "omnicall_v9.drift_detected", 
                extra={"similarity": ratio, "v8": s1[:100], "v9": s2[:100]}
            )
            
        return {
            "similarity_ratio": round(ratio, 3),
            "is_divergent": is_divergent,
            "threshold": self.similarity_threshold
        }

# Instance globale
v9_drift = DriftDetector()
