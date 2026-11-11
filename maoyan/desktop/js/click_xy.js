// 在指定屏幕坐标上派发真实鼠标事件序列
// 用于「再点同一个位置」的二次确认(按钮 DOM 可能变化, 靠坐标最稳)
// 用法: 由 Python 拼进 expression, 坐标写在 __X__ / __Y__ 占位
//   最终形如: (function(){var X=123,Y=456; ...})()
(function () {
  var X = window.__TS_X, Y = window.__TS_Y;
  if (typeof X !== 'number' || typeof Y !== 'number') {
    return JSON.stringify({ ok: false, err: 'no coords' });
  }
  var el = document.elementFromPoint(X, Y);
  if (!el) return JSON.stringify({ ok: false, err: 'no element at ' + X + ',' + Y });

  var opts = {
    bubbles: true, cancelable: true, composed: true,
    clientX: X, clientY: Y,
    view: window, button: 0, buttons: 1
  };
  var seq = ['pointerdown', 'mousedown', 'pointerup', 'mouseup', 'click'];
  var fired = [];
  for (var i = 0; i < seq.length; i++) {
    var t = seq[i];
    var Ev = (t.indexOf('pointer') === 0 && window.PointerEvent) ? PointerEvent : MouseEvent;
    try {
      el.dispatchEvent(new Ev(t, opts));
      fired.push(t);
    } catch (e) { /* 某些类型不支持就跳过 */ }
  }

  var txt = (el.innerText || el.textContent || '').replace(/\s+/g, '').slice(0, 20);
  return JSON.stringify({
    ok: true,
    tag: el.tagName,
    cls: (typeof el.className === 'string' ? el.className : '').slice(0, 40),
    text: txt,
    fired: fired
  });
})();
