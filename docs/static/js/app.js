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
    const lang = window.getVolAlerteLang ? window.getVolAlerteLang() : 'fr';
    if (lang === 'zh') {
      btn.title = theme === 'dark' ? '切换浅色模式' : '切换深色模式';
    } else if (lang === 'en') {
      btn.title = theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode';
    } else {
      btn.title = theme === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre';
    }
  }
}

// ============================================================================
// SYSTÈME MULTILINGUE COMPLET : FRANÇAIS (fr) / ENGLISH (en) / 中文 (zh)
// ============================================================================
const I18N_DICT = {
  fr: {
    nav_dashboard: 'Tableau de bord',
    nav_radar: 'Radar Bons Plans',
    nav_alerts: 'Alertes',
    nav_settings: 'Réglages',
    btn_run_now: '⚡ Vérifier maintenant',
    btn_running: '⏳ Vérification en cours...',
    demo_banner: '<b>Mode Démo Actif</b> : Données et relevés simulés réalistes. Aucune clé API requise. Vous pouvez le désactiver dans les Réglages.',
    footer_text: 'VolAlerte • Suivi autonome de prix avec calcul réel bagages inclus • 100% local sur votre PC'
  },
  en: {
    nav_dashboard: 'Dashboard',
    nav_radar: 'Flight Deals Radar',
    nav_alerts: 'Alerts',
    nav_settings: 'Settings',
    btn_run_now: '⚡ Check Prices Now',
    btn_running: '⏳ Checking flights...',
    demo_banner: '<b>Demo Mode Active</b>: Realistic flight & fare data. No API key required. You can change this in Settings.',
    footer_text: 'VolAlerte • Autonomous Flight Price Tracker with Real Baggage & High-Speed Train Calculation'
  },
  zh: {
    nav_dashboard: '监控面板',
    nav_radar: '特价机票雷达',
    nav_alerts: '低价提醒',
    nav_settings: '系统设置',
    btn_run_now: '⚡ 立即刷新价格',
    btn_running: '⏳ 正在查询航班...',
    demo_banner: '<b>演示模式已启用</b>：真实航线与含行李/高铁比价数据，无需 API 密钥，可在“系统设置”中管理。',
    footer_text: 'VolAlerte • 智能机票与高铁联运比价监控系统（含真实手提/托运行李费用计算）'
  }
};

// Traduction des villes & aéroports
const CITY_MAP = {
  en: {
    "Hanoï": "Hanoi",
    "Pékin": "Beijing",
    "Séoul": "Seoul",
    "Singapour": "Singapore",
    "Manille": "Manila",
    "Ho Chi Minh": "Ho Chi Minh City",
    "Thaïlande": "Thailand",
    "Viêt Nam": "Vietnam",
    "Corée du Sud": "South Korea",
    "Japon": "Japan",
    "Malaisie": "Malaysia",
    "Indonésie": "Indonesia",
    "Taïwan": "Taiwan",
    "Chine": "China",
    "France": "France",
    "Asie du Sud-Est": "Southeast Asia",
    "Asie de l'Est": "East Asia",
    "Europe": "Europe"
  },
  zh: {
    "Zhengzhou": "郑州",
    "Pékin": "北京",
    "Shanghai": "上海",
    "Xi'an": "西安",
    "Wuhan": "武汉",
    "Shijiazhuang": "石家庄",
    "Paris": "巴黎",
    "Nantes": "南特",
    "Hanoï": "河内",
    "Hanoi": "河内",
    "Chiang Mai": "清迈",
    "Bangkok": "曼谷",
    "Phuket": "普吉岛",
    "Ho Chi Minh": "胡志明市",
    "Da Nang": "岘港",
    "Séoul": "首尔",
    "Tokyo": "东京",
    "Osaka": "大阪",
    "Fukuoka": "福冈",
    "Singapour": "新加坡",
    "Kuala Lumpur": "吉隆坡",
    "Penang": "槟城",
    "Manille": "马尼拉",
    "Cebu": "宿务",
    "Bali": "巴厘岛",
    "Jakarta": "雅加达",
    "Phnom Penh": "金边",
    "Siem Reap": "暹粒",
    "Vientiane": "万象",
    "Luang Prabang": "琅勃拉邦",
    "Hong Kong": "香港",
    "Macao": "澳门",
    "Taipei": "台北",
    "Jeju": "济州岛",
    "Busan": "釜山",
    "Colombo": "科伦坡",
    "Katmandou": "加德满都",
    "Thaïlande": "泰国",
    "Viêt Nam": "越南",
    "Corée du Sud": "韩国",
    "Japon": "日本",
    "Malaisie": "马来西亚",
    "Indonésie": "印度尼西亚",
    "Philippines": "菲律宾",
    "Cambodge": "柬埔寨",
    "Laos": "老挝",
    "Taïwan": "中国台湾",
    "Chine": "中国",
    "France": "法国",
    "Asie du Sud-Est": "东南亚",
    "Asie de l'Est": "东亚/港澳台",
    "Europe": "欧洲/法国"
  }
};

// Remplacements exacts ou partiels de chaînes UI (du plus spécifique au plus général)
const PHRASE_RULES = {
  en: [
    ["📡 Radar Bons Plans & Aéroports Proches", "📡 Flight Deals Radar & Nearby Airports"],
    ["Choisis une destination (Asie ou France : Paris / Nantes) pour voir quel aéroport proche de chez toi (Zhengzhou + TGV) est le moins cher", "Pick a destination (Asia or France: Paris / Nantes) to see which nearby airport (Zhengzhou + High-Speed Train) is the cheapest"],
    ["🏠 Chez moi (Départ)", "🏠 My Home (Origin)"],
    ["🎯 Pick une Destination", "🎯 Pick a Destination"],
    ["🌍 Toutes les destinations", "🌍 All destinations"],
    ["📅 Mois", "📅 Month"],
    ["Octobre 2026", "October 2026"],
    ["Novembre 2026", "November 2026"],
    ["Décembre 2026", "December 2026"],
    ["Janvier 2027", "January 2027"],
    ["Février 2027", "February 2027"],
    ["Mars 2027", "March 2027"],
    ["📆 Date précise", "📆 Exact Date"],
    ["🧳 Bagages", "🧳 Baggage"],
    ["Cabine incluse", "Cabin bag included"],
    ["Soute 23 kg", "Checked bag 23 kg"],
    ["Sans bagage", "No baggage"],
    ["🛑 Escales", "🛑 Stops"],
    ["Toutes", "Any"],
    ["Direct (0 escale)", "Direct (Nonstop)"],
    ["Max 1 escale", "Max 1 stop"],
    ["Max 2 escales", "Max 2 stops"],
    ["⏱️ Durée max", "⏱️ Max Duration"],
    ["Sans limite", "No limit"],
    ["🔍 Chercher", "🔍 Search"],
    ["✅ Prix & vols mis à jour", "✅ Prices & flights updated"],
    ["🚅 Croiser les aéroports TGV proches (Xi'an 1h30, Wuhan 1h45, Shijiazhuang 1h20, Pékin 2h15)", "🚅 Include nearby High-Speed Train airports (Xi'an 1h30, Wuhan 1h45, Shijiazhuang 1h20, Beijing 2h15)"],
    ["🌍 Tous les prix", "🌍 All prices"],
    ["🏆 Meilleur Aéroport Proche", "🏆 Best Nearby Airport"],
    ["Trajet (Train + Vol)", "Journey (Train + Flight)"],
    ["Prix Vol / Total avec TGV", "Flight Fare / Total with Train"],
    ["Action", "Book"],
    ["🏆 Meilleur départ proche :", "🏆 Best nearby departure:"],
    ["🏠 Sur place (0 € TGV)", "🏠 Local airport (€0 train)"],
    ["(Sur place)", "(Local)"],
    ["Total Vol + TGV :", "Flight + Train Total:"],
    ["Durée totale (Train + Vol) :", "Total duration (Train + Flight):"],
    ["🏆 Quel aéroport choisir pas loin de chez moi ?", "🏆 Which nearby airport is cheapest from my home?"],
    ["aéroports comparés : Vol + TGV & Prix Moyen", "airports compared: Flight + Train & Average Price"],
    ["Aéroport & TGV", "Airport & Train"],
    ["Moyenne", "Avg Fare"],
    ["Billet Vol", "Flight Fare"],
    ["Total (Vol+TGV)", "Total (Flight+Train)"],
    ["Lien", "Links"],
    ["🏠 0 € de train", "🏠 €0 train"],
    ["🚅 TGV +", "🚅 Train +"],
    ["🎒 Sans", "🎒 No bag"],
    ["🧳 Cabine", "🧳 Cabin"],
    ["📦 Soute", "📦 Checked"],
    ["1 escale", "1 stop"],
    ["2 escales", "2 stops"],
    ["1 esc.", "1 stop"],
    ["2 esc.", "2 stops"],
    ["Cie)", "Airline)"],
    ["📊 Mes trajets sous surveillance", "📊 My Monitored Routes"],
    ["Suivi historique des prix et seuils d'alerte • Pour explorer toutes les destinations et comparer les aéroports TGV, ouvre le", "Historical price tracking & alert thresholds • To explore all destinations and compare High-Speed Train airports, open the"],
    ["📡 Radar Bons Plans →", "📡 Flight Deals Radar →"],
    ["Moy. mois :", "Monthly avg:"],
    ["🔔 Seuil alerte :", "🔔 Alert threshold:"],
    ["🚅 Bon plan TGV : départ", "🚅 High-Speed Train deal: depart"],
    ["TGV inclus", "Train included"],
    ["📈 Courbe & Historique", "📈 Price Chart & History"],
    ["🏆 Comparer 5 aéroports", "🏆 Compare 5 Airports"],
    ["🔔 Alertes Déclenchées", "🔔 Triggered Price Alerts"],
    ["Historique des notifications envoyées lorsque le prix total et les conditions statistiques étaient au plus bas.", "History of notifications sent when total price and statistical conditions hit their lowest point."],
    ["Aucune alerte pour l'instant", "No alerts triggered yet"],
    ["⚙️ Paramètres & Gestion des Trajets", "⚙️ Settings & Route Management"],
    ["Aucun vol ne correspond à ces filtres.", "No flights match these filters."],
    ["Réinitialiser", "Reset"],
    [" — dès ", " — from "]
  ],
  zh: [
    ["📡 Radar Bons Plans & Aéroports Proches", "📡 特价机票雷达 & 周边高铁机场比价"],
    ["Choisis une destination (Asie ou France : Paris / Nantes) pour voir quel aéroport proche de chez toi (Zhengzhou + TGV) est le moins cher", "选择目的地（亚洲或法国：巴黎 / 南特），自动对比郑州本地与周边高铁机场（西安/武汉/石家庄/北京）含高铁总价"],
    ["🏠 Chez moi (Départ)", "🏠 出发地（常住城市）"],
    ["🎯 Pick une Destination", "🎯 选择目的地"],
    ["🌍 Toutes les destinations", "🌍 全部目的地"],
    ["📅 Mois", "📅 出发月份"],
    ["Octobre 2026", "2026年10月"],
    ["Novembre 2026", "2026年11月"],
    ["Décembre 2026", "2026年12月"],
    ["Janvier 2027", "2027年1月"],
    ["Février 2027", "2027年2月"],
    ["Mars 2027", "2027年3月"],
    ["📆 Date précise", "📆 精确出发日期"],
    ["🧳 Bagages", "🧳 行李选项"],
    ["Cabine incluse", "含手提行李"],
    ["Soute 23 kg", "含 23kg 托运行李"],
    ["Sans bagage", "无免费行李额度"],
    ["🛑 Escales", "🛑 中转次数"],
    ["Toutes", "不限中转"],
    ["Direct (0 escale)", "仅看直飞 (0中转)"],
    ["Max 1 escale", "最多 1 次中转"],
    ["Max 2 escales", "最多 2 次中转"],
    ["⏱️ Durée max", "⏱️ 最长总耗时"],
    ["Sans limite", "不限时长"],
    ["Max 6h", "最多 6 小时"],
    ["Max 8h", "最多 8 小时"],
    ["Max 12h", "最多 12 小时"],
    ["Max 16h", "最多 16 小时"],
    ["🔍 Chercher", "🔍 搜索比价"],
    ["✅ Prix & vols mis à jour", "✅ 航班与价格已更新"],
    ["🚅 Croiser les aéroports TGV proches (Xi'an 1h30, Wuhan 1h45, Shijiazhuang 1h20, Pékin 2h15)", "🚅 智能跨城对比周边高铁机场（西安 1.5h、武汉 1h45、石家庄 1h20、北京 2h15）"],
    ["🌍 Tous les prix", "🌍 全部价格"],
    ["💰 < 100 €", "💰 低于 100 €"],
    ["Destination", "目的地"],
    ["🏆 Meilleur Aéroport Proche", "🏆 最优出发机场（本地/高铁）"],
    ["Trajet (Train + Vol)", "行程耗时（高铁+航班）"],
    ["Prix Vol / Total avec TGV", "机票价格 / 含高铁总价"],
    ["Action", "预订"],
    ["🏆 Meilleur départ proche :", "🏆 最划算出发机场："],
    ["🏠 Sur place (0 € TGV)", "🏠 本地直接出发（0 € 高铁费）"],
    ["(Sur place)", "(本地直发)"],
    ["Total Vol + TGV :", "机票 + 高铁总计："],
    ["Durée totale (Train + Vol) :", "总耗时（高铁+飞行）："],
    ["🏆 Quel aéroport choisir pas loin de chez moi ?", "🏆 距离我家哪个机场出发最便宜？"],
    ["aéroports comparés : Vol + TGV & Prix Moyen", "大周边机场比价：机票+高铁总价 & 历史均价"],
    ["Aéroport & TGV", "出发机场 & 高铁"],
    ["Moyenne", "历史均价"],
    ["Billet Vol", "机票单价"],
    ["Total (Vol+TGV)", "总计 (机票+高铁)"],
    ["Lien", "预订链接"],
    ["🏠 0 € de train", "🏠 本地出发 (0 € 高铁)"],
    ["🚅 TGV +", "🚅 高铁 +"],
    ["🎒 Sans", "🎒 无行李"],
    ["🧳 Cabine", "🧳 手提"],
    ["📦 Soute", "📦 托运"],
    ["Direct", "直飞"],
    ["1 escale", "1次中转"],
    ["2 escales", "2次中转"],
    ["1 esc.", "1次中转"],
    ["2 esc.", "2次中转"],
    ["Cie)", "官网价)"],
    ["📊 Mes trajets sous surveillance", "📊 我的监控航线"],
    ["Suivi historique des prix et seuils d'alerte • Pour explorer toutes les destinations et comparer les aéroports TGV, ouvre le", "历史价格趋势与低价提醒阈值 • 如需探索全部亚洲/法国目的地并对比周边高铁机场，请打开"],
    ["📡 Radar Bons Plans →", "📡 特价机票雷达 →"],
    ["Moy. mois :", "月均价："],
    ["🔔 Seuil alerte :", "🔔 提醒阈值："],
    ["🚅 Bon plan TGV : départ", "🚅 高铁联运特惠：从"],
    ["TGV inclus", "含高铁票"],
    ["📈 Courbe & Historique", "📈 历史价格趋势"],
    ["🏆 Comparer 5 aéroports", "🏆 对比周边 5 大机场"],
    ["🔔 Alertes Déclenchées", "🔔 已触发的低价提醒"],
    ["Historique des notifications envoyées lorsque le prix total et les conditions statistiques étaient au plus bas.", "当含行李/高铁总价达到历史低位或低于设定阈值时触发的提醒记录。"],
    ["Aucune alerte pour l'instant", "暂无低价提醒记录"],
    ["⚙️ Paramètres & Gestion des Trajets", "⚙️ 系统设置与监控航线管理"],
    ["Aucun vol ne correspond à ces filtres.", "没有符合当前筛选条件的航班。"],
    ["Réinitialiser", "重置筛选"],
    [" — dès ", " — 低至 "]
  ]
};

window.getVolAlerteLang = function() {
  const q = new URLSearchParams(window.location.search);
  const qLang = q.get('lang');
  if (qLang && (qLang === 'fr' || qLang === 'en' || qLang === 'zh')) {
    localStorage.setItem('volalerte_lang', qLang);
    return qLang;
  }
  const saved = localStorage.getItem('volalerte_lang');
  if (saved === 'en' || saved === 'zh' || saved === 'fr') return saved;
  return 'fr';
};

window.translateCityText = function(text, lang) {
  if (!text || lang === 'fr') return text;
  let out = text;
  const map = CITY_MAP[lang] || {};
  Object.keys(map).forEach(function(k) {
    if (out.indexOf(k) !== -1) {
      out = out.split(k).join(map[k]);
    }
  });
  return out;
};

window.formatDateByLang = function(isoDate, lang) {
  if (!isoDate || isoDate.length < 10) return isoDate || '';
  const parts = isoDate.slice(0, 10).split('-');
  const y = parseInt(parts[0], 10), m = parseInt(parts[1], 10) - 1, d = parseInt(parts[2], 10);
  const dt = new Date(y, m, d);
  if (isNaN(dt.getTime())) return isoDate;
  const l = lang || window.getVolAlerteLang();
  if (l === 'zh') {
    const daysZh = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'];
    return y + '年' + (m + 1) + '月' + d + '日 ' + daysZh[dt.getDay()];
  }
  if (l === 'en') {
    const daysEn = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const monthsEn = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return daysEn[dt.getDay()] + ', ' + monthsEn[m] + ' ' + d + ', ' + y;
  }
  const daysFr = ['Dim.', 'Lun.', 'Mar.', 'Mer.', 'Jeu.', 'Ven.', 'Sam.'];
  const monthsFr = ['janv.', 'févr.', 'mars', 'avr.', 'mai', 'juin', 'juil.', 'août', 'sept.', 'oct.', 'nov.', 'déc.'];
  return daysFr[dt.getDay()] + ' ' + d + ' ' + monthsFr[m] + ' ' + y;
};

function translateString(str, lang) {
  if (!str || lang === 'fr') return str;
  let out = str;
  const rules = PHRASE_RULES[lang] || [];
  for (let i = 0; i < rules.length; i++) {
    const from = rules[i][0];
    const to = rules[i][1];
    if (out.indexOf(from) !== -1) {
      out = out.split(from).join(to);
    }
  }
  out = window.translateCityText(out, lang);
  // Traduire les dates françaises "Dim. 15 nov. 2026"
  if (lang === 'zh') {
    out = out.replace(/TGV ([A-Za-zÀ-ÿ' -]+)\s*➔\s*([A-Za-zÀ-ÿ' -]+)/g, function(_, a, b) {
      return '高铁 ' + window.translateCityText(a, 'zh') + ' ➔ ' + window.translateCityText(b, 'zh');
    });
  } else if (lang === 'en') {
    out = out.replace(/TGV ([A-Za-zÀ-ÿ' -]+)\s*➔\s*([A-Za-zÀ-ÿ' -]+)/g, function(_, a, b) {
      return 'High-Speed Train ' + window.translateCityText(a, 'en') + ' ➔ ' + window.translateCityText(b, 'en');
    });
  }
  return out;
}

// Sauvegarder tous les noeuds texte originaux une seule fois pour pouvoir basculer FR <-> EN <-> ZH à volonté
const TRACKED_TEXT_NODES = [];
const TRACKED_ATTR_ELS = [];

function collectTranslatableNodes() {
  if (window._volalerteNodesCollected) return;
  window._volalerteNodesCollected = true;

  const walker = document.createTreeWalker(
    document.body,
    NodeFilter.SHOW_TEXT,
    {
      acceptNode: function(node) {
        if (!node.parentElement) return NodeFilter.FILTER_REJECT;
        const tag = node.parentElement.tagName;
        if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'NOSCRIPT') {
          return NodeFilter.FILTER_REJECT;
        }
        if (!node.nodeValue || !node.nodeValue.trim()) {
          return NodeFilter.FILTER_REJECT;
        }
        return NodeFilter.FILTER_ACCEPT;
      }
    }
  );

  let n;
  while ((n = walker.nextNode())) {
    TRACKED_TEXT_NODES.push({
      node: n,
      orig: n.nodeValue
    });
  }

  document.querySelectorAll('[title], [placeholder]').forEach(function(el) {
    TRACKED_ATTR_ELS.push({
      el: el,
      title: el.getAttribute('title'),
      placeholder: el.getAttribute('placeholder')
    });
  });
}

function updateExternalBookingLinksLocale(lang) {
  const hlMap = { fr: 'fr', en: 'en', zh: 'zh-CN' };
  const tripLocaleMap = { fr: 'fr-FR', en: 'en-XX', zh: 'zh-CN' };
  const hl = hlMap[lang] || 'fr';
  const tripLoc = tripLocaleMap[lang] || 'fr-FR';

  document.querySelectorAll('a[href*="google.com/travel/flights"]').forEach(function(a) {
    const href = a.getAttribute('href');
    if (href) {
      a.setAttribute('href', href.replace(/([?&])hl=[a-zA-Z-]+/, '$1hl=' + hl));
    }
  });
  document.querySelectorAll('a[href*="trip.com"]').forEach(function(a) {
    const href = a.getAttribute('href');
    if (href) {
      a.setAttribute('href', href.replace(/([?&])locale=[a-zA-Z_-]+/, '$1locale=' + tripLoc));
    }
  });
}

window.applyVolAlerteLang = function(lang) {
  const activeLang = lang || window.getVolAlerteLang();
  document.documentElement.setAttribute('lang', activeLang === 'zh' ? 'zh-CN' : activeLang);

  // Mettre à jour l'état visuel des boutons FR / EN / 中文
  document.querySelectorAll('.js-lang-btn').forEach(function(btn) {
    const bLang = btn.getAttribute('data-lang');
    const isActive = (bLang === activeLang);
    btn.classList.toggle('btn-primary', isActive);
    btn.classList.toggle('btn-secondary', !isActive);
    btn.style.background = isActive ? '#10b981' : 'transparent';
    btn.style.color = isActive ? '#ffffff' : 'var(--text-secondary)';
  });

  // 1. Éléments avec data-i18n / data-i18n-html
  const dict = I18N_DICT[activeLang] || I18N_DICT.fr;
  document.querySelectorAll('[data-i18n]').forEach(function(el) {
    const key = el.getAttribute('data-i18n');
    if (dict[key]) el.textContent = dict[key];
  });
  document.querySelectorAll('[data-i18n-html]').forEach(function(el) {
    const key = el.getAttribute('data-i18n-html');
    if (dict[key]) el.innerHTML = dict[key];
  });

  // 2. Collecter et traduire tous les noeuds texte de la page
  collectTranslatableNodes();
  TRACKED_TEXT_NODES.forEach(function(item) {
    if (!item.node.parentElement) return;
    if ( item.node.parentElement.hasAttribute('data-i18n') ||
         item.node.parentElement.hasAttribute('data-i18n-html') ) {
      return;
    }
    item.node.nodeValue = activeLang === 'fr' ? item.orig : translateString(item.orig, activeLang);
  });

  TRACKED_ATTR_ELS.forEach(function(item) {
    if (item.title) {
      item.el.setAttribute('title', activeLang === 'fr' ? item.title : translateString(item.title, activeLang));
    }
    if (item.placeholder) {
      item.el.setAttribute('placeholder', activeLang === 'fr' ? item.placeholder : translateString(item.placeholder, activeLang));
    }
  });

  // 3. Si on est sur le Radar, relancer le rendu dynamique pour formater les dates, villes et prix dans la langue choisie
  if (typeof window.refreshRadarLanguage === 'function') {
    window.refreshRadarLanguage(activeLang);
  } else {
    document.querySelectorAll('.js-dep-date-label').forEach(function(span) {
      const defDate = span.getAttribute('data-default-date');
      if (defDate) {
        span.textContent = window.formatDateByLang(defDate, activeLang);
      }
    });
  }

  updateExternalBookingLinksLocale(activeLang);
  updateThemeIcon(document.documentElement.getAttribute('data-theme') || 'dark');
};

window.setVolAlerteLang = function(lang) {
  localStorage.setItem('volalerte_lang', lang);
  window.applyVolAlerteLang(lang);
};

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
  const lang = window.getVolAlerteLang();
  const dict = I18N_DICT[lang] || I18N_DICT.fr;
  const btn = document.getElementById('btn-run-now');
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = dict.btn_running;
  }
  showToast(
    lang === 'zh' ? '正在刷新实时航班价格...' : (lang === 'en' ? 'Refreshing flight prices...' : 'Lancement du relevé des vols...'),
    'info'
  );

  try {
    const res = await fetch('/api/run-now', { method: 'POST' });
    const data = await res.json();
    showToast(data.message || 'OK', 'success');
    setTimeout(() => {
      window.location.reload();
    }, 2500);
  } catch (err) {
    showToast(
      lang === 'zh' ? '演示模式：本地价格已同步' : (lang === 'en' ? 'Demo mode: prices synced' : 'Prix synchronisés'),
      'info'
    );
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = dict.btn_run_now;
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

  // Appliquer la langue choisie (FR, EN, ou ZH)
  window.applyVolAlerteLang(window.getVolAlerteLang());
});
