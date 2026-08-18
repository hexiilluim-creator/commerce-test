import React, { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { formatMoney } from '../utils/currency';

/**
 * ROI Calculator Component
 * Affiche l'économie réalisée avec AutoCommerce vs Jumia/Glovo
 * Calcul dynamique basé sur le CA mensuel de l'utilisateur
 */
export default function ROICalculator({ store = null, currencyInfo = null }) {
  const { t } = useTranslation();
  const [monthlyRevenue, setMonthlyRevenue] = useState(10000); // valeur interne de référence en TND
  const displayCurrency = currencyInfo?.currency || store?.currency || 'TND';
  const displayRate = currencyInfo?.rate ?? 1;
  const displaySymbol = currencyInfo?.symbol || (displayCurrency === 'USD' ? '$' : 'DT');
  const displayStore = { ...store, country: displayCurrency === 'USD' ? 'US' : 'TN', currency: displayCurrency, locale: displayCurrency === 'USD' ? 'en-US' : 'fr-TN' };
  const displayRevenue = monthlyRevenue * displayRate;

  // Commissions standards du marché tunisien
  const COMMISSION_RATES = {
    jumia: 0.15,      // 15%
    glovo: 0.18,      // 18%
    autocommerce: 0.00, // 0% commission
  };

  const AUTOCOMMERCE_PLANS = {
    starter: 99,      // 99 DT/mois
    growth: 199,      // 199 DT/mois
    pro: 399,         // 399 DT/mois
  };

  // Calcul des coûts mensuels
  const calculations = useMemo(() => {
    const jumiaCommission = monthlyRevenue * COMMISSION_RATES.jumia;
    const glovoCommission = monthlyRevenue * COMMISSION_RATES.glovo;
    const autocommerceCost = AUTOCOMMERCE_PLANS.growth; // Plan Growth par défaut

    return {
      jumia: {
        commission: jumiaCommission,
        total: jumiaCommission,
      },
      glovo: {
        commission: glovoCommission,
        total: glovoCommission,
      },
      autocommerce: {
        subscription: autocommerceCost,
        total: autocommerceCost,
      },
      savings: {
        vsJumia: jumiaCommission - autocommerceCost,
        vsGlovo: glovoCommission - autocommerceCost,
        average: ((jumiaCommission + glovoCommission) / 2) - autocommerceCost,
      },
      annualSavings: {
        vsJumia: (jumiaCommission - autocommerceCost) * 12,
        vsGlovo: (glovoCommission - autocommerceCost) * 12,
        average: (((jumiaCommission + glovoCommission) / 2) - autocommerceCost) * 12,
      },
    };
  }, [monthlyRevenue]);

  const fmt = (n) => formatMoney(n * displayRate, displayStore, displayStore.locale);

  const handleRevenueChange = (e) => {
    const value = Math.max(0, parseFloat(e.target.value) || 0);
    setMonthlyRevenue(value / displayRate);
  };

  return (
    <section style={{
      padding: '100px 0',
      background: 'linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%)',
      borderTop: '1px solid #e5e7eb',
      borderBottom: '1px solid #e5e7eb',
    }}>
      <div className="container">
        {/* Titre */}
        <div style={{
          textAlign: 'center',
          marginBottom: '60px',
        }}>
          <h2 style={{
            fontSize: '48px',
            fontFamily: "'Fraunces', serif",
            fontWeight: '700',
            marginBottom: '16px',
            color: '#0c0c0c',
          }}>
            💰 Calculez vos Économies
          </h2>
          <p style={{
            fontSize: '18px',
            color: '#6a6a6a',
            maxWidth: '600px',
            margin: '0 auto',
            lineHeight: '1.6',
          }}>
            Découvrez combien vous économisez chaque mois en passant à AutoCommerce
          </p>
        </div>

        {/* Slider de CA mensuel */}
        <div style={{
          background: 'white',
          borderRadius: '24px',
          padding: '40px',
          boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
          marginBottom: '40px',
          maxWidth: '600px',
          margin: '0 auto 40px',
        }}>
          <label style={{
            display: 'block',
            fontSize: '14px',
            fontWeight: '700',
            color: '#6a6a6a',
            marginBottom: '12px',
            textTransform: 'uppercase',
            letterSpacing: '0.5px',
          }}>
            📊 Votre CA mensuel estimé
          </label>

          <div style={{
            display: 'flex',
            alignItems: 'center',
            gap: '16px',
            marginBottom: '24px',
          }}>
            <input
              type="range"
              min={Math.round(1000 * displayRate)}
              max={Math.round(100000 * displayRate)}
              step={Math.max(1, Math.round(1000 * displayRate))}
              value={Math.round(displayRevenue * 100) / 100}
              onChange={handleRevenueChange}
              style={{
                flex: 1,
                height: '8px',
                borderRadius: '4px',
                background: 'linear-gradient(90deg, #1d4ed8, #10b981)',
                outline: 'none',
                WebkitAppearance: 'none',
                appearance: 'none',
                cursor: 'pointer',
              }}
            />
            <input
              type="number"
              min={Math.round(1000 * displayRate)}
              max={Math.round(100000 * displayRate)}
              value={Math.round(displayRevenue * 100) / 100}
              onChange={handleRevenueChange}
              style={{
                width: '120px',
                padding: '10px 12px',
                border: '1.5px solid #e5e7eb',
                borderRadius: '12px',
                fontSize: '16px',
                fontWeight: '700',
                textAlign: 'right',
                outline: 'none',
              }}
            />
            <span style={{
              fontSize: '14px',
              fontWeight: '600',
              color: '#6a6a6a',
              minWidth: '40px',
            }}>
              {displaySymbol}
            </span>
          </div>

          {/* Slider CSS */}
          <style>{`
            input[type="range"]::-webkit-slider-thumb {
              appearance: none;
              width: 24px;
              height: 24px;
              border-radius: 50%;
              background: white;
              border: 3px solid #1d4ed8;
              cursor: pointer;
              box-shadow: 0 2px 8px rgba(29, 78, 216, 0.3);
            }
            input[type="range"]::-moz-range-thumb {
              width: 24px;
              height: 24px;
              border-radius: 50%;
              background: white;
              border: 3px solid #1d4ed8;
              cursor: pointer;
              box-shadow: 0 2px 8px rgba(29, 78, 216, 0.3);
            }
          `}</style>

          {/* Prédéfinis rapides */}
          <div style={{
            display: 'flex',
            gap: '8px',
            flexWrap: 'wrap',
            justifyContent: 'center',
          }}>
            {[5000, 10000, 20000, 50000].map((val) => (
              <button
                key={val}
                onClick={() => setMonthlyRevenue(val)}
                style={{
                  padding: '8px 16px',
                  borderRadius: '12px',
                  border: monthlyRevenue === val ? '2px solid #1d4ed8' : '1.5px solid #e5e7eb',
                  background: monthlyRevenue === val ? '#eff6ff' : 'white',
                  color: monthlyRevenue === val ? '#1d4ed8' : '#6a6a6a',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  transition: 'all 0.2s',
                }}
              >
                {fmt(val)}
              </button>
            ))}
          </div>
        </div>

        {/* Comparaison 3 colonnes */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
          gap: '24px',
          marginBottom: '40px',
        }}>
          {/* Jumia */}
          <div style={{
            background: 'white',
            borderRadius: '20px',
            padding: '32px 24px',
            border: '1.5px solid #e5e7eb',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>🛒</div>
            <h3 style={{
              fontSize: '20px',
              fontWeight: '700',
              color: '#0c0c0c',
              marginBottom: '8px',
              fontFamily: "'Fraunces', serif",
            }}>
              Jumia
            </h3>
            <p style={{
              fontSize: '13px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              Commission: 15% des ventes
            </p>
            <div style={{
              fontSize: '32px',
              fontWeight: '800',
              color: '#ef4444',
              marginBottom: '12px',
            }}>
              {fmt(calculations.jumia.total)}
            </div>
            <p style={{
              fontSize: '12px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              par mois
            </p>
            <div style={{
              padding: '12px',
              background: '#fef2f2',
              borderRadius: '12px',
              fontSize: '12px',
              color: '#991b1b',
              fontWeight: '600',
            }}>
              💸 {fmt(calculations.annualSavings.vsJumia)}/an avec AutoCommerce
            </div>
          </div>

          {/* Glovo */}
          <div style={{
            background: 'white',
            borderRadius: '20px',
            padding: '32px 24px',
            border: '1.5px solid #e5e7eb',
            textAlign: 'center',
          }}>
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>🚚</div>
            <h3 style={{
              fontSize: '20px',
              fontWeight: '700',
              color: '#0c0c0c',
              marginBottom: '8px',
              fontFamily: "'Fraunces', serif",
            }}>
              Glovo
            </h3>
            <p style={{
              fontSize: '13px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              Commission: 18% des ventes
            </p>
            <div style={{
              fontSize: '32px',
              fontWeight: '800',
              color: '#f59e0b',
              marginBottom: '12px',
            }}>
              {fmt(calculations.glovo.total)}
            </div>
            <p style={{
              fontSize: '12px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              par mois
            </p>
            <div style={{
              padding: '12px',
              background: '#fff7ed',
              borderRadius: '12px',
              fontSize: '12px',
              color: '#92400e',
              fontWeight: '600',
            }}>
              💸 {fmt(calculations.annualSavings.vsGlovo)}/an avec AutoCommerce
            </div>
          </div>

          {/* AutoCommerce */}
          <div style={{
            background: 'linear-gradient(135deg, #eff6ff 0%, #f0fdf4 100%)',
            borderRadius: '20px',
            padding: '32px 24px',
            border: '2.5px solid #1d4ed8',
            textAlign: 'center',
            boxShadow: '0 8px 32px rgba(29, 78, 216, 0.15)',
            position: 'relative',
          }}>
            <div style={{
              position: 'absolute',
              top: '-12px',
              left: '50%',
              transform: 'translateX(-50%)',
              background: '#1d4ed8',
              color: 'white',
              padding: '4px 12px',
              borderRadius: '20px',
              fontSize: '11px',
              fontWeight: '700',
              textTransform: 'uppercase',
              letterSpacing: '0.5px',
            }}>
              ⭐ Recommandé
            </div>
            <div style={{ fontSize: '32px', marginBottom: '12px' }}>🚀</div>
            <h3 style={{
              fontSize: '20px',
              fontWeight: '700',
              color: '#1d4ed8',
              marginBottom: '8px',
              fontFamily: "'Fraunces', serif",
            }}>
              AutoCommerce
            </h3>
            <p style={{
              fontSize: '13px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              Zéro commission
            </p>
            <div style={{
              fontSize: '32px',
              fontWeight: '800',
              color: '#10b981',
              marginBottom: '12px',
            }}>
              {fmt(calculations.autocommerce.total)}
            </div>
            <p style={{
              fontSize: '12px',
              color: '#6a6a6a',
              marginBottom: '20px',
            }}>
              par mois
            </p>
            <div style={{
              padding: '12px',
              background: '#ecfdf5',
              borderRadius: '12px',
              fontSize: '12px',
              color: '#065f46',
              fontWeight: '600',
            }}>
              ✓ Économisez {fmt(calculations.annualSavings.average)}/an
            </div>
          </div>
        </div>

        {/* CTA */}
        <div style={{ textAlign: 'center' }}>
          <a
            href="/login"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              background: '#1d4ed8',
              color: 'white',
              padding: '14px 32px',
              borderRadius: '12px',
              fontSize: '16px',
              fontWeight: '700',
              textDecoration: 'none',
              transition: 'all 0.2s',
              cursor: 'pointer',
              border: 'none',
            }}
            onMouseEnter={(e) => e.target.style.background = '#2563eb'}
            onMouseLeave={(e) => e.target.style.background = '#1d4ed8'}
          >
            Commencer maintenant → Économisez {fmt(calculations.savings.average)}/mois
          </a>
        </div>
      </div>
    </section>
  );
}
