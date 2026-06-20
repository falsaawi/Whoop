/* TripSplit — vanilla JS, localStorage-backed expense splitter
 * Data model:
 *  state = {
 *    activeTripId: string,
 *    trips: { [id]: { id, name, createdAt, people: [{id, name}], events: [...] } }
 *  }
 *  event = { id, title, city, date, amount, currency, payerId, attendeeIds[], photo (dataURL|null), notes, createdAt }
 */

const STORAGE_KEY = "tripsplit:v1";

const CURRENCY_SYMBOLS = {
  EUR: "€", USD: "$", GBP: "£", JPY: "¥", CHF: "CHF",
  AED: "د.إ", SAR: "﷼", TRY: "₺", THB: "฿",
};

/* ---------- Storage ---------- */

function uid() {
  return Math.random().toString(36).slice(2, 9) + Date.now().toString(36).slice(-4);
}

function loadState() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    console.warn("Bad state, resetting", e);
    return null;
  }
}

function saveState() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function makeStarterTrip() {
  const tripId = uid();
  return {
    activeTripId: tripId,
    trips: {
      [tripId]: {
        id: tripId,
        name: "Europe Roadtrip",
        createdAt: Date.now(),
        people: [],
        events: [],
      },
    },
  };
}

let state = loadState() || makeStarterTrip();

function activeTrip() {
  return state.trips[state.activeTripId];
}

/* ---------- DOM refs ---------- */

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const tripSelect = $("#trip-select");
const eventsList = $("#events-list");
const eventsEmpty = $("#events-empty");
const peopleList = $("#people-list");
const peopleEmpty = $("#people-empty");
const balancesList = $("#balances-list");
const settlementsList = $("#settlements-list");
const balancesEmpty = $("#balances-empty");
const tripTotal = $("#trip-total");

const eventModal = $("#event-modal");
const eventForm = $("#event-form");
const eventModalTitle = $("#event-modal-title");

const personModal = $("#person-modal");
const personForm = $("#person-form");

const photoInput = $("#photo-input");
const photoPreview = $("#photo-preview");
const photoPlaceholder = $("#photo-placeholder");
const removePhotoBtn = $("#remove-photo-btn");

const lightbox = $("#lightbox");
const lightboxImg = $("#lightbox-img");

let editingEventId = null;
let pendingPhotoDataUrl = null;

/* ---------- Helpers ---------- */

function fmtMoney(amount, currency) {
  const sym = CURRENCY_SYMBOLS[currency] || currency;
  const n = Number(amount || 0);
  return `${sym}${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function initialsOf(name) {
  return name
    .trim()
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function personById(id) {
  return activeTrip().people.find((p) => p.id === id);
}

/* ---------- Tabs ---------- */

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
  });
});

/* ---------- Trip bar ---------- */

function renderTripSelect() {
  tripSelect.innerHTML = "";
  Object.values(state.trips)
    .sort((a, b) => b.createdAt - a.createdAt)
    .forEach((t) => {
      const opt = document.createElement("option");
      opt.value = t.id;
      opt.textContent = t.name;
      if (t.id === state.activeTripId) opt.selected = true;
      tripSelect.appendChild(opt);
    });
}

tripSelect.addEventListener("change", () => {
  state.activeTripId = tripSelect.value;
  saveState();
  renderAll();
});

$("#new-trip-btn").addEventListener("click", () => {
  const name = prompt("Name this trip (e.g. 'Asia 2026')");
  if (!name) return;
  const id = uid();
  state.trips[id] = { id, name: name.trim(), createdAt: Date.now(), people: [], events: [] };
  state.activeTripId = id;
  saveState();
  renderAll();
});

$("#rename-trip-btn").addEventListener("click", () => {
  const t = activeTrip();
  const name = prompt("Rename trip", t.name);
  if (!name) return;
  t.name = name.trim();
  saveState();
  renderAll();
});

$("#delete-trip-btn").addEventListener("click", () => {
  const ids = Object.keys(state.trips);
  if (ids.length === 1) {
    alert("Can't delete the only trip. Create another one first.");
    return;
  }
  const t = activeTrip();
  if (!confirm(`Delete trip "${t.name}" and all its events? This can't be undone.`)) return;
  delete state.trips[t.id];
  state.activeTripId = Object.keys(state.trips)[0];
  saveState();
  renderAll();
});

/* ---------- People ---------- */

$("#add-person-btn").addEventListener("click", () => openPersonModal());

function openPersonModal() {
  personModal.hidden = false;
  personForm.reset();
  setTimeout(() => personForm.elements.name.focus(), 50);
}

personForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const name = personForm.elements.name.value.trim();
  if (!name) return;
  activeTrip().people.push({ id: uid(), name });
  saveState();
  closeModals();
  renderAll();
});

function renderPeople() {
  const people = activeTrip().people;
  peopleEmpty.hidden = people.length > 0;
  peopleList.innerHTML = "";
  people.forEach((p) => {
    const li = document.createElement("li");
    li.innerHTML = `
      <div style="display:flex; align-items:center; gap:10px; min-width:0;">
        <div class="avatar">${initialsOf(p.name)}</div>
        <div class="person-name" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</div>
      </div>
      <button class="btn-ghost danger" data-remove="${p.id}" aria-label="Remove ${escapeHtml(p.name)}">✕</button>
    `;
    peopleList.appendChild(li);
  });
  peopleList.querySelectorAll("[data-remove]").forEach((btn) => {
    btn.addEventListener("click", () => removePerson(btn.dataset.remove));
  });
}

function removePerson(personId) {
  const t = activeTrip();
  const involved = t.events.some(
    (e) => e.payerId === personId || e.attendeeIds.includes(personId)
  );
  if (involved) {
    if (!confirm("This person is in some events. Remove them anyway? Existing events keep their record.")) return;
  }
  t.people = t.people.filter((p) => p.id !== personId);
  saveState();
  renderAll();
}

/* ---------- Events ---------- */

$("#add-event-btn").addEventListener("click", () => openEventModal());

function openEventModal(eventId) {
  if (activeTrip().people.length === 0) {
    alert("Add at least one traveler first (Travelers tab).");
    return;
  }
  editingEventId = eventId || null;
  eventModalTitle.textContent = eventId ? "Edit event" : "Add event";
  eventForm.reset();
  pendingPhotoDataUrl = null;
  photoPreview.hidden = true;
  photoPreview.src = "";
  photoPlaceholder.hidden = false;
  removePhotoBtn.hidden = true;

  // Default date today
  eventForm.elements.date.value = new Date().toISOString().slice(0, 10);

  // Populate payer select
  const payerSel = eventForm.elements.payer;
  payerSel.innerHTML = `<option value="">— Select payer —</option>`;
  activeTrip().people.forEach((p) => {
    const opt = document.createElement("option");
    opt.value = p.id;
    opt.textContent = p.name;
    payerSel.appendChild(opt);
  });

  // Populate attendees
  const checks = $("#attendees-checks");
  checks.innerHTML = "";
  activeTrip().people.forEach((p) => {
    const row = document.createElement("label");
    row.className = "check-row";
    row.innerHTML = `<input type="checkbox" value="${p.id}" /> <span>${escapeHtml(p.name)}</span>`;
    const input = row.querySelector("input");
    input.addEventListener("change", () => row.classList.toggle("active", input.checked));
    checks.appendChild(row);
  });

  if (eventId) {
    const ev = activeTrip().events.find((e) => e.id === eventId);
    if (ev) {
      eventForm.elements.title.value = ev.title;
      eventForm.elements.city.value = ev.city;
      eventForm.elements.date.value = ev.date;
      eventForm.elements.amount.value = ev.amount;
      eventForm.elements.currency.value = ev.currency;
      eventForm.elements.payer.value = ev.payerId;
      eventForm.elements.notes.value = ev.notes || "";
      checks.querySelectorAll("input[type=checkbox]").forEach((cb) => {
        if (ev.attendeeIds.includes(cb.value)) {
          cb.checked = true;
          cb.closest(".check-row").classList.add("active");
        }
      });
      if (ev.photo) {
        pendingPhotoDataUrl = ev.photo;
        photoPreview.src = ev.photo;
        photoPreview.hidden = false;
        photoPlaceholder.hidden = true;
        removePhotoBtn.hidden = false;
      }
    }
  }

  eventModal.hidden = false;
}

$("#select-all-btn").addEventListener("click", () => {
  $$("#attendees-checks input[type=checkbox]").forEach((cb) => {
    cb.checked = true;
    cb.closest(".check-row").classList.add("active");
  });
});
$("#select-none-btn").addEventListener("click", () => {
  $$("#attendees-checks input[type=checkbox]").forEach((cb) => {
    cb.checked = false;
    cb.closest(".check-row").classList.remove("active");
  });
});

photoInput.addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  if (!file) return;
  const dataUrl = await fileToCompressedDataUrl(file);
  pendingPhotoDataUrl = dataUrl;
  photoPreview.src = dataUrl;
  photoPreview.hidden = false;
  photoPlaceholder.hidden = true;
  removePhotoBtn.hidden = false;
});

removePhotoBtn.addEventListener("click", () => {
  pendingPhotoDataUrl = null;
  photoInput.value = "";
  photoPreview.hidden = true;
  photoPreview.src = "";
  photoPlaceholder.hidden = false;
  removePhotoBtn.hidden = true;
});

function fileToCompressedDataUrl(file, maxDim = 1280, quality = 0.82) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = reject;
    reader.onload = () => {
      const img = new Image();
      img.onload = () => {
        let { width, height } = img;
        const scale = Math.min(1, maxDim / Math.max(width, height));
        width = Math.round(width * scale);
        height = Math.round(height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.onerror = reject;
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

eventForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const fd = new FormData(eventForm);
  const attendeeIds = Array.from(
    $$("#attendees-checks input[type=checkbox]:checked")
  ).map((cb) => cb.value);
  if (attendeeIds.length === 0) {
    alert("Pick at least one attendee.");
    return;
  }
  const payerId = fd.get("payer");
  if (!attendeeIds.includes(payerId)) {
    if (!confirm("The payer isn't in the attendees list. Continue? (They won't share the cost.)")) return;
  }
  const data = {
    title: fd.get("title").trim(),
    city: fd.get("city").trim(),
    date: fd.get("date"),
    amount: parseFloat(fd.get("amount")),
    currency: fd.get("currency"),
    payerId,
    attendeeIds,
    photo: pendingPhotoDataUrl || null,
    notes: (fd.get("notes") || "").trim(),
  };
  const t = activeTrip();
  if (editingEventId) {
    const ev = t.events.find((e) => e.id === editingEventId);
    Object.assign(ev, data);
  } else {
    t.events.push({ id: uid(), createdAt: Date.now(), ...data });
  }
  saveState();
  closeModals();
  renderAll();
});

function renderEvents() {
  const events = [...activeTrip().events].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  eventsEmpty.hidden = events.length > 0;
  eventsList.innerHTML = "";
  events.forEach((ev) => {
    const card = document.createElement("article");
    card.className = "event-card";
    const share = ev.amount / Math.max(ev.attendeeIds.length, 1);
    const payer = personById(ev.payerId);
    const thumbStyle = ev.photo ? `background-image: url('${ev.photo}');` : "";

    card.innerHTML = `
      <div class="event-thumb" style="${thumbStyle}" data-photo="${ev.id}">
        ${ev.photo ? "" : "🧾"}
      </div>
      <div class="event-body">
        <div class="event-title">
          ${escapeHtml(ev.title)}
        </div>
        <div class="event-meta">
          <span>📍 ${escapeHtml(ev.city)}</span>
          <span class="dot">•</span>
          <span>${fmtDate(ev.date)}</span>
        </div>
        <div class="event-money">
          <span class="total">${fmtMoney(ev.amount, ev.currency)}</span>
          <span class="share">${fmtMoney(share, ev.currency)} × ${ev.attendeeIds.length} ${ev.attendeeIds.length === 1 ? "person" : "people"}</span>
        </div>
        <div class="event-attendees">
          <span class="chip payer">💳 ${payer ? escapeHtml(payer.name) : "Unknown"}</span>
          ${ev.attendeeIds.map((id) => {
            const p = personById(id);
            return `<span class="chip">${p ? escapeHtml(p.name) : "?"}</span>`;
          }).join("")}
          ${ev.notes ? `<span class="chip notes" title="${escapeHtml(ev.notes)}">📝 ${escapeHtml(ev.notes.length > 30 ? ev.notes.slice(0,30)+'…' : ev.notes)}</span>` : ""}
        </div>
      </div>
      <div class="event-actions">
        <button class="btn-ghost" data-edit="${ev.id}" title="Edit">✏️</button>
        <button class="btn-ghost danger" data-delete="${ev.id}" title="Delete">🗑️</button>
      </div>
    `;
    eventsList.appendChild(card);
  });
  eventsList.querySelectorAll("[data-edit]").forEach((b) =>
    b.addEventListener("click", () => openEventModal(b.dataset.edit))
  );
  eventsList.querySelectorAll("[data-delete]").forEach((b) =>
    b.addEventListener("click", () => deleteEvent(b.dataset.delete))
  );
  eventsList.querySelectorAll("[data-photo]").forEach((el) =>
    el.addEventListener("click", () => {
      const ev = activeTrip().events.find((x) => x.id === el.dataset.photo);
      if (ev && ev.photo) showLightbox(ev.photo);
    })
  );
}

function deleteEvent(id) {
  if (!confirm("Delete this event? Splits will recalculate.")) return;
  const t = activeTrip();
  t.events = t.events.filter((e) => e.id !== id);
  saveState();
  renderAll();
}

/* ---------- Balances ---------- */

function renderBalances() {
  const t = activeTrip();
  const balancesByCurrency = {};

  t.events.forEach((ev) => {
    const cur = ev.currency;
    if (!balancesByCurrency[cur]) balancesByCurrency[cur] = {};
    const share = ev.amount / Math.max(ev.attendeeIds.length, 1);
    balancesByCurrency[cur][ev.payerId] = (balancesByCurrency[cur][ev.payerId] || 0) + ev.amount;
    ev.attendeeIds.forEach((id) => {
      balancesByCurrency[cur][id] = (balancesByCurrency[cur][id] || 0) - share;
    });
  });

  const currencies = Object.keys(balancesByCurrency);
  const hasData = currencies.length > 0 && t.events.length > 0;
  balancesEmpty.hidden = hasData;
  balancesList.innerHTML = "";
  settlementsList.innerHTML = "";

  if (!hasData) {
    tripTotal.textContent = "";
    return;
  }

  // Trip total summary
  const totals = currencies.map((cur) => {
    const total = t.events
      .filter((e) => e.currency === cur)
      .reduce((s, e) => s + e.amount, 0);
    return fmtMoney(total, cur);
  });
  tripTotal.textContent = `Total: ${totals.join(" + ")}`;

  currencies.forEach((cur) => {
    const header = document.createElement("h3");
    header.className = "section-title";
    header.style.marginTop = "8px";
    header.textContent = `${cur} balances`;
    balancesList.appendChild(header);

    const entries = Object.entries(balancesByCurrency[cur])
      .map(([id, val]) => ({ id, val: Math.round(val * 100) / 100 }))
      .sort((a, b) => b.val - a.val);

    entries.forEach(({ id, val }) => {
      const p = personById(id);
      const cls = Math.abs(val) < 0.01 ? "zero" : val > 0 ? "pos" : "neg";
      const li = document.createElement("li");
      li.className = "balance-row";
      const sign = val > 0 ? "+" : "";
      li.innerHTML = `
        <div class="balance-name">
          <div class="avatar">${p ? initialsOf(p.name) : "?"}</div>
          <div>${p ? escapeHtml(p.name) : "Unknown"}</div>
        </div>
        <div class="balance-amount ${cls}">${sign}${fmtMoney(val, cur)}</div>
      `;
      balancesList.appendChild(li);
    });

    // Settlements (greedy min-transfer)
    const settlements = computeSettlements(balancesByCurrency[cur]);
    if (settlements.length > 0) {
      const sHeader = document.createElement("h3");
      sHeader.className = "section-title";
      sHeader.textContent = `${cur} settlements`;
      settlementsList.appendChild(sHeader);
      settlements.forEach((s) => {
        const from = personById(s.from);
        const to = personById(s.to);
        const row = document.createElement("li");
        row.className = "settlement-row";
        row.innerHTML = `
          <span><strong>${from ? escapeHtml(from.name) : "?"}</strong> <span class="arrow">→</span> <strong>${to ? escapeHtml(to.name) : "?"}</strong></span>
          <span class="balance-amount pos">${fmtMoney(s.amount, cur)}</span>
        `;
        settlementsList.appendChild(row);
      });
    }
  });
}

function computeSettlements(balances) {
  // balances: { personId: net amount (positive = owed money) }
  const debtors = [];
  const creditors = [];
  Object.entries(balances).forEach(([id, val]) => {
    const v = Math.round(val * 100) / 100;
    if (v < -0.005) debtors.push({ id, val: -v });
    else if (v > 0.005) creditors.push({ id, val: v });
  });
  debtors.sort((a, b) => b.val - a.val);
  creditors.sort((a, b) => b.val - a.val);

  const out = [];
  let i = 0, j = 0;
  while (i < debtors.length && j < creditors.length) {
    const pay = Math.min(debtors[i].val, creditors[j].val);
    if (pay > 0.005) {
      out.push({ from: debtors[i].id, to: creditors[j].id, amount: Math.round(pay * 100) / 100 });
    }
    debtors[i].val -= pay;
    creditors[j].val -= pay;
    if (debtors[i].val < 0.005) i++;
    if (creditors[j].val < 0.005) j++;
  }
  return out;
}

/* ---------- Modal helpers ---------- */

function closeModals() {
  eventModal.hidden = true;
  personModal.hidden = true;
}
$$("[data-close]").forEach((b) => b.addEventListener("click", closeModals));
[eventModal, personModal].forEach((m) =>
  m.addEventListener("click", (e) => {
    if (e.target === m) closeModals();
  })
);

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    closeModals();
    hideLightbox();
  }
});

function showLightbox(src) {
  lightboxImg.src = src;
  lightbox.hidden = false;
}
function hideLightbox() {
  lightbox.hidden = true;
  lightboxImg.src = "";
}
$("#lightbox-close").addEventListener("click", hideLightbox);
lightbox.addEventListener("click", (e) => {
  if (e.target === lightbox) hideLightbox();
});

/* ---------- Misc ---------- */

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderAll() {
  renderTripSelect();
  renderPeople();
  renderEvents();
  renderBalances();
}

/* ---------- Demo seed (first run only) ---------- */

function maybeSeedDemo() {
  const t = activeTrip();
  if (t.people.length > 0 || t.events.length > 0) return;
  const names = ["Sara", "Omar", "Lina", "Ravi"];
  t.people = names.map((n) => ({ id: uid(), name: n }));
  const [sara, omar, lina, ravi] = t.people;
  t.events = [
    {
      id: uid(),
      title: "Welcome dinner",
      city: "Rome",
      date: new Date(Date.now() - 4 * 86400000).toISOString().slice(0, 10),
      amount: 184.50,
      currency: "EUR",
      payerId: sara.id,
      attendeeIds: [sara.id, omar.id, lina.id, ravi.id],
      photo: null,
      notes: "Tip included",
      createdAt: Date.now() - 4 * 86400000,
    },
    {
      id: uid(),
      title: "Pizza al taglio",
      city: "Florence",
      date: new Date(Date.now() - 2 * 86400000).toISOString().slice(0, 10),
      amount: 42.00,
      currency: "EUR",
      payerId: omar.id,
      attendeeIds: [sara.id, omar.id, ravi.id],
      photo: null,
      notes: "",
      createdAt: Date.now() - 2 * 86400000,
    },
    {
      id: uid(),
      title: "Tapas night",
      city: "Barcelona",
      date: new Date(Date.now() - 1 * 86400000).toISOString().slice(0, 10),
      amount: 96.00,
      currency: "EUR",
      payerId: lina.id,
      attendeeIds: [omar.id, lina.id, ravi.id],
      photo: null,
      notes: "Sara wasn't here",
      createdAt: Date.now() - 1 * 86400000,
    },
  ];
  saveState();
}

maybeSeedDemo();
renderAll();
