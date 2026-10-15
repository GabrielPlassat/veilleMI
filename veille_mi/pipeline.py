"""Orchestration de la veille : requêtes → recherche → téléchargement → Albert → rangement."""
from __future__ import annotations

import itertools
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .albert import Albert, AlbertErreur
from .analyse import generer_requetes, qualifier
from .config import acteur_pour_nom, acteur_pour_url, domaines_connus
from .rangement import Catalogue
from .recherche import MoteurRecherche, filtrer_domaines
from .referentiel import ModeIntervention, charger_referentiel
from .telechargement import Ressource, liens_pdf, telecharger, texte_html, texte_pdf


@dataclass
class Options:
    """Ce que l'utilisateur choisit avant d'appuyer sur le bouton."""
    modes: list[str] = field(default_factory=lambda: ["referentiel", "evaluateurs", "decouverte"])
    mi_ids: list[str] = field(default_factory=list)          # vide = tous
    acteurs_codes: list[str] = field(default_factory=list)   # vide = tous les évaluateurs
    zones: list[str] = field(default_factory=lambda: ["France"])
    requete_libre: str = ""
    consigne_decouverte: str = ""
    max_requetes: int = 30
    max_documents: int = 25
    indexer_albert: bool = False


@dataclass
class Requete:
    texte: str
    origine: str          # referentiel / evaluateurs / decouverte / libre
    region: str = "fr-fr"
    mi_id: str = ""


class Veille:
    def __init__(self, cfg: dict, cle_albert: str, dossier: str | Path | None = None,
                 cle_brave: str | None = None, journal=print, progression=None):
        self.cfg = cfg
        self.journal = journal
        self.progression = progression or (lambda x: None)
        a = cfg["albert"]
        self.albert = Albert(cle_albert, a["base_url"], a["modele"])
        self.moteur = MoteurRecherche(cfg["recherche"], cle_brave, journal)
        self.catalogue = Catalogue(dossier or cfg["telechargement"]["dossier"])
        self.acteurs = cfg["acteurs"]
        self.mis, self.urls_referentiel = charger_referentiel(cfg["referentiel"]["fichier"])
        self.referentiel_txt = "\n".join(m.pour_prompt() for m in self.mis)
        self.stats = {}

    # =============================================================== requêtes
    def _evaluateurs(self, options: Options) -> list[dict]:
        evals = [a for a in self.acteurs if a["role"] in ("evaluateur", "les_deux")
                 and a["zone"] in options.zones]
        if options.acteurs_codes:
            evals = [a for a in self.acteurs if a["code"] in options.acteurs_codes]
        return evals

    def construire_requetes(self, options: Options) -> list[Requete]:
        files: dict[str, list[Requete]] = {}
        evaluateurs = self._evaluateurs(options)

        if "referentiel" in options.modes:
            mis = [m for m in self.mis if not options.mi_ids or m.id in options.mi_ids]
            liste = []
            peu_evaluateurs = 0 < len(options.acteurs_codes) <= 3
            for m in mis:
                for terme in m.termes_recherche(3):
                    if "France" in options.zones:
                        if peu_evaluateurs:  # requêtes ciblées site par site
                            for a in evaluateurs:
                                liste.append(Requete(f"site:{a['domaines'][0]} {terme} évaluation",
                                                     "referentiel", "fr-fr", m.id))
                        else:
                            liste.append(Requete(f"{terme} évaluation rapport", "referentiel", "fr-fr", m.id))
                    if {"Europe", "Monde"} & set(options.zones) and terme == m.libelle_court:
                        liste.append(Requete(f"{terme} evaluation report OECD OR EU", "referentiel", "wt-wt", m.id))
            files["referentiel"] = liste

        if "evaluateurs" in options.modes:
            liste = []
            for theme_fr, theme_en in itertools.zip_longest(self.cfg["themes_fr"], self.cfg["themes_en"]):
                for a in evaluateurs:
                    if a["zone"] == "France" and theme_fr:
                        liste.append(Requete(f"site:{a['domaines'][0]} évaluation {theme_fr}", "evaluateurs", "fr-fr"))
                    elif a["zone"] != "France" and theme_en:
                        liste.append(Requete(f"site:{a['domaines'][0]} evaluation {theme_en}", "evaluateurs", "wt-wt"))
            files["evaluateurs"] = liste

        if "decouverte" in options.modes:
            liste = []
            for zone in options.zones:
                qs = generer_requetes(self.albert, perimetre=self.cfg["perimetre"], zone=zone,
                                      evaluateurs=[a["nom"] for a in evaluateurs if a["zone"] == zone],
                                      connus=[m.nom for m in self.mis], n=10,
                                      consigne=options.consigne_decouverte)
                self.journal(f"🧭 Albert propose {len(qs)} requêtes de découverte ({zone})")
                liste += [Requete(q, "decouverte", "fr-fr" if zone == "France" else "wt-wt") for q in qs]
            files["decouverte"] = liste

        if options.requete_libre.strip():
            files["libre"] = [Requete(q.strip(), "libre") for q in options.requete_libre.splitlines() if q.strip()]

        # tourniquet entre les modes pour que le plafond ne vide pas un seul mode
        resultat, vues = [], set()
        for groupe in itertools.zip_longest(*files.values()):
            for r in groupe:
                if r and r.texte.lower() not in vues:
                    vues.add(r.texte.lower())
                    resultat.append(r)
        return resultat[: options.max_requetes]

    # =============================================================== traitement d'une URL
    def _ressources(self, url: str) -> list[Ressource]:
        """Une URL de résultat → liste de documents à analyser (PDF trouvés ou page elle-même)."""
        tcfg = self.cfg["telechargement"]
        r = telecharger(url, tcfg["taille_max_mo"])
        if r is None:
            return []
        if r.type == "pdf":
            return [r]
        pdfs = []
        for lien in liens_pdf(r, tcfg["pdf_max_par_page"]):
            if self.catalogue.deja_vu(lien):
                continue
            p = telecharger(lien, tcfg["taille_max_mo"])
            if p and p.type == "pdf":
                p.titre = r.titre
                pdfs.append(p)
        return pdfs or [r]

    def traiter_ressource(self, res: Ressource, *, requete: str, origine: str,
                          url_page: str = "", indexer: bool = False, nom_fichier: str = "",
                          forcer: bool = False) -> str:
        """Analyse et range un document. Renvoie 'garde', 'ecarte', 'doublon' ou 'erreur'."""
        if self.catalogue.empreinte_connue(res.empreinte):
            self.catalogue.marquer_vu(res.url)
            return "doublon"
        maxc = self.cfg["albert"]["max_caracteres_analyse"]
        if res.type == "pdf":
            texte, pages = texte_pdf(res.contenu, maxc)
        else:
            texte, pages = texte_html(res.contenu, maxc), ""
        if len(texte) < 300 and res.type == "html":
            self.catalogue.ecarter(res.url, "page sans contenu exploitable", requete)
            return "ecarte"
        try:
            q = qualifier(self.albert, texte, url=res.url, titre=res.titre or nom_fichier, pages=pages,
                          requete=requete, referentiel_txt=self.referentiel_txt,
                          perimetre=self.cfg["perimetre"])
        except (AlbertErreur, json.JSONDecodeError, KeyError) as e:
            self.journal(f"   ⚠️ Albert n'a pas pu lire ce document : {e}")
            return "erreur"

        if not q.get("pertinent") and not forcer:
            self.catalogue.ecarter(res.url, f"hors périmètre : {q.get('raison_si_non_pertinent') or ''}", requete)
            return "ecarte"

        # -- auteur / évaluateur
        acteur = acteur_pour_url(url_page or res.url, self.acteurs) or acteur_pour_nom(q.get("organisme_auteur"), self.acteurs)
        code = acteur["code"] if acteur else "AUTRE"
        ev = q.get("evaluation") or {}

        # -- MI principal
        mis = [m for m in q["modes_intervention"] if isinstance(m, dict) and m.get("nom")]
        principal = mis[0] if mis else {}
        ref = next((m for m in self.mis if m.id == principal.get("id_referentiel")), None)
        nouveau = ref is None and bool(principal)
        famille = ref.famille if ref else principal.get("famille_proposee") or ""
        nom_mi = ref.libelle_court if ref else principal.get("nom")

        ext = "pdf" if res.type == "pdf" else "html"
        cible = self.catalogue.chemin(famille=famille, mi=nom_mi, nouveau=nouveau, date=q.get("date"),
                                      code_auteur=code, type_doc=q.get("type_document"),
                                      titre=q.get("titre") or res.titre or nom_fichier, ext=ext)
        cible.write_bytes(res.contenu)

        doc_id = self.catalogue.nouvel_id()
        albert_id = ""
        if indexer:
            try:
                cid = self._collection_id()
                albert_id = self.albert.indexer(cible, cid, {
                    "doc_id": doc_id, "titre": q.get("titre"), "date": q.get("date"),
                    "type": q.get("type_document"), "mi": nom_mi, "id_referentiel": principal.get("id_referentiel"),
                    "auteur": q.get("organisme_auteur"), "url": res.url}) or ""
            except AlbertErreur as e:
                self.journal(f"   ⚠️ indexation Albert impossible : {e}")

        relatif = str(cible.relative_to(self.catalogue.racine))
        self.catalogue.ajouter({
            "doc_id": doc_id, "date_veille": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "titre": q.get("titre"), "type_document": q.get("type_document"),
            "date_document": q.get("date"), "organisme_auteur": q.get("organisme_auteur"),
            "code_auteur": code, "evaluateur": ev.get("evaluateur"), "zone": q.get("zone"),
            "mi_principal": nom_mi, "dispositif": principal.get("dispositif"),
            "id_referentiel": principal.get("id_referentiel"), "famille": famille,
            "nouveau_mi": nouveau, "criteres": ", ".join(ev.get("criteres") or []),
            "resultats_chiffres": ev.get("resultats_chiffres"),
            "limites_effet_aubaine": ev.get("limites_effet_aubaine"),
            "recommandations": ev.get("recommandations"), "robustesse": ev.get("robustesse"),
            "resume": q.get("resume"), "fichier": relatif, "url_document": res.url,
            "url_page": url_page if url_page != res.url else "", "requete": requete,
            "origine": origine, "pages": pages, "sha256": res.empreinte, "albert_doc_id": albert_id,
        }, [{
            "doc_id": doc_id, "rang": i + 1, "nom": m.get("nom"), "dispositif": m.get("dispositif"),
            "id_referentiel": m.get("id_referentiel"),
            "nouveau": not any(r.id == m.get("id_referentiel") for r in self.mis),
            "famille": m.get("famille_proposee"), "acteur_porteur": m.get("acteur_porteur"),
            "probleme_vise": m.get("probleme_vise"), "moyens": m.get("moyens"),
            "gouvernance": m.get("gouvernance"), "zone": q.get("zone"),
            "type_document": q.get("type_document"), "titre_document": q.get("titre"), "fichier": relatif,
        } for i, m in enumerate(mis)])
        etiquette = "📗 évaluation" if q.get("type_document") == "evaluation" else "📄 document"
        self.journal(f"   {etiquette} rangé : {relatif}")
        return "garde"

    def _collection_id(self) -> int:
        if not hasattr(self, "_cid"):
            self._cid = self.albert.collection(self.cfg["albert"]["collection"],
                                               "Veille modes d'intervention transition écologique")
        return self._cid

    # =============================================================== points d'entrée
    def lancer(self, options: Options) -> dict:
        """Bouton « Lancer la veille »."""
        self.stats = {"requetes": 0, "resultats": 0, "garde": 0, "ecarte": 0, "doublon": 0, "erreur": 0}
        requetes = self.construire_requetes(options)
        self.journal(f"🔎 {len(requetes)} requêtes préparées")
        autorises = domaines_connus(self.acteurs)
        filtrer = self.cfg["recherche"].get("domaines_connus_seulement", True)

        candidats, vus = [], set()
        for i, rq in enumerate(requetes):
            self.progression(0.3 * i / max(len(requetes), 1))
            self.journal(f"🔎 [{rq.origine}] {rq.texte}")
            res = self.moteur.chercher(rq.texte, rq.region)
            self.stats["requetes"] += 1
            if filtrer and rq.origine != "libre":
                res = filtrer_domaines(res, autorises)
            for r in res:
                if r["url"] not in vus and not self.catalogue.deja_vu(r["url"]):
                    vus.add(r["url"])
                    candidats.append((r, rq))
        self.stats["resultats"] = len(candidats)
        self.journal(f"📥 {len(candidats)} nouveaux résultats à examiner")
        return self._traiter_candidats(candidats, options)

    def _traiter_candidats(self, candidats, options: Options) -> dict:
        for i, (r, rq) in enumerate(candidats):
            if self.stats["garde"] >= options.max_documents:
                self.journal(f"⏹️ Plafond de {options.max_documents} documents atteint.")
                break
            self.progression(0.3 + 0.7 * i / max(len(candidats), 1))
            self.journal(f"⬇️ {r['url']}")
            ressources = self._ressources(r["url"])
            if not ressources:
                self.catalogue.ecarter(r["url"], "téléchargement impossible", rq.texte)
                self.stats["erreur"] += 1
                continue
            for res in ressources:
                etat = self.traiter_ressource(res, requete=rq.texte, origine=rq.origine,
                                              url_page=r["url"], indexer=options.indexer_albert)
                self.stats[etat] += 1
            self.catalogue.marquer_vu(r["url"])
        self.progression(1.0)
        self.catalogue.exporter_excel()
        self.journal(f"✅ Terminé : {self.stats['garde']} documents rangés, {self.stats['ecarte']} écartés, "
                     f"{self.stats['doublon']} doublons, {self.stats['erreur']} erreurs.")
        return self.stats

    def traiter_urls(self, urls: list[str], options: Options | None = None, origine: str = "urls") -> dict:
        """Traite une liste d'URL connues (ex. sources citées dans le référentiel)."""
        options = options or Options(max_documents=10_000)
        self.stats = {"requetes": 0, "resultats": len(urls), "garde": 0, "ecarte": 0, "doublon": 0, "erreur": 0}
        candidats = [({"url": u}, Requete(u, origine)) for u in urls if not self.catalogue.deja_vu(u)]
        return self._traiter_candidats(candidats, options)

    def importer_fichiers(self, fichiers: list[str | Path], indexer: bool = False) -> dict:
        """Ajoute la base de documents de l'utilisateur (PDF déjà en sa possession)."""
        self.stats = {"requetes": 0, "resultats": len(fichiers), "garde": 0, "ecarte": 0, "doublon": 0, "erreur": 0}
        for i, f in enumerate(fichiers):
            f = Path(f)
            self.progression(i / max(len(fichiers), 1))
            contenu = f.read_bytes()
            type_ = "pdf" if contenu[:5] == b"%PDF-" else "html" if f.suffix.lower() in (".html", ".htm") else None
            if not type_:
                self.journal(f"   format non pris en charge : {f.name}")
                self.stats["erreur"] += 1
                continue
            self.journal(f"📂 {f.name}")
            res = Ressource(url=f"fichier://{f.name}", contenu=contenu, type=type_, titre=f.stem)
            etat = self.traiter_ressource(res, requete="", origine="base_utilisateur",
                                          indexer=indexer, nom_fichier=f.stem, forcer=True)
            self.stats[etat] += 1
        self.progression(1.0)
        self.catalogue.exporter_excel()
        self.journal(f"✅ Import : {self.stats['garde']} rangés, {self.stats['ecarte']} hors périmètre, "
                     f"{self.stats['doublon']} doublons, {self.stats['erreur']} erreurs.")
        return self.stats
