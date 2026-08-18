"""
models/blueprints.py — Modèles pour les Blueprints Métier
===========================================================
Définit les structures pour les configurations spécialisées par métier.
"""

from datetime import UTC, datetime, timezone
from enum import Enum, StrEnum
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Integer, String

# AUDIT FIX: Importer Base depuis models.database au lieu d'en créer une nouvelle.
# Une declarative_base() séparée causait des problèmes avec les migrations Alembic
# et l'overlay d'isolation tenant. Une seule Base doit être partagée dans toute l'appli.
from models.database import Base


class BusinessTypeEnum(StrEnum):
    """Types d'activités supportées"""
    AUTOMOTIVE = "automotive"
    BEAUTY_SALON = "beauty_salon"
    GUESTHOUSE = "guesthouse"
    RESTAURANT = "restaurant"
    GENERAL_SHOP = "general_shop"


class Blueprint(Base):
    """
    Représente un Blueprint Métier (configuration pré-définie pour un type d'activité).
    Cette table est généralement remplie au démarrage et ne change pas souvent.
    """
    __tablename__ = "blueprints"

    id = Column(String(50), primary_key=True)  # ex: "automotive", "beauty_salon"
    name = Column(String(255), nullable=False)  # ex: "Garage Automobile"
    icon = Column(String(10), nullable=True)  # emoji ou chemin court
    description = Column(String(1000), nullable=True)
    
    # Modules à activer pour ce blueprint
    modules_enabled = Column(JSON, default=list)  # ex: ["appointments", "stock", "oem_parts"]
    
    # Configuration IA par défaut
    default_ai_prompt = Column(String(2000), nullable=True)
    default_business_type = Column(String(50), nullable=True)  # ex: "appointments", "ecommerce"
    default_service_category = Column(String(50), nullable=True)  # ex: "automotive", "beauty"
    
    # Contrôle de visibilité UI
    ui_visibility = Column(JSON, default=dict)  # ex: { "show_oem_apis": true, "show_stock_sources": false }
    
    # Quotas spécifiques au métier
    quotas = Column(JSON, default=dict)  # ex: { "max_rooms": 5, "max_tables": 15 }
    
    # Données initiales à créer (services, produits par défaut)
    initial_data = Column(JSON, default=dict)  # ex: { "services": [...], "products": [...] }
    
    # Métadonnées
    created_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<Blueprint {self.id}: {self.name}>"


class StoreBlueprint(Base):
    """
    Lie un Store à un Blueprint Métier.
    Permet de tracker quel blueprint est utilisé par chaque boutique.
    """
    __tablename__ = "store_blueprints"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, nullable=False, unique=True)  # FK vers Store
    blueprint_id = Column(String(50), nullable=False)  # FK vers Blueprint
    
    # Configuration personnalisée du blueprint pour ce store
    # (permet de surcharger les valeurs par défaut)
    custom_config = Column(JSON, default=dict)
    
    # Métadonnées
    selected_at = Column(DateTime, default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    def __repr__(self):
        return f"<StoreBlueprint store_id={self.store_id} blueprint_id={self.blueprint_id}>"


# ─── Pydantic Schemas pour les APIs ────────────────────────────────────────

from pydantic import BaseModel


class BlueprintRead(BaseModel):
    """Schéma pour lire un Blueprint"""
    id: str
    name: str
    icon: str | None
    description: str | None
    modules_enabled: list[str]
    default_ai_prompt: str | None
    default_business_type: str | None
    default_service_category: str | None
    ui_visibility: dict[str, Any]
    quotas: dict[str, Any]
    initial_data: dict[str, Any]

    class Config:
        from_attributes = True


class StoreBlueprintSelect(BaseModel):
    """Schéma pour sélectionner un Blueprint pour un Store"""
    blueprint_id: str
    custom_config: dict[str, Any] | None = {}

    class Config:
        from_attributes = True


class StoreBlueprintRead(BaseModel):
    """Schéma pour lire la sélection de Blueprint d'un Store"""
    id: int
    store_id: int
    blueprint_id: str
    custom_config: dict[str, Any]
    selected_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
