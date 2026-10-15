"""Recherche web (Albert API n'a pas de recherche web : moteur externe)."""
from __future__ import annotations

import time

import requests

from .config import domaine


def _duckduckgo(requete: str, n: int, region: str) -> list[dict]:
    try:
        from ddgs import DDGS
    except ImportError:  # ancien nom du paquet
        from duckduckgo_search import DDGS
    res = DDGS().text(requete, region=region, max_results=n) or []
    return [{"url": r.get("href") or r.get("url"), "titre": r.get("title", ""),
             "extrait": r.get("body", "")} for r in res]


def _brave(requete: str, n: int, region: str, cle: str) -> list[dict]:
    pays = {"fr-fr": "FR", "wt-wt": "ALL"}.get(region, "ALL")
    r = requests.get("https://api.search.brave.com/res/v1/web/search",
                     params={"q": requete, "count": min(n, 20), "country": pays},
                     headers={"X-Subscription-Token": cle, "Accept": "application/json"},
                     timeout=30)
    r.raise_for_status()
    return [{"url": x["url"], "titre": x.get("title", ""), "extrait": x.get("description", "")}
            for x in r.json().get("web", {}).get("results", [])]


class MoteurRecherche:
    def __init__(self, cfg_recherche: dict, cle_brave: str | None = None, journal=print):
        self.moteur = cfg_recherche.get("moteur", "duckduckgo")
        self.n = int(cfg_recherche.get("resultats_par_requete", 8))
        self.pause = float(cfg_recherche.get("pause_entre_requetes_s", 2))
        self.cle_brave = cle_brave
        self.journal = journal
        if self.moteur == "brave" and not cle_brave:
            self.journal("⚠️ Pas de clé Brave : bascule sur DuckDuckGo.")
            self.moteur = "duckduckgo"

    def chercher(self, requete: str, region: str = "fr-fr") -> list[dict]:
        for essai in range(3):
            try:
                if self.moteur == "brave":
                    res = _brave(requete, self.n, region, self.cle_brave)
                else:
                    res = _duckduckgo(requete, self.n, region)
                time.sleep(self.pause)
                return [r for r in res if r.get("url")]
            except Exception as e:  # moteurs gratuits : limitations fréquentes
                attente = self.pause * (4 ** (essai + 1))
                self.journal(f"   recherche ralentie ({type(e).__name__}), nouvel essai dans {attente:.0f}s")
                time.sleep(attente)
        return []


def filtrer_domaines(resultats: list[dict], autorises: set[str]) -> list[dict]:
    garde = []
    for r in resultats:
        d = domaine(r["url"])
        if any(d == a or d.endswith("." + a) for a in autorises):
            garde.append(r)
    return garde
