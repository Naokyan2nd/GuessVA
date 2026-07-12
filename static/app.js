(() => {
    'use strict';

    function syncThemeBtn() {
        const btn = document.getElementById('themeBtn');
        if (btn) {
            const chinese = document.documentElement.lang.startsWith('zh');
            btn.textContent = document.body.classList.contains('dark-theme')
                ? (chinese ? '浅色' : 'ライト')
                : (chinese ? '深色' : 'ダーク');
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
