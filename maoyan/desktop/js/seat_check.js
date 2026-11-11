// 猫眼演出座位图检测器
// 用途: 判断座位图里是否有可售区域(非灰色), 返回可点击坐标
// 用法: evaluate --expression-file seat_check.js
// 返回: {total, available:[{id,x,y,w,h,fill}], soldOut:true|false}
//
// 原理: 售罄区域 fill 为 rgb(245,245,245) 灰色
//       放票后可售区域会变成品牌色(高饱和), 据此判断
(function () {
  var GREY = /rgb\(\s*24[0-9]\s*,\s*24[0-9]\s*,\s*24[0-9]\s*\)/;
  var paths = [].slice.call(document.querySelectorAll('svg path'));
  if (!paths.length) {
    return JSON.stringify({ total: 0, available: [], soldOut: null,
                            note: 'no svg path - 可能未加载完成或不是座位页' });
  }

  var avail = [];
  paths.forEach(function (p) {
    var st = p.getAttribute('style') || '';
    var m = st.match(/fill:\s*([^;]+)/);
    var fill = m ? m[1].trim() : '';
    if (!fill) return;
    // 灰色 = 售罄; 其他颜色 = 可能可售
    if (GREY.test(fill)) return;
    // 排除纯白/透明
    if (/rgba?\(\s*255\s*,\s*255\s*,\s*255/.test(fill)) return;
    if (/transparent|none/.test(fill)) return;

    var r = p.getBoundingClientRect();
    if (r.width < 8 || r.height < 8) return;
    avail.push({
      id: p.getAttribute('id') || '',
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      w: Math.round(r.width),
      h: Math.round(r.height),
      fill: fill
    });
  });

  return JSON.stringify({
    total: paths.length,
    availableCount: avail.length,
    soldOut: avail.length === 0,
    available: avail.slice(0, 8)
  });
})();
