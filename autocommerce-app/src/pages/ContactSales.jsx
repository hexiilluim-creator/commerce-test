import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';

const WHATSAPP_NUMBER = '21655919598';
const WHATSAPP_DISPLAY = '+216 55 919 598';

const PLAN_LABELS = {
  starter: 'Starter',
  business: 'Business',
  premium: 'Premium',
  pro_whatsapp: 'Pro WhatsApp',
};

export default function ContactSales() {
  const [searchParams] = useSearchParams();
  const planCode = searchParams.get('plan') || '';
  const planLabel = PLAN_LABELS[planCode.toLowerCase()] || null;
  const waMessage = encodeURIComponent(
    planLabel
      ? `Bonjour, je souhaite activer le plan ${planLabel} sur AutoCommerce.`
      : 'Bonjour, je souhaite en savoir plus sur les abonnements AutoCommerce.',
  );
  const waLink = `https://wa.me/${WHATSAPP_NUMBER}?text=${waMessage}`;

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#101828] p-4 sm:p-6">
      <div className="pointer-events-none absolute -left-24 -top-24 h-72 w-72 rounded-full bg-[#635bff]/30 blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 -right-20 h-96 w-96 rounded-full bg-[#c6923e]/20 blur-3xl" />
      <div className="relative w-full max-w-lg rounded-[30px] border border-white/10 bg-white p-6 text-center shadow-[0_32px_90px_rgba(0,0,0,.35)] sm:p-10">
        <div className="mx-auto mb-5 grid h-16 w-16 place-items-center rounded-[22px] bg-gradient-to-br from-[#8177ff] via-[#635bff] to-[#4f46e5] text-lg font-black tracking-tight text-white shadow-[0_14px_28px_rgba(99,91,255,.28)]">
          AC
        </div>
        <p className="mb-3 text-[11px] font-bold uppercase tracking-[.2em] text-[#635bff]">AutoCommerce Enterprise</p>
        {planLabel ? (
          <>
            <h1 className="text-balance text-2xl font-extrabold tracking-[-.04em] text-[#101828] sm:text-3xl">Vous avez choisi le plan {planLabel}</h1>
            <p className="mt-4 leading-7 text-[#667085]">Notre équipe vous accompagne pour finaliser votre activation par virement bancaire, en espèces ou via Flouci.</p>
          </>
        ) : (
          <>
            <h1 className="text-balance text-2xl font-extrabold tracking-[-.04em] text-[#101828] sm:text-3xl">Parlons de votre abonnement</h1>
            <p className="mt-4 leading-7 text-[#667085]">Contactez-nous pour choisir le plan adapté à votre activité et démarrer dans les meilleures conditions.</p>
          </>
        )}
        <a href={waLink} target="_blank" rel="noopener noreferrer" className="mt-7 flex w-full items-center justify-center gap-2 rounded-xl bg-[#25D366] px-5 py-3.5 text-sm font-extrabold text-white shadow-[0_12px_26px_rgba(37,211,102,.25)] transition hover:brightness-105 active:scale-[.98]">
          WhatsApp · {WHATSAPP_DISPLAY}
        </a>
        <p className="mt-4 text-xs leading-5 text-[#98a2b3]">Un compte administrateur active votre abonnement dès la confirmation du paiement.</p>
        <div className="my-7 h-px bg-[#e4e7ec]" />
        <p className="text-sm text-[#667085]">Vous avez déjà un compte ? <Link to="/login" className="font-bold text-[#635bff] hover:underline">Connectez-vous</Link></p>
        <Link to="/" className="mt-5 inline-flex text-sm font-semibold text-[#98a2b3] transition hover:text-[#344054]">← Retour à l’accueil</Link>
      </div>
    </div>
  );
}
