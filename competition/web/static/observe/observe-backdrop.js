/* 背景：一层从左往右行进的 ASCII 字符场。
 *
 * 只画氛围，不碰数据：所有字符来自固定字母表。每格有一个弹簧状态，
 * 被一条向右传播的正弦波牵引（相位 x*k - t*w，波峰沿 x 增大方向走），
 * 欠阻尼所以会过冲回弹；亮度取行波本身，平滑地扫过去，上下位移取弹簧
 * 的当前位置，两处叠加出从左向右的弹性起伏。
 *
 * 每格字符一经确定就不再改变：只有亮度与位置在动，字符集合本身是静的。
 * 蓝白两色，白色只占少数。模拟按 60Hz 定步长跑，绘制压到 30fps；暗格
 * 仍然绘制，只是透明度很低，保证背景是连续的字符面。
 *
 * 中央的斜体 ZJJ 不是用 destination-out 一刀挖掉的：先画一张带高斯模糊
 * 的字形遮罩，每格按遮罩覆盖率把自己的透明度乘下去，字缘的字符因此是
 * 慢慢淡出、自然让出字形的，而不是被硬边裁切。用户要求减少动态时只画
 * 一帧静止画面。 */
(function () {
  'use strict';

  var canvas = document.getElementById('ob-bg');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  if (!ctx) return;

  var GLYPHS = '0123456789ABCDEF0123456789abcdef<>[]{}()/\\|;:*+-=$#@%&|~^'.split('');
  var BLUE = '86, 146, 214';
  var WHITE = '219, 234, 255';
  var CELL_W = 15;
  var CELL_H = 19;
  var FONT = 13;
  var DPR_MAX = 1.5;

  // 行波：波峰以 SPEED / WAVE_X ≈ 60px/s 向右走，波长约 330px。
  var WAVE_X = 0.019;
  var WAVE_Y = 0.0045;
  var SPEED = 0.00115;
  // 欠阻尼弹簧（ζ≈0.79），波峰附近会有一次明显的回弹。
  var SPRING_K = 40;
  var SPRING_C = 10;
  // 左右海浪：每格水平位移追一个行间错相的正弦，弹簧软一些，回弹更明显。
  var SWAY_K = 26;
  var SWAY_C = 6.2;
  var SWAY_W = 0.0055;
  var SWAY_H = 0.058;

  var FIXED = 1000 / 60;
  var PAINT_EVERY = 1000 / 30;

  var calm = window.matchMedia('(prefers-reduced-motion: reduce)');

  // 背景中间镂空成斜体 ZJJ：字形先渲染成一张模糊遮罩，字符按覆盖率淡出。
  var STENCIL = 'ZJJ';
  var stencilSize = 0;
  var mask = null;
  var maskW = 0;
  var maskH = 0;
  var maskDpr = 1;

  var cells = [];
  var cols = 0;
  var rows = 0;
  var width = 0;
  var height = 0;
  var time = 0;
  var raf = 0;
  var lastFrame = 0;
  var lastPaint = 0;
  var acc = 0;

  function hash(x, y) {
    var n = Math.sin(x * 127.1 + y * 311.7) * 43758.5453;
    return n - Math.floor(n);
  }

  function buildMask(dpr) {
    mask = null;
    var off = document.createElement('canvas');
    off.width = canvas.width;
    off.height = canvas.height;
    var g = off.getContext('2d');
    if (!g) return;
    maskDpr = dpr;
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = '#fff';
    g.textAlign = 'center';
    g.textBaseline = 'middle';
    if ('filter' in g) {
      g.filter = 'blur(6px)';
    }
    g.font = 'italic 800 ' + stencilSize
      + 'px "Helvetica Neue", Helvetica, Arial, sans-serif';
    g.fillText(STENCIL, width / 2, height / 2);
    maskW = off.width;
    maskH = off.height;
    mask = g.getImageData(0, 0, maskW, maskH).data;
  }

  function coverAt(cx, cy) {
    if (!mask) return 0;
    var mx = Math.round(cx * maskDpr);
    var my = Math.round(cy * maskDpr);
    if (mx < 0 || my < 0 || mx >= maskW || my >= maskH) return 0;
    return mask[(my * maskW + mx) * 4 + 3] / 255;
  }

  function build() {
    width = canvas.clientWidth || window.innerWidth;
    height = canvas.clientHeight || window.innerHeight;
    var dpr = Math.min(window.devicePixelRatio || 1, DPR_MAX);
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    stencilSize = Math.min(width * 0.4, height * 0.72);
    buildMask(dpr);

    cols = Math.ceil(width / CELL_W) + 1;
    rows = Math.ceil(height / CELL_H) + 1;
    cells = new Array(cols * rows);

    for (var y = 0; y < rows; y += 1) {
      for (var x = 0; x < cols; x += 1) {
        var r = hash(x, y);
        // 每格给一点相位偏移，波面不是尺子画出来的直线。
        var phase = r * Math.PI * 2 * 0.12;
        cells[y * cols + x] = {
          gi: Math.floor(r * GLYPHS.length),
          white: hash(x + 41, y + 17) > 0.8,
          phase: phase,
          lit: Math.sin(x * WAVE_X + y * WAVE_Y + phase),
          pos: 0,
          vel: 0,
          sx: 0,
          svx: 0,
          cover: coverAt(x * CELL_W + CELL_W / 2, y * CELL_H + CELL_H / 2)
        };
      }
    }
  }

  // 一个固定步长：每格朝行波目标靠，速度累积后产生过冲。
  function simulate(dt) {
    for (var y = 0; y < rows; y += 1) {
      for (var x = 0; x < cols; x += 1) {
        var cell = cells[y * cols + x];
        var target = Math.sin(x * WAVE_X + y * WAVE_Y - time * SPEED + cell.phase);
        cell.lit = target;
        var force = (target - cell.pos) * SPRING_K - cell.vel * SPRING_C;
        cell.vel += force * dt;
        cell.pos += cell.vel * dt;

        // 海浪：亮带处摆幅更大，行与行相位错开，整片像水面一样左右缓移。
        var amp = 1.3 + (target + 1) * 1.7;
        var sway = Math.sin(y * SWAY_H + x * SWAY_W - time * 0.0011 + cell.phase) * amp;
        var spring = (sway - cell.sx) * SWAY_K - cell.svx * SWAY_C;
        cell.svx += spring * dt;
        cell.sx += cell.svx * dt;
      }
    }
    time += dt * 1000;
  }

  function paint() {
    ctx.clearRect(0, 0, width, height);
    ctx.font = '500 ' + FONT + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    var blue = 'rgba(' + BLUE + ', 1)';
    var white = 'rgba(' + WHITE + ', 1)';

    for (var y = 0; y < rows; y += 1) {
      var py = y * CELL_H + CELL_H / 2;
      for (var x = 0; x < cols; x += 1) {
        var cell = cells[y * cols + x];
        var lit = (cell.lit + 1) * 0.5;
        var alpha = (0.07 + lit * lit * 0.26) * (1 - cell.cover);
        if (alpha < 0.01) continue;

        var offset = cell.pos * 2.1;
        ctx.globalAlpha = alpha;
        ctx.fillStyle = cell.white ? white : blue;
        ctx.fillText(GLYPHS[cell.gi],
                     x * CELL_W + CELL_W / 2 + cell.sx, py + offset);
      }
    }

    ctx.globalAlpha = 1;
  }

  function frame(now) {
    raf = window.requestAnimationFrame(frame);
    if (!lastFrame) lastFrame = now;
    acc += Math.min(now - lastFrame, 200);
    lastFrame = now;

    var steps = 0;
    while (acc >= FIXED && steps < 8) {
      simulate(FIXED / 1000);
      acc -= FIXED;
      steps += 1;
    }
    if (steps && now - lastPaint >= PAINT_EVERY) {
      lastPaint = now;
      paint();
    }
  }

  function stop() {
    if (raf) window.cancelAnimationFrame(raf);
    raf = 0;
    lastFrame = 0;
    acc = 0;
  }

  function start() {
    stop();
    build();
    if (calm.matches) {
      paint();
      return;
    }
    if (document.hidden) return;
    lastPaint = 0;
    raf = window.requestAnimationFrame(frame);
  }

  var timer = 0;
  window.addEventListener('resize', function () {
    window.clearTimeout(timer);
    timer = window.setTimeout(start, 180);
  });

  document.addEventListener('visibilitychange', function () {
    if (document.hidden) stop();
    else start();
  });

  if (calm.addEventListener) {
    calm.addEventListener('change', start);
  } else if (calm.addListener) {
    calm.addListener(start);
  }

  start();
})();
