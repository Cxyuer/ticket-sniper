// 猫眼座位盲选器 —— 通用探测「可选座位/区域」
// 不依赖固定 DOM 结构: 遍历 SVG 内所有形状元素, 按 fill 颜色判断是否可选
// 用法: evaluate --expression-file seat_pick.js
// 返回: {count, picks:[{x,y,tag,fill}]}  可售元素坐标(屏幕坐标)
//
// 判定: 灰色(rgb(2xx,2xx,2xx)) = 不可选
//       彩色(高饱和) = 可选
//       尺寸 6~60px 的小元素 = 座位级; >60px = 区域级
(function () {
  function toRgb(fill) {
    var m = fill.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (m) return [+m[1], +m[2], +m[3]];
    var h = fill.replace('#', '');
    if (h.length === 3) h = h[0]+h[0]+h[1]+h[1]+h[2]+h[2];
    if (h.length === 6) return [parseInt(h.substr(0,2),16), parseInt(h.substr(2,2),16), parseInt(h.substr(4,2),16)];
    return null;
  }

  // 黑白灰一律排除: 这些是 UI 元素/售罄/背景, 不含可售座位
  function isNeutral(fill) {
    var c = toRgb(fill);
    if (!c) return true;
    var r = c[0], g = c[1], b = c[2];
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    if (mx < 25) return true;                 // 纯黑
    if (mn > 240) return true;                // 纯白
    if (mx - mn < 26) return true;            // 灰(三通道接近)
    return false;
  }

  var cands = [];
  var tags = ['path', 'circle', 'rect', 'polygon', 'ellipse'];
  tags.forEach(function (tag) {
    var nodes = document.querySelectorAll('svg ' + tag);
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var st = el.getAttribute('style') || '';
      var fm = st.match(/fill:\s*([^;]+)/);
      var fill = fm ? fm[1].trim() : (el.getAttribute('fill') || '');
      if (!fill) continue;
      if (/transparent|none/i.test(fill)) continue;
      if (isNeutral(fill)) continue;

      var r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6) continue;
      if (r.width > 900 || r.height > 900) continue;   // 排除背景大块
      if (r.x < 0 || r.y < 0) continue;
      if (r.x > window.innerWidth || r.y > window.innerHeight) continue;

      var pe = window.getComputedStyle(el).pointerEvents;
      if (pe === 'none') continue;

      cands.push({
        tag: tag,
        id: el.getAttribute('id') || '',
        x: Math.round(r.x + r.width / 2),
        y: Math.round(r.y + r.height / 2),
        w: Math.round(r.width),
        h: Math.round(r.height),
        fill: fill,
        level: (r.width <= 60 && r.height <= 60) ? 'seat' : 'area'
      });
    }
  });

  // 优先选靠近屏幕中心的, 通常观感更好
  var cx = window.innerWidth / 2, cy = window.innerHeight / 2;
  cands.sort(function (a, b) {
    var da = Math.abs(a.x - cx) + Math.abs(a.y - cy);
    var db = Math.abs(b.x - cx) + Math.abs(b.y - cy);
    return da - db;
  });

  var seats = cands.filter(function (c) { return c.level === 'seat'; });
  var areas = cands.filter(function (c) { return c.level === 'area'; });

  return JSON.stringify({
    count: cands.length,
    seatCount: seats.length,
    areaCount: areas.length,
    best: (seats[0] || areas[0] || null),
    picks: cands.slice(0, 6)
  });
})();
