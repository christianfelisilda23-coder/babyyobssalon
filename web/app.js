/* ============================================================
   Bloom Studio · Salon Manager — app logic
   Data is kept in localStorage so changes survive reloads.
   ============================================================ */

const SESSION_KEY = "salon_session";
const DB_KEY = "salon_db_v3";

/* ---------------- Database store ----------------
   Starts empty for a clean presentation. Records are created
   through the UI and persisted in the browser's localStorage. */
const DB = {
  users: [
    { id: 1, name: "Administrator", role: "admin", email: "admin@salon.com", pass: "admin" },
    { id: 2, name: "Owner", role: "owner", email: "owner@salon.com", pass: "owner" },
    { id: 3, name: "Staff", role: "staff", email: "staff@salon.com", pass: "staff" }
  ],
  services: [],
  staff: [],
  clients: [],
  appointments: [],
  nextId: { user: 4, service: 1, staff: 1, client: 1, appointment: 1 }
};

/* ---------------- Persistence helpers ---------------- */
function loadDB() {
  try {
    const raw = localStorage.getItem(DB_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      const merged = Object.assign({}, DB, saved);
      merged.nextId = Object.assign({}, DB.nextId, saved.nextId || {});
      return merged;
    }
  } catch (e) { /* fall back to defaults */ }
  return DB;
}
function saveDB() {
  localStorage.setItem(DB_KEY, JSON.stringify(db));
}
let db = loadDB();

/* ---------------- Session ---------------- */
let session = null;
try { session = JSON.parse(localStorage.getItem(SESSION_KEY)) || null; } catch (e) { session = null; }

function currentUser() {
  return session ? db.users.find(u => u.id === session.userId) : null;
}

const ROLE_ACCESS = {
  admin: ["dashboard", "appointments", "clients", "staff", "services", "reports"],
  owner: ["dashboard", "appointments", "clients", "staff", "services", "reports"],
  staff: ["dashboard", "appointments"]
};
const ROLE_LABEL = { admin: "Administrator", owner: "Owner", staff: "Staff" };

function canAccess(page) {
  const u = currentUser();
  return !!u && (ROLE_ACCESS[u.role] || []).includes(page);
}

function renderSidebar(u) {
  const allowed = ROLE_ACCESS[u.role] || [];
  const groups = [
    { label: "Overview", items: [
      { page: "dashboard", icon: "ti ti-layout-dashboard", label: "Dashboard" },
      { page: "appointments", icon: "ti ti-calendar-event", label: "Appointments", badge: true },
      { page: "clients", icon: "ti ti-users", label: "Clients" }
    ]},
    { label: "Management", items: [
      { page: "staff", icon: "ti ti-user-circle", label: "Staff" },
      { page: "services", icon: "ti ti-scissors", label: "Services" },
      { page: "reports", icon: "ti ti-chart-bar", label: "Reports" }
    ]}
  ];
  $("#sidebar-nav").innerHTML = groups.map(g => {
    const items = g.items.filter(i => allowed.includes(i.page));
    if (!items.length) return "";
    return `<div class="nav-section">${g.label}</div>` + items.map(i =>
      `<a class="nav-item${i.page === currentPage ? " active" : ""}" data-page="${i.page}" href="#">` +
      `<i class="${i.icon}"></i> ${i.label}${i.badge ? ' <span class="badge-count" id="nav-appts">0</span>' : ""}</a>`
    ).join("");
  }).join("");
}

/* ---------------- Helpers ---------------- */
const $ = (sel, el) => (el || document).querySelector(sel);
const $$ = (sel, el) => Array.from((el || document).querySelectorAll(sel));

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}
function money(n) { return "₱" + Number(n || 0).toLocaleString("en-PH"); }
function initials(name) { return name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase(); }
function todayISO() { return new Date().toISOString().slice(0, 10); }

const APPT_STATUS = {
  pending:     { label: "Pending",    badge: "badge-amber" },
  confirmed:   { label: "Confirmed",  badge: "badge-blue" },
  "checked-in": { label: "Checked In", badge: "badge-emerald" },
  completed:   { label: "Completed",  badge: "badge-gray" },
  cancelled:   { label: "Cancelled",  badge: "badge-rose" }
};
const STAFF_STATUS = {
  active:   { label: "Active",   badge: "badge-emerald" },
  onleave:  { label: "On Leave", badge: "badge-amber" },
  inactive: { label: "Inactive", badge: "badge-rose" }
};

/* ---------------- Toast ---------------- */
let toastTimer = null;
function toast(msg, isErr) {
  const el = $("#toast");
  el.textContent = msg;
  el.className = "toast" + (isErr ? " err" : "");
  el.style.display = "block";
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = "none"; }, 3200);
}

/* ---------------- Routing ---------------- */
let currentPage = "dashboard";

function navigate(page) {
  if (!canAccess(page)) page = "dashboard";
  currentPage = page;
  $$(".nav-item").forEach(n => n.classList.toggle("active", n.dataset.page === page));
  $$("#page-dashboard, #page-appointments, #page-clients, #page-staff, #page-services, #page-reports")
    .forEach(s => { s.style.display = s.id === "page-" + page ? "block" : "none"; });
  closeAllKebabs();
  render();
}

function render() {
  if ($("#nav-appts")) {
    $("#nav-appts").textContent = db.appointments.filter(a => a.status !== "cancelled" && a.status !== "completed").length;
  }
  const fn = { dashboard: renderDashboard, appointments: renderAppointments,
    clients: renderClients, staff: renderStaff, services: renderServices,
    reports: renderReports }[currentPage];
  if (fn) fn();
}

/* ---------------- Pager state ---------------- */
const pagerState = { appointments: { page: 1, size: 8 }, clients: { page: 1, size: 8 }, staff: { page: 1, size: 8 } };
const filters = {
  appointments: { q: "", status: "all", date: "all" },
  clients: { q: "" },
  staff: { q: "", status: "all" }
};
const PAGER_IDS = { appointments: "appts-pager", clients: "clients-pager", staff: "staff-pager" };

function resetPage(key) { pagerState[key].page = 1; }

function pageSlice(key, list) {
  const p = pagerState[key];
  const pages = Math.max(1, Math.ceil(list.length / p.size));
  p.page = Math.min(Math.max(1, p.page), pages);
  const start = (p.page - 1) * p.size;
  return { rows: list.slice(start, start + p.size), total: list.length, page: p.page, pages };
}

function pagerHTML(key, info) {
  if (info.total === 0) return "";
  const btns = [];
  for (let i = 1; i <= info.pages; i++) {
    btns.push(`<button data-pg="${i}" ${i === info.page ? 'class="active"' : ""}>${i}</button>`);
  }
  return `<div class="pager">
    <div class="pager-left">${info.total} result${info.total === 1 ? "" : "s"}
      <select data-size>${[8, 15, 25].map(s => `<option value="${s}" ${s === pagerState[key].size ? "selected" : ""}>${s}</option>`).join("")} per page</select>
    </div>
    <div class="pager-btns">${btns.join("")}</div>
  </div>`;
}

/* ---------------- Kebab menus / modals ---------------- */
function toggleKebab(btn) {
  closeAllKebabs();
  btn.closest(".kebab-wrap").querySelector(".kebab-menu").classList.add("open");
}
function closeAllKebabs() {
  $$(".kebab-menu.open").forEach(m => m.classList.remove("open"));
}
function openModal(id) { $(id).classList.add("open"); }
function closeModal(id) { $(id).classList.remove("open"); }

/* ---------------- Dashboard ---------------- */
function renderDashboard() {
  const today = todayISO();
  const appts = db.appointments;
  $("#kpi-today").textContent = appts.filter(a => a.date === today).length;
  $("#kpi-revenue").textContent = money(appts.filter(a => a.date === today).reduce((s, a) => s + a.price, 0));
  $("#kpi-clients").textContent = db.clients.length;
  $("#kpi-staff").textContent = db.staff.filter(s => s.status === "active").length;

  const upcoming = appts
    .filter(a => a.date >= today && a.status !== "cancelled")
    .sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time))
    .slice(0, 7);

  $("#upcoming-tbody").innerHTML = upcoming.map(a => `<tr>
    <td class="cell-primary">${esc(a.date)}</td>
    <td>${esc(a.time)}</td>
    <td class="cell-primary">${esc(a.client)}</td>
    <td>${esc(a.service)}</td>
    <td>${esc(a.staff)}</td>
    <td><span class="badge ${APPT_STATUS[a.status].badge}"><span class="bdot"></span>${APPT_STATUS[a.status].label}</span></td>
    <td>${money(a.price)}</td></tr>`).join("");
  $("#upcoming-empty").style.display = upcoming.length ? "none" : "block";

  $("#mobile-upcoming").innerHTML = upcoming.map(a => `<div class="mcard">
    <div class="mcard-top"><span class="mcard-title">${esc(a.client)}</span>
      <span class="badge ${APPT_STATUS[a.status].badge}"><span class="bdot"></span>${APPT_STATUS[a.status].label}</span></div>
    <div class="mcard-sub">${esc(a.service)} · ${esc(a.staff)}</div>
    <div class="mcard-row"><span>${esc(a.date)} ${esc(a.time)}</span><span>${money(a.price)}</span></div>
  </div>`).join("") || '<div class="empty-state"><p>No upcoming appointments</p></div>';

  $("#dashboard-staff-tbody").innerHTML = db.staff.map(s => {
    const done = appts.filter(a => a.staff === s.name && a.date === today && a.status !== "cancelled");
    const pct = Math.min(100, done.length * 20);
    return `<tr>
      <td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${esc(s.initials)}</div><span class="cell-primary">${esc(s.name)}</span></div></td>
      <td class="cell-muted">${esc(s.role)}</td>
      <td>${done.length}</td>
      <td>${money(done.reduce((x, a) => x + a.price, 0))}</td>
      <td style="min-width:120px"><div style="display:flex;align-items:center;gap:8px">
        <div style="flex:1;height:6px;background:var(--g100);border-radius:999px"><div style="width:${pct}%;height:6px;background:var(--primary);border-radius:999px"></div></div>
        <span style="font-size:12px;color:var(--g500)">${pct}%</span></div></td></tr>`;
  }).join("");
  $("#dashboard-staff-empty").style.display = db.staff.length ? "none" : "block";
}

/* ---------------- Appointments page ---------------- */
function renderAppointments() {
  const f = filters.appointments;
  const source = db.appointments.filter(a => {
    if (f.q && !(a.client + a.service + a.staff).toLowerCase().includes(f.q.toLowerCase())) return false;
    if (f.status !== "all" && a.status !== f.status) return false;
    if (f.date === "today" && a.date !== todayISO()) return false;
    if (f.date === "upcoming" && (a.date < todayISO() || a.status === "cancelled")) return false;
    return true;
  }).sort((a, b) => (a.date + a.time).localeCompare(b.date + b.time));

  const info = pageSlice("appointments", source);
  $("#appts-tbody").innerHTML = info.rows.map(a => `<tr>
    <td class="cell-primary">${esc(a.date)}</td>
    <td>${esc(a.time)}</td>
    <td class="cell-primary">${esc(a.client)}</td>
    <td>${esc(a.service)}</td>
    <td>${esc(a.staff)}</td>
    <td><span class="badge ${APPT_STATUS[a.status].badge}"><span class="bdot"></span>${APPT_STATUS[a.status].label}</span></td>
    <td>${money(a.price)}</td>
    <td class="actions-cell"><div class="kebab-wrap">
      <button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button>
      <div class="kebab-menu">
        <button data-act="checkin" data-id="${a.id}"><i class="ti ti-check"></i> Check in</button>
        <button data-act="complete" data-id="${a.id}"><i class="ti ti-circle-check"></i> Mark completed</button>
        <button data-act="cancel" data-id="${a.id}"><i class="ti ti-ban"></i> Cancel booking</button>
        <hr>
        <button class="danger" data-act="delete-appt" data-id="${a.id}"><i class="ti ti-trash"></i> Delete</button>
      </div></div></td></tr>`).join("");

  $("#appts-empty").style.display = info.total ? "none" : "block";
  $("#appts-pager").innerHTML = pagerHTML("appointments", info);
  $("#appts-total").textContent = info.total + " appointment" + (info.total === 1 ? "" : "s");

  $("#appts-mobile").innerHTML = info.rows.map(a => `<div class="mcard">
    <div class="mcard-top"><span class="mcard-title">${esc(a.client)}</span>
      <span class="badge ${APPT_STATUS[a.status].badge}"><span class="bdot"></span>${APPT_STATUS[a.status].label}</span></div>
    <div class="mcard-sub">${esc(a.service)} · ${esc(a.staff)}</div>
    <div class="mcard-row"><span>${esc(a.date)} ${esc(a.time)}</span><span>${money(a.price)}</span></div>
  </div>`).join("");
}

/* ---------------- Clients page ---------------- */
function renderClients() {
  const f = filters.clients;
  const source = db.clients.filter(c =>
    !f.q || (c.name + c.phone + c.email).toLowerCase().includes(f.q.toLowerCase())
  );
  const info = pageSlice("clients", source);
  $("#clients-tbody").innerHTML = info.rows.map(c => `<tr>
    <td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${initials(c.name)}</div><span class="cell-primary">${esc(c.name)}</span></div></td>
    <td><div>${esc(c.phone)}</div><div class="cell-muted" style="font-size:12px">${esc(c.email)}</div></td>
    <td>${c.visit} <span class="cell-muted" style="font-size:12px">visits</span></td>
    <td>${money(c.ltv)}</td>
    <td class="actions-cell"><div class="kebab-wrap">
      <button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button>
      <div class="kebab-menu">
        <button data-act="edit-client" data-id="${c.id}"><i class="ti ti-pencil"></i> Edit client</button>
        <button class="danger" data-act="delete-client" data-id="${c.id}"><i class="ti ti-trash"></i> Delete</button>
      </div></div></td></tr>`).join("");

  $("#clients-empty").style.display = info.total ? "none" : "block";
  $("#clients-pager").innerHTML = pagerHTML("clients", info);
  $("#clients-total").textContent = info.total + " client" + (info.total === 1 ? "" : "s");

  $("#clients-mobile").innerHTML = info.rows.map(c => `<div class="mcard">
    <div class="mcard-top"><span class="mcard-title">${esc(c.name)}</span></div>
    <div class="mcard-sub">${esc(c.phone)}</div>
    <div class="mcard-row"><span>${c.visit} visits</span><span>${money(c.ltv)} LTV</span></div>
  </div>`).join("");
}

/* ---------------- Staff page ---------------- */
function renderStaff() {
  const f = filters.staff;
  const source = db.staff.filter(s => {
    if (f.q && !(s.name + s.role).toLowerCase().includes(f.q.toLowerCase())) return false;
    if (f.status !== "all" && s.status !== f.status) return false;
    return true;
  });
  const info = pageSlice("staff", source);
  $("#staff-tbody").innerHTML = info.rows.map(s => `<tr>
    <td><div style="display:flex;align-items:center;gap:10px"><div class="avatar" style="width:28px;height:28px;font-size:10px">${esc(s.initials)}</div><span class="cell-primary">${esc(s.name)}</span></div></td>
    <td class="cell-muted">${esc(s.role)}</td>
    <td><div>${esc(s.phone)}</div><div class="cell-muted" style="font-size:12px">${esc(s.email)}</div></td>
    <td><span class="badge ${STAFF_STATUS[s.status].badge}"><span class="bdot"></span>${STAFF_STATUS[s.status].label}</span></td>
    <td class="actions-cell"><div class="kebab-wrap">
      <button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button>
      <div class="kebab-menu">
        <button data-act="edit-staff" data-id="${s.id}"><i class="ti ti-pencil"></i> Edit</button>
        <button data-act="toggle-staff" data-id="${s.id}"><i class="ti ti-toggle"></i> ${s.status === "active" ? "Set on leave" : "Set active"}</button>
        <hr>
        <button class="danger" data-act="delete-staff" data-id="${s.id}"><i class="ti ti-trash"></i> Delete</button>
      </div></div></td></tr>`).join("");

  $("#staff-empty").style.display = info.total ? "none" : "block";
  $("#staff-pager").innerHTML = pagerHTML("staff", info);
  $("#staff-total").textContent = info.total + " member" + (info.total === 1 ? "" : "s");

  $("#staff-mobile").innerHTML = info.rows.map(s => `<div class="mcard">
    <div class="mcard-top"><span class="mcard-title">${esc(s.name)}</span>
      <span class="badge ${STAFF_STATUS[s.status].badge}"><span class="bdot"></span>${STAFF_STATUS[s.status].label}</span></div>
    <div class="mcard-sub">${esc(s.role)}</div>
    <div class="mcard-row"><span>${esc(s.phone)}</span></div>
  </div>`).join("");
}

/* ---------------- Services page ---------------- */
function renderServices() {
  $("#svc-count").textContent = db.services.length;
  $("#svc-tbody").innerHTML = db.services.map(s => `<tr>
    <td class="cell-primary">${esc(s.name)}</td>
    <td><span class="badge badge-blue"><span class="bdot"></span>${esc(s.category)}</span></td>
    <td>${s.duration} min</td>
    <td class="cell-primary">${money(s.price)}</td>
    <td class="actions-cell"><div class="kebab-wrap">
      <button class="kebab-btn" onclick="toggleKebab(this)">&#8942;</button>
      <div class="kebab-menu">
        <button data-act="edit-svc" data-id="${s.id}"><i class="ti ti-pencil"></i> Edit</button>
        <button class="danger" data-act="delete-svc" data-id="${s.id}"><i class="ti ti-trash"></i> Delete</button>
      </div></div></td></tr>`).join("");
  $("#svc-empty").style.display = db.services.length ? "none" : "block";
}

/* ---------------- Reports page ---------------- */
function renderReports() {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth();
  const days = new Date(y, m + 1, 0).getDate();
  const start = `${y}-${String(m + 1).padStart(2, "0")}-01`;
  const end = `${y}-${String(m + 1).padStart(2, "0")}-${String(days).padStart(2, "0")}`;

  const monthAppts = db.appointments.filter(a => a.date >= start && a.date <= end && a.status !== "cancelled");
  const revenue = monthAppts.reduce((s, a) => s + a.price, 0);

  $("#rep-total").textContent = money(revenue);
  $("#rep-appts").textContent = monthAppts.length;
  $("#rep-avg").textContent = money(monthAppts.length ? Math.round(revenue / monthAppts.length) : 0);
  $("#rep-coming").textContent = monthAppts.filter(a => a.date >= todayISO()).length;

  const svcCounts = {};
  monthAppts.forEach(a => { svcCounts[a.service] = (svcCounts[a.service] || 0) + 1; });
  const svcRows = Object.entries(svcCounts).sort((x, y) => y[1] - x[1]).slice(0, 6);
  const svcMax = Math.max(1, ...svcRows.map(r => r[1]));
  $("#rep-svc-tbody").innerHTML = svcRows.length ? svcRows.map(([name, n]) => `<tr>
    <td class="cell-primary">${esc(name)}</td>
    <td><div style="display:flex;align-items:center;gap:8px">
      <div style="flex:1;height:6px;background:var(--g100);border-radius:999px"><div style="width:${Math.round(n / svcMax * 100)}%;height:6px;background:var(--primary);border-radius:999px"></div></div>
      <span style="font-size:12px;color:var(--g500);width:26px;text-align:right">${n}</span></div></td></tr>`).join("")
    : `<tr><td class="cell-muted">No bookings this month yet.</td><td></td></tr>`;

  $("#rep-staff-tbody").innerHTML = db.staff.length ? db.staff
    .map(s => {
      const sAppts = monthAppts.filter(a => a.staff === s.name);
      return { name: s.name, count: sAppts.length, revenue: sAppts.reduce((x, a) => x + a.price, 0) };
    })
    .sort((a, b) => b.revenue - a.revenue)
    .map(p => `<tr><td class="cell-primary">${esc(p.name)}</td><td>${p.count}</td><td>${money(p.revenue)}</td></tr>`)
    .join("") : '<tr><td class="cell-muted">No staff members yet.</td><td></td><td></td></tr>';

  const uniq = new Set();
  db.appointments.forEach(a => { if (a.date >= start && a.date <= end) uniq.add(a.client); });
  $("#rep-clients").textContent = uniq.size;

  $("#rep-recent-tbody").innerHTML = db.appointments
    .filter(a => a.status === "completed" || a.status === "checked-in")
    .sort((a, b) => b.id - a.id).slice(0, 5).map(a => `<tr>
    <td class="cell-primary">${esc(a.client)}</td>
    <td>${esc(a.service)}</td>
    <td>${esc(a.date)}</td>
    <td>${money(a.price)}</td></tr>`).join("");
}

/* ---------------- Appointment modal ---------------- */
let editingApptId = null;

function openApptModal(id) {
  editingApptId = id || null;
  $("#appt-err").textContent = "";
  const a = id ? db.appointments.find(x => x.id === id) : null;
  $("#appt-modal-title").textContent = a ? "Edit appointment" : "New appointment";
  $("#f-date").value = a ? a.date : todayISO();
  $("#f-time").value = a ? a.time : "10:00";

  $("#clients-list").innerHTML = db.clients.map(c => `<option value="${esc(c.name)}"></option>`).join("");
  $("#services-list").innerHTML = db.services.map(s => `<option value="${esc(s.name)}"></option>`).join("");
  $("#staff-list").innerHTML = db.staff.filter(s => s.status !== "inactive").map(s => `<option value="${esc(s.name)}"></option>`).join("");

  $("#f-client").value = a ? a.client : (db.clients[0] ? db.clients[0].name : "");
  $("#f-service").value = a ? a.service : "";
  $("#f-staff").value = a ? a.staff : (db.staff[0] ? db.staff[0].name : "");
  const svc = a ? db.services.find(s => s.name === a.service) : null;
  $("#f-price").value = a ? a.price : (svc ? svc.price : "");
  $("#f-status").value = a ? a.status : "confirmed";
  openModal("#appt-modal");
}
function saveAppointment() {
  const date = $("#f-date").value.trim();
  const time = $("#f-time").value.trim();
  const clientName = $("#f-client").value.trim();
  const serviceName = $("#f-service").value.trim();
  const staffName = $("#f-staff").value.trim();
  const price = Number($("#f-price").value);
  const status = $("#f-status").value;

  if (!date || !time || !clientName || !serviceName || !staffName) {
    $("#appt-err").textContent = "Please fill in all fields.";
    return;
  }

  let client = db.clients.find(c => c.name === clientName);
  if (!client) {
    client = { id: db.nextId.client++, name: clientName, phone: "", email: "", visit: 0, ltv: 0 };
    db.clients.push(client);
  }

  let svc = db.services.find(s => s.name === serviceName);
  if (!svc) {
    if (!price) { $("#appt-err").textContent = "This is a new service — enter a price for it."; return; }
    svc = { id: db.nextId.service++, name: serviceName, price, duration: 60, category: "General" };
    db.services.push(svc);
  }

  let staff = db.staff.find(s => s.name === staffName);
  if (!staff) {
    staff = { id: db.nextId.staff++, name: staffName, role: "Stylist", phone: "", email: "", status: "active", initials: initials(staffName) };
    db.staff.push(staff);
  }

  const finalPrice = price || svc.price;
  if (editingApptId) {
    Object.assign(db.appointments.find(x => x.id === editingApptId), { date, time, client: client.name, service: svc.name, staff: staff.name, price: finalPrice, status });
  } else {
    db.appointments.push({ id: db.nextId.appointment++, date, time, client: client.name, service: svc.name, staff: staff.name, price: finalPrice, status });
  }
  saveDB();
  closeModal("#appt-modal");
  resetPage("appointments");
  renderAppointments();
  toast("Appointment saved");
}
function apptAction(act, id) {
  const a = db.appointments.find(x => x.id === id);
  if (!a) return;
  if (act === "checkin") a.status = "checked-in";
  if (act === "complete") a.status = "completed";
  if (act === "cancel") a.status = "cancelled";
  saveDB();
  renderAppointments();
  toast("Appointment status updated");
}
function deleteAppointment(id) {
  db.appointments = db.appointments.filter(a => a.id !== id);
  saveDB();
  renderAppointments();
  toast("Appointment deleted", true);
}

/* ---------------- Client modal ---------------- */
let editingClientId = null;

function openClientModal(id) {
  editingClientId = id || null;
  $("#client-err").textContent = "";
  const c = id ? db.clients.find(x => x.id === id) : null;
  $("#client-modal-title").textContent = c ? "Edit client" : "New client";
  $("#cf-name").value = c ? c.name : "";
  $("#cf-phone").value = c ? c.phone : "";
  $("#cf-email").value = c ? c.email : "";
  openModal("#client-modal");
}
function saveClient() {
  const name = $("#cf-name").value.trim();
  const phone = $("#cf-phone").value.trim();
  const email = $("#cf-email").value.trim();
  if (!name || !phone) { $("#client-err").textContent = "Name and phone are required."; return; }
  if (editingClientId) {
    Object.assign(db.clients.find(c => c.id === editingClientId), { name, phone, email });
  } else {
    db.clients.push({ id: db.nextId.client++, name, phone, email, visit: 0, ltv: 0 });
  }
  saveDB();
  closeModal("#client-modal");
  renderClients();
  toast(editingClientId ? "Client updated" : "Client added");
}
function deleteClient(id) {
  db.clients = db.clients.filter(c => c.id !== id);
  saveDB();
  renderClients();
  toast("Client deleted", true);
}

/* ---------------- Staff modal ---------------- */
let editingStaffId = null;

function openStaffModal(id) {
  editingStaffId = id || null;
  $("#staff-err").textContent = "";
  const s = id ? db.staff.find(x => x.id === id) : null;
  $("#staff-modal-title").textContent = s ? "Edit staff member" : "Add staff member";
  $("#sf-name").value = s ? s.name : "";
  $("#sf-role").value = s ? s.role : "Stylist";
  $("#sf-phone").value = s ? s.phone : "";
  $("#sf-email").value = s ? s.email : "";
  $("#sf-status").value = s ? s.status : "active";
  openModal("#staff-modal");
}
function saveStaff() {
  const name = $("#sf-name").value.trim();
  const role = $("#sf-role").value.trim();
  const phone = $("#sf-phone").value.trim();
  const email = $("#sf-email").value.trim();
  const status = $("#sf-status").value;
  if (!name || !role || !phone) { $("#staff-err").textContent = "Name, role and phone are required."; return; }
  if (editingStaffId) {
    Object.assign(db.staff.find(s => s.id === editingStaffId), { name, role, phone, email, status });
  } else {
    db.staff.push({ id: db.nextId.staff++, name, role, phone, email, status, initials: initials(name) });
  }
  saveDB();
  closeModal("#staff-modal");
  renderStaff();
  toast(editingStaffId ? "Staff member updated" : "Staff member added");
}
function toggleStaff(id) {
  const s = db.staff.find(x => x.id === id);
  if (!s) return;
  s.status = s.status === "active" ? "onleave" : "active";
  saveDB();
  renderStaff();
  toast(s.status === "active" ? "Staff member set active" : "Staff member set on leave");
}
function deleteStaff(id) {
  db.staff = db.staff.filter(s => s.id !== id);
  saveDB();
  renderStaff();
  toast("Staff member removed", true);
}

/* ---------------- Service modal ---------------- */
let editingSvcId = null;

function openSvcModal(id) {
  editingSvcId = id || null;
  $("#svc-err").textContent = "";
  const s = id ? db.services.find(x => x.id === id) : null;
  $("#svc-modal-title").textContent = s ? "Edit service" : "New service";
  $("#v-name").value = s ? s.name : "";
  $("#v-cat").value = s ? s.category : "Cut & Style";
  $("#v-dur").value = s ? s.duration : 60;
  $("#v-price").value = s ? s.price : "";
  openModal("#svc-modal");
}
function saveSvc() {
  const name = $("#v-name").value.trim();
  const category = $("#v-cat").value.trim();
  const duration = Number($("#v-dur").value);
  const price = Number($("#v-price").value);
  if (!name || !category || !duration || !price) { $("#svc-err").textContent = "All fields are required."; return; }
  if (editingSvcId) {
    Object.assign(db.services.find(s => s.id === editingSvcId), { name, category, duration, price });
  } else {
    db.services.push({ id: db.nextId.service++, name, category, duration, price });
  }
  saveDB();
  closeModal("#svc-modal");
  renderServices();
  toast(editingSvcId ? "Service updated" : "Service added");
}
function deleteSvc(id) {
  db.services = db.services.filter(s => s.id !== id);
  saveDB();
  renderServices();
  toast("Service deleted", true);
}

/* ---------------- Login / logout ---------------- */
function showLogin() {
  $("#login-overlay").classList.add("open");
  $("#login-err").textContent = "";
}
function doLogin() {
  const email = $("#login-email").value.trim().toLowerCase();
  const pass = $("#login-pass").value;
  const u = db.users.find(x => x.email.toLowerCase() === email && x.pass === pass);
  if (!u) { $("#login-err").textContent = "Invalid email or password."; return; }
  session = { userId: u.id };
  localStorage.setItem(SESSION_KEY, JSON.stringify(session));
  setUserInfo(u);
  $("#login-overlay").classList.remove("open");
  toast("Welcome back, " + u.name.split(" ")[0] + "!");
  render();
}
function setUserInfo(u) {
  $("#user-email").textContent = u ? u.email : "";
  $("#user-role").textContent = u ? (ROLE_LABEL[u.role] || u.role) : "";
  $("#top-avatar").textContent = u ? initials(u.name) : "";
  if (u) renderSidebar(u);
}
function doLogout() {
  session = null;
  localStorage.removeItem(SESSION_KEY);
  setUserInfo(null);
  currentPage = "dashboard";
  showLogin();
  toast("You have been signed out");
}

/* ---------------- Global event handling ---------------- */
function keyFromPager(el) {
  for (const k of Object.keys(PAGER_IDS)) {
    if (el.closest("#" + PAGER_IDS[k])) return k;
  }
  return null;
}

document.addEventListener("click", e => {
  const nav = e.target.closest(".nav-item");
  if (nav) { navigate(nav.dataset.page); return; }

  const kebab = e.target.closest(".kebab-btn");
  if (kebab) { toggleKebab(kebab); return; }

  const act = e.target.closest("[data-act]");
  if (act) {
    const id = Number(act.dataset.id);
    switch (act.dataset.act) {
      case "checkin": case "complete": case "cancel": apptAction(act.dataset.act, id); break;
      case "delete-appt": deleteAppointment(id); break;
      case "edit-client": openClientModal(id); break;
      case "delete-client": deleteClient(id); break;
      case "edit-staff": openStaffModal(id); break;
      case "toggle-staff": toggleStaff(id); break;
      case "delete-staff": deleteStaff(id); break;
      case "edit-svc": openSvcModal(id); break;
      case "delete-svc": deleteSvc(id); break;
    }
    closeAllKebabs();
    return;
  }

  if (!e.target.closest(".kebab-wrap")) closeAllKebabs();

  const pg = e.target.closest("[data-pg]");
  if (pg) {
    const k = keyFromPager(pg);
    if (k) { pagerState[k].page = Number(pg.dataset.pg); render(); }
    return;
  }
});

document.addEventListener("change", e => {
  const sel = e.target;
  if (sel.matches("[data-size]")) {
    const k = keyFromPager(sel);
    if (k) { pagerState[k].size = Number(sel.value); pagerState[k].page = 1; render(); }
    return;
  }
  if (sel.matches("#f-service")) {
    const svc = db.services.find(s => s.name === sel.value.trim());
    if (svc) $("#f-price").value = svc.price;
    return;
  }
  if (sel.id === "appts-status") { filters.appointments.status = sel.value; resetPage("appointments"); render(); return; }
  if (sel.id === "appts-date") { filters.appointments.date = sel.value; resetPage("appointments"); render(); return; }
  if (sel.id === "staff-status") { filters.staff.status = sel.value; resetPage("staff"); render(); return; }
});

document.addEventListener("input", e => {
  const inp = e.target;
  if (inp.matches(".search-input")) {
    const key = inp.dataset.key;
    if (!filters[key]) filters[key] = { q: "" };
    filters[key].q = inp.value;
    resetPage(key);
    render();
    return;
  }
  if (inp.matches("#f-service")) {
    const svc = db.services.find(s => s.name === inp.value.trim());
    if (svc) $("#f-price").value = svc.price;
  }
});

document.addEventListener("click", e => {
  const closer = e.target.closest("[data-close]");
  if (closer) closeModal("#" + closer.dataset.close);
});

/* ---------------- Init ---------------- */
window.addEventListener("load", () => {
  $$("#login-tabs .tab").forEach(t => {
    t.addEventListener("click", () => {
      $$("#login-tabs .tab").forEach(x => x.classList.remove("active"));
      t.classList.add("active");
      if (t.dataset.loginTab === "quick") {
        $("#login-email").value = "admin@salon.com";
        $("#login-pass").value = "admin";
      }
    });
  });

  if (session) {
    setUserInfo(currentUser());
    render();
  } else {
    showLogin();
  }
});
