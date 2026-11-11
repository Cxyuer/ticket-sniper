// winlist —— 列出屏幕上的窗口
// 输出: <windowId>|<ownerApp>|<windowTitle>|<x>,<y>,<w>x<h>
// 编译: swiftc -O winlist.swift -o ../winlist   （见 tools/README）

import Cocoa

guard let list = CGWindowListCopyWindowInfo(
    [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
) as? [[String: Any]] else {
    exit(1)
}

for w in list {
    guard let bounds = w[kCGWindowBounds as String] as? [String: Any],
          let owner = w[kCGWindowOwnerName as String] as? String else { continue }
    let layer = w[kCGWindowLayer as String] as? Int ?? 0
    if layer != 0 { continue }                       // 只看普通应用窗口
    let id = w[kCGWindowNumber as String] as? Int ?? 0

    let x = bounds["X"] as? Double ?? 0
    let y = bounds["Y"] as? Double ?? 0
    let width = bounds["Width"] as? Double ?? 0
    let height = bounds["Height"] as? Double ?? 0
    if width < 80 || height < 80 { continue }        // 跳过特效窗/工具条

    let title = w[kCGWindowName as String] as? String ?? ""
    print("\(id)|\(owner)|\(title)|\(Int(x)),\(Int(y)),\(Int(width))x\(Int(height))")
}
