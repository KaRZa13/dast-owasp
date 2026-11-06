# TP — DAST avec OWASP ZAP sur TIWAP — Compte rendu

**Entreprise fil rouge :** NOVA SERVICES — équipe sécurité
**Cible :** TIWAP (Flask + SQLite + MongoDB), déployée en local uniquement
**Outil :** OWASP ZAP 2.17.0 (`ghcr.io/zaproxy/zaproxy:stable`), Baseline Scan
**Date du scan :** 02/11/2026

## Livrables

| Livrable | Fichier |
|---|---|
| Fichier Compose modifié | `config/docker-compose.yml` |
| Captures montrant TIWAP en fonctionnement | `captures/01-tiwap-login.png`, `captures/02-tiwap-dashboard.png` |
| Rapports ZAP HTML / JSON (+ Markdown et sortie console) | `rapports-zap/zap-report.html`, `rapports-zap/zap-report.json`, `rapports-zap/zap-report.md`, `rapports-zap/zap-baseline-console.log` |
| Capture du rapport HTML | `captures/03-rapport-zap-html.png` |
| Workflow CI (GitHub Actions) | `config/github-dast-zap.yml` (à placer dans `.github/workflows/dast-zap.yml`) ; variante GitLab CI fournie : `config/.gitlab-ci.yml` + `config/docker-compose.ci.yml` |
| Tableau de qualification, analyse, fiches, indicateurs, conclusion | ce document (§3 à §8) |
| Script d'indicateurs à partir du JSON | `kpi_zap.py` |
| Captures du workflow GitHub Actions et de ses artefacts | `captures/04-github-run.png`, `captures/05-github-job-dast_zap.png`, `captures/06-github-artefacts.png` (voir §6.3) |

---

## 1. Déploiement de TIWAP (Partie 1)

```bash
git clone https://github.com/tombstoneghost/TIWAP.git && cd TIWAP
docker compose config --services     # -> db, app (+ zap après la Partie 2)
```

Modifications apportées au `docker-compose.yml` :

- `app` : `ports: ["127.0.0.1:5000:5000"]`. Le port n'est plus exposé que sur la boucle locale (vérifié avec `ss -ltn` : `127.0.0.1:5000`).
- `db` : la section `ports` (27017) est supprimée. TIWAP joint MongoDB par le nom de service `db` sur le réseau Compose.
- L'attribut obsolète `version: "2"` est retiré : Compose v2 l'ignore et affichait un avertissement.
- Ajout du service `zap` (Partie 2).

```bash
docker compose up -d --build
docker compose ps
# tiwap-app-1  Up  127.0.0.1:5000->5000/tcp
# tiwap-db-1   Up  27017/tcp            <- non publié sur l'hôte
# tiwap-zap-1  Up  (sleep infinity)
```

> **Écart par rapport à l'énoncé : TIWAP est servi en HTTPS, pas en HTTP.**
> `app.py` lance `app.run(..., debug=True, ssl_context=('certificate/server.crt', 'certificate/server.key'))`.
> `http://localhost:5000` ne répond donc pas (`curl` → code 000). L'URL à utiliser est **`https://localhost:5000`** (certificat auto-signé à accepter dans le navigateur).
> La cible ZAP devient **`https://app:5000`**. Le Baseline Scan accepte les certificats auto-signés.

Vérification : `GET https://localhost:5000/` → 200. Connexion `admin / admin` → 302 vers `/dashboard` (capture `02-tiwap-dashboard.png`).

**Q1 — Pourquoi démarrer et vérifier l'application avant ZAP ?**
Le DAST teste une application *en fonctionnement*. Si l'application ne répond pas, est encore en démarrage ou renvoie des erreurs, le spider n'explore rien et le rapport est vide ou faussé. On risque alors de conclure à tort qu'il n'y a « pas de vulnérabilité ». La vérification valide aussi l'URL cible (ici HTTPS et non HTTP) et le réseau entre les conteneurs (`curl` depuis le conteneur ZAP vers `https://app:5000` → 200).

**Q2 — Pourquoi ne pas exposer MongoDB à l'hôte ?**
La base contient des données volontairement vulnérables. Ses identifiants sont codés en dur (`username/password` dans le Compose et dans `helper/mongodb_manager.py`). Publier 27017 (sur `0.0.0.0` par défaut) la rendrait joignable depuis le réseau local de la machine, voire au-delà. L'application n'en a pas besoin : elle passe par le réseau interne Compose. C'est le principe de moindre exposition : on réduit la surface d'attaque du laboratoire.

## 2. ZAP dans Compose et scan (Parties 2 et 3)

Service ajouté (tel que fourni dans l'énoncé) : image `ghcr.io/zaproxy/zaproxy:stable`, montage `./reports:/zap/wrk/:rw`, `entrypoint: ["sleep", "infinity"]`. Le dossier `reports/` a été créé et rendu inscriptible pour l'utilisateur `zap` (uid 1000) du conteneur.

```bash
docker compose exec zap zap-baseline.py \
  -t https://app:5000 -m 2 \
  -r zap-report.html -J zap-report.json -w zap-report.md
```

Note : les chemins de rapport sont relatifs à `/zap/wrk`. Écrire `-r /zap/wrk/zap-report.html` comme dans l'énoncé donne le même résultat.

Résultat (durée réelle ≈ 36 s, code retour 2 = WARN) :

```
FAIL-NEW: 0  FAIL-INPROG: 0  WARN-NEW: 15  WARN-INPROG: 0  INFO: 0  IGNORE: 0  PASS: 53
```

Synthèse du rapport HTML : **0 High, 4 Medium, 8 Low, 5 Informational** (17 types d'alertes, 45 instances, 10 endpoints découverts).

**Surface réellement explorée :** `/`, `/login` (POST), `/robots.txt`, `/sitemap.xml`, `/index.css`, les ressources du débogueur Werkzeug, et des chemins de fichiers sources lus dans une trace d'erreur. **Aucune des 22 pages vulnérables de TIWAP n'a été atteinte.** Elles sont toutes protégées par le décorateur `@is_logged`, et le scan n'était pas authentifié.

## 3. Interprétation des résultats (Partie 4)

### 3.1 Alertes relevées (extrait du rapport JSON)

| Règle | Alerte | Risque (confiance) ZAP | URL / preuve |
|---|---|---|---|
| 10099 | Source Code Disclosure - SQL | Medium (Medium) | `POST /login` — preuve : `SELECT username, password FROM users WHERE username` |
| 90022 | Application Error Disclosure | Low (Medium) | `POST /login` — `HTTP/1.0 500 INTERNAL SERVER ERROR` |
| 10027 | Information Disclosure - Suspicious Comments | Info (Medium) | `POST /login` — trace Python complète dans un commentaire HTML ; `debugger.js` |
| 10202 | Absence of Anti-CSRF Tokens | Medium (Low) | `GET /` — `<form method="post" action="/login">` |
| 10038 | Content Security Policy Header Not Set | Medium (High) | `/`, `/sitemap.xml`, … |
| 10020 | Missing Anti-clickjacking Header | Medium (Medium) | `GET /` — pas de `X-Frame-Options` ni de `frame-ancestors` |
| 10036 | Server Leaks Version Information | Low (High) | `Server: Werkzeug/2.0.3 Python/3.6.15` |
| 10035 | Strict-Transport-Security Header Not Set | Low (High) | toutes les réponses HTTPS |
| 10021 | X-Content-Type-Options Header Missing | Low (Medium) | `/`, `/index.css`, `/robots.txt`, … |
| 10063 | Permissions Policy Header Not Set | Low (Medium) | `/`, … |
| 90004 | Cross-Origin-{Embedder,Opener,Resource}-Policy manquants | Low (Medium) | `/`, `/index.css`, … |
| 10111 | Authentication Request Identified | Info (High) | `POST /login` (paramètres `username` / `password`) |
| 10109 | Modern Web Application | Info (Medium) | `/` |
| 10015 / 10049 | Cache-control / Storable and Cacheable Content | Info | `/robots.txt`, ressources statiques |

### 3.2 Vérifications manuelles effectuées (sur le labo uniquement)

1. **Erreur 500 sur `/login`** — reproduite avec `curl -k -d 'username=ZAP&password=ZAP' https://localhost:5000/login` → **500**, page « TypeError: 'NoneType' object is not subscriptable // Werkzeug Debugger ».
   Cause dans le code (`helper/db_manager.py:40-45`) : pour un utilisateur inconnu, `fetchone()` renvoie `None` et `data[1]` lève une exception. Comme l'application tourne avec `debug=True`, Werkzeug affiche la trace complète avec le code source. C'est ce code que ZAP a pris pour une « fuite de code SQL ».
2. **Console de débogage** — `GET https://localhost:5000/console` → **200**. La console Werkzeug est exposée, protégée seulement par un PIN (le PIN apparaît aussi dans les logs du conteneur). Je ne l'ai pas exploitée.
3. **En-têtes** — `curl -kI https://localhost:5000/` ne renvoie que `Content-Type`, `Content-Length`, `Server`, `Date`. Les en-têtes de sécurité sont donc bien absents : le constat est confirmé.
4. **Injection SQL (contrôle croisé SAST/DAST)** — voir §3.5.

### 3.3 Tableau de qualification

| Alerte constatée | Risque indiqué | Vérification nécessaire | Résultat de la vérification | Action envisagée |
|---|---|---|---|---|
| **10099 Source Code Disclosure - SQL** + **90022 Application Error Disclosure** (`POST /login`) | Medium / Low | Rejouer la requête, lire la réponse, remonter au code | **Confirmé, mais requalifié.** Ce n'est pas une injection SQL : la requête de login est paramétrée (`WHERE username = ?`). Le vrai défaut est double : (1) exception non gérée pour un utilisateur inconnu, qui permet aussi d'énumérer les comptes (500 si le compte n'existe pas, « Invalid Credentials » s'il existe) ; (2) **mode debug Werkzeug actif en exposition réseau** : divulgation de code et de chemins, et console `/console` joignable (exécution de code à distance si le PIN est obtenu). | **Corriger** : `debug=False` / serveur WSGI de production, gestionnaire d'erreurs générique, `if data is None: return False`. Risque réel **supérieur** au « Medium » de ZAP. |
| **10038 CSP Header Not Set** (+ 10020 anti-clickjacking, 10021 nosniff) | Medium / Medium / Low | Examiner les réponses : en-têtes réellement absents ? Contenu dynamique réfléchi ? | **Confirmé** par `curl -I` : aucun en-tête de sécurité. Gravité dépendante du contexte : TIWAP contient des XSS (réfléchie, stockée, DOM) que la CSP limiterait. | **Corriger** au niveau du reverse proxy ou de l'application (`Content-Security-Policy`, `X-Frame-Options: DENY` / `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`). Vérifier par un nouveau scan : les règles 10038/10020/10021 doivent passer en PASS. |
| **10202 Absence of Anti-CSRF Tokens** (formulaire de login) | Medium (confiance Low) | Déterminer si le risque est exploitable : quelle action le formulaire déclenche-t-il ? Cookie `SameSite` ? | **Vrai positif technique, impact faible sur ce formulaire.** Un CSRF sur le login (« login CSRF ») a un impact limité. En revanche, TIWAP contient une page CSRF dédiée (`/csrf`, changement de mot de passe) que le scan n'a pas vue. | **Corriger globalement** (Flask-WTF `CSRFProtect`, cookie `SameSite=Lax`). Sur le login seul, priorité faible. |
| **10036 Server Leaks Version** (`Werkzeug/2.0.3 Python/3.6.15`) | Low (High) | Confirmer la version et vérifier les CVE associées | **Confirmé.** Python 3.6 n'est plus maintenu (fin de vie 12/2021), Werkzeug 2.0.3 non plus. La fuite de version facilite le ciblage. | Masquer l'en-tête **et surtout mettre à jour** la pile (image de base, Flask/Werkzeug). |
| **10035 HSTS Not Set** | Low (High) | L'application est-elle exposée en HTTPS à des utilisateurs non fiables ? | Confirmé techniquement. Non pertinent tant que le labo reste sur `127.0.0.1` avec un certificat auto-signé. | **Justifier / accepter** pour le labo. **Corriger** pour toute application NOVA exposée (`Strict-Transport-Security: max-age=31536000; includeSubDomains`). |
| **10111 / 10109 / 10015 / 10049** | Informational | — | Observations de contexte, pas des vulnérabilités. | Aucune action, sinon documenter. |

### 3.4 Analyse : pourquoi une alerte doit être vérifiée (exemple des en-têtes, §8.3)

Prenons **10038 « Content Security Policy Header Not Set »** sur `GET https://app:5000/` :

- **Réponse concernée** : la page de login (HTML) et les pages d'erreur 404. L'absence d'en-tête est une **observation directe** : `curl -I` le confirme, c'est un fait technique et non une supposition.
- **Utilisateurs non fiables ?** Dans le labo, non : l'application est sur `127.0.0.1`. Pour une application NOVA accessible aux clients, oui.
- **Risque** : sans CSP, une injection XSS s'exécute sans restriction (chargement de scripts externes, vol de session). La CSP ne corrige pas la XSS, c'est une défense en profondeur.
- **Correction** : au niveau du reverse proxy (nginx/Traefik, uniforme pour toutes les applications) ou dans l'application (`@app.after_request` / Flask-Talisman). La CSP doit être testée pour ne pas casser le chargement de Bootstrap depuis `cdn.jsdelivr.net`.
- **Vérification** : relancer le Baseline Scan et constater la disparition des règles 10038/10020/10021 (comparaison automatisable avec `kpi_zap.py ancien.json nouveau.json`).

Le cas inverse montre pourquoi la vérification est indispensable. **10099 « Source Code Disclosure - SQL »** laisse penser à un problème SQL, mais l'examen de la réponse et du code montre un problème différent (mode debug) et **plus grave** que le niveau Medium affiché. Le libellé et le niveau de ZAP sont un point de départ : ils ne remplacent pas la qualification. Il faut distinguer **l'observation technique** (une trace s'affiche) de la **gravité métier** (exécution de code possible via la console de debug sur une application exposée).

### 3.5 Lien avec l'injection SQL étudiée avec SonarQube

**Le Baseline Scan n'a détecté aucune injection SQL.** Pourtant, la vulnérabilité existe :

- **Côté code (SAST)** : `vulnerabilities/SQLi.py`, `sqli_low()` construit la requête par concaténation :
  `"SELECT userid, username FROM users WHERE username='%s' AND password='%s'" % (username, password)`. C'est exactement le type de constat que SonarQube remonte (règle d'injection SQL / taint analysis).
- **Test dynamique contrôlé** (manuel, authentifié, sur le labo) sur `POST /sql-injection` (niveau Low) :
  - `username=nobody` → `[]` (comportement normal) ;
  - `username=nobody'` → `unrecognized token` (erreur SQLite : l'entrée casse la requête) ;
  - `username=nobody' OR '1'='1' -- ` → renvoie **les 5 comptes** de la table `users`. **Injection confirmée.**
- **Pourquoi ZAP ne l'a pas vue** : (1) la page est derrière l'authentification et le scan n'était pas authentifié ; (2) le Baseline Scan est passif : il n'envoie pas de charges d'injection. Il faudrait un scan **authentifié et actif** (`zap-full-scan.py` avec un contexte et un utilisateur), réservé à un environnement autorisé.
- **Correction** : requêtes paramétrées (`cur.execute("... WHERE username=? AND password=?", (u, p))`), puis nouvelle analyse SonarQube **et** nouveau test dynamique.

Le croisement SAST et DAST donne la preuve complète : SAST localise la ligne fautive, le test dynamique démontre l'exploitabilité et l'impact. À l'inverse, le DAST a trouvé un problème (debug actif, configuration d'exécution) qu'une simple analyse des requêtes SQL n'aurait pas priorisé.

## 4. Fiches de traitement (Partie 5)

Hypothèse de contexte : l'analogue métier est le **portail client NOVA SERVICES** (gestion des clients et des prestations : données personnelles et contractuelles), exposé sur Internet derrière un reverse proxy. Barème d'échéance utilisé : Critique 7 j, Élevée 30 j, Moyenne 60 j, Faible 90 j.

### Fiche 1 — Mode debug actif / divulgation d'erreurs

| Champ | Valeur |
|---|---|
| Référence | ZAP 10099 + 90022 + 10027 — `POST /login` |
| Application | TIWAP (cible de laboratoire) |
| Actif métier analogue | Portail client NOVA SERVICES (Flask) |
| Impact | Confidentialité : code source, chemins, requêtes et énumération des comptes. Intégrité/disponibilité : la console Werkzeug permet d'exécuter du code sur le serveur si le PIN est obtenu, donc compromission complète. |
| Priorité | **Critique** — exposition Internet, exploitation simple (une requête suffit à provoquer la trace), impact maximal, aucune mesure compensatoire. Le « Medium » de ZAP est sous-évalué. |
| Responsable | Équipe de développement (code) + exploitation (configuration de déploiement) |
| Échéance | 09/11/2026 (J+7) |
| Action | `debug=False` et lancement par gunicorn/uwsgi ; gestionnaire d'erreurs 500 générique ; correction de `check_login` (`data is None`) et message d'erreur identique pour un compte inexistant ou un mauvais mot de passe. Contrôle en CI : refuser `debug=True` (règle SAST). |
| Vérification | `curl -k -d 'username=x&password=x' …/login` → page générique ; `GET /console` → 404 ; nouveau scan : 10099/90022 absents |
| Statut | Ouvert |

### Fiche 2 — Injection SQL (`/sql-injection`)

| Champ | Valeur |
|---|---|
| Référence | Non détectée par ZAP Baseline — constat SAST (SonarQube) + test manuel du 02/11/2026 |
| Application | TIWAP (cible de laboratoire) |
| Actif métier analogue | Recherche de clients / authentification du portail client |
| Impact | Lecture de toute la base (comptes, données clients), contournement d'authentification, modification possible des données |
| Priorité | **Critique** — vulnérabilité confirmée et exploitée en test, facile à exploiter, données sensibles. Atténuant : la page exige d'être authentifié (mais les comptes faibles comme admin/admin annulent cette protection). |
| Responsable | Équipe de développement |
| Échéance | 09/11/2026 (J+7) |
| Action | Requêtes paramétrées sur toutes les fonctions de `SQLi.py` ; compte SQL à privilèges minimaux ; revue des autres concaténations (blind SQLi, NoSQL) |
| Vérification | Revue de code + SonarQube sans issue ; rejouer les 3 tests du §3.5 (la tautologie ne doit plus rien renvoyer) ; scan ZAP actif authentifié en recette |
| Statut | Ouvert |

### Fiche 3 — En-têtes de sécurité absents (CSP, anti-clickjacking, nosniff, HSTS)

| Champ | Valeur |
|---|---|
| Référence | ZAP 10038, 10020, 10021, 10035, 10063, 90004 |
| Application | TIWAP (cible de laboratoire) |
| Actif métier analogue | Toutes les applications web NOVA derrière le reverse proxy commun |
| Impact | Défense en profondeur : aggrave une XSS, permet le clickjacking, le MIME sniffing et le déclassement HTTPS |
| Priorité | **Moyenne** — confirmé, mais pas exploitable seul ; la correction est mutualisable au niveau du proxy. Passe en **Élevée** pour une application qui contient des XSS confirmées. |
| Responsable | Exploitation (configuration du reverse proxy), validation sécurité |
| Échéance | 01/01/2027 (J+60) |
| Action | Ajouter les en-têtes au reverse proxy ; CSP d'abord en mode `Report-Only`, puis en mode bloquant |
| Vérification | Nouveau Baseline Scan : règles concernées en PASS ; `curl -I` |
| Statut | Ouvert |

### Fiche 4 — Version serveur divulguée / pile obsolète

| Champ | Valeur |
|---|---|
| Référence | ZAP 10036 — `Server: Werkzeug/2.0.3 Python/3.6.15` |
| Actif métier analogue | Images Docker de base des applications Python NOVA |
| Impact | Facilite le ciblage d'exploits ; la pile est en fin de vie (aucun correctif de sécurité) |
| Priorité | **Faible** pour l'en-tête seul, **Élevée** pour la mise à jour de la pile (Python 3.6 en fin de vie) |
| Responsable | Développement (dépendances) + exploitation (images) |
| Échéance | En-tête 31/01/2027 ; montée de version 02/12/2026 |
| Action | Masquer `Server` au proxy ; passer à une image Python maintenue et à Flask/Werkzeug récents ; scan SCA des dépendances |
| Vérification | Nouveau scan (10036 absent), rapport SCA |
| Statut | Ouvert |

## 5. Mini-tableau de bord (Partie 7)

Valeurs initiales mesurées le 02/11/2026 (1 application scannée, 1 scan).

| Indicateur | Définition / calcul | Source | Fréquence | Responsable | Décision permise | Valeur initiale |
|---|---|---|---|---|---|---|
| **Vulnérabilités confirmées ouvertes, par priorité** | Nombre de fiches au statut Ouvert ou En cours, par priorité (après qualification, pas les alertes brutes) | Registre de qualification / tickets | Hebdomadaire | RSSI / équipe sécurité | Réaffecter des ressources si les vulnérabilités critiques ne baissent pas | Critique 2, Élevée 1, Moyenne 1, Faible 1 |
| **Vulnérabilités prioritaires hors délai** | Nombre de fiches Critique/Élevée dont l'échéance est dépassée et le statut différent de Corrigé | Tickets (date d'échéance) | Hebdomadaire | Responsables d'équipe | Escalade à la direction, acceptation de risque formelle ou blocage de la mise en production | 0 (échéances au 09/11) |
| **Délai médian de correction (MTTR)** | Médiane de (date de vérification de la correction − date de détection), par priorité | Tickets | Mensuelle | Équipe sécurité | Ajuster les SLA, investir dans l'outillage ou la formation | n/a (aucune correction encore) |
| **% de corrections vérifiées par un nouveau scan** | Corrections confirmées par un nouveau scan ou test ÷ corrections déclarées | Tickets + comparaison des JSON (`kpi_zap.py ancien nouveau`) | Mensuelle | Équipe sécurité | Refuser la clôture des tickets sans preuve ; détecter les corrections inefficaces | n/a |
| **% d'applications critiques couvertes par le DAST** | Applications critiques avec au moins un scan DAST réussi sur les 30 derniers jours ÷ applications critiques du référentiel | Artefacts CI + CMDB | Mensuelle | RSSI | Prioriser l'intégration du job DAST dans les pipelines manquants | 1 application de labo (TIWAP) |
| **Taux d'échec technique des scans** | Jobs `dast_zap` en erreur (code 3 / timeout) ÷ jobs lancés | GitHub Actions (historique des runs) | Hebdomadaire | Exploitation / DevOps | Fiabiliser les runners ; un scan en échec ne doit pas être pris pour un scan sans alerte | 0 % (1 scan local + 1 simulation CI réussis) |
| **Couverture d'exploration** (complémentaire) | Endpoints découverts par le spider ÷ endpoints connus (routes Flask) | Rapport ZAP (*Insights*) + inventaire des routes | À chaque scan | Équipe sécurité | Décider d'un scan authentifié ou de compléter le spider | **10 endpoints découverts sur 34 routes** : couverture faible, scan authentifié nécessaire |

> Le nombre d'alertes n'est pas une mesure du niveau de sécurité. On l'a constaté directement : deux scans identiques (local puis simulation CI) donnent 17 puis 18 types d'alertes (`10049-1 Non-Storable Content` en plus) sans aucun changement de code. Un scan authentifié ferait grimper le total parce que la couverture augmente, pas parce que la sécurité se dégrade.

## 6. Intégration CI avec GitHub Actions (Partie 6)

L'énoncé laisse le choix entre GitLab CI et GitHub Actions. Le contrôle est automatisé avec **GitHub Actions**, dans un dépôt GitHub **privé**.

### 6.1 Fichiers

- `.github/workflows/dast-zap.yml` — workflow « DAST - OWASP ZAP baseline », job `dast_zap` sur `ubuntu-latest`.
  - **Déclencheurs** : `push` limité aux changements de code pertinents (`app.py`, `helper/**`, `vulnerabilities/**`, `templates/**`, `Static/**`, `requirements.txt`, `Dockerfile`, `docker-compose*.yml`, le workflow lui-même) ; `workflow_dispatch` (lancement manuel) ; `schedule` hebdomadaire (lundi 03:00 UTC) pour détecter les régressions sans changement de code.
  - **Étapes** :
    1. `actions/checkout@v4` ;
    2. `docker compose up -d --build app db zap`, avec le Compose du labo inchangé : Docker est natif sur le runner, les montages fonctionnent ;
    3. attente de TIWAP depuis le conteneur ZAP (`curl -k https://app:5000/`, jusqu'à 5 min) ;
    4. `zap-baseline.py -t https://app:5000 -m 2 -r zap-report.html -J zap-report.json -w zap-report.md` ;
    5. publication de `reports/` avec `actions/upload-artifact@v4` (artefact `zap-reports`, conservé 30 jours, `if: always()`) ;
    6. `docker compose down -v` (`if: always()`).
  - **Sécurité du workflow** : `permissions: contents: read` (jeton en lecture seule) et `timeout-minutes: 30`.
- `.gitignore` : ajout de `reports/`. Les rapports sont conservés comme artefacts, pas commités.
- **Politique de blocage** : les alertes (codes retour 1 et 2) **ne bloquent pas** le workflow, car elles doivent d'abord être qualifiées. Seule une erreur technique (code ≥ 3) fait échouer le job. Une évolution possible est de bloquer sur une liste de règles confirmées via un fichier de configuration `-c` (règles en FAIL).

Variante GitLab CI, fournie à titre de comparaison : `.gitlab-ci.yml` (job `dast_zap` en Docker-in-Docker) et `docker-compose.ci.yml`. Cette surcharge neutralise les montages *bind* (`!reset []`), qui seraient vides avec un service `dind` ; les rapports sont alors récupérés par `docker compose cp`. Elle n'est pas nécessaire sur GitHub Actions.

### 6.2 Validation

- La séquence du workflow (Compose du labo, attente, `zap-baseline.py` vers `https://app:5000`, rapports dans `reports/`) est celle qui a été exécutée localement au §2 : scan réussi, code retour 2 (WARN).
- Le workflow s'exécute sur GitHub au push : voir les captures `04` à `06`.

### 6.3 Mise en place et captures

```bash
cd TIWAP
git remote add perso git@github.com:<votre-compte>/tiwap-dast.git   # dépôt PRIVÉ (pas un fork)
git add docker-compose.yml docker-compose.ci.yml .gitlab-ci.yml .gitignore .github/
git commit -m "TP DAST : Compose de labo + workflow ZAP baseline"
git push perso HEAD:main
```

Le dépôt est créé vide et **privé**, et non comme un fork : sur GitHub, un fork d'un dépôt public reste public, ce qui reviendrait à publier l'application vulnérable. `TIWAP.db`, modifié par l'application au démarrage, n'est pas commité.

Captures réalisées :

1. **Actions** → run « DAST - OWASP ZAP baseline » : statut vert et job `dast_zap` (`04-github-run.png`).
2. Job `dast_zap` → étape **Scan de référence ZAP** dépliée : ligne `FAIL-NEW: 0 … WARN-NEW: …` et `Code retour ZAP : 2` (`05-github-job-dast_zap.png`).
3. Page de synthèse du run → section **Artifacts** : artefact `zap-reports` téléchargeable (`06-github-artefacts.png`).

### 6.4 Limites

- Le rapport HTML/JSON est seulement conservé en artefact, pour 30 jours. Il n'est **pas** intégré à l'onglet **Security > Code scanning** de GitHub, qui attend un rapport SARIF (`github/codeql-action/upload-sarif`). Il faudrait convertir le JSON ZAP en SARIF, ou utiliser l'action officielle `zaproxy/action-baseline`, qui ouvre une *issue* récapitulative. Sur un dépôt privé, le Code scanning demande aussi une licence GitHub Advanced Security.
- Les minutes d'Actions sont limitées sur les dépôts privés (quota du forfait gratuit) : il faut garder le filtre `paths` et la planification hebdomadaire plutôt qu'un scan à chaque commit.
- Le scan en CI reste non authentifié et passif : mêmes angles morts qu'en local (§3.5).

## 7. Questions de compréhension

1. **SAST vs DAST** — Le SAST analyse le code source sans l'exécuter (« boîte blanche »). Il localise précisément la ligne fautive, mais produit des faux positifs et ignore la configuration d'exécution. Le DAST teste l'application en fonctionnement par HTTP (« boîte noire »). Il voit ce qu'un attaquant voit (en-têtes, erreurs, configuration réelle, mode debug), mais seulement sur la surface qu'il atteint, et sans localiser le code.
2. **Pourquoi une application en fonctionnement ?** ZAP n'a pas accès au code : il observe des requêtes et des réponses. Sans application qui répond, il n'y a rien à explorer ni à analyser. De plus, certains défauts n'existent qu'à l'exécution (ici `debug=True`, les en-têtes absents, le serveur Werkzeug exposé).
3. **Pourquoi `app:5000` depuis le conteneur ?** Compose crée un réseau où chaque service est résolu par son nom (DNS interne). Dans le conteneur ZAP, `localhost` désigne ZAP lui-même. Ici, il faut en plus `https://`, car TIWAP sert en TLS.
4. **Passif vs actif** — Le passif analyse les échanges observés pendant l'exploration, sans charges malveillantes : sans risque pour la cible. L'actif envoie des requêtes d'attaque (injections, traversées de répertoires…) : il trouve plus de choses mais peut modifier ou supprimer des données et perturber le service. Il est réservé à un périmètre autorisé et préparé.
5. **Pourquoi le Baseline Scan ne garantit pas la détection d'une injection SQL ?** Il n'injecte rien. Il ne peut repérer que des indices dans des réponses (messages d'erreur SQL) que le spider aurait provoqués par hasard. Ici, la page vulnérable était en plus derrière l'authentification : la SQLi, confirmée manuellement, n'apparaît pas dans le rapport.
6. **Alerte vs vulnérabilité confirmée** — Une alerte est une observation automatique avec un niveau de confiance. Une vulnérabilité confirmée a été reproduite, son exploitabilité et son impact ont été évalués dans le contexte. Exemple : l'alerte « Source Code Disclosure - SQL » a été requalifiée en « mode debug exposé », plus grave.
7. **Prioriser une alerte sur une application critique** — Partir de l'alerte confirmée, puis croiser criticité des données, exposition (Internet ou interne), impact sur la confidentialité, l'intégrité et la disponibilité, facilité d'exploitation, mesures compensatoires (WAF, authentification) et coût de correction. Le risque ZAP n'est qu'une donnée d'entrée (cf. fiches §4).
8. **Pourquoi conserver les rapports en CI ?** Pour la traçabilité et l'audit (preuve du contrôle à chaque version), la comparaison entre scans (régressions, vérification des corrections), le calcul des indicateurs, et l'accès de l'équipe sans relancer le scan. L'artefact garde la version exacte associée au commit.
9. **Éviter de publier l'application vulnérable** — Lier les ports à `127.0.0.1`, ne pas publier la base, utiliser un dépôt et un projet CI **privés**, des runners éphémères sans exposition (`docker compose down -v` en fin de job), ne jamais déployer via un pipeline de production, et bannir les vrais secrets et données personnelles du labo.
10. **Indicateurs d'efficacité de la correction** — Délai médian de correction par priorité, vulnérabilités prioritaires hors délai, % de corrections vérifiées par un nouveau scan, taux de réouverture (régressions), stock de vulnérabilités confirmées ouvertes (cf. §5).

## 8. Conclusion — limites du DAST et complémentarité avec le SAST

Le Baseline Scan a fourni en 36 secondes un premier état réel de la configuration d'exécution de TIWAP. Il a révélé un **défaut critique** qu'une analyse purement statique des requêtes n'aurait pas priorisé : mode debug Werkzeug exposé, traces avec code source, console `/console` joignable. Il a aussi relevé l'absence générale des en-têtes de sécurité et une pile logicielle obsolète.

Ses limites sont aussi nettes. Sur les 22 vulnérabilités documentées de TIWAP, **aucune n'a été trouvée directement** : scan passif, non authentifié, 10 endpoints atteints sur 34 routes. **Aucune injection SQL n'a été détectée**, alors qu'elle est confirmée par l'analyse du code (SAST) et par un test manuel contrôlé. Les libellés et niveaux de ZAP doivent être requalifiés : un « Medium » s'est révélé critique, plusieurs alertes ne sont que du contexte, et deux scans identiques ne donnent pas exactement le même total.

Pour NOVA SERVICES, les deux approches sont complémentaires. Le SAST trouve et localise les défauts dans le code. Le DAST valide le comportement réel et la configuration de déploiement. L'étape suivante est un scan **authentifié** puis **actif** en recette, avec un contexte ZAP. La valeur ne vient pas de l'outil seul mais du processus : détecter, qualifier, prioriser selon le risque métier, corriger, puis vérifier par un nouveau scan, et piloter ce processus avec des indicateurs centrés sur les vulnérabilités confirmées plutôt que sur le nombre d'alertes.

## 9. Nettoyage

```bash
docker compose down        # fait : tiwap-app, tiwap-db, tiwap-zap supprimés
docker compose ps          # vide
```

Les rapports sont conservés dans `livrables/rapports-zap/`. Il n'y a pas de volume nommé, mais l'image `mongo:4.4` crée des volumes **anonymes** (`/data/db`, `/data/configdb`) que `docker compose down` laisse en place (`docker volume ls`). Ils ne contiennent que les données de labo, réinitialisées à chaque démarrage : `docker compose down -v` les supprime si on n'en a plus besoin. Les images (`tiwap-app`, `mongo:4.4`, `zaproxy`, `python:3.6`) sont conservées localement, à supprimer si nécessaire avec `docker image rm`.
