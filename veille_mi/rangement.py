"""Nommage des fichiers, rangement en dossiers et catalogue (CSV + Excel)."""
from __future__ import annotations

import re
import shutil
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

COLONNES_DOCS = [
    "doc_id", "date_veille", "titre", "type_document", "date_document", "organisme_auteur",
    "code_auteur", "evaluateur", "zone", "mi_principal", "dispositif", "id_referentiel",
    "famille", "nouveau_mi", "criteres", "resultats_chiffres", "limites_effet_aubaine",
    "recommandations", "robustesse", "resume", "fichier", "url_document", "url_page",
    "requete", "origine", "pages", "sha256", "albert_doc_id",
]
COLONNES_MI = [
    "doc_id", "rang", "nom", "dispositif", "id_referentiel", "nouveau", "famille",
    "acteur_porteur", "probleme_vise", "moyens", "gouvernance", "zone", "type_document",
    "titre_document", "fichier",
]
COLONNES_ECARTES = ["date_veille", "url", "raison", "requete"]

TYPES_COURTS = {"evaluation": "EVAL", "rapport_dispositif": "RAPPORT", "texte_cadre": "CADRE",
                "etude": "ETUDE"}


def slug(texte: str | None, longueur: int = 60) -> str:
    texte = unicodedata.normalize("NFKD", str(texte or "")).encode("ascii", "ignore").decode()
    texte = re.sub(r"[^A-Za-z0-9]+", "-", texte).strip("-").lower()
    return texte[:longueur].rstrip("-") or "sans-titre"


def annee(date: str | None) -> str:
    m = re.search(r"(19|20)\d{2}", str(date or ""))
    return m.group(0) if m else "ND"


class Catalogue:
    """Dossier de veille : rapports rangés + fichiers CSV de suivi."""

    def __init__(self, racine: str | Path):
        self.racine = Path(racine)
        self.rapports = self.racine / "rapports"
        self.rapports.mkdir(parents=True, exist_ok=True)
        self.f_docs = self.racine / "catalogue_documents.csv"
        self.f_mi = self.racine / "catalogue_modes_intervention.csv"
        self.f_ecartes = self.racine / "urls_ecartees.csv"
        self.docs = self._lire(self.f_docs, COLONNES_DOCS)
        self.mi = self._lire(self.f_mi, COLONNES_MI)
        self.ecartes = self._lire(self.f_ecartes, COLONNES_ECARTES)
        self._urls = set(self.docs["url_document"]) | set(self.docs["url_page"]) | set(self.ecartes["url"])
        self._hash = set(self.docs["sha256"])

    @staticmethod
    def _lire(f: Path, colonnes: list[str]) -> pd.DataFrame:
        if f.exists():
            df = pd.read_csv(f, dtype=str, keep_default_na=False)
            for c in colonnes:
                if c not in df:
                    df[c] = ""
            return df[colonnes]
        return pd.DataFrame(columns=colonnes)

    # -------------------------------------------------------------- dédoublonnage
    def deja_vu(self, url: str) -> bool:
        return url in self._urls

    def empreinte_connue(self, h: str) -> bool:
        return h in self._hash

    def marquer_vu(self, url: str):
        self._urls.add(url)

    # -------------------------------------------------------------- rangement
    def chemin(self, *, famille: str | None, mi: str | None, nouveau: bool, date: str | None,
               code_auteur: str, type_doc: str | None, titre: str | None, ext: str) -> Path:
        if not mi:
            dossier = self.rapports / "_A_classer"
        elif nouveau:
            dossier = self.rapports / "_Nouveaux_MI" / slug(mi, 50)
        else:
            dossier = self.rapports / slug(famille, 40) / slug(mi, 50)
        dossier.mkdir(parents=True, exist_ok=True)
        base = f"{annee(date)}_{code_auteur or 'AUTRE'}_{TYPES_COURTS.get(type_doc or '', 'DOC')}_{slug(titre, 70)}"
        chemin, i = dossier / f"{base}.{ext}", 2
        while chemin.exists():
            chemin, i = dossier / f"{base}_{i}.{ext}", i + 1
        return chemin

    def nouvel_id(self) -> str:
        return f"D{len(self.docs) + 1:05d}"

    def ajouter(self, ligne_doc: dict, lignes_mi: list[dict]):
        ligne_doc = {c: ligne_doc.get(c, "") for c in COLONNES_DOCS}
        self.docs = pd.concat([self.docs, pd.DataFrame([ligne_doc])], ignore_index=True)
        if lignes_mi:
            df = pd.DataFrame([{c: l.get(c, "") for c in COLONNES_MI} for l in lignes_mi])
            self.mi = pd.concat([self.mi, df], ignore_index=True)
        for u in (ligne_doc["url_document"], ligne_doc["url_page"]):
            if u:
                self._urls.add(u)
        self._hash.add(ligne_doc["sha256"])
        self.sauver()

    def ecarter(self, url: str, raison: str, requete: str = ""):
        ligne = {"date_veille": datetime.now().strftime("%Y-%m-%d %H:%M"), "url": url,
                 "raison": raison[:300], "requete": requete}
        self.ecartes = pd.concat([self.ecartes, pd.DataFrame([ligne])], ignore_index=True)
        self._urls.add(url)
        self.ecartes.to_csv(self.f_ecartes, index=False)

    def sauver(self):
        self.docs.to_csv(self.f_docs, index=False)
        self.mi.to_csv(self.f_mi, index=False)

    # -------------------------------------------------------------- exports
    def nouveaux_mi(self) -> pd.DataFrame:
        if self.mi.empty:
            return pd.DataFrame(columns=["nom", "nb_documents", "dispositifs", "familles", "porteurs", "problemes"])
        nv = self.mi[self.mi["nouveau"].astype(str).str.lower().isin(["true", "1", "oui"])].copy()
        if nv.empty:
            return pd.DataFrame(columns=["nom", "nb_documents", "dispositifs", "familles", "porteurs", "problemes"])
        nv["cle"] = nv["nom"].map(lambda x: slug(x, 80))
        joint = lambda s: " ; ".join(sorted({x for x in s if x}))[:500]
        return (nv.groupby("cle").agg(nom=("nom", "first"), nb_documents=("doc_id", "nunique"),
                                      dispositifs=("dispositif", joint), familles=("famille", joint),
                                      porteurs=("acteur_porteur", joint), problemes=("probleme_vise", joint))
                .sort_values("nb_documents", ascending=False).reset_index(drop=True))

    def exporter_excel(self) -> Path:
        f = self.racine / "veille_modes_intervention.xlsx"
        with pd.ExcelWriter(f, engine="openpyxl") as w:
            self.docs.to_excel(w, sheet_name="Documents", index=False)
            self.mi.to_excel(w, sheet_name="MI détectés", index=False)
            self.nouveaux_mi().to_excel(w, sheet_name="Nouveaux MI candidats", index=False)
            evals = self.docs[self.docs["type_document"] == "evaluation"]
            evals.to_excel(w, sheet_name="Évaluations", index=False)
            self.ecartes.to_excel(w, sheet_name="URL écartées", index=False)
            for feuille in w.sheets.values():
                feuille.freeze_panes = "A2"
                for col in feuille.columns:
                    feuille.column_dimensions[col[0].column_letter].width = 22
        return f

    def zipper(self) -> Path:
        self.exporter_excel()
        cible = self.racine.parent / f"{self.racine.name}_{datetime.now():%Y%m%d_%H%M}.zip"
        with zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED) as z:
            for p in self.racine.rglob("*"):
                if p.is_file():
                    z.write(p, p.relative_to(self.racine.parent))
        return cible

    def deplacer(self, source: Path, cible: Path):
        cible.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(cible))
