// 座位图探测器（canvas 版）
//
// 为什么需要它：猫眼的座位图有两套实现
//   概览层: <svg><path>  区域块，能直接读 fill
//   钻入后: <canvas> 分块 + #sdk-seat-container 接收事件，座位画在像素里
// 所以钻入区域后读不到任何 DOM 元素，只能读 canvas 像素。
//
// 用法: evaluate --expression-file seat_grid.js
// 返回: {found, count, container:{x,y,w,h}, seats:[{ox,oy,fill}]}
//   ox/oy 是相对 #sdk-seat-container 的坐标，直接喂给 CDP 的 --position-x/y
//
// 判定可售：饱和度高（>=0.35）的彩色像素；白/灰 = 已售或背景
// 顶部 80px 要跳过，那里是票档图例，不是座位
(function () {
  var cont = document.querySelector('#sdk-seat-container');
  if (!cont) return JSON.stringify({ found: false, count: 0, seats: [] });

  var cb = cont.getBoundingClientRect();
  var SKIP_TOP = 80;          // 跳过高德图例区域
  var cells = document.querySelectorAll('canvas');

  function sat(r, g, b) {
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b);
    return mx === 0 ? 0 : (mx - mn) / mx;
  }
  function hex(r, g, b) {
    return '#' + [r, g, b].map(function (v) {
      return ('0' + Math.round(v).toString(16)).slice(-2);
    }).join('');
  }

  var raw = [];
  for (var i = 0; i < cells.length; i++) {
    var c = cells[i];
    var b = c.getBoundingClientRect();
    if (b.width < 10 || b.height < 10) continue;
    if (b.bottom < cb.top + SKIP_TOP || b.top > cb.bottom) continue;

    var ctx = c.getContext('2d');
    if (!ctx) continue;
    var W = c.width, H = c.height, d;
    try { d = ctx.getImageData(0, 0, W, H).data; } catch (e) { continue; }

    var sx = b.width / W, sy = b.height / H;
    for (var y = 2; y < H - 2; y += 6) {
      for (var x = 2; x < W - 2; x += 6) {
        var k = (y * W + x) * 4;
        var R = d[k], G = d[k + 1], B = d[k + 2], A = d[k + 3];
        if (A < 180) continue;                       // 透明
        if (R > 245 && G > 245 && B > 245) continue;  // 白 = 已售
        if (sat(R, G, B) < 0.35) continue;           // 灰

        var cx = b.left + x * sx, cy = b.top + y * sy;
        if (cy < cb.top + SKIP_TOP || cy > cb.bottom - 8) continue;
        if (cx < 2 || cx > window.innerWidth - 2) continue;

        raw.push({ ox: Math.round(cx - cb.left), oy: Math.round(cy - cb.top),
                   fill: hex(R, G, B) });
      }
    }
  }

  // 同一颗座位会被多个采样点命中，按 20px 网格去重
  var seen = {}, uniq = [];
  for (var j = 0; j < raw.length; j++) {
    var s = raw[j];
    var key = Math.round(s.ox / 20) + ',' + Math.round(s.oy / 20);
    if (seen[key]) continue;
    seen[key] = 1;
    uniq.push(s);
  }

  return JSON.stringify({
    found: true,
    count: uniq.length,
    container: { x: Math.round(cb.left), y: Math.round(cb.top),
                 w: Math.round(cb.width), h: Math.round(cb.height) },
    seats: uniq.slice(0, 400)
  });
})();
