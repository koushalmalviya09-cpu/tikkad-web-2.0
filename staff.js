let csrfToken = '';
let bookings = [];

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

async function reportMutationError(error) {
  if (error.status === 401) {
    showLogin();
    loginError.textContent = 'Your staff session expired. Please sign in again.';
    return;
  }
  dashboardMessage.textContent = error.message;
  try {
    await loadBookings();
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
    await loadBookings();
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

async function refreshBookings() {
  dashboardMessage.textContent = '';
  try {
    await loadBookings();
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
    await reportMutationError(error);
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
    await reportMutationError(error);
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
    await loadBookings();
    showDashboard();
  } catch (error) {
    showLogin();
    if (error.status !== 401) loginError.textContent = error.message;
  }
}

restoreStaffSession();
