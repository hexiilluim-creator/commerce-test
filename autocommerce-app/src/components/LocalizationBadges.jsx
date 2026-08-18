import React, { useMemo } from 'react';

/**
 * LocalizationBadges Component
 * Affiche les logos et témoignages de partenaires locaux (banques, livreurs, etc.)
 * Augmente la confiance et la conversion auprès des clients tunisiens
 */
export default function LocalizationBadges({ country = 'TN', variant = 'full' }) {
  // Partenaires locaux par pays
  const localPartners = useMemo(() => ({
    TN: {
      banks: [
        { name: 'Attijari Bank', logo: '🏦', color: '#1e40af' },
        { name: 'BNA', logo: '🏦', color: '#dc2626' },
        { name: 'BIAT', logo: '🏦', color: '#0891b2' },
        { name: 'STB', logo: '🏦', color: '#7c3aed' },
        { name: 'Flouci', logo: '💳', color: '#f59e0b' },
        { name: 'Clix', logo: '💳', color: '#10b981' },
      ],
      delivery: [
        { name: 'Tunisie Logistique', logo: '📦', color: '#1f2937' },
        { name: 'Poste Tunisienne', logo: '📮', color: '#dc2626' },
        { name: 'Aramex', logo: '🚚', color: '#fbbf24' },
        { name: 'DHL', logo: '📦', color: '#fbbf24' },
      ],
      testimonials: [
        {
          name: 'Fatima B.',
          role: 'Commerçante, Tunis',
          text: 'AutoCommerce a augmenté mes ventes de 45% en 3 mois. Zéro commission, c\'est du rêve!',
          rating: 5,
        },
        {
          name: 'Mohamed S.',
          role: 'Entrepreneur, Sfax',
          text: 'Gestion simplifiée avec WhatsApp. Mes clients adorent. Recommandé!',
          rating: 5,
        },
        {
          name: 'Yasmine K.',
          role: 'Boutique Mode, Sousse',
          text: 'Le Morning Brief IA me sauve du temps chaque jour. Excellent support!',
          rating: 5,
        },
      ],
    },
    MA: {
      banks: [
        { name: 'Attijariwafa bank', logo: '🏦', color: '#1e40af' },
        { name: 'BMCE', logo: '🏦', color: '#dc2626' },
        { name: 'Maroc Telecom Money', logo: '💳', color: '#00a84f' },
        { name: 'Orange Money', logo: '💳', color: '#f59e0b' },
      ],
      delivery: [
        { name: 'Maroc Logistique', logo: '📦', color: '#1f2937' },
        { name: 'Poste Maroc', logo: '📮', color: '#dc2626' },
        { name: 'DHL', logo: '📦', color: '#fbbf24' },
      ],
      testimonials: [
        {
          name: 'Amina M.',
          role: 'Commerçante, Casablanca',
          text: 'AutoCommerce a transformé mon business. Plus simple et plus rentable!',
          rating: 5,
        },
      ],
    },
    AE: {
      banks: [
        { name: 'Emirates NBD', logo: '🏦', color: '#1e40af' },
        { name: 'FAB', logo: '🏦', color: '#dc2626' },
        { name: 'Mashreq', logo: '🏦', color: '#0891b2' },
      ],
      delivery: [
        { name: 'Smiles', logo: '📦', color: '#1f2937' },
        { name: 'Aramex', logo: '🚚', color: '#fbbf24' },
      ],
      testimonials: [
        {
          name: 'Layla A.',
          role: 'E-commerce Owner, Dubai',
          text: 'Best platform for MENA merchants. Highly recommended!',
          rating: 5,
        },
      ],
    },
  }), []);

  const partners = localPartners[country] || localPartners.TN;

  if (variant === 'compact') {
    return (
      <div style={{
        padding: '24px',
        background: 'linear-gradient(135deg, #f0fdf4 0%, #eff6ff 100%)',
        borderRadius: '16px',
        textAlign: 'center',
      }}>
        <p style={{
          fontSize: '13px',
          fontWeight: '600',
          color: '#6a6a6a',
          marginBottom: '12px',
          textTransform: 'uppercase',
          letterSpacing: '0.5px',
        }}>
          ✓ Partenaires de confiance
        </p>
        <div style={{
          display: 'flex',
          gap: '12px',
          justifyContent: 'center',
          flexWrap: 'wrap',
        }}>
          {partners.banks.slice(0, 3).map((bank, idx) => (
            <div
              key={idx}
              style={{
                fontSize: '24px',
                padding: '8px 12px',
                background: 'white',
                borderRadius: '8px',
                border: '1px solid #e5e7eb',
              }}
              title={bank.name}
            >
              {bank.logo}
            </div>
          ))}
          {partners.delivery.slice(0, 2).map((delivery, idx) => (
            <div
              key={`delivery-${idx}`}
              style={{
                fontSize: '24px',
                padding: '8px 12px',
                background: 'white',
                borderRadius: '8px',
                border: '1px solid #e5e7eb',
              }}
              title={delivery.name}
            >
              {delivery.logo}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <section style={{
      padding: '80px 0',
      background: 'white',
      borderTop: '1px solid #e5e7eb',
    }}>
      <div className="container">
        {/* Témoignages */}
        <div>
          <h2 style={{
            fontSize: '36px',
            fontFamily: "'Fraunces', serif",
            fontWeight: '700',
            marginBottom: '40px',
            color: '#0c0c0c',
            textAlign: 'center',
          }}>
            ⭐ Témoignages de Nos Clients
          </h2>

          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
            gap: '24px',
          }}>
            {partners.testimonials.map((testimonial, idx) => (
              <div
                key={idx}
                style={{
                  padding: '24px',
                  background: '#f9fafb',
                  borderRadius: '16px',
                  border: '1.5px solid #e5e7eb',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                {/* Rating */}
                <div style={{
                  fontSize: '16px',
                  marginBottom: '12px',
                  letterSpacing: '2px',
                }}>
                  {'⭐'.repeat(testimonial.rating)}
                </div>

                {/* Texte */}
                <p style={{
                  fontSize: '14px',
                  color: '#0c0c0c',
                  lineHeight: '1.6',
                  marginBottom: '16px',
                  flex: 1,
                  fontStyle: 'italic',
                }}>
                  "{testimonial.text}"
                </p>

                {/* Auteur */}
                <div>
                  <p style={{
                    fontSize: '13px',
                    fontWeight: '700',
                    color: '#0c0c0c',
                    margin: '0 0 4px',
                  }}>
                    {testimonial.name}
                  </p>
                  <p style={{
                    fontSize: '12px',
                    color: '#6a6a6a',
                    margin: 0,
                  }}>
                    {testimonial.role}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
