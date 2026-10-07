// Gestion du Thème Clair / Sombre
function initTheme() {
  const savedTheme = localStorage.getItem('volalerte_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  updateThemeIcon(savedTheme);
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('volalerte_theme', next);
  updateThemeIcon(next);
}

function updateThemeIcon(theme) {
  const btn = document.getElementById('theme-toggle-btn');
  if (btn) {
    btn.innerHTML = theme === 'dark' ? '☀️' : '🌙';
    btn.title = theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre';
  }
}

// Notifications Toasts
function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span>🔔</span> <span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.remove();
  }, 4000);
}

// Lancement immédiat de la vérification
async function runVerificationNow() {
  const btn = document.getElementById('btn-run-now');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = '⏳ Vérification en cours...';
  }
  showToast('Lancement du relevé des vols...', 'info');

  try {
    const res = await fetch('/api/run-now', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'Vérification lancée !', 'success');
    setTimeout(() => {
      window.location.reload();
    }, 2500);
  } catch (err) {
    showToast('Erreur lors du lancement de la vérification', 'danger');
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = '⚡ Vérifier maintenant';
    }
  }
}

// Enregistrement du Service Worker PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/static/js/sw.js')
      .then(reg => console.log('PWA Service Worker actif'))
      .catch(err => console.log('Erreur SW:', err));
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  const themeBtn = document.getElementById('theme-toggle-btn');
  if (themeBtn) {
    themeBtn.addEventListener('click', toggleTheme);
  }

  const runBtn = document.getElementById('btn-run-now');
  if (runBtn) {
    runBtn.addEventListener('click', runVerificationNow);
  }
});
