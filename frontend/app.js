"use strict";

// Same-origin API: the backend serves this page at /ui/.
const $ = (sel) => document.querySelector(sel);
const store = sessionStorage;
const state = { mode: "login", page: 1, limit: 10, rooms: [], current: null };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (cents) => `$${(cents / 100).toFixed(2)}`;
const utc = (iso) => iso.replace("T", " ").replace(/(:\d\d)(\.\d+)?(Z|\+00:00)$/, "$1").slice(0, 16);
const today = () => new Date().toISOString().slice(0, 10);

function toast(msg, isError = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast" + (isError ? " error" : "");
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 4000);
}

function errorText(data, status) {
  if (!data) return `Request failed (${status})`;
  if (Array.isArray(data.detail)) return data.detail.map((d) => `${d.loc.slice(-1)[0]}: ${d.msg}`).join("; ");
  return data.code ? `${data.detail} (${data.code})` : data.detail || `Request failed (${status})`;
}

function claims() {
  const token = store.getItem("access");
  if (!token) return null;
  try {
    return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

async function refreshTokens() {
  const refresh_token = store.getItem("refresh");
  if (!refresh_token) return false;
  const res = await fetch("/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  store.setItem("access", data.access_token);
  store.setItem("refresh", data.refresh_token);
  return true;
}

// Calls the API; on 401 rotates tokens once and retries, else signs out.
async function api(path, { method = "GET", body, raw = false } = {}, retry = true) {
  const headers = {};
  const token = store.getItem("access");
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (res.status === 401 && token && retry) {
    if (await refreshTokens()) return api(path, { method, body, raw }, false);
    signOut();
    throw new Error("Session expired. Please log in again.");
  }
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(errorText(data, res.status));
  }
  return raw ? res : res.json();
}

// Wraps a submit/click handler: disables the button and reports errors.
function action(fn) {
  return async (e) => {
    e.preventDefault();
    const btn = e.submitter || e.currentTarget;
    if (btn) btn.disabled = true;
    try {
      await fn(e);
    } catch (err) {
      toast(err.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  };
}

/* ---------- auth ---------- */

function setMode(mode) {
  state.mode = mode;
  $("#tab-login").setAttribute("aria-selected", mode === "login");
  $("#tab-register").setAttribute("aria-selected", mode === "register");
  $("#auth-form").setAttribute("aria-labelledby", `tab-${mode}`);
  $("#auth-submit").textContent = mode === "login" ? "Log in" : "Create account";
  $("#auth-form [name=password]").autocomplete = mode === "login" ? "current-password" : "new-password";
}

async function login(creds) {
  const data = await api("/auth/login", { method: "POST", body: creds });
  store.setItem("access", data.access_token);
  store.setItem("refresh", data.refresh_token);
  store.setItem("who", `${creds.username}@${creds.org_name}`);
}

function signOut() {
  ["access", "refresh", "who"].forEach((k) => store.removeItem(k));
  render();
}

/* ---------- rooms ---------- */

async function loadRooms() {
  state.rooms = await api("/rooms");
  const list = $("#rooms");
  $("#rooms-empty").hidden = state.rooms.length > 0;
  list.innerHTML = state.rooms
    .map(
      (r) => `<li>
        <div><strong>${esc(r.name)}</strong>
          <div class="meta">${r.capacity} seats · ${money(r.hourly_rate_cents)}/h</div></div>
        <div class="stats" id="stats-${r.id}" aria-label="Room statistics">…</div>
      </li>`
    )
    .join("");
  const select = $("#book-form [name=room_id]");
  const prev = select.value;
  select.innerHTML = state.rooms.map((r) => `<option value="${r.id}">${esc(r.name)}</option>`).join("");
  if (state.rooms.some((r) => String(r.id) === prev)) select.value = prev;

  await Promise.all(
    state.rooms.map(async (r) => {
      const s = await api(`/rooms/${r.id}/stats`).catch(() => null);
      const el = $(`#stats-${r.id}`);
      if (el) el.innerHTML = s ? `${s.total_confirmed_bookings} booked<br>${money(s.total_revenue_cents)}` : "—";
    })
  );
}

const roomName = (id) => (state.rooms.find((r) => r.id === id) || { name: `#${id}` }).name;

/* ---------- bookings ---------- */

async function loadBookings() {
  const data = await api(`/bookings?page=${state.page}&limit=${state.limit}`);
  const pages = Math.max(1, Math.ceil(data.total / data.limit));
  if (state.page > pages) {
    state.page = pages;
    return loadBookings();
  }
  $("#bookings-total").textContent = `${data.total} total`;
  $("#bookings-empty").hidden = data.total > 0;
  $("#page-label").textContent = `${data.page} / ${pages}`;
  $("#prev").disabled = data.page <= 1;
  $("#next").disabled = data.page >= pages;
  $("#bookings").innerHTML = data.items
    .map(
      (b) => `<tr>
        <td class="mono">${esc(b.reference_code)}</td>
        <td>${esc(roomName(b.room_id))}</td>
        <td class="mono">${esc(utc(b.start_time))}</td>
        <td class="mono">${esc(utc(b.end_time))}</td>
        <td class="num">${money(b.price_cents)}</td>
        <td><span class="badge ${esc(b.status)}">${esc(b.status)}</span></td>
        <td><button class="btn ghost small" type="button" data-id="${b.id}">Details</button></td>
      </tr>`
    )
    .join("");
}

async function showBooking(id) {
  const b = await api(`/bookings/${id}`);
  state.current = b;
  const refunds = b.refunds.length
    ? b.refunds.map((r) => `${money(r.amount_cents)} · ${esc(r.status)} · ${esc(utc(r.processed_at))}`).join("<br>")
    : "—";
  const rows = [
    ["Reference", esc(b.reference_code)],
    ["Room", esc(roomName(b.room_id))],
    ["Start (UTC)", esc(utc(b.start_time))],
    ["End (UTC)", esc(utc(b.end_time))],
    ["Price", money(b.price_cents)],
    ["Status", esc(b.status)],
    ["Created", esc(utc(b.created_at))],
    ["Refunds", refunds],
  ];
  $("#detail-body").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  $("#cancel-booking").hidden = b.status !== "confirmed";
  $("#detail").showModal();
}

function nextHourLocal() {
  const d = new Date();
  d.setMinutes(0, 0, 0);
  d.setHours(d.getHours() + 1);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`;
}

/* ---------- render ---------- */

async function render() {
  const c = claims();
  $("#auth-view").hidden = !!c;
  $("#app-view").hidden = !c;
  $("#session").hidden = !c;
  if (!c) return;
  $("#who").textContent = `${store.getItem("who") || "user " + c.sub} · ${c.role}`;
  $("#admin").hidden = c.role !== "admin";
  try {
    await loadRooms();
    await loadBookings();
  } catch (err) {
    toast(err.message, true);
  }
}

/* ---------- wiring ---------- */

$("#tab-login").addEventListener("click", () => setMode("login"));
$("#tab-register").addEventListener("click", () => setMode("register"));

$("#auth-form").addEventListener(
  "submit",
  action(async (e) => {
    const creds = Object.fromEntries(new FormData(e.target));
    if (state.mode === "register") {
      const u = await api("/auth/register", { method: "POST", body: creds });
      toast(`Registered as ${u.role} of ${creds.org_name}.`);
    }
    await login(creds);
    e.target.reset();
    await render();
  })
);

$("#logout").addEventListener(
  "click",
  action(async () => {
    await api("/auth/logout", { method: "POST" }, false).catch(() => {});
    signOut();
  })
);

$("#rooms-refresh").addEventListener("click", action(loadRooms));

$("#book-form").addEventListener(
  "submit",
  action(async (e) => {
    const f = new FormData(e.target);
    const start = new Date(f.get("start"));
    if (isNaN(start)) throw new Error("Pick a start time.");
    const end = new Date(start.getTime() + Number(f.get("hours")) * 3600e3);
    const b = await api("/bookings", {
      method: "POST",
      body: { room_id: Number(f.get("room_id")), start_time: start.toISOString(), end_time: end.toISOString() },
    });
    toast(`Booked ${b.reference_code} — ${money(b.price_cents)}`);
    await Promise.all([loadRooms(), loadBookings()]);
  })
);

$("#avail-form").addEventListener(
  "submit",
  action(async (e) => {
    const roomId = $("#book-form [name=room_id]").value;
    if (!roomId) throw new Error("Create or select a room first.");
    const date = new FormData(e.target).get("date");
    const a = await api(`/rooms/${roomId}/availability?date=${encodeURIComponent(date)}`);
    $("#avail").innerHTML = a.busy.length
      ? a.busy.map((i) => `<li>busy ${esc(utc(i.start_time).slice(11))}–${esc(utc(i.end_time).slice(11))} UTC</li>`).join("")
      : `<li class="free">${esc(roomName(Number(roomId)))} is free all day</li>`;
  })
);

$("#bookings").addEventListener("click", (e) => {
  const id = e.target.dataset.id;
  if (id) showBooking(id).catch((err) => toast(err.message, true));
});
$("#prev").addEventListener("click", () => { state.page--; loadBookings().catch((err) => toast(err.message, true)); });
$("#next").addEventListener("click", () => { state.page++; loadBookings().catch((err) => toast(err.message, true)); });

$("#cancel-booking").addEventListener(
  "click",
  action(async () => {
    const b = state.current;
    if (!confirm(`Cancel ${b.reference_code}? Refund: 100% with ≥48 h notice, 50% with ≥24 h, otherwise none.`)) return;
    const r = await api(`/bookings/${b.id}/cancel`, { method: "POST" });
    $("#detail").close();
    toast(`Cancelled. Refund ${r.refund_percent}% = ${money(r.refund_amount_cents)}`);
    await Promise.all([loadRooms(), loadBookings()]);
  })
);

$("#room-form").addEventListener(
  "submit",
  action(async (e) => {
    const f = new FormData(e.target);
    const r = await api("/rooms", {
      method: "POST",
      body: { name: f.get("name"), capacity: Number(f.get("capacity")), hourly_rate_cents: Math.round(Number(f.get("rate")) * 100) },
    });
    e.target.reset();
    toast(`Room “${r.name}” created.`);
    await loadRooms();
  })
);

$("#report-form").addEventListener(
  "submit",
  action(async (e) => {
    const f = new FormData(e.target);
    const q = new URLSearchParams({ from: f.get("from"), to: f.get("to") });
    const rep = await api(`/admin/usage-report?${q}`);
    $("#report").innerHTML = rep.rooms
      .map((r) => `<tr><td>${esc(r.room_name)}</td><td class="num">${r.confirmed_bookings}</td><td class="num">${money(r.revenue_cents)}</td></tr>`)
      .join("") || `<tr><td colspan="3" class="muted">No rooms.</td></tr>`;
  })
);

$("#export-form").addEventListener(
  "submit",
  action(async (e) => {
    const all = new FormData(e.target).has("include_all");
    const res = await api(`/admin/export?include_all=${all}`, { raw: true });
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `bookings-${today()}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  })
);

$("#book-form [name=start]").value = nextHourLocal();
$("#avail-form [name=date]").value = today();
$("#report-form [name=from]").value = today();
$("#report-form [name=to]").value = new Date(Date.now() + 6 * 864e5).toISOString().slice(0, 10);

render();
