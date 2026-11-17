/* ============================================================
   TrustHarvest — Field-Ledger UI Progressive Enhancement
   Adapted from Genspark assets/app.js for live Flask/Jinja routes.
   ============================================================ */
(function () {
  'use strict';

  /* ---------- hash expand/collapse + copy ---------- */
  function groupHash(hash) {
    var out = '';
    for (var i = 0; i < hash.length; i += 8) {
      out += '<span class="grp">' + hash.slice(i, i + 8) + '</span>';
    }
    return out;
  }

  function shortHash(hash) {
    if (hash.length <= 20) return hash;
    return hash.slice(0, 10) + '\u2026' + hash.slice(-6);
  }

  function buildHash(el) {
    var full = (el.getAttribute('data-hash') || '').trim();
    if (!full) return;
    var code = el.querySelector('code');
    if (!code) {
      code = document.createElement('code');
      el.appendChild(code);
    }
    code.setAttribute('data-hash-full', full);
    code.textContent = shortHash(full);
    var btns = el.querySelector('.hash__btns');
    if (!btns) {
      btns = document.createElement('span');
      btns.className = 'hash__btns';
      btns.innerHTML =
        '<button type="button" class="hash__btn" data-act="expand" aria-expanded="false" title="Show all 64 characters">Expand</button>' +
        '<button type="button" class="hash__btn" data-act="copy" title="Copy full hash">Copy</button>';
      el.appendChild(btns);
    }
    el.setAttribute('data-expanded', 'false');
  }

  function toggleHash(el) {
    var code = el.querySelector('code');
    if (!code) return;
    var full = code.getAttribute('data-hash-full') || code.textContent;
    var expanded = el.getAttribute('data-expanded') === 'true';
    var btn = el.querySelector('[data-act="expand"]');
    if (expanded) {
      code.textContent = shortHash(full);
      el.setAttribute('data-expanded', 'false');
      el.classList.remove('hash--full');
      if (btn) {
        btn.textContent = 'Expand';
        btn.setAttribute('aria-expanded', 'false');
      }
    } else {
      code.innerHTML = groupHash(full);
      el.setAttribute('data-expanded', 'true');
      el.classList.add('hash--full');
      if (btn) {
        btn.textContent = 'Collapse';
        btn.setAttribute('aria-expanded', 'true');
      }
    }
  }

  function fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.setAttribute('readonly', '');
    ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0';
    document.body.appendChild(ta);
    ta.select();
    var ok = false;
    try {
      ok = document.execCommand('copy');
    } catch (_) {}
    document.body.removeChild(ta);
    return ok;
  }

  function copyText(text, btn) {
    var done = function () {
      if (!btn) return;
      var prev = btn.textContent;
      if (btn.classList.contains('iconbtn')) {
        btn.setAttribute('data-copied', 'true');
        setTimeout(function () { btn.removeAttribute('data-copied'); }, 1400);
        return;
      }
      btn.textContent = 'Copied';
      btn.setAttribute('data-copied', 'true');
      setTimeout(function () {
        btn.textContent = prev;
        btn.removeAttribute('data-copied');
      }, 1400);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () {
        fallbackCopy(text);
        done();
      });
    } else {
      fallbackCopy(text);
      done();
    }
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('.hash__btn');
    if (b) {
      var wrap = b.closest('.hash');
      if (!wrap) return;
      var act = b.getAttribute('data-act');
      if (act === 'expand') toggleHash(wrap);
      if (act === 'copy') {
        var code = wrap.querySelector('code');
        copyText((code && (code.getAttribute('data-hash-full') || code.textContent)) || '', b);
      }
      return;
    }

    var copyOnly = e.target.closest('[data-copy]');
    if (copyOnly) {
      copyText(copyOnly.getAttribute('data-copy'), copyOnly.querySelector('.js-copy-lbl') || copyOnly);
    }
  });

  /* ---------- mobile navigation toggle ---------- */
  function initNav() {
    var toggle = document.querySelector('.nav__toggle');
    var links = document.querySelector('.nav__links');
    if (toggle && links) {
      toggle.addEventListener('click', function () {
        var open = links.classList.toggle('is-open');
        toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
  }

  /* ---------- retailer tile -> POS dock binding ---------- */
  function initShelfBind() {
    var tiles = document.querySelectorAll('[data-bind-tile]');
    if (!tiles.length) return;
    tiles.forEach(function (tile) {
      tile.addEventListener('click', function (e) {
        if (e.target.closest('a') || e.target.closest('button')) return;
        var prodId = tile.getAttribute('data-product-id') || '';
        var batchId = tile.getAttribute('data-batch-id') || '';
        var store = tile.getAttribute('data-store') || '';
        var loc = tile.getAttribute('data-location') || '';
        var price = tile.getAttribute('data-price') || '';
        var stock = tile.getAttribute('data-stock') || '';
        var arrival = tile.getAttribute('data-arrival') || '';
        var shelf = tile.getAttribute('data-shelf') || '';

        var fProd = document.getElementById('rt-product');
        var fStore = document.getElementById('rt-store');
        var fLoc = document.getElementById('rt-location');
        var fPrice = document.getElementById('rt-price');
        var fStock = document.getElementById('rt-stock');
        var fArrival = document.getElementById('rt-arrival');
        var fShelf = document.getElementById('rt-shelf');
        var lab = document.getElementById('shelfBatchTag');

        if (fProd && prodId) fProd.value = prodId;
        if (fStore && store) fStore.value = store;
        if (fLoc && loc) fLoc.value = loc;
        if (fPrice && price) fPrice.value = price;
        if (fStock && stock) fStock.value = stock;
        if (fArrival && arrival) fArrival.value = arrival;
        if (fShelf && shelf) fShelf.value = shelf;
        if (lab && batchId) lab.textContent = batchId;

        tiles.forEach(function (t) {
          t.classList.toggle('is-bound', t === tile);
        });

        var dock = document.getElementById('dock');
        if (dock && window.innerWidth < 992) {
          dock.classList.add('is-open');
        }
      });
    });
  }

  /* ---------- retailer mobile slide-over dock ---------- */
  function initDock() {
    var dock = document.getElementById('dock');
    if (!dock) return;
    document.querySelectorAll('[data-open-dock]').forEach(function (b) {
      b.addEventListener('click', function () { dock.classList.add('is-open'); });
    });
    document.querySelectorAll('[data-close-dock]').forEach(function (b) {
      b.addEventListener('click', function () { dock.classList.remove('is-open'); });
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') dock.classList.remove('is-open');
    });
  }

  /* ---------- clickable ledger rows ---------- */
  function initClickableRows() {
    document.querySelectorAll('tr[data-href]').forEach(function (row) {
      row.addEventListener('click', function (e) {
        if (e.target.closest('a') || e.target.closest('button')) return;
        var href = row.getAttribute('data-href');
        if (href) window.location.href = href;
      });
    });
  }

  /* ---------- mount ---------- */
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.hash[data-hash]').forEach(buildHash);
    initNav();
    initShelfBind();
    initDock();
    initClickableRows();
  });
})();
