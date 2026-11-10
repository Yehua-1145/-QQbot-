package com.botagent;

import android.accessibilityservice.AccessibilityService;
import android.graphics.Bitmap;
import android.hardware.HardwareBuffer;
import android.os.Build;
import android.util.Base64;

import java.io.ByteArrayOutputStream;

/**
 * Android 11+ 的截图实现（API 30 才有 takeScreenshot / ScreenshotResult / HardwareBuffer）。
 *
 * 关键：这些类型必须隔离在这个类里，由 A11yService 通过反射调用。
 * 否则 Android 9/10 在实例化无障碍服务时会去解析 AccessibilityService$TakeScreenshotCallback，
 * 直接抛 NoClassDefFoundError —— 服务起不来，整机无障碍全废。
 */
public class Shot30 {

    public static String take(AccessibilityService svc) {
        try {
            ShotCallback cb = new ShotCallback();
            svc.takeScreenshot(android.view.Display.DEFAULT_DISPLAY, svc.getMainExecutor(), cb);
            cb.waitFor(6);
            AccessibilityService.ScreenshotResult r = cb.result;
            if (r == null) {
                return "{\"ok\":false,\"err\":\"screenshot failed\"}";
            }
            HardwareBuffer hb = r.getHardwareBuffer();
            Bitmap bmp = Bitmap.wrapHardwareBuffer(hb, r.getColorSpace());
            if (bmp == null) {
                return "{\"ok\":false,\"err\":\"bitmap null\"}";
            }
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            bmp.compress(Bitmap.CompressFormat.PNG, 100, bos);
            String b64 = Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP);
            return "{\"ok\":true,\"w\":" + bmp.getWidth() + ",\"h\":" + bmp.getHeight()
                    + ",\"png\":\"" + b64 + "\"}";
        } catch (Throwable t) {
            return "{\"ok\":false,\"err\":\"" + String.valueOf(t).replace("\"", "'") + "\"}";
        }
    }

    /** 只在 SDK >= 30 时才允许加载本类。 */
    public static boolean available() {
        return Build.VERSION.SDK_INT >= 30;
    }
}
