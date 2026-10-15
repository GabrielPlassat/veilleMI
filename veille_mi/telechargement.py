"""Téléchargement des pages et rapports, extraction de texte."""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

ENTETES = {
    "User-Agent": "Mozilla/5.0 (veille-modes-intervention; usage recherche publique)",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

MOTS_RAPPORT = ("rapport", "synthèse", "synthese", "télécharger", "telecharger", "évaluation",
                "evaluation", "report", "download", "full text", "pdf", "étude", "etude", "avis")


@dataclass
class Ressource:
    url: str
    contenu: bytes
    type: str  # "pdf" ou "html"
    titre: str = ""

    @property
    def empreinte(self) -> str:
        return hashlib.sha256(self.contenu).hexdigest()


def telecharger(url: str, taille_max_mo: float = 60, timeout: int = 45) -> Ressource | None:
    try:
        r = requests.get(url, headers=ENTETES, timeout=timeout, stream=True, allow_redirects=True)
        r.raise_for_status()
        morceaux, total, limite = [], 0, int(taille_max_mo * 1024 * 1024)
        for m in r.iter_content(64 * 1024):
            total += len(m)
            if total > limite:
                return None
            morceaux.append(m)
        contenu = b"".join(morceaux)
    except requests.RequestException:
        return None
    ctype = r.headers.get("Content-Type", "").lower()
    if contenu[:5] == b"%PDF-" or "application/pdf" in ctype:
        return Ressource(r.url, contenu, "pdf")
    if "html" in ctype or contenu[:200].lstrip().lower().startswith((b"<!doctype", b"<html")):
        soupe = BeautifulSoup(contenu, "html.parser")
        titre = soupe.title.get_text(" ", strip=True) if soupe.title else ""
        return Ressource(r.url, contenu, "html", titre)
    return None


def liens_pdf(page: Ressource, maximum: int = 3) -> list[str]:
    """Liens vers des PDF sur une page web, les plus probables d'abord."""
    soupe = BeautifulSoup(page.contenu, "html.parser")
    candidats: dict[str, int] = {}
    for a in soupe.find_all("a", href=True):
        href = urljoin(page.url, a["href"])
        chemin = urlparse(href).path.lower()
        texte = (a.get_text(" ", strip=True) + " " + a.get("title", "")).lower()
        est_pdf = chemin.endswith(".pdf") or "/pdf" in chemin or "pdf" in texte
        if not est_pdf or href.startswith("mailto:"):
            continue
        score = 1 + sum(2 for mot in MOTS_RAPPORT if mot in texte)
        if "synth" in texte or "synth" in chemin:
            score += 1
        if any(x in chemin for x in ("cgu", "mentions", "cookies", "rgpd", "plan-du-site")):
            score -= 5
        candidats[href] = max(score, candidats.get(href, 0))
    tries = sorted(candidats.items(), key=lambda kv: -kv[1])
    return [u for u, s in tries if s > 0][:maximum]


def texte_pdf(contenu: bytes, max_caracteres: int = 18000, max_pages: int = 25) -> tuple[str, int]:
    """Texte des premières pages + nombre total de pages."""
    from pypdf import PdfReader
    try:
        lecteur = PdfReader(io.BytesIO(contenu))
        nb = len(lecteur.pages)
        morceaux, total = [], 0
        for page in lecteur.pages[:max_pages]:
            t = page.extract_text() or ""
            morceaux.append(t)
            total += len(t)
            if total >= max_caracteres:
                break
        texte = re.sub(r"[ \t]+", " ", "\n".join(morceaux))
        return texte[:max_caracteres], nb
    except Exception:
        return "", 0


def texte_html(contenu: bytes, max_caracteres: int = 18000) -> str:
    soupe = BeautifulSoup(contenu, "html.parser")
    for balise in soupe(["script", "style", "nav", "header", "footer", "form", "aside"]):
        balise.decompose()
    principal = soupe.find("main") or soupe.find("article") or soupe.body or soupe
    texte = principal.get_text("\n", strip=True)
    texte = re.sub(r"\n{2,}", "\n", texte)
    return texte[:max_caracteres]
