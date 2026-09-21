#!/usr/bin/env python3
"""
update_tarifs.py — Mise à jour ANNUELLE des tarifs énergie (AEROHM)

Exécuté une fois par an par GitHub Actions, mi-février, après la révision
annuelle des tarifs réglementés d'électricité du 1er février (et l'alignement
des fournisseurs alternatifs dans les jours qui suivent).

Optimisation des tokens :
  - UN seul appel API (électricité + énergies de chauffage) ;
  - recherches web plafonnées (max_uses) : c'est le poste le plus coûteux ;
  - l'IA ne renvoie QUE les valeurs qui évoluent, en JSON compact ;
  - les valeurs fixes (jours Tempo/EJP, métadonnées) sont conservées ;
  - les abonnements 9 et 12 kVA sont calculés ici à partir de l'écart
    réglementé (TURPE) observé chez EDF, au lieu d'être demandés offre par offre.
Robustesse :
  - fusion champ par champ dans le tarifs.json existant : une valeur absente
    ou aberrante conserve l'ancienne au lieu de faire échouer la mise à jour ;
  - la structure du fichier ne change jamais (le configurateur n'est pas impacté).
"""

import os
import json
import copy
import anthropic
from datetime import datetime, date
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
TARIFS_FILE = Path(__file__).parent / "tarifs.json"
MODEL = "claude-sonnet-4-6"
MAX_RECHERCHES = 8      # plafond de recherches web (principal levier de coût)
# Chaque recherche injecte des pages entières dans la consommation : on limite
# aux sites qui publient réellement ces tarifs, pour éviter les pages inutiles.
SITES = [
    "kelwatt.fr", "selectra.info", "hellowatt.fr", "jechange.fr",
    "fournisseurs-electricite.com", "cre.fr", "edf.fr", "octopusenergy.fr",
    "fioulreduc.com", "propellet.fr",
]
MAX_TOKENS = 6000       # plafond de sortie : non facturé s'il n'est pas atteint

# Champs demandés à l'IA : uniquement ce qui évolue d'une année sur l'autre.
# Grilles 6/9/12 kVA complètes seulement pour EDF (base, HC/HP, Tempo) :
# elles servent à calculer l'écart réglementé appliqué à toutes les autres offres.
DEMANDE = {
    "edf": {
        "base": ["kwh", "abo_6kva", "abo_9kva", "abo_12kva"],
        "hchp": ["kwh_hc", "kwh_hp", "abo_6kva", "abo_9kva", "abo_12kva"],
        "tempo": ["abo_6kva", "abo_9kva", "abo_12kva", "bleu_hc", "bleu_hp",
                  "blanc_hc", "blanc_hp", "rouge_hc", "rouge_hp"],
        "ejp": ["abo_6kva", "kwh_normal", "kwh_pointe"],
        "zen_fixe": ["kwh", "abo_6kva"],
    },
    "engie": {"base": ["kwh", "abo_6kva"], "hchp": ["kwh_hc", "kwh_hp", "abo_6kva"]},
    "totalenergies": {
        "heures_eco_base": ["kwh", "abo_6kva"],
        "heures_eco_hchp": ["kwh_hc", "kwh_hp", "abo_6kva"],
        "heures_eco_plus": ["abo_6kva", "eco_hc", "eco_hp", "peak_hc", "peak_hp"],
        "fixe_2ans": ["kwh", "abo_6kva"],
    },
    "ohm": {"base": ["kwh", "abo_6kva"], "hchp": ["kwh_hc", "kwh_hp", "abo_6kva"]},
    "mint": {"base": ["kwh", "abo_6kva"], "hchp": ["kwh_hc", "kwh_hp", "abo_6kva"]},
    "primeo": {"confort_plus": ["kwh", "abo_6kva"]},
    "octopus": {
        "go": ["kwh_hc", "kwh_hp", "abo_6kva"],
        "intelligent": ["kwh_hc", "kwh_hp", "abo_6kva", "bonus_ve"],
        "drive_pack": ["kwh", "abo_6kva", "forfait_ve"],
    },
    "ekwateur": {"hchp": ["kwh_hc", "kwh_hp", "abo_6kva"]},
    "ilek": {"base": ["kwh", "abo_6kva"]},
    "eni": {"agile": ["abo_6kva", "eco_hc", "eco_hp", "peak_hc", "peak_hp"]},
    "energies": ["gaz_kwh", "fioul_kwh", "granules_kwh", "buches_kwh"],
}

# Bornes de cohérence (TTC). Hors bornes → valeur rejetée, ancienne conservée.
def bornes(champ: str):
    if champ.startswith("abo_"):
        return (60, 500)
    if champ in ("rouge_hc", "rouge_hp", "kwh_pointe", "peak_hc", "peak_hp"):
        return (0.15, 1.20)
    if champ == "bonus_ve":
        return (0.0, 0.30)
    if champ == "forfait_ve":
        return (0.0, 100.0)
    if champ == "gaz_kwh":
        return (0.06, 0.22)
    if champ == "fioul_kwh":
        return (0.07, 0.25)
    if champ == "granules_kwh":
        return (0.05, 0.18)
    if champ == "buches_kwh":
        return (0.025, 0.12)
    return (0.08, 0.45)   # prix du kWh électricité (base, HC, HP, bleu, blanc, éco…)


def gabarit_json() -> str:
    """Gabarit compact envoyé à l'IA (0 = valeur à remplir)."""
    g = {}
    for fourn, offres in DEMANDE.items():
        if isinstance(offres, list):
            g[fourn] = {c: 0 for c in offres}
        else:
            g[fourn] = {o: {c: 0 for c in champs} for o, champs in offres.items()}
    return json.dumps(g, separators=(",", ":"))


PROMPT = f"""Trouve les tarifs TTC en vigueur en France pour les particuliers (puissance 6 kVA sauf si le champ indique 9 ou 12 kVA), puis les prix des énergies de chauffage.
Sources à privilégier : une page comparative récente (kelwatt.fr ou selectra.info) pour les fournisseurs alternatifs, cre.fr pour les tarifs réglementés EDF et le prix repère du gaz.
Énergies de chauffage, en €/kWh TTC : gaz = prix repère CRE chauffage ; fioul = prix du litre ÷ 9,96 ; granulés = prix de la tonne en vrac ÷ 4600 ; bûches = prix du stère sec ÷ 1700.
Réponds UNIQUEMENT avec ce JSON compact, sans espaces, sans retour à la ligne ni texte autour, en remplaçant chaque 0 : prix du kWh en € avec 4 décimales, abonnements en €/an, forfait_ve en €/mois. Mets null si une valeur est introuvable, ne l'invente pas. Ne commente pas ta recherche : le JSON doit être la seule chose que tu écris.
{gabarit_json()}"""


# ── Utilitaires ───────────────────────────────────────────────────────────────
def extract_json(raw: str) -> dict:
    """Parcourt toute la réponse et renvoie l'objet JSON qui contient la clé
    "edf". L'IA ajoute parfois des remarques avant ou APRÈS le JSON malgré la
    consigne : on ne suppose donc ni sa position, ni qu'il est seul."""
    candidats = []
    i = 0
    while True:
        start = raw.find("{", i)
        if start == -1:
            break
        depth, fin = 0, None
        for j in range(start, len(raw)):
            if raw[j] == "{":
                depth += 1
            elif raw[j] == "}":
                depth -= 1
                if depth == 0:
                    fin = j
                    break
        if fin is None:
            break
        try:
            obj = json.loads(raw[start:fin + 1])
            if isinstance(obj, dict):
                candidats.append(obj)
            i = fin + 1          # objet valide : on saute tout son contenu
        except json.JSONDecodeError:
            i = start + 1        # faux départ : on essaie l'accolade suivante
    for obj in candidats:
        if "edf" in obj:
            return obj
    raise ValueError(f"Aucun JSON contenant 'edf' dans la réponse : {raw[:300]!r}")


def load_current(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tarifs(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ tarifs.json enregistré : {path}")


def prochaine_revision(today: date) -> str:
    """Prochaine révision annuelle des tarifs réglementés : 1er février."""
    annee = today.year if today < date(today.year, 2, 1) else today.year + 1
    return f"{annee}-02-01"


# ── Appel API unique ──────────────────────────────────────────────────────────
def fetch_valeurs() -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    print(f"📡 Appel API unique (recherches web plafonnées à {MAX_RECHERCHES})...")
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        tools=[{"type": "web_search_20250305", "name": "web_search",
                "max_uses": MAX_RECHERCHES, "allowed_domains": SITES}],
        messages=[{"role": "user", "content": PROMPT}],
    )

    u = response.usage
    tool_use = getattr(u, "server_tool_use", None)
    nb_rech = getattr(tool_use, "web_search_requests", "?") if tool_use else "?"
    print(f"📊 Consommation : {u.input_tokens} tokens en entrée · {u.output_tokens} en sortie · "
          f"{nb_rech} recherche(s) web · stop_reason={response.stop_reason}")

    if response.stop_reason == "max_tokens":
        raise ValueError("Réponse tronquée : plafond MAX_TOKENS atteint")

    blocs = [b.text for b in response.content if getattr(b, "type", "") == "text" and b.text.strip()]
    if not blocs:
        raise ValueError(f"Aucun texte dans la réponse (stop_reason={response.stop_reason})")
    texte = "\n".join(blocs)
    data = extract_json(texte)
    # Remarques éventuelles de l'IA (valeurs non trouvées…) : utiles dans le log
    remarques = texte[texte.rfind("}") + 1:].strip()
    if remarques:
        print(f"💬 Remarque de l'IA : {remarques[:400]}")
    return data


# ── Fusion champ par champ ────────────────────────────────────────────────────
def fusionner(current: dict, recu: dict) -> tuple[dict, list, list]:
    tarifs = copy.deepcopy(current)
    changes, rejets = [], []

    def appliquer(cible: dict, champ: str, val, chemin: str):
        if val is None:
            rejets.append(f"{chemin} (introuvable)")
            return
        if not isinstance(val, (int, float)):
            rejets.append(f"{chemin} (non numérique : {val!r})")
            return
        lo, hi = bornes(champ)
        if not (lo <= val <= hi):
            rejets.append(f"{chemin} (hors bornes : {val})")
            return
        ancien = cible.get(champ)
        dec = 2 if (champ.startswith("abo_") or champ == "forfait_ve") else 4
        cible[champ] = round(float(val), dec)
        if ancien != cible[champ]:
            changes.append(f"{chemin} : {ancien} → {cible[champ]}")

    for fourn, offres in DEMANDE.items():
        bloc_recu = recu.get(fourn) or {}
        if isinstance(offres, list):                       # énergies de chauffage
            cible = tarifs.setdefault(fourn, {})
            for champ in offres:
                appliquer(cible, champ, bloc_recu.get(champ), f"{fourn}.{champ}")
            continue
        for offre, champs in offres.items():
            cible = tarifs.setdefault(fourn, {}).setdefault(offre, {})
            valeurs = bloc_recu.get(offre) or {}
            for champ in champs:
                appliquer(cible, champ, valeurs.get(champ), f"{fourn}.{offre}.{champ}")
    return tarifs, changes, rejets


def calculer_paliers_kva(tarifs: dict) -> int:
    """Abonnements 9/12 kVA des offres non-EDF = abonnement 6 kVA + écart
    réglementé (TURPE) observé chez EDF pour le même type d'option."""
    def ecarts(offre: dict, defaut9: float, defaut12: float):
        a6, a9, a12 = offre.get("abo_6kva"), offre.get("abo_9kva"), offre.get("abo_12kva")
        e9 = round(a9 - a6, 2) if (a6 and a9) else defaut9
        e12 = round(a12 - a6, 2) if (a6 and a12) else defaut12
        return e9, e12

    edf = tarifs.get("edf", {})
    ref = {
        "base": ecarts(edf.get("base", {}), 18.6, 44.4),
        "hchp": ecarts(edf.get("hchp", {}), 21.0, 48.0),
        "pointe": ecarts(edf.get("tempo", {}), 22.0, 50.0),
    }
    print("📐 Écarts kVA de référence (EDF) : "
          + " · ".join(f"{k} +{v[0]}/+{v[1]} €/an" for k, v in ref.items()))

    grilles_edf = {("edf", "base"), ("edf", "hchp"), ("edf", "tempo")}
    n = 0
    for fourn, offres in tarifs.items():
        if fourn in ("meta", "energies") or not isinstance(offres, dict):
            continue
        for nom, offre in offres.items():
            if not isinstance(offre, dict) or "abo_6kva" not in offre:
                continue
            if (fourn, nom) in grilles_edf:
                continue
            if any(k in offre for k in ("rouge_hp", "peak_hp", "kwh_pointe")):
                cat = "pointe"
            elif "kwh_hc" in offre:
                cat = "hchp"
            else:
                cat = "base"
            e9, e12 = ref[cat]
            offre["abo_9kva"] = round(offre["abo_6kva"] + e9, 2)
            offre["abo_12kva"] = round(offre["abo_6kva"] + e12, 2)
            n += 1
    return n


# ── Programme principal ───────────────────────────────────────────────────────
def main():
    print(f"🔄 Mise à jour annuelle des tarifs — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    current = load_current(TARIFS_FILE)
    print(f"📂 Tarifs actuels chargés (date : {current.get('meta', {}).get('date_maj', '?')})")

    try:
        recu = fetch_valeurs()
        tarifs, changes, rejets = fusionner(current, recu)

        # Garde-fou principal : sans tarif EDF Base valide, on n'écrit rien.
        edf_kwh = recu.get("edf", {}).get("base", {}).get("kwh")
        if not isinstance(edf_kwh, (int, float)) or not (0.15 <= edf_kwh <= 0.30):
            raise ValueError(f"kWh EDF Base invalide ou absent : {edf_kwh}")

        n = calculer_paliers_kva(tarifs)
        print(f"🔧 {n} offre(s) : abonnements 9/12 kVA recalculés")

        today = date.today()
        tarifs.setdefault("meta", {})
        tarifs["meta"]["date_maj"] = today.isoformat()
        tarifs["meta"]["source"] = "Mise à jour annuelle automatique (GitHub Actions + Anthropic API)"
        tarifs["meta"]["prochaine_revision_cre"] = prochaine_revision(today)
        tarifs.setdefault("energies", {})["date_maj"] = today.isoformat()

        print(f"📝 {len(changes)} valeur(s) modifiée(s)")
        for c in changes:
            print(f"   • {c}")
        if rejets:
            print(f"⚠️  {len(rejets)} valeur(s) conservée(s) à l'identique :")
            for r in rejets:
                print(f"   • {r}")

        save_tarifs(TARIFS_FILE, tarifs)
        print("✨ Mise à jour réussie !")

    except Exception as e:
        print(f"❌ Échec : {e}")
        print("⚠️  tarifs.json inchangé (valeurs précédentes conservées)")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
