/**
 * Landing.jsx — AutoCommerce V25 Gold
 * Design: mobile-first, palette enrichie, sections mises à jour
 * avec toutes les nouvelles fonctionnalités (Promotions, Loyalty IA,
 * Visual Builder, Predictive Restocking, B2B Portal, Plan Gold).
 *
 * Règles design :
 *   - Même structure de sections qu'avant (zéro chantier)
 *   - Couleurs enrichies : gradient indigo→violet sur hero, accents dorés, verts
 *   - Mobile-first : breakpoints 480 / 768 / 1100
 *   - Pas de lib CSS externe ajoutée
 */
import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import LanguageSwitcher from '../components/LanguageSwitcher';
import ROICalculator from '../components/ROICalculator';
import LocalizationBadges from '../components/LocalizationBadges';
import { useGeoCurrency } from '../hooks/useGeoCurrency';

/* ─── Design tokens ──────────────────────────────────────────────────────── */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,300;9..144,400;9..144,600;9..144,700&family=Geist:wght@300;400;500;600;700&display=swap');

  :root {
    /* Neutrals */
    --w:       #FFFFFF;
    --off:     #F8F7F4;
    --stone:   #F1EDE6;
    --ink:     #0C0C0C;
    --ink2:    #1C1C1C;
    --muted:   #6A6A6A;
    --border:  #E4E1DB;
    --border2: #D0CCC5;

    /* Primary — indigo */
    --blue:      #4F46E5;
    --blue2:     #6366F1;
    --blue3:     #818CF8;
    --blue-soft: #EEF2FF;
    --blue-mid:  #C7D2FE;

    /* Accent — gold / amber */
    --gold:      #D97706;
    --gold2:     #F59E0B;
    --gold-soft: #FFFBEB;
    --gold-mid:  #FDE68A;

    /* Success / WhatsApp */
    --green:      #059669;
    --green2:     #10B981;
    --green-soft: #ECFDF5;
    --wa:         #25D366;
    --wa-soft:    #F0FDF4;

    /* Violet accent */
    --violet:     #7C3AED;
    --violet-soft:#EDE9FE;

    /* Hero gradient bg */
    --hero-bg: linear-gradient(135deg, #1E1B4B 0%, #312E81 40%, #4338CA 70%, #6D28D9 100%);

    /* Shadows */
    --shadow-sm: 0 2px 8px rgba(0,0,0,0.06);
    --shadow-md: 0 8px 24px rgba(0,0,0,0.10);
    --shadow-xl: 0 32px 80px rgba(0,0,0,0.18), 0 8px 24px rgba(0,0,0,0.08);
    --shadow-glow: 0 0 60px rgba(99,102,241,0.25);
  }

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { scroll-behavior: smooth; }
  body {
    background: var(--w);
    color: var(--ink);
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
  }
  h1,h2,h3,h4 { font-family: 'Fraunces', serif; line-height: 1.1; }
  a { text-decoration: none; color: inherit; }
  img { display: block; width: 100%; }

  /* ── Layout ── */
  .container { max-width: 1280px; margin: 0 auto; padding: 0 20px; }

  /* ── Navigation ── */
  nav {
    position: fixed; top: 0; width: 100%;
    background: rgba(30,27,75,0.92);
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    z-index: 100; height: 68px;
    display: flex; align-items: center;
    border-bottom: 1px solid rgba(255,255,255,0.08);
    transition: background 0.3s;
  }
  nav.scrolled { background: rgba(15,14,40,0.97); box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
  .nav-inner { display: flex; justify-content: space-between; align-items: center; width: 100%; }
  .logo { font-family: 'Fraunces', serif; font-size: 22px; font-weight: 700; color: #fff; letter-spacing: -0.3px; }
  .logo span { color: var(--blue3); }
  .nav-links { display: flex; gap: 28px; font-weight: 500; font-size: 14px; color: rgba(255,255,255,0.75); }
  .nav-links a:hover { color: #fff; }
  .btn-nav {
    background: linear-gradient(135deg, var(--blue) 0%, var(--violet) 100%);
    color: #fff; padding: 10px 22px; border-radius: 8px;
    font-weight: 600; font-size: 14px; border: none; cursor: pointer;
    transition: opacity 0.2s, transform 0.2s;
    white-space: nowrap;
  }
  .btn-nav:hover { opacity: 0.88; transform: translateY(-1px); }
  .btn-primary {
    background: linear-gradient(135deg, var(--blue) 0%, var(--violet) 100%);
    color: #fff; padding: 14px 28px; border-radius: 10px;
    font-weight: 600; font-size: 16px; border: none; cursor: pointer;
    display: inline-flex; align-items: center; gap: 8px;
    transition: opacity 0.2s, transform 0.2s, box-shadow 0.2s;
    box-shadow: 0 4px 20px rgba(99,102,241,0.4);
  }
  .btn-primary:hover { opacity: 0.9; transform: translateY(-2px); box-shadow: 0 8px 28px rgba(99,102,241,0.5); }
  .btn-outline {
    background: transparent;
    color: rgba(255,255,255,0.9);
    padding: 14px 28px; border-radius: 10px;
    font-weight: 600; font-size: 16px;
    border: 1.5px solid rgba(255,255,255,0.25);
    cursor: pointer; display: inline-flex; align-items: center; gap: 8px;
    transition: border-color 0.2s, background 0.2s;
  }
  .btn-outline:hover { border-color: rgba(255,255,255,0.6); background: rgba(255,255,255,0.06); }

  /* ── Hero ── */
  .hero {
    padding: 130px 0 90px;
    background: var(--hero-bg);
    position: relative; overflow: hidden;
  }
  .hero::before {
    content: '';
    position: absolute; inset: 0;
    background: radial-gradient(ellipse 70% 60% at 20% 40%, rgba(99,102,241,0.35) 0%, transparent 70%),
                radial-gradient(ellipse 50% 50% at 80% 20%, rgba(124,58,237,0.25) 0%, transparent 60%);
    pointer-events: none;
  }
  .hero-grid {
    display: grid;
    grid-template-columns: 1.15fr 1fr;
    gap: 56px; align-items: center;
    position: relative; z-index: 1;
  }
  .hero-eyebrow {
    display: inline-flex; align-items: center; gap: 8px;
    background: rgba(255,255,255,0.1);
    border: 1px solid rgba(255,255,255,0.2);
    border-radius: 100px; padding: 6px 14px;
    font-size: 13px; font-weight: 600; color: rgba(255,255,255,0.9);
    margin-bottom: 24px; backdrop-filter: blur(8px);
  }
  .hero-eyebrow-dot { width: 8px; height: 8px; background: var(--green2); border-radius: 50%; animation: pulse-dot 2s infinite; }
  @keyframes pulse-dot { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:0.5;transform:scale(0.85)} }
  .hero h1 {
    font-size: clamp(40px, 5.5vw, 68px);
    color: #fff; margin-bottom: 24px;
    letter-spacing: -1.5px; line-height: 1.05;
  }
  .hero h1 .gradient-text {
    background: linear-gradient(135deg, #A5B4FC 0%, #C4B5FD 50%, #FDE68A 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text;
  }
  .hero-sub {
    font-size: clamp(17px, 2vw, 21px);
    color: rgba(255,255,255,0.72);
    margin-bottom: 40px; line-height: 1.65; max-width: 520px;
  }
  .hero-cta-group { display: flex; gap: 14px; flex-wrap: wrap; }
  .hero-trust {
    margin-top: 40px; display: flex; align-items: center; gap: 12px;
    color: rgba(255,255,255,0.55); font-size: 13px;
  }
  .hero-trust-badges { display: flex; gap: 8px; flex-wrap: wrap; }
  .trust-badge {
    background: rgba(255,255,255,0.08);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 6px; padding: 4px 10px;
    font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.8);
  }

  /* ── Hero Slider ── */
  .hero-slider {
    position: relative; border-radius: 20px; overflow: hidden;
    box-shadow: var(--shadow-xl), var(--shadow-glow);
    transform: perspective(1000px) rotateY(-4deg) rotateX(2deg);
    transition: transform 0.6s ease;
    background: var(--stone); aspect-ratio: 4/3;
    border: 1px solid rgba(255,255,255,0.12);
  }
  .hero-slider:hover { transform: perspective(1000px) rotateY(0deg) rotateX(0deg) scale(1.01); }
  .slide { position: absolute; inset: 0; opacity: 0; transition: opacity 0.9s ease-in-out; pointer-events: none; }
  .slide.active { opacity: 1; pointer-events: auto; }
  .slide img { width: 100%; height: 100%; object-fit: cover; }
  .slide-caption {
    position: absolute; bottom: 0; left: 0; right: 0;
    padding: 32px 24px 20px;
    background: linear-gradient(to top, rgba(0,0,0,0.78) 0%, transparent 100%);
    color: #fff;
    transform: translateY(8px); opacity: 0;
    transition: opacity 0.5s ease 0.3s, transform 0.5s ease 0.3s;
  }
  .slide.active .slide-caption { opacity: 1; transform: translateY(0); }
  .slide-caption h4 { font-size: 17px; font-weight: 600; margin-bottom: 4px; }
  .slide-caption p { font-size: 13px; color: rgba(255,255,255,0.75); line-height: 1.4; }
  .wa-badge {
    position: absolute; top: 16px; right: 16px;
    background: var(--wa); color: #fff;
    padding: 6px 12px; border-radius: 100px;
    font-size: 13px; font-weight: 700;
    display: flex; align-items: center; gap: 6px;
    box-shadow: 0 4px 16px rgba(37,211,102,0.4);
  }
  .slider-progress {
    position: absolute; bottom: 0; left: 0; height: 3px;
    background: linear-gradient(90deg, var(--blue3), var(--gold2));
    transition: width 0.05s linear; z-index: 10;
  }
  .slider-dots { position: absolute; bottom: 14px; right: 16px; display: flex; gap: 6px; z-index: 10; }
  .dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: rgba(255,255,255,0.4); border: none; cursor: pointer;
    transition: background 0.2s, width 0.2s; padding: 0;
  }
  .dot.active { background: #fff; width: 20px; border-radius: 4px; }

  /* ── Stats bar ── */
  .stats {
    background: var(--off);
    border-top: 1px solid var(--border);
    border-bottom: 1px solid var(--border);
    padding: 40px 0;
  }
  .stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 24px; text-align: center; }
  .stat-item h3 { font-size: clamp(28px, 3vw, 40px); color: var(--blue); margin-bottom: 6px; }
  .stat-item p { color: var(--muted); font-size: 14px; font-weight: 500; }

  /* ── Value banner (Zéro commission + Sécurité) ── */
  .value-banner { padding: 100px 0; background: var(--off); }
  .value-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 48px; }
  .value-item {
    background: var(--w);
    border: 1px solid var(--border);
    border-radius: 20px; padding: 48px 40px;
    position: relative; overflow: hidden;
    transition: box-shadow 0.25s, transform 0.25s;
  }
  .value-item:hover { box-shadow: var(--shadow-md); transform: translateY(-3px); }
  .value-item::before {
    content: ''; position: absolute; top: 0; left: 0; right: 0; height: 4px;
    background: linear-gradient(90deg, var(--blue), var(--violet));
  }
  .value-icon {
    font-size: 40px; margin-bottom: 20px;
    width: 72px; height: 72px; border-radius: 16px;
    background: var(--blue-soft); display: flex; align-items: center; justify-content: center;
  }
  .value-item h3 { font-size: 26px; margin-bottom: 12px; color: var(--ink); }
  .value-item p { color: var(--muted); line-height: 1.65; margin-bottom: 24px; }
  .value-list { list-style: none; display: flex; flex-direction: column; gap: 10px; }
  .value-list li {
    display: flex; align-items: flex-start; gap: 10px;
    color: var(--ink2); font-size: 15px;
  }
  .value-list li::before {
    content: '✓'; color: var(--green2); font-weight: 900;
    flex-shrink: 0; margin-top: 1px;
  }

  /* ── Features deep-dive ── */
  .features { padding: 100px 0; }
  .section-title { text-align: center; margin-bottom: 72px; }
  .section-title h2 { font-size: clamp(32px, 4vw, 52px); margin-bottom: 16px; }
  .section-title p { color: var(--muted); font-size: 18px; max-width: 560px; margin: 0 auto; }
  .section-badge {
    display: inline-block;
    background: var(--blue-soft); color: var(--blue);
    font-size: 12px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.8px; padding: 4px 12px; border-radius: 100px;
    margin-bottom: 16px;
  }
  .feature-card {
    display: grid; grid-template-columns: 1fr 1fr; gap: 64px;
    align-items: center; margin-bottom: 100px;
  }
  .feature-card.reverse { }
  .feature-card.reverse .feature-img { order: -1; }
  .feature-content h3 { font-size: clamp(24px, 2.5vw, 36px); margin-bottom: 16px; }
  .feature-content p { color: var(--muted); line-height: 1.7; margin-bottom: 24px; font-size: 17px; }
  .feature-img {
    border-radius: 20px; overflow: hidden;
    box-shadow: var(--shadow-md);
    aspect-ratio: 4/3; background: var(--stone);
  }
  .feature-img img { width: 100%; height: 100%; object-fit: cover; }
  .feature-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px; }
  .feature-tag {
    background: var(--blue-soft); color: var(--blue);
    font-size: 13px; font-weight: 600; padding: 5px 12px; border-radius: 100px;
  }
  .feature-tag.green { background: var(--green-soft); color: var(--green); }
  .feature-tag.gold { background: var(--gold-soft); color: var(--gold); }
  .feature-tag.violet { background: var(--violet-soft); color: var(--violet); }
  .price-features { list-style: none; display: flex; flex-direction: column; gap: 10px; margin: 0; padding: 0; }
  .price-features li {
    display: flex; align-items: flex-start; gap: 10px;
    color: var(--ink2); font-size: 15px; line-height: 1.5;
  }
  .price-features li::before { content: '✓'; color: var(--green2); font-weight: 900; flex-shrink: 0; }

  /* ── New features modules grid ── */
  .modules { padding: 100px 0; background: var(--off); }
  .modules-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 24px; margin-top: 56px; }
  .module-card {
    background: var(--w); border: 1px solid var(--border);
    border-radius: 18px; padding: 32px 28px;
    transition: box-shadow 0.25s, transform 0.25s;
    position: relative; overflow: hidden;
  }
  .module-card:hover { box-shadow: var(--shadow-md); transform: translateY(-4px); }
  .module-card::after {
    content: ''; position: absolute; bottom: 0; left: 0; right: 0; height: 3px;
  }
  .module-card.indigo::after  { background: linear-gradient(90deg, var(--blue), var(--blue2)); }
  .module-card.violet::after  { background: linear-gradient(90deg, var(--violet), #A855F7); }
  .module-card.gold::after    { background: linear-gradient(90deg, var(--gold), var(--gold2)); }
  .module-card.green::after   { background: linear-gradient(90deg, var(--green), var(--green2)); }
  .module-card.teal::after    { background: linear-gradient(90deg, #0891B2, #06B6D4); }
  .module-card.rose::after    { background: linear-gradient(90deg, #E11D48, #F43F5E); }
  .module-icon {
    font-size: 32px; margin-bottom: 18px;
    width: 60px; height: 60px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
  }
  .module-icon.indigo { background: var(--blue-soft); }
  .module-icon.violet { background: var(--violet-soft); }
  .module-icon.gold   { background: var(--gold-soft); }
  .module-icon.green  { background: var(--green-soft); }
  .module-icon.teal   { background: #CFFAFE; }
  .module-icon.rose   { background: #FFE4E6; }
  .module-card h4 { font-size: 19px; margin-bottom: 10px; }
  .module-card p { color: var(--muted); font-size: 14px; line-height: 1.6; margin-bottom: 16px; }
  .module-plan {
    display: inline-block; font-size: 11px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 3px 10px; border-radius: 100px;
    background: var(--blue-soft); color: var(--blue);
  }
  .module-plan.gold { background: var(--gold-soft); color: var(--gold); }
  .module-plan.violet { background: var(--violet-soft); color: var(--violet); }

  /* ── Audiences ── */
  .audiences { padding: 100px 0; background: linear-gradient(135deg, #1E1B4B 0%, #2D2B6B 100%); }
  .audience-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 20px; margin-top: 56px; }
  .audience-card {
    background: rgba(255,255,255,0.06);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 16px; padding: 32px 28px;
    transition: background 0.25s, transform 0.25s;
    cursor: default;
  }
  .audience-card:hover { background: rgba(255,255,255,0.1); transform: translateY(-3px); }
  .audience-card h4 { font-size: 19px; color: #fff; margin-bottom: 10px; }

  /* ── Pricing ── */
  .pricing { padding: 100px 0; background: var(--w); }
  .cycle-toggle {
    display: inline-flex; border: 1.5px solid var(--border);
    border-radius: 12px; overflow: hidden; margin: 0 auto 56px;
    display: flex; width: fit-content;
  }
  .cycle-btn {
    padding: 12px 24px; font-size: 14px; font-weight: 600; border: none;
    background: transparent; color: var(--muted); cursor: pointer;
    transition: 0.2s; display: flex; align-items: center; gap: 8px;
  }
  .cycle-btn.active { background: var(--blue); color: #fff; }
  .annual-save {
    background: var(--green-soft); color: var(--green);
    font-size: 11px; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.4px; padding: 2px 8px; border-radius: 100px;
  }
  .pricing-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-bottom: 48px; }
  .price-card {
    border: 1.5px solid var(--border); border-radius: 20px; padding: 32px 28px;
    display: flex; flex-direction: column; position: relative;
    transition: box-shadow 0.25s, transform 0.25s;
    background: var(--w);
  }
  .price-card:hover { box-shadow: var(--shadow-md); transform: translateY(-4px); }
  .price-card.featured {
    border-color: var(--blue); border-width: 2px;
    background: linear-gradient(180deg, var(--blue-soft) 0%, var(--w) 100%);
    box-shadow: 0 8px 32px rgba(79,70,229,0.18);
  }
  .price-card.featured::before {
    content: '⭐ Populaire';
    position: absolute; top: -14px; left: 50%; transform: translateX(-50%);
    background: linear-gradient(135deg, var(--blue), var(--violet));
    color: #fff; padding: 4px 16px; border-radius: 100px;
    font-size: 12px; font-weight: 700; white-space: nowrap;
  }
  .plan-badge {
    display: inline-block; font-size: 12px; font-weight: 700;
    padding: 4px 12px; border-radius: 100px; margin-bottom: 12px;
    width: fit-content;
  }
  .plan-name { font-size: 22px; font-weight: 700; margin-bottom: 8px; font-family: 'Fraunces', serif; }
  .price-main { font-size: 38px; font-weight: 800; color: var(--ink); line-height: 1; margin-bottom: 4px; }
  .price-main span { font-size: 16px; font-weight: 500; color: var(--muted); }
  .price-annual-note { font-size: 13px; color: var(--green); font-weight: 600; margin-bottom: 12px; }
  .price-equiv { font-size: 13px; color: var(--muted); margin-bottom: 12px; min-height: 20px; }
  .credit-pill {
    background: var(--blue-soft); color: var(--blue);
    font-size: 13px; font-weight: 700; padding: 7px 14px;
    border-radius: 100px; margin: 16px 0; width: fit-content;
  }
  .price-disclaimer {
    background: var(--gold-soft); border: 1px solid var(--gold-mid);
    border-radius: 8px; padding: 10px 14px;
    font-size: 12px; color: var(--gold); font-weight: 500;
    margin-bottom: 16px; line-height: 1.5;
  }
  .topup-grid { display: flex; justify-content: center; gap: 12px; flex-wrap: wrap; margin-top: 40px; }
  .topup-chip {
    background: var(--off); border: 1.5px solid var(--border);
    border-radius: 12px; padding: 10px 20px;
    font-size: 13px; font-weight: 600; color: var(--ink);
    transition: border-color 0.2s, background 0.2s;
  }
  .topup-chip:hover { border-color: var(--blue); background: var(--blue-soft); }
  .topup-chip span { color: var(--blue); }

  /* ── About / Trust ── */
  .about { padding: 100px 0; background: var(--off); }
  .about-inner {
    display: grid; grid-template-columns: 1fr 1fr; gap: 64px; align-items: center;
  }
  .about-trust {
    background: linear-gradient(135deg, var(--blue) 0%, var(--violet) 100%);
    border-radius: 24px; padding: 56px 48px; color: #fff; text-align: center;
  }
  .about-trust h4 { font-size: 36px; margin-bottom: 16px; color: #fff; }
  .about-trust p { color: rgba(255,255,255,0.8); font-size: 18px; line-height: 1.7; }

  /* ── Footer ── */
  footer {
    background: #0F0E28;
    padding: 80px 0 40px;
    color: rgba(255,255,255,0.6);
  }
  .footer-grid { display: grid; grid-template-columns: 1.5fr 1fr 1fr 1fr; gap: 48px; margin-bottom: 60px; }
  .footer-logo { font-family: 'Fraunces', serif; font-size: 22px; font-weight: 700; color: #fff; margin-bottom: 16px; }
  .footer-col h5 { color: #fff; font-size: 14px; font-weight: 700; margin-bottom: 16px; text-transform: uppercase; letter-spacing: 0.5px; }
  .footer-links { list-style: none; display: flex; flex-direction: column; gap: 10px; }
  .footer-links li { font-size: 14px; transition: color 0.2s; cursor: pointer; }
  .footer-links li:hover { color: #fff; }
  .footer-divider { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin-bottom: 32px; }

  /* ── Responsive — Mobile First ── */
  @media (max-width: 1100px) {
    .pricing-grid { grid-template-columns: repeat(2, 1fr); }
    .modules-grid { grid-template-columns: repeat(2, 1fr); }
    .footer-grid { grid-template-columns: 1fr 1fr; gap: 32px; }
  }

  @media (max-width: 768px) {
    .hero { padding: 100px 0 64px; }
    .hero-grid { grid-template-columns: 1fr; gap: 40px; }
    .hero-slider { transform: none; }
    .feature-card, .feature-card.reverse, .value-grid, .about-inner {
      grid-template-columns: 1fr; gap: 32px;
    }
    .feature-card.reverse .feature-img { order: 0; }
    .pricing-grid { grid-template-columns: 1fr; }
    .modules-grid { grid-template-columns: 1fr; }
    .audience-grid { grid-template-columns: 1fr; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); }
    .footer-grid { grid-template-columns: 1fr; gap: 28px; }
    .nav-links { display: none; }
    .section-title h2 { font-size: 30px; }
    .cycle-toggle { flex-direction: column; }
  }

  @media (max-width: 480px) {
    .hero h1 { font-size: 34px; }
    .hero-cta-group { flex-direction: column; }
    .btn-primary, .btn-outline { width: 100%; justify-content: center; font-size: 15px; }
    .stats-grid { grid-template-columns: repeat(2, 1fr); gap: 16px; }
    .container { padding: 0 16px; }
    .about-trust { padding: 36px 24px; }
    .value-item { padding: 32px 24px; }
    .price-card { padding: 24px 20px; }
    .module-card { padding: 24px 20px; }
  }

  /* ── RTL ── */
  [dir="rtl"] .price-features li { flex-direction: row-reverse; }
  [dir="rtl"] .value-list li { flex-direction: row-reverse; }
  [dir="rtl"] .price-features li::before,
  [dir="rtl"] .value-list li::before { margin-right: 0; }
`;

const SLIDE_DURATION = 3400;

export default function Landing() {
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';

  const [scrolled, setScrolled]         = useState(false);
  const [currentSlide, setCurrentSlide] = useState(0);
  const [progress, setProgress]         = useState(0);
  const [billingCycle, setBillingCycle] = useState('monthly');
  // Devise d'affichage détectée depuis l'IP du visiteur (cosmétique — voir hooks/useGeoCurrency.js).
  // Les plans sont définis en TND (plan_catalog.py) ; ceci ne convertit que l'affichage.
  const { symbol: currencySymbol, rate: currencyRate, currency: detectedCurrency } = useGeoCurrency();
  const intervalRef   = useRef(null);
  const progressRef   = useRef(null);
  const startTimeRef  = useRef(null);
  const isAnnual = billingCycle === 'annual';
  const formatLandingAmount = (amountTND) => {
    const amount = amountTND * currencyRate;
    if (detectedCurrency === 'TND') return `${amount.toFixed(0)} DT`;
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: detectedCurrency,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(amount);
  };

  const SLIDES = [
    { src: '/hero_woman.jpg',     alt: t('slides.0.title'), title: t('slides.0.title'), desc: t('slides.0.desc'), showWaBadge: false },
    { src: '/slide_artisan.jpg',  alt: t('slides.1.title'), title: t('slides.1.title'), desc: t('slides.1.desc'), showWaBadge: true  },
    { src: '/slide_coiffure.jpg', alt: t('slides.2.title'), title: t('slides.2.title'), desc: t('slides.2.desc'), showWaBadge: false },
    { src: '/slide_livestream.jpg',alt:t('slides.3.title'), title: t('slides.3.title'), desc: t('slides.3.desc'), showWaBadge: false },
  ];

  useEffect(() => {
    const h = () => setScrolled(window.scrollY > 50);
    window.addEventListener('scroll', h);
    return () => window.removeEventListener('scroll', h);
  }, []);

  const startSlider = () => {
    startTimeRef.current = Date.now();
    setProgress(0);
    progressRef.current = setInterval(() => {
      const elapsed = Date.now() - startTimeRef.current;
      setProgress(Math.min((elapsed / SLIDE_DURATION) * 100, 100));
    }, 50);
    intervalRef.current = setTimeout(() => {
      setCurrentSlide(prev => (prev + 1) % SLIDES.length);
    }, SLIDE_DURATION);
  };

  const stopSlider = () => {
    clearTimeout(intervalRef.current);
    clearInterval(progressRef.current);
  };

  useEffect(() => { startSlider(); return stopSlider; }, [currentSlide]); // eslint-disable-line

  const goToSlide = (idx) => { stopSlider(); setCurrentSlide(idx); };

  /* ── Plans data (sync with plan_catalog.py) ── */
  const PLANS = [
    {
      code: 'starter', label: 'Starter',
      price_monthly: 19.99, price_annual: 199,
      credits: 500, featured: false,
      badge: null,
      color: '',
      features: ['Boutique en ligne', 'Instagram, Messenger, TikTok', '500 crédits IA/mois', "Jusqu'à 50 produits", '1 utilisateur', 'TVA multi-pays', 'Support standard'],
    },
    {
      code: 'business', label: 'Business',
      price_monthly: 29.99, price_annual: 299,
      credits: 2000, featured: true,
      badge: null,
      color: '',
      features: ['Tout Starter', 'CRM client intégré', '2 000 crédits IA/mois', "Jusqu'à 500 produits", '3 utilisateurs', 'Automatisations & Suivi', 'Stats avancées'],
    },
    {
      code: 'premium', label: 'Premium',
      price_monthly: 39.99, price_annual: 399,
      credits: 5000, featured: false,
      badge: null,
      color: '',
      features: ['Tout Business', 'Produits illimités', '5 000 crédits IA/mois', 'Campagnes marketing', '10 utilisateurs', 'IA Analyse image & audio', 'Rapports détaillés'],
    },
    {
      code: 'pro_whatsapp', label: 'Pro WhatsApp',
      price_monthly: 59.99, price_annual: 599,
      credits: 10000, featured: false,
      badge: 'WhatsApp ✓', badgeColor: '#25D366',
      color: '',
      features: ['Tout Premium', 'WhatsApp Business inclus', 'CRM omnicanal', '10 000 crédits IA/mois', '20 utilisateurs', 'Support prioritaire', 'File IA prioritaire'],
      disclaimer: '⚠️ Les frais Meta WhatsApp ne sont pas inclus.',
    },
  ];

  /* ── Nouveaux modules Plans E & F ── */
  const MODULES = [
    { icon: '🏷️', title: 'Promotions & Coupons', desc: 'Créez des campagnes, codes promo, remises automatiques et suivez leur ROI en temps réel.', plan: 'Gold', planClass: 'gold', color: 'gold' },
    { icon: '🎁', title: 'Fidélité IA', desc: 'Points, récompenses personnalisées, prédiction de churn et segmentation RFM automatique.', plan: 'Gold', planClass: 'gold', color: 'violet' },
    { icon: '🎨', title: 'Visual Builder', desc: 'Éditeur visuel drag & drop pour créer votre boutique sans coder, avec templates mobiles.', plan: 'Gold', planClass: 'gold', color: 'indigo' },
    { icon: '📦', title: 'Restocking Prédictif', desc: "Prévisions IA des ruptures de stock basées sur l'historique de ventes et la saisonnalité.", plan: 'Gold', planClass: 'gold', color: 'teal' },
    { icon: '🏢', title: 'Portail B2B', desc: 'Comptes entreprises, tarifs négociés, approbations multi-niveaux et facturation groupée.', plan: 'Gold', planClass: 'gold', color: 'rose' },
    { icon: '💰', title: 'TVA Multi-pays', desc: 'Calcul automatique de la TVA par pays, exemptions et conformité fiscale internationale.', plan: 'Tous plans', planClass: '', color: 'green' },
  ];

  const audienceItems = t('audiences.items', { returnObjects: true });

  return (
    <>
      <style>{CSS}</style>

      {/* ── Navigation ── */}
      <nav className={scrolled ? 'scrolled' : ''} dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="nav-inner">
            <Link to="/" className="logo">Auto<span>Commerce</span></Link>
            <div className="nav-links">
              <a href="#features">{t('nav.features')}</a>
              <a href="#modules">Nouveautés</a>
              <a href="#audiences">{t('nav.audiences')}</a>
              <a href="#pricing">{t('nav.pricing')}</a>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <LanguageSwitcher variant="nav" />
              <Link to="/login" className="btn-nav">{t('nav.freeTrial')}</Link>
            </div>
          </div>
        </div>
      </nav>

      {/* ── Hero ── */}
      <section className="hero" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="hero-grid">
            <div className="hero-content">
              <div className="hero-eyebrow">
                <span className="hero-eyebrow-dot" />
                Plateforme SaaS Commerce — V25 Gold
              </div>
              <h1>
                {t('hero.title')}
                {' '}
                <span className="gradient-text">{t('hero.titleAccent') || 'avec l\'IA'}</span>
              </h1>
              <p className="hero-sub">{t('hero.subtitle')}</p>
              <div className="hero-cta-group">
                <Link to="/login" className="btn-primary" style={{ padding: '16px 32px', fontSize: '17px' }}>
                  {t('hero.cta')} →
                </Link>
                <a href="#features" className="btn-outline" style={{ padding: '16px 28px', fontSize: '16px' }}>
                  {t('hero.demo') || 'Voir la démo'}
                </a>
              </div>
              <div className="hero-trust">
                <span>Inclus :</span>
                <div className="hero-trust-badges">
                  <span className="trust-badge">0% commission</span>
                  <span className="trust-badge">WhatsApp IA</span>
                  <span className="trust-badge">RGPD ✓</span>
                  <span className="trust-badge">Paiement TN ✓</span>
                </div>
              </div>
            </div>

            {/* Slider */}
            <div className="hero-slider">
              {SLIDES.map((slide, idx) => (
                <div key={idx} className={`slide${currentSlide === idx ? ' active' : ''}`}>
                  <img src={slide.src} alt={slide.alt} loading={idx === 0 ? 'eager' : 'lazy'} />
                  {slide.showWaBadge && (
                    <div className="wa-badge">
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
                      </svg>
                      WhatsApp Live
                    </div>
                  )}
                  <div className="slide-caption">
                    <h4>{slide.title}</h4>
                    <p>{slide.desc}</p>
                  </div>
                </div>
              ))}
              <div className="slider-progress" style={{ width: `${progress}%` }} />
              <div className="slider-dots">
                {SLIDES.map((_, idx) => (
                  <button key={idx} className={`dot${currentSlide === idx ? ' active' : ''}`} onClick={() => goToSlide(idx)} aria-label={`Slide ${idx + 1}`} />
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Stats ── */}
      <section className="stats" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="stats-grid">
            <div className="stat-item"><h3>+45%</h3><p>{t('stats.revenue')}</p></div>
            <div className="stat-item"><h3>24/7</h3><p>{t('stats.ai')}</p></div>
            <div className="stat-item"><h3>10h+</h3><p>{t('stats.time')}</p></div>
            <div className="stat-item"><h3>100%</h3><p>{t('stats.secure')}</p></div>
          </div>
        </div>
      </section>

      {/* ── Zéro commission + Sécurité ── */}
      <section id="zero-commission" className="value-banner" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="value-grid">
            <div className="value-item">
              <div className="value-icon">💰</div>
              <h3>{t('features.f1Title')}</h3>
              <p>{t('features.f1Desc')}</p>
              <ul className="value-list">
                <li>{t('features.f1l1')}</li>
                <li>{t('features.f1l2')}</li>
                <li>{t('features.f1l3')}</li>
              </ul>
            </div>
            <div className="value-item">
              <div className="value-icon">🔒</div>
              <h3>{t('features.f2Title')}</h3>
              <p>{t('features.f2Desc')}</p>
              <ul className="value-list">
                <li>{t('features.f2l1')}</li>
                <li>{t('features.f2l2')}</li>
                <li>{t('features.f2l3')}</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ── Features deep-dive ── */}
      <section id="features" className="features" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="section-title">
            <span className="section-badge">Fonctionnalités</span>
            <h2>{t('features.sectionTitle')}</h2>
            <p>{t('features.sectionSub')}</p>
          </div>

          <div className="feature-card">
            <div className="feature-content">
              <div className="feature-tags">
                <span className="feature-tag">IA Conversationnelle</span>
                <span className="feature-tag green">WhatsApp</span>
                <span className="feature-tag">Darija ✓</span>
              </div>
              <h3>🤖 {t('features.f1Title')}</h3>
              <p>{t('features.f1Desc')}</p>
              <ul className="price-features">
                <li>{t('features.f1l1')}</li>
                <li>{t('features.f1l2')}</li>
                <li>{t('features.f1l3')}</li>
              </ul>
            </div>
            <div className="feature-img"><img src="/ai_agent.jpg" alt="AI WhatsApp Agent" /></div>
          </div>

          <div className="feature-card reverse">
            <div className="feature-img"><img src="/omnicall.jpg" alt="OmniCall V9" /></div>
            <div className="feature-content">
              <div className="feature-tags">
                <span className="feature-tag">OmniCall V9</span>
                <span className="feature-tag violet">Multi-canal</span>
                <span className="feature-tag gold">Instagram • TikTok • FB</span>
              </div>
              <h3>🌍 {t('features.f2Title')}</h3>
              <p>{t('features.f2Desc')}</p>
              <ul className="price-features">
                <li>{t('features.f2l1')}</li>
                <li>{t('features.f2l2')}</li>
                <li>{t('features.f2l3')}</li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* ── Nouveaux modules Plans E & F ── */}
      <section id="modules" className="modules" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="section-title">
            <span className="section-badge" style={{ background: 'var(--gold-soft)', color: 'var(--gold)' }}>Nouveautés V25 Gold</span>
            <h2>Tout ce qu'il faut pour scaler</h2>
            <p>Des modules avancés activables selon votre plan — sans changer de plateforme.</p>
          </div>
          <div className="modules-grid">
            {MODULES.map((m, i) => (
              <div key={i} className={`module-card ${m.color}`}>
                <div className={`module-icon ${m.color}`}>{m.icon}</div>
                <h4>{m.title}</h4>
                <p>{m.desc}</p>
                <span className={`module-plan ${m.planClass}`}>{m.plan}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Audiences ── */}
      <section id="audiences" className="audiences" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="section-title">
            <h2 style={{ color: '#fff' }}>{t('audiences.sectionTitle')}</h2>
            <p style={{ color: 'rgba(255,255,255,0.6)' }}>{t('audiences.sectionSub')}</p>
          </div>
          <div className="audience-grid">
            {Array.isArray(audienceItems) && audienceItems.map((a, i) => (
              <div key={i} className="audience-card">
                <h4>{a.t}</h4>
                <p style={{ color: 'rgba(255,255,255,0.6)', lineHeight: '1.55', fontSize: '14px' }}>{a.d}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <ROICalculator currencyInfo={{ currency: detectedCurrency, symbol: currencySymbol, rate: currencyRate }} />
      <LocalizationBadges country="TN" />

      {/* ── Pricing ── */}
      <section id="pricing" className="pricing" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="section-title">
            <span className="section-badge">Tarifs</span>
            <h2>Tarifs Transparents</h2>
            <p>Zéro commission sur vos ventes — payez uniquement l'abonnement mensuel ou annuel.</p>
          </div>

          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: '48px' }}>
            <div className="cycle-toggle">
              <button className={`cycle-btn${!isAnnual ? ' active' : ''}`} onClick={() => setBillingCycle('monthly')}>Mensuel</button>
              <button className={`cycle-btn${isAnnual ? ' active' : ''}`} onClick={() => setBillingCycle('annual')}>
                Annuel <span className="annual-save">2 mois offerts</span>
              </button>
            </div>
          </div>

          <div className="pricing-grid">
            {PLANS.map((plan) => {
              const priceTND = isAnnual ? plan.price_annual : plan.price_monthly;
              const price = priceTND * currencyRate;
              const period = isAnnual ? '/an' : '/mois';
              const monthlyEquivTND = isAnnual ? plan.price_annual / 12 : null;
              const monthlyEquiv = isAnnual ? (monthlyEquivTND * currencyRate).toFixed(2) : null;
              const savings = ((plan.price_monthly * 12 - plan.price_annual) * currencyRate).toFixed(0);

              return (
                <div key={plan.code} className={`price-card${plan.featured ? ' featured' : ''}`}>
                  {plan.badge && (
                    <div className="plan-badge" style={{ background: plan.badgeColor ? plan.badgeColor + '18' : 'var(--blue-soft)', color: plan.badgeColor || 'var(--blue)' }}>
                      {plan.badge}
                    </div>
                  )}
                  <div className="plan-name">{plan.label}</div>
                  <div className="price-main">
                    {price.toFixed(2).replace('.', ',')} <span>{currencySymbol}{period}</span>
                  </div>
                  {isAnnual
                    ? <div className="price-annual-note">≈ {monthlyEquiv} {currencySymbol}/mois · économisez {savings} {currencySymbol}</div>
                    : <div className="price-equiv">&nbsp;</div>
                  }
                  <div className="credit-pill">✦ {plan.credits.toLocaleString('fr-TN')} crédits IA/mois</div>
                  <ul className="price-features" style={{ flex: 1 }}>
                    {plan.features.map((f, fi) => <li key={fi}>{f}</li>)}
                  </ul>
                  {plan.disclaimer && <div className="price-disclaimer">{plan.disclaimer}</div>}
                  <Link to={`/contact-sales?plan=${plan.code}`} className="btn-primary" style={{ width: '100%', justifyContent: 'center', marginTop: '20px', background: plan.featured ? 'linear-gradient(135deg, var(--blue), var(--violet))' : 'var(--ink)', boxShadow: plan.featured ? '0 4px 20px rgba(79,70,229,0.35)' : 'none' }}>
                    Commencer →
                  </Link>
                </div>
              );
            })}
          </div>

          {detectedCurrency !== 'TND' && (
            <p style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '12px', marginTop: '12px' }}>
              Prix indicatifs convertis en {detectedCurrency} — la facturation s'effectue dans la devise de votre pays au moment du paiement.
            </p>
          )}

          <p style={{ textAlign: 'center', color: 'var(--muted)', fontSize: '14px', marginBottom: '16px', marginTop: '48px' }}>
            Crédits IA épuisés ? Rechargez sans changer de plan.
          </p>
          <div className="topup-grid">
            {[
              { label: '1 000 crédits', price: formatLandingAmount(5) },
              { label: '5 000 crédits', price: formatLandingAmount(20) },
              { label: '10 000 crédits', price: `${formatLandingAmount(35)} (+500 bonus)` },
            ].map((pack, i) => (
              <div key={i} className="topup-chip">{pack.label} — <span>{pack.price}</span></div>
            ))}
          </div>

          {/* Gold teaser */}
          <div style={{ marginTop: '56px', padding: '40px', background: 'linear-gradient(135deg, #1E1B4B 0%, #312E81 100%)', borderRadius: '24px', textAlign: 'center', color: '#fff' }}>
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', background: 'rgba(253,230,138,0.15)', border: '1px solid rgba(253,230,138,0.3)', borderRadius: '100px', padding: '6px 16px', fontSize: '13px', fontWeight: '700', color: '#FDE68A', marginBottom: '20px' }}>
              ✨ Plan Gold — Bientôt disponible
            </div>
            <h3 style={{ fontSize: 'clamp(22px, 3vw, 32px)', marginBottom: '14px', color: '#fff' }}>
              Promotions · Fidélité IA · B2B Portal · Et plus
            </h3>
            <p style={{ color: 'rgba(255,255,255,0.65)', maxWidth: '520px', margin: '0 auto 28px', lineHeight: '1.65', fontSize: '16px' }}>
              Accédez à l'ensemble des modules avancés dans un seul plan. Sur liste d'attente prioritaire.
            </p>
            <Link to="/login" className="btn-primary" style={{ margin: '0 auto', width: 'fit-content', background: 'linear-gradient(135deg, #D97706, #F59E0B)', boxShadow: '0 4px 20px rgba(217,119,6,0.4)' }}>
              Rejoindre la liste d'attente →
            </Link>
          </div>
        </div>
      </section>

      {/* ── About ── */}
      <section id="about" className="about" dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="about-inner">
            <div>
              <span className="section-badge">Notre mission</span>
              <h3 style={{ fontSize: 'clamp(28px, 3vw, 42px)', marginBottom: '20px', marginTop: '12px' }}>{t('about.title')}</h3>
              <p style={{ color: 'var(--muted)', lineHeight: '1.75', fontSize: '17px', marginBottom: '20px' }}>{t('about.p1')}</p>
              <p style={{ color: 'var(--muted)', lineHeight: '1.75', fontSize: '17px' }}>
                {t('about.p2_pre')}
                {(t('about.p2_highlights', { returnObjects: true }) || []).map((hl, i, arr) => (
                  <span key={i}>
                    <strong style={{ color: 'var(--ink)' }}>{hl}</strong>
                    {i < arr.length - 1 ? t('about.p2_join') : ''}
                  </span>
                ))}
                {t('about.p2_post')}
              </p>
            </div>
            <div className="about-trust">
              <h4>{t('about.trustTitle')}</h4>
              <p style={{ whiteSpace: 'pre-line' }}>{t('about.trustDesc')}</p>
            </div>
          </div>
        </div>
      </section>

      {/* ── Footer ── */}
      <footer dir={isRTL ? 'rtl' : 'ltr'}>
        <div className="container">
          <div className="footer-grid">
            <div className="footer-col">
              <div className="footer-logo">Auto<span style={{ color: 'var(--blue3)' }}>Commerce</span></div>
              <p style={{ lineHeight: '1.65', marginBottom: '20px' }}>{t('footer.tagline')}</p>
              <LanguageSwitcher variant="compact" />
            </div>
            <div className="footer-col">
              <h5>{t('footer.product')}</h5>
              <ul className="footer-links">
                {(t('footer.productLinks', { returnObjects: true }) || []).map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            </div>
            <div className="footer-col">
              <h5>{t('footer.company')}</h5>
              <ul className="footer-links">
                {(t('footer.companyLinks', { returnObjects: true }) || []).map((l, i) => <li key={i}>{l}</li>)}
              </ul>
            </div>
            <div className="footer-col">
              <h5>{t('footer.legal')}</h5>
              <ul className="footer-links">
                {(t('footer.legalLinks', { returnObjects: true }) || []).map((l, i) => <li key={i}>{l}</li>)}
                <li><Link to="/privacy" style={{ color: 'inherit' }}>Politique de confidentialité</Link></li>
              </ul>
            </div>
          </div>
          <hr className="footer-divider" />
          <div style={{ textAlign: 'center', fontSize: '13px' }}>
            {t('footer.copyright')}
          </div>
        </div>
      </footer>
    </>
  );
}
