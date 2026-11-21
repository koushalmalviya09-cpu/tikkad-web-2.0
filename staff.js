let csrfToken = '';
let bookings = [];
let orders = [];

const loginPanel = document.querySelector('#login-panel');
const dashboardPanel = document.querySelector('#dashboard-panel');
const loginForm = document.querySelector('#staff-login-form');
const loginError = document.querySelector('#login-error');
const dashboardMessage = document.querySelector('#dashboard-message');

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || 'The request could not be completed.');
    error.status = response.status;
    throw error;
  }
  return data;
}

function showDashboard() {
  loginPanel.hidden = true;
  dashboardPanel.hidden = false;
}

function showLogin() {
  dashboardPanel.hidden = true;
  loginPanel.hidden = false;
  csrfToken = '';
}

async function loadBookings() {
  const data = await requestJson('/api/staff/bookings');
  bookings = data.bookings;
  renderBookings();
}

async function loadOrders() {
  const data = await requestJson('/api/staff/orders');
  orders = data.orders;
  renderOrders();
}

async function loadDashboardData() {
  await Promise.all([loadBookings(), loadOrders()]);
}

async function reportMutationError(error, reload = loadDashboardData) {
  if (error.status === 401) {
    showLogin();
    loginError.textContent = 'Your staff session expired. Please sign in again.';
    return;
  }
  dashboardMessage.textContent = error.message;
  try {
    await reload();
  } catch (refreshError) {
    if (refreshError.status === 401) showLogin();
    dashboardMessage.textContent = `${error.message} ${refreshError.message}`;
  }
}

loginForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  loginError.textContent = '';
  const submitButton = loginForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;

  try {
    const code = document.querySelector('#staff-code').value;
    const data = await requestJson('/api/staff/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code })
    });
    csrfToken = data.csrfToken;
    await loadDashboardData();
    showDashboard();
  } catch (error) {
    showLogin();
    loginError.textContent = error.message;
  } finally {
    submitButton.disabled = false;
  }
});

function escapeHtml(value) {
  const element = document.createElement('span');
  element.textContent = value;
  return element.innerHTML;
}

function formatDateTime(booking) {
  const date = new Date(`${booking.booking_date}T${booking.booking_time}:00`);
  if (Number.isNaN(date.getTime())) return `${booking.booking_date} · ${booking.booking_time}`;
  return `${date.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })} · ${booking.booking_time}`;
}

function formatReceived(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
}

function renderBookings() {
  const search = document.querySelector('#booking-search').value.trim().toLowerCase();
  const status = document.querySelector('#status-filter').value;
  const filtered = bookings.filter((booking) => {
    const matchesSearch = !search ||
      booking.name.toLowerCase().includes(search) ||
      booking.phone.toLowerCase().includes(search);
    return matchesSearch && (status === 'all' || booking.status === status);
  });

  document.querySelector('#total-count').textContent = bookings.length;
  document.querySelector('#new-count').textContent = bookings.filter((booking) => booking.status === 'new').length;
  document.querySelector('#confirmed-count').textContent = bookings.filter((booking) => booking.status === 'confirmed').length;

  const now = new Date();
  const today = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0')
  ].join('-');
  document.querySelector('#today-count').textContent = bookings
    .filter((booking) => booking.booking_date === today && booking.status !== 'cancelled')
    .reduce((total, booking) => total + booking.guests, 0);

  const rows = document.querySelector('#booking-rows');
  rows.innerHTML = filtered.map((booking) => {
    const phoneLink = booking.phone.replace(/[^\d+]/g, '');
    return `
      <tr>
        <td><strong>${escapeHtml(booking.name)}</strong></td>
        <td><a href="tel:${escapeHtml(phoneLink)}">${escapeHtml(booking.phone)}</a></td>
        <td>${escapeHtml(formatDateTime(booking))}</td>
        <td>${booking.guests}</td>
        <td>
          <select class="status-select" data-id="${booking.id}" aria-label="Booking status">
            <option value="new" ${booking.status === 'new' ? 'selected' : ''}>New</option>
            <option value="confirmed" ${booking.status === 'confirmed' ? 'selected' : ''}>Confirmed</option>
            <option value="cancelled" ${booking.status === 'cancelled' ? 'selected' : ''}>Cancelled</option>
          </select>
        </td>
        <td>${escapeHtml(formatReceived(booking.created_at))}</td>
        <td><button class="delete-booking" data-id="${booking.id}" type="button" aria-label="Delete booking">Delete</button></td>
      </tr>
    `;
  }).join('');

  document.querySelector('#empty-state').hidden = filtered.length !== 0;
}

function formatCurrency(paise) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(paise / 100);
}

function renderOrders() {
  const search = document.querySelector('#order-search').value.trim().toLowerCase();
  const status = document.querySelector('#order-status-filter').value;
  const filtered = orders.filter((order) => {
    const matchesSearch = !search ||
      order.customer_name.toLowerCase().includes(search) ||
      order.phone.toLowerCase().includes(search) ||
      String(order.id).includes(search);
    return matchesSearch && (status === 'all' || order.order_status === status);
  });

  document.querySelector('#order-total-count').textContent = orders.length;
  document.querySelector('#order-pending-count').textContent = orders.filter((order) => order.payment_status === 'pending').length;
  document.querySelector('#order-new-count').textContent = orders.filter((order) => order.payment_status === 'paid' && order.order_status === 'new').length;
  document.querySelector('#order-preparing-count').textContent = orders.filter((order) => order.order_status === 'preparing').length;

  const rows = document.querySelector('#order-rows');
  rows.innerHTML = filtered.map((order) => {
    const phoneLink = order.phone.replace(/[^\d+]/g, '');
    const items = order.items.map((item) =>
      `<li>${escapeHtml(item.item_name)} × ${item.quantity}</li>`
    ).join('');
    const fulfillment = order.fulfillment_type === 'dine_in' ? 'Dine-in' : 'Pickup';
    const table = order.fulfillment_type === 'dine_in' && order.table_number
      ? `<br>Table ${escapeHtml(order.table_number)}`
      : '';
    const notes = order.notes ? `<br><small>${escapeHtml(order.notes)}</small>` : '';
    const statuses = ['new', 'accepted', 'preparing', 'ready', 'completed', 'cancelled'];
    const statusOptions = statuses.map((value) =>
      `<option value="${value}" ${order.order_status === value ? 'selected' : ''}>${value[0].toUpperCase()}${value.slice(1)}</option>`
    ).join('');
    const isPaid = order.payment_status === 'paid';
    return `
      <tr>
        <td><strong>#${order.id}</strong></td>
        <td><strong>${escapeHtml(order.customer_name)}</strong>${notes}</td>
        <td><a href="tel:${escapeHtml(phoneLink)}">${escapeHtml(order.phone)}</a></td>
        <td class="order-fulfillment">${fulfillment}${table}</td>
        <td><ul class="order-item-list">${items}</ul></td>
        <td>${formatCurrency(order.total_paise)}</td>
        <td><span class="payment-badge ${escapeHtml(order.payment_status)}">${escapeHtml(order.payment_status)}</span></td>
        <td>
          ${isPaid
            ? `<select class="order-status-select status-select" data-id="${order.id}" aria-label="Order status">${statusOptions}</select>`
            : `<span class="payment-badge pending">${escapeHtml(order.order_status.replace('_', ' '))}</span>`}
        </td>
        <td>${escapeHtml(formatReceived(order.created_at))}</td>
      </tr>
    `;
  }).join('');
  document.querySelector('#orders-empty-state').hidden = filtered.length !== 0;
}

document.querySelectorAll('[data-view]').forEach((button) => {
  button.addEventListener('click', () => {
    const selectedView = button.dataset.view;
    document.querySelector('#dashboard-title').textContent = selectedView === 'orders-view' ? 'Orders' : 'Bookings';
    document.querySelectorAll('.staff-view').forEach((view) => {
      view.hidden = view.id !== selectedView;
    });
    document.querySelectorAll('[data-view]').forEach((tab) => {
      const active = tab.dataset.view === selectedView;
      tab.classList.toggle('active', active);
      if (tab.hasAttribute('aria-pressed')) tab.setAttribute('aria-pressed', String(active));
    });
  });
});

async function refreshBookings() {
  dashboardMessage.textContent = '';
  try {
    await loadDashboardData();
  } catch (error) {
    if (error.status === 401) {
      showLogin();
      loginError.textContent = 'Your staff session expired. Please sign in again.';
      return;
    }
    dashboardMessage.textContent = error.message;
  }
}

document.querySelector('#booking-search').addEventListener('input', renderBookings);
document.querySelector('#status-filter').addEventListener('change', renderBookings);
document.querySelector('#order-search').addEventListener('input', renderOrders);
document.querySelector('#order-status-filter').addEventListener('change', renderOrders);
document.querySelector('#refresh-button').addEventListener('click', refreshBookings);

document.querySelector('#booking-rows').addEventListener('change', async (event) => {
  if (!event.target.matches('.status-select')) return;
  dashboardMessage.textContent = '';
  try {
    await requestJson(`/api/staff/bookings/${event.target.dataset.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ status: event.target.value })
    });
    await loadBookings();
  } catch (error) {
    await reportMutationError(error, loadBookings);
  }
});

document.querySelector('#booking-rows').addEventListener('click', async (event) => {
  if (!event.target.matches('.delete-booking')) return;
  if (!confirm('Delete this booking permanently?')) return;
  dashboardMessage.textContent = '';
  try {
    await requestJson(`/api/staff/bookings/${event.target.dataset.id}`, {
      method: 'DELETE',
      headers: { 'X-CSRF-Token': csrfToken }
    });
    await loadBookings();
  } catch (error) {
    await reportMutationError(error, loadBookings);
  }
});

document.querySelector('#order-rows').addEventListener('change', async (event) => {
  if (!event.target.matches('.order-status-select')) return;
  dashboardMessage.textContent = '';
  try {
    await requestJson(`/api/staff/orders/${event.target.dataset.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({ status: event.target.value })
    });
    await loadOrders();
  } catch (error) {
    await reportMutationError(error, loadOrders);
  }
});

document.querySelector('#logout-button').addEventListener('click', async () => {
  dashboardMessage.textContent = '';
  try {
    await requestJson('/api/staff/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': csrfToken }
    });
    showLogin();
    loginForm.reset();
    loginError.textContent = '';
  } catch (error) {
    dashboardMessage.textContent = error.message;
  }
});

async function restoreStaffSession() {
  try {
    const data = await requestJson('/api/staff/session');
    csrfToken = data.csrfToken;
    await loadDashboardData();
    showDashboard();
  } catch (error) {
    showLogin();
    if (error.status !== 401) loginError.textContent = error.message;
  }
}

restoreStaffSession();
