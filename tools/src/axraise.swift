// axraise —— 把标题匹配的窗口提到最前（需要「辅助功能」权限）
// 用法: axraise <标题关键字>
// 输出: raised <windowId> / not found

import Cocoa

let argv = CommandLine.arguments
guard argv.count >= 2 else {
    FileHandle.standardError.write("usage: axraise <title-key>\n".data(using: .utf8)!)
    exit(2)
}
let key = argv[1]

guard AXIsProcessTrusted() else {
    FileHandle.standardError.write("need accessibility permission\n".data(using: .utf8)!)
    exit(3)
}

// 1) 先从 CGWindowList 找到匹配窗口，拿到 owner PID
var targetPid: pid_t = 0
var targetId = 0
if let list = CGWindowListCopyWindowInfo(
    [.optionOnScreenOnly, .excludeDesktopElements], kCGNullWindowID
) as? [[String: Any]] {
    for w in list {
        let owner = w[kCGWindowOwnerName as String] as? String ?? ""
        let title = w[kCGWindowName as String] as? String ?? ""
        guard (owner + title).contains(key) else { continue }
        targetPid = w[kCGWindowOwnerPID as String] as? pid_t ?? 0
        targetId = w[kCGWindowNumber as String] as? Int ?? 0
        break
    }
}

guard targetPid != 0 else {
    print("not found")
    exit(1)
}

// 2) AX 里找到该窗口并 raise
let app = AXUIElementCreateApplication(targetPid)
var winsRef: CFTypeRef?
guard AXUIElementCopyAttributeValue(app, kAXWindowsAttribute as CFString, &winsRef) == .success,
      let wins = winsRef as? [AXUIElement] else {
    print("no windows")
    exit(1)
}

var raised = false
for win in wins {
    var titleRef: CFTypeRef?
    AXUIElementCopyAttributeValue(win, kAXTitleAttribute as CFString, &titleRef)
    let title = titleRef as? String ?? ""
    var roleRef: CFTypeRef?
    AXUIElementCopyAttributeValue(win, kAXRoleAttribute as CFString, &roleRef)
    if roleRef as? String != kAXWindowRole as String { continue }
    if !title.contains(key) && !key.isEmpty && wins.count > 1 { continue }

    AXUIElementPerformAction(win, kAXRaiseAction as CFString)
    AXUIElementSetAttributeValue(win, kAXMainAttribute as CFString, kCFBooleanTrue)
    raised = true
    break
}

// 3) 激活应用本身（没有这步，窗口在前台但接收不到键盘/鼠标焦点）
if let running = NSRunningApplication(processIdentifier: targetPid) {
    running.activate(options: [.activateIgnoringOtherApps])
}

print(raised ? "raised \(targetId)" : "ax failed")
usleep(400_000)
