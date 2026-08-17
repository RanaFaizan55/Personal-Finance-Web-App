document.addEventListener('DOMContentLoaded', () => {
  const today = new Date().toISOString().split('T')[0];
  document.querySelectorAll('input[type="date"]').forEach((input) => {
    if (!input.value) {
      input.value = today;
    }
  });

  const root = document.body;
  const toggleButton = document.getElementById('theme-toggle');
  const savedTheme = localStorage.getItem('life-hub-theme');

  if (savedTheme === 'dark') {
    root.classList.add('dark-theme');
  }

  if (toggleButton) {
    toggleButton.textContent = root.classList.contains('dark-theme') ? '☀️' : '🌙';
    toggleButton.addEventListener('click', () => {
      const isDark = root.classList.toggle('dark-theme');
      localStorage.setItem('life-hub-theme', isDark ? 'dark' : 'light');
      toggleButton.textContent = isDark ? '☀️' : '🌙';
    });
  }
});
