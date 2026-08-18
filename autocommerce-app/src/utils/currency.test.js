import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatMoney, getCurrencyConfig } from './currency';
import { detectCountry, resolveLandingCurrency } from '../hooks/useGeoCurrency';

describe('currency configuration', () => {
  it('uses the currency explicitly selected by the store', () => {
    expect(getCurrencyConfig({ country: 'TN', currency: 'USD' }, 'fr')).toMatchObject({
      country: 'TN',
      currency: 'USD',
      decimals: 2,
    });
  });

  it('falls back to TND for a Tunisian store without an explicit currency', () => {
    expect(getCurrencyConfig({ country: 'TN' }, 'fr')).toMatchObject({
      country: 'TN',
      currency: 'TND',
      decimals: 3,
    });
  });

  it('formats prices with the selected store currency', () => {
    const euro = formatMoney(19.99, { country: 'TN', currency: 'EUR' }, 'fr');
    const dollar = formatMoney(19.99, { country: 'TN', currency: 'USD' }, 'en');
    expect(euro).toContain('€');
    expect(dollar).toContain('$');
    expect(euro).not.toContain('TND');
    expect(dollar).not.toContain('TND');
  });
});

describe('landing geo currency', () => {
  it('shows TND for a visitor in Tunisia', () => {
    expect(resolveLandingCurrency('TN')).toMatchObject({
      country: 'TN',
      currency: 'TND',
      symbol: 'DT',
      rate: 1,
    });
  });

  it('shows USD for every visitor outside Tunisia', () => {
    expect(resolveLandingCurrency('FR')).toMatchObject({ currency: 'USD', symbol: '$' });
    expect(resolveLandingCurrency('US')).toMatchObject({ currency: 'USD', symbol: '$' });
    expect(resolveLandingCurrency('DE')).toMatchObject({ currency: 'USD', symbol: '$' });
  });

  it('normalizes lower-case country codes', () => {
    expect(resolveLandingCurrency('tn').currency).toBe('TND');
    expect(resolveLandingCurrency('fr').currency).toBe('USD');
  });
});


describe('IP geo detection', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('reads Tunisia from the primary geo provider', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ country_code: 'TN' }),
    }));

    await expect(detectCountry()).resolves.toBe('TN');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('falls back to the second provider for a foreign visitor', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockRejectedValueOnce(new Error('primary unavailable'))
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ country_code: 'FR' }),
      }));

    const country = await detectCountry();
    expect(country).toBe('FR');
    expect(resolveLandingCurrency(country).currency).toBe('USD');
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
