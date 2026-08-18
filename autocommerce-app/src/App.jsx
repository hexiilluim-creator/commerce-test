import CookieConsentBanner from './components/CookieConsentBanner';
import PrivacyPolicy from './pages/PrivacyPolicy';
import React from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { StoreProvider, useStore } from './context/StoreContext';
import { ToastProvider } from './context/ToastContext';
import { ConfirmProvider } from './context/ConfirmContext';
import Auth from './pages/Auth';
import ContactSales from './pages/ContactSales';
import Dashboard from './pages/Dashboard';
import DashboardCEO from './pages/DashboardCEO';
import DashboardCommercial from './pages/DashboardCommercial';
import DashboardIA from './pages/DashboardIA';
import Products from './pages/Products';
import Orders from './pages/Orders';
import Conversations from './pages/Conversations';
import Settings from './pages/Settings';
import SuperAdmin from './pages/SuperAdmin';
import Landing from './pages/Landing';
import Appointments from './pages/Appointments';
import StockSources from './pages/StockSources';
import SocialBroadcast from './pages/SocialBroadcast';
import StorefrontPageV2 from './pages/StorefrontPageV2';
import StorefrontCartPage from './pages/StorefrontCartPage';
import BusinessSetup from './pages/BusinessSetup';
import MyStorefront from './pages/MyStorefront';
import PaymentLinks from './pages/PaymentLinks';
import Promotions from './pages/Promotions';
import PredictiveRestocking from './pages/PredictiveRestocking';
import LoyaltyIA from './pages/LoyaltyIA';
import VisualBuilder from './pages/VisualBuilder';
import B2BPortal from './pages/B2BPortal';
import ResetPassword from './pages/ResetPassword';
import LanguageSwitcher from './components/LanguageSwitcher';
import {
  BarChart3,
  BarChartHorizontal,
  BriefcaseBusiness,
  CalendarDays,
  ChevronRight,
  CreditCard,
  HeartHandshake,
  LayoutDashboard,
  LogOut,
  Megaphone,
  Menu,
  MessageCircle,
  Package,
  Palette,
  PanelLeftClose,
  Settings2,
  ShieldCheck,
  ShoppingBag,
  Store,
  Tag,
  TrendingUp,
  X,
} from 'lucide-react';

function useNavItems(role) {
  const { t } = useTranslation();

  const ADMIN_NAV = [
    { path: '/dashboard', label: t('nav_items.dashboard'), icon: LayoutDashboard },
    { path: '/dashboard/ceo', label: t('nav_items.dashboard_ceo'), icon: BarChart3 },
    { path: '/dashboard/commercial', label: t('nav_items.dashboard_commercial'), icon: BarChartHorizontal },
    { path: '/dashboard/ia', label: t('nav_items.dashboard_ia'), icon: TrendingUp },
    { path: '/products', label: t('nav_items.products'), icon: Package },
    { path: '/orders', label: t('nav_items.orders'), icon: ShoppingBag },
    { path: '/appointments', label: t('nav_items.appointments'), icon: CalendarDays },
    { path: '/conversations', label: t('nav_items.conversations'), icon: MessageCircle },
    { path: '/social-broadcast', label: t('nav_items.social_broadcast'), icon: Megaphone, accent: true },
    { path: '/payment-links', label: t('nav_items.payment_links'), icon: CreditCard },
    { path: '/promotions', label: t('nav_items.promotions'), icon: Tag },
    { path: '/visual-builder', label: t('nav_items.visual_builder'), icon: Palette },
    { path: '/restocking', label: t('nav_items.predictive_restocking'), icon: TrendingUp },
    { path: '/loyalty-ia', label: t('nav_items.loyalty_ia'), icon: HeartHandshake },
    { path: '/b2b-portal', label: t('nav_items.b2b_portal'), icon: BriefcaseBusiness },
    { path: '/my-storefront', label: t('nav_items.my_storefront'), icon: Store },
    { path: '/settings', label: t('nav_items.settings'), icon: Settings2 },
  ];

  const SUPER_ADMIN_NAV = [{ path: '/super-admin', label: t('nav_items.super_admin'), icon: ShieldCheck }];
  return role === 'super_admin' ? SUPER_ADMIN_NAV : ADMIN_NAV;
}

function FullScreenLoader() {
  const { t } = useTranslation();
  return (
    <div className="min-h-screen grid place-items-center bg-[#f7f8fc] text-[#667085]">
      <div className="flex flex-col items-center gap-3">
        <div className="h-10 w-10 animate-spin rounded-full border-4 border-[#e4e7ec] border-t-[#635bff]" />
        <p className="text-sm font-medium">{t('common.loading')}</p>
      </div>
    </div>
  );
}

function Brand({ compact = false }) {
  return (
    <div className={`flex items-center gap-3 ${compact ? 'justify-center' : ''}`}>
      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-[14px] bg-gradient-to-br from-[#8177ff] via-[#635bff] to-[#4f46e5] text-sm font-black text-white shadow-[0_10px_24px_rgba(99,91,255,.3)]">
        AC
      </div>
      {!compact && (
        <div className="min-w-0">
          <p className="truncate text-[15px] font-extrabold tracking-[-.03em] text-white">AutoCommerce</p>
          <p className="mt-0.5 text-[10px] font-semibold uppercase tracking-[.18em] text-white/45">Enterprise suite</p>
        </div>
      )}
    </div>
  );
}

function Layout() {
  const { isAuthenticated, role, logout, authReady } = useStore();
  const navigate = useNavigate();
  const { t, i18n } = useTranslation();
  const isRTL = i18n.language === 'ar';
  const [sidebarOpen, setSidebarOpen] = React.useState(false);
  const navItems = useNavItems(role);

  if (!authReady) return <FullScreenLoader />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  return (
    <div className="min-h-screen bg-[#f7f8fc]" dir={isRTL ? 'rtl' : 'ltr'}>
      <header className="fixed inset-x-0 top-0 z-30 border-b border-white/10 bg-[#101828]/95 px-4 py-3 shadow-lg backdrop-blur-xl lg:hidden">
        <div className="flex items-center justify-between gap-3">
          <Brand />
          <div className="flex items-center gap-2">
            <LanguageSwitcher variant="compact" />
            <button
              type="button"
              onClick={() => setSidebarOpen((open) => !open)}
              className="grid h-10 w-10 place-items-center rounded-xl border border-white/15 text-white transition hover:bg-white/10 active:scale-95"
              aria-label={sidebarOpen ? 'Fermer le menu' : 'Ouvrir le menu'}
            >
              {sidebarOpen ? <X size={20} /> : <Menu size={20} />}
            </button>
          </div>
        </div>
      </header>

      <aside
        className={`fixed inset-y-0 z-40 flex w-[282px] flex-col border-white/10 bg-[#101828] text-white shadow-2xl transition-transform duration-200 lg:translate-x-0 ${isRTL ? 'right-0 border-l' : 'left-0 border-r'} ${sidebarOpen ? 'translate-x-0' : isRTL ? 'translate-x-full' : '-translate-x-full'}`}
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-5">
          <Brand />
          <button type="button" onClick={() => setSidebarOpen(false)} className="grid h-9 w-9 place-items-center rounded-xl text-white/45 hover:bg-white/10 hover:text-white lg:hidden" aria-label="Fermer le menu">
            <PanelLeftClose size={18} />
          </button>
        </div>

        <div className="px-5 pb-3 pt-5">
          <p className="mb-2 text-[10px] font-bold uppercase tracking-[.18em] text-white/35">Workspace</p>
          <div className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/[.06] px-3 py-3">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-[#c6923e]/15 text-sm font-bold text-[#e5bd75]">{(role || 'A').slice(0, 1).toUpperCase()}</div>
            <div className="min-w-0">
              <p className="truncate text-xs font-bold text-white">{role?.replace('_', ' ') || 'Admin'}</p>
              <p className="mt-0.5 truncate text-[11px] text-white/45">Compte sécurisé</p>
            </div>
            <ChevronRight size={15} className="ml-auto text-white/30" />
          </div>
        </div>

        <nav className="scrollbar-hide flex-1 space-y-1 overflow-y-auto px-3 pb-4" aria-label="Navigation principale">
          {navItems.map(({ path, label, icon: Icon, accent }) => (
            <NavLink
              key={path}
              to={path}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) => `group flex min-h-11 items-center gap-3 rounded-xl px-3.5 py-2.5 text-[13px] font-semibold transition-all ${isActive ? (accent ? 'bg-gradient-to-r from-violet-500 to-fuchsia-500 text-white shadow-lg shadow-violet-900/30' : 'bg-white text-[#101828] shadow-lg shadow-black/10') : accent ? 'text-fuchsia-200 hover:bg-fuchsia-500/10' : 'text-white/58 hover:bg-white/[.08] hover:text-white'}`}
            >
              {({ isActive }) => (
                <>
                  <Icon size={17} strokeWidth={isActive ? 2.5 : 2} className={isActive ? '' : 'opacity-75'} />
                  <span className="min-w-0 flex-1 truncate">{label}</span>
                  {isActive && <ChevronRight size={14} className="opacity-45" />}
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="space-y-3 border-t border-white/10 p-4">
          <LanguageSwitcher variant="sidebar" />
          <button type="button" onClick={handleLogout} className="flex w-full items-center gap-3 rounded-xl px-3.5 py-2.5 text-left text-xs font-bold text-rose-200 transition hover:bg-rose-500/10 hover:text-rose-100">
            <LogOut size={16} />
            {t('sidebar.logout')}
          </button>
        </div>
      </aside>

      {sidebarOpen && <button type="button" aria-label="Fermer le menu" className="fixed inset-0 z-30 bg-[#101828]/55 backdrop-blur-sm lg:hidden" onClick={() => setSidebarOpen(false)} />}

      <main className="min-w-0 overflow-x-hidden px-4 pb-8 pt-20 lg:ml-[282px] lg:px-8 lg:pb-10 lg:pt-8 xl:px-10">
        <div className="mx-auto flex max-w-[1440px] items-center justify-between gap-4 border-b border-[#e4e7ec] pb-6 lg:mb-8">
          <div>
            <p className="text-[11px] font-bold uppercase tracking-[.18em] text-[#98a2b3]">AutoCommerce / Console</p>
            <p className="mt-1 text-sm font-semibold text-[#344054]">Pilotage intelligent de votre activité</p>
          </div>
          <div className="hidden items-center gap-3 lg:flex">
            <LanguageSwitcher variant="compact" />
            <div className="h-9 w-9 rounded-full bg-gradient-to-br from-[#dcd8ff] to-[#f2e5c8] ring-4 ring-white" aria-hidden="true" />
          </div>
        </div>
        <Routes>
          {role === 'super_admin' ? (
            <>
              <Route path="/super-admin" element={<SuperAdmin />} />
              <Route path="*" element={<Navigate to="/super-admin" replace />} />
            </>
          ) : (
            <>
              <Route path="/dashboard" element={<Dashboard />} />
              <Route path="/dashboard/ceo" element={<DashboardCEO />} />
              <Route path="/dashboard/commercial" element={<DashboardCommercial />} />
              <Route path="/dashboard/ia" element={<DashboardIA />} />
              <Route path="/products" element={<Products />} />
              <Route path="/appointments" element={<Navigate to="/appointments/agenda" replace />} />
              <Route path="/appointments/agenda" element={<Appointments initialTab="agenda" />} />
              <Route path="/appointments/services" element={<Appointments initialTab="services" />} />
              <Route path="/appointments/availability" element={<Appointments initialTab="availability" />} />
              <Route path="/appointments/settings" element={<Appointments initialTab="settings" />} />
              <Route path="/orders" element={<Orders />} />
              <Route path="/conversations" element={<Conversations />} />
              <Route path="/settings" element={<Navigate to="/settings/store" replace />} />
              <Route path="/settings/store" element={<Settings initialTab="store" />} />
              <Route path="/settings/whatsapp" element={<Settings initialTab="whatsapp" />} />
              <Route path="/settings/payments" element={<Settings initialTab="payments" />} />
              <Route path="/settings/ai" element={<Settings initialTab="agent" />} />
              <Route path="/settings/social" element={<Settings initialTab="social" />} />
              <Route path="/settings/users" element={<Settings initialTab="users" />} />
              <Route path="/stock-sources" element={<StockSources />} />
              <Route path="/social-broadcast" element={<SocialBroadcast />} />
              <Route path="/payment-links" element={<PaymentLinks />} />
              <Route path="/promotions" element={<Promotions />} />
              <Route path="/visual-builder" element={<VisualBuilder />} />
              <Route path="/restocking" element={<PredictiveRestocking />} />
              <Route path="/loyalty-ia" element={<LoyaltyIA />} />
              <Route path="/b2b-portal" element={<B2BPortal />} />
              <Route path="/my-storefront" element={<MyStorefront />} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </>
          )}
        </Routes>
      </main>
    </div>
  );
}

function PublicRoute() {
  const { isAuthenticated, role, authReady } = useStore();
  if (!authReady) return <FullScreenLoader />;
  if (isAuthenticated) return <Navigate to={role === 'super_admin' ? '/super-admin' : '/dashboard'} replace />;
  return <Auth />;
}

export default function App() {
  return (
    <StoreProvider>
      <ToastProvider>
        <ConfirmProvider>
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
            <Routes>
              <Route path="/" element={<Landing />} />
              <Route path="/login" element={<PublicRoute />} />
              <Route path="/contact-sales" element={<ContactSales />} />
              <Route path="/reset-password" element={<ResetPassword />} />
              <Route path="/privacy" element={<PrivacyPolicy />} />
              <Route path="/store/:storeId" element={<StorefrontPageV2 />} />
              <Route path="/cart" element={<StorefrontCartPage />} />
              <Route path="/boutique/:storeId" element={<StorefrontPageV2 />} />
              <Route path="/setup" element={<BusinessSetup />} />
              <Route path="/*" element={<Layout />} />
            </Routes>
            <CookieConsentBanner />
          </BrowserRouter>
        </ConfirmProvider>
      </ToastProvider>
    </StoreProvider>
  );
}
