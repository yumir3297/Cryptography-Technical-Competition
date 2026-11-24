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
  function labelsLayer(canvas) {
    var layer = canvas.querySelector('.ob-labels');
    if (!layer) {
      layer = document.createElement('div');
      layer.className = 'ob-labels';
      canvas.appendChild(layer);
    }
    return layer;
  }

  // ── 布局：交给 dagre ────────────────────────────────────────────────────
  // 总图与块内是同一套：量出每个节点的真实宽高，交给 dagre 排 LR 泳道，
  // 再把节点放到它给的中心点、把边按它给的折线点画成直角折线。页面自己
  // 不做分层，也不猜列号。
  function orthoPath(points) {
    if (!points || !points.length) return '';
    var d = 'M ' + Math.round(points[0].x) + ' ' + Math.round(points[0].y);
    for (var i = 1; i < points.length; i++) {
      var p = points[i];
      var q = points[i - 1];
      var dx = Math.abs(p.x - q.x);
      var dy = Math.abs(p.y - q.y);
      if (dx > 0.5 && dy > 0.5) {
        d += ' H ' + Math.round(p.x) + ' V ' + Math.round(p.y);
      } else {
        d += ' L ' + Math.round(p.x) + ' ' + Math.round(p.y);
      }
    }
    return d;
  }

  function midPoint(points) {
    if (!points || !points.length) return { x: 0, y: 0 };
    var lens = [];
    var total = 0;
    for (var i = 1; i < points.length; i++) {
      var len = Math.abs(points[i].x - points[i - 1].x)
        + Math.abs(points[i].y - points[i - 1].y);
      lens.push(len);
      total += len;
    }
    var half = total / 2;
    var acc = 0;
    for (var j = 0; j < lens.length; j++) {
      if (acc + lens[j] >= half) {
        var t = lens[j] ? (half - acc) / lens[j] : 0;
        return {
          x: points[j].x + (points[j + 1].x - points[j].x) * t,
          y: points[j].y + (points[j + 1].y - points[j].y) * t
        };
      }
      acc += lens[j];
    }
    var last = points[points.length - 1];
    return { x: last.x, y: last.y };
  }

  function fallbackLayout(host, model, geo, byId) {
    // dagre 没加载成功时的兜底：一排横放，至少还能看清节点。
    var x = 18;
    var y = 18;
    var maxH = 0;
    model.nodes.forEach(function (node) {
      var el = byId[node.id];
      if (!el) return;
      el.style.left = x + 'px';
      el.style.top = y + 'px';
      x += geo[node.id].w + 90;
      maxH = Math.max(maxH, geo[node.id].h);
    });
    var canvas = host.querySelector('.ob-canvas');
    var svg = host.querySelector('.ob-edges');
    canvas.style.width = (x + 18) + 'px';
    canvas.style.height = (maxH + 36) + 'px';
    svg.setAttribute('viewBox', '0 0 ' + (x + 18) + ' ' + (maxH + 36));
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
      geo[id] = { w: node.offsetWidth || 1, h: node.offsetHeight || 1 };
    });

    if (typeof dagre === 'undefined' || !dagre.layout) {
      fallbackLayout(host, model, geo, byId);
      return;
    }

    var pad = 18;
    var labeled = name !== 'map';
    var gap = labeled ? (parseFloat(host.getAttribute('data-gap')) || 54) : 92;
    var rowGap = labeled ? 22 : 48;

    var g = new dagre.graphlib.Graph({ multigraph: true });
    g.setGraph({ rankdir: 'LR', nodesep: rowGap, ranksep: gap,
                 marginx: pad, marginy: pad });
    g.setDefaultEdgeLabel(function () { return {}; });
    model.nodes.forEach(function (node) {
      if (!byId[node.id]) return;
      g.setNode(node.id, { width: geo[node.id].w, height: geo[node.id].h });
    });
    model.edges.forEach(function (edge, index) {
      if (!byId[edge.src] || !byId[edge.dst]) return;
      g.setEdge(edge.src, edge.dst, { weight: 1, minlen: 1 }, 'e' + index);
    });
    dagre.layout(g);

    g.nodes().forEach(function (id) {
      var point = g.node(id);
      var box = geo[id];
      byId[id].style.left = Math.round(point.x - box.w / 2) + 'px';
      byId[id].style.top = Math.round(point.y - box.h / 2) + 'px';
    });

    var graph = g.graph();
    var width = Math.ceil(graph.width || 0);
    var height = Math.ceil(graph.height || 0);
    canvas.style.width = width + 'px';
    canvas.style.height = height + 'px';
    svg.setAttribute('viewBox', '0 0 ' + width + ' ' + height);
    svg.setAttribute('width', width);
    svg.setAttribute('height', height);

    drawEdges(host, model, g, name);
  }

  function drawEdges(host, model, g, name) {
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
    var labeled = name !== 'map';

    model.edges.forEach(function (edge, index) {
      var datum = g.edge({ v: edge.src, w: edge.dst, name: 'e' + index });
      if (!datum || !datum.points || !datum.points.length) return;
      var points = datum.points;
      var path = document.createElementNS(NS, 'path');
      path.setAttribute('d', orthoPath(points));
      path.setAttribute('class', 'ob-edge');
      path.setAttribute('data-kind', edge.kind);
      path.setAttribute('marker-end',
                        'url(#arrow-' + name + '-' + edge.kind + ')');
      if (edge.label) {
        var title = document.createElementNS(NS, 'title');
        title.textContent = edge.label;
        path.appendChild(title);
      }
      layer.appendChild(path);

      if (labeled && edge.label) {
        var mid = midPoint(points);
        var chip = document.createElement('span');
        chip.className = 'ob-elabel';
        chip.textContent = edge.label;
        chip.title = edge.label;
        chip.style.left = Math.round(mid.x) + 'px';
        chip.style.top = Math.round(mid.y) + 'px';
        labels.appendChild(chip);
      }
    });
  }

  function applyMapPan() {
    var map = mapHost();
    if (!map) return;
    var canvas = map.querySelector('.ob-canvas');
    if (canvas) {
      canvas.style.transform = 'translate(' + mapView.x.toFixed(1) + 'px, '
        + mapView.y.toFixed(1) + 'px) scale(' + mapView.k.toFixed(4) + ')';
    }
  }

  function layoutMap() {
    var map = mapHost();
    if (!map) return;
    layoutGraph(map);
    var canvas = map.querySelector('.ob-canvas');
    if (!canvas) return;
    var W = map.clientWidth;
    var H = map.clientHeight;
    var cw = canvas.offsetWidth || 1;
    var ch = canvas.offsetHeight || 1;
    // 高度铺满，块保持可读；横向超出就拖，滚轮可以拉远看全图。
    var k = Math.min((H - 40) / ch, 1.5);
    mapView.k = Math.max(0.2, k);
    mapView.x = 24;
    mapView.y = Math.round((H - ch * mapView.k) / 2);
    applyMapPan();
  }

  /* ── 就地展开：同一张画布的 zoom ─────────────────────────────────────
     没有第二层页面。被点的块在这张图上就地铺开内部结构，其余块被挤到
     两侧、缩小压暗，但始终留在视野里；收起时回到原位。所有变换都作用在
     同一画布的节点上，不出现覆盖层。 */
  var fly = null;
  var FLY_IN = 420;
  var FLY_OUT = 320;
  var FLY_EASE = 'cubic-bezier(.2, 0, 0, 1)';
  var PUSH_SCALE = 0.6;
  var frameRects = {};
  var view = { id: null, cw: 0, ch: 0, k: 1, fit: 1,
               panX: 0, panY: 0 };
  var mapView = { k: 1, x: 0, y: 0 };
  var mapDrag = null;
  var suppressClick = false;
  var ZOOM_MAX = 1.5;
  var ZOOM_STEP = 1.2;

  function syncTop() {
    if (!el.bar) return;
    document.documentElement.style.setProperty('--ob-top', el.bar.offsetHeight + 'px');
  }

  function calm() {
    return !!(window.matchMedia
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  }

  function stopFly() {
    if (!fly) return;
    var running = fly;
    fly = null;
    running.onfinish = null;
    running.cancel();
  }

  function viewTransform(v) {
    return 'translate(' + (v.panX || 0) + 'px, ' + (v.panY || 0) + 'px)'
      + ' scale(' + v.k.toFixed(4) + ')';
  }

  function showZoom() {
    if (!el.zoomVal) return;
    el.zoomVal.textContent = view.id ? Math.round(view.k * 100) + '%' : '—';
  }

  function setZoom(k) {
    if (!view.id) return;
    view.k = Math.max(view.fit, Math.min(ZOOM_MAX, k));
    var expand = expandOf(view.id);
    if (expand) expand.style.transform = viewTransform(view);
    showZoom();
  }

  function mapHost() {
    return document.querySelector('.ob-graph[data-graph="map"]');
  }

  function expandOf(id) {
    return document.querySelector('[data-expand="' + id + '"]');
  }

  function blockOf(id) {
    return document.querySelector('.ob-gnode--block[data-block="' + id + '"]');
  }

  // 每块在画布坐标系里的矩形，展开前量一次；收起时按它缩回去。
  // 块在画布坐标系里的矩形。总图的缩放/平移只作用在 .ob-canvas 上，
  // 屏幕坐标不能直接写回块的 transform；这里统一用 offset 尺寸。
  function captureFrames(host) {
    frameRects = {};
    host.querySelectorAll('.ob-gnode--block').forEach(function (node) {
      frameRects[node.getAttribute('data-block')] = {
        node: node,
        x: node.offsetLeft,
        y: node.offsetTop,
        w: node.offsetWidth,
        h: node.offsetHeight
      };
    });
  }

  function restoreBlocks(animate) {
    Object.keys(frameRects).forEach(function (bid) {
      var node = frameRects[bid].node;
      node.style.transition = animate
        ? 'transform ' + FLY_OUT + 'ms ' + FLY_EASE
          + ', opacity ' + FLY_OUT + 'ms ' + FLY_EASE
        : '';
      node.style.transform = '';
      node.style.opacity = '';
      node.style.visibility = '';
      node.removeAttribute('data-pushed');
      node.removeAttribute('inert');
      node.removeAttribute('aria-hidden');
    });
  }

  // 其余块按「左/右」分列退到展开层的两侧，列内按原高度顺序均分。
  function pushBlocks(activeId, animate) {
    var host = mapHost();
    if (!host) return;
    var k = mapView.k || 1;
    var W = host.clientWidth;
    var H = host.clientHeight;
    // 展开层在屏幕上的位置，换算回画布坐标；两侧的块也在这个坐标系里排。
    function localX(x) { return (x - mapView.x) / k; }
    function localY(y) { return (y - mapView.y) / k; }
    var visW = view.w * view.k;
    var visH = view.h * view.k;
    var frameLeft = localX((W - visW) / 2);
    var frameRight = localX((W + visW) / 2);
    var frameTop = localY((H - visH) / 2);
    var frameBottom = localY((H + visH) / 2);
    var left = [];
    var right = [];
    Object.keys(frameRects).forEach(function (bid) {
      if (bid === activeId) return;
      var box = frameRects[bid];
      (box.x + box.w / 2 < localX(W / 2) ? left : right).push(box);
    });
    left.sort(function (a, b) { return a.y - b.y; });
    right.sort(function (a, b) { return a.y - b.y; });

    var pushed = {};
    var pad = 10 / k;
    var gap = 14 / k;

    function move(box, cx, cy, scale) {
      var halfW = box.w * scale / 2;
      var halfH = box.h * scale / 2;
      cx = Math.max(localX(0) + pad + halfW,
           Math.min(localX(W) - pad - halfW, cx));
      cy = Math.max(localY(0) + pad + halfH,
           Math.min(localY(H) - pad - halfH, cy));
      pushed[box.node.getAttribute('data-block')] = {
        x: mapView.x + (cx - halfW) * k,
        y: mapView.y + (cy - halfH) * k,
        w: box.w * scale * k,
        h: box.h * scale * k
      };
      var dx = cx - (box.x + box.w / 2);
      var dy = cy - (box.y + box.h / 2);
      box.node.style.transition = animate
        ? 'transform ' + FLY_IN + 'ms ' + FLY_EASE
          + ', opacity ' + FLY_IN + 'ms ' + FLY_EASE
        : '';
      box.node.style.transform = 'translate(' + dx.toFixed(1) + 'px, '
        + dy.toFixed(1) + 'px) scale(' + scale.toFixed(3) + ')';
      box.node.style.opacity = '.42';
      box.node.setAttribute('data-pushed', '1');
    }

    function place(list, side) {
      var count = list.length;
      if (!count) return;
      var room = side === 'left'
        ? frameLeft - localX(20) : localX(W - 20) - frameRight;
      var scale = PUSH_SCALE / k;
      list.forEach(function (box) {
        scale = Math.min(scale, room / box.w);
      });
      scale = Math.max(0.38 / k, scale);
      // 列内紧凑排列，夹在展开层的上下边界之间。
      var step = Math.min((frameBottom - frameTop) / count,
                          list[0].h * scale + 26 / k);
      var top = (frameTop + frameBottom - step * count) / 2;
      list.forEach(function (box, index) {
        var cx = side === 'left'
          ? frameLeft - gap - box.w * scale / 2
          : frameRight + gap + box.w * scale / 2;
        move(box, cx, top + step * (index + 0.5), scale);
      });
    }

    place(left, 'left');
    place(right, 'right');
    if (frameRects[activeId]) {
      // 展开的那块彻底退场：不可见、不可点、不能被 Tab 聚焦。
      var self = frameRects[activeId].node;
      self.style.transition = animate ? 'opacity 160ms ease-out' : '';
      self.style.opacity = '0';
      self.style.visibility = 'hidden';
      self.setAttribute('inert', '');
      self.setAttribute('aria-hidden', 'true');
    }

    var edges = host.querySelector('.ob-edges');
    if (edges) {
      // 展开后总图连线整体退场，只留外部泳道；否则它们会在展开层
      // 底下拖一条条残影。transition 结束后再置 visibility，避免任何
      // 合成层残留。
      edges.style.transition = animate
        ? 'opacity ' + Math.round(FLY_IN * 0.5) + 'ms ease-out' : '';
      edges.style.opacity = '0';
      edges.style.visibility = 'hidden';
    }
  }

  function showHud(id) {
    var node = blockOf(id) || expandOf(id);
    if (!node || !el.hud) return;
    el.hud.hidden = false;
    if (el.hudCode) el.hudCode.textContent = node.getAttribute('data-code') || '';
    if (el.hudName) el.hudName.textContent = node.getAttribute('data-label') || '';
    if (el.hudEn) el.hudEn.textContent = node.getAttribute('data-en') || '';
    showZoom();
    document.querySelectorAll('[data-panel]').forEach(function (part) {
      part.hidden = part.getAttribute('data-panel') !== id;
    });
    if (el.hudPanel) el.hudPanel.hidden = true;
    if (el.hudRaw) el.hudRaw.setAttribute('aria-expanded', 'false');
  }

  function hideHud() {
    if (el.hud) el.hud.hidden = true;
    if (el.hudPanel) el.hudPanel.hidden = true;
    if (el.hudRaw) el.hudRaw.setAttribute('aria-expanded', 'false');
  }

  function clearSelection() {
    document.querySelectorAll('[data-selected]').forEach(function (node) {
      node.removeAttribute('data-selected');
    });
  }

  function selectLeaf(id) {
    if (view.id) collapseBlock(false, true);
    clearSelection();
    var node = blockOf(id);
    if (node) node.setAttribute('data-selected', '1');
    showHud(id);
  }

  function expandBlock(id, push, instant) {
    var host = mapHost();
    var expand = expandOf(id);
    if (!expand) { selectLeaf(id); return; }
    if (!host || !expand || !state.model) return;
    if (view.id === id) return;
    if (view.id) collapseBlock(false, true);

    clearSelection();
    syncTop();
    host.scrollLeft = 0;
    host.scrollTop = 0;
    stopFly();
    captureFrames(host);
    var frame = frameRects[id];

    var W = host.clientWidth;
    var H = host.clientHeight;

    expand.hidden = false;
    // 先给排版一个接近最终宽度的参考，再按真实尺寸落位。
    expand.style.width = Math.round(Math.max(W * 0.9, 1180)) + 'px';
    expand.style.height = '';
    expand.style.overflow = '';
    layoutGraph(expand);

    var canvas = expand.querySelector('.ob-canvas');
    var cw = canvas.offsetWidth || 1;
    var ch = canvas.offsetHeight || 1;
    var fit = Math.min(W * 0.72 / cw, (H - 40) / ch, 1);
    // 展开默认放大：子图直接铺满，细节先看清；要全貌时再缩回 fit。
    // S7 节点最多，125% 就够，再大两端的 CANCEL / SETTLE 会被裁掉。
    var preferred = id === 's7' ? 1.25 : 1.5;
    var k = Math.max(fit, Math.min(ZOOM_MAX, preferred));
    expand.style.width = cw + 'px';
    expand.style.height = ch + 'px';
    expand.style.left = Math.round((W - cw) / 2) + 'px';
    expand.style.top = Math.round((H - ch) / 2) + 'px';

    var box = { x: (W - cw) / 2, y: (H - ch) / 2, w: cw, h: ch };
    view = { id: id, cw: cw, ch: ch, k: k, fit: fit, panX: 0, panY: 0,
             x: box.x, y: box.y, w: box.w, h: box.h };
    var target = viewTransform(view);
    showZoom();
    state.openBlock = id;
    showHud(id);

    if (calm() || instant) {
      expand.style.transform = target;
      expand.style.opacity = '';
      fly = null;
      pushBlocks(id, false);
    } else {
      var vcx = box.x + box.w / 2;
      var vcy = box.y + box.h / 2;
      var cx = frame ? frame.x + frame.w / 2 : vcx;
      var cy = frame ? frame.y + frame.h / 2 : vcy;
      var sx = frame ? frame.w / box.w : 0.08;
      var sy = frame ? frame.h / box.h : 0.08;
      var from = 'translate(' + (cx - vcx).toFixed(2) + 'px, '
        + (cy - vcy).toFixed(2) + 'px) scale(' + sx.toFixed(4) + ', '
        + sy.toFixed(4) + ')';
      fly = expand.animate(
        [{ transform: from, opacity: 0.25 }, { transform: target, opacity: 1 }],
        { duration: FLY_IN, easing: FLY_EASE });
      fly.onfinish = function () {
        fly = null;
        expand.style.transform = target;
      };
      pushBlocks(id, true);
    }

    if (push && location.hash !== '#block-' + id) {
      history.pushState(null, '', '#block-' + id);
    }
  }

  function collapseBlock(push, instant) {
    clearSelection();
    var id = view.id;
    if (!id) {
      if (push && location.hash !== '#map') history.pushState(null, '', '#map');
      return;
    }
    var host = mapHost();
    var expand = expandOf(id);
    var frame = frameRects[id];
    var W = host ? host.clientWidth : 0;
    var H = host ? host.clientHeight : 0;
    var geometry = view;
    view = { id: null, cw: 0, ch: 0, k: 1, fit: 1, panX: 0, panY: 0 };
    state.openBlock = null;

    var finish = function () {
      if (expand) {
        expand.hidden = true;
        expand.style.transform = '';
        expand.style.opacity = '';
        expand.style.overflow = '';
      }
      restoreBlocks(false);
      if (host) {
        var edges = host.querySelector('.ob-edges');
        if (edges) {
          edges.style.opacity = '';
          edges.style.visibility = '';
          edges.style.transition = '';
        }
      }
      hideHud();
    };

    stopFly();
    if (instant || calm() || !frame || !expand) {
      finish();
    } else {
      var vcx = geometry.x + geometry.w / 2;
      var vcy = geometry.y + geometry.h / 2;
      var to = 'translate(' + ((frame.x + frame.w / 2) - vcx).toFixed(2) + 'px, '
        + ((frame.y + frame.h / 2) - vcy).toFixed(2) + 'px) scale('
        + (frame.w / geometry.w).toFixed(4) + ', '
        + (frame.h / geometry.h).toFixed(4) + ')';
      fly = expand.animate(
        [{ transform: viewTransform(geometry), opacity: 1 },
         { transform: to, opacity: 0.2 }],
        { duration: FLY_OUT, easing: FLY_EASE, fill: 'forwards' });
      fly.onfinish = finish;
      restoreBlocks(true);
      var edges = host.querySelector('.ob-edges');
      if (edges) {
        edges.style.visibility = '';
        edges.style.transition = 'opacity ' + FLY_OUT + 'ms ease-out';
        edges.style.opacity = '';
      }
    }
    if (push && location.hash !== '#map') history.pushState(null, '', '#map');
  }

  function route() {
    var match = /^#block-([a-z0-9]+)$/.exec(location.hash || '');
    if (match && expandOf(match[1])) expandBlock(match[1], false, true);
    else collapseBlock(false, true);
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
    el.op = $('ob-op');
    el.profile = $('ob-profile');
    el.current = $('ob-current');
    el.hud = $('ob-hud');
    el.hudCode = $('ob-hud-code');
    el.hudName = $('ob-hud-name');
    el.hudEn = $('ob-hud-en');
    el.hudPanel = $('ob-hud-panel');
    el.hudRaw = $('ob-hud-raw');
    el.zoomIn = $('ob-zoom-in');
    el.zoomOut = $('ob-zoom-out');
    el.zoomVal = $('ob-zoom-val');
    el.bar = document.querySelector('.ob-bar');

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

    document.querySelectorAll('.ob-expand').forEach(function (layer) {
      layer.addEventListener('pointerdown', function (event) {
        if (!view.id || event.button !== 0) return;
        if (view.k <= view.fit + 0.001) return;
        var originX = event.clientX;
        var originY = event.clientY;
        var startX = view.panX;
        var startY = view.panY;
        var node = layer;
        function move(moveEvent) {
          view.panX = startX + (moveEvent.clientX - originX);
          view.panY = startY + (moveEvent.clientY - originY);
          node.style.transform = viewTransform(view);
        }
        function stop() {
          node.removeEventListener('pointermove', move);
          node.removeEventListener('pointerup', stop);
          node.removeEventListener('pointercancel', stop);
        }
        node.setPointerCapture && node.setPointerCapture(event.pointerId);
        node.addEventListener('pointermove', move);
        node.addEventListener('pointerup', stop);
        node.addEventListener('pointercancel', stop);
        event.preventDefault();
      });
    });

    var graph = mapHost();
    if (graph) {
      graph.addEventListener('pointerdown', function (event) {
        if (event.button !== 0 || view.id) return;
        mapDrag = { x: event.clientX, y: event.clientY,
                    px: mapView.x, py: mapView.y, moved: false };
      });
      graph.addEventListener('pointermove', function (event) {
        if (!mapDrag) return;
        var dx = event.clientX - mapDrag.x;
        var dy = event.clientY - mapDrag.y;
        if (!mapDrag.moved && Math.abs(dx) + Math.abs(dy) < 5) return;
        mapDrag.moved = true;
        suppressClick = true;
        mapView.x = mapDrag.px + dx;
        mapView.y = mapDrag.py + dy;
        applyMapPan();
        graph.setAttribute('data-panning', '1');
      });
      var endDrag = function () {
        if (!mapDrag) return;
        var moved = mapDrag.moved;
        mapDrag = null;
        graph.removeAttribute('data-panning');
        if (moved) window.setTimeout(function () { suppressClick = false; }, 0);
      };
      graph.addEventListener('pointerup', endDrag);
      graph.addEventListener('pointercancel', endDrag);
      graph.addEventListener('pointerleave', endDrag);
      graph.addEventListener('wheel', function (event) {
        if (view.id) return;
        event.preventDefault();
        var rect = graph.getBoundingClientRect();
        var cx = event.clientX - rect.left;
        var cy = event.clientY - rect.top;
        var wx = (cx - mapView.x) / mapView.k;
        var wy = (cy - mapView.y) / mapView.k;
        var next = mapView.k * (event.deltaY < 0 ? 1.1 : 0.9);
        next = Math.max(0.2, Math.min(1.6, next));
        mapView.k = next;
        mapView.x = cx - wx * next;
        mapView.y = cy - wy * next;
        applyMapPan();
      }, { passive: false });
    }

    document.querySelectorAll('.ob-gnode--block').forEach(function (block) {
      block.addEventListener('click', function () {
        if (suppressClick) { suppressClick = false; return; }
        var id = block.getAttribute('data-block');
        if (view.id === id) collapseBlock(true);
        else expandBlock(id, true);
      });
    });
    document.querySelectorAll('[data-back]').forEach(function (button) {
      button.addEventListener('click', function () { collapseBlock(true); });
    });
    if (el.zoomIn) el.zoomIn.addEventListener('click', function () { setZoom(view.k * ZOOM_STEP); });
    if (el.zoomOut) el.zoomOut.addEventListener('click', function () { setZoom(view.k / ZOOM_STEP); });

    if (el.hudRaw) {
      el.hudRaw.addEventListener('click', function () {
        if (!el.hudPanel) return;
        var open = el.hudPanel.hidden;
        el.hudPanel.hidden = !open;
        el.hudRaw.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
    }
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && view.id) collapseBlock(true);
    });
    window.addEventListener('hashchange', route);
    window.addEventListener('resize', function () {
      window.requestAnimationFrame(function () {
        syncTop();
        collapseBlock(false, true);
        layoutMap();
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
          state.graphs['expand-' + block.id] = { nodes: block.nodes, edges: block.edges };
        });
        fill();
        derive();
        layoutMap();
        syncTop();
        if (document.fonts && document.fonts.ready) {
          document.fonts.ready.then(function () { layoutMap(); });
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
