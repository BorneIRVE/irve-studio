#!/usr/bin/env python3
"""
update_tarifs.py
Mis à jour automatique des tarifs électricité France via Anthropic API + web search.
Exécuté par GitHub Actions 2x/an (1er février et 1er août) + le 1er de chaque mois.
"""

import os
import json
import anthropic
from datetime import datetime
from pathlib import Path

# ── Configuration ─────────────────────────────────────────────────────────────
TARIFS_FILE = Path(__file__).parent / "tarifs.json"
MODEL = "claude-sonnet-4-6"

import time

# Schéma JSON attendu pour chaque fournisseur (traité séparément pour rester sous la limite de débit)
FOURNISSEURS = {
    "edf": """{
  "base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "tempo": { "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "bleu_hc": X.XXXX, "bleu_hp": X.XXXX, "blanc_hc": X.XXXX, "blanc_hp": X.XXXX, "rouge_hc": X.XXXX, "rouge_hp": X.XXXX, "jours_rouge": 22, "jours_blanc": 43, "jours_bleu": 300 },
  "ejp": { "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "kwh_normal": X.XXXX, "kwh_pointe": X.XXXX, "jours_pointe": 22 },
  "zen_fixe": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "engie": """{
  "base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "totalenergies": """{
  "heures_eco_base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "heures_eco_hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "heures_eco_plus": { "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "eco_hc": X.XXXX, "eco_hp": X.XXXX, "peak_hc": X.XXXX, "peak_hp": X.XXXX, "jours_peak": 20 },
  "fixe_2ans": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "ohm": """{
  "base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "mint": """{
  "base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "primeo": """{
  "confort_plus": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "octopus": """{
  "go": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX },
  "intelligent": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "bonus_ve": 0.12 },
  "drive_pack": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "forfait_ve": XX.XX }
}""",
    "ekwateur": """{
  "hchp": { "kwh_hc": X.XXXX, "kwh_hp": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "ilek": """{
  "base": { "kwh": X.XXXX, "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX }
}""",
    "eni": """{
  "agile": { "abo_6kva": XXX.XX, "abo_9kva": XXX.XX, "abo_12kva": XXX.XX, "eco_hc": X.XXXX, "eco_hp": X.XXXX, "peak_hc": X.XXXX, "peak_hp": X.XXXX, "jours_peak": 22 }
}""",
}

def prompt_fournisseur(nom: str, schema: str, actuel: dict) -> str:
    return f"""Tu es un expert en tarifs d'électricité en France. Recherche sur le web les tarifs
actuellement en vigueur du fournisseur "{nom}" et retourne UNIQUEMENT un objet JSON valide
(sans markdown, sans texte autour).

Sources : fournisseurs-electricite.com, kelwatt.fr, jechange.fr, hellowatt.fr, site officiel du fournisseur.

Pour CHAQUE offre, renseigne les abonnements annuels aux 3 puissances 6, 9 et 12 kVA
(abo_6kva, abo_9kva, abo_12kva). Si tu ne trouves pas la valeur 9 ou 12 kVA exacte, applique au
tarif 6 kVA le même écart que celui observé chez EDF (environ +18,60 €/an pour 9 kVA, +44,40 €/an pour 12 kVA).

Structure JSON attendue (valeurs en float €/kWh ou €/an) :
{schema}

Valeurs actuelles (à conserver si tu ne trouves pas mieux) :
{json.dumps(actuel, ensure_ascii=False)}

Réponds UNIQUEMENT avec le JSON. Aucun texte avant ou après."""

def load_current(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def fetch_un_fournisseur(client, nom, schema, actuel_fourn):
    """Récupère les tarifs d'UN fournisseur (petit appel, sous la limite de débit)."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": prompt_fournisseur(nom, schema, actuel_fourn)}]
    )
    text_blocks = [b.text for b in response.content if getattr(b, "type", None) == "text"]
    raw = "\n".join(text_blocks).strip().replace("```json", "").replace("```", "").strip()
    if "{" in raw and "}" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    if not raw:
        raise ValueError(f"{nom}: réponse vide (stop_reason={response.stop_reason})")
    return json.loads(raw)

def fetch_tarifs(current: dict) -> dict:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resultat = {"meta": dict(current.get("meta", {}))}

    noms = list(FOURNISSEURS.keys())
    for i, nom in enumerate(noms):
        print(f"📡 [{i+1}/{len(noms)}] {nom}...", end=" ", flush=True)
        try:
            data = fetch_un_fournisseur(client, nom, FOURNISSEURS[nom], current.get(nom, {}))
            resultat[nom] = data
            print("OK")
        except Exception as e:
            # En cas d'échec sur un fournisseur, on conserve ses valeurs actuelles
            print(f"échec ({e}) — valeurs actuelles conservées")
            resultat[nom] = current.get(nom, {})
        # Pause entre fournisseurs pour rester sous 30 000 tokens/minute
        if i < len(noms) - 1:
            time.sleep(20)

    return resultat

def completer_abonnements(tarifs: dict) -> dict:
    """Filet de sécurité : complète tout abo_9kva/abo_12kva manquant
    via l'écart réglementé (TURPE) observé chez EDF, identique pour tous les fournisseurs."""
    edf_base = tarifs.get("edf", {}).get("base", {})
    a6 = edf_base.get("abo_6kva")
    a9 = edf_base.get("abo_9kva")
    a12 = edf_base.get("abo_12kva")
    # Écarts réglementés de référence (fallback si EDF incomplet : valeurs TURPE usuelles)
    ecart_9 = round(a9 - a6, 2) if (a6 and a9) else 18.6
    ecart_12 = round(a12 - a6, 2) if (a6 and a12) else 44.4
    print(f"📐 Écarts kVA de référence : 6→9 = +{ecart_9} €/an, 6→12 = +{ecart_12} €/an")

    completes = 0
    for fourn, offres in tarifs.items():
        if fourn == "meta" or not isinstance(offres, dict):
            continue
        for nom_offre, offre in offres.items():
            if not isinstance(offre, dict) or "abo_6kva" not in offre:
                continue
            base6 = offre["abo_6kva"]
            if "abo_9kva" not in offre or not offre["abo_9kva"]:
                offre["abo_9kva"] = round(base6 + ecart_9, 2)
                completes += 1
            if "abo_12kva" not in offre or not offre["abo_12kva"]:
                offre["abo_12kva"] = round(base6 + ecart_12, 2)
                completes += 1
    if completes:
        print(f"🔧 {completes} abonnement(s) 9/12 kVA complété(s) via l'écart réglementé")
    return tarifs

def save_tarifs(path: Path, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✅ tarifs.json mis à jour : {path}")

def main():
    print(f"🔄 Mise à jour des tarifs - {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # Charger les tarifs actuels (fallback si l'API échoue)
    current = load_current(TARIFS_FILE)
    print(f"📂 Tarifs actuels chargés (date : {current['meta']['date_maj']})")

    try:
        new_tarifs = fetch_tarifs(current)

        # Filet de sécurité : compléter les abonnements 9/12 kVA manquants
        new_tarifs = completer_abonnements(new_tarifs)

        # Validation de cohérence : le kWh EDF Base doit être plausible
        edf_kwh = new_tarifs.get("edf", {}).get("base", {}).get("kwh", 0)
        if not (0.15 <= edf_kwh <= 0.30):
            raise ValueError(f"kWh EDF base incohérent : {edf_kwh} (attendu entre 0.15 et 0.30)")

        # Mettre à jour la date
        new_tarifs["meta"]["date_maj"] = datetime.now().strftime("%Y-%m-%d")

        # Comparer quelques valeurs clés pour log
        old_edf = current["edf"]["base"]["kwh"]
        new_edf = new_tarifs["edf"]["base"]["kwh"]
        if old_edf != new_edf:
            print(f"📊 EDF Base : {old_edf} → {new_edf} €/kWh")
        else:
            print(f"📊 EDF Base : inchangé ({new_edf} €/kWh)")

        save_tarifs(TARIFS_FILE, new_tarifs)
        print("✨ Mise à jour réussie !")

    except json.JSONDecodeError as e:
        print(f"❌ Erreur JSON : {e}")
        print("⚠️  Tarifs inchangés (conservation des valeurs actuelles)")
        raise SystemExit(1)
    except ValueError as e:
        print(f"❌ Validation échouée : {e}")
        print("⚠️  Tarifs inchangés (conservation des valeurs actuelles)")
        raise SystemExit(1)
    except Exception as e:
        print(f"❌ Erreur inattendue : {e}")
        print("⚠️  Tarifs inchangés (conservation des valeurs actuelles)")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
