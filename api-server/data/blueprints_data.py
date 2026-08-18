"""
data/blueprints_data.py — Données des Blueprints Métier
========================================================
Contient les définitions de tous les blueprints disponibles.
À charger en base de données lors de l'initialisation.
"""

BLUEPRINTS_DATA = [
    {
        "id": "automotive",
        "name": "Garage Automobile / Pièces de Rechange",
        "icon": "🚗",
        "description": "Gestion de stock de pièces, identification OEM par VIN, prise de RDV pour entretien.",
        "modules_enabled": ["appointments", "stock", "oem_parts"],
        "default_ai_prompt": "Vous êtes un assistant expert en pièces automobiles. Vous aidez les clients à trouver la bonne pièce en fonction de leur véhicule (VIN) ou de la référence OEM. Vous pouvez aussi prendre des rendez-vous pour l'entretien.",
        "default_business_type": "appointments",
        "default_service_category": "automotive",
        "ui_visibility": {
            "show_oem_apis": True,
            "show_stock_sources": True,
            "show_appointment_settings": True,
        },
        "quotas": {},
        "initial_data": {
            "services": [
                {"name": "Diagnostic Moteur", "duration_min": 60, "price": 50},
                {"name": "Vidange Huile", "duration_min": 30, "price": 80},
                {"name": "Changement Plaquettes", "duration_min": 45, "price": 120},
            ]
        },
    },
    {
        "id": "beauty_salon",
        "name": "Salon de Beauté / Coiffure",
        "icon": "💇‍♀️",
        "description": "Prise de rendez-vous pour services de coiffure, esthétique, manucure.",
        "modules_enabled": ["appointments"],
        "default_ai_prompt": "Vous êtes un assistant de salon de beauté. Vous aidez les clients à prendre rendez-vous pour nos services de coiffure, manucure, et soins esthétiques. Vous pouvez aussi répondre aux questions sur nos tarifs et disponibilités.",
        "default_business_type": "appointments",
        "default_service_category": "beauty",
        "ui_visibility": {
            "show_oem_apis": False,
            "show_stock_sources": False,
            "show_appointment_settings": True,
        },
        "quotas": {},
        "initial_data": {
            "services": [
                {"name": "Coupe Femme", "duration_min": 45, "price": 35},
                {"name": "Coupe Homme", "duration_min": 20, "price": 20},
                {"name": "Manucure", "duration_min": 30, "price": 20},
                {"name": "Soin du Visage", "duration_min": 60, "price": 50},
            ]
        },
    },
    {
        "id": "guesthouse",
        "name": "Maison d'Hôte",
        "icon": "🏡",
        "description": "Gestion des réservations de chambres, informations sur les services et activités.",
        "modules_enabled": ["appointments"],
        "default_ai_prompt": "Bienvenue dans notre maison d'hôte. Je peux vous aider à vérifier la disponibilité des chambres, à réserver votre séjour et à vous informer sur nos services et activités.",
        "default_business_type": "appointments",
        "default_service_category": "hospitality",
        "ui_visibility": {
            "show_oem_apis": False,
            "show_stock_sources": False,
            "show_appointment_settings": True,
        },
        "quotas": {"max_rooms": 5},
        "initial_data": {
            "services": [
                {"name": "Chambre Double", "duration_min": 1440, "price": 120},
                {"name": "Suite Familiale", "duration_min": 1440, "price": 200},
                {"name": "Chambre Simple", "duration_min": 1440, "price": 80},
            ]
        },
    },
    {
        "id": "restaurant",
        "name": "Restaurant",
        "icon": "🍽️",
        "description": "Prise de commandes, gestion des réservations de tables, affichage du menu.",
        "modules_enabled": ["appointments", "stock"],
        "default_ai_prompt": "Bienvenue dans notre restaurant. Je peux prendre votre commande, gérer les réservations de tables et vous présenter notre menu du jour.",
        "default_business_type": "appointments",
        "default_service_category": "food_service",
        "ui_visibility": {
            "show_oem_apis": False,
            "show_stock_sources": True,
            "show_appointment_settings": True,
        },
        "quotas": {"max_tables": 15},
        "initial_data": {
            "services": [
                {"name": "Réservation Table (2 pers)", "duration_min": 90, "price": 0},
                {"name": "Réservation Table (4 pers)", "duration_min": 120, "price": 0},
            ]
        },
    },
    {
        "id": "general_shop",
        "name": "Boutique Générale",
        "icon": "🛍️",
        "description": "Vente de produits divers, gestion de stock, suivi de commandes.",
        "modules_enabled": ["stock"],
        "default_ai_prompt": "Bienvenue dans notre boutique. Je peux vous aider à trouver des produits, vérifier leur disponibilité et répondre à vos questions.",
        "default_business_type": "ecommerce",
        "default_service_category": None,
        "ui_visibility": {
            "show_oem_apis": False,
            "show_stock_sources": True,
            "show_appointment_settings": False,
        },
        "quotas": {},
        "initial_data": {},
    },
]


async def seed_blueprints(db):
    """
    Charge les blueprints en base de données.
    À appeler lors de l'initialisation de l'application.
    """
    from sqlalchemy import select

    from models.blueprints import Blueprint

    for bp_data in BLUEPRINTS_DATA:
        # Vérifier si le blueprint existe déjà
        result = await db.execute(
            select(Blueprint).where(Blueprint.id == bp_data["id"])
        )
        if result.scalar_one_or_none():
            continue  # Blueprint déjà présent

        # Créer le blueprint
        bp = Blueprint(**bp_data)
        db.add(bp)

    await db.commit()
