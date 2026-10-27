(() => {
    const storageKey = 'interviewai-theme';
    const root = document.documentElement;
    let savedTheme;
    try { savedTheme = localStorage.getItem(storageKey); } catch (_) {}
    const systemTheme = window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    root.dataset.theme = savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : systemTheme;

    function updateButton(button) {
        const light = root.dataset.theme === 'light';
        button.setAttribute('aria-label', `Switch to ${light ? 'dark' : 'light'} mode`);
        button.setAttribute('title', `Switch to ${light ? 'dark' : 'light'} mode`);
        button.setAttribute('aria-pressed', String(light));
    }

    function mountToggle() {
        const host = document.querySelector('.nav-inner, .header-meta, .header-actions, .header-nav, body > .container');
        if (!host || document.getElementById('themeToggle')) return;
        const button = document.createElement('button');
        button.id = 'themeToggle';
        button.type = 'button';
        button.className = 'theme-toggle';
        if (host.matches('body > .container')) button.classList.add('theme-toggle--floating');
        button.innerHTML = `
            <svg class="theme-icon theme-icon-sun" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <circle cx="12" cy="12" r="4" stroke="currentColor" stroke-width="1.8"/>
                <path d="M12 2v2m0 16v2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M2 12h2m16 0h2M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
            </svg>
            <svg class="theme-icon theme-icon-moon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
                <path d="M20.2 15.7A8.5 8.5 0 0 1 8.3 3.8 8.5 8.5 0 1 0 20.2 15.7Z" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
                <path d="M17.8 3.2v3.5m-1.75-1.75h3.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
            </svg>`;
        updateButton(button);
        button.addEventListener('click', () => {
            root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
            try { localStorage.setItem(storageKey, root.dataset.theme); } catch (_) {}
            updateButton(button);
        });
        host.appendChild(button);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountToggle, { once: true });
    } else {
        mountToggle();
    }
})();
