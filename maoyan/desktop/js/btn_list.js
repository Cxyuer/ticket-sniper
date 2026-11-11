// 页面按钮探测器 —— 列出所有可点击按钮的文本与定位方式
// 用于自动提交订单: 按文本优先级点击「确定/下一步/提交订单/去支付」
// 用法: evaluate --expression-file btn_list.js
// 返回: {count, buttons:[{text, tag, id, cls, x, y}]}
(function () {
  var SEL = 'button, [role=button], div[class*=btn], div[class*=button], a';
  var nodes = document.querySelectorAll(SEL);
  var out = [];
  var seen = {};

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var txt = (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
    if (!txt || txt.length > 14) continue;          // 排除长文本(说明文字)
    if (!el.offsetParent && el.offsetWidth === 0) continue;   // 不可见

    // 只要最内层按钮, 避免重复
    var key = txt;
    if (seen[key]) continue;

    var r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 16) continue;

    var st = window.getComputedStyle(el);
    if (st.pointerEvents === 'none' || st.display === 'none') continue;
    if (st.visibility === 'hidden') continue;
    // 排除禁用态
    var disabled = el.disabled ||
                   el.getAttribute('aria-disabled') === 'true' ||
                   /disable/i.test(el.className || '');

    seen[key] = 1;
    out.push({
      text: txt,
      tag: el.tagName,
      id: el.id || '',
      cls: (typeof el.className === 'string' ? el.className : '').slice(0, 50),
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      disabled: !!disabled
    });
  }
  return JSON.stringify({ count: out.length, buttons: out });
})();
