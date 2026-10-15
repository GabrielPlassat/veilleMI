"""Client minimal pour Albert API (DINUM) — compatible OpenAI.

Documentation : https://guides.ia.numerique.gouv.fr/albert-api
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import requests


class AlbertErreur(RuntimeError):
    pass


class Albert:
    def __init__(self, cle: str, base_url: str = "https://albert.api.etalab.gouv.fr/v1",
                 modele: str = "openweight-medium", timeout: int = 180):
        if not cle:
            raise AlbertErreur("Clé Albert API manquante.")
        self.base = base_url.rstrip("/")
        self.modele = modele
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {cle}"

    # ------------------------------------------------------------------ bas niveau
    def _requete(self, methode: str, chemin: str, essais: int = 4, **kw) -> requests.Response:
        url = f"{self.base}/{chemin.lstrip('/')}"
        for i in range(essais):
            try:
                r = self.session.request(methode, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                if i == essais - 1:
                    raise AlbertErreur(f"Albert injoignable : {e}") from e
                time.sleep(3 * (i + 1))
                continue
            if r.status_code in (429, 500, 502, 503, 504) and i < essais - 1:
                attente = float(r.headers.get("Retry-After", 5 * (i + 1)))
                time.sleep(min(attente, 60))
                continue
            return r
        raise AlbertErreur("Albert : trop d'essais")

    def verifier(self) -> dict:
        """Teste la clé et renvoie les infos du compte (quotas inclus)."""
        r = self._requete("GET", "/me/info")
        if r.status_code == 401:
            raise AlbertErreur("Clé Albert refusée (401). Vérifiez la clé.")
        r.raise_for_status()
        return r.json()

    def modeles(self) -> list[str]:
        r = self._requete("GET", "/models")
        r.raise_for_status()
        return [m["id"] for m in r.json().get("data", [])]

    # ------------------------------------------------------------------ génération
    def chat(self, systeme: str, utilisateur: str, json_mode: bool = False,
             max_tokens: int = 2500, temperature: float = 0.1) -> str:
        corps = {
            "model": self.modele,
            "messages": [{"role": "system", "content": systeme},
                         {"role": "user", "content": utilisateur}],
            "temperature": temperature,
            "max_completion_tokens": max_tokens,
        }
        if json_mode:
            corps["response_format"] = {"type": "json_object"}
        r = self._requete("POST", "/chat/completions", json=corps)
        if r.status_code == 400 and json_mode:  # modèle sans mode JSON : on retente sans
            corps.pop("response_format")
            r = self._requete("POST", "/chat/completions", json=corps)
        if r.status_code >= 400:
            raise AlbertErreur(f"Albert {r.status_code} : {r.text[:300]}")
        return r.json()["choices"][0]["message"]["content"] or ""

    def chat_json(self, systeme: str, utilisateur: str, **kw) -> dict:
        texte = self.chat(systeme, utilisateur, json_mode=True, **kw)
        return extraire_json(texte)

    # ------------------------------------------------------------------ collections (RAG)
    def collection(self, nom: str, description: str = "") -> int:
        """Retourne l'id de la collection privée `nom`, en la créant si besoin."""
        r = self._requete("GET", "/collections", params={"name": nom, "limit": 100})
        r.raise_for_status()
        for c in r.json().get("data", []):
            if c.get("name") == nom:
                return int(c["id"])
        r = self._requete("POST", "/collections",
                          json={"name": nom, "description": description, "visibility": "private"})
        if r.status_code >= 400:
            raise AlbertErreur(f"Création de collection impossible : {r.text[:300]}")
        return int(r.json()["id"])

    def indexer(self, fichier: str | Path, collection_id: int, metadonnees: dict) -> int | None:
        """Envoie un document dans une collection Albert. Renvoie l'id du document."""
        meta = {k: str(v)[:250] for k, v in metadonnees.items() if v not in (None, "")}
        meta = dict(list(meta.items())[:10])  # 10 clés max côté Albert
        with open(fichier, "rb") as f:
            r = self._requete(
                "POST", "/documents",
                files={"file": (Path(fichier).name, f)},
                data={"collection_id": str(collection_id), "metadata": json.dumps(meta, ensure_ascii=False)},
            )
        if r.status_code >= 400:
            raise AlbertErreur(f"Indexation refusée ({r.status_code}) : {r.text[:200]}")
        return r.json().get("id")


def extraire_json(texte: str) -> dict:
    """Récupère le premier objet JSON d'une réponse (tolère ```json ... ```)."""
    texte = texte.strip()
    texte = re.sub(r"^```(?:json)?|```$", "", texte, flags=re.M).strip()
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass
    debut = texte.find("{")
    if debut < 0:
        raise AlbertErreur(f"Réponse sans JSON : {texte[:200]}")
    profondeur = 0
    for i, c in enumerate(texte[debut:], start=debut):
        if c == "{":
            profondeur += 1
        elif c == "}":
            profondeur -= 1
            if profondeur == 0:
                return json.loads(texte[debut:i + 1])
    raise AlbertErreur(f"JSON incomplet : {texte[:200]}")
