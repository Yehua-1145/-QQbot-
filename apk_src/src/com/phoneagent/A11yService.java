package com.phoneagent;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Bitmap;
import android.graphics.Path;
import android.graphics.Rect;
import android.hardware.HardwareBuffer;
import android.os.Build;
import android.os.Bundle;
import android.util.Base64;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * 无障碍服务：让没有 root 的手机也能被 AI 读界面 / 点按 / 输入 / 滑动 / 截图。
 *
 * 只监听 127.0.0.1:8081，外部访问不到。
 * 接口：
 *   GET  /ping
 *   GET  /foreground
 *   GET  /dump?limit=40
 *   GET  /shot                （Android 11+）
 *   POST /tap    {"text":".."} 或 {"x":1,"y":2}
 *   POST /type   {"text":".."}
 *   POST /swipe  {"dir":"up","dist":500}
 *   POST /key    {"key":"back"}
 *   POST /launch {"pkg":"com.tencent.mobileqq"}
 */
public class A11yService extends AccessibilityService {

    private static final int PORT = 8081;
    private volatile Object server;
    private volatile Thread serverThread;
    private volatile String foregroundPkg = "";
    private static A11yService inst;

    public static A11yService get() {
        return inst;
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        inst = this;
        startServer();
    }

    @Override
    public void onDestroy() {
        stopServer();
        inst = null;
        super.onDestroy();
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent e) {
        try {
            if (e.getEventType() == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
                CharSequence p = e.getPackageName();
                if (p != null) foregroundPkg = p.toString();
            }
        } catch (Exception ignored) {
        }
    }

    @Override
    public void onInterrupt() {
    }

    // ---------------- HTTP ----------------

    private A11yServer srv;

    private void startServer() {
        stopServer();
        srv = new A11yServer(this);
        Thread t = new Thread(srv);
        t.setDaemon(true);
        serverThread = t;
        t.start();
    }

    private void stopServer() {
        try {
            if (srv != null) srv.close();
        } catch (Exception ignored) {
        }
        srv = null;
        server = null;
    }

    void handle(Socket c) throws Exception {
        InputStream in = c.getInputStream();
        StringBuilder head = new StringBuilder();
        int ch, guard = 0;
        while ((ch = in.read()) != -1 && guard++ < 20000) {
            head.append((char) ch);
            int L = head.length();
            if (L >= 4 && head.charAt(L - 1) == '\n'
                    && (head.charAt(L - 2) == '\n'
                        || (head.charAt(L - 2) == '\r' && head.charAt(L - 3) == '\n'))) {
                break;   // 空行：头部结束（\r\n\r\n 或 \n\n）
            }
        }
        String[] lines = head.toString().split("\r?\n");
        if (lines.length == 0) return;
        String[] first = lines[0].split(" ");
        if (first.length < 2) return;
        String method = first[0];
        String url = first[1];

        int len = 0;
        for (String h : lines) {
            String low = h.toLowerCase(Locale.ROOT);
            if (low.startsWith("content-length:")) {
                try { len = Integer.parseInt(h.substring(15).trim()); } catch (Exception ignored) { }
            }
        }
        String body = "";
        if (len > 0) {
            byte[] buf = new byte[len];
            int got = 0;
            while (got < len) {
                int r = in.read(buf, got, len - got);
                if (r <= 0) break;
                got += r;
            }
            body = new String(buf, 0, got, StandardCharsets.UTF_8);
        }

        String path = url;
        String query = "";
        int qi = url.indexOf('?');
        if (qi >= 0) {
            path = url.substring(0, qi);
            query = url.substring(qi + 1);
        }

        String out;
        try {
            out = route(path, query, body);
        } catch (Throwable t) {
            out = "{\"ok\":false,\"err\":\"" + esc(String.valueOf(t)) + "\"}";
        }
        byte[] data = out.getBytes(StandardCharsets.UTF_8);
        OutputStream os = c.getOutputStream();
        String header = "HTTP/1.1 200 OK\r\nContent-Type: application/json; charset=utf-8\r\n"
                + "Content-Length: " + data.length + "\r\nConnection: close\r\n\r\n";
        os.write(header.getBytes(StandardCharsets.UTF_8));
        os.write(data);
        os.flush();
    }

    private String route(String path, String query, String body) {
        if (path.equals("/ping")) return "{\"ok\":true,\"api\":" + Build.VERSION.SDK_INT + "}";
        if (path.equals("/foreground")) return "{\"ok\":true,\"pkg\":\"" + esc(foregroundPkg) + "\"}";
        if (path.equals("/dump")) {
            int limit = intArg(query, "limit", 40);
            return dump(limit);
        }
        if (path.equals("/shot")) return shot();
        if (path.equals("/tap")) {
            String text = strArg(body, "text");
            if (text != null && text.length() > 0) return tapText(text);
            int x = intArg(body, "x", -1), y = intArg(body, "y", -1);
            if (x >= 0 && y >= 0) return tapXY(x, y, "coords");
            return "{\"ok\":false,\"err\":\"need text or x/y\"}";
        }
        if (path.equals("/type")) return typeText(strArg(body, "text"));
        if (path.equals("/swipe")) {
            String dir = strArg(body, "dir");
            if (dir == null) dir = "up";
            return swipe(dir, intArg(body, "dist", 500));
        }
        if (path.equals("/key")) {
            String k = strArg(body, "key");
            return key(k == null ? "back" : k);
        }
        if (path.equals("/launch")) return launch(strArg(body, "pkg"));
        return "{\"ok\":false,\"err\":\"unknown path\"}";
    }

    // ---------------- 功能实现 ----------------

    private String dump(int limit) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return "{\"ok\":true,\"pkg\":\"" + esc(foregroundPkg) + "\",\"nodes\":[]}";
        List<String> items = new ArrayList<>();
        walk(root, items, 0, limit * 3);
        StringBuilder sb = new StringBuilder();
        sb.append("{\"ok\":true,\"pkg\":\"").append(esc(foregroundPkg)).append("\",\"nodes\":[");
        int n = 0;
        for (String s : items) {
            if (n >= limit) break;
            if (n > 0) sb.append(',');
            sb.append(s);
            n++;
        }
        sb.append("],\"total\":").append(items.size()).append('}');
        return sb.toString();
    }

    private void walk(AccessibilityNodeInfo node, List<String> out, int depth, int cap) {
        if (node == null || depth > 40 || out.size() >= cap) return;
        CharSequence text = node.getText();
        CharSequence desc = node.getContentDescription();
        String t = text == null ? "" : text.toString().trim();
        String d = desc == null ? "" : desc.toString().trim();
        boolean clickable = node.isClickable();
        if (t.length() > 0 || d.length() > 0 || clickable) {
            Rect r = new Rect();
            node.getBoundsInScreen(r);
            if (r.width() > 0 && r.height() > 0) {
                String cls = node.getClassName() == null ? "" : node.getClassName().toString();
                int dot = cls.lastIndexOf('.');
                if (dot > 0) cls = cls.substring(dot + 1);
                String id = node.getViewIdResourceName();
                if (id != null) {
                    int sl = id.lastIndexOf('/');
                    if (sl > 0) id = id.substring(sl + 1);
                } else id = "";
                out.add("{\"text\":\"" + esc(t) + "\",\"desc\":\"" + esc(d) + "\",\"cls\":\"" + esc(cls)
                        + "\",\"id\":\"" + esc(id) + "\",\"x\":" + r.centerX() + ",\"y\":" + r.centerY()
                        + ",\"clickable\":" + clickable + "}");
            }
        }
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo ch = null;
            try { ch = node.getChild(i); } catch (Exception ignored) { }
            if (ch != null) walk(ch, out, depth + 1, cap);
        }
    }

    private AccessibilityNodeInfo findTextNode(String q, boolean needClickable) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) return null;
        String low = q.toLowerCase(Locale.ROOT);
        List<AccessibilityNodeInfo> stack = new ArrayList<>();
        stack.add(root);
        AccessibilityNodeInfo loose = null;
        int guard = 0;
        while (!stack.isEmpty() && guard++ < 2000) {
            AccessibilityNodeInfo n = stack.remove(stack.size() - 1);
            if (n == null) continue;
            String t = n.getText() == null ? "" : n.getText().toString().toLowerCase(Locale.ROOT);
            String d = n.getContentDescription() == null ? ""
                    : n.getContentDescription().toString().toLowerCase(Locale.ROOT);
            if (t.contains(low) || d.contains(low)) {
                if (n.isClickable()) return n;
                if (loose == null) {
                    // 往上找可点的父亲
                    AccessibilityNodeInfo p = n;
                    for (int i = 0; i < 4 && p != null; i++) {
                        if (p.isClickable()) return p;
                        p = p.getParent();
                    }
                    loose = n;
                }
            }
            for (int i = 0; i < n.getChildCount(); i++) {
                try { stack.add(n.getChild(i)); } catch (Exception ignored) { }
            }
        }
        return needClickable ? null : loose;
    }

    private String tapText(String text) {
        AccessibilityNodeInfo n = findTextNode(text, false);
        if (n == null) return "{\"ok\":false,\"err\":\"not found\"}";
        Rect r = new Rect();
        n.getBoundsInScreen(r);
        boolean clicked = false;
        try {
            AccessibilityNodeInfo c = n;
            for (int i = 0; i < 4 && c != null; i++) {
                if (c.isClickable()) { clicked = c.performAction(AccessibilityNodeInfo.ACTION_CLICK); break; }
                c = c.getParent();
            }
        } catch (Exception ignored) {
        }
        if (!clicked) return tapXY(r.centerX(), r.centerY(), "gesture");
        return "{\"ok\":true,\"by\":\"click\",\"x\":" + r.centerX() + ",\"y\":" + r.centerY() + "}";
    }

    private String tapXY(int x, int y, String by) {
        if (Build.VERSION.SDK_INT < 24) return "{\"ok\":false,\"err\":\"need api24\"}";
        Path p = new Path();
        p.moveTo(x, y);
        GestureDescription.Builder b = new GestureDescription.Builder();
        b.addStroke(new GestureDescription.StrokeDescription(p, 0, 60));
        dispatchGesture(b.build(), null, null);
        return "{\"ok\":true,\"by\":\"" + by + "\",\"x\":" + x + ",\"y\":" + y + "}";
    }

    private String typeText(String text) {
        if (text == null) return "{\"ok\":false,\"err\":\"no text\"}";
        AccessibilityNodeInfo root = getRootInActiveWindow();
        AccessibilityNodeInfo target = null;
        if (root != null) {
            List<AccessibilityNodeInfo> found = root.findAccessibilityNodeInfosByText("");
            try {
                target = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
            } catch (Exception ignored) {
            }
        }
        if (target == null) return "{\"ok\":false,\"err\":\"no focused input\"}";
        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text);
        boolean ok = target.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
        return ok ? "{\"ok\":true}" : "{\"ok\":false,\"err\":\"setText failed\"}";
    }

    private String swipe(String dir, int dist) {
        if (Build.VERSION.SDK_INT < 24) return "{\"ok\":false,\"err\":\"need api24\"}";
        int w = getResources().getDisplayMetrics().widthPixels;
        int h = getResources().getDisplayMetrics().heightPixels;
        int cx = w / 2, cy = h / 2;
        int d = Math.max(120, Math.min(dist, Math.min(w, h) / 2));
        float x1 = cx, y1 = cy, x2 = cx, y2 = cy;
        if (dir.equals("up")) { y1 = cy + d / 2f; y2 = cy - d / 2f; }
        else if (dir.equals("down")) { y1 = cy - d / 2f; y2 = cy + d / 2f; }
        else if (dir.equals("left")) { x1 = cx + d / 2f; x2 = cx - d / 2f; }
        else { x1 = cx - d / 2f; x2 = cx + d / 2f; }
        Path p = new Path();
        p.moveTo(x1, y1);
        p.lineTo(x2, y2);
        GestureDescription.Builder b = new GestureDescription.Builder();
        b.addStroke(new GestureDescription.StrokeDescription(p, 0, 300));
        dispatchGesture(b.build(), null, null);
        return "{\"ok\":true}";
    }

    private String key(String k) {
        int action;
        if (k.equals("home")) action = GLOBAL_ACTION_HOME;
        else if (k.equals("recents")) action = GLOBAL_ACTION_RECENTS;
        else if (k.equals("notifications")) action = GLOBAL_ACTION_NOTIFICATIONS;
        else if (k.equals("quick")) action = GLOBAL_ACTION_QUICK_SETTINGS;
        else if (k.equals("power")) action = GLOBAL_ACTION_LOCK_SCREEN;
        else action = GLOBAL_ACTION_BACK;
        boolean ok = performGlobalAction(action);
        return "{\"ok\":" + ok + "}";
    }

    private String launch(String pkg) {
        if (pkg == null || pkg.length() == 0) return "{\"ok\":false,\"err\":\"no pkg\"}";
        try {
            android.content.Intent i = getPackageManager().getLaunchIntentForPackage(pkg);
            if (i == null) return "{\"ok\":false,\"err\":\"no launch intent (app not installed?)\"}";
            i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
            startActivity(i);
            return "{\"ok\":true}";
        } catch (Exception e) {
            return "{\"ok\":false,\"err\":\"" + esc(String.valueOf(e)) + "\"}";
        }
    }

    private String shot() {
        if (Build.VERSION.SDK_INT < 30) return "{\"ok\":false,\"err\":\"need android 11+\"}";
        try {
            ShotCallback cb = new ShotCallback();
            takeScreenshot(android.view.Display.DEFAULT_DISPLAY, getMainExecutor(), cb);
            cb.waitFor(6);
            ScreenshotResult r = cb.result;
            if (r == null) return "{\"ok\":false,\"err\":\"screenshot failed\"}";
            HardwareBuffer hb = r.getHardwareBuffer();
            Bitmap bmp = Bitmap.wrapHardwareBuffer(hb, r.getColorSpace());
            if (bmp == null) return "{\"ok\":false,\"err\":\"bitmap null\"}";
            ByteArrayOutputStream bos = new ByteArrayOutputStream();
            bmp.compress(Bitmap.CompressFormat.PNG, 100, bos);
            String b64 = Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP);
            return "{\"ok\":true,\"w\":" + bmp.getWidth() + ",\"h\":" + bmp.getHeight()
                    + ",\"png\":\"" + b64 + "\"}";
        } catch (Throwable t) {
            return "{\"ok\":false,\"err\":\"" + esc(String.valueOf(t)) + "\"}";
        }
    }

    // ---------------- 小工具 ----------------

    private static String esc(String s) {
        if (s == null) return "";
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '"' || c == '\\') b.append('\\').append(c);
            else if (c == '\n') b.append("\\n");
            else if (c == '\r') b.append("\\r");
            else if (c == '\t') b.append("\\t");
            else if (c < 0x20) b.append(' ');
            else b.append(c);
        }
        return b.toString();
    }

    private static String strArg(String body, String key) {
        if (body == null) return null;
        String pat = "\"" + key + "\"";
        int i = body.indexOf(pat);
        if (i < 0) return null;
        int c = body.indexOf(':', i + pat.length());
        if (c < 0) return null;
        int q1 = body.indexOf('"', c + 1);
        if (q1 < 0) return null;
        StringBuilder sb = new StringBuilder();
        for (int k = q1 + 1; k < body.length(); k++) {
            char ch = body.charAt(k);
            if (ch == '\\' && k + 1 < body.length()) {
                char nx = body.charAt(k + 1);
                if (nx == 'n') sb.append('\n');
                else if (nx == 't') sb.append('\t');
                else sb.append(nx);
                k++;
            } else if (ch == '"') break;
            else sb.append(ch);
        }
        return sb.toString();
    }

    private static int intArg(String src, String key, int def) {
        if (src == null) return def;
        String pat = "\"" + key + "\"";
        int i = src.indexOf(pat + "?") >= 0 ? src.indexOf(pat) : src.indexOf(pat);
        int use = src.indexOf(pat);
        if (use < 0) {
            // 支持 ?limit=40 这种 query 写法
            int q = src.indexOf(key + "=");
            if (q < 0) return def;
            int s2 = q + key.length() + 1, e2 = s2;
            while (e2 < src.length() && (Character.isDigit(src.charAt(e2)) || src.charAt(e2) == '-')) e2++;
            try { return Integer.parseInt(src.substring(s2, e2)); } catch (Exception ex) { return def; }
        }
        int c = src.indexOf(':', use + pat.length());
        if (c < 0) return def;
        int s = c + 1, e = s;
        while (e < src.length() && (Character.isDigit(src.charAt(e)) || src.charAt(e) == '-')) e++;
        try { return Integer.parseInt(src.substring(s, e).trim()); } catch (Exception ex) { return def; }
    }
}
