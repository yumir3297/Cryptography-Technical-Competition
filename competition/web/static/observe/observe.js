/* 只读观察面：把 /api/diag/* 的投影贴到流程图的每个节点上。
 *
 * 图形按 mmd 的声明画成左到右的分层图：总图把子块收起成单点，块内视图
 * 展开该子图（含一步之外的块外节点）。列的先后由构建期的 flow.json 给出，
 * 浏览器只负责量文字、摆方块、连正交线——不加载任何预渲染图片。
 *
 * 页面自己不持有任何凭据：token 只放在本标签页的 sessionStorage，
 * 数据请求仍要经过 auditor 会话；轮询在页面隐藏时暂停。
 */
(function () {
  'use strict';

  var TOKEN_KEY = 'zjj.observe.token';
  var OID_KEY = 'zjj.observe.oid';
  var THEME_KEY = 'zjj.observe.theme';
  var POLL_MS = 5000;
  var MAX_PARALLEL = 6;
  var NS = 'http://www.w3.org/2000/svg';

  var KINDS = ['control', 'evidence', 'feedback', 'reject'];

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
    graphs: {},
    data: {},
    error: {},
    nodes: {},
    blocks: {},
    current: null,
    openBlock: null
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
      var list = block.nodes.filter(function (node) {
        return node.id !== 'NOTE' && !node.stub;
      }).map(function (node) { return nodes[node.id] || 'idle'; });
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

    document.querySelectorAll('.ob-gnode--block[data-block]').forEach(function (block) {
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

  /* ── 分层布局（mmd 结构，浏览器自绘） ─────────────────────────────── */
  function graphHost(name) {
    return document.querySelector('.ob-graph[data-graph="' + name + '"]');
  }

  function labelsLayer(canvas) {
    var layer = canvas.querySelector('.ob-labels');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'ob-labels';
      canvas.appendChild(layer);
    }
    return layer;
  }

  function layoutGraph(host) {
    var name = host.getAttribute('data-graph');
    var model = state.graphs[name];
    if (!model || !model.nodes.length) return;
    var wrap = host.querySelector('.ob-nodes');
    var canvas = host.querySelector('.ob-canvas');
    var svg = host.querySelector('.ob-edges');
    if (!wrap || !canvas || !svg || !host.clientWidth) return;

    var items = Array.prototype.slice.call(wrap.querySelectorAll('[data-graph-node]'));
    wrap.classList.add('is-laid');
    items.forEach(function (node) {
      node.style.left = '0px';
      node.style.top = '0px';
    });

    var geo = {};
    var byId = {};
    items.forEach(function (node) {
      var id = node.getAttribute('data-gid');
      byId[id] = node;
      geo[id] = { w: node.offsetWidth, h: node.offsetHeight };
    });

    var rankOf = {};
    model.nodes.forEach(function (node) {
      rankOf[node.id] = node.rank;
    });

    var levels = {};
    model.nodes.forEach(function (node) {
      if (!byId[node.id]) return;
      (levels[node.rank] = levels[node.rank] || []).push(node);
    });
    var ranks = Object.keys(levels).map(Number).sort(function (a, b) { return a - b; });
    if (!ranks.length) return;
    ranks.forEach(function (rank) {
      levels[rank].sort(function (a, b) { return a.order - b.order; });
    });

    var labeled = name !== 'map';
    var pad = 14;
    var gap = labeled ? 96 : 44;
    var rowGap = 24;
    var reverse = model.edges.filter(function (edge) {
      return rankOf[edge.src] !== undefined && rankOf[edge.dst] !== undefined
        && rankOf[edge.src] > rankOf[edge.dst];
    }).length;
    var longForward = model.edges.filter(function (edge) {
      return rankOf[edge.src] !== undefined && rankOf[edge.dst] !== undefined
        && rankOf[edge.dst] - rankOf[edge.src] > 1;
    }).length;

    var colW = {};
    var colH = {};
    var rowW = {};
    var rowH = {};
    ranks.forEach(function (rank) {
      var widthMax = 0;
      var heightSum = 0;
      var widthSum = 0;
      var heightMax = 0;
      levels[rank].forEach(function (node, index) {
        var box = geo[node.id];
        widthMax = Math.max(widthMax, box.w);
        heightSum += box.h + (index ? rowGap : 0);
        widthSum += box.w + (index ? rowGap : 0);
        heightMax = Math.max(heightMax, box.h);
      });
      colW[rank] = widthMax;
      colH[rank] = heightSum;
      rowW[rank] = widthSum;
      rowH[rank] = heightMax;
    });

    var maxCol = Math.max.apply(null, ranks.map(function (rank) { return colH[rank]; }));
    var maxRow = Math.max.apply(null, ranks.map(function (rank) { return rowW[rank]; }));
    var lrWidth = ranks.reduce(function (sum, rank) { return sum + colW[rank]; }, 0)
      + gap * (ranks.length - 1) + pad * 2;
    var LR = lrWidth <= host.clientWidth || host.clientWidth >= 1100;
    var gutter = LR
      ? (reverse + longForward ? 16 + (reverse + longForward) * 14 : 0)
      : (reverse ? 16 + reverse * 14 : 0);
    var bus = LR ? 0 : (longForward ? 16 + longForward * 14 : 0);
    var available = Math.max(160, host.clientWidth - pad * 2 - gutter);
    var inlineRow = {};
    ranks.forEach(function (rank) {
      inlineRow[rank] = rowW[rank] <= available;
    });
    var lineH = {};
    ranks.forEach(function (rank) {
      lineH[rank] = inlineRow[rank] ? rowH[rank]
        : levels[rank].reduce(function (sum, node, index) {
          return sum + geo[node.id].h + (index ? rowGap : 0);
        }, 0);
    });
    var tbWidth = pad * 2 + gutter + Math.max.apply(null, ranks.map(function (rank) {
      return inlineRow[rank] ? rowW[rank]
        : Math.max.apply(null, levels[rank].map(function (node) { return geo[node.id].w; }));
    }));

    var rects = {};
    var width;
    var height;

    function place(node, x, y) {
      var box = geo[node.id];
      var nodeEl = byId[node.id];
      nodeEl.style.left = Math.round(x) + 'px';
      nodeEl.style.top = Math.round(y) + 'px';
      rects[node.id] = { x: x, y: y, w: box.w, h: box.h,
                         rank: node.rank, order: node.order };
    }

    if (LR) {
      width = lrWidth;
      height = pad * 2 + gutter + maxCol + bus;
      var x = pad;
      ranks.forEach(function (rank) {
        var y = pad + gutter;
        levels[rank].forEach(function (node) {
          place(node, x + (colW[rank] - geo[node.id].w) / 2, y);
          y += geo[node.id].h + rowGap;
        });
        x += colW[rank] + gap;
      });
    } else {
      width = tbWidth;
      height = pad * 2 + bus + ranks.reduce(function (sum, rank) {
        return sum + lineH[rank];
      }, 0) + gap * (ranks.length - 1);
      var y2 = pad;
      ranks.forEach(function (rank) {
        if (inlineRow[rank]) {
          var x3 = pad + gutter;
          levels[rank].forEach(function (node) {
            place(node, x3, y2 + (lineH[rank] - geo[node.id].h) / 2);
            x3 += geo[node.id].w + rowGap;
          });
        } else {
          var y3 = y2;
          levels[rank].forEach(function (node) {
            place(node, pad + gutter, y3);
            y3 += geo[node.id].h + rowGap;
          });
        }
        y2 += lineH[rank] + gap;
      });
    }

    canvas.style.width = Math.ceil(width) + 'px';
    canvas.style.height = Math.ceil(height) + 'px';
    var hint = host.parentNode && host.parentNode.querySelector('[data-scroll-hint]');
    if (hint) hint.hidden = width <= host.clientWidth + 1;
    svg.setAttribute('viewBox', '0 0 ' + Math.ceil(width) + ' ' + Math.ceil(height));
    svg.setAttribute('width', Math.ceil(width));
    svg.setAttribute('height', Math.ceil(height));

    drawEdges(host, model, rects, LR, name, {
      gutter: gutter,
      forwardLane: 10 + reverse * 14,
      busStart: LR ? pad + gutter + maxCol + 14
        : pad + ranks.reduce(function (sum, rank) { return sum + lineH[rank]; }, 0)
          + gap * (ranks.length - 1) + 14
    });
  }

  function drawEdges(host, model, rects, LR, name, frame) {
    var svg = host.querySelector('.ob-edges');
    var canvas = host.querySelector('.ob-canvas');
    svg.textContent = '';

    var defs = document.createElementNS(NS, 'defs');
    KINDS.forEach(function (kind) {
      var marker = document.createElementNS(NS, 'marker');
      marker.setAttribute('id', 'arrow-' + name + '-' + kind);
      marker.setAttribute('viewBox', '0 0 8 8');
      marker.setAttribute('refX', '7');
      marker.setAttribute('refY', '4');
      marker.setAttribute('markerWidth', '7');
      marker.setAttribute('markerHeight', '7');
      marker.setAttribute('orient', 'auto-start-reverse');
      var head = document.createElementNS(NS, 'path');
      head.setAttribute('d', 'M0 0 L8 4 L0 8 z');
      head.setAttribute('class', 'ob-arrow--' + kind);
      marker.appendChild(head);
      defs.appendChild(marker);
    });
    svg.appendChild(defs);
    var layer = document.createElementNS(NS, 'g');
    svg.appendChild(layer);

    var labels = labelsLayer(canvas);
    labels.textContent = '';

    var pairs = {};
    var lane = 0;
    var busLane = 0;
    var ports = {};
    var labeled = name !== 'map';

    function port(id) {
      var index = (ports[id] = (ports[id] || 0) + 1) - 1;
      var seq = [0, 9, -9, 18, -18, 27, -27];
      return seq[Math.min(index, seq.length - 1)];
    }

    model.edges.forEach(function (edge) {
      var a = rects[edge.src];
      var b = rects[edge.dst];
      if (!a || !b) return;
      var pair = [edge.src, edge.dst].sort().join('<>');
      pairs[pair] = (pairs[pair] || 0) + 1;
      var nudge = (pairs[pair] - 1) * 8;
      var pa = port(edge.src);
      var pb = port(edge.dst);

      var d;
      var labelX;
      var labelY;

      if (edge.src === edge.dst) {
        var loopY = a.y + a.h / 2;
        d = 'M ' + (a.x + a.w) + ' ' + (loopY - 11)
          + ' H ' + (a.x + a.w + 26)
          + ' V ' + (loopY + 11)
          + ' H ' + (a.x + a.w);
        labelX = a.x + a.w + 30;
        labelY = loopY + 20;
      } else if (LR) {
        if (b.rank - a.rank > 1) {
          var busY = frame.forwardLane + (busLane++) * 14;
          var ay = a.y + a.h / 2 + pa;
          var oy = b.y + b.h / 2 + pb;
          d = 'M ' + (a.x + a.w) + ' ' + ay
            + ' H ' + (a.x + a.w + 14)
            + ' V ' + busY
            + ' H ' + (b.x - 14)
            + ' V ' + oy
            + ' H ' + b.x;
          labelX = (a.x + b.x) / 2;
          labelY = busY;
        } else if (b.rank > a.rank) {
          var sx = a.x + a.w;
          var sy = a.y + a.h / 2 + pa;
          var tx = b.x;
          var ty = b.y + b.h / 2 + pb;
          var mx = (sx + tx) / 2 + nudge;
          d = 'M ' + sx + ' ' + sy + ' H ' + mx + ' V ' + ty + ' H ' + tx;
          labelX = mx;
          labelY = (sy + ty) / 2;
        } else if (b.rank === a.rank) {
          var cx = a.x + a.w / 2 + pa;
          var dx = b.x + b.w / 2 + pb;
          if (b.y > a.y) {
            d = 'M ' + cx + ' ' + (a.y + a.h) + ' V ' + (a.y + a.h + 12)
              + ' H ' + dx + ' V ' + b.y;
            labelX = (cx + dx) / 2;
            labelY = a.y + a.h + 8;
          } else {
            d = 'M ' + cx + ' ' + a.y + ' V ' + (a.y - 12)
              + ' H ' + dx + ' V ' + (b.y + b.h);
            labelX = (cx + dx) / 2;
            labelY = a.y - 8;
          }
        } else {
          var laneY = 10 + (lane++) * 14;
          var ly = a.y + a.h / 2 + pa;
          var ry = b.y + b.h / 2 + pb;
          d = 'M ' + a.x + ' ' + ly
            + ' H ' + (a.x - 12)
            + ' V ' + laneY
            + ' H ' + (b.x + b.w + 12)
            + ' V ' + ry
            + ' H ' + (b.x + b.w);
          labelX = (a.x + b.x + b.w) / 2;
          labelY = laneY;
        }
      } else {
        if (b.rank - a.rank > 1) {
          var busY = frame.busStart + (busLane++) * 14;
          var ay2 = a.y + a.h / 2 + pa;
          var oy = b.y + b.h / 2 + pb;
          d = 'M ' + (a.x + a.w) + ' ' + ay2
            + ' H ' + (a.x + a.w + 12)
            + ' V ' + busY
            + ' H ' + (b.x - 14)
            + ' V ' + oy
            + ' H ' + b.x;
          labelX = (a.x + b.x) / 2;
          labelY = busY;
        } else if (b.rank > a.rank) {
          var bx = a.x + a.w / 2 + pa;
          var by = a.y + a.h;
          var ex = b.x + b.w / 2 + pb;
          var ey = b.y;
          var my = (by + ey) / 2 + nudge;
          d = 'M ' + bx + ' ' + by + ' V ' + my + ' H ' + ex + ' V ' + ey;
          labelX = (bx + ex) / 2;
          labelY = my;
        } else if (b.rank === a.rank) {
          var cy = a.y + a.h / 2 + pa;
          var fy = b.y + b.h / 2 + pb;
          if (b.x > a.x) {
            d = 'M ' + (a.x + a.w) + ' ' + cy + ' H ' + (a.x + a.w + 12)
              + ' V ' + fy + ' H ' + b.x;
            labelX = a.x + a.w + 8;
            labelY = (cy + fy) / 2;
          } else {
            d = 'M ' + a.x + ' ' + cy + ' H ' + (a.x - 12)
              + ' V ' + fy + ' H ' + (b.x + b.w);
            labelX = a.x - 8;
            labelY = (cy + fy) / 2;
          }
        } else {
          var laneX = 10 + (lane++) * 14;
          var fx = a.x + a.w / 2 + pa;
          var gy = b.y + b.h / 2 + pb;
          d = 'M ' + fx + ' ' + a.y
            + ' V ' + (a.y - 12)
            + ' H ' + laneX
            + ' V ' + gy
            + ' H ' + b.x;
          labelX = laneX;
          labelY = (a.y + b.y + b.h / 2) / 2;
        }
      }

      var path = document.createElementNS(NS, 'path');
      path.setAttribute('d', d);
      path.setAttribute('class', 'ob-edge');
      path.setAttribute('data-kind', edge.kind);
      path.setAttribute('marker-end', 'url(#arrow-' + name + '-' + edge.kind + ')');
      if (edge.label) {
        var title = document.createElementNS(NS, 'title');
        title.textContent = edge.label;
        path.appendChild(title);
      }
      layer.appendChild(path);

      if (labeled && edge.label) {
        var chip = document.createElement('span');
        chip.className = 'ob-elabel';
        chip.textContent = edge.label;
        chip.title = edge.label;
        chip.style.left = Math.round(labelX) + 'px';
        chip.style.top = Math.round(labelY) + 'px';
        labels.appendChild(chip);
      }
    });
  }

  function layoutAll() {
    var map = graphHost('map');
    if (map) layoutGraph(map);
    var open = document.querySelector('.ob-detail:not([hidden])');
    if (open) {
      var host = open.querySelector('.ob-graph');
      if (host) layoutGraph(host);
    }
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
    state.openBlock = id;
    var host = panel.querySelector('.ob-graph');
    if (host) layoutGraph(host);
    requestAnimationFrame(function () {
      el.details.classList.add('is-in');
      if (host) layoutGraph(host);
    });
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
    var back = last && document.querySelector('.ob-gnode--block[data-block="' + last + '"]');
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
      var denied = Object.keys(state.error).filter(function (key) { return state.error[key]; });
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
    el.bar = document.querySelector('.ob-bar');

    var fallback = document.documentElement.getAttribute('data-theme') || 'light';
    var stored = fallback;
    try { stored = localStorage.getItem(THEME_KEY) || fallback; } catch (e) {}
    applyTheme(stored);

    if (el.theme) {
      el.theme.addEventListener('click', function () {
        applyTheme(document.documentElement.getAttribute('data-theme') === 'dark' ? 'light' : 'dark');
        syncTop();
        layoutAll();
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

    document.querySelectorAll('.ob-gnode--block').forEach(function (block) {
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
        layoutAll();
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
        state.graphs = { map: model.map };
        model.blocks.forEach(function (block) {
          state.graphs['block-' + block.id] = { nodes: block.nodes, edges: block.edges };
        });
        fill();
        derive();
        layoutAll();
        syncTop();
        if (document.fonts && document.fonts.ready) {
          document.fonts.ready.then(function () { layoutAll(); });
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
