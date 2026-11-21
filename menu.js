const menuToggle = document.querySelector('.menu-toggle');
const mainNav = document.querySelector('#main-nav');
const menuFilters = document.querySelector('#menu-filters');
const menuItems = document.querySelector('#menu-items');
const menuStatus = document.querySelector('#menu-status');
const orderDialog = document.querySelector('#order-dialog');
const orderForm = document.querySelector('#order-form');
const orderMessage = document.querySelector('#order-message');
const cartItems = document.querySelector('#cart-items');
const cartCount = document.querySelector('#cart-count');
const cartTotal = document.querySelector('#cart-total');
const orderButton = document.querySelector('#place-order-button');
const paymentAvailability = document.querySelector('#payment-availability');
const fulfillmentSelect = document.querySelector('#order-fulfillment');
const tableNumberField = document.querySelector('#table-number-field');
let items = [];
let selectedCategory = 'All';
let orderEnabled = false;
let csrfToken = '';
let isSubmitting = false;
let paymentNeedsReview = false;
const cart = new Map();

function formatPrice(price) {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0
  }).format(price);
}

menuToggle.addEventListener('click', () => {
  const isOpen = menuToggle.getAttribute('aria-expanded') === 'true';
  menuToggle.setAttribute('aria-expanded', String(!isOpen));
  mainNav.classList.toggle('open', !isOpen);
});

mainNav.querySelectorAll('a').forEach((link) => {
  link.addEventListener('click', () => {
    menuToggle.setAttribute('aria-expanded', 'false');
    mainNav.classList.remove('open');
  });
});

function renderFilters() {
  const categories = ['All', ...new Set(items.map((item) => item.category))];
  menuFilters.replaceChildren();

  categories.forEach((category) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'menu-filter';
    button.textContent = category;
    button.setAttribute('aria-pressed', String(category === selectedCategory));
    button.addEventListener('click', () => {
      selectedCategory = category;
      renderFilters();
      renderItems();
    });
    menuFilters.append(button);
  });
}

function renderItems() {
  const visibleItems = selectedCategory === 'All'
    ? items
    : items.filter((item) => item.category === selectedCategory);
  menuItems.replaceChildren();
  menuStatus.textContent = visibleItems.length ? '' : 'There are no items in this category right now.';

  visibleItems.forEach((item) => {
    const card = document.createElement('article');
    card.className = 'menu-page-card';

    if (item.image_url) {
      const image = document.createElement('img');
      image.src = item.image_url;
      image.alt = item.name;
      image.loading = 'lazy';
      card.append(image);
    }

    const content = document.createElement('div');
    content.className = 'menu-page-card-body';
    const category = document.createElement('p');
    category.className = 'item-type';
    category.textContent = item.category;
    const name = document.createElement('h3');
    name.textContent = item.name;
    const description = document.createElement('p');
    description.className = 'menu-item-description';
    description.textContent = item.description;
    const price = document.createElement('strong');
    price.className = 'menu-item-price';
    price.textContent = formatPrice(item.price);
    const actions = document.createElement('div');
    actions.className = 'menu-card-actions';
    const addButton = document.createElement('button');
    addButton.className = 'button button-dark menu-add-button';
    addButton.type = 'button';
    addButton.textContent = 'Add to order';
    addButton.addEventListener('click', () => addToCart(item));
    actions.append(price, addButton);
    content.append(category, name, description, actions);
    card.append(content);
    menuItems.append(card);
  });
}

function addToCart(item) {
  const entry = cart.get(item.id);
  if (entry) {
    if (entry.quantity >= 20) {
      orderMessage.textContent = 'You can order up to 20 of each item.';
      orderDialog.showModal();
      return;
    }
    entry.quantity += 1;
  } else {
    cart.set(item.id, { item, quantity: 1 });
  }
  orderMessage.textContent = `${item.name} added to your order.`;
  updateCart();
}

function updateCart() {
  cartItems.replaceChildren();
  let quantityTotal = 0;
  let amountTotal = 0;
  if (cart.size === 0) {
    const empty = document.createElement('p');
    empty.className = 'cart-empty';
    empty.textContent = 'Your order is empty. Add something delicious from the menu.';
    cartItems.append(empty);
  }

  cart.forEach(({ item, quantity }, id) => {
    quantityTotal += quantity;
    amountTotal += item.price * quantity;
    const row = document.createElement('div');
    row.className = 'cart-row';
    const details = document.createElement('div');
    details.className = 'cart-row-details';
    const name = document.createElement('strong');
    name.textContent = item.name;
    const unitPrice = document.createElement('span');
    unitPrice.textContent = `${formatPrice(item.price)} each`;
    details.append(name, unitPrice);

    const controls = document.createElement('div');
    controls.className = 'cart-quantity';
    const decrease = document.createElement('button');
    decrease.type = 'button';
    decrease.textContent = '-';
    decrease.setAttribute('aria-label', `Remove one ${item.name}`);
    decrease.addEventListener('click', () => changeQuantity(id, -1));
    const quantityText = document.createElement('span');
    quantityText.textContent = quantity;
    const increase = document.createElement('button');
    increase.type = 'button';
    increase.textContent = '+';
    increase.setAttribute('aria-label', `Add one ${item.name}`);
    increase.disabled = quantity >= 20;
    increase.addEventListener('click', () => changeQuantity(id, 1));
    controls.append(decrease, quantityText, increase);

    const lineTotal = document.createElement('span');
    lineTotal.className = 'cart-line-total';
    lineTotal.textContent = formatPrice(item.price * quantity);
    row.append(details, controls, lineTotal);
    cartItems.append(row);
  });

  cartCount.textContent = quantityTotal;
  cartTotal.textContent = formatPrice(amountTotal);
  orderButton.disabled = !orderEnabled || cart.size === 0 || isSubmitting || paymentNeedsReview;
}

function changeQuantity(id, amount) {
  const entry = cart.get(id);
  if (!entry) return;
  entry.quantity += amount;
  if (entry.quantity <= 0) cart.delete(id);
  orderMessage.textContent = '';
  updateCart();
}

async function requestJson(url, options) {
  const response = await fetch(url, options);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || 'The request could not be completed.');
  return result;
}

async function loadRazorpay() {
  if (window.Razorpay) return;
  await new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = resolve;
    script.onerror = () => reject(new Error('Secure payment could not be loaded. Please try again.'));
    document.head.append(script);
  });
}

function setSubmitting(submitting, message = '') {
  isSubmitting = submitting;
  orderButton.textContent = submitting ? 'Preparing secure payment...' : 'Continue to payment';
  orderMessage.textContent = message;
  updateCart();
}

async function loadOrderConfig() {
  try {
    const config = await requestJson('/api/orders/config');
    orderEnabled = config.enabled;
    csrfToken = config.csrfToken;
    paymentAvailability.textContent = orderEnabled
      ? 'Pay securely online with Razorpay. Prices are confirmed when your order is placed.'
      : config.message || 'Online ordering is not available yet. Please contact the restaurant to place an order.';
    paymentAvailability.dataset.unavailable = String(!orderEnabled);
  } catch (error) {
    orderEnabled = false;
    paymentAvailability.textContent = error.message;
    paymentAvailability.dataset.unavailable = 'true';
  }
  updateCart();
}

async function submitOrder(event) {
  event.preventDefault();
  if (!orderEnabled || cart.size === 0 || isSubmitting) return;
  setSubmitting(true);

  try {
    const formData = new FormData(orderForm);
    const result = await requestJson('/api/orders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
      body: JSON.stringify({
        name: formData.get('name'),
        phone: formData.get('phone'),
        fulfillment: formData.get('fulfillment'),
        tableNumber: formData.get('tableNumber'),
        notes: formData.get('notes'),
        items: [...cart.values()].map(({ item, quantity }) => ({ id: item.id, quantity }))
      })
    });
    await loadRazorpay();
    const checkout = new window.Razorpay({
      key: result.keyId,
      amount: result.amount,
      currency: result.currency,
      name: result.name,
      description: `Order #${result.orderId}`,
      order_id: result.razorpayOrderId,
      prefill: { name: result.customerName, contact: result.phone },
      theme: { color: '#1e3027' },
      handler: async (payment) => {
        try {
          await requestJson(`/api/orders/${result.orderId}/confirm`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken },
            body: JSON.stringify(payment)
          });
          cart.clear();
          orderForm.reset();
          tableNumberField.hidden = false;
          setSubmitting(false, `Payment received. Your order #${result.orderId} has been sent to our staff.`);
        } catch (error) {
          paymentNeedsReview = true;
          setSubmitting(false, `Payment confirmation needs staff review. Contact the restaurant with order #${result.orderId}; do not pay again yet. ${error.message}`);
        }
      },
      modal: {
        ondismiss: () => {
          if (isSubmitting) setSubmitting(false, 'Payment was not completed. Your cart is still here if you want to try again.');
        }
      }
    });
    checkout.on('payment.failed', (event) => {
      const description = event.error && event.error.description;
      setSubmitting(false, description || 'Payment was not completed. Please try again.');
    });
    checkout.open();
  } catch (error) {
    setSubmitting(false, error.message);
  }
}

async function loadMenu() {
  try {
    const response = await fetch('/api/menu');
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'Menu could not be loaded.');
    items = result.items;
    renderFilters();
    renderItems();
  } catch (error) {
    menuStatus.textContent = error.message;
  }
}

document.querySelector('#order-cart-button').addEventListener('click', () => {
  orderMessage.textContent = '';
  orderDialog.showModal();
});
document.querySelector('#close-order-dialog').addEventListener('click', () => orderDialog.close());
orderDialog.addEventListener('click', (event) => {
  if (event.target === orderDialog) orderDialog.close();
});
fulfillmentSelect.addEventListener('change', () => {
  const isDineIn = fulfillmentSelect.value === 'dine_in';
  tableNumberField.hidden = !isDineIn;
  if (!isDineIn) tableNumberField.querySelector('input').value = '';
});
orderForm.addEventListener('submit', submitOrder);

loadMenu();
loadOrderConfig();
