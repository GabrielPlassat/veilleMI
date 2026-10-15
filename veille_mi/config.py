"""Lecture de config.yaml et petites fonctions utilitaires sur les acteurs."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

RACINE_PROJET = Path(__file__).resolve().parent.parent


def charger_config(chemin: str | Path | None = None) -> dict:
    chemin = Path(chemin) if chemin else RACINE_PROJET / "config.yaml"
    with open(chemin, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # chemins relatifs -> relatifs au projet
    ref = Path(cfg["referentiel"]["fichier"])
    if not ref.is_absolute():
        cfg["referentiel"]["fichier"] = str(RACINE_PROJET / ref)
    return cfg


def domaine(url: str) -> str:
    try:
        d = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return d[4:] if d.startswith("www.") else d


def acteur_pour_url(url: str, acteurs: list[dict]) -> dict | None:
    """Retrouve l'acteur dont un domaine correspond à l'URL (le plus spécifique gagne)."""
    d = domaine(url)
    meilleur, longueur = None, 0
    for a in acteurs:
        for dom in a.get("domaines", []):
            if (d == dom or d.endswith("." + dom)) and len(dom) > longueur:
                meilleur, longueur = a, len(dom)
    return meilleur


def acteur_pour_nom(nom: str | None, acteurs: list[dict]) -> dict | None:
    """Rapproche un nom d'organisme renvoyé par Albert d'un acteur connu."""
    if not nom:
        return None
    n = nom.lower()
    meilleur, longueur = None, 0
    for a in acteurs:
        cands = [a["nom"].lower(), a["code"].lower()] + [x.lower() for x in a.get("alias") or []]
        for c in cands:
            if len(c) >= 3 and c in n and len(c) > longueur:  # le nom le plus précis gagne
                meilleur, longueur = a, len(c)
    return meilleur


def domaines_connus(acteurs: list[dict]) -> set[str]:
    return {d for a in acteurs for d in a.get("domaines", [])}
