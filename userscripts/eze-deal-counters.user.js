// ==UserScript==
// @name         Platcore Deal Counters for EZE
// @namespace    http://tampermonkey.net/
// @version      1.1
// @description  Счетчики статусов + New USDT сумма в шапке + уведомление о новой сделке KZT
// @author       You
// @match        https://e.hz.temkitemki.work/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    const API = 'https://e.hz.temkitemki.work/api/deals/findNew';
    const PAGE_LIMIT = 100;
    const OURS = new Set(['new', 'pending', 'disputed', 'paid']);
    const NOTIFY_KEY = 'eze-kzt-notify';
    const SEEN_KEY = 'eze-kzt-seen';

    let realCounts = { new: 0, disputed: 0, pending: 0, paid: 0 };
    let newUsdtSum = 0;
    let countsReady = false;
    let applying = false;
    let seenReady = false;
    let seen = new Set();

    try {
        const raw = localStorage.getItem(SEEN_KEY);
        if (raw != null) {
            const list = JSON.parse(raw);
            if (Array.isArray(list)) {
                seen = new Set(list.map(String));
                seenReady = true;
            }
        }
    } catch (e) {}

    function injectStyle() {
        if (document.getElementById('pc-counters-style')) return;
        const style = document.createElement('style');
        style.id = 'pc-counters-style';
        style.textContent = `
            [data-pc-count] .chakra-badge:not(.pc-badge) {
                display: none !important;
            }
            #pc-new-usdt-sum {
                margin-left: 8px;
                padding: 4px 10px;
                border-radius: 8px;
                background: rgba(229,62,62,.12);
                border: 1px solid rgba(229,62,62,.28);
                display: flex;
                flex-direction: column;
                justify-content: center;
                line-height: 1.15;
                white-space: nowrap;
                flex-shrink: 0;
            }
            #eze-kzt-notify {
                margin-left: 8px;
                padding: 6px 12px;
                border-radius: 8px;
                border: 1px solid #E53E3E;
                background: #FFF5F5;
                color: #C53030;
                font: 600 12px/1.15 system-ui, sans-serif;
                white-space: nowrap;
                flex-shrink: 0;
                cursor: pointer;
            }
            #eze-kzt-notify[data-on="1"] {
                background: #F0FFF4;
                border-color: #38A169;
                color: #276749;
            }
        `;
        document.documentElement.appendChild(style);
    }

    function authHeaders() {
        const token = localStorage.getItem('token');
        if (!token) return null;
        return {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json'
        };
    }

    async function getCount(status) {
        const headers = authHeaders();
        if (!headers) return null;
        try {
            const res = await fetch(
                `${API}?page=1&limit=50&status=${status}&type=buyAll`,
                { method: 'GET', headers }
            );
            if (!res.ok) return null;
            const data = await res.json();
            const total = data.meta?.total;
            if (total == null) return null;
            return Number(total);
        } catch (e) {
            console.error(`Ошибка при получении ${status}:`, e);
            return null;
        }
    }

    async function fetchNewPage(page) {
        const headers = authHeaders();
        if (!headers) return null;
        const res = await fetch(
            `${API}?page=${page}&limit=${PAGE_LIMIT}&status=new&type=buyAll`,
            { method: 'GET', headers }
        );
        if (!res.ok) return null;
        return res.json();
    }

    function isKzt(deal) {
        const sources = [deal?.currencyTo, deal?.currencyFrom];
        return sources.some((src) => {
            const code = src && typeof src === 'object' ? src.code : src;
            return String(code || '').toUpperCase() === 'KZT';
        });
    }

    function dealLine(deal) {
        const fiat = Number(deal?.out?.client) || 0;
        const usdt = Number(deal?.out?.trader) || 0;
        const id = deal?.orderId || deal?._id || '—';
        return `${id} · ${fiat} KZT · ${usdt} USDT`;
    }

    function saveSeen() {
        localStorage.setItem(SEEN_KEY, JSON.stringify([...seen].slice(-500)));
        seenReady = true;
    }

    function noteKzt(rows) {
        const fresh = [];
        rows.forEach((deal) => {
            if (!isKzt(deal)) return;
            const id = String(deal?._id || deal?.orderId || '');
            if (!id) return;
            if (seenReady && !seen.has(id)) fresh.push(deal);
            seen.add(id);
        });
        saveSeen();

        if (!fresh.length) return;
        if (localStorage.getItem(NOTIFY_KEY) !== '1') return;
        if (typeof Notification === 'undefined' || Notification.permission !== 'granted') return;

        const title = fresh.length === 1 ? 'Новая сделка KZT' : `Новые сделки KZT: ${fresh.length}`;
        try {
            new Notification(title, { body: fresh.slice(0, 5).map(dealLine).join('\n') });
        } catch (e) {
            console.error('Уведомление KZT:', e);
        }
    }

    async function getNewUsdtSum() {
        try {
            const first = await fetchNewPage(1);
            if (!first) return null;

            const total = first.meta?.total;
            if (total == null) return null;

            const rows = [...(first.rows || [])];
            const pages = Math.ceil(total / PAGE_LIMIT) || 1;

            for (let page = 2; page <= pages; page++) {
                const data = await fetchNewPage(page);
                if (data?.rows) rows.push(...data.rows);
                else return null;
            }

            noteKzt(rows);
            return rows.reduce((sum, deal) => sum + (Number(deal?.out?.trader) || 0), 0);
        } catch (e) {
            console.error('Ошибка суммы new USDT:', e);
            return null;
        }
    }

    function formatSum(value) {
        return value.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function buttonStatus(btn) {
        let text = '';
        btn.childNodes.forEach((node) => {
            if (node.nodeType === Node.TEXT_NODE) {
                text += node.textContent;
            } else if (
                node.nodeType === Node.ELEMENT_NODE &&
                !node.classList.contains('chakra-badge')
            ) {
                text += node.textContent;
            }
        });
        text = text.trim().toLowerCase();
        if (text.includes('pending')) return 'pending';
        if (text.includes('disputed')) return 'disputed';
        if (text.includes('paid')) return 'paid';
        if (text.includes('new')) return 'new';
        return null;
    }

    function nativeClass(el) {
        return el.className
            .split(/\s+/)
            .filter((c) => c && c !== 'pc-badge')
            .join(' ');
    }

    function updateOverlayBadge(root, value) {
        if (!root) return;

        const str = String(value);
        const badges = [...root.querySelectorAll('.chakra-badge')];
        const native = badges.find((b) => !b.classList.contains('pc-badge'));
        let ours = badges.find((b) => b.classList.contains('pc-badge'));

        if (!native && !ours) return;

        const cls = nativeClass(native || ours) + ' pc-badge';

        if (!ours) {
            ours = document.createElement('span');
            ours.className = cls;
            (native || root).after(ours);
        } else if (ours.className !== cls) {
            ours.className = cls;
        }

        if (ours.textContent !== str) ours.textContent = str;
        if (root.getAttribute('data-pc-count') !== str) {
            root.setAttribute('data-pc-count', str);
        }
    }

    let anchorEl = null;

    function headerAnchor() {
        if (anchorEl && anchorEl.isConnected) return anchorEl;

        const known = document.querySelector('[data-testid="currency-selector"]');
        if (known) {
            anchorEl = known;
            return known;
        }

        let best = null;
        let bestLen = Infinity;
        document.querySelectorAll('button, [role="button"], div, span, p').forEach((el) => {
            if (el.closest('#pc-new-usdt-sum, #eze-kzt-notify')) return;
            const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
            if (!/USDT/i.test(text) || !/TRC20/i.test(text) || text.length > 32) return;
            if (text.length < bestLen) {
                best = el;
                bestLen = text.length;
            }
        });
        if (!best) return null;
        anchorEl = best.closest('button, [role="button"]') || best;
        return anchorEl;
    }

    function paintNotify(btn) {
        const on = localStorage.getItem(NOTIFY_KEY) === '1' && Notification.permission === 'granted';
        btn.dataset.on = on ? '1' : '0';
        btn.textContent = on ? 'KZT вкл' : 'KZT выкл';
    }

    function ensureNotifyToggle() {
        if (document.getElementById('eze-kzt-notify')) return;
        const currency = headerAnchor();
        if (!currency || !currency.parentNode) return;

        const btn = document.createElement('button');
        btn.id = 'eze-kzt-notify';
        btn.type = 'button';
        paintNotify(btn);
        btn.addEventListener('click', async (event) => {
            event.preventDefault();
            event.stopPropagation();

            if (localStorage.getItem(NOTIFY_KEY) === '1') {
                localStorage.setItem(NOTIFY_KEY, '0');
                paintNotify(btn);
                return;
            }

            let perm = Notification.permission;
            if (perm === 'default') perm = await Notification.requestPermission();
            if (perm !== 'granted') {
                localStorage.setItem(NOTIFY_KEY, '0');
                btn.textContent = 'KZT нет доступа';
                return;
            }

            localStorage.setItem(NOTIFY_KEY, '1');
            paintNotify(btn);
            try {
                new Notification('KZT', { body: 'Уведомления включены' });
            } catch (e) {}
        });
        currency.parentNode.insertBefore(btn, currency);
    }

    function ensureSumPlaque() {
        const currency = headerAnchor();
        if (!currency || !currency.parentNode) return null;

        let el = document.getElementById('pc-new-usdt-sum');
        if (!el) {
            el = document.createElement('div');
            el.id = 'pc-new-usdt-sum';
            el.className = currency.className;

            const label = document.createElement('p');
            label.className = currency.querySelector('p')?.className || 'chakra-text';
            label.style.cssText = 'margin:0;color:#E57373;font-weight:600;font-size:12px;';
            label.dataset.role = 'label';
            label.textContent = 'New USDT';

            const value = document.createElement('p');
            value.className = currency.querySelector('p')?.className || 'chakra-text';
            value.style.cssText = 'margin:0;color:#FC8181;font-weight:700;font-size:13px;';
            value.dataset.role = 'value';
            value.textContent = countsReady ? formatSum(newUsdtSum) : '…';

            el.appendChild(label);
            el.appendChild(value);
        }

        if (el.nextElementSibling !== currency) {
            currency.parentNode.insertBefore(el, currency);
        }

        return el;
    }

    function updateSumPlaque() {
        const el = ensureSumPlaque();
        if (!el) return;
        const value = el.querySelector('[data-role="value"]');
        if (!value) return;
        const next = formatSum(newUsdtSum);
        if (value.textContent !== next) value.textContent = next;
    }

    function mountTools() {
        if (applying || document.getElementById('eze-kzt-notify')) return;
        if (!headerAnchor()) return;
        applying = true;
        observer.disconnect();
        try {
            ensureSumPlaque();
            ensureNotifyToggle();
        } finally {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
            }
            applying = false;
        }
    }

    function applyBadges() {
        if (applying || !countsReady) return;
        applying = true;
        observer.disconnect();
        try {
            document.querySelectorAll('button[data-testid="pay-out-tags-button"]').forEach((btn) => {
                const status = buttonStatus(btn);
                if (status && OURS.has(status)) {
                    updateOverlayBadge(btn, realCounts[status]);
                } else {
                    btn.removeAttribute('data-pc-count');
                    btn.querySelectorAll('.pc-badge').forEach((el) => el.remove());
                }
            });
            updateOverlayBadge(
                document.querySelector('[data-testid="menu-item-pay-out"]'),
                realCounts.new
            );
            updateOverlayBadge(
                document.querySelector('[data-testid="menu-item-disputes"]'),
                realCounts.disputed
            );
            updateSumPlaque();
            ensureNotifyToggle();
        } finally {
            if (document.body) {
                observer.observe(document.body, { childList: true, subtree: true });
            }
            applying = false;
        }
    }

    async function updateCounts() {
        const [newCount, pendingCount, disputedCount, paidCount, usdtSum] = await Promise.all([
            getCount('new'),
            getCount('pending'),
            getCount('disputed'),
            getCount('paid'),
            getNewUsdtSum()
        ]);

        if (newCount !== null) realCounts.new = newCount;
        if (pendingCount !== null) realCounts.pending = pendingCount;
        if (disputedCount !== null) realCounts.disputed = disputedCount;
        if (paidCount !== null) realCounts.paid = paidCount;
        if (usdtSum !== null) newUsdtSum = usdtSum;

        if (
            newCount !== null ||
            pendingCount !== null ||
            disputedCount !== null ||
            paidCount !== null ||
            usdtSum !== null
        ) {
            countsReady = true;
        }

        applyBadges();
    }

    const observer = new MutationObserver(() => {
        applyBadges();
    });

    injectStyle();

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    } else {
        document.addEventListener('DOMContentLoaded', () => {
            observer.observe(document.body, { childList: true, subtree: true });
        }, { once: true });
    }

    document.body?.addEventListener('click', () => {
        requestAnimationFrame(() => requestAnimationFrame(applyBadges));
    }, true);

    updateCounts();
    mountTools();
    setInterval(updateCounts, 15000);
    setInterval(applyBadges, 1000);
    setInterval(mountTools, 1000);
})();
