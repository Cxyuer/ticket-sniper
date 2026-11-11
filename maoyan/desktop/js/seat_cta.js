// 座位页底部 CTA 探测器
//
// 实测结构（猫眼演出座位页）:
//   未选座: <div class="btn opc40">请选择座位</div>   ← opc40 = 禁用(opacity .4)
//   已选座: <div class="btn">提交</div>                ← 去掉 opc40 = 可提交
//
// 所以「能不能锁座」不用看文案，看 class 有没有 opc40 最可靠。
//
// 用法: evaluate --expression-file seat_cta.js
// 返回: {found, text, enabled, cls, x, y}
(function () {
  var vw = window.innerWidth, vh = window.innerHeight;
  var nodes = document.querySelectorAll('div, button, a');
  var best = null;

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var cls = (typeof el.className === 'string') ? el.className : '';
    if (!/btn/i.test(cls)) continue;

    var r = el.getBoundingClientRect();
    if (r.width < 90 || r.height < 30) continue;      // CTA 是底部大块
    if (r.y < vh * 0.70) continue;                    // 只要底部
    if (r.x < 0 || r.y > vh) continue;

    var st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;

    var txt = (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
    var disabled = /opc40|opc50|opc30|disabled/i.test(cls) ||
                   parseFloat(st.opacity) < 0.6 ||
                   el.getAttribute('aria-disabled') === 'true';

    var item = {
      text: txt.slice(0, 12),
      cls: cls.slice(0, 40),
      enabled: !disabled,
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      w: Math.round(r.width),
      bottom: Math.round(r.bottom)
    };

    // 取最靠下、最宽的那个
    if (!best || item.bottom > best.bottom ||
        (item.bottom === best.bottom && item.w > best.w)) {
      best = item;
    }
  }

  return JSON.stringify({ found: !!best, best: best });
})();
