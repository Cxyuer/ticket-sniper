// lockstate —— 屏幕是否锁定（锁屏后窗口不再重绘，截图会静默变成旧帧）
// 输出: LOCKED / UNLOCKED

import Cocoa

let d = CGSessionCopyCurrentDictionary() as? [String: Any] ?? [:]
let locked = d["CGSSessionScreenIsLocked"] as? Bool ?? false
print(locked ? "LOCKED" : "UNLOCKED")
