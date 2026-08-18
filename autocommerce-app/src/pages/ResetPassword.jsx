import React, { useState, useEffect } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { apiPost, extractErrorMessage } from '../api';

export default function ResetPassword() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const token = searchParams.get('token') || '';

  const [form, setForm] = useState({ newPassword: '', confirmPassword: '' });
  const [showPwd, setShowPwd] = useState(false);
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) setError('Lien invalide — aucun token trouvé. Veuillez refaire la demande.');
  }, [token]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.newPassword !== form.confirmPassword) {
      setError('Les mots de passe ne correspondent pas.');
      return;
    }
    if (form.newPassword.length < 8) {
      setError('Le mot de passe doit contenir au moins 8 caractères.');
      return;
    }
    setLoading(true);
    try {
      await apiPost('/auth/reset-password', {
        token,
        new_password: form.newPassword,
        confirm_password: form.confirmPassword,
      });
      setSuccess(true);
      setTimeout(() => navigate('/login'), 3000);
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-900 to-purple-900 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-8">
        {/* Header */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center w-16 h-16 bg-indigo-100 rounded-2xl mb-4">
            <span className="text-3xl">🔐</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">
            {success ? 'Mot de passe mis à jour' : 'Nouveau mot de passe'}
          </h1>
          <p className="text-gray-500 text-sm mt-1">
            {success
              ? 'Redirection vers la connexion…'
              : 'Choisissez un nouveau mot de passe sécurisé'}
          </p>
        </div>

        {success ? (
          <div className="space-y-4">
            <div className="bg-green-50 border border-green-200 rounded-xl p-4 text-center">
              <div className="text-3xl mb-2">✅</div>
              <p className="text-green-700 font-medium">Mot de passe modifié avec succès !</p>
              <p className="text-green-600 text-sm mt-1">
                Vous serez redirigé automatiquement dans 3 secondes.
              </p>
            </div>
            <Link
              to="/login"
              className="block w-full text-center bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-2.5 rounded-xl transition-colors"
            >
              Se connecter maintenant
            </Link>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* New password */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Nouveau mot de passe
              </label>
              <div className="relative">
                <input
                  type={showPwd ? 'text' : 'password'}
                  required
                  minLength={8}
                  value={form.newPassword}
                  onChange={(e) => setForm({ ...form, newPassword: e.target.value })}
                  className="w-full px-4 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none"
                  placeholder="Minimum 8 caractères"
                  dir="ltr"
                  disabled={!token}
                />
                <button
                  type="button"
                  onClick={() => setShowPwd(!showPwd)}
                  className="absolute right-3 top-2.5 text-gray-400 hover:text-gray-600"
                  tabIndex={-1}
                >
                  {showPwd ? '👁️' : '🙈'}
                </button>
              </div>
            </div>

            {/* Confirm password */}
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Confirmer le mot de passe
              </label>
              <input
                type={showPwd ? 'text' : 'password'}
                required
                minLength={8}
                value={form.confirmPassword}
                onChange={(e) => setForm({ ...form, confirmPassword: e.target.value })}
                className="w-full px-4 py-2.5 border border-gray-300 rounded-xl focus:ring-2 focus:ring-indigo-500 outline-none"
                placeholder="Répétez votre mot de passe"
                dir="ltr"
                disabled={!token}
              />
            </div>

            {/* Password strength hint */}
            {form.newPassword && (
              <div className="flex gap-1">
                {[...Array(4)].map((_, i) => (
                  <div
                    key={i}
                    className={`h-1 flex-1 rounded-full transition-colors ${
                      form.newPassword.length >= (i + 1) * 3
                        ? form.newPassword.length >= 12
                          ? 'bg-green-500'
                          : form.newPassword.length >= 8
                          ? 'bg-yellow-400'
                          : 'bg-red-400'
                        : 'bg-gray-200'
                    }`}
                  />
                ))}
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="text-red-600 text-sm bg-red-50 border border-red-200 p-3 rounded-xl">
                {error}
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading || !token}
              className="w-full bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300 text-white font-semibold py-2.5 rounded-xl transition-colors"
            >
              {loading ? 'Mise à jour…' : 'Définir le nouveau mot de passe'}
            </button>

            {/* Back link */}
            <Link
              to="/login"
              className="block text-center text-sm text-gray-500 hover:text-indigo-600 hover:underline"
            >
              ← Retour à la connexion
            </Link>
          </form>
        )}
      </div>
    </div>
  );
}
