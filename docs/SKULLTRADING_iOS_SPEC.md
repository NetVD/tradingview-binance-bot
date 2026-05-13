# SkullTrading iOS — Spécification complète V1

> Document de spec destiné à être passé à Claude Code pour démarrer le projet.
> Source : conversation stratégique du 11 mai 2026.
> À lire en parallèle de `SKULLTRADING_INVENTORY.md` (l'inventaire du backend existant).

---

## 0. TL;DR exécutif

**Produit** : App iOS native Swift, marque SkullTrading. Reçoit les signaux de trading IA générés par l'agent Gekko (backend VPS existant), permet à l'utilisateur de visualiser les analyses, et — pour les utilisateurs qui le souhaitent — de connecter leur compte Binance et d'exécuter les trades depuis l'app après validation manuelle.

**Marché cible** : mondial (anglais + français en V1).

**Tiers de monétisation** (prix à figer plus tard) :

1. Free : disclaimers, onboarding, prix temps réel, aucun signal
2. Signals Global : signaux partagés (mêmes pour tous) + analyses Gekko basiques
3. Signals Pro : tier précédent + analyses Gekko détaillées (thèse complète, risques, key levels)
4. Personnalisé (tier le plus cher) : signaux + analyses adaptés aux préférences/historique de l'utilisateur

**Stack tech** :

- Frontend : SwiftUI iOS 17+, MVVM, Swift Charts, KeychainAccess, RevenueCat
- Backend Supabase : auth multi-user + DB users + RLS + Edge Functions pour proxy Binance + vault clés API
- **VPS-1 SkullTrading (existant, Infomaniak)** : reste **dédié à votre bot perso** + Gekko + dashboard interne. Aucune modification structurelle.
- **VPS-2 SkullTrading-App (NOUVEAU, Infomaniak)** : héberge le service commercial qui expose les endpoints `/api/v2/*` aux apps iOS. Communique avec VPS-1 via token service-to-service.
- Notifications : APNS via Supabase Edge Functions
- Paiements : Apple In-App Purchases (RevenueCat)

**Pourquoi 2 VPS séparés** : isolation totale entre votre trading perso (capital réel) et l'infra commerciale multi-user. Un crash de l'app ne touche pas votre bot. Sécurité renforcée, scalabilité indépendante.

**Durée estimée** : 11-14 semaines de dev en solo, découpée en 3 phases.

**Risque assumé** : possible rejet Apple Store (l'app place des trades sur Binance). Plan B prévu : si rejet, basculer en read-only et garder Binance pour V2 sur web companion.

---

## 1. Architecture cible

### 1.1 Vue d'ensemble

```
┌──────────────────────────────────────────────────────────────┐
│                    APP iOS — SkullTrading                    │
│  • SwiftUI iOS 17+                                           │
│  • Auth via Supabase (Sign in with Apple + email)            │
│  • Clé Binance : chiffrée localement → envoyée chiffrée à    │
│    Supabase → déchiffrée en mémoire côté Edge Function       │
│  • Push notifications signaux (APNS)                         │
│  • RevenueCat pour abonnements                               │
└──────────────────────────────────────────────────────────────┘
        ↕ HTTPS + JWT                       ↕ HTTPS + JWT
┌─────────────────────────────┐    ┌──────────────────────────────┐
│   SUPABASE                  │    │   VPS-2 SkullTrading-App     │
│   (cloud managé)            │    │   (Infomaniak — NOUVEAU)     │
│   ─────────────             │    │   ──────────────────────     │
│   • Auth (managée)          │    │   • FastAPI /api/v2/*        │
│   • DB users + abos         │    │   • Cache Redis signaux      │
│   • Vault clés Binance      │    │   • Rate limiting per user   │
│     (chiffrées AES-256)     │    │   • Postgres app             │
│   • Row Level Security      │    │     (logs accès, métriques)  │
│   • Edge Functions :        │    │   • Webhook receiver         │
│     - binance-proxy         │    │     (signaux depuis VPS-1)   │
│     - notify-subscribers    │    │   • api.skulltrading.com     │
└─────────────────────────────┘    └──────────────────────────────┘
              ↑                                  ↕
              │                          HTTPS + service token
              │                                  ↕
              │                    ┌──────────────────────────────┐
              └──── service ──────→│   VPS-1 SkullTrading         │
                       token       │   (Infomaniak — EXISTANT)    │
                                   │   ───────────────────────    │
                                   │   • Bot trading PERSO        │
                                   │   • Gekko (agents IA)        │
                                   │   • Dashboard interne        │
                                   │     (dashboard.skull...)     │
                                   │   • Postgres signaux         │
                                   │   • Webhook EMITTER          │
                                   │     (push signaux vers VPS-2)│
                                   └──────────────────────────────┘
                                              ↕
                                   ┌──────────────────────────────┐
                                   │   Binance Futures API        │
                                   └──────────────────────────────┘
```

**Séparation claire des domaines** :

- `dashboard.skulltrading.com` → VPS-1, votre dashboard perso (auth cookie existante)
- `api.skulltrading.com` → VPS-2, l'API publique multi-user pour l'app iOS
- `app.skulltrading.com` (optionnel V2) → landing page + version web companion

### 1.2 Flux des données critiques

#### Flux A : Génération et diffusion d'un signal global

1. Bot SkullTrading sur **VPS-1** détecte une opportunité sur XAU/XAG/BTC (pipeline existant intouché)
2. Score ≥ 39, filtres OK
3. Gekko analyse → produit `GekkoAnalysis` (recommandation, conviction, thèse…)
4. **Nouveau** : si recommandation = `STRONG_GO` ou `GO`, VPS-1 émet un webhook HTTPS vers VPS-2 (`POST https://api.skulltrading.com/internal/signal-webhook` avec service token)
5. **VPS-2** reçoit le webhook, persiste le signal dans son Postgres app, et appelle Supabase Edge Function `notify-subscribers`
6. Edge Function récupère les users abonnés (tier ≥ Global) à cette paire dans la DB Supabase
7. Edge Function envoie un push APNS à chaque device
8. L'app iOS reçoit le push → notification affichée → tap → ouvre l'écran "Détail signal"
9. L'app fetch le détail via `GET https://api.skulltrading.com/api/v2/signals/{id}` (VPS-2, qui peut soit servir depuis son cache, soit relayer vers VPS-1 si besoin de data fraîche)

#### Flux B : Utilisateur valide un trade depuis l'app

1. User reçoit notif signal, ouvre l'écran détail
2. User tape "Trader maintenant" → écran de confirmation (marge, levier, SL, TP suggérés par Gekko)
3. User ajuste si besoin, tape "Confirmer"
4. App appelle `POST /api/v2/binance-execute` (Supabase Edge Function) avec :
   - JWT user
   - ID du signal Gekko à exécuter
   - Paramètres ajustés (marge, levier)
5. Edge Function :
   - Vérifie JWT et tier
   - Récupère la clé Binance chiffrée du user dans la DB
   - Déchiffre en mémoire avec la master key Supabase
   - Appelle Binance Futures API : SET_LEVERAGE, MARGIN_TYPE, NEW_ORDER (market + SL + TP)
   - Efface la clé de la mémoire
   - Stocke un log d'exécution (sans la clé)
6. Réponse à l'app : succès + ID position Binance + détails fill
7. App affiche confirmation et redirige vers "Mes positions"

#### Flux C : Onboarding et connexion Binance

1. User télécharge l'app
2. Onboarding 4 écrans (présentation, disclaimers OBLIGATOIRES, sign in, choix tier)
3. Si user choisit un tier payant → IAP Apple via RevenueCat
4. User peut, OPTIONNELLEMENT, connecter Binance :
   - Écran tutorial "Comment créer une clé API Binance" (avec capture d'écrans + restrictions : pas de withdraw, IP whitelist Supabase obligatoire)
   - User colle clé + secret
   - App chiffre localement avec FaceID + clé dérivée du device
   - App envoie clé chiffrée à Supabase via HTTPS
   - Supabase re-chiffre avec sa master key (chiffrement à deux étages)
   - Confirmation à l'user : "Clé enregistrée, vous pouvez maintenant trader depuis l'app"

### 1.3 Choix techniques justifiés

| Choix | Pourquoi |
|-------|----------|
| **2 VPS séparés (VPS-1 perso + VPS-2 app)** | Isolation totale du bot perso (capital réel) vs infra commerciale. Sécurité, scalabilité, mises à jour découplées. ~20 CHF/mois supplémentaires, ROI immédiat. |
| **Infomaniak pour VPS-2** | Données hébergées en Suisse (argument marketing + RGPD strict pour users UE). Vous connaissez déjà la plateforme. Énergie 100% renouvelable. |
| **Supabase plutôt que backend custom** | Auth + DB users + RLS + Edge Functions managés, gratuit jusqu'à 50k MAU. Économie de 2-3 semaines de dev. Tient le rôle de DB users + vault clés Binance + auth. |
| **Sign in with Apple obligatoire** | Apple l'exige si on propose email/Google login. Réduit aussi le friction d'onboarding. |
| **Architecture clé Binance hybride** | Compromis sécurité/UX : user garde le contrôle (révocable côté Binance), mais on évite que l'app porte la clé en clair. Edge Function = trust boundary claire. |
| **Push notifications via APNS depuis Supabase Edge Function** | Notification critique (signaux time-sensitive) doit arriver en moins de 5 sec. APNS direct depuis Edge Function (pas de Firebase, moins de dépendance). |
| **SwiftUI iOS 17+** | Modern, productif, couvre 90%+ des iPhones actifs en 2026. Charts framework natif évite TradingView SDK. |
| **RevenueCat plutôt qu'StoreKit direct** | Gère IAP cross-platform + dashboard analytics. Free jusqu'à 2.5k$ MRR. |
| **Communication VPS-1 ↔ VPS-2 par webhook + token** | Découplage. VPS-1 push les signaux à VPS-2 dès qu'ils sont prêts. VPS-2 a son propre cache, peut servir l'app même si VPS-1 a un hoquet réseau de quelques secondes. |

---

## 2. Schéma DB Supabase

Voir `supabase/migrations/` pour l'implémentation. Le schéma comprend :

- `user_profiles` — extension 1-1 de `auth.users` (tier, langue, statut disclaimers, statut Binance)
- `user_devices` — tokens APNS par device
- `user_pair_subscriptions` — paires suivies + préférences notifs
- `binance_credentials` — clés API chiffrées via pgsodium
- `trade_executions` — historique d'ordres passés depuis l'app
- `signal_access_logs` — logs d'accès pour rate-limiting et analytics

Row Level Security activé sur toutes les tables, policies qui restreignent chaque user à ses propres lignes.

(Schémas SQL complets dans `supabase/migrations/`.)

---

## 3. Endpoints API à créer

### 3.1 Sur le VPS-2 SkullTrading-App (Infomaniak, `api.skulltrading.com`)

Tous protégés par JWT Supabase (vérification de signature via JWKS public key).

```
GET  /api/v2/signals?symbol={BTCUSDT|XAUUSDT|XAGUSDT}&limit=20
GET  /api/v2/signals/{signal_id}
GET  /api/v2/gekko/{signal_id}/basic         # tier ≥ global
GET  /api/v2/gekko/{signal_id}/detailed      # tier ≥ pro
GET  /api/v2/prices/{symbol}                 # tier free OK
GET  /api/v2/crypto-score/{symbol}           # tier ≥ pro (proxy VPS-1)
GET  /api/v2/leverage-calc                   # tier free (proxy VPS-1)
POST /api/v2/backtest                        # tier ≥ pro (proxy VPS-1)
```

### 3.1.bis Endpoints internes (VPS-1 → VPS-2)

Protégés par header `X-Service-Token`.

```
POST /internal/signal-webhook
     → Reçu par VPS-2 quand VPS-1 produit un signal STRONG_GO/GO
     → Persiste en cache + déclenche notify-subscribers
```

### 3.2 Sur Supabase (Edge Functions)

```
binance-connect      Valide une clé, chiffre, persiste
binance-disconnect   Soft-delete la clé
binance-execute      Déchiffre + place ordre Binance + logue
notify-subscribers   Envoie push APNS aux abonnés
```

Voir `supabase/functions/` pour l'implémentation.

### 3.3 Sécurisation

- `X-Service-Token` partagé entre VPS-1 ↔ VPS-2 (32 chars aléatoires).
- VPS-1 whitelist IP de VPS-2.
- JWT Supabase vérifié via JWKS côté VPS-2.
- Rate limiting Redis : 100 req/min par user.
- Audit logs sur tous les endpoints publics.

---

## 4. Disclaimers obligatoires

Critiques pour la review Apple ET pour la protection légale. Le texte
complet est défini dans la spec d'origine (voir conversation source) et
sera implémenté dans l'app iOS en Phase 2 (écran d'onboarding 3, voir §5.1).

**Points clés** :

1. Risque de perte totale (futures + levier)
2. Aucune garantie sur les signaux IA
3. Responsabilité exclusive de l'utilisateur
4. Connexion Binance à ses propres risques
5. Non-conseil financier (auteur non agréé)
6. Restrictions de juridiction
7. Protection des données

Date d'acceptation stockée en DB (`user_profiles.disclaimers_accepted_at`, `disclaimers_version`).

Versionnage des disclaimers : à chaque update du texte légal, on incrémente `disclaimers_version` et on force la ré-acceptation au prochain lancement.

CGU et Privacy Policy à rédiger en parallèle. Templates : iubenda.com / termsfeed.com. Relecture avocat fintech recommandée (~300-500 CHF).

---

## 5. Liste des écrans iOS (V1)

12 écrans principaux (détail dans la spec source) :

### 5.1 Onboarding (4 écrans, vu 1 fois)
- Écran 1 — Welcome
- Écran 2 — Comment ça marche
- Écran 3 — Disclaimers (scroll obligatoire)
- Écran 4 — Sign in (Apple + email)

### 5.2 Tab Bar principale (4 tabs)
- Tab 1 — Dashboard (home)
- Tab 2 — Signaux
- Tab 3 — Outils (calculateurs, backtest)
- Tab 4 — Profil (abo, paires, Binance, trades, paramètres)

### 5.3 Écrans secondaires
- Détail signal
- Trader maintenant (modal sheet, slide-to-confirm)
- Connexion Binance (tutorial + form)
- Mes positions (poll 5s)
- Mes trades (historique)
- Paywall / Upgrade

### 5.4 Design system
- Couleurs : noir #0A0A0A, rouge #DC2626, vert #10B981, gris #1F1F1F, blanc #FAFAFA
- Typo : SF Pro
- Icônes : SF Symbols
- Charts : Swift Charts framework natif
- Dark mode forcé en V1

---

## 6. Roadmap (semaine par semaine)

### Phase 1 — Foundation backend (Semaines 1-5)

- **S1** : Setup Supabase + schéma DB + RLS + index + test_rls
- **S2** : Commander VPS-2 Infomaniak + setup OS + Docker + Nginx + monitoring
- **S3** : Service FastAPI VPS-2 + middleware JWT + endpoints + Docker Compose
- **S4** : Edge Functions Supabase (binance-*, notify) + webhook emitter VPS-1 → VPS-2
- **S5** : APNS + tests E2E backend + runbook ops

### Phase 2 — App iOS V1 (Semaines 6-11)

- **S6** : Setup projet Xcode + Onboarding
- **S7** : Tab Bar + Dashboard + Signaux
- **S8** : Outils + Profil + Paywall
- **S9** : Connexion Binance + Mes positions
- **S10** : Trader maintenant + Notifications APNS
- **S11** : Polish + TestFlight beta

### Phase 3 — Préparation lancement (Semaines 12-13)

- **S12** : Soumission App Store (screenshots, description, privacy labels)
- **S13** : Itération sur retours Apple + Plan B read-only si rejet

---

## 7. Coûts mensuels prévisionnels

| Poste | Coût mensuel |
|-------|--------------|
| VPS-1 Infomaniak (existant) | ~25 CHF |
| VPS-2 Infomaniak (NOUVEAU) | ~20 CHF |
| Swiss Backup VPS-2 | ~5 CHF |
| Supabase Pro (au-delà 500 MAU) | 25 USD |
| RevenueCat | 0 USD (< $2.5k MRR) |
| Apple Developer | ~8 USD (99/an) |
| Domaine | ~10 CHF |
| Claude API tier global | 30-60 USD |
| Sentry | 0 USD |
| **Total fixe** | **~100-130 CHF/mois** |

Break-even : ~30-35 abonnés payants à 5 CHF/mois.

---

## 8. Stratégie de lancement (ASO)

- **Title** : `SkullTrading: Crypto AI` (30 chars)
- **Subtitle** : `Bitcoin Gold Silver Signals` (30 chars)
- **Keywords** : `trading,bitcoin,gold,silver,ai,signals,crypto,btc,xau,leverage,futures,gekko,binance`
- **Catégorie** : Finance (primaire), Business (secondaire)

Marketing : landing page + waitlist + build in public X/TikTok + micro-influenceurs.

Prix indicatifs (à figer en fin de Phase 2) :
- Global : 4.99-9.99 EUR/mois
- Pro : 14.99-19.99 EUR/mois
- Personnalisé : 29.99-49.99 EUR/mois (ou 1.99 EUR / analyse)

---

## 9. Risques et plans de mitigation

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Rejet Apple Store (exécution Binance) | Élevée | Critique | Plan B read-only prêt |
| Perte de fonds attribuée à l'app | Moyenne | Critique | Disclaimers + CGU + assurance RC pro |
| Bug d'exécution Binance | Moyenne | Élevé | Tests sandbox + double validation user |
| Coûts Claude API qui explosent | Moyenne | Moyen | Rate limit + cache 5 min |
| FINMA / régulation suisse | Faible (1-3 ans) | Critique | Sàrl si revenus > 100k CHF/an |
| VPS-2 down | Faible | Élevé | VPS-1 isolé continue. Restart ~5 min |
| VPS-1 down | Très faible | Critique perso | App sert le cache, pas de nouveaux signaux |
| Concurrent qui copie | Moyenne | Moyen | Moat = qualité Gekko + playbook auto-évolutif |

---

## 10. Questions ouvertes

1. APNS direct vs Firebase Cloud Messaging ? → APNS direct (décidé).
2. Logger les clés Binance dans Sentry ? → Jamais. Strip explicite.
3. EN seul ou EN+FR en V1 ? → EN + FR.
4. Notifications par signal ou résumé quotidien ? → Par signal pour STRONG_GO, résumé optionnel pour le reste.
5. Apple Watch companion ? → Non en V1.
6. Mode démo / paper trading ? → À évaluer.
7. Support / SAV ? → Email + FAQ. Pas de chat en V1.
8. Géofencing (bloquer certains pays) ? → À vérifier (USA pour Binance, Chine, Iran).

---

## 11. Notes finales

- Personne physique, pas d'entité juridique → assurance RC pro recommandée avant lancement.
- Consultation avocat fintech (1h, 300-500 CHF) avant soumission Apple.
- Sauvegarde du code en git, push régulier.
- TestFlight 1-2 semaines avec 10-20 testeurs avant submission publique.
- Analytics intégré dès le jour 1 (Mixpanel ou Posthog).

Fin de la spec.
