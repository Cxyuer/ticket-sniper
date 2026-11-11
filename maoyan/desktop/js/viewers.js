// 订单确认页：实名观演人列表
//
// 实测结构（2026-11-11）：
//   div.wrapper__list > div.wrapper__item            每个观演人一项
//     .wrapper__item__name        名字（可能带「默认」标记）
//     .wrapper__item__id          身份证（脱敏）
//  已选中的项有 class 修饰符 `wrapper__item--selected`
//
// 用法: evaluate --expression-file viewers.js
// 返回: {count, need, selected:[names], items:[{index,name,selected}]}
(function () {
  var list = document.querySelector('.wrapper__list');
  var items = [], selected = [];
  var nodes = document.querySelectorAll('.wrapper__item');

  for (var i = 0; i < nodes.length; i++) {
    var el = nodes[i];
    var cls = (typeof el.className === 'string') ? el.className : '';
    var nameEl = el.querySelector('.wrapper__item__name');
    // 名字里可能混着「默认」徽标，取第一段文本即可
    var raw = ((nameEl && nameEl.innerText) || el.innerText || '')
      .replace(/\s+/g, ' ').trim();
    var name = raw.split(' ')[0].replace(/^\*/, '');
    var isSel = /item--selected/.test(cls);
    items.push({ index: i, name: name, selected: isSel });
    if (isSel) selected.push(name);
  }

  // 顶部提示「已选1张票，需选择 1 位实名制观演人」
  var need = null;
  var m = (document.body.innerText || '').match(/需选择\s*(\d+)\s*位/);
  if (m) need = parseInt(m[1], 10);

  return JSON.stringify({
    found: items.length > 0,
    hasList: !!list,
    count: items.length,
    need: need,
    selected: selected,
    items: items
  });
})();
