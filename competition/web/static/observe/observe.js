/* 只读观察面：把 /api/diag/* 的投影贴到流程的每个阶段上。
 *
 * 页面自己不持有任何凭据：token 只放在本标签页的 sessionStorage，
 * 数据请求仍要经过 auditor 会话；轮询在页面隐藏时暂停。
 * 流程图由浏览器自绘（DOM 方块 + SVG 连线），不加载任何预渲染图片。
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'zjj.observe.token';
  var OID_KEY = 'zjj.observe.oid';
  var THEME_KEY = 'zjj.observe.theme';
  var POLL_MS = 5000;
  var MAX_PARALLEL = 6;

  var LABEL = {
    idle: '未到达',
    done: '已走过',
    current: '当前',
    blocked: '阻断',
    'current-blocked': '当前 · 阻断',
    note: ''
  };

  var state = {
    token: sessionStorage.getItem(TOKEN_KEY) || '',
    oid: sessionStorage.getItem(OID_KEY) || '',
    profile: '',
    timer: null,
    running: false,
    asOf: null,
    model: null,
    data: {},
    error: {},
    nodes: {},
    blocks: {},
    current: null
  };

  var el = {};

  function $(id) { return document.getElementById(id); }

  function setSession(text, kind) {
    if (!el.session) return;
    el.session.textContent = text;
    el.session.setAttribute('data-state', kind || 'empty');
  }

  function mask(token) {
    if (!token) return '';
    return token.length <= 10 ? '••••' : token.slice(0, 4) + '••••' + token.slice(-4);
  }

  /* ── 主题：终端（暗）/ 档案（亮） ─────────────────────────────────── */
  function applyTheme(mode) {
    var dark = mode !== 'light';
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    if (el.theme) {
      el.theme.textContent = dark ? '档案' : '终端';
      el.theme.setAttribute('aria-pressed', dark ? 'true' : 'false');
      el.theme.setAttribute('title', dark ? '切到档案模式' : '切到终端模式');
    }
    try { localStorage.setItem(THEME_KEY, dark ? 'dark' : 'light'); } catch (e) {}
  }

  /* ── 请求 ─────────────────────────────────────────────────────────── */
  function api(path) {
    if (!state.token) return Promise.reject({ deny: 'SESSION_REQUIRED' });
    return fetch(path, {
      headers: { authorization: 'Bearer ' + state.token },
      cache: 'no-store'
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) return Promise.reject(body && body.deny ? body : { deny: 'HTTP_' + res.status });
        return body;
      });
    });
  }

  function pathFor(name) {
    var scope = state.model && state.model.endpoints[name];
    if (scope === 'operation') {
      return state.oid ? '/api/diag/' + name + '/' + encodeURIComponent(state.oid) : null;
    }
    if (scope === 'profile') {
      return state.profile ? '/api/diag/' + name + '/' + encodeURIComponent(state.profile) : null;
    }
    if (scope === 'table') {
      return '/api/diag/db/w_operation';
    }
    return '/api/diag/' + name;
  }

  /* ── 取值与格式化 ─────────────────────────────────────────────────── */
  function pick(obj, path) {
    var parts = String(path || '').split('.');
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function fmt(value) {
    if (value === undefined || value === null || value === '') return '—';
    if (typeof value === 'boolean') return value ? '是' : '否';
    if (typeof value === 'number') return String(value);
    if (Array.isArray(value)) {
      if (value.length === 0) return '0 项';
      if (value.every(function (v) { return v === null || typeof v !== 'object'; })) {
        var text = value.join(' · ');
        return text.length > 72 ? text.slice(0, 71) + '…' : text;
      }
      return value.length + ' 项';
    }
    if (typeof value === 'object') {
      var json = JSON.stringify(value);
      return json.length > 72 ? json.slice(0, 71) + '…' : json;
    }
    var plain = String(value);
    return plain.length > 72 ? plain.slice(0, 71) + '…' : plain;
  }

  /* ── 数据贴附 ─────────────────────────────────────────────────────── */
  function fill() {
    document.querySelectorAll('[data-live]').forEach(function (node) {
      var body = state.data[node.getAttribute('data-live-diag')];
      var field = node.getAttribute('data-live-field') || '';
      var path = field.indexOf('data.') === 0 ? field.slice(5) : field;
      var value = body === undefined ? undefined : pick(body, path);
      node.textContent = fmt(value);
      node.setAttribute('data-empty', value === undefined || value === null || value === '' ? '1' : '0');
    });

    document.querySelectorAll('.ob-card').forEach(function (card) {
      var diag = card.getAttribute('data-diag');
      var body = state.data[diag];
      var ok = body !== undefined;
      card.setAttribute('data-state', ok ? 'ok' : (state.error[diag] ? 'error' : ''));
      card.querySelectorAll('[data-field]').forEach(function (cell) {
        var field = cell.getAttribute('data-field') || '';
        var path = field.indexOf('data.') === 0 ? field.slice(5) : field;
        cell.textContent = ok ? fmt(pick(body, path)) : '—';
      });
    });
  }

  /* ── 由投影推断数据流停在哪 ───────────────────────────────────────── */
  function derive() {
    var model = state.model;
    if (!model) return;
    var d = state.data;
    var nodes = {};
    var has = function (name) { return d[name] !== undefined; };
    var arr = function (name, key) {
      var body = d[name];
      return body && Array.isArray(body[key]) ? body[key] : [];
    };
    var stages = arr('guard', 'observed_stages');
    var seen = function (kind) { return stages.indexOf(kind) !== -1; };

    nodes.AG = arr('entry', 'operations').length ? 'done' : 'idle';
    var kinds = arr('entry', 'entry_kinds');
    nodes.ENTRY_SRV = kinds.indexOf('server') !== -1 ? 'done' : 'idle';
    nodes.ENTRY_IND = kinds.indexOf('ind_http') !== -1 || kinds.indexOf('ind_mcp') !== -1 ? 'done' : 'idle';
    nodes.C = arr('registry', 'records').length ? 'done' : 'idle';
    nodes.E = has('source') && d.source.actor ? 'done' : 'idle';
    nodes.CTX = has('construct') && d.construct.action_hash ? 'done' : 'idle';

    if (has('guard')) {
      nodes.GUARD = (d.guard.decision || d.guard.status) ? 'done' : 'idle';
    } else {
      nodes.GUARD = 'idle';
    }

    nodes.PREPARE = has('plan') && d.plan.intent !== undefined && d.plan.intent !== null ? 'done' : 'idle';
    nodes.CHAL = (arr('challenge', 'nonces').length
      || (has('identity') && d.identity.stage)) ? 'done' : 'idle';
    nodes.GF = has('goal') && d.goal.mode
      ? (d.goal.decision === 'F' ? 'blocked' : 'done')
      : 'idle';

    var accepted = seen('W_COMMIT') || (has('accept') && !!d.accept.state);
    nodes.ACCEPT = accepted ? 'done' : 'idle';
    var signed = has('receipt') && d.receipt.state === 'SIGNED';
    nodes.RECEIPT = (signed || seen('W_RECEIPT')) ? 'done' : 'idle';
    var pending = accepted && !signed;
    nodes.PENDING = pending ? 'blocked' : 'idle';
    nodes.CLAIM = (seen('W_CLAIM') || (has('claim') && d.claim.attempt_id)) ? 'done' : 'idle';
    nodes.EXEC0 = (seen('W_EXEC_INTENT') || (has('exec') && d.exec.exec_consumed)) ? 'done' : 'idle';

    nodes.TOOL = (arr('tool', 'requests').length || arr('tool', 'effects').length
      || arr('tool', 'finalfacts').length) ? 'done' : 'idle';

    nodes.QUERY = (seen('W_QUERY_INTENT') || (has('query') && d.query.queries > 0)) ? 'done' : 'idle';
    nodes.FINAL = (has('final') && d.final.final_fact_id) ? 'done' : 'idle';
    nodes.SETTLE = (seen('W_SETTLE') || (has('settlement') && d.settlement.fact_id)) ? 'done' : 'idle';
    nodes.CANCEL = (seen('W_CANCEL') || (has('cancel') && d.cancel.state === 'CANCELED')) ? 'done' : 'idle';

    var halted = (has('exec') && d.exec.halted) || (has('accept') && d.accept.state === 'HALTED');
    var unknown = has('exec') && d.exec.effect_state === 'UNKNOWN' && d.exec.exec_consumed;
    var denied = has('deny') && arr('deny', 'refs').length > 0;

    nodes.UNKNOWN = unknown ? 'blocked' : 'idle';
    nodes.HALTED = halted ? 'blocked' : 'idle';
    nodes.DUP = 'idle';
    nodes.REJ = denied ? 'blocked' : 'idle';

    nodes.SHARED = has('store') && d.store.shared ? 'done' : 'idle';
    nodes.RES = arr('obligations', 'resources').length ? 'done' : 'idle';
    nodes.OBL = arr('obligations', 'goals').length ? 'done' : 'idle';
    nodes.OBS = arr('observe', 'events').length ? 'done' : 'idle';
    nodes.VIEW = has('result') && d.result.status ? 'done' : 'idle';
    nodes.NOTE = 'note';

    var current = null;
    if (halted) current = 'HALTED';
    else if (nodes.CANCEL === 'done') current = 'CANCEL';
    else if (nodes.SETTLE === 'done') current = 'SETTLE';
    else if (unknown) current = 'UNKNOWN';
    else if (pending) current = 'PENDING';
    else if (nodes.GF === 'blocked' || denied) {
      current = denied ? 'REJ' : 'GF';
    } else {
      model.stages.forEach(function (id) {
        if (nodes[id] === 'done') current = id;
      });
    }
    if (current) {
      nodes[current] = nodes[current] === 'blocked' ? 'current-blocked' : 'current';
    }

    var blocks = {};
    model.blocks.forEach(function (block) {
      var list = block.nodes.filter(function (node) { return node.id !== 'NOTE'; })
        .map(function (node) { return nodes[node.id] || 'idle'; });
      if (list.indexOf('current-blocked') !== -1) blocks[block.id] = 'current-blocked';
      else if (list.indexOf('blocked') !== -1) blocks[block.id] = 'blocked';
      else if (list.indexOf('current') !== -1) blocks[block.id] = 'current';
      else if (list.indexOf('done') !== -1) blocks[block.id] = 'done';
      else blocks[block.id] = 'idle';
    });

    state.nodes = nodes;
    state.blocks = blocks;
    state.current = current;
    paint();
  }

  function paint() {
    document.querySelectorAll('[data-node]').forEach(function (node) {
      var id = node.getAttribute('data-node');
      var value = state.nodes[id] || 'idle';
      node.setAttribute('data-state', value);
      var tag = node.querySelector('[data-node-state]');
      if (tag) tag.textContent = LABEL[value];
    });

    document.querySelectorAll('.ob-block').forEach(function (block) {
      var id = block.getAttribute('data-block');
      var value = state.blocks[id] || 'idle';
      block.setAttribute('data-state', value);
      var tag = block.querySelector('[data-block-state]');
      if (tag) tag.textContent = LABEL[value];
    });

    if (el.current) {
      var current = state.current;
      if (!current) {
        el.current.textContent = '当前 —';
        el.current.setAttribute('data-state', 'idle');
      } else {
        var blocked = state.nodes[current] === 'blocked'
          || state.nodes[current] === 'current-blocked';
        el.current.textContent = '当前 · ' + current + (blocked ? ' · 阻断' : '');
        el.current.setAttribute('data-state', blocked ? 'blocked' : 'current');
      }
    }
  }

  /* ── 总图连线（自绘，不用图片） ───────────────────────────────────── */
  function segmentsHit(points, ignore, rects) {
    for (var i = 0; i + 1 < points.length; i++) {
      var x1 = points[i][0], y1 = points[i][1];
      var x2 = points[i + 1][0], y2 = points[i + 1][1];
      for (var key in rects) {
        if (ignore.indexOf(key) !== -1) continue;
        var r = rects[key];
        var left = r.left - 6, right = r.right + 6;
        var top = r.top - 6, bottom = r.bottom + 6;
        if (Math.abs(y1 - y2) < 0.5) {
          if (y1 > top && y1 < bottom) {
            var lo = Math.min(x1, x2), hi = Math.max(x1, x2);
            if (hi > left && lo < right) return true;
          }
        } else if (Math.abs(x1 - x2) < 0.5) {
          if (x1 > left && x1 < right) {
            var loY = Math.min(y1, y2), hiY = Math.max(y1, y2);
            if (hiY > top && loY < bottom) return true;
          }
        }
      }
    }
    return false;
  }

  function laneOffset(taken, key) {
    taken[key] = (taken[key] || 0) + 1;
    return (taken[key] - 1) * 14;
  }

  function spread(index) {
    var seq = [0, 10, -10, 20, -20, 30, -30];
    return seq[Math.min(index, seq.length - 1)];
  }

  function drawWires() {
    if (!state.model || !el.svg) return;
    var host = el.mapwrap;
    var box = host.getBoundingClientRect();
    var layer = el.svg.querySelector('.ob-wire-layer');
    if (!box.width || !box.height || !layer) return;

    el.svg.setAttribute('viewBox', '0 0 ' + Math.ceil(box.width) + ' ' + Math.ceil(box.height));
    layer.textContent = '';

    var rects = {};
    var bounds = { left: Infinity, top: Infinity, right: -Infinity, bottom: -Infinity };
    document.querySelectorAll('.ob-block').forEach(function (node) {
      var r = node.getBoundingClientRect();
      var item = {
        left: r.left - box.left,
        top: r.top - box.top,
        right: r.right - box.left,
        bottom: r.bottom - box.top,
        cx: r.left - box.left + r.width / 2,
        cy: r.top - box.top + r.height / 2
      };
      rects[node.getAttribute('data-block')] = item;
      bounds.left = Math.min(bounds.left, item.left);
      bounds.top = Math.min(bounds.top, item.top);
      bounds.right = Math.max(bounds.right, item.right);
      bounds.bottom = Math.max(bounds.bottom, item.bottom);
    });
    if (!isFinite(bounds.left)) return;

    var lanes = {};
    var arrows = {};

    var order = {};
    state.model.blocks.forEach(function (block, index) { order[block.id] = index; });
    var narrow = window.innerWidth <= 1180;

    state.model.block_edges.forEach(function (edge) {
      var a = rects[edge.src];
      var b = rects[edge.dst];
      if (!a || !b) return;
      if (narrow && Math.abs(order[edge.src] - order[edge.dst]) !== 1) return;

      var pair = [edge.src, edge.dst].sort().join('<>');
      arrows[pair] = (arrows[pair] || 0) + 1;
      var nudge = spread(arrows[pair] - 1);

      var horizontal = Math.abs(a.cy - b.cy) < 40;
      var points;

      if (horizontal) {
        var dir = b.cx >= a.cx ? 1 : -1;
        var sx = dir > 0 ? a.right : a.left;
        var tx = dir > 0 ? b.left : b.right;
        if (Math.abs(a.cy - b.cy) < 1) {
          var y = a.cy + (dir > 0 ? -nudge : nudge);
          points = [[sx, y], [tx, y]];
        } else {
          var midX = (sx + tx) / 2 + nudge;
          points = [[sx, a.cy], [midX, a.cy], [midX, b.cy], [tx, b.cy]];
        }
        if (segmentsHit(points, [edge.src, edge.dst], rects)) {
          var rowTop = Math.min(a.top, b.top);
          var rowBottom = Math.max(a.bottom, b.bottom);
          var below = rowTop > (bounds.top + bounds.bottom) / 2;
          var key = (below ? 'below-' : 'above-') + Math.round(below ? rowBottom : rowTop);
          var laneY = below
            ? rowBottom + 14 + laneOffset(lanes, key)
            : rowTop - 14 - laneOffset(lanes, key);
          points = [[a.cx, a.top], [a.cx, laneY],
                    [b.cx, laneY], [b.cx, b.top]];
        }
      } else {
        var down = b.cy >= a.cy;
        var sy = down ? a.bottom : a.top;
        var ty = down ? b.top : b.bottom;
        if (Math.abs(a.cx - b.cx) < 1) {
          var x = a.cx + (down ? nudge : -nudge);
          points = [[x, sy], [x, ty]];
        } else {
          var midY = (sy + ty) / 2 + nudge;
          points = [[a.cx, sy], [a.cx, midY], [b.cx, midY], [b.cx, ty]];
        }
        if (segmentsHit(points, [edge.src, edge.dst], rects)) {
          var laneX = bounds.right + 18 + laneOffset(lanes, 'right');
          if (laneX > box.width - 10) return;
          points = [[a.right, a.cy], [laneX, a.cy], [laneX, b.cy], [b.right, b.cy]];
        }
      }

      var d = 'M ' + points.map(function (point) {
        return (Math.round(point[0] * 10) / 10) + ' ' + (Math.round(point[1] * 10) / 10);
      }).join(' L ');

      var node = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      node.setAttribute('d', d);
      node.setAttribute('class', 'ob-wire');
      node.setAttribute('data-kind', edge.kind);
      node.setAttribute('marker-end', 'url(#ob-arrow-' + edge.kind + ')');
      layer.appendChild(node);
    });
  }

  /* ── 飞入 / 飞出 ──────────────────────────────────────────────────── */
  var closeTimer = null;

  function syncTop() {
    if (!el.bar) return;
    document.documentElement.style.setProperty('--ob-top', el.bar.offsetHeight + 'px');
  }

  function openBlock(id, push) {
    var panel = document.getElementById('block-' + id);
    if (!panel || !el.details) return;
    if (closeTimer) { clearTimeout(closeTimer); closeTimer = null; }
    syncTop();
    document.querySelectorAll('.ob-detail').forEach(function (other) {
      if (other !== panel) other.hidden = true;
    });
    panel.hidden = false;
    el.details.hidden = false;
    el.details.scrollTop = 0;
    state.openBlock = id;
    requestAnimationFrame(function () { el.details.classList.add('is-in'); });
    document.body.setAttribute('data-open', '1');
    if (push && location.hash !== '#block-' + id) {
      history.pushState(null, '', '#block-' + id);
    }
    var back = panel.querySelector('[data-back]');
    if (back) back.focus({ preventScroll: true });
  }

  function closeBlock(push) {
    if (!el.details || el.details.hidden) {
      if (push && location.hash !== '#map') history.pushState(null, '', '#map');
      return;
    }
    var last = state.openBlock;
    state.openBlock = null;
    el.details.classList.remove('is-in');
    document.body.removeAttribute('data-open');
    closeTimer = setTimeout(function () {
      if (el.details.classList.contains('is-in')) return;
      el.details.hidden = true;
      document.querySelectorAll('.ob-detail').forEach(function (panel) { panel.hidden = true; });
      closeTimer = null;
    }, 220);
    if (push && location.hash !== '#map') history.pushState(null, '', '#map');
    var back = last && document.querySelector('.ob-block[data-block="' + last + '"]');
    if (back) back.focus({ preventScroll: true });
  }

  function route() {
    var match = /^#block-([a-z0-9]+)$/.exec(location.hash || '');
    if (match && document.getElementById('block-' + match[1])) openBlock(match[1], false);
    else closeBlock(false);
  }

  /* ── 一轮刷新 ─────────────────────────────────────────────────────── */
  function runPool(thunks, limit) {
    var index = 0;
    function next() {
      if (index >= thunks.length) return Promise.resolve();
      var task = thunks[index++];
      return task().catch(function () {}).then(next);
    }
    var chain = [];
    for (var i = 0; i < Math.min(limit, thunks.length); i++) chain.push(next());
    return Promise.all(chain);
  }

  function refresh() {
    if (state.running || !state.model) return Promise.resolve();
    if (!state.token) {
      state.data = {};
      state.error = {};
      derive();
      setSession('未授权 · 页面只读', 'empty');
      return Promise.resolve();
    }
    state.running = true;
    var started = Date.now();
    var names = Object.keys(state.model.endpoints);
    var tasks = [];
    names.forEach(function (name) {
      var path = pathFor(name);
      if (!path) {
        delete state.data[name];
        delete state.error[name];
        return;
      }
      tasks.push(function () {
        return api(path).then(function (body) {
          state.data[name] = body && body.data ? body.data : {};
          state.error[name] = null;
          if (body && body.as_of) state.asOf = body.as_of;
        }, function (err) {
          delete state.data[name];
          state.error[name] = (err && err.deny) || 'ERROR';
        });
      });
    });

    return runPool(tasks, MAX_PARALLEL).then(function () {
      fill();
      derive();
      var ok = Object.keys(state.data).length > 0;
      var denied = Object.keys(state.error).filter(function (k) { return state.error[k]; });
      if (ok) setSession('已授权 · auditor · ' + mask(state.token), 'ok');
      else if (denied.length) setSession('会话无效 · ' + state.error[denied[0]], 'error');
      else setSession('无可用投影', 'error');
      if (el.asof) {
        el.asof.textContent = state.asOf
          ? 'as_of ' + new Date(state.asOf * 1000).toLocaleTimeString()
          : 'as_of —';
      }
      if (el.latency) el.latency.textContent = '本轮 ' + (Date.now() - started) + ' ms';
    }).catch(function () {
    }).then(function () { state.running = false; });
  }

  /* ── 操作列表 ─────────────────────────────────────────────────────── */
  function fillOperations(body) {
    var data = (body && body.data) || {};
    var ops = Array.isArray(data.operations) ? data.operations : [];
    if (!el.op) return;
    el.op.textContent = '';
    var blank = document.createElement('option');
    blank.value = '';
    blank.textContent = ops.length ? '— 选择操作 —' : '— 暂无操作 —';
    el.op.appendChild(blank);

    var selected = null;
    ops.forEach(function (item) {
      var option = document.createElement('option');
      option.value = item.operation_id;
      var bits = [item.profile, item.state, String(item.operation_id).slice(0, 8)];
      option.textContent = bits.filter(Boolean).join(' · ');
      option.setAttribute('data-profile', item.profile || '');
      el.op.appendChild(option);
      if (item.operation_id === state.oid) selected = option;
    });

    if (!selected && ops.length === 1) selected = el.op.options[1];
    if (selected) {
      el.op.value = selected.value;
    } else {
      state.oid = '';
      state.profile = '';
    }
    syncProfile();
  }

  function syncProfile() {
    if (!el.op) return;
    var option = el.op.selectedOptions && el.op.selectedOptions[0];
    state.oid = el.op.value || '';
    state.profile = (option && option.getAttribute('data-profile')) || '';
    try { sessionStorage.setItem(OID_KEY, state.oid); } catch (e) {}
    if (el.profile) el.profile.textContent = 'profile ' + (state.profile || '—');
  }

  /* ── 启动 ─────────────────────────────────────────────────────────── */
  function boot() {
    el.session = $('ob-session');
    el.asof = $('ob-asof');
    el.latency = $('ob-latency');
    el.token = $('ob-token');
    el.save = $('ob-token-save');
    el.clear = $('ob-token-clear');
    el.theme = $('ob-theme');
    el.op = $('ob-op');
    el.profile = $('ob-profile');
    el.current = $('ob-current');
    el.details = $('details');
    el.mapwrap = document.querySelector('.ob-mapwrap');
    el.svg = document.querySelector('.ob-wires');
    el.bar = document.querySelector('.ob-bar');

    var fallback = document.documentElement.getAttribute('data-theme') || 'light';
    var stored = fallback;
    try { stored = localStorage.getItem(THEME_KEY) || fallback; } catch (e) {}
    applyTheme(stored);

    if (el.theme) {
      el.theme.addEventListener('click', function () {
        applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
        syncTop();
        drawWires();
      });
    }

    if (el.token) el.token.value = state.token ? mask(state.token) : '';
    if (el.save) el.save.addEventListener('click', function () {
      var value = (el.token.value || '').trim();
      if (!value || value.indexOf('••') !== -1) return;
      state.token = value.replace(/^Bearer\s+/i, '');
      try { sessionStorage.setItem(TOKEN_KEY, state.token); } catch (e) {}
      el.token.value = mask(state.token);
      start(true);
    });
    if (el.clear) el.clear.addEventListener('click', function () {
      state.token = '';
      try { sessionStorage.removeItem(TOKEN_KEY); } catch (e) {}
      if (el.token) el.token.value = '';
      stop();
      state.data = {};
      state.error = {};
      if (el.op) fillOperations(null);
      fill();
      derive();
      setSession('未授权 · 页面只读', 'empty');
    });
    if (el.op) el.op.addEventListener('change', function () {
      syncProfile();
      refresh();
    });

    document.querySelectorAll('.ob-block').forEach(function (block) {
      block.addEventListener('click', function () {
        openBlock(block.getAttribute('data-block'), true);
      });
    });
    document.querySelectorAll('[data-back]').forEach(function (button) {
      button.addEventListener('click', function () { closeBlock(true); });
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && el.details && !el.details.hidden) closeBlock(true);
    });
    window.addEventListener('hashchange', route);
    window.addEventListener('resize', function () {
      window.requestAnimationFrame(function () {
        syncTop();
        drawWires();
      });
    });
    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') start(false);
      else stop();
    });

    fetch('/observe/assets/flow.json', { cache: 'no-store' })
      .then(function (res) { return res.json(); })
      .then(function (model) {
        state.model = model;
        fill();
        derive();
        drawWires();
        if (document.fonts && document.fonts.ready) {
          document.fonts.ready.then(function () { drawWires(); });
        }
        route();
        start(true);
      })
      .catch(function () {
        setSession('流程图未构建 · 运行 observe_page', 'error');
      });
  }

  function start(withEntry) {
    if (!state.token) {
      setSession('未授权 · 页面只读', 'empty');
      return;
    }
    if (withEntry) {
      api('/api/diag/entry').then(function (body) {
        fillOperations(body);
        return refresh();
      }, function (err) {
        setSession('会话无效 · ' + ((err && err.deny) || 'ERROR'), 'error');
      });
    } else {
      refresh();
    }
    if (state.timer) clearInterval(state.timer);
    state.timer = setInterval(refresh, POLL_MS);
  }

  function stop() {
    if (state.timer) clearInterval(state.timer);
    state.timer = null;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
