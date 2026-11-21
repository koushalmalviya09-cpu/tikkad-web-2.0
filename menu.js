const menuToggle = document.querySelector('.menu-toggle');
const mainNav = document.querySelector('#main-nav');
const menuFilters = document.querySelector('#menu-filters');
const menuItems = document.querySelector('#menu-items');
const menuStatus = document.querySelector('#menu-status');
let items = [];
let selectedCategory = 'All';

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
    price.textContent = new Intl.NumberFormat('en-IN', {
      style: 'currency',
      currency: 'INR',
      maximumFractionDigits: 0
    }).format(item.price);
    content.append(category, name, description, price);
    card.append(content);
    menuItems.append(card);
  });
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

loadMenu();
