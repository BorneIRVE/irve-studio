# ⚡ IRVE Studio — Guide de déploiement

## Fichiers du projet

```
├── index.html          ← Configurateur complet (à mettre en ligne)
├── tarifs.json         ← Tarifs mis à jour automatiquement chaque mois
├── catalogue.json      ← Catalogue de bornes (modifiable via panneau Admin)
├── update_tarifs.py    ← Script de mise à jour des tarifs (GitHub Actions)
└── .github/
    └── workflows/
        └── update-tarifs.yml  ← Robot planifié (1x/mois)
```

---

## Déploiement pas à pas

### Étape 1 — Créer le repository GitHub
1. Aller sur [github.com](https://github.com) → **New repository**
2. Nom : `irve-studio` (ou ce que tu veux)
3. Cocher **Public**
4. Cliquer **Create repository**

### Étape 2 — Uploader les fichiers
1. Dans le repository → **uploading an existing file**
2. Glisser-déposer les 4 fichiers : `index.html`, `tarifs.json`, `catalogue.json`, `update_tarifs.py`
3. Pour le dossier `.github/workflows/` :
   - Cliquer **Add file → Create new file**
   - Nommer `.github/workflows/update-tarifs.yml`
   - Coller le contenu du fichier
4. Cliquer **Commit changes**

### Étape 3 — Activer GitHub Pages
1. **Settings → Pages**
2. Source : **Deploy from a branch** → branch **main** → dossier **/ (root)**
3. Sauvegarder
4. Ton site sera sur : `https://TON-PSEUDO.github.io/irve-studio/`

### Étape 4 — Ajouter la clé API Anthropic
1. Créer une clé sur [console.anthropic.com](https://console.anthropic.com)
2. Dans GitHub → **Settings → Secrets and variables → Actions**
3. **New repository secret** : `ANTHROPIC_API_KEY` = ta clé
4. Tester : **Actions → Mise à jour automatique → Run workflow**

### Étape 5 — Personnaliser index.html
Remplacer dans le fichier `index.html` :
```
TON-PSEUDO  →  ton nom d'utilisateur GitHub (2 occurrences)
```

---

## Configuration EmailJS (envoi email auto)

1. Créer un compte gratuit sur [emailjs.com](https://emailjs.com)
2. Connecter ton adresse mail : **Email Services → Add Service**
3. Créer un template : **Email Templates → Create Template**
   - Activer l'option **Attachments** pour recevoir PDF + Word
   - Variables disponibles dans le template :
     - `{{client_nom}}` — Nom du client
     - `{{client_email}}` — Email du client
     - `{{client_tel}}` — Téléphone
     - `{{client_cp}}` — Code postal
     - `{{install_type}}` — Type d'installation
     - `{{nb_bornes}}` — Nombre de bornes
     - `{{borne_nom}}` — Borne recommandée
     - `{{borne_puissance}}` — Puissance
     - `{{devis_net}}` — Prix net TTC
     - `{{tarif_nom}}` — Meilleure offre tarifaire
     - `{{facture_an}}` — Facture annuelle estimée
     - `{{roi}}` — Retour sur investissement
     - `{{cout_100km}}` — Coût aux 100km
     - `{{date_etude}}` — Date de l'étude
     - `{{pdf_content}}` — Pièce jointe PDF (base64)
     - `{{docx_content}}` — Pièce jointe Word (base64)

4. Remplir les 4 constantes dans `index.html` :
```javascript
const EMAILJS_SERVICE  = 'service_xxxxxx';
const EMAILJS_TEMPLATE = 'template_xxxxxx';
const EMAILJS_KEY      = 'xxxxxxxxxxxxxxxxx';
const MON_EMAIL        = 'ton@email.fr';
```

---

## Panneau d'administration

Accessible via le bouton **⚙️ Admin** dans le header.
- Mot de passe par défaut : `irve2024` (à changer dès la mise en ligne)
- Permet de gérer : catalogue de bornes, tarifs de pose, tranchée, options
- Les données sont sauvegardées en localStorage sur le navigateur admin
- Bouton **Exporter JSON** pour récupérer le catalogue et le déposer sur GitHub

---

## Mise à jour des tarifs

| Déclencheur | Fréquence |
|-------------|-----------|
| Automatique | Le 1er de chaque mois |
| Révisions CRE | 1er février et 1er août |
| Manuelle | Actions → Run workflow |

Coût estimé : ~0,03 €/mois (1 appel API Anthropic)

---

## Intégration sur ton site

Une fois ton site créé, deux options :

**Option A — Lien direct GitHub Pages**
Intégrer le configurateur via un iframe ou un lien depuis ton site.

**Option B — Héberger sur ton domaine**
Copier `index.html` sur ton hébergeur. Le fichier chargera toujours `tarifs.json`
et `catalogue.json` depuis GitHub automatiquement.

```
https://raw.githubusercontent.com/TON-PSEUDO/irve-studio/main/tarifs.json
https://raw.githubusercontent.com/TON-PSEUDO/irve-studio/main/catalogue.json
```
