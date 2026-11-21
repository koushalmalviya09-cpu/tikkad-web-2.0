const menuButton = document.querySelector('.menu-toggle');
const mainNav = document.querySelector('.main-nav');

menuButton.addEventListener('click', () => {
  const isOpen = menuButton.getAttribute('aria-expanded') === 'true';
  menuButton.setAttribute('aria-expanded', String(!isOpen));
  mainNav.classList.toggle('open', !isOpen);
});

mainNav.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    menuButton.setAttribute('aria-expanded', 'false');
    mainNav.classList.remove('open');
  });
});

const dateInput = document.querySelector('input[type="date"]');
const today = new Date();
const localDate = new Date(today.getTime() - today.getTimezoneOffset() * 60000)
  .toISOString()
  .split('T')[0];
dateInput.min = localDate;
dateInput.value = localDate;

const reservationForm = document.querySelector('#reservation-form');
const formMessage = document.querySelector('#form-message');

reservationForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submitButton = reservationForm.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  submitButton.textContent = 'Sending...';

  const data = new FormData(reservationForm);
  const payload = {
    name: data.get('name'),
    phone: data.get('phone'),
    date: data.get('date'),
    time: data.get('time'),
    guests: data.get('guests')
  };

  try {
    const response = await fetch('/api/bookings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const result = await response.json();

    if (!response.ok) throw new Error(result.error || 'Booking could not be submitted');

    const date = new Date(`${payload.date}T12:00:00`).toLocaleDateString(undefined, {
      month: 'long',
      day: 'numeric'
    });
    formMessage.textContent = `Thank you, ${payload.name}! Your request for ${payload.guests} guests on ${date} at ${payload.time} has been received.`;
    reservationForm.reset();
    dateInput.min = localDate;
    dateInput.value = localDate;
  } catch (error) {
    formMessage.textContent = error.message;
  } finally {
    submitButton.disabled = false;
    submitButton.textContent = 'Request booking';
  }
});

const nfcStatus = document.querySelector('#nfc-status');
const nfcReadButton = document.querySelector('#nfc-read');
const nfcWriteButton = document.querySelector('#nfc-write');

function setNfcStatus(message) {
  nfcStatus.textContent = message;
}

async function readNfcTag() {
  if (!('NDEFReader' in window)) {
    setNfcStatus('NFC reading needs Android Chrome and a secure HTTPS website.');
    return;
  }

  try {
    const reader = new NDEFReader();
    await reader.scan();
    setNfcStatus('NFC is active. Hold your phone close to a tag.');

    reader.addEventListener('reading', ({ message }) => {
      for (const record of message.records) {
        if (record.recordType === 'url') {
          const data = new TextDecoder().decode(record.data);
          setNfcStatus(`Tag found: ${data}`);
        } else {
          setNfcStatus('Tag found successfully.');
        }
      }
    });
  } catch (error) {
    setNfcStatus(`NFC could not start: ${error.message}`);
  }
}

async function writeNfcTag() {
  if (!('NDEFReader' in window)) {
    setNfcStatus('Tag setup needs Android Chrome, NFC enabled, and an HTTPS link. iPhone cannot write NFC tags from a browser.');
    return;
  }

  if (!window.isSecureContext) {
    setNfcStatus('Publish the website on HTTPS before writing the NFC tag.');
    return;
  }

  try {
    const writer = new NDEFReader();
    await writer.write({
      records: [{ recordType: 'url', data: new URL('/menu', window.location.origin).href }]
    });
    setNfcStatus('Success! The tag now opens Khandwa Tikkad Hotel.');
  } catch (error) {
    setNfcStatus(`Tag setup failed: ${error.message}`);
  }
}

nfcReadButton.addEventListener('click', readNfcTag);
nfcWriteButton.addEventListener('click', writeNfcTag);

if (!('NDEFReader' in window)) {
  nfcStatus.textContent = 'NFC setup works on supported Android phones using Chrome and HTTPS.';
}
