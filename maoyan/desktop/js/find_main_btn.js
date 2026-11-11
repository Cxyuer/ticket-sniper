// 定位页面底部主按钮（白名单版）
//
// 为什么不用「最靠下就是主按钮」：售罄时底部是「缺货登记」「想看」，
// 点错了就变成登记缺货，抢票直接失败还留下记录。
//
// 由 Python 侧注入:
//   window.__TS_ALLOW = ["选座购票","立即购买",...]   // 只允许点这些
//   window.__TS_DENY  = ["缺货登记","想看",...]        // 出现这些一律不点
//
// 用法: evaluate --expression-file find_main_btn.js
// 返回: {found, best:{text,x,y,w,h}, candidates:[...], blocked:[...]}
(function () {
  var ALLOW = window.__TS_ALLOW || [];
  var DENY = window.__TS_DENY ||
             ['缺货登记', '想看', '取消', '返回', '关闭', '删除', '放弃',
              '退出', '暂不', '售罄', '候补'];

  function hit(text, words) {
    for (var i = 0; i < words.length; i++) {
      if (words[i] && text.indexOf(words[i]) >= 0) return words[i];
    }
    return null;
  }

  var nodes = document.querySelectorAll('div, button, a, span');
  var okList = [], blocked = [];
  var vw = window.innerWidth, vh = window.innerHeight;

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var cls = (typeof el.className === 'string') ? el.className : '';
    var txt = (el.innerText || el.textContent || '').replace(/\s+/g, '').trim();
    if (!txt || txt.length > 14) continue;              // 按钮文案都很短

    var r = el.getBoundingClientRect();
    if (r.width < 70 || r.height < 26) continue;
    if (r.width > vw * 0.98) continue;
    if (r.y < vh * 0.45) continue;                      // 只看下半屏
    if (r.x < 0 || r.y < 0 || r.x > vw || r.y > vh) continue;

    var st = window.getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    if (parseFloat(st.opacity) < 0.5) continue;
    if (st.pointerEvents === 'none') continue;

    var item = {
      text: txt.slice(0, 16),
      cls: cls.slice(0, 40),
      x: Math.round(r.x + r.width / 2),
      y: Math.round(r.y + r.height / 2),
      w: Math.round(r.width),
      h: Math.round(r.height),
      bottom: Math.round(r.bottom),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true' ||
                /disabled|opc40|opc50|opc30/i.test(cls)
    };

    if (item.disabled) { blocked.push(item); continue; }

    // 黑名单优先（「缺货登记」里也有「登记」，白名单匹配前必须先拦）
    var bad = hit(txt, DENY);
    if (bad) { item.reason = 'deny:' + bad; blocked.push(item); continue; }

    if (ALLOW.length) {
      var good = hit(txt, ALLOW);
      if (!good) { item.reason = 'not-allowed'; blocked.push(item); continue; }
      item.matched = good;
    }

    okList.push(item);
  }

  // 越靠下越优先；同高度取靠右（主 CTA 通常在右）
  okList.sort(function (a, b) {
    if (b.bottom !== a.bottom) return b.bottom - a.bottom;
    return b.x - a.x;
  });

  // 去重（父子元素常出现相同文案）
  var seen = {}, uniq = [];
  for (var j = 0; j < okList.length; j++) {
    var key = okList[j].text + '@' + okList[j].bottom;
    if (seen[key]) continue;
    seen[key] = 1;
    uniq.push(okList[j]);
  }

  return JSON.stringify({
    found: uniq.length > 0,
    best: uniq[0] || null,
    candidates: uniq.slice(0, 5),
    blocked: blocked.slice(0, 8)
  });
})();
