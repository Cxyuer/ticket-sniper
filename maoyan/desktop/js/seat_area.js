// 猫眼座位图探测器 v2（带票档分组）
//
// 输出两种用途的数据:
//   1) available —— 当前可售的区域/座位，供抢票决策
//   2) allAreas  —— 全量区域(名称/颜色/坐标)，供「同票档扩围」和刷新后重新定位
//
// 票档线索: 同一票档的区域在有票时会用同一种 fill 颜色，所以
//   colorGroups 的每个 key（颜色）≈ 一个票档。售罄时全是灰色，学不到，
//   由 Python 侧用名称前缀兜底。
//
// 用法: evaluate --expression-file seat_area.js
// 返回: {total, availableCount, soldOut, available[], allAreas[], areaNames[], colorGroups{}}
(function () {
  function toRgb(fill) {
    if (!fill) return null;
    var m = fill.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
    if (m) return [+m[1], +m[2], +m[3]];
    var h = fill.replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    if (h.length === 6) {
      return [parseInt(h.substr(0, 2), 16),
              parseInt(h.substr(2, 2), 16),
              parseInt(h.substr(4, 2), 16)];
    }
    return null;
  }

  // 颜色归一化成 #rrggbb，作为「票档」的分组 key
  function normFill(fill) {
    var c = toRgb(fill);
    if (!c) return '';
    return '#' + c.map(function (v) {
      return ('0' + Math.round(v).toString(16)).slice(-2);
    }).join('');
  }

  // 黑/白/灰 = 无彩色, 不是可售
  function isNeutral(fill) {
    var c = toRgb(fill);
    if (!c) return true;
    var r = c[0], g = c[1], b = c[2];
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    if (mx < 25) return true;          // 纯黑(UI/文字)
    if (mn > 240) return true;         // 纯白
    if (mx - mn < 26) return true;     // 灰(售罄/背景)
    return false;
  }

  // 1) 区域名文字
  var labels = [];
  var texts = document.querySelectorAll('svg text');
  for (var i = 0; i < texts.length; i++) {
    var t = texts[i];
    var name = (t.textContent || '').replace(/\s+/g, '').trim();
    if (!name || name.length > 12) continue;
    var tr = t.getBoundingClientRect();
    if (tr.width < 2 || tr.height < 2) continue;
    labels.push({
      name: name,
      cx: tr.left + tr.width / 2,
      cy: tr.top + tr.height / 2
    });
  }

  // 2) 遍历区域 path，把「名字中心落在哪个 path 内」当作归属
  var paths = document.querySelectorAll('svg path');
  var areas = [];
  var seen = {};

  for (var j = 0; j < paths.length; j++) {
    var p = paths[j];
    var st = p.getAttribute('style') || '';
    var fm = st.match(/fill:\s*([^;]+)/);
    var fill = fm ? fm[1].trim() : (p.getAttribute('fill') || '');
    if (!fill) continue;
    if (/transparent|none/i.test(fill)) continue;

    var r = p.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;   // 缩放后区域可能很小，不能按固定 8px 砍
    if (r.width > 1200 || r.height > 1200) continue;   // 排除背景

    // 归属判定: 优先取中心距该区域中心最近的文字
    var owner = null, bestD = Infinity;
    var ax = r.left + r.width / 2, ay = r.top + r.height / 2;
    for (var k = 0; k < labels.length; k++) {
      var L = labels[k];
      if (L.cx < r.left || L.cx > r.right) continue;
      if (L.cy < r.top || L.cy > r.bottom) continue;
      var d = Math.abs(L.cx - ax) + Math.abs(L.cy - ay);
      if (d < bestD) { bestD = d; owner = L; }
    }

    var name = owner ? owner.name : '';
    var key = name || p.getAttribute('id') || ('#' + j);
    if (seen[key]) continue;
    seen[key] = 1;

    areas.push({
      id: p.getAttribute('id') || '',
      name: name,
      x: Math.round(ax),
      y: Math.round(ay),
      w: Math.round(r.width),
      h: Math.round(r.height),
      fill: normFill(fill),
      available: !isNeutral(fill)
    });
  }

  // 区域块尺寸的中位数：地图可缩放，绝对像素不可靠，用它当基准
  var namedSizes = areas.filter(function (a) { return a.name; })
                        .map(function (a) { return Math.max(a.w, a.h); })
                        .sort(function (a, b) { return a - b; });
  var medianSize = namedSizes.length
    ? namedSizes[Math.floor(namedSizes.length / 2)] : 0;

  var avail = areas.filter(function (a) { return a.available && a.name; });
  var names = [];
  var colorGroups = {};
  for (var m = 0; m < areas.length; m++) {
    var a = areas[m];
    if (a.name && names.indexOf(a.name) < 0) names.push(a.name);
    if (a.available && a.name) {
      (colorGroups[a.fill] = colorGroups[a.fill] || []).push(a.name);
    }
  }

  return JSON.stringify({
    total: areas.length,
    availableCount: avail.length,
    soldOut: avail.length === 0,
    available: avail,
    allAreas: areas,
    areaNames: names,
    medianSize: medianSize,
    colorGroups: colorGroups
  });
})();
