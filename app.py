"""Veille des modes d'intervention (MI) — application Streamlit.

Lancement local :  streamlit run app.py
Streamlit Cloud :  mettre ALBERT_API_KEY (et BRAVE_API_KEY optionnel) dans les « Secrets ».
"""
import io
import zipfile
from pathlib import Path
import tempfile

import pandas as pd
import streamlit as st

from veille_mi import Veille, charger_config
from veille_mi.albert import Albert, AlbertErreur
from veille_mi.pipeline import Options
from veille_mi.referentiel import charger_referentiel

st.set_page_config(page_title="Veille MI", page_icon="🔭", layout="wide")
CFG = charger_config()
DOSSIER = Path(CFG["telechargement"]["dossier"])


def secret(nom):
    try:
        return st.secrets.get(nom, "")
    except Exception:
        return ""


# ------------------------------------------------------------------ barre latérale
with st.sidebar:
    st.title("🔭 Veille MI")
    st.caption("Modes d'intervention de la transition écologique : dispositifs, rapports, évaluations.")
    cle = secret("ALBERT_API_KEY") or st.text_input("Clé Albert API", type="password")
    if secret("ALBERT_API_KEY"):
        st.success("Clé Albert chargée depuis les secrets", icon="🔑")
    modele = st.text_input("Modèle Albert", CFG["albert"]["modele"],
                           help="openweight-medium (rapide) ou openweight-large (plus fin)")
    CFG["albert"]["modele"] = modele
    moteur = st.radio("Moteur de recherche web", ["duckduckgo", "brave"],
                      index=0 if CFG["recherche"]["moteur"] == "duckduckgo" else 1,
                      help="Albert ne cherche pas sur le web. DuckDuckGo est gratuit sans clé ; "
                           "Brave demande une clé gratuite mais est plus stable.")
    CFG["recherche"]["moteur"] = moteur
    cle_brave = None
    if moteur == "brave":
        cle_brave = secret("BRAVE_API_KEY") or st.text_input("Clé Brave Search", type="password")
    CFG["recherche"]["domaines_connus_seulement"] = st.toggle(
        "Seulement les sites des acteurs connus", CFG["recherche"]["domaines_connus_seulement"],
        help="Désactiver pour élargir (plus de bruit, plus de découvertes).")
    if st.button("Tester la connexion Albert", width="stretch"):
        try:
            info = Albert(cle, CFG["albert"]["base_url"], modele).verifier()
            st.success("Connexion OK")
            with st.expander("Compte et quotas"):
                st.json(info)
        except (AlbertErreur, Exception) as e:
            st.error(str(e))


def veille(journal, progression):
    if not cle:
        st.error("Renseignez d'abord la clé Albert API dans la barre latérale.")
        st.stop()
    return Veille(CFG, cle, DOSSIER, cle_brave=cle_brave, journal=journal, progression=progression)


def zone_journal():
    barre = st.progress(0.0)
    boite = st.empty()
    lignes = []

    def journal(msg):
        lignes.append(str(msg))
        boite.code("\n".join(lignes[-25:]), language=None)

    return journal, lambda x: barre.progress(min(max(x, 0.0), 1.0))


MIS, URLS_REF = charger_referentiel(CFG["referentiel"]["fichier"])
EVALUATEURS = [a for a in CFG["acteurs"] if a["role"] in ("evaluateur", "les_deux")]

onglets = st.tabs(["🚀 Lancer la veille", "📚 Résultats", "📂 Ajouter ma base", "♻️ Reprendre / sauvegarder", "⚙️ Acteurs"])

# ------------------------------------------------------------------ 1. Lancer
with onglets[0]:
    st.subheader("Paramètres de la veille")
    c1, c2 = st.columns(2)
    with c1:
        modes = st.multiselect(
            "Stratégies de recherche",
            ["referentiel", "evaluateurs", "decouverte"], default=["referentiel", "evaluateurs", "decouverte"],
            format_func={"referentiel": "📋 Évaluations des MI du référentiel",
                         "evaluateurs": "🏛️ Publications récentes des évaluateurs",
                         "decouverte": "🧭 Découverte de nouveaux MI (Albert propose des requêtes)"}.get)
        zones = st.multiselect("Zones", ["France", "Europe", "Monde"], default=["France"])
        MI_PAR_ID = {m.id: m for m in MIS}
        mi_sel = st.multiselect("Modes d'intervention ciblés (vide = tous)", list(MI_PAR_ID),
                                format_func=lambda i: f"{i} · {MI_PAR_ID[i].famille} · {MI_PAR_ID[i].libelle_court}")
        EV_PAR_CODE = {a["code"]: a for a in EVALUATEURS}
        ev_sel = st.multiselect("Évaluateurs ciblés (vide = tous ceux des zones)", list(EV_PAR_CODE),
                                format_func=lambda c: f"{EV_PAR_CODE[c]['nom']} ({EV_PAR_CODE[c]['zone']})",
                                help="Si vous en choisissez 3 au plus, les recherches sont faites site par site.")
    with c2:
        requete_libre = st.text_area("Requêtes libres (une par ligne, optionnel)",
                                     placeholder="évaluation MaPrimeRénov' Cour des comptes\nfossil fuel subsidy reform evaluation OECD")
        consigne = st.text_input("Consigne pour la découverte (optionnel)",
                                 placeholder="ex. insister sur la sortie des énergies fossiles et la mobilité rurale")
        max_req = st.slider("Nombre maximum de requêtes", 5, 150, 30, 5)
        max_docs = st.slider("Nombre maximum de documents à ranger", 5, 200, 25, 5)
        indexer = st.checkbox("Indexer aussi les documents dans une collection Albert (pour le RAG)", False)

    options = Options(modes=modes, mi_ids=mi_sel, acteurs_codes=ev_sel,
                      zones=zones or ["France"], requete_libre=requete_libre, consigne_decouverte=consigne,
                      max_requetes=max_req, max_documents=max_docs, indexer_albert=indexer)

    b1, b2 = st.columns([1, 3])
    if b1.button("👀 Voir les requêtes"):
        v = veille(lambda m: None, lambda x: None)
        st.dataframe(pd.DataFrame([r.__dict__ for r in v.construire_requetes(options)]), width="stretch")
    if b2.button("🚀 Lancer la veille", type="primary", width="stretch"):
        journal, progression = zone_journal()
        v = veille(journal, progression)
        stats = v.lancer(options)
        st.success(f"{stats['garde']} documents rangés · {stats['ecarte']} écartés · "
                   f"{stats['doublon']} doublons · {stats['erreur']} erreurs")
        st.info("Pensez à télécharger le dossier (onglet ♻️) : sur Streamlit Cloud, les fichiers sont effacés au redémarrage.")

# ------------------------------------------------------------------ 2. Résultats
with onglets[1]:
    f_docs = DOSSIER / "catalogue_documents.csv"
    if not f_docs.exists():
        st.info("Aucune veille encore. Lancez-en une ou reprenez un dossier existant.")
    else:
        docs = pd.read_csv(f_docs, dtype=str, keep_default_na=False)
        mi = pd.read_csv(DOSSIER / "catalogue_modes_intervention.csv", dtype=str, keep_default_na=False)
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Documents", len(docs))
        k2.metric("Évaluations", int((docs["type_document"] == "evaluation").sum()))
        k3.metric("MI du référentiel couverts", docs.loc[docs["id_referentiel"] != "", "id_referentiel"].nunique())
        k4.metric("Nouveaux MI candidats", mi.loc[mi["nouveau"].str.lower() == "true", "nom"].str.lower().nunique())

        f1, f2, f3 = st.columns(3)
        t = f1.multiselect("Type", sorted(docs["type_document"].unique()))
        fa = f2.multiselect("Famille", sorted(docs["famille"].unique()))
        au = f3.multiselect("Auteur", sorted(docs["code_auteur"].unique()))
        vue = docs
        if t: vue = vue[vue["type_document"].isin(t)]
        if fa: vue = vue[vue["famille"].isin(fa)]
        if au: vue = vue[vue["code_auteur"].isin(au)]
        st.dataframe(vue[["doc_id", "date_document", "code_auteur", "type_document", "mi_principal", "dispositif",
                          "titre", "robustesse", "resultats_chiffres", "fichier", "url_document"]],
                     width="stretch", hide_index=True,
                     column_config={"url_document": st.column_config.LinkColumn("Source")})

        st.subheader("🆕 Nouveaux modes d'intervention candidats")
        from veille_mi.rangement import Catalogue
        st.dataframe(Catalogue(DOSSIER).nouveaux_mi(), width="stretch", hide_index=True)

        xlsx = Catalogue(DOSSIER).exporter_excel()
        st.download_button("⬇️ Catalogue Excel", xlsx.read_bytes(), file_name=xlsx.name)

# ------------------------------------------------------------------ 3. Ajouter ma base
with onglets[2]:
    st.subheader("Ajouter ma base de documents d'évaluation")
    st.caption("Les PDF sont lus par Albert, renommés et rangés comme les documents trouvés en veille. "
               "Un fichier .zip contenant des PDF est accepté.")
    fichiers = st.file_uploader("PDF ou ZIP", type=["pdf", "zip", "html"], accept_multiple_files=True)
    if fichiers and st.button("📂 Importer et ranger", type="primary"):
        journal, progression = zone_journal()
        tmp = Path(tempfile.mkdtemp())
        chemins = []
        for f in fichiers:
            if f.name.lower().endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(f.getvalue())) as z:
                    for n in z.namelist():
                        if n.lower().endswith((".pdf", ".html", ".htm")) and not n.startswith("__MACOSX"):
                            cible = tmp / Path(n).name
                            cible.write_bytes(z.read(n))
                            chemins.append(cible)
            else:
                cible = tmp / f.name
                cible.write_bytes(f.getvalue())
                chemins.append(cible)
        stats = veille(journal, progression).importer_fichiers(chemins, indexer=indexer)
        st.success(f"{stats['garde']} documents rangés, {stats['doublon']} doublons, {stats['erreur']} erreurs")

    st.divider()
    st.markdown(f"**Sources citées dans le référentiel** : {len(URLS_REF)} liens trouvés dans le fichier Excel.")
    if st.button("Télécharger et ranger ces sources"):
        journal, progression = zone_journal()
        stats = veille(journal, progression).traiter_urls(URLS_REF, origine="referentiel_sources")
        st.success(f"{stats['garde']} documents rangés")

# ------------------------------------------------------------------ 4. Reprendre / sauvegarder
with onglets[3]:
    st.subheader("Sauvegarder")
    if (DOSSIER / "catalogue_documents.csv").exists():
        from veille_mi.rangement import Catalogue
        if st.button("Préparer le .zip du dossier de veille"):
            z = Catalogue(DOSSIER).zipper()
            st.download_button("⬇️ Télécharger le dossier complet", z.read_bytes(), file_name=z.name,
                               type="primary")
    st.subheader("Reprendre une veille précédente")
    st.caption("Chargez le .zip téléchargé la dernière fois : les documents déjà vus ne seront pas retraités.")
    ancien = st.file_uploader("Dossier de veille (.zip)", type=["zip"], key="reprise")
    if ancien and st.button("Restaurer"):
        with zipfile.ZipFile(io.BytesIO(ancien.getvalue())) as z:
            racine = DOSSIER.parent
            for n in z.namelist():
                if n.startswith(DOSSIER.name + "/") and ".." not in n:
                    z.extract(n, racine)
        st.success("Dossier restauré.")

# ------------------------------------------------------------------ 5. Acteurs
with onglets[4]:
    st.caption("Pour ajouter un acteur ou un site, modifiez config.yaml dans GitHub (bouton crayon) : "
               "l'application se met à jour toute seule.")
    st.dataframe(pd.DataFrame([{**a, "domaines": ", ".join(a["domaines"])} for a in CFG["acteurs"]]),
                 width="stretch", hide_index=True)
    st.markdown("**Référentiel chargé** : " + f"{len(MIS)} modes d'intervention")
    st.dataframe(pd.DataFrame([{"id": m.id, "famille": m.famille, "nom": m.nom,
                                "termes de recherche": " · ".join(m.termes_recherche())} for m in MIS]),
                 width="stretch", hide_index=True)
