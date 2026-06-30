(() => {
    'use strict';

    function syncThemeBtn() {
        const btn = document.getElementById('themeBtn');
        if (btn) {
            btn.textContent = document.body.classList.contains('dark-theme') ? '☀️' : '🌙';
        }
    }

    window.toggleTheme = function toggleTheme() {
        document.body.classList.toggle('dark-theme');
        localStorage.setItem('theme', document.body.classList.contains('dark-theme') ? 'dark' : 'light');
        syncThemeBtn();
    };

    if (localStorage.getItem('theme') === 'dark') {
        document.body.classList.add('dark-theme');
    }

    document.addEventListener('DOMContentLoaded', () => {
        syncThemeBtn();
        const btn = document.getElementById('themeBtn');
        if (btn && !btn.onclick) {
            btn.addEventListener('click', toggleTheme);
        }
    });
})();
