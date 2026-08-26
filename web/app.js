/* ============================================================
   Bloom Studio · Salon Management System · API-connected
   ============================================================ */

// ─── Configuration ───────────────────────────────────────────
const API_BASE = localStorage.getItem('salon_api_base') || 'https://salon-backend-irjr.onrender.com';

// ─── Token Management ────────────────────────────────────────
let authToken = localStorage.getItem('salon_token');
let refreshToken = localStorage.getItem('salon_refresh_token');
let tokenPayload = null;

function decodeToken(t) { try { const p = JSON.parse(atob(t.split('.')[1])); return { userId: p.user_id, orgId: p.organization_id, role: p.role }; } catch(e) { return null; } }
function storeTokens(a, r) { authToken = a; refreshToken = r; localStorage.setItem('salon_token', a); localStorage.setItem('salon_refresh_token', r); tokenPayload = decodeToken(a); }
function clearTokens() { authToken = refreshToken = tokenPayload = null; localStorage.removeItem('salon_token'); localStorage.removeItem('salon_refresh_token'); }

// ─── API Layer ───────────────────────────────────────────────
async function api(method, path, body) {
  const h = { 'Content-Type': 'application/json' };
  if (authToken) h['Authorization'] = 'Bearer ' + authToken;
  let res = await fetch(API_BASE + path, { method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined });
  if (res.status === 401 && refreshToken) {
    const ok = await tryRefresh();
    if (ok) { h['Authorization'] = 'Bearer ' + authToken; res = await fetch(API_BASE + path, { method, headers: h, body: body !== undefined ? JSON.stringify(body) : undefined }); }
  }
  if (res.status === 204) return null;
  if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail || e.message || 'Request failed'); }
  return res.json();
}
async function tryRefresh() {
  try {
    const r = await fetch(API_BASE + '/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: refreshToken }) });
    if (!r.ok) { clearTokens(); return false; }
    const d = await r.json(); storeTokens(d.access_token, d.refresh_token); return true;
  } catch(e) { clearTokens(); return false; }
}

// ─── State ───────────────────────────────────────────────────
const SESSION_KEY = 'salon_session';
const LOCAL_KEY = 'salon_local_v1';
let db = { clients: [], staff: [], services: [], appointments: [], products: [], transactions: [], promotions: [], notifications: [], reviews: [], settings: { salonName: 'Bloom Studio', salonAddress: 'Quezon City', salonPhone: '', salonEmail: '', taxRate: 12, currency: '₱', lowStockThreshold: 10 }, users: [], nextId: { promotion: 1, notification: 1, review: 1 } };
function loadLocal() { try { const r = localStorage.getItem(LOCAL_KEY); if (r) { const s = JSON.parse(r); db.promotions = s.promotions || []; db.notifications = s.notifications || []; db.reviews = s.reviews || []; db.settings = Object.assign(db.settings, s.settings || {}); db.nextId = Object.assign(db.nextId, s.nextId || {}); } } catch(e) {} }
function saveLocal() { localStorage.setItem(LOCAL_KEY, JSON.stringify({ promotions: db.promotions, notifications: db.notifications, reviews: db.reviews, settings: db.settings, nextId: db.nextId })); }
loadLocal();
let session = null;
try { session = JSON.parse(localStorage.getItem(SESSION_KEY)) || null; } catch(e) { session = null; }

// ─── Data Loading ────────────────────────────────────────────
async function loadAllData() {
  try {
    const [clients, staff, services, products, appointments, payments] = await Promise.all([
      api('GET', '/clients').catch(() => []),
      api('GET', '/staff?active_only=false').catch(() => []),
      api('GET', '/services?active_only=false').catch(() => []),
      api('GET', '/products?active_only=false').catch(() => []),
      api('GET', '/appointments?limit=500').catch(() => []),
      api('GET', '/payments?limit=500').catch(() => [])
    ]);
    const cMap = {}; clients.forEach(c => cMap[c.id] = c);
    const sMap = {}; staff.forEach(s => sMap[s.id] = s);
    const svcMap = {}; services.forEach(s => svcMap[s.id] = s);

    db.clients = clients.map(c => ({ id: c.id, name: c.full_name, phone: c.phone || '', email: c.email || '', notes: c.notes || '', visit: 0, ltv: 0, loyaltyPoints: 0, tier: 'Bronze' }));
    db.staff = staff.map(s => ({ id: s.id, name: s.display_name, role: s.title || 'Staff', phone: '', email: '', status: s.active ? 'active' : 'inactive', initials: initials(s.display_name), schedule: {}, userId: s.user_id }));
    db.services = services.map(s => ({ id: s.id, name: s.name, category: s.category || 'General', duration: s.duration_minutes, price: s.price_cents / 100, assignedStaff: [] }));
    db.products = products.map(p => ({ id: p.id, name: p.name, category: p.category || 'General', stock: Number(p.stock_quantity), unitPrice: p.price_cents / 100, lowStockThreshold: Number(p.reorder_level), supplier: '', unit: p.unit || 'unit', sku: p.sku || '' }));

    db.appointments = appointments.map(a => {
      const cl = cMap[a.client_id]; const st = sMap[a.staff_id]; const svc = a.appointment_services && a.appointment_services[0];
      const dt = a.start_time ? new Date(a.start_time) : new Date();
      return { id: a.id, date: a.start_time ? a.start_time.slice(0, 10) : '', time: a.start_time ? a.start_time.slice(11, 16) : '', client: cl ? cl.full_name : (a.walk_in_id ? 'Walk-in' : 'Unknown'), clientId: a.client_id, walkInId: a.walk_in_id, service: svc ? svc.service_name : 'Service', serviceId: a.service_id || (svc ? svc.service_id : null), staff: st ? st.display_name : 'Unknown', staffId: a.staff_id, price: a.total_cents / 100, status: a.status, _raw: a };
    });

    db.transactions = payments.map(p => {
      const appt = db.appointments.find(a => a.id === p.appointment_id);
      return { id: p.id, appointmentId: p.appointment_id, date: (p.paid_at || p.created_at || '').slice(0, 10), customer: appt ? appt.client : 'Customer', amount: p.amount_cents / 100, method: p.method, status: p.status, tip: p.tip_cents / 100, discount: p.discount_cents / 100, _raw: p };
    });

    if (tokenPayload && tokenPayload.role === 'admin') {
      try { db.users = await api('GET', '/auth/users'); } catch(e) { db.users = []; }
    }
    try { db.notifications = await api('GET', '/notifications'); } catch(e) { db.notifications = []; }
    renderNotifBell();
  } catch(e) { console.error('Load failed:', e); toast('Failed to connect to server', true); }
}

// ─── Utility Functions ───────────────────────────────────────
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => Array.from((el || document).querySelectorAll(s));
function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])); }
function money(n) { return '₱' + Number(n || 0).toLocaleString('en-PH', { minimumFractionDigits: 0, maximumFractionDigits: 2 }); }
function initials(n) { return n.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase(); }
function todayISO() { return new Date().toISOString().slice(0, 10); }
function toISOWithTZ(date, time) { const d = new Date(date + 'T' + time); const off = d.getTimezoneOffset(); const abs = Math.abs(off); const sign = off <= 0 ? '+' : '-'; return `${date}T${time}:00${sign}${String(Math.floor(abs / 60)).padStart(2, '0')}:${String(abs % 60).padStart(2, '0')}`; }
function centsToPeso(c) { return c / 100; }
function pesoToCents(p) { return Math.round(p * 100); }
function tierBadge(t) { const c = { Bronze: 'badge-amber', Silver: 'badge-gray', Gold: 'badge-blue', Platinum: 'badge-emerald' }; return `<span class="badge ${c[t] || 'badge-gray'}"><span class="bdot"></span>${t}</span>`; }
function stockBadge(s, th) { if (s <= 0) return `<span class="badge badge-rose"><span class="bdot"></span>Out of Stock</span>`; if (s <= th) return `<span class="badge badge-amber"><span class="bdot"></span>Low Stock</span>`; return `<span class="badge badge-emerald"><span class="bdot"></span>In Stock</span>`; }
function starsHTML(r) { let s = ''; for (let i = 1; i <= 5; i++) s += `<span style="color:${i <= r ? '#F59E0B' : '#E5E7EB'}">★</span>`; return s; }
function getTier(pts) { if (pts >= 500) return 'Platinum'; if (pts >= 200) return 'Gold'; if (pts >= 50) return 'Silver'; return 'Bronze'; }
let toastTimer = null;
function toast(m, e) { const el = $('#toast'); if (!el) return; el.textContent = m; el.className = 'toast' + (e ? ' err' : ''); el.style.display = 'block'; clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.style.display = 'none'; }, 3200); }

const APPT_STATUS = { requested: { label: 'Requested', badge: 'badge-amber' }, confirmed: { label: 'Confirmed', badge: 'badge-blue' }, in_progress: { label: 'In Progress', badge: 'badge-emerald' }, completed: { label: 'Completed', badge: 'badge-gray' }, cancelled: { label: 'Cancelled', badge: 'badge-rose' }, no_show: { label: 'No Show', badge: 'badge-rose' } };
const STAFF_STATUS = { active: { label: 'Active', badge: 'badge-emerald' }, inactive: { label: 'Inactive', badge: 'badge-rose' } };
const ROLE_ACCESS = { admin: ['dashboard', 'appointments', 'clients', 'staff', 'services', 'inventory', 'scheduling', 'billing', 'loyalty', 'reports', 'notifications', 'reviews', 'settings'], owner: ['dashboard', 'appointments', 'clients', 'staff', 'services', 'inventory', 'scheduling', 'billing', 'loyalty', 'reports', 'notifications', 'reviews', 'settings'], staff: ['dashboard', 'appointments', 'billing'], front_desk: ['dashboard', 'appointments', 'clients', 'staff', 'services', 'inventory', 'scheduling', 'billing', 'loyalty', 'reports', 'notifications', 'reviews', 'settings'], specialist: ['dashboard', 'appointments', 'billing'],   client: ['my-bookings', 'book-appointment', 'notifications'] };
const ROLE_LABEL = { admin: 'Administrator', owner: 'Owner', staff: 'Staff', front_desk: 'Front Desk', specialist: 'Specialist', client: 'Customer' };
function canAccess(page) { const u = currentUser(); return !!u && (ROLE_ACCESS[u.role] || []).includes(page); }
function currentUser() { return tokenPayload ? { id: tokenPayload.userId, role: tokenPayload.role, email: '' } : null; }

// ─── Navigation ──────────────────────────────────────────────
let currentPage = 'dashboard';
function navigate(page) {
  if (!canAccess(page)) page = 'dashboard';
  currentPage = page;
  $$('.nav-item').forEach(n => n.classList.toggle('active', n.dataset.page === page));
  ['dashboard', 'appointments', 'clients', 'staff', 'services', 'inventory', 'scheduling', 'billing', 'loyalty', 'reports', 'notifications', 'reviews', 'settings', 'my-bookings', 'book-appointment'].forEach(p => { const el = $('#page-' + p); if (el) el.style.display = p === page ? 'block' : 'none'; });
  closeAllKebabs(); render();
}
function render() {
  if ($('#nav-appts')) $('#nav-appts').textContent = db.appointments.filter(a => a.status !== 'cancelled' && a.status !== 'completed').length;
  if ($('#nav-lowstock')) $('#nav-lowstock').textContent = db.products.filter(p => p.stock <= p.lowStockThreshold).length;
  const fn = { dashboard: renderDashboard, appointments: renderAppointments, clients: renderClients, staff: renderStaff, services: renderServices, inventory: renderInventory, scheduling: renderScheduling, billing: renderBilling, loyalty: renderLoyalty, reports: renderReports, notifications: renderNotifications, reviews: renderReviews, settings: renderSettings, 'my-bookings': renderMyBookings, 'book-appointment': renderBookAppointment }[currentPage];
  if (fn) fn();
}
function renderSidebar(u) {
  const allowed = ROLE_ACCESS[u.role] || [];
  const G = [
    { label: 'Overview', items: [{ page: 'dashboard', icon: 'ti ti-layout-dashboard', label: 'Dashboard' }, { page: 'appointments', icon: 'ti ti-calendar-event', label: 'Appointments', badge: 'nav-appts' }] },
    { label: 'Management', items: [{ page: 'clients', icon: 'ti ti-users', label: 'Clients' }, { page: 'staff', icon: 'ti ti-user-circle', label: 'Staff' }, { page: 'services', icon: 'ti ti-scissors', label: 'Services' }, { page: 'inventory', icon: 'ti ti-package', label: 'Inventory', badge: 'nav-lowstock' }] },
    { label: 'Operations', items: [{ page: 'scheduling', icon: 'ti ti-calendar-month', label: 'Scheduling' }, { page: 'billing', icon: 'ti ti-receipt', label: 'Billing' }, { page: 'loyalty', icon: 'ti ti-award', label: 'Loyalty' }] },
    { label: 'Analytics', items: [{ page: 'reports', icon: 'ti ti-chart-bar', label: 'Reports' }, { page: 'notifications', icon: 'ti ti-bell', label: 'Notifications' }, { page: 'reviews', icon: 'ti ti-star', label: 'Reviews' }] },
    { label: 'Admin', items: [{ page: 'settings', icon: 'ti ti-settings', label: 'Settings' }] },
    { label: 'Customer', items: [{ page: 'my-bookings', icon: 'ti ti-calendar-check', label: 'My Appointments' }, { page: 'book-appointment', icon: 'ti ti-calendar-plus', label: 'Book Appointment' }, { page: 'notifications', icon: 'ti ti-bell', label: 'Notifications' }] }
  ];
  $('#sidebar-nav').innerHTML = G.map(g => { const items = g.items.filter(i => allowed.includes(i.page)); if (!items.length) return ''; return `<div class="nav-section">${g.label}</div>` + items.map(i => `<a class="nav-item${i.page === currentPage ? ' active' : ''}" data-page="${i.page}" href="#"><i class="${i.icon}"></i> ${i.label}${i.badge ? ` <span class="badge-count" id="${i.badge}">0</span>` : ''}</a>`).join(''); }).join('');
}

// ─── Pager ───────────────────────────────────────────────────
const pagerState = { appointments: { page: 1, size: 8 }, clients: { page: 1, size: 8 }, staff: { page: 1, size: 8 }, inventory: { page: 1, size: 8 } };
const filters = { appointments: { q: '', status: 'all', date: 'all' }, clients: { q: '' }, staff: { q: '', status: 'all' }, inventory: { q: '', category: 'all' } };
const PAGER_IDS = { appointments: 'appts-pager', clients: 'clients-pager', staff: 'staff-pager', inventory: 'inv-pager' };
function resetPage(k) { pagerState[k].page = 1; }
function pageSlice(k, list) { const p = pagerState[k]; const pg = Math.max(1, Math.ceil(list.length / p.size)); p.page = Math.min(Math.max(1, p.page), pg); const s = (p.page - 1) * p.size; return { rows: list.slice(s, s + p.size), total: list.length, page: p.page, pages: pg }; }
function pagerHTML(k, info) { if (info.total === 0) return ''; const btns = []; for (let i = 1; i <= info.pages; i++) btns.push(`<button data-pg="${i}" ${i === info.page ? 'class="active"' : ''}>${i}</button>`); return `<div class="pager"><div class="pager-left">${info.total} results <select data-size>${[8, 15, 25].map(s => `<option value="${s}" ${s === pagerState[k].size ? 'selected' : ''}>${s}</option>`).join('')} per page</select></div><div class="pager-btns">${btns.join('')}</div></div>`; }
function keyFromPager(el) { for (const k of Object.keys(PAGER_IDS)) if (el.closest('#' + PAGER_IDS[k])) return k; return null; }
function toggleKebab(b) { closeAllKebabs(); b.closest('.kebab-wrap').querySelector('.kebab-menu').classList.add('open'); }
function closeAllKebabs() { $$('.kebab-menu.open').forEach(m => m.classList.remove('open')); }
function openModal(id) { $(id).classList.add('open'); }
function closeModal(id) { $(id).classList.remove('open'); }

// ─── Options Helpers ─────────────────────────────────────────
function clientOptions() { return db.clients.map(c => `<option value="${esc(c.name)}"></option>`).join(''); }
function serviceOptions() { return db.services.map(s => `<option value="${esc(s.name)}"></option>`).join(''); }
function staffOptions() { return db.staff.filter(s => s.status !== 'inactive').map(s => `<option value="${esc(s.name)}"></option>`).join(''); }
function staffSelectOptions(selected) { return db.staff.filter(s => s.status === 'active').map(s => `<option value="${s.id}" ${s.id === selected ? 'selected' : ''}>${esc(s.name)}</option>`).join(''); }
function productOptions() { return db.products.filter(p => p.stock > 0).map(p => `<option value="${esc(p.name)}" data-price="${p.unitPrice}"></option>`).join(''); }

// ─── Dashboard ───────────────────────────────────────────────
async function renderDashboard() {
  try {
    const d = await api('GET', '/reports/dashboard');
    $('#kpi-today').textContent = (d.appointments_total || 0);
    $('#kpi-revenue').textContent = money(centsToPeso(d.revenue_cents || 0));
    $('#kpi-clients').textContent = db.clients.length;
    $('#kpi-staff').textContent = db.staff.filter(s => s.status === 'active').length;
    if ($('#kpi-pending')) $('#kpi-pending').textContent = (d.appointments.requested || 0) + (d.appointments.confirmed || 0);
    if ($('#kpi-lowstock')) $('#kpi-lowstock').textContent = d.low_stock_products || 0;
  } catch(e) {
    $('#kpi-today').textContent = db.appointments.filter(a => a.date === todayISO()).length;
    $('#kpi-revenue').textContent = money(db.appointments.filter(a => a.date === todayISO()).reduce((s, a) => s + a.price, 0));
    $('#kpi-clients').textContent = db.clients.length;
    $('#kpi-staff').textContent = db.staff.filter(s => s.status === 'active').length;
    if ($('#kpi-pending')) $('#kpi-pending').textContent = db.appointments.filter(a => a.status === 'requested' || a.status === 'confirmed').length;
    if ($('#kpi-lowstock')) $('#kpi-lowstock').textContent = db.products.filter(p => p.stock <= p.lowStockThreshold).length;
  }

  const today = todayISO();
  const upcoming = db.appointments.filter(a => a.date >= today && a.status !== 'cancelled').sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time)).slice(0, 7);
  const tbt = $('#upcoming-tbody');
  if (tbt) tbt.innerHTML = upcoming.map(a => `<tr><td class="cell-primary">${esc(a.date)}</td><td>${esc(a.time)}</td><td class="cell-primary">${esc(a.client)}</td><td>${esc(a.service)}</td><td>${esc(a.staff)}</td><td><span class="badge ${APPT_STATUS[a.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[a.status]?.label || a.status}</span></td><td>${money(a.price)}</td></tr>`).join('');
  if ($('#upcoming-empty')) $('#upcoming-empty').style.display = upcoming.length ? 'none' : 'block';
  if ($('#mobile-upcoming')) $('#mobile-upcoming').innerHTML = upcoming.map(a => `<div class="mcard"><div class="mcard-top"><span class="mcard-title">${esc(a.client)}</span><span class="badge ${APPT_STATUS[a.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[a.status]?.label || a.status}</span></div><div class="mcard-sub">${esc(a.service)} · ${esc(a.staff)}</div><div class="mcard-row"><span>${esc(a.date)} ${esc(a.time)}</span><span>${money(a.price)}</span></div></div>`).join('') || '<div class="empty-state"><p>No upcoming appointments</p></div>';

  const dtbt = $('#dashboard-staff-tbody');
  if (dtbt) dtbt.innerHTML = db.staff.map(s => { const done = db.appointments.filter(a => a.staffId === s.id && a.date === today && a.status !== 'cancelled'); const pct = Math.min(100, done.length * 20); return `<tr><td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${esc(s.initials)}</div><span class="cell-primary">${esc(s.name)}</span></div></td><td class="cell-muted">${esc(s.role)}</td><td>${done.length}</td><td>${money(done.reduce((x, a) => x + a.price, 0))}</td><td style="min-width:120px"><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:6px;background:var(--g100);border-radius:999px"><div style="width:${pct}%;height:6px;background:var(--primary);border-radius:999px"></div></div><span style="font-size:12px;color:var(--g500)">${pct}%</span></div></td></tr>`; }).join('');
  if ($('#dashboard-staff-empty')) $('#dashboard-staff-empty').style.display = db.staff.length ? 'none' : 'block';
}

// ─── Appointments ────────────────────────────────────────────
async function renderAppointments() {
  const f = filters.appointments;
  const src = db.appointments.filter(a => {
    if (f.q && !((a.client + a.service + a.staff).toLowerCase().includes(f.q.toLowerCase()))) return false;
    if (f.status !== 'all' && a.status !== f.status) return false;
    if (f.date === 'today' && a.date !== todayISO()) return false;
    if (f.date === 'upcoming' && (a.date < todayISO() || a.status === 'cancelled')) return false;
    return true;
  }).sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));
  const info = pageSlice('appointments', src);
  $('#appts-tbody').innerHTML = info.rows.map(a => {
    let actions = '';
    if (a.status === 'requested') actions = '<button class="btn btn-sm btn-primary" style="margin-right:4px" data-act="confirm" data-id="'+a.id+'"><i class="ti ti-check"></i> Approve</button><button class="btn btn-sm btn-delete" data-act="cancel" data-id="'+a.id+'"><i class="ti ti-x"></i> Decline</button>';
    else if (a.status === 'confirmed') actions = '<button class="btn btn-sm btn-outline" style="margin-right:4px" data-act="checkin" data-id="'+a.id+'"><i class="ti ti-login"></i> Check in</button><button class="btn btn-sm btn-delete" data-act="cancel" data-id="'+a.id+'"><i class="ti ti-x"></i> Cancel</button>';
    else if (a.status === 'in_progress') actions = '<button class="btn btn-sm btn-primary" style="margin-right:4px" data-act="complete" data-id="'+a.id+'"><i class="ti ti-circle-check"></i> Complete</button><button class="btn btn-sm btn-delete" data-act="cancel" data-id="'+a.id+'"><i class="ti ti-x"></i> Cancel</button>';
    return `<tr><td class="cell-primary">${esc(a.date)}</td><td>${esc(a.time)}</td><td class="cell-primary">${esc(a.client)}</td><td>${esc(a.service)}</td><td>${esc(a.staff)}</td><td><span class="badge ${APPT_STATUS[a.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[a.status]?.label || a.status}</span></td><td>${money(a.price)}</td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu">${actions}</div></div></td></tr>`;
  }).join('');
  $('#appts-empty').style.display = info.total ? 'none' : 'block';
  $('#appts-pager').innerHTML = pagerHTML('appointments', info);
  $('#appts-total').textContent = info.total + ' appointment' + (info.total === 1 ? '' : 's');
  $('#appts-mobile').innerHTML = info.rows.map(a => `<div class="mcard"><div class="mcard-top"><span class="mcard-title">${esc(a.client)}</span><span class="badge ${APPT_STATUS[a.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[a.status]?.label || a.status}</span></div><div class="mcard-sub">${esc(a.service)} · ${esc(a.staff)}</div><div class="mcard-row"><span>${esc(a.date)} ${esc(a.time)}</span><span>${money(a.price)}</span></div></div>`).join('');
}
let editingApptId = null;
async function openApptModal(id) {
  editingApptId = id || null; $('#appt-err').textContent = '';
  const a = id ? db.appointments.find(x => x.id === id) : null;
  $('#appt-modal-title').textContent = a ? 'Edit appointment' : 'New appointment';
  $('#f-date').value = a ? a.date : todayISO(); $('#f-time').value = a ? a.time : '10:00';
  $('#clients-list').innerHTML = clientOptions(); $('#f-client').value = a ? a.client : '';
  $('#services-list').innerHTML = serviceOptions(); $('#f-service').value = a ? a.service : '';
  $('#staff-list').innerHTML = staffOptions(); $('#f-staff').value = a ? a.staff : '';
  const svc = a ? db.services.find(s => s.name === a.service) : null;
  $('#f-price').value = a ? a.price : (svc ? svc.price : '');
  $('#f-status').value = a ? a.status : 'requested';
  openModal('#appt-modal');
}
async function saveAppointment() {
  const date = $('#f-date').value.trim(), time = $('#f-time').value.trim(), clientName = $('#f-client').value.trim(), serviceName = $('#f-service').value.trim(), staffName = $('#f-staff').value.trim(), price = Number($('#f-price').value), status = $('#f-status').value;
  if (!date || !time || !clientName || !serviceName || !staffName) { $('#appt-err').textContent = 'Please fill in all fields.'; return; }
  try {
    let client = db.clients.find(c => c.name.toLowerCase() === clientName.toLowerCase());
    if (!client) { const c = await api('POST', '/clients', { full_name: clientName, phone: '', email: null, notes: '' }); client = { id: c.id, name: c.full_name, phone: '', email: '', notes: '', visit: 0, ltv: 0, loyaltyPoints: 0, tier: 'Bronze' }; db.clients.push(client); }
    const svc = db.services.find(s => s.name.toLowerCase() === serviceName.toLowerCase());
    if (!svc) { $('#appt-err').textContent = 'Service not found. Please select a valid service.'; return; }
    const stf = db.staff.find(s => s.name.toLowerCase() === staffName.toLowerCase());
    if (!stf) { $('#appt-err').textContent = 'Staff member not found.'; return; }
    const start_time = toISOWithTZ(date, time);
    if (editingApptId) {
      const existing = db.appointments.find(x => x.id === editingApptId);
      if (existing && existing.status !== status) {
        if (status === 'completed') { await api('POST', '/appointments/' + editingApptId + '/complete'); }
        else { await api('POST', '/appointments/' + editingApptId + '/status', { status }); }
      }
    } else {
      const appt = await api('POST', '/appointments', { client_id: client.id, staff_id: stf.id, service_id: svc.id, start_time, discount_cents: 0 });
      if (status !== 'requested' && status !== 'confirmed') {
        if (status === 'completed') { await api('POST', '/appointments/' + appt.id + '/complete'); }
        else { await api('POST', '/appointments/' + appt.id + '/status', { status }); }
      }
    }
    await loadAllData();
    closeModal('#appt-modal'); resetPage('appointments'); renderAppointments(); toast('Appointment saved');
  } catch(e) { $('#appt-err').textContent = e.message; }
}
async function apptAction(act, id) {
  try {
    const appt = db.appointments.find(a => a.id === id);
    if (act === 'cancel') {
      await api('POST', '/appointments/' + id + '/status', { status: 'cancelled', cancellation_reason: 'Cancelled by user' });
    } else if (act === 'confirm') {
      await api('POST', '/appointments/' + id + '/status', { status: 'confirmed' });
    } else if (act === 'checkin') {
      await api('POST', '/appointments/' + id + '/status', { status: 'in_progress' });
    } else if (act === 'complete') {
      await api('POST', '/appointments/' + id + '/complete');
    }
    await loadAllData(); renderAppointments(); toast('Status updated');
  } catch(e) { toast(e.message, true); }
}

// ─── Clients ─────────────────────────────────────────────────
async function renderClients() {
  const f = filters.clients;
  const src = db.clients.filter(c => !f.q || (c.name + c.phone + c.email).toLowerCase().includes(f.q.toLowerCase()));
  const info = pageSlice('clients', src);
  $('#clients-tbody').innerHTML = info.rows.map(c => `<tr><td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${initials(c.name)}</div><span class="cell-primary">${esc(c.name)}</span></div></td><td><div>${esc(c.phone)}</div><div class="cell-muted" style="font-size:12px">${esc(c.email)}</div></td><td>${c.visit}</td><td>${tierBadge(c.tier || 'Bronze')} <span class="cell-muted" style="font-size:11px">${c.loyaltyPoints || 0} pts</span></td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="edit-client" data-id="${c.id}"><i class="ti ti-pencil"></i> Edit</button><button class="danger" data-act="delete-client" data-id="${c.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('');
  $('#clients-empty').style.display = info.total ? 'none' : 'block'; $('#clients-pager').innerHTML = pagerHTML('clients', info);
  $('#clients-total').textContent = info.total + ' client' + (info.total === 1 ? '' : 's');
  $('#clients-mobile').innerHTML = info.rows.map(c => `<div class="mcard"><div class="mcard-top"><span class="mcard-title">${esc(c.name)}</span>${tierBadge(c.tier || 'Bronze')}</div><div class="mcard-sub">${esc(c.phone)}</div><div class="mcard-row"><span>${c.visit} visits</span><span>${c.loyaltyPoints || 0} pts</span></div></div>`).join('');
}
let editingClientId = null;
function openClientModal(id) { editingClientId = id || null; $('#client-err').textContent = ''; const c = id ? db.clients.find(x => x.id === id) : null; $('#client-modal-title').textContent = c ? 'Edit client' : 'New client'; $('#cf-name').value = c ? c.name : ''; $('#cf-phone').value = c ? c.phone : ''; $('#cf-email').value = c ? c.email : ''; if ($('#cf-notes')) $('#cf-notes').value = c ? c.notes : ''; openModal('#client-modal'); }
async function saveClient() {
  const name = $('#cf-name').value.trim(), phone = $('#cf-phone').value.trim(), email = $('#cf-email').value.trim() || null, notes = $('#cf-notes') ? $('#cf-notes').value.trim() : '';
  if (!name || !phone) { $('#client-err').textContent = 'Name and phone required.'; return; }
  try {
    if (editingClientId) { await api('PATCH', '/clients/' + editingClientId, { full_name: name, phone, email, notes }); }
    else { await api('POST', '/clients', { full_name: name, phone, email, notes }); }
    await loadAllData(); closeModal('#client-modal'); renderClients(); toast(editingClientId ? 'Client updated' : 'Client added');
  } catch(e) { $('#client-err').textContent = e.message; }
}
async function deleteClient(id) { try { await api('DELETE', '/clients/' + id); await loadAllData(); renderClients(); toast('Client deleted', true); } catch(e) { toast(e.message, true); } }

// ─── Staff ───────────────────────────────────────────────────
async function renderStaff() {
  const f = filters.staff;
  const src = db.staff.filter(s => { if (f.q && !((s.name + s.role).toLowerCase().includes(f.q.toLowerCase()))) return false; if (f.status !== 'all' && s.status !== f.status) return false; return true; });
  const info = pageSlice('staff', src);
  $('#staff-tbody').innerHTML = info.rows.map(s => `<tr><td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${esc(s.initials)}</div><span class="cell-primary">${esc(s.name)}</span></div></td><td class="cell-muted">${esc(s.role)}</td><td><div>${esc(s.phone)}</div><div class="cell-muted" style="font-size:12px">${esc(s.email)}</div></td><td><span class="badge ${STAFF_STATUS[s.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${STAFF_STATUS[s.status]?.label || s.status}</span></td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="edit-staff" data-id="${s.id}"><i class="ti ti-pencil"></i> Edit</button><button data-act="toggle-staff" data-id="${s.id}"><i class="ti ti-toggle"></i> ${s.status === 'active' ? 'Set inactive' : 'Set active'}</button><hr><button class="danger" data-act="delete-staff" data-id="${s.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('');
  $('#staff-empty').style.display = info.total ? 'none' : 'block'; $('#staff-pager').innerHTML = pagerHTML('staff', info);
  $('#staff-total').textContent = info.total + ' member' + (info.total === 1 ? '' : 's');
  $('#staff-mobile').innerHTML = info.rows.map(s => `<div class="mcard"><div class="mcard-top"><span class="mcard-title">${esc(s.name)}</span><span class="badge ${STAFF_STATUS[s.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${STAFF_STATUS[s.status]?.label || s.status}</span></div><div class="mcard-sub">${esc(s.role)}</div><div class="mcard-row"><span>${esc(s.phone)}</span></div></div>`).join('');
}
let editingStaffId = null;
function openStaffModal(id) { editingStaffId = id || null; $('#staff-err').textContent = ''; const s = id ? db.staff.find(x => x.id === id) : null; $('#staff-modal-title').textContent = s ? 'Edit staff' : 'Add staff'; $('#sf-name').value = s ? s.name : ''; $('#sf-role').value = s ? s.role : 'Stylist'; $('#sf-phone').value = s ? s.phone : ''; $('#sf-email').value = s ? s.email : ''; $('#sf-status').value = s ? s.status : 'active'; if ($('#sf-login-email')) $('#sf-login-email').value = ''; if ($('#sf-pass')) $('#sf-pass').value = ''; if ($('#sf-email-field')) $('#sf-email-field').style.display = s ? 'none' : 'block'; if ($('#sf-pass-field')) $('#sf-pass-field').style.display = s ? 'none' : 'block'; openModal('#staff-modal'); }
async function saveStaff() {
  const name = $('#sf-name').value.trim(), role = $('#sf-role').value.trim(), phone = $('#sf-phone').value.trim(), email = $('#sf-email').value.trim(), status = $('#sf-status').value;
  if (!name || !role) { $('#staff-err').textContent = 'Name and role required.'; return; }
  try {
    if (editingStaffId) { await api('PATCH', '/staff/' + editingStaffId, { display_name: name, title: role, active: status === 'active' }); }
    else {
      const loginEmail = ($('#sf-login-email') ? $('#sf-login-email').value.trim() : '') || email || (name.toLowerCase().replace(/\s+/g, '.') + '@salon.local');
      const pass = ($('#sf-pass') ? $('#sf-pass').value.trim() : '') || 'password123';
      const user = await api('POST', '/auth/users', { email: loginEmail, password: pass, role: 'staff', display_name: name });
      await api('POST', '/staff', { user_id: user.id, display_name: name, title: role, active: status === 'active' });
    }
    await loadAllData(); closeModal('#staff-modal'); renderStaff(); toast(editingStaffId ? 'Staff updated' : 'Staff added');
  } catch(e) { $('#staff-err').textContent = e.message; }
}
async function toggleStaff(id) { const s = db.staff.find(x => x.id === id); if (!s) return; try { await api('PATCH', '/staff/' + id, { active: s.status !== 'active' }); await loadAllData(); renderStaff(); toast(s.status === 'active' ? 'Set inactive' : 'Set active'); } catch(e) { toast(e.message, true); } }
async function deleteStaff(id) { try { await api('DELETE', '/staff/' + id); await loadAllData(); renderStaff(); toast('Staff removed', true); } catch(e) { toast(e.message, true); } }

// ─── Services ────────────────────────────────────────────────
async function renderServices() {
  if ($('#svc-count')) $('#svc-count').textContent = db.services.length;
  $('#svc-tbody').innerHTML = db.services.map(s => `<tr><td class="cell-primary">${esc(s.name)}</td><td><span class="badge badge-blue"><span class="bdot"></span>${esc(s.category)}</span></td><td>${s.duration} min</td><td>${money(s.price)}</td><td>${esc((s.assignedStaff || []).join(', ') || '—')}</td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="edit-svc" data-id="${s.id}"><i class="ti ti-pencil"></i> Edit</button><button class="danger" data-act="delete-svc" data-id="${s.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('');
  if ($('#svc-empty')) $('#svc-empty').style.display = db.services.length ? 'none' : 'block';
}
let editingSvcId = null;
function openSvcModal(id) { editingSvcId = id || null; $('#svc-err').textContent = ''; const s = id ? db.services.find(x => x.id === id) : null; $('#svc-modal-title').textContent = s ? 'Edit service' : 'New service'; $('#v-name').value = s ? s.name : ''; $('#v-cat').value = s ? s.category : 'Cut & Style'; $('#v-dur').value = s ? s.duration : 60; $('#v-price').value = s ? s.price : ''; openModal('#svc-modal'); }
async function saveSvc() {
  const name = $('#v-name').value.trim(), category = $('#v-cat').value.trim(), duration = Number($('#v-dur').value), price = Number($('#v-price').value);
  if (!name || !category || !duration || !price) { $('#svc-err').textContent = 'All fields required.'; return; }
  try {
    const payload = { name, category, duration_minutes: duration, price_cents: pesoToCents(price), active: true };
    if (editingSvcId) { await api('PATCH', '/services/' + editingSvcId, payload); }
    else { await api('POST', '/services', payload); }
    await loadAllData(); closeModal('#svc-modal'); renderServices(); toast(editingSvcId ? 'Service updated' : 'Service added');
  } catch(e) { $('#svc-err').textContent = e.message; }
}
async function deleteSvc(id) { try { await api('DELETE', '/services/' + id); await loadAllData(); renderServices(); toast('Service deleted', true); } catch(e) { toast(e.message, true); } }

// ─── Inventory ───────────────────────────────────────────────
async function renderInventory() {
  if ($('#inv-total-products')) $('#inv-total-products').textContent = db.products.length;
  if ($('#inv-low-stock')) $('#inv-low-stock').textContent = db.products.filter(p => p.stock <= p.lowStockThreshold && p.stock > 0).length;
  if ($('#inv-value')) $('#inv-value').textContent = money(db.products.reduce((s, p) => s + p.stock * p.unitPrice, 0));
  if ($('#inv-out-of-stock')) $('#inv-out-of-stock').textContent = db.products.filter(p => p.stock <= 0).length;
  const f = filters.inventory; const src = db.products.filter(p => { if (f.q && !((p.name + p.supplier).toLowerCase().includes(f.q.toLowerCase()))) return false; if (f.category !== 'all' && p.category !== f.category) return false; return true; });
  const info = pageSlice('inventory', src);
  $('#inv-tbody').innerHTML = info.rows.map(p => `<tr><td class="cell-primary">${esc(p.name)}</td><td><span class="badge badge-blue"><span class="bdot"></span>${esc(p.category)}</span></td><td style="font-weight:600;color:${p.stock <= 0 ? 'var(--danger)' : p.stock <= p.lowStockThreshold ? 'var(--warning)' : 'var(--success)'}">${p.stock}</td><td>${money(p.unitPrice)}</td><td>${esc(p.supplier || '—')}</td><td>${stockBadge(p.stock, p.lowStockThreshold)}</td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="edit-inv" data-id="${p.id}"><i class="ti ti-pencil"></i> Edit</button><button data-act="stock-in" data-id="${p.id}"><i class="ti ti-plus"></i> Stock In</button><button data-act="stock-out" data-id="${p.id}"><i class="ti ti-minus"></i> Stock Out</button><hr><button class="danger" data-act="delete-inv" data-id="${p.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('');
  if ($('#inv-empty')) $('#inv-empty').style.display = info.total ? 'none' : 'block';
  if ($('#inv-pager')) $('#inv-pager').innerHTML = pagerHTML('inventory', info);
  if ($('#inv-total')) $('#inv-total').textContent = info.total + ' product' + (info.total === 1 ? '' : 's');
}
let editingInvId = null;
function openInventoryModal(id) { editingInvId = id || null; $('#inv-err').textContent = ''; const p = id ? db.products.find(x => x.id === id) : null; $('#inv-modal-title').textContent = p ? 'Edit product' : 'New product'; $('#inv-name').value = p ? p.name : ''; $('#inv-cat').value = p ? p.category : 'Hair Care'; $('#inv-stock').value = p ? p.stock : 0; $('#inv-price').value = p ? p.unitPrice : ''; $('#inv-threshold').value = p ? p.lowStockThreshold : 10; $('#inv-supplier').value = p ? p.supplier : ''; if ($('#inv-unit')) $('#inv-unit').value = p ? p.unit : 'pcs'; openModal('#inventory-modal'); }
async function saveInventoryItem() {
  const name = $('#inv-name').value.trim(), category = $('#inv-cat').value.trim(), stock = Number($('#inv-stock').value), unitPrice = Number($('#inv-price').value), lowStockThreshold = Number($('#inv-threshold').value), supplier = $('#inv-supplier').value.trim(), unit = $('#inv-unit') ? $('#inv-unit').value.trim() : 'pcs';
  if (!name || !category || !unitPrice) { $('#inv-err').textContent = 'Name, category and price required.'; return; }
  try {
    const payload = { name, category, stock_quantity: stock, price_cents: pesoToCents(unitPrice), reorder_level: lowStockThreshold, unit: unit || 'unit', active: true };
    if (editingInvId) { await api('PATCH', '/products/' + editingInvId, payload); }
    else { await api('POST', '/products', payload); }
    await loadAllData(); closeModal('#inventory-modal'); renderInventory(); toast(editingInvId ? 'Product updated' : 'Product added');
  } catch(e) { $('#inv-err').textContent = e.message; }
}
async function stockIn(id) { const p = db.products.find(x => x.id === id); if (!p) return; const amt = prompt('Stock in quantity:', '10'); if (amt === null) return; try { await api('POST', '/products/' + id + '/stock', { delta: Number(amt) }); await loadAllData(); renderInventory(); toast('Stock updated'); } catch(e) { toast(e.message, true); } }
async function stockOut(id) { const p = db.products.find(x => x.id === id); if (!p) return; const amt = prompt('Stock out quantity:', '1'); if (amt === null) return; try { await api('POST', '/products/' + id + '/stock', { delta: -Number(amt) }); await loadAllData(); renderInventory(); toast('Stock updated'); } catch(e) { toast(e.message, true); } }
async function deleteProduct(id) { try { await api('DELETE', '/products/' + id); await loadAllData(); renderInventory(); toast('Product deleted', true); } catch(e) { toast(e.message, true); } }

// ─── Scheduling (localStorage only — no backend endpoint) ─────
function renderScheduling() {
  const days = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  if (!db.staff.length) { $('#scheduling-tbody').innerHTML = ''; if ($('#scheduling-empty')) $('#scheduling-empty').style.display = 'block'; return; }
  if ($('#scheduling-empty')) $('#scheduling-empty').style.display = 'none';
  $('#scheduling-tbody').innerHTML = db.staff.filter(s => s.status !== 'inactive').map(s => {
    const cells = days.map(d => { const sch = s.schedule && s.schedule[d]; const off = !sch; return `<td style="cursor:pointer;${off ? 'color:var(--g400);font-style:italic' : ''}" data-act="toggle-schedule" data-staff="${s.id}" data-day="${d}">${off ? 'Off' : esc(sch.start + '-' + sch.end)}</td>`; }).join('');
    return `<tr><td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${esc(s.initials)}</div><span class="cell-primary">${esc(s.name)}</span></div></td>${cells}</tr>`;
  }).join('');
}
function toggleSchedule(staffId, day) { const s = db.staff.find(x => x.id === staffId); if (!s) return; if (!s.schedule) s.schedule = {}; if (s.schedule[day]) { delete s.schedule[day]; } else { s.schedule[day] = { start: '09:00', end: '17:00' }; } saveLocal(); renderScheduling(); }
function openScheduleModal() {
  const sel = $('#sch-staff');
  if (sel) sel.innerHTML = db.staff.filter(s => s.status !== 'inactive').map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
  $$('#schedule-modal .sch-day-chip input').forEach(cb => cb.checked = cb.value !== 'sat' && cb.value !== 'sun');
  if ($('#sch-start')) $('#sch-start').value = '09:00';
  if ($('#sch-end')) $('#sch-end').value = '17:00';
  if ($('#sch-err')) $('#sch-err').textContent = '';
  openModal('#schedule-modal');
}
function saveSchedule() {
  const staffId = $('#sch-staff').value, start = $('#sch-start').value, end = $('#sch-end').value;
  if (!staffId || !start || !end) { if ($('#sch-err')) $('#sch-err').textContent = 'All fields required.'; return; }
  const days = $$('#schedule-modal .sch-day-chip input:checked').map(cb => cb.value);
  if (!days.length) { if ($('#sch-err')) $('#sch-err').textContent = 'Select at least one day.'; return; }
  const s = db.staff.find(x => x.id === staffId);
  if (!s) return;
  if (!s.schedule) s.schedule = {};
  days.forEach(d => { s.schedule[d] = { start, end }; });
  saveLocal(); closeModal('#schedule-modal'); renderScheduling(); toast('Shift assigned to ' + days.length + ' day' + (days.length > 1 ? 's' : ''));
}

// ─── Billing ─────────────────────────────────────────────────
let billingItems = [];
let billingPaymentMethod = 'cash';
async function renderBilling() {
  if (!db.services.length || !db.staff.length) {
    toast('Loading billing data...');
    await loadAllData();
  }
  if ($('#billing-customers-list')) $('#billing-customers-list').innerHTML = clientOptions();
  if ($('#billing-services-list')) $('#billing-services-list').innerHTML = serviceOptions();
  if ($('#billing-products-list')) $('#billing-products-list').innerHTML = productOptions();
  if ($('#billing-staff-select')) $('#billing-staff-select').innerHTML = '<option value="">Select staff...</option>' + staffSelectOptions();
  renderBillingItems();
  if ($('#billing-recent-tbody')) {
    const recent = db.transactions.slice(-5).reverse();
    $('#billing-recent-tbody').innerHTML = recent.map(t => `<tr><td class="cell-primary">${esc(t.customer || 'Walk-in')}</td><td>${esc(t.date)}</td><td>${money(t.amount)}</td><td><span class="badge badge-blue"><span class="bdot"></span>${esc(t.method)}</span></td></tr>`).join('') || `<tr><td class="cell-muted" colspan="4">No transactions yet</td></tr>`;
  }
  $$('.billing-pay-btn').forEach(b => b.classList.toggle('active', b.dataset.method === billingPaymentMethod));
}
function renderBillingItems() {
  const tbody = $('#billing-items-tbody'); if (!tbody) return;
  const svc = db.services, prod = db.products;
  tbody.innerHTML = billingItems.map((it, i) => {
    const svcObj = svc.find(s => s.name === it.name); const prodObj = prod.find(p => p.name === it.name);
    const unit = it.type === 'service' ? (svcObj ? svcObj.duration + 'min' : '') : (prodObj ? prodObj.unit : '');
    return `<tr><td>${esc(it.name)}</td><td><span class="badge ${it.type === 'service' ? 'badge-blue' : 'badge-emerald'}">${it.type}</span></td><td>${it.qty}</td><td>${money(it.price)}</td><td>${money(it.price * it.qty)}</td><td><button class="btn btn-sm btn-outline" onclick="removeBillingItem(${i})"><i class="ti ti-x"></i></button></td></tr>`;
  }).join('') || `<tr><td class="cell-muted" colspan="6" style="text-align:center;padding:20px">Add services or products to begin</td></tr>`;
  const subtotal = billingItems.reduce((s, it) => s + it.price * it.qty, 0);
  const discPct = Number($('#billing-discount') ? $('#billing-discount').value : 0);
  const discount = subtotal * discPct / 100;
  const taxable = subtotal - discount;
  const taxRate = db.settings.taxRate || 12;
  const tax = taxable * taxRate / 100;
  const total = taxable + tax;
  if ($('#billing-subtotal')) $('#billing-subtotal').textContent = money(subtotal);
  if ($('#billing-tax')) $('#billing-tax').textContent = money(tax);
  if ($('#billing-total')) $('#billing-total').textContent = money(total);
}
function addBillingItemFromInput(type) {
  let name;
  if (type === 'service') {
    name = $('#billing-svc-input') ? $('#billing-svc-input').value.trim() : '';
    if (!name) { toast('Select a service first', true); return; }
    const svc = db.services.find(s => s.name.toLowerCase() === name.toLowerCase());
    if (!svc) { toast('Service not found', true); return; }
    billingItems.push({ name: svc.name, type: 'service', qty: 1, price: svc.price, serviceId: svc.id });
  } else {
    name = $('#billing-prod-input') ? $('#billing-prod-input').value.trim() : '';
    if (!name) { toast('Select a product first', true); return; }
    const prod = db.products.find(p => p.name.toLowerCase() === name.toLowerCase());
    if (!prod) { toast('Product not found', true); return; }
    if (prod.stock <= 0) { toast('Product out of stock!', true); return; }
    billingItems.push({ name: prod.name, type: 'product', qty: 1, price: prod.unitPrice, productId: prod.id });
  }
  renderBillingItems();
  if (type === 'service' && $('#billing-svc-input')) $('#billing-svc-input').value = '';
  if (type === 'product' && $('#billing-prod-input')) $('#billing-prod-input').value = '';
}
function removeBillingItem(i) { billingItems.splice(i, 1); renderBillingItems(); }
function selectPaymentMethod(m) { billingPaymentMethod = m; renderBilling(); }
async function processPayment() {
  if (!billingItems.length) { toast('Add items first!', true); return; }
  const customerName = $('#billing-customer') ? $('#billing-customer').value.trim() : '';
  const staffId = $('#billing-staff-select') ? $('#billing-staff-select').value : '';
  const services = billingItems.filter(it => it.type === 'service');
  const products = billingItems.filter(it => it.type === 'product');
  if (!services.length) { toast('Add at least one service', true); return; }
  if (!staffId) { toast('Select a staff member', true); return; }

  const subtotal = billingItems.reduce((s, it) => s + it.price * it.qty, 0);
  const discPct = Number($('#billing-discount') ? $('#billing-discount').value : 0);
  const discount = subtotal * discPct / 100;
  const taxable = subtotal - discount;
  const taxRate = db.settings.taxRate || 12;
  const tax = taxable * taxRate / 100;
  const total = taxable + tax;

  try {
    let clientId = null;
    if (customerName) {
      let client = db.clients.find(c => c.name.toLowerCase() === customerName.toLowerCase());
      if (!client) { const c = await api('POST', '/clients', { full_name: customerName, phone: '', email: null, notes: 'Created from billing' }); client = { id: c.id, name: c.full_name }; db.clients.push(client); }
      clientId = client.id;
    }

    const now = new Date();
    const dateStr = now.toISOString().slice(0, 10);
    const timeStr = String(now.getHours()).padStart(2, '0') + ':' + String(now.getMinutes()).padStart(2, '0');
    const start_time = toISOWithTZ(dateStr, timeStr);

    const firstSvc = services[0];
    const apptPayload = { staff_id: staffId, service_id: firstSvc.serviceId, start_time, discount_cents: pesoToCents(discount) };
    if (clientId) apptPayload.client_id = clientId;

    const appt = await api('POST', '/appointments', apptPayload);

    for (const p of products) {
      try { await api('POST', '/products/usage', { appointment_id: appt.id, product_id: p.productId, quantity: p.qty }); } catch(e) { console.warn('Product usage failed:', e); }
    }

    try { await api('PATCH', '/appointments/' + appt.id + '/status', { status: 'confirmed' }); } catch(e) { console.warn('Confirm failed:', e); }
    try { await api('PATCH', '/appointments/' + appt.id + '/status', { status: 'in_progress' }); } catch(e) { console.warn('Start failed:', e); }

    await api('POST', '/payments', { appointment_id: appt.id, amount_cents: pesoToCents(total), method: billingPaymentMethod, status: 'paid', discount_cents: pesoToCents(discount) });

    try { await api('POST', '/appointments/' + appt.id + '/complete'); } catch(e) { console.warn('Complete failed:', e); }

    billingItems = [];
    if ($('#billing-customer')) $('#billing-customer').value = '';
    if ($('#billing-discount')) $('#billing-discount').value = 0;
    db.transactions.push({ id: appt.id, customer: customerName || 'Walk-in', date: dateStr, amount: total, method: billingPaymentMethod });
    await loadAllData();
    renderBilling();
    toast('Payment processed! ' + money(total));
  } catch(e) { toast('Payment failed: ' + e.message, true); }
}

// ─── Loyalty (localStorage only — no backend endpoint) ────────
let loyaltyTab = 'members';
function renderLoyalty() {
  if ($('#loyalty-members')) $('#loyalty-members').textContent = db.clients.filter(c => (c.loyaltyPoints || 0) > 0).length;
  if ($('#loyalty-promos')) $('#loyalty-promos').textContent = db.promotions.filter(p => p.active).length;
  if ($('#loyalty-points')) $('#loyalty-points').textContent = db.clients.reduce((s, c) => s + (c.loyaltyPoints || 0), 0);
  if (loyaltyTab === 'members') {
    if ($('#loyalty-members-tbody')) $('#loyalty-members-tbody').innerHTML = db.clients.filter(c => (c.loyaltyPoints || 0) > 0).map(c => `<tr><td class="cell-primary">${esc(c.name)}</td><td>${c.loyaltyPoints || 0}</td><td>${tierBadge(c.tier || 'Bronze')}</td><td>${c.visit} visits</td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="edit-loyalty" data-id="${c.id}"><i class="ti ti-pencil"></i> Adjust Points</button><button class="danger" data-act="remove-loyalty" data-id="${c.id}"><i class="ti ti-heart-off"></i> Remove</button></div></div></td></tr>`).join('') || `<tr><td class="cell-muted" style="text-align:center;padding:20px" colspan="5">No loyalty members yet</td></tr>`;
  } else {
    if ($('#loyalty-promos-tbody')) $('#loyalty-promos-tbody').innerHTML = db.promotions.map(p => `<tr><td class="cell-primary">${esc(p.name)}</td><td><span class="badge badge-blue"><span class="bdot"></span>${esc(p.type)}</span></td><td>${p.type === 'percentage' ? p.value + '%' : money(p.value)}</td><td>${esc(p.startDate || '—')} — ${esc(p.endDate || '—')}</td><td><span class="badge ${p.active ? 'badge-emerald' : 'badge-gray'}"><span class="bdot"></span>${p.active ? 'Active' : 'Inactive'}</span></td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="toggle-promo" data-id="${p.id}"><i class="ti ti-toggle"></i> ${p.active ? 'Deactivate' : 'Activate'}</button><button class="danger" data-act="delete-promo" data-id="${p.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('') || `<tr><td class="cell-muted" style="text-align:center;padding:20px" colspan="6">No promotions yet</td></tr>`;
  }
}
function switchLoyaltyTab(t) { loyaltyTab = t; $$('.tabs .tab').forEach(x => x.classList.remove('active')); $$('.tabs .tab').forEach(x => { if (x.dataset.tab === t) x.classList.add('active'); }); renderLoyalty(); }
let editingPromoId = null;
function openPromoModal(id) { editingPromoId = id || null; $('#promo-err').textContent = ''; const p = id ? db.promotions.find(x => x.id === id) : null; $('#promo-modal-title').textContent = p ? 'Edit promotion' : 'New promotion'; $('#promo-name').value = p ? p.name : ''; $('#promo-type').value = p ? p.type : 'percentage'; $('#promo-value').value = p ? p.value : ''; $('#promo-start').value = p ? p.startDate : ''; $('#promo-end').value = p ? p.endDate : ''; if ($('#promo-desc')) $('#promo-desc').value = p ? p.description : ''; openModal('#promo-modal'); }
function savePromo() { const name = $('#promo-name').value.trim(), type = $('#promo-type').value, value = Number($('#promo-value').value), startDate = $('#promo-start').value, endDate = $('#promo-end').value, description = $('#promo-desc') ? $('#promo-desc').value.trim() : ''; if (!name || !value) { $('#promo-err').textContent = 'Name and value required.'; return; } if (editingPromoId) { Object.assign(db.promotions.find(p => p.id === editingPromoId), { name, type, value, startDate, endDate, description }); } else { db.promotions.push({ id: 'promo_' + (db.nextId.promotion++), name, type, value, startDate, endDate, description, active: true }); } saveLocal(); closeModal('#promo-modal'); renderLoyalty(); toast(editingPromoId ? 'Promotion updated' : 'Promotion added'); }
function togglePromo(id) { const p = db.promotions.find(x => x.id === id); if (!p) return; p.active = !p.active; saveLocal(); renderLoyalty(); toast(p.active ? 'Promotion activated' : 'Promotion deactivated'); }
function deletePromo(id) { db.promotions = db.promotions.filter(p => p.id !== id); saveLocal(); renderLoyalty(); toast('Promotion deleted', true); }
let editingLoyaltyId = null;
function openLoyaltyModal(id) {
  editingLoyaltyId = id || null;
  $('#la-err').textContent = '';
  if (id) {
    const c = db.clients.find(x => x.id === id);
    if (!c) return;
    $('#la-modal-title').textContent = 'Edit Loyalty Points';
    if ($('#la-client-field-wrap')) $('#la-client-field-wrap').style.display = 'none';
    if ($('#la-name-display-wrap')) $('#la-name-display-wrap').style.display = '';
    if ($('#la-name-display')) $('#la-name-display').textContent = c.name;
    if ($('#la-points')) $('#la-points').value = c.loyaltyPoints || 0;
  } else {
    $('#la-modal-title').textContent = 'Add Loyalty Member';
    if ($('#la-client-field-wrap')) $('#la-client-field-wrap').style.display = '';
    if ($('#la-name-display-wrap')) $('#la-name-display-wrap').style.display = 'none';
    if ($('#la-client-select')) {
      const enrolled = new Set(db.clients.filter(c => (c.loyaltyPoints || 0) > 0).map(c => c.id));
      $('#la-client-select').innerHTML = '<option value="">Select customer...</option>' + db.clients.filter(c => !enrolled.has(c.id)).map(c => '<option value="' + c.id + '">' + esc(c.name) + '</option>').join('');
    }
    if ($('#la-points')) $('#la-points').value = 0;
  }
  openModal('#loyalty-adjust-modal');
}
function saveLoyalty() {
  if (editingLoyaltyId) {
    const c = db.clients.find(x => x.id === editingLoyaltyId);
    if (!c) return;
    const pts = Number($('#la-points').value);
    c.loyaltyPoints = pts;
    c.tier = getTier(pts);
  } else {
    const clientId = $('#la-client-select') ? $('#la-client-select').value : '';
    if (!clientId) { $('#la-err').textContent = 'Select a customer.'; return; }
    const c = db.clients.find(x => x.id === clientId);
    if (!c) return;
    const pts = Number($('#la-points').value);
    c.loyaltyPoints = pts;
    c.tier = getTier(pts);
  }
  saveLocal();
  closeModal('#loyalty-adjust-modal');
  renderLoyalty();
  toast(editingLoyaltyId ? 'Points updated' : 'Member added to loyalty');
}

// ─── Reports ─────────────────────────────────────────────────
async function renderReports() {
  try {
    const now = new Date(), y = now.getFullYear(), m = now.getMonth(), days = new Date(y, m + 1, 0).getDate();
    const dateFrom = `${y}-${String(m + 1).padStart(2, '0')}-01T00:00:00`;
    const dateTo = `${y}-${String(m + 1).padStart(2, '0')}-${String(days).padStart(2, '0')}T23:59:59`;

    const [dash, revDay, revSvc, revStaff] = await Promise.all([
      api('GET', '/reports/dashboard').catch(() => null),
      api('GET', `/reports/revenue?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&group_by=day`).catch(() => null),
      api('GET', `/reports/revenue?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&group_by=service`).catch(() => null),
      api('GET', `/reports/revenue?date_from=${encodeURIComponent(dateFrom)}&date_to=${encodeURIComponent(dateTo)}&group_by=staff`).catch(() => null)
    ]);

    if (dash) {
      if ($('#rep-total')) $('#rep-total').textContent = money(centsToPeso(dash.revenue_cents || 0));
      if ($('#rep-appts')) $('#rep-appts').textContent = dash.appointments_total || 0;
      if ($('#rep-avg')) { const total = dash.appointments_total || 0; $('#rep-avg').textContent = money(total ? centsToPeso(dash.revenue_cents || 0) / total : 0); }
      if ($('#rep-cancel-rate')) { const total = dash.appointments_total || 0; const cancelled = (dash.appointments.cancelled || 0); $('#rep-cancel-rate').textContent = total ? Math.round(cancelled / total * 100) + '%' : '0%'; }
    }

    if (revSvc && revSvc.rows) {
      const maxSvc = Math.max(1, ...revSvc.rows.map(r => r.revenue_cents || 0));
      if ($('#rep-svc-tbody')) $('#rep-svc-tbody').innerHTML = revSvc.rows.length ? revSvc.rows.map(r => `<tr><td class="cell-primary">${esc(r.service_name)}</td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:6px;background:var(--g100);border-radius:999px"><div style="width:${Math.round((r.revenue_cents || 0) / maxSvc * 100)}%;height:6px;background:var(--primary);border-radius:999px"></div></div><span style="font-size:12px;color:var(--g500)">${r.appointments || 0}</span></div></td></tr>`).join('') : `<tr><td class="cell-muted">No data</td><td></td></tr>`;
    }

    if (revStaff && revStaff.rows) {
      if ($('#rep-staff-tbody')) $('#rep-staff-tbody').innerHTML = revStaff.rows.length ? revStaff.rows.map(r => `<tr><td class="cell-primary">${esc(r.staff_name || 'Unknown')}</td><td>${r.appointments || 0}</td><td>${money(centsToPeso(r.revenue_cents || 0))}</td></tr>`).join('') : `<tr><td class="cell-muted">No data</td><td></td><td></td></tr>`;
    }

    const recentAppts = db.appointments.filter(a => a.status === 'completed').sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5);
    if ($('#rep-recent-tbody')) $('#rep-recent-tbody').innerHTML = recentAppts.map(a => `<tr><td class="cell-primary">${esc(a.client)}</td><td>${esc(a.service)}</td><td>${esc(a.date)}</td><td>${money(a.price)}</td></tr>`).join('');

    if (revDay && revDay.rows) {
      if ($('#rep-sales-tbody')) $('#rep-sales-tbody').innerHTML = revDay.rows.length ? revDay.rows.slice(-7).reverse().map(r => `<tr><td>${esc((r.bucket || '').slice(0, 10))}</td><td>${r.transactions || 0}</td><td>${money(centsToPeso(r.revenue_cents || 0))}</td></tr>`).join('') : `<tr><td class="cell-muted">No sales yet</td><td></td><td></td></tr>`;
    }

    if (dash && dash.appointments) {
      const all = dash.appointments_total || 1; const stObj = dash.appointments;
      if ($('#rep-status-tbody')) $('#rep-status-tbody').innerHTML = Object.entries(stObj).filter(([s, c]) => c > 0).map(([s, c]) => `<tr><td><span class="badge ${APPT_STATUS[s]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[s]?.label || s}</span></td><td>${c}</td><td><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:6px;background:var(--g100);border-radius:999px"><div style="width:${Math.round(c / all * 100)}%;height:6px;background:var(--primary);border-radius:999px"></div></div><span style="font-size:12px;color:var(--g500)">${Math.round(c / all * 100)}%</span></div></td></tr>`).join('') || `<tr><td class="cell-muted">No data</td><td></td><td></td></tr>`;
    }
  } catch(e) { console.error('Reports error:', e); }
}

// ─── Notifications ──────────────────────────────────────────
async function renderNotifications() {
  if (!db.notifications || !db.notifications.length) {
    try { db.notifications = await api('GET', '/notifications'); } catch(e) { db.notifications = db.notifications || []; }
  }
  const apiNotifs = db.notifications || [];
  if (!apiNotifs.length) {
    if ($('#notifications-tbody')) $('#notifications-tbody').innerHTML = `<tr><td class="cell-muted" colspan="6" style="text-align:center;padding:20px">No notifications yet</td></tr>`;
    if ($('#notifications-empty')) $('#notifications-empty').style.display = 'block';
    if ($('#notifications-total')) $('#notifications-total').textContent = '0 notifications';
    return;
  }
  if ($('#notifications-empty')) $('#notifications-empty').style.display = 'none';
  if ($('#notifications-tbody')) $('#notifications-tbody').innerHTML = apiNotifs.map(n => `<tr>
    <td><span class="badge ${n.is_read ? 'badge-gray' : 'badge-blue'}"><span class="bdot"></span>${n.is_read ? 'Read' : 'Unread'}</span></td>
    <td><span class="badge badge-amber"><span class="bdot"></span>${esc(n.type || 'info')}</span></td>
    <td class="cell-primary">${esc(n.title || 'Notification')}</td>
    <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(n.message)}</td>
    <td>${timeAgo(n.created_at || n.date)}</td>
    <td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="toggle-notif-read" data-id="${n.id}"><i class="ti ti-${n.is_read ? 'eye-off' : 'eye'}"></i> Mark ${n.is_read ? 'unread' : 'read'}</button><button class="danger" data-act="delete-notif" data-id="${n.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td>
  </tr>`).join('');
  if ($('#notifications-total')) $('#notifications-total').textContent = apiNotifs.length + ' notification' + (apiNotifs.length === 1 ? '' : 's');
}
function openNotificationModal() { if ($('#notif-customer')) $('#notif-customer').value = ''; if ($('#notif-type')) $('#notif-type').value = 'confirmation'; if ($('#notif-message')) $('#notif-message').value = ''; if ($('#notif-err')) $('#notif-err').textContent = ''; openModal('#notification-modal'); }
function saveNotification() { const customer = $('#notif-customer').value.trim(), type = $('#notif-type').value, message = $('#notif-message').value.trim(); if (!customer || !message) { if ($('#notif-err')) $('#notif-err').textContent = 'Customer and message required.'; return; } db.notifications.unshift({ id: 'notif_' + (db.nextId.notification++), type, title: customer, message, is_read: false, created_at: new Date().toISOString() }); saveLocal(); closeModal('#notification-modal'); renderNotifications(); toast('Notification sent'); renderNotifBell(); }
function deleteNotif(id) { db.notifications = (db.notifications || []).filter(n => String(n.id) !== String(id)); saveLocal(); renderNotifications(); toast('Notification deleted', true); renderNotifBell(); }

// ─── Reviews (localStorage only) ─────────────────────────────
function renderReviews() {
  $('#reviews-tbody').innerHTML = db.reviews.map(r => `<tr><td class="cell-primary">${esc(r.customer)}</td><td>${esc(r.service)}</td><td>${esc(r.staff)}</td><td>${starsHTML(r.rating)}</td><td style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(r.comment)}</td><td>${esc(r.date)}</td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button data-act="respond-review" data-id="${r.id}"><i class="ti ti-message"></i> Respond</button><button class="danger" data-act="delete-review" data-id="${r.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('') || `<tr><td class="cell-muted" colspan="7" style="text-align:center;padding:20px">No reviews yet</td></tr>`;
}
let respondingReviewId = null;
function openReviewModal(id) { respondingReviewId = id || null; const r = db.reviews.find(x => x.id === id); if (!r) return; $('#rv-response').value = r.response || ''; openModal('#review-modal'); }
function saveReviewResponse() { if (!respondingReviewId) return; const r = db.reviews.find(x => x.id === respondingReviewId); if (r) { r.response = $('#rv-response').value.trim(); saveLocal(); closeModal('#review-modal'); renderReviews(); toast('Response saved'); } }
function deleteReview(id) { db.reviews = db.reviews.filter(r => r.id !== id); saveLocal(); renderReviews(); toast('Review deleted', true); }

// ─── Settings (localStorage + API user management) ───────────
function renderSettings() {
  if ($('#settings-salon-name')) $('#settings-salon-name').value = db.settings.salonName;
  if ($('#settings-salon-address')) $('#settings-salon-address').value = db.settings.salonAddress;
  if ($('#settings-salon-phone')) $('#settings-salon-phone').value = db.settings.salonPhone;
  if ($('#settings-salon-email')) $('#settings-salon-email').value = db.settings.salonEmail;
  if ($('#settings-tax-rate')) $('#settings-tax-rate').value = db.settings.taxRate;
  if ($('#settings-currency')) $('#settings-currency').value = db.settings.currency;
  if ($('#settings-lowstock-threshold')) $('#settings-lowstock-threshold').value = db.settings.lowStockThreshold;
  if ($('#settings-users-tbody')) {
    if (db.users.length) {
      $('#settings-users-tbody').innerHTML = db.users.map(u => `<tr><td class="cell-primary">${esc(u.email)}</td><td>${esc(u.email)}</td><td><span class="badge badge-blue"><span class="bdot"></span>${esc(u.role)}</span></td><td class="actions-cell"><div class="kebab-wrap"><button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button><div class="kebab-menu"><button class="danger" data-act="delete-user" data-id="${u.id}"><i class="ti ti-trash"></i> Delete</button></div></div></td></tr>`).join('');
    } else {
      $('#settings-users-tbody').innerHTML = `<tr><td class="cell-muted" colspan="4" style="text-align:center;padding:20px">No additional users</td></tr>`;
    }
  }
}
function saveSettings() { db.settings.salonName = $('#settings-salon-name').value.trim(); db.settings.salonAddress = $('#settings-salon-address').value.trim(); db.settings.salonPhone = $('#settings-salon-phone').value.trim(); db.settings.salonEmail = $('#settings-salon-email').value.trim(); db.settings.taxRate = Number($('#settings-tax-rate').value); db.settings.currency = $('#settings-currency').value.trim(); db.settings.lowStockThreshold = Number($('#settings-lowstock-threshold').value); saveLocal(); toast('Settings saved'); }
function saveBusinessInfo() { saveSettings(); }
function saveSystemSettings() { saveSettings(); }

// ─── Auth ────────────────────────────────────────────────────
function setUserInfo(u) { if (!u) { $('#user-email').textContent = ''; $('#user-role').textContent = ''; $('#top-avatar').textContent = ''; return; } $('#user-email').textContent = u.email || ''; $('#user-role').textContent = ROLE_LABEL[u.role] || u.role; $('#top-avatar').textContent = u.name ? initials(u.name) : 'U'; if (u.role) renderSidebar(u); }
function showLogin() { ['dashboard', 'appointments', 'clients', 'staff', 'services', 'inventory', 'scheduling', 'billing', 'loyalty', 'reports', 'notifications', 'reviews', 'settings', 'my-bookings', 'book-appointment'].forEach(p => { const el = $('#page-' + p); if (el) el.style.display = 'none'; }); $('#login-overlay').classList.add('open'); $('#login-err').textContent = ''; }

async function doLogin() {
  const email = $('#login-email').value.trim().toLowerCase(), pass = $('#login-pass').value;
  if (!email || !pass) { $('#login-err').textContent = 'Email and password required.'; return; }
  $('#login-btn').disabled = true; $('#login-btn').innerHTML = '<span class="spinner"></span> Signing in...';
  try {
    const data = await api('POST', '/auth/login', { email, password: pass });
    storeTokens(data.access_token, data.refresh_token);
    tokenPayload = decodeToken(data.access_token);
    await loadAllData();
    setUserInfo({ email, role: tokenPayload.role, name: email.split('@')[0] });
    $('#login-overlay').classList.remove('open');
    currentPage = tokenPayload.role === 'client' ? 'my-bookings' : 'dashboard'; navigate(currentPage);
    toast('Welcome!');
  } catch(e) { $('#login-err').textContent = e.message || 'Login failed'; }
  $('#login-btn').disabled = false; $('#login-btn').textContent = 'Login';
}

async function doRegister() {
  const org = $('#reg-org') ? $('#reg-org').value.trim() : '', email = $('#reg-email') ? $('#reg-email').value.trim() : '', pass = $('#reg-pass') ? $('#reg-pass').value : '', name = $('#reg-name') ? $('#reg-name').value.trim() : '';
  if (!org || !email || !pass || !name) { const errEl = $('#register-err') || $('#login-err'); errEl.textContent = 'All fields required.'; return; }
  const btn = $('#register-btn') || $('#login-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Creating...';
  try {
    const data = await api('POST', '/auth/register', { organization_name: org, email, password: pass, display_name: name });
    storeTokens(data.access_token, data.refresh_token);
    tokenPayload = decodeToken(data.access_token);
    await loadAllData();
    setUserInfo({ email, role: 'admin', name });
    $('#login-overlay').classList.remove('open');
    currentPage = 'dashboard'; render();
    toast('Organization created! Welcome!');
  } catch(e) { const errEl = $('#register-err') || $('#login-err'); errEl.textContent = e.message || 'Registration failed'; }
  btn.disabled = false; btn.textContent = 'Create account';
}

async function doClientRegister() {
  const name = ($('#cr-name') ? $('#cr-name').value.trim() : ''), phone = ($('#cr-phone') ? $('#cr-phone').value.trim() : ''), email = ($('#cr-email') ? $('#cr-email').value.trim() : ''), pass = ($('#cr-pass') ? $('#cr-pass').value : '');
  if (!name || !email || !pass) { const errEl = $('#client-reg-err') || $('#login-err'); errEl.textContent = 'Name, email and password required.'; return; }
  const btn = $('#client-reg-btn') || $('#login-btn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Creating...';
  try {
    const data = await api('POST', '/auth/client-register', { full_name: name, email, password: pass, phone: phone || null });
    storeTokens(data.access_token, data.refresh_token);
    tokenPayload = decodeToken(data.access_token);
    await loadAllData();
    setUserInfo({ email, role: 'client', name });
    $('#login-overlay').classList.remove('open');
    currentPage = 'my-bookings'; navigate(currentPage);
    toast('Account created! Welcome!');
  } catch(e) { const errEl = $('#client-reg-err') || $('#login-err'); errEl.textContent = e.message || 'Registration failed'; }
  btn.disabled = false; btn.textContent = 'Create Account';
}

function doLogout() { clearTokens(); session = null; setUserInfo(null); currentPage = 'dashboard'; showLogin(); toast('Signed out'); }

// ─── Event Handlers ──────────────────────────────────────────
document.addEventListener('click', e => {
  const nav = e.target.closest('.nav-item'); if (nav) { navigate(nav.dataset.page); return; }
  const kb = e.target.closest('.kebab-btn'); if (kb) { toggleKebab(kb); return; }
  const act = e.target.closest('[data-act]');
  if (act) {
    const id = act.dataset.id;
    switch (act.dataset.act) {
      case 'checkin': case 'complete': case 'cancel': case 'confirm': apptAction(act.dataset.act, id); break;
      case 'edit-client': openClientModal(id); break;
      case 'delete-client': deleteClient(id); break;
      case 'edit-staff': openStaffModal(id); break;
      case 'toggle-staff': toggleStaff(id); break;
      case 'delete-staff': deleteStaff(id); break;
      case 'edit-svc': openSvcModal(id); break;
      case 'delete-svc': deleteSvc(id); break;
      case 'edit-inv': openInventoryModal(id); break;
      case 'stock-in': stockIn(id); break;
      case 'stock-out': stockOut(id); break;
      case 'delete-inv': deleteProduct(id); break;
      case 'toggle-schedule': toggleSchedule(act.dataset.staff, act.dataset.day); break;
      case 'toggle-promo': togglePromo(id); break;
      case 'delete-promo': deletePromo(id); break;
      case 'edit-loyalty': openLoyaltyModal(id); break;
      case 'toggle-notif-read': { const n = (db.notifications || []).find(x => String(x.id) === String(id)); if (n) { n.is_read = !n.is_read; saveLocal(); renderNotifications(); renderNotifBell(); toast(n.is_read ? 'Marked as read' : 'Marked as unread'); } break; }
      case 'delete-notif': deleteNotif(id); break;
      case 'respond-review': openReviewModal(id); break;
      case 'delete-review': deleteReview(id); break;
      case 'delete-user': deleteUser(id); break;
      case 'remove-loyalty': { const c = db.clients.find(x => x.id === id); if (c) { c.loyaltyPoints = 0; c.tier = 'Bronze'; saveLocal(); renderLoyalty(); toast('Removed from loyalty'); } break; }
    }
    closeAllKebabs(); return;
  }
  if (!e.target.closest('.kebab-wrap')) closeAllKebabs();
  const pg = e.target.closest('[data-pg]'); if (pg) { const k = keyFromPager(pg); if (k) { pagerState[k].page = Number(pg.dataset.pg); render(); } return; }
  const lp = e.target.closest('[data-tab]'); if (lp && lp.dataset.tab) { switchLoyaltyTab(lp.dataset.tab); return; }
  const pm = e.target.closest('[data-method]'); if (pm) { selectPaymentMethod(pm.dataset.method); return; }
  const bs = e.target.closest('[data-addtype]'); if (bs) { addBillingItemFromInput(bs.dataset.addtype); return; }
  const st = e.target.closest('[data-settingsave]'); if (st) { saveSettings(); return; }
  const closer = e.target.closest('[data-close]'); if (closer) { closeModal('#' + closer.dataset.close); }
  const loginTab = e.target.closest('[data-login-tab]');
  if (loginTab) {
    $$('#login-tabs .tab').forEach(x => x.classList.remove('active'));
    loginTab.classList.add('active');
    const tab = loginTab.dataset.loginTab;
    const emailForm = $('#login-email-form');
    const clientRegForm = $('#client-register-form');
    const sub = $('#login-sub');
    if (tab === 'login') {
      if (emailForm) emailForm.style.display = 'flex';
      if (clientRegForm) clientRegForm.style.display = 'none';
      if (sub) sub.textContent = 'Sign in to your account';
    } else if (tab === 'signup') {
      if (emailForm) emailForm.style.display = 'none';
      if (clientRegForm) clientRegForm.style.display = 'flex';
      if (sub) sub.textContent = 'Create a customer account';
    }
    return;
  }
});

document.addEventListener('change', e => {
  const sel = e.target;
  if (sel.matches('[data-size]')) { const k = keyFromPager(sel); if (k) { pagerState[k].size = Number(sel.value); pagerState[k].page = 1; render(); } return; }
  if (sel.matches('#f-service')) { const svc = db.services.find(s => s.name === sel.value.trim()); if (svc && $('#f-price')) $('#f-price').value = svc.price; return; }
  if (sel.id === 'appts-status') { filters.appointments.status = sel.value; resetPage('appointments'); render(); return; }
  if (sel.id === 'appts-date') { filters.appointments.date = sel.value; resetPage('appointments'); render(); return; }
  if (sel.id === 'staff-status') { filters.staff.status = sel.value; resetPage('staff'); render(); return; }
  if (sel.id === 'inv-cat-filter') { filters.inventory.category = sel.value; resetPage('inventory'); render(); return; }
});

document.addEventListener('input', e => {
  const inp = e.target;
  if (inp.matches('.search-input')) { const key = inp.dataset.key; if (!filters[key]) filters[key] = { q: '' }; filters[key].q = inp.value; resetPage(key); render(); return; }
  if (inp.matches('#f-service')) { const svc = db.services.find(s => s.name === inp.value.trim()); if (svc && $('#f-price')) $('#f-price').value = svc.price; }
});

async function deleteUser(id) { try { await api('DELETE', '/auth/users/' + id); await loadAllData(); renderSettings(); toast('User deleted', true); } catch(e) { toast(e.message, true); } }

// ─── Notifications Bell ──────────────────────────────────────
function renderNotifBell() {
  const unread = (db.notifications || []).filter(n => !n.is_read).length;
  const badge = $('#notif-badge');
  if (badge) { badge.textContent = unread; badge.style.display = unread > 0 ? 'flex' : 'none'; }
  const list = $('#notif-dd-list');
  if (list) {
    if (!db.notifications || !db.notifications.length) { list.innerHTML = '<div class="notif-dd-empty">No notifications yet</div>'; return; }
    list.innerHTML = db.notifications.slice(0, 20).map(n => `
      <div class="notif-dd-item${n.is_read ? '' : ' unread'}" onclick="readNotif('${n.id}')">
        <div class="notif-dd-item-title">${esc(n.title)}</div>
        <div class="notif-dd-item-msg">${esc(n.message)}</div>
        <div class="notif-dd-item-time">${timeAgo(n.created_at)}</div>
      </div>`).join('');
  }
}
function toggleNotifDropdown() { const dd = $('#notif-dropdown'); if (dd) dd.classList.toggle('open'); }
async function readNotif(id) {
  const n = db.notifications.find(x => x.id === id);
  if (n && !n.is_read) { try { await api('PATCH', '/notifications/' + id, { is_read: true }); n.is_read = true; renderNotifBell(); } catch(e) {} }
}
async function markAllRead() {
  try { await api('POST', '/notifications/read-all'); db.notifications.forEach(n => n.is_read = true); renderNotifBell(); } catch(e) {}
}
function timeAgo(d) { if (!d) return ''; const s = Math.floor((Date.now() - new Date(d).getTime()) / 1000); if (s < 60) return 'just now'; if (s < 3600) return Math.floor(s/60) + 'm ago'; if (s < 86400) return Math.floor(s/3600) + 'h ago'; return Math.floor(s/86400) + 'd ago'; }
document.addEventListener('click', e => { const dd = $('#notif-dropdown'); if (dd && dd.classList.contains('open') && !e.target.closest('.notif-bell-wrap')) dd.classList.remove('open'); });

// ─── Client: My Bookings ─────────────────────────────────────
async function renderMyBookings() {
  const me = currentUser(); if (!me) return;
  const myClient = db.clients.find(c => c.email && c.email.toLowerCase() === (tokenPayload.email || '').toLowerCase());
  const myClientId = myClient ? myClient.id : null;
  const myAppts = myClientId ? db.appointments.filter(a => a.clientId === myClientId) : [];
  const tbody = $('#mybookings-tbody');
  if (tbody) tbody.innerHTML = myAppts.map(a => `<tr><td class="cell-primary">${esc(a.date)}</td><td>${esc(a.time)}</td><td>${esc(a.service)}</td><td>${esc(a.staff)}</td><td><span class="badge ${APPT_STATUS[a.status]?.badge || 'badge-gray'}"><span class="bdot"></span>${APPT_STATUS[a.status]?.label || a.status}</span></td><td>${money(a.price)}</td><td>${a.status === 'requested' || a.status === 'confirmed' ? '<button class="btn btn-sm btn-outline" onclick="cancelMyBooking(\'' + a.id + '\')"><i class="ti ti-ban"></i> Cancel</button>' : ''}</td></tr>`).join('');
  if ($('#mybookings-empty')) $('#mybookings-empty').style.display = myAppts.length ? 'none' : 'block';
  if ($('#mybookings-total')) $('#mybookings-total').textContent = myAppts.length + ' booking' + (myAppts.length === 1 ? '' : 's');
}
async function cancelMyBooking(id) {
  try { await api('POST', '/appointments/' + id + '/status', { status: 'cancelled', cancellation_reason: 'Cancelled by customer' }); await loadAllData(); renderMyBookings(); toast('Booking cancelled'); } catch(e) { toast(e.message, true); }
}

// ─── Client: Book Appointment ─────────────────────────────────
function renderBookAppointment() {
  const svcSel = $('#bk-service'); const staffSel = $('#bk-staff');
  if (svcSel) svcSel.innerHTML = '<option value="">Select a service...</option>' + db.services.map(s => `<option value="${s.id}">${esc(s.name)} — ${money(s.price)} (${s.duration} min)</option>`).join('');
  if (staffSel) staffSel.innerHTML = '<option value="">Any available stylist</option>' + db.staff.filter(s => s.status === 'active').map(s => `<option value="${s.id}">${esc(s.name)} — ${esc(s.role)}</option>`).join('');
  const today = todayISO();
  if ($('#bk-date')) $('#bk-date').value = today;
  if ($('#bk-date')) $('#bk-date').min = today;
}
async function submitBooking() {
  const serviceId = $('#bk-service').value, staffId = $('#bk-staff').value, date = $('#bk-date').value, time = $('#bk-time').value;
  if (!serviceId || !date || !time) { $('#bk-err').textContent = 'Please select a service, date and time.'; return; }
  try {
    const me = currentUser(); if (!me) { $('#bk-err').textContent = 'Not logged in'; return; }
    let clientId = null;
    const myClient = db.clients.find(c => c.email === (tokenPayload.email || ''));
    if (myClient) clientId = myClient.id;
    if (!clientId) { const c = await api('POST', '/clients', { full_name: tokenPayload.userId || 'Customer', phone: '', email: tokenPayload.email || null, notes: 'Created from booking' }); clientId = c.id; }
    const payload = { client_id: clientId, staff_id: staffId || db.staff[0].id, service_id: serviceId, start_time: toISOWithTZ(date, time), discount_cents: 0 };
    await api('POST', '/appointments', payload);
    await loadAllData(); currentPage = 'my-bookings'; render(); toast('Appointment booked!');
  } catch(e) { $('#bk-err').textContent = e.message; }
}

// ─── Init ────────────────────────────────────────────────────
window.addEventListener('load', async () => {
  if (authToken) {
    tokenPayload = decodeToken(authToken);
    if (tokenPayload) {
      await loadAllData();
      setUserInfo({ email: tokenPayload.email || '', role: tokenPayload.role, name: '' });
      currentPage = tokenPayload.role === 'client' ? 'my-bookings' : 'dashboard';
      navigate(currentPage);
      return;
    }
  }
  showLogin();
});
