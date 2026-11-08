package com.botagent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;

/** 手势工具：长按等。所有回调都写成顶层类，避免 d8 处理匿名类时崩溃。 */
public class GestureHelper {

    public static boolean longPress(AccessibilityService svc, int x, int y) {
        try {
            Path p = new Path();
            p.moveTo(x, y);
            GestureDescription.StrokeDescription stroke =
                    new GestureDescription.StrokeDescription(p, 0, 650);
            GestureDescription.Builder b = new GestureDescription.Builder();
            b.addStroke(stroke);
            GestureCallback cb = new GestureCallback();
            boolean dispatched = svc.dispatchGesture(b.build(), cb, null);
            if (!dispatched) {
                return false;
            }
            cb.await(2500);
            return cb.ok;
        } catch (Throwable t) {
            return false;
        }
    }
}
