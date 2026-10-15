"""Veille des modes d'intervention (MI) de la transition écologique.

Cœur commun à l'application Streamlit (app.py) et au notebook Colab.
"""
from .config import charger_config
from .pipeline import Veille

__all__ = ["charger_config", "Veille"]
