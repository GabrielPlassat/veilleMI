"""Lecture des documents par Albert : qualification et génération de requêtes."""
from __future__ import annotations

from .albert import Albert, AlbertErreur

DEFINITION_MI = (
    "Un MODE D'INTERVENTION (MI) est un ensemble organisé de moyens, de règles, de gouvernance, "
    "de capacitation et de récit mobilisé par une structure (État, ministère, agence, collectivité, "
    "organisation internationale, acteur privé) pour résoudre un problème plus ou moins bien formulé. "
    "Exemples : appel à projets, fonds de garantie, bonus-malus, obligation réglementaire calendaire, "
    "label, certificats d'économies d'énergie, leasing social, accompagnement individualisé, "
    "contrat carbone pour différence, programme expérimental, commun numérique, formation."
)

SYSTEME_QUALIF = f"""Tu es analyste de politiques publiques de la transition écologique.
{DEFINITION_MI}
Tu lis un document et tu réponds UNIQUEMENT par un objet JSON valide, en français, sans texte autour.
N'invente rien : si une information est absente du document, mets null."""

GABARIT_QUALIF = """PÉRIMÈTRE THÉMATIQUE À RETENIR :
{perimetre}

RÉFÉRENTIEL ACTUEL DES MODES D'INTERVENTION (id | famille | nom) :
{referentiel}

DOCUMENT
- URL : {url}
- Titre détecté : {titre}
- Pages : {pages}
- Trouvé via la requête : {requete}
--- DÉBUT DU TEXTE (extrait) ---
{texte}
--- FIN DU TEXTE ---

Réponds avec ce JSON :
{{
  "pertinent": true/false,            // traite d'un ou plusieurs MI dans le périmètre thématique ?
  "raison_si_non_pertinent": "...",
  "titre": "titre exact du document",
  "date": "AAAA ou AAAA-MM",
  "organisme_auteur": "organisme qui publie le document",
  "type_document": "evaluation" | "rapport_dispositif" | "texte_cadre" | "etude" | "autre",
      // evaluation = juge l'efficacité/efficience/effets d'un MI (Cour des comptes, I4CE, CGDD, OCDE...)
      // rapport_dispositif = présente/bilan d'activité d'un MI par son porteur
      // texte_cadre = stratégie, loi, programmation ; etude = analyse générale
  "zone": "France" | "Europe" | "Monde" | "<pays>",
  "modes_intervention": [
    {{
      "nom": "nom générique du MI (ex. 'Prêt bonifié à taux zéro')",
      "dispositif": "nom propre du dispositif concret (ex. 'éco-PTZ')",
      "id_referentiel": "MIxx si correspond à une ligne du référentiel, sinon null",
      "nouveau": true/false,           // true si absent du référentiel
      "famille_proposee": "famille du référentiel la plus proche, ou nouvelle famille",
      "acteur_porteur": "qui met en oeuvre",
      "probleme_vise": "problème que le MI cherche à résoudre (1 phrase)",
      "moyens": "moyens et règles principaux (1 phrase)",
      "gouvernance": "qui pilote / décide (1 phrase ou null)"
    }}
  ],
  "evaluation": {{                     // null si le document n'évalue rien
    "evaluateur": "organisme évaluateur",
    "criteres": ["efficacité", "efficience", "pertinence", "cohérence", "impact", "coût budgétaire", ...],
    "resultats_chiffres": "principaux chiffres de résultat (2 phrases max)",
    "limites_effet_aubaine": "limites, effets d'aubaine, effets rebond relevés",
    "recommandations": "principales recommandations (2 phrases max)",
    "robustesse": "Faible" | "Moyenne" | "Forte"   // contrefactuel, données, méthode
  }},
  "resume": "résumé en 3 phrases maximum"
}}
Liste au plus 5 modes d'intervention, le principal en premier."""


def qualifier(albert: Albert, texte: str, *, url: str, titre: str, pages: int | str,
              requete: str, referentiel_txt: str, perimetre: str) -> dict:
    invite = GABARIT_QUALIF.format(perimetre=perimetre.strip(), referentiel=referentiel_txt,
                                   url=url, titre=titre or "(inconnu)", pages=pages or "?",
                                   requete=requete or "-", texte=texte or "(texte non extractible)")
    res = albert.chat_json(SYSTEME_QUALIF, invite, max_tokens=2500)
    res.setdefault("modes_intervention", [])
    if not isinstance(res["modes_intervention"], list):
        res["modes_intervention"] = []
    return res


SYSTEME_REQ = "Tu es documentaliste expert des politiques publiques environnementales. Réponds en JSON."

GABARIT_REQ = """{definition}

Objectif : trouver sur le web des RAPPORTS et des ÉVALUATIONS de modes d'intervention
publics (ou privés) liés à ce périmètre :
{perimetre}

Zone géographique visée : {zone}
Organismes évaluateurs à privilégier : {evaluateurs}

Modes d'intervention DÉJÀ CONNUS (à ne pas rechercher, on veut en découvrir d'autres) :
{connus}

{consigne}

Propose {n} requêtes de moteur de recherche courtes (4 à 9 mots), variées, chacune ciblant
un dispositif ou instrument concret différent (nom propre si possible) et contenant un mot comme
évaluation / bilan / rapport / evaluation / review / assessment.
Langue : {langue}.
Réponds : {{"requetes": ["...", "..."]}}"""


def generer_requetes(albert: Albert, *, perimetre: str, zone: str, evaluateurs: list[str],
                     connus: list[str], n: int = 10, consigne: str = "") -> list[str]:
    langue = "français" if zone == "France" else "anglais (et quelques-unes en français)"
    invite = GABARIT_REQ.format(definition=DEFINITION_MI, perimetre=perimetre.strip(), zone=zone,
                                evaluateurs=", ".join(evaluateurs) or "tous",
                                connus="\n".join(f"- {c}" for c in connus),
                                consigne=f"Consigne de l'utilisateur : {consigne}" if consigne else "",
                                n=n, langue=langue)
    try:
        res = albert.chat_json(SYSTEME_REQ, invite, max_tokens=1200, temperature=0.6)
    except AlbertErreur:
        return []
    return [q.strip() for q in res.get("requetes", []) if isinstance(q, str) and q.strip()][:n]
