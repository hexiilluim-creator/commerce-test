/**
 * PrivacyPolicy.jsx — Politique de confidentialité RGPD
 * Obligatoire: RGPD Art. 13-14 (information au moment de la collecte)
 * Marchés: UE, Tunisie (Loi 2004-63), Maroc (Loi 09-08)
 */

// Company info — override via VITE_COMPANY_NAME / VITE_PRIVACY_EMAIL in .env
const COMPANY_NAME    = import.meta.env.VITE_COMPANY_NAME    || "AutoCommerce SaaS";
const COMPANY_ADDRESS = import.meta.env.VITE_COMPANY_ADDRESS || "Tunisie";
const PRIVACY_EMAIL   = import.meta.env.VITE_PRIVACY_EMAIL   || "privacy@autocommerce.io";

export default function PrivacyPolicy() {
  return (
    <div className="min-h-screen bg-[#f7f8fc] py-12">
      <div className="max-w-3xl mx-auto px-4">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">
          Politique de Confidentialité
        </h1>
        <p className="text-sm text-gray-500 mb-8">
          Version 1.1 — Dernière mise à jour : {new Date().getFullYear()}
        </p>

        <div className="bg-white rounded-xl shadow-sm p-8 space-y-8">

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              1. Responsable du traitement
            </h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              AutoCommerce est édité par <strong>{COMPANY_NAME}</strong>, {COMPANY_ADDRESS}.
              Pour toute question : <a href={`mailto:${PRIVACY_EMAIL}`}
                className="text-blue-600 underline">{PRIVACY_EMAIL}</a>
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              2. Données collectées
            </h2>
            <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
              <li>Compte : email, mot de passe hashé (bcrypt)</li>
              <li>Boutique : nom, slug, configuration canaux (WhatsApp, Instagram…)</li>
              <li>Clients de vos boutiques : numéros WhatsApp/téléphone, historique conversations, commandes</li>
              <li>Données d'usage : logs d'accès (IP), métriques anonymisées</li>
              <li>Paiements : traités par des prestataires tiers certifiés PCI-DSS</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              3. Base légale (RGPD Art. 6)
            </h2>
            <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
              <li><strong>Exécution du contrat (6.1.b)</strong> — traitement des commandes, conversations IA, facturation</li>
              <li><strong>Intérêt légitime (6.1.f)</strong> — sécurité, détection de fraude, amélioration du service</li>
              <li><strong>Consentement (6.1.a)</strong> — cookies analytiques et marketing</li>
              <li><strong>Obligation légale (6.1.c)</strong> — conservation des factures (10 ans)</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              4. Durée de conservation
            </h2>
            <ul className="text-sm text-gray-600 space-y-1 list-disc list-inside">
              <li>Données actives : durée de l'abonnement + 30 jours</li>
              <li>Données anonymisées après suppression : 30 jours puis purge automatique</li>
              <li>Logs de sécurité : 12 mois</li>
              <li>Factures : 10 ans (obligation comptable)</li>
              <li>Conversations : durée de l'abonnement puis suppression</li>
            </ul>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              5. Vos droits (RGPD Art. 15-22)
            </h2>
            <div className="text-sm text-gray-600 space-y-2">
              <p>Vous disposez des droits suivants, exercables depuis votre compte :</p>
              <ul className="space-y-1 list-disc list-inside">
                <li><strong>Accès (Art. 15)</strong> — Paramètres → RGPD → Exporter mes données (JSON)</li>
                <li><strong>Rectification (Art. 16)</strong> — Paramètres → modifier vos informations</li>
                <li><strong>Effacement (Art. 17)</strong> — Paramètres → RGPD → Supprimer mon compte</li>
                <li><strong>Portabilité (Art. 20)</strong> — export JSON disponible à tout moment</li>
                <li><strong>Opposition (Art. 21)</strong> — contactez <a href="mailto:privacy@autocommerce.io"
                    className="text-blue-600 underline">privacy@autocommerce.io</a></li>
              </ul>
            </div>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              6. Transferts hors UE
            </h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              Les données sont hébergées dans l'UE. En cas de transfert vers des pays tiers
              (ex: API OpenAI/DeepSeek), des Clauses Contractuelles Types (SCC) approuvées
              par la Commission européenne sont en place.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              7. Sécurité
            </h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              Chiffrement en transit (TLS 1.3), at-rest (AES-256/Fernet), MFA TOTP disponible,
              tokens JWT invalidés à chaque changement de mot de passe, rate-limiting sur
              toutes les routes sensibles.
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              8. Contact DPO & réclamations
            </h2>
            <p className="text-sm text-gray-600 leading-relaxed">
              Délégué à la Protection des Données :{' '}
              <a href={`mailto:${PRIVACY_EMAIL}`} className="text-blue-600 underline">
                {PRIVACY_EMAIL}
              </a>
              <br />
              Autorité de contrôle UE : votre CNIL nationale (ex: CNIL France, AEPD Espagne).
              <br />
              Tunisie : Instance Nationale de Protection des Données Personnelles (INPDP).
            </p>
          </section>

          <section>
            <h2 className="text-lg font-semibold text-gray-800 mb-3">
              9. Documents complémentaires
            </h2>
            <ul className="text-sm text-gray-600 space-y-2">
              <li>
                <a href="/api/v1/settings/gdpr/retention-policy"
                   target="_blank" rel="noopener noreferrer"
                   className="text-blue-600 underline">
                  📋 Tableau complet des durées de rétention (JSON)
                </a>
                {' '}— Art. 13/14 RGPD
              </li>
              <li>
                <a href="/ONBOARDING.md#annexe-rgpd--accord-de-traitement-des-données-dpa"
                   target="_blank" rel="noopener noreferrer"
                   className="text-blue-600 underline">
                  📄 Modèle DPA (Accord de traitement des données)
                </a>
                {' '}— Art. 28 RGPD — disponible sur demande à {PRIVACY_EMAIL}
              </li>
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
