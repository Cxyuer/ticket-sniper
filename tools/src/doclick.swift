// doclick —— 在屏幕绝对坐标点击一次（需要「辅助功能」权限）
// 用法: doclick <x> <y> [clicks]

import Cocoa

let argv = CommandLine.arguments
guard argv.count >= 3,
      let x = Double(argv[1]), let y = Double(argv[2]) else {
    FileHandle.standardError.write("usage: doclick <x> <y> [clicks]\n".data(using: .utf8)!)
    exit(2)
}
let clicks = argv.count >= 4 ? (Int(argv[3]) ?? 1) : 1

guard AXIsProcessTrusted() else {
    FileHandle.standardError.write("need accessibility permission\n".data(using: .utf8)!)
    exit(3)
}

let pt = CGPoint(x: x, y: y)
let src = CGEventSource(stateID: .hidSystemState)

// 先移动再按下抬起，避免部分应用忽略纯点击事件
if let move = CGEvent(mouseEventSource: src, mouseType: .mouseMoved,
                      mouseCursorPosition: pt, mouseButton: .left) {
    move.post(tap: .cghidEventTap)
    usleep(60_000)
}

for i in 0..<clicks {
    let downType: CGEventType = .leftMouseDown
    let upType: CGEventType = .leftMouseUp
    if let down = CGEvent(mouseEventSource: src, mouseType: downType,
                          mouseCursorPosition: pt, mouseButton: .left) {
        down.setIntegerValueField(.mouseEventClickState, value: Int64(i + 1))
        down.post(tap: .cghidEventTap)
    }
    usleep(40_000)
    if let up = CGEvent(mouseEventSource: src, mouseType: upType,
                        mouseCursorPosition: pt, mouseButton: .left) {
        up.setIntegerValueField(.mouseEventClickState, value: Int64(i + 1))
        up.post(tap: .cghidEventTap)
    }
    usleep(80_000)
}
