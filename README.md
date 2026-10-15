# 🔭 Veille des modes d'intervention (MI) — transition écologique

Outil de veille **à la demande** : on appuie sur un bouton, il cherche sur le web les modes d'intervention
(dispositifs, programmes, instruments) liés à la transition écologique, à l'énergie et à la sortie des fossiles,
récupère **les rapports et leurs évaluations**, les fait **lire par Albert API**, puis les **range et les nomme**
dans un dossier, avec un catalogue Excel.

C'est la première étape avant de **classifier les MI, en extraire une grammaire et enrichir ART**.

## Ce que fait un lancement

```
Requêtes ──► Recherche web ──► Téléchargement ──► Lecture par Albert ──► Rangement + catalogue
 (3 stratégies)  (DuckDuckGo/Brave)  (PDF trouvés      (pertinent ? MI ?        (dossier par famille / MI,
                 filtrée sur les      sur la page)      évaluation ? chiffres)   Excel de synthèse)
                 sites des acteurs
```

**Trois stratégies de recherche**, combinables :

| Stratégie | Ce qu'elle cherche | Exemple de requête |
|---|---|---|
| 📋 Référentiel | les évaluations des 43 MI du fichier `MI_ademe_ART_enrichi.xlsx` et des dispositifs cités entre parenthèses | `éco-PTZ évaluation rapport` |
| 🏛️ Évaluateurs | les publications récentes de chaque évaluateur sur chaque thème | `site:ccomptes.fr évaluation rénovation énergétique` |
| 🧭 Découverte | des MI **absents** du référentiel : Albert propose lui-même des requêtes | `contrat carbone pour différence bilan` |

**Pour chaque document**, Albert renvoie : pertinence, titre, date, auteur, type (évaluation / rapport de dispositif / texte cadre / étude),
les MI concernés (rattachés au référentiel ou **nouveaux**), le problème visé, les moyens, la gouvernance, et pour les
évaluations : critères, résultats chiffrés, limites et effets d'aubaine, recommandations, robustesse de la preuve.

## Le dossier produit

```
veille_MI/
├── rapports/
│   ├── instruments-financiers/pret-bonifie-a-taux-zero/2025_CCOMPTES_EVAL_l-eco-pret-a-taux-zero.pdf
│   ├── signal-prix/fiscalite-incitative-et-bonus-malus/2021_I4CE_EVAL_bonus-malus-automobile.pdf
│   ├── _Nouveaux_MI/<mi-decouvert>/...      ← MI candidats à ajouter au référentiel
│   └── _A_classer/...                        ← documents sans MI identifié
├── catalogue_documents.csv                   ← 1 ligne par document
├── catalogue_modes_intervention.csv          ← 1 ligne par MI mentionné dans un document
├── urls_ecartees.csv                         ← ce qui a été vu et rejeté (jamais retraité)
└── veille_modes_intervention.xlsx            ← Documents · MI détectés · Nouveaux MI candidats · Évaluations
```

Nom des fichiers : `ANNÉE_CODE-AUTEUR_TYPE_titre.pdf` (types : EVAL, RAPPORT, CADRE, ETUDE, DOC).
Les documents déjà vus (même URL ou même contenu) ne sont jamais retraités : on peut relancer sans risque.

---

## Mise en route (sans droits administrateur, rien à installer sur l'ordinateur)

### 1. Mettre le code sur GitHub
1. Sur github.com : **New repository** → nom `veille-mi` → **Public** (nécessaire pour Streamlit Cloud gratuit et Colab sans jeton).
2. **Add file → Upload files** → glisser **le contenu** du dossier `veille-mi` (pas le dossier lui-même) → **Commit**.

> ⚠️ Le fichier `data/MI_ademe_ART_enrichi.xlsx` sera public. Si ce n'est pas souhaitable, mettez le dépôt en **Private** et utilisez Colab avec un jeton (voir FAQ).

### 2. Obtenir une clé Albert API
Connexion ProConnect sur le Playground Albert → page **Clés API** : https://albert.playground.etalab.gouv.fr/keys → créer une clé (affichée une seule fois).
Documentation : https://guides.ia.numerique.gouv.fr/albert-api

### 3a. Utiliser avec Google Colab (recommandé : les rapports vont dans votre Drive)
1. Sur GitHub, ouvrir `veille_MI_colab.ipynb` → bouton **Open in Colab** (ou dans Colab : Fichier → Ouvrir → onglet GitHub).
2. Icône 🔑 à gauche → **Ajouter un secret** `ALBERT_API_KEY` = votre clé → activer l'accès.
3. Cellule 1 : remplacer `VOTRE-COMPTE` par votre identifiant GitHub → ▶.
4. Cellule 2 : cocher les options → ▶ **c'est le bouton « Lancer la veille »**.

### 3b. Utiliser avec Streamlit Cloud (interface web, partageable)
1. https://share.streamlit.io → **Create app** → choisir le dépôt `veille-mi`, fichier `app.py`.
2. **Advanced settings → Secrets** : coller `ALBERT_API_KEY = "votre-clé"`.
3. Ouvrir l'app → onglet 🚀 → **Lancer la veille**.

> Sur Streamlit Cloud, les fichiers sont **effacés au redémarrage** : téléchargez le .zip (onglet ♻️) après chaque veille,
> et rechargez-le la fois suivante pour que l'outil se souvienne de ce qu'il a déjà vu.

---

## Ajouter votre base de documents d'évaluation
- **Colab** : mettre les PDF dans un dossier Drive (par défaut `MyDrive/base_evaluations`) → cellule 3.
- **Streamlit** : onglet 📂 → déposer les PDF ou un .zip.

Ils sont lus par Albert, renommés et rangés comme le reste (toujours conservés, même si Albert les juge hors périmètre).
La cellule 4 / le bouton « sources du référentiel » récupère aussi les 12 liens déjà cités dans le fichier Excel.

## Personnaliser sans coder : `config.yaml`
Modifiable directement sur GitHub (icône ✏️) :
- **acteurs** : ajouter un évaluateur ou un porteur avec son site (`domaines`) ;
- **perimetre** : la définition du périmètre thématique qu'Albert applique ;
- **themes_fr / themes_en** : les thèmes croisés avec chaque évaluateur ;
- **albert.modele** : `openweight-medium` (rapide) ou `openweight-large` (plus fin) ;
- **recherche.moteur** : `duckduckgo` (gratuit, sans clé) ou `brave` (clé gratuite, plus stable).

Pour enrichir le référentiel, remplacez `data/MI_ademe_ART_enrichi.xlsx` (même structure : colonne A = famille, B = mode d'intervention).

## Indexation Albert (préparer la suite)
L'option « Indexer dans une collection Albert » envoie chaque document retenu dans la collection privée
`veille-modes-intervention`, avec ses métadonnées (MI, type, auteur, date). Cette collection servira de base
RAG pour l'étape suivante : classer les MI et en extraire une grammaire.

## FAQ
- **La recherche ralentit / renvoie peu de résultats** : DuckDuckGo limite les rafales. Baisser `max_requetes`,
  augmenter `pause_entre_requetes_s`, ou passer à Brave (clé gratuite : https://api-search.brave.com).
- **Trop peu de résultats** : décocher « Seulement les sites des acteurs connus » (plus de bruit, plus de découvertes).
- **PDF scannés** : le texte n'est pas extractible ; Albert se fonde alors sur le titre, le document va dans `_A_classer`.
- **Dépôt privé + Colab** : créer un jeton GitHub (Settings → Developer settings → Fine-grained token, lecture seule) et
  écrire l'URL `https://<jeton>@github.com/VOTRE-COMPTE/veille-mi` dans la cellule 1.

## Structure du code
| Fichier | Rôle |
|---|---|
| `app.py` | interface Streamlit |
| `veille_MI_colab.ipynb` | interface Colab |
| `config.yaml` | acteurs, domaines, périmètre, réglages |
| `veille_mi/referentiel.py` | lecture du fichier Excel des MI |
| `veille_mi/recherche.py` | recherche web (DuckDuckGo / Brave) |
| `veille_mi/telechargement.py` | téléchargement, détection des PDF, extraction du texte |
| `veille_mi/albert.py` | client Albert API (chat JSON, collections, documents) |
| `veille_mi/analyse.py` | consignes données à Albert (qualification, génération de requêtes) |
| `veille_mi/rangement.py` | nommage, dossiers, catalogue CSV/Excel, zip |
| `veille_mi/pipeline.py` | enchaînement complet |
