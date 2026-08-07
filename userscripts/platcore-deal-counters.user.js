// ==UserScript==
// @name         Platcore Deal Counters for Hz
// @namespace    http://tampermonkey.net/
// @version      1.5
// @description  Счетчики статусов + New USDT сумма в шапке
// @author       You
// @match        https://hz.temkitemki.work/*
// @grant        none
// ==/UserScript==

(function () {
    'use strict';

    const API = 'https://my.prod.platcore.io/api/deals/findNew';
    const PAGE_LIMIT = 100;

    let realCounts = { new: 0, disputed: 0, pending: 0, paid: 0 };
    let newUsdtSum = 0;
    let applying = false;
    let applyTimer = null;

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
        if (!headers) return 0;
        try {
            const res = await fetch(
                `${API}?page=1&limit=50&status=${status}&type=buyAll`,
                { method: 'GET', headers }
            );
            if (!res.ok) return 0;
            const data = await res.json();
            return data.meta?.total || 0;
        } catch (e) {
            console.error(`Ошибка при получении ${status}:`, e);
            return 0;
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

    async function getNewUsdtSum() {
        try {
            const first = await fetchNewPage(1);
            if (!first) return 0;

            const total = first.meta?.total || 0;
            const rows = [...(first.rows || [])];
            const pages = Math.ceil(total / PAGE_LIMIT) || 1;

            for (let page = 2; page <= pages; page++) {
                const data = await fetchNewPage(page);
                if (data?.rows) rows.push(...data.rows);
            }

            return rows.reduce((sum, deal) => sum + (Number(deal?.out?.trader) || 0), 0);
        } catch (e) {
            console.error('Ошибка суммы new USDT:', e);
            return 0;
        }
    }

    function formatSum(value) {
        return value.toLocaleString('en-US', {
            minimumFractionDigits: 2,
            maximumFractionDigits: 2
        });
    }

    function ensureSumPlaque() {
        const currency = document.querySelector('[data-testid="currency-selector"]');
        if (!currency || !currency.parentNode) return null;

        let el = document.getElementById('pc-new-usdt-sum');
        if (!el) {
            el = document.createElement('div');
            el.id = 'pc-new-usdt-sum';
            el.className = currency.className;

            // мягкий красный акцент, без крика
            el.style.cssText = [
                'margin-left:8px',
                'padding:4px 10px',
                'border-radius:8px',
                'background:rgba(229,62,62,.12)',
                'border:1px solid rgba(229,62,62,.28)',
                'display:flex',
                'flex-direction:column',
                'justify-content:center',
                'line-height:1.15',
                'white-space:nowrap'
            ].join(';');

            const label = document.createElement('p');
            label.className = currency.querySelector('p')?.className || 'chakra-text';
            label.style.cssText = 'margin:0;color:#E57373;font-weight:600;font-size:12px;';
            label.dataset.role = 'label';
            label.textContent = 'New USDT';

            const value = document.createElement('p');
            value.className = currency.querySelector('p')?.className || 'chakra-text';
            value.style.cssText = 'margin:0;color:#FC8181;font-weight:700;font-size:13px;';
            value.dataset.role = 'value';
            value.textContent = '…';

            el.appendChild(label);
            el.appendChild(value);
        }

        // держим сразу перед currency-selector
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

    function updateBadge(root, value) {
        if (!root) return;
        const badge = root.querySelector('.chakra-badge');
        if (!badge) return;
        const strValue = String(value);
        if (badge.textContent !== strValue) badge.textContent = strValue;
    }

    function applyBadges() {
        if (applying) return;
        applying = true;
        try {
            document.querySelectorAll('button[data-testid="pay-out-tags-button"]').forEach(btn => {
                const text = btn.textContent.toLowerCase();
                if (text.includes('new')) updateBadge(btn, realCounts.new);
                if (text.includes('pending')) updateBadge(btn, realCounts.pending);
                if (text.includes('disputed')) updateBadge(btn, realCounts.disputed);
                if (text.includes('paid')) updateBadge(btn, realCounts.paid);
            });
            updateBadge(document.querySelector('[data-testid="menu-item-pay-out"]'), realCounts.new);
            updateBadge(document.querySelector('[data-testid="menu-item-disputes"]'), realCounts.disputed);
            updateSumPlaque();
        } finally {
            applying = false;
        }
    }

    function scheduleApplyBadges() {
        if (applyTimer) return;
        applyTimer = setTimeout(() => {
            applyTimer = null;
            applyBadges();
        }, 200);
    }

    async function updateCounts() {
        const [newCount, pendingCount, disputedCount, paidCount, usdtSum] = await Promise.all([
            getCount('new'),
            getCount('pending'),
            getCount('disputed'),
            getCount('paid'),
            getNewUsdtSum()
        ]);

        realCounts.new = newCount;
        realCounts.pending = pendingCount;
        realCounts.disputed = disputedCount;
        realCounts.paid = paidCount;
        newUsdtSum = usdtSum;

        applyBadges();
    }

    const observer = new MutationObserver(scheduleApplyBadges);
    observer.observe(document.body, { childList: true, subtree: true });

    updateCounts();
    setInterval(updateCounts, 15000);
})();
