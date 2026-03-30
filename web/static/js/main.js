// Serial Fork — minimal JS
// Most functionality is server-rendered; this file handles small enhancements.

document.addEventListener('DOMContentLoaded', () => {
  // Auto-dismiss flash messages after 4 seconds
  document.querySelectorAll('.flash').forEach(el => {
    setTimeout(() => el.remove(), 4000);
  });

  // Mobile nav toggle
  const toggle = document.getElementById('navToggle');
  const navLinks = document.getElementById('navLinks');
  if (toggle && navLinks) {
    toggle.addEventListener('click', () => {
      const open = navLinks.classList.toggle('open');
      toggle.setAttribute('aria-expanded', open);
    });
  }
});
