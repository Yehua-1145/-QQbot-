package com.botagent;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.KeyEvent;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStreamWriter;

/**
 * Botagent 2.0：一体化控制台
 *
 * 首屏是本地 setup.html（向导 + 状态），配置写进 App 私有目录。
 * 服务起来后可以进 8080 的完整控制台；服务没起就退回向导页。
 *
 * 注意：不用匿名内部类（老版本 d8 会在 $1.class 上崩）。
 */
public class MainActivity extends Activity {


    WebView web;
    android.widget.FrameLayout root;
    android.widget.FrameLayout navBar;
    android.widget.TextView prevBtn;
    android.widget.TextView nextBtn;
    boolean onConsole = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        try {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        } catch (Throwable ignored) {
        }
        // file:// 页面要能 fetch 127.0.0.1:8080 上的本地接口，否则控制台全是"读不到"
        try {
            s.setAllowUniversalAccessFromFileURLs(true);
            s.setAllowFileAccessFromFileURLs(true);
        } catch (Throwable ignored) {
        }

        web.setBackgroundColor(0xFF0D1117);
        web.setWebViewClient(new PageClient(this));
        web.addJavascriptInterface(new Bridge(this), "Android");
        getWindow().setBackgroundDrawable(
                new android.graphics.drawable.ColorDrawable(0xFF08181b));

        // 外层 FrameLayout：WebView 铺满，底部叠一条原生导航（不依赖 HTML 定位）
        root = new android.widget.FrameLayout(this);
        root.setBackgroundColor(0xFF08181b);
        root.addView(web, new android.widget.FrameLayout.LayoutParams(
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                android.widget.FrameLayout.LayoutParams.MATCH_PARENT));

        navBar = buildNavBar();
        android.widget.FrameLayout.LayoutParams navLp =
                new android.widget.FrameLayout.LayoutParams(
                        android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                        android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.BOTTOM);
        root.addView(navBar, navLp);
        setContentView(root);

        web.loadUrl(pageUrl("setup.html"));
    }

    /** 原生底部导航：左「上一步」，中间「下一步」。 */
    private android.widget.FrameLayout buildNavBar() {
        float d = getResources().getDisplayMetrics().density;

        android.widget.FrameLayout bar = new android.widget.FrameLayout(this);
        android.graphics.drawable.GradientDrawable bg =
                new android.graphics.drawable.GradientDrawable(
                        android.graphics.drawable.GradientDrawable.Orientation.TOP_BOTTOM,
                        new int[]{0xF20B2226, 0xFF071619});
        bg.setStroke((int) (1 * d), 0x14FFFFFF);
        bar.setBackground(bg);

        int padH = (int) (16 * d), padV = (int) (12 * d);
        bar.setPadding(padH, padV, padH, padV + (int) (12 * d));

        // 上一步（左下，文字按钮）
        prevBtn = new android.widget.TextView(this);
        prevBtn.setText("\u2039");          // ‹
        prevBtn.setTextSize(24f);
        prevBtn.setTextColor(0xFF8FB3B7);
        prevBtn.setGravity(android.view.Gravity.CENTER);
        prevBtn.setContentDescription("上一步");
        prevBtn.setOnClickListener(new NavPrev(this));
        android.widget.FrameLayout.LayoutParams prevLp =
                new android.widget.FrameLayout.LayoutParams(
                        (int) (44 * d), (int) (44 * d),
                        android.view.Gravity.START | android.view.Gravity.CENTER_VERTICAL);
        prevLp.leftMargin = (int) (4 * d);
        bar.addView(prevBtn, prevLp);

        // 下一步（正中，青色胶囊）
        nextBtn = new android.widget.TextView(this);
        nextBtn.setText("下一步");
        nextBtn.setTextSize(15.5f);
        nextBtn.setTypeface(null, android.graphics.Typeface.BOLD);
        nextBtn.setTextColor(0xFF04211F);
        nextBtn.setGravity(android.view.Gravity.CENTER);
        nextBtn.setPadding(0, (int) (15 * d), 0, (int) (15 * d));
        android.graphics.drawable.GradientDrawable pill =
                new android.graphics.drawable.GradientDrawable(
                        android.graphics.drawable.GradientDrawable.Orientation.LEFT_RIGHT,
                        new int[]{0xFF2EE6D6, 0xFF12B3A2});
        pill.setCornerRadius(14 * d);
        nextBtn.setBackground(pill);
        nextBtn.setOnClickListener(new NavNext(this));
        android.widget.FrameLayout.LayoutParams nextLp =
                new android.widget.FrameLayout.LayoutParams(
                        android.widget.FrameLayout.LayoutParams.MATCH_PARENT,
                        android.widget.FrameLayout.LayoutParams.WRAP_CONTENT,
                        android.view.Gravity.CENTER);
        nextLp.leftMargin = (int) (48 * d);
        nextLp.rightMargin = (int) (48 * d);
        bar.addView(nextBtn, nextLp);

        bar.setVisibility(android.view.View.GONE);
        return bar;
    }

    /** JS 告诉原生当前在第几步（1..4，5=完成页）。 */
    void syncNav(int step, int total) {
        if (navBar == null) {
            return;
        }
        runOnUiThread(new NavSync(this, step, total));
    }

    // ---------- 页面切换 ----------
    // ---------------- root（可选） ----------------

    static final String[] SU_PATHS = {
            "/system/bin/su", "/system/xbin/su", "/sbin/su",
            "/debug_ramdisk/su", "/su/bin/su", "su"
    };

    private java.io.File rootFlag() {
        java.io.File d = new java.io.File(getFilesDir(), "aibot");
        d.mkdirs();
        return new java.io.File(d, "root_mode.json");
    }

    boolean rootEnabled() {
        try {
            String t = readSmall(rootFlag());
            return t.contains("\"enabled\":true") || t.contains("\"enabled\": true");
        } catch (Throwable t) {
            return false;
        }
    }

    void rootSetEnabled(boolean on) {
        try {
            java.io.FileWriter w = new java.io.FileWriter(rootFlag());
            w.write("{\"enabled\":" + (on ? "true" : "false") + "}");
            w.close();
        } catch (Throwable ignored) {
        }
    }

    static String findSu() {
        for (String p : SU_PATHS) {
            try {
                if (p.equals("su")) {
                    // 交给 PATH 解析，能跑到就算有
                    Process t = Runtime.getRuntime().exec(new String[]{"sh", "-c", "command -v su"});
                    java.io.BufferedReader r = new java.io.BufferedReader(
                            new java.io.InputStreamReader(t.getInputStream()));
                    String line = r.readLine();
                    t.waitFor();
                    if (line != null && line.trim().length() > 0) {
                        return line.trim();
                    }
                    continue;
                }
                java.io.File f = new java.io.File(p);
                if (f.exists() && f.canExecute()) {
                    return p;
                }
            } catch (Throwable ignored) {
            }
        }
        return "";
    }

    /** 执行 su -c cmd，返回 "uid=0(root)..." 或错误字符串。timeoutMs 内没结果就算失败。 */
    static String execSu(String su, String cmd, int timeoutMs) {
        Process p = null;
        final StringBuilder out = new StringBuilder();
        try {
            p = Runtime.getRuntime().exec(new String[]{su, "-c", cmd});
            final java.io.BufferedReader r = new java.io.BufferedReader(
                    new java.io.InputStreamReader(p.getInputStream()));
            final java.io.BufferedReader e = new java.io.BufferedReader(
                    new java.io.InputStreamReader(p.getErrorStream()));
            final Process fp = p;
            Thread rd = new Thread(new Runnable() {
                public void run() {
                    try {
                        String l;
                        while ((l = r.readLine()) != null) {
                            out.append(l).append('\n');
                        }
                    } catch (Throwable ignored) {
                    }
                }
            });
            Thread re = new Thread(new Runnable() {
                public void run() {
                    try {
                        String l;
                        while ((l = e.readLine()) != null) {
                            out.append(l).append('\n');
                        }
                    } catch (Throwable ignored) {
                    }
                }
            });
            rd.start();
            re.start();
            long deadline = System.currentTimeMillis() + timeoutMs;
            while (System.currentTimeMillis() < deadline) {
                try {
                    int code = fp.exitValue();
                    rd.join(400);
                    re.join(400);
                    return out.toString().trim().isEmpty()
                            ? ("(exit " + code + ")") : out.toString().trim();
                } catch (IllegalThreadStateException alive) {
                    try {
                        Thread.sleep(120);
                    } catch (InterruptedException ignored) {
                    }
                }
            }
            try {
                fp.destroy();
            } catch (Throwable ignored) {
            }
            return out.toString().trim();
        } catch (Throwable t) {
            return "ERR " + t;
        } finally {
            try {
                if (p != null) {
                    p.destroy();
                }
            } catch (Throwable ignored) {
            }
        }
    }

    static String readSmall(java.io.File f) {
        try {
            java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
            java.io.FileInputStream in = new java.io.FileInputStream(f);
            byte[] buf = new byte[2048];
            int n;
            while ((n = in.read(buf)) > 0) {
                bo.write(buf, 0, n);
            }
            in.close();
            return new String(bo.toByteArray(), "UTF-8");
        } catch (Throwable t) {
            return "";
        }
    }

    /** 热更新：files/web/console.html 存在就优先用它，否则用 APK 内置的。 */
    String pageUrl(String name) {
        try {
            java.io.File f = new java.io.File(new java.io.File(getFilesDir(), "web"), name);
            if (f.exists() && f.length() > 512) {
                return "file://" + f.getAbsolutePath();
            }
        } catch (Throwable ignored) {
        }
        return "file:///android_asset/" + name;
    }

    /** 离线装依赖：把 /sdcard/botagent-deps/*.deb 打进容器 /tmp/deps 再 dpkg。 */
    void offlineDeps() {
        new Thread(new OfflineDepsTask(this)).start();
    }

    /** 自检/申请 root：返回 JSON 字符串给前端。ask=true 时会真的去弹授权框。 */
    String rootStatusJson(boolean ask) {
        String su = findSu();
        boolean has = su.length() > 0;
        boolean granted = false;
        String msg = "";
        if (has) {
            String out = execSu(su, "id", ask ? 30000 : 6000);
            granted = out != null && out.contains("uid=0");
            msg = (out == null ? "" : out.replace("\n", " ").trim());
            if (msg.length() > 120) {
                msg = msg.substring(0, 120);
            }
        } else {
            msg = "设备上没有 su（未 root，或用的是隐藏 root）";
        }
        StringBuilder b = new StringBuilder();
        b.append("{\"su_found\":").append(has)
         .append(",\"granted\":").append(granted)
         .append(",\"enabled\":").append(rootEnabled())
         .append(",\"su_path\":\"").append(su.replace("\"", ""))
         .append("\",\"msg\":\"")
         .append(msg.replace("\"", "'").replace("\\", "/"))
         .append("\"}");
        return b.toString();
    }

    /** 一键启动：协议端（QQ+NapCat）→ 机器人，中间等端口就绪。 */
    void startAll() {
        new Thread(new StartAllTask(this)).start();
    }

    /** 自检：返回 JSON 数组字符串，前端直接渲染。 */
    String selfCheckJson() {
        StringBuilder sb = new StringBuilder("[");
        boolean first = true;

        Object[][] items = new Object[][]{
                {"容器", container().ready(), "点第 3 步「创建容器」"},
                {"运行时", runtimeReady(), "点第 4 步「启动机器人」"},
                {"无障碍", portOpen(8081, 300), "第 2 步打开无障碍"},
                {"协议端 6099", portOpen(6099, 400), "第 3 步点「启动协议端」"},
                {"OneBot 3001", portOpen(3001, 400), "协议端登录后自动开；没开就看 docs/onebot-port.md"},
                {"控制台 8080", portOpen(RuntimeManager.port > 0 ? RuntimeManager.port : 8080, 400),
                        "点第 4 步「启动机器人」"},
        };
        for (Object[] it : items) {
            boolean ok = Boolean.TRUE.equals(it[1]);
            if (!first) {
                sb.append(',');
            }
            first = false;
            sb.append("{\"name\":\"").append(it[0]).append("\",\"ok\":").append(ok)
              .append(",\"hint\":\"").append(ok ? "" : it[2]).append("\"}");
        }
        sb.append("]");
        return sb.toString();
    }

    static boolean portOpen(int port, int timeoutMs) {
        java.net.Socket sk = null;
        try {
            sk = new java.net.Socket();
            sk.connect(new java.net.InetSocketAddress("127.0.0.1", port), timeoutMs);
            return true;
        } catch (Exception e) {
            return false;
        } finally {
            try {
                if (sk != null) {
                    sk.close();
                }
            } catch (Exception ignored) {
            }
        }
    }

    void showNav(final boolean on) {
        runOnUiThread(new NavToggle(this, on));
    }

    void openConsole() {
        onConsole = true;
        showNav(false);
        // 用自己的控制台界面（不再把 webui 的网页塞进 WebView）
        web.loadUrl(pageUrl("console.html"));
    }

    void backToSetup() {
        onConsole = false;
        showNav(true);
        web.loadUrl(pageUrl("setup.html"));
    }

    void reloadPage() {
        if (onConsole) {
            web.loadUrl(pageUrl("console.html"));
        } else {
            web.loadUrl(pageUrl("setup.html"));
        }
    }

    void startServices() {
        new Thread(new RootTask(
                "sh /data/local/tmp/start_webui.sh; sleep 5; sh /data/local/tmp/start_bot.sh")).start();
        new Handler(Looper.getMainLooper()).postDelayed(new DelayReload(this), 11000);
    }

    // ---------- 配置读写 ----------
    File configFile() {
        return new File(new File(getFilesDir(), "aibot"), "config.json");
    }

    String readConfig() {
        try {
            File f = configFile();
            if (!f.exists()) {
                return "{}";
            }
            InputStream in = new java.io.FileInputStream(f);
            BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = r.readLine()) != null) {
                sb.append(line);
            }
            r.close();
            return sb.toString();
        } catch (Exception e) {
            return "{}";
        }
    }

    /** 保存协议端地址（ws://...）和 access_token。 */
    String saveProto(String ws, String token) {
        try {
            File dir = new File(getFilesDir(), "aibot");
            dir.mkdirs();
            org.json.JSONObject o = new org.json.JSONObject();
            File f = configFile();
            if (f.exists()) {
                String raw = new String(java.nio.file.Files.readAllBytes(f.toPath()), "UTF-8");
                try {
                    o = new org.json.JSONObject(raw);
                } catch (Exception ignored) {
                }
            }
            ws = ws == null ? "" : ws.trim();
            token = token == null ? "" : token.trim();
            if (ws.length() > 0) {
                if (!ws.startsWith("ws://") && !ws.startsWith("wss://")) {
                    ws = "ws://" + ws;
                }
                o.put("proto_ws", ws);
            } else {
                o.remove("proto_ws");
            }
            if (token.length() > 0) {
                o.put("proto_token", token);
            } else {
                o.remove("proto_token");
            }
            java.io.FileWriter w = new java.io.FileWriter(f);
            w.write(o.toString(2));
            w.close();
            return "协议端已保存";
        } catch (Exception e) {
            return "保存失败：" + e.getMessage();
        }
    }

    String saveConfig(String qq, String apiKey) {
        try {
            File dir = new File(getFilesDir(), "aibot");
            dir.mkdirs();
            String owner = qq == null ? "" : qq.trim();
            if (owner.length() == 0) {
                return "QQ 号为空";
            }
            String cur = readConfig();
            org.json.JSONObject o;
            try {
                o = new org.json.JSONObject(cur.length() > 2 ? cur : "{}");
            } catch (Exception e) {
                o = new org.json.JSONObject();
            }
            // QQ 号是 10 位，超过 int 范围，必须用 long
            long uid = Long.parseLong(owner);
            o.put("owner_uid", uid);
            org.json.JSONArray arr = new org.json.JSONArray();
            arr.put(uid);
            o.put("adult_uids", arr);
            o.put("allowed_private_uids", arr);
            if (apiKey != null && apiKey.trim().length() > 0) {
                o.put("api_key", apiKey.trim());
            }
            if (!o.has("base_url")) {
                o.put("base_url", "https://api.deepseek.com/chat/completions");
            }
            if (!o.has("model")) {
                o.put("model", "deepseek-chat");
            }
            if (!o.has("napcat_ws")) {
                o.put("napcat_ws", "ws://127.0.0.1:3001");
            }
            FileOutputStream out = new FileOutputStream(configFile());
            OutputStreamWriter w = new OutputStreamWriter(out, "UTF-8");
            w.write(o.toString(2));
            w.close();
            return "ok";
        } catch (Exception e) {
            return String.valueOf(e.getMessage());
        }
    }

    // ---------- 运行时的 UI 反馈 ----------
    void uiLog(final String msg) {
        android.util.Log.i("botagent", msg);
        // 同时写一份日志文件，方便 adb 侧排查
        try {
            java.io.File f = new java.io.File(getFilesDir(), "rt.log");
            java.io.FileWriter w = new java.io.FileWriter(f, true);
            w.write(new java.text.SimpleDateFormat("HH:mm:ss")
                    .format(new java.util.Date()) + "  " + msg + "\n");
            w.close();
        } catch (Exception ignored) {
        }
        runOnUiThread(new UiEval(this, "rtlog", msg));
    }

    void uiDone(final String msg) {
        runOnUiThread(new UiEval(this, "rtdone", msg));
    }

    void uiRefresh() {
        runOnUiThread(new UiEval(this, "refresh", ""));
    }

    void startRuntime(boolean force) {
        android.content.Intent i = new android.content.Intent(this, BotService.class);
        i.putExtra("force", force);
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            startForegroundService(i);
        } else {
            startService(i);
        }
    }

    boolean astrbotInstalled() {
        try {
            getPackageManager().getPackageInfo("com.astrbot.astrbot_android", 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    boolean termuxInstalled() {
        try {
            getPackageManager().getPackageInfo("com.termux", 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    void openTermux() {
        try {
            android.content.Intent i = getPackageManager()
                    .getLaunchIntentForPackage("com.termux");
            if (i != null) {
                i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
            }
        } catch (Exception ignored) {
        }
    }

    boolean batteryOk() {
        try {
            android.os.PowerManager pm =
                    (android.os.PowerManager) getSystemService(POWER_SERVICE);
            return pm.isIgnoringBatteryOptimizations(getPackageName());
        } catch (Exception e) {
            return false;
        }
    }

    void requestBattery() {
        try {
            android.content.Intent i = new android.content.Intent(
                    android.provider.Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    android.net.Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception e) {
            openAppSettings();
        }
    }

    void openAppSettings() {
        try {
            android.content.Intent i = new android.content.Intent(
                    android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    android.net.Uri.parse("package:" + getPackageName()));
            startActivity(i);
        } catch (Exception ignored) {
        }
    }

    void openAutoStart() {
        // 各家 ROM 的「自启动管理」入口，找不到就退回应用详情页
        String[] acts = {
                "com.miui.securitycenter/com.miui.permcenter.autostart.AutoStartManagementActivity",
                "com.miui.powerkeeper/com.miui.powerkeeper.ui.HiddenAppsConfigActivity",
                "com.huawei.systemmanager/.startupmgr.ui.StartupNormalAppListActivity",
                "com.coloros.safecenter/.startupapp.StartupAppListActivity",
                "com.oppo.safe/.permission.startup.StartupAppListActivity",
                "com.vivo.permissionmanager/.activity.BgStartUpManagerActivity",
        };
        for (String a : acts) {
            try {
                android.content.Intent i = new android.content.Intent();
                i.setComponent(android.content.ComponentName.unflattenFromString(a));
                i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(i);
                return;
            } catch (Exception ignored) {
            }
        }
        openAppSettings();
    }

    Container container() {
        return new Container(this);
    }

    static final int REQ_EXT = 4352;

    Extension qqExt() {
        return new Extension(this, Extension.QQ_ID, "QQ 协议端", "用户自备安装包");
    }

    void extImport() {
        try {
            android.content.Intent i = new android.content.Intent(
                    android.content.Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(android.content.Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            startActivityForResult(i, REQ_EXT);
        } catch (Exception e) {
            uiLog("打不开文件选择器：" + e);
        }
    }

    static final int REQ_DEB = 4351;

    void pickDeb() {
        try {
            android.content.Intent i = new android.content.Intent(
                    android.content.Intent.ACTION_OPEN_DOCUMENT);
            i.addCategory(android.content.Intent.CATEGORY_OPENABLE);
            i.setType("*/*");
            startActivityForResult(i, REQ_DEB);
        } catch (Exception e) {
            uiLog("打不开文件选择器：" + e);
        }
    }

    @Override
    protected void onActivityResult(int req, int res, android.content.Intent data) {
        super.onActivityResult(req, res, data);
        if (res != RESULT_OK || data == null || data.getData() == null) {
            return;
        }
        if (req == REQ_EXT) {
            final android.net.Uri u2 = data.getData();
            new Thread(new ExtImporter(this, u2)).start();
            return;
        }
        if (req != REQ_DEB) {
            return;
        }
        final android.net.Uri uri = data.getData();
        new Thread(new DebImporter(this, uri)).start();
    }

    void createContainer() {
        new Thread(new ContainerMaker(this)).start();
    }

    /** 容器里跑一条命令（调试/装包用）。 */
    void containerRun(String cmdline) {
        new Thread(new ContainerRunner(this, cmdline)).start();
    }

    boolean runtimeReady() {
        // 有 assets/runtime.zip 就算带运行时（不再依赖 lib/ 里的二进制）
        try {
            getAssets().open("runtime.zip").close();
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) {
            if (onConsole) {
                backToSetup();
                return true;
            }
            if (web != null && web.canGoBack()) {
                web.goBack();
                return true;
            }
        }
        return super.onKeyDown(keyCode, event);
    }
}

/** WebView 客户端：控制台加载失败时退回向导页。 */
class PageClient extends WebViewClient {

    private final MainActivity act;

    PageClient(MainActivity a) {
        this.act = a;
    }

    private boolean handleUrl(String url) {
        if (url == null) {
            return false;
        }
        if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")
                || url.startsWith("file://")) {
            return false;
        }
        try {
            android.content.Intent it = new android.content.Intent(
                    android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url));
            it.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(it);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, String url) {
        return handleUrl(url);
    }

    @Override
    public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
        try {
            return handleUrl(request.getUrl().toString());
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        if (act.onConsole && (request == null || request.isForMainFrame())) {
            act.backToSetup();
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
        if (act.onConsole) {
            act.backToSetup();
        }
    }
}

/** 暴露给网页的接口（window.Android.xxx）。 */
class Bridge {

    private final MainActivity act;

    Bridge(MainActivity a) {
        this.act = a;
    }

    @JavascriptInterface
    public String saveConfig(String qq, String apiKey) {
        return act.saveConfig(qq, apiKey);
    }

    @JavascriptInterface
    public String getConfig() {
        return act.readConfig();
    }

    @JavascriptInterface
    public boolean a11yEnabled() {
        // 先看无障碍服务端口通不通（最准）；不行再退回读设置
        java.net.Socket sk = null;
        try {
            sk = new java.net.Socket();
            sk.connect(new java.net.InetSocketAddress("127.0.0.1", 8081), 350);
            return true;
        } catch (Exception ignored) {
        } finally {
            try {
                if (sk != null) {
                    sk.close();
                }
            } catch (Exception ignored) {
            }
        }
        try {
            String cur = android.provider.Settings.Secure.getString(
                    act.getContentResolver(),
                    android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES);
            if (cur == null) {
                return false;
            }
            return cur.contains("com.botagent") && cur.contains("A11yService");
        } catch (Exception e) {
            return false;
        }
    }

    @JavascriptInterface
    public void openA11y() {
        act.runOnUiThread(new A11yOpener(act, false));
    }

    @JavascriptInterface
    public boolean astrbotInstalled() {
        return act.astrbotInstalled();
    }

    @JavascriptInterface
    public void openAstrbot() {
        try {
            android.content.Intent i = act.getPackageManager()
                    .getLaunchIntentForPackage("com.astrbot.astrbot_android");
            if (i != null) {
                i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                act.startActivity(i);
            }
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public boolean termuxInstalled() {
        return act.termuxInstalled();
    }

    @JavascriptInterface
    public void openTermux() {
        act.runOnUiThread(new TermuxOpener(act));
    }

    /** 复制文本到剪贴板，方便用户去 Termux 里粘贴。 */
    @JavascriptInterface
    public void copyText(String text) {
        try {
            android.content.ClipboardManager cm = (android.content.ClipboardManager)
                    act.getSystemService(act.CLIPBOARD_SERVICE);
            cm.setPrimaryClip(android.content.ClipData.newPlainText("botagent", text));
        } catch (Exception ignored) {
        }
    }

    @JavascriptInterface
    public void openSetup() {
        act.runOnUiThread(new SetupOpener(act));
    }

    @JavascriptInterface
    public void offlineDeps() {
        act.offlineDeps();
    }

    @JavascriptInterface
    public String rootStatus() {
        return act.rootStatusJson(false);
    }

    @JavascriptInterface
    public String rootRequest() {
        return act.rootStatusJson(true);
    }

    @JavascriptInterface
    public boolean rootEnabled() {
        return act.rootEnabled();
    }

    @JavascriptInterface
    public void rootSetEnabled(boolean on) {
        act.rootSetEnabled(on);
    }

    @JavascriptInterface
    public void startAll() {
        act.startAll();
    }

    @JavascriptInterface
    public String selfCheck() {
        return act.selfCheckJson();
    }

    @JavascriptInterface
    public void navStep(int step, int total) {
        act.syncNav(step, total);
    }

    @JavascriptInterface
    public void showNav(boolean on) {
        act.showNav(on);
    }

    @JavascriptInterface
    public int runPort() {
        return RuntimeManager.port;
    }

    @JavascriptInterface
    public boolean containerReady() {
        return act.container().ready();
    }

    @JavascriptInterface
    public String containerInfo() {
        Container c = act.container();
        long mb = c.totalBytes() / 1048576;
        return c.ready() ? ("已就绪，" + mb + " MB") : "未创建";
    }

    @JavascriptInterface
    public void containerCreate() {
        act.createContainer();
    }

    @JavascriptInterface
    public void extPick() {
        act.runOnUiThread(new ExtPicker(act));
    }

    @JavascriptInterface
    public boolean extHasPayload() {
        Extension e = act.qqExt();
        return e.payload() != null;
    }

    @JavascriptInterface
    public String extInfo() {
        Extension e = act.qqExt();
        java.io.File p = e.payload();
        StringBuilder sb = new StringBuilder();
        if (p == null) {
            sb.append("没放安装包");
        } else {
            sb.append("已放 ").append(p.getName())
              .append("（").append(p.length() / 1048576).append(" MB）");
        }
        if (e.installed()) {
            sb.append(" · 已安装");
        }
        return sb.toString();
    }

    @JavascriptInterface
    public void napcatInstall() {
        new Thread(new NapCatInstaller(act)).start();
    }

    @JavascriptInterface
    public void napcatStart() {
        android.util.Log.i("botagent", "napcatStart -> ExtRunner2(napcat-run)");
        new Thread(new ExtRunner2(act, "napcat-run", 86400)).start();
    }

    @JavascriptInterface
    public void extInstall() {
        new Thread(new ExtInstaller(act)).start();
    }

    @JavascriptInterface
    public void extStart() {
        new Thread(new ExtRunner(act, "start")).start();
    }

    @JavascriptInterface
    public void extStop() {
        new Thread(new ExtRunner(act, "stop")).start();
    }

    @JavascriptInterface
    public void extStatus() {
        new Thread(new ExtRunner(act, "status")).start();
    }

    @JavascriptInterface
    public void containerPickDeb() {
        act.runOnUiThread(new DebPicker(act));
    }

    @JavascriptInterface
    public void containerExec(String cmd) {
        act.containerRun(cmd);
    }

    @JavascriptInterface
    public boolean batteryOk() {
        return act.batteryOk();
    }

    @JavascriptInterface
    public void requestBattery() {
        act.runOnUiThread(new BatteryRequester(act));
    }

    @JavascriptInterface
    public void openAppSettings() {
        act.runOnUiThread(new SettingsOpener(act, false));
    }

    @JavascriptInterface
    public void openAutoStart() {
        act.runOnUiThread(new SettingsOpener(act, true));
    }

    @JavascriptInterface
    public boolean serviceRunning() {
        return BotService.running;
    }

    @JavascriptInterface
    public String serviceState() {
        return BotService.state;
    }

    @JavascriptInterface
    public void stopService() {
        act.stopService(new android.content.Intent(act, BotService.class));
    }

    @JavascriptInterface
    public boolean runtimeReady() {
        return act.runtimeReady();
    }

    @JavascriptInterface
    public String startRuntime() {
        act.startRuntime(false);
        return "开始启动…";
    }

    @JavascriptInterface
    public String reinstallRuntime() {
        act.startRuntime(true);
        return "重新解压运行时…";
    }

    @JavascriptInterface
    public void openConsole() {
        act.runOnUiThread(new ConsoleOpener(act));
    }

    @JavascriptInterface
    public void reload() {
        act.runOnUiThread(new DelayReload(act));
    }

    @JavascriptInterface
    public void startServices() {
        act.startServices();
    }

    @JavascriptInterface
    public void toast(String text) {
        act.runOnUiThread(new UiToast(act, text));
    }

    @JavascriptInterface
    public void openUrl(String url) {
        act.runOnUiThread(new AppOpener(act, url, url));
    }

    @JavascriptInterface
    public void openApp(String appUrl, String webUrl) {
        act.runOnUiThread(new AppOpener(act, appUrl, webUrl));
    }
}

/** 主线程切到控制台。 */
class ConsoleOpener implements Runnable {

    private final MainActivity act;

    ConsoleOpener(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.openConsole();
    }
}

/** 打开外部链接：先试 app scheme，失败回退 web url。 */
class AppOpener implements Runnable {

    private final MainActivity act;
    private final String appUrl;
    private final String webUrl;

    AppOpener(MainActivity a, String appUrl, String webUrl) {
        this.act = a;
        this.appUrl = appUrl;
        this.webUrl = webUrl;
    }

    private void launch(String url) {
        android.content.Intent i = new android.content.Intent(
                android.content.Intent.ACTION_VIEW, android.net.Uri.parse(url));
        i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
        act.startActivity(i);
    }

    @Override
    public void run() {
        try {
            launch(appUrl);
        } catch (Exception e) {
            if (webUrl != null && webUrl.length() > 0) {
                try {
                    launch(webUrl);
                } catch (Exception ignored) {
                }
            }
        }
    }
}

/** 以 root 执行一条命令（有 root 才有用）。 */
class RootTask implements Runnable {

    private static final String[] SU_PATHS = {
            "/debug_ramdisk/su", "/system/bin/su", "/sbin/su", "/system/xbin/su", "su"
    };

    private final String cmd;

    RootTask(String cmd) {
        this.cmd = cmd;
    }

    @Override
    public void run() {
        for (String su : SU_PATHS) {
            try {
                Process p = Runtime.getRuntime().exec(new String[]{su, "-c", cmd});
                BufferedReader r = new BufferedReader(new InputStreamReader(p.getInputStream()));
                BufferedReader e = new BufferedReader(new InputStreamReader(p.getErrorStream()));
                String line;
                while ((line = r.readLine()) != null) {
                }
                while ((line = e.readLine()) != null) {
                }
                if (p.waitFor() == 0) {
                    return;
                }
            } catch (Throwable ignored) {
            }
        }
    }
}

/** 延迟后重新加载。 */
class DelayReload implements Runnable {

    private final MainActivity act;

    DelayReload(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.reloadPage();
    }
}

/** 主线程 Toast。 */
class UiToast implements Runnable {

    private final MainActivity act;
    private final String text;

    UiToast(MainActivity a, String t) {
        this.act = a;
        this.text = t;
    }

    @Override
    public void run() {
        Toast.makeText(act, text, Toast.LENGTH_SHORT).show();
    }
}

/** 打开无障碍设置页。 */
class A11yOpener implements Runnable {

    private final MainActivity act;
    private final boolean detail;

    A11yOpener(MainActivity a, boolean detail) {
        this.act = a;
        this.detail = detail;
    }

    @Override
    public void run() {
        try {
            android.content.Intent i;
            if (detail) {
                i = new android.content.Intent(
                        android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS);
                i.putExtra(":settings:fragment_args_key",
                        "com.botagent/com.botagent.A11yService");
                i.putExtra(":settings:show_fragment_args", "");
            } else {
                i = new android.content.Intent(
                        android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS);
            }
            i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
            act.startActivity(i);
        } catch (Exception e) {
            try {
                android.content.Intent i2 = new android.content.Intent(
                        android.provider.Settings.ACTION_ACCESSIBILITY_SETTINGS);
                i2.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK);
                act.startActivity(i2);
            } catch (Exception ignored) {
            }
        }
    }
}

/** 在主线程里调 JS（webkit 只能在 UI 线程用）。 */
class UiEval implements Runnable {

    private final MainActivity act;
    private final String kind;
    private final String msg;

    UiEval(MainActivity a, String kind, String msg) {
        this.act = a;
        this.kind = kind;
        this.msg = msg;
    }

    @Override
    public void run() {
        try {
            String js;
            if ("rtlog".equals(kind)) {
                js = "window.rtLog && window.rtLog(" + jsStr(msg) + ")";
            } else if ("rtdone".equals(kind)) {
                js = "window.rtDone && window.rtDone(" + jsStr(msg) + ")";
            } else {
                js = "window.refreshAll && window.refreshAll()";
            }
            act.web.evaluateJavascript(js, null);
        } catch (Exception ignored) {
        }
    }

    private static String jsStr(String s) {
        if (s == null) {
            return "''";
        }
        StringBuilder b = new StringBuilder("'");
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '\\' || c == '\'') {
                b.append('\\').append(c);
            } else if (c == '\n') {
                b.append("\\n");
            } else if (c == '\r') {
                b.append("");
            } else {
                b.append(c);
            }
        }
        return b.append("'").toString();
    }
}

/** 主线程打开 Termux。 */
class TermuxOpener implements Runnable {

    private final MainActivity act;

    TermuxOpener(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.openTermux();
    }
}

/** 主线程请求忽略电池优化。 */
class BatteryRequester implements Runnable {

    private final MainActivity act;

    BatteryRequester(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.requestBattery();
    }
}

/** 主线程打开系统设置页（自启动 / 应用详情）。 */
class SettingsOpener implements Runnable {

    private final MainActivity act;
    private final boolean autoStart;

    SettingsOpener(MainActivity a, boolean auto) {
        this.act = a;
        this.autoStart = auto;
    }

    @Override
    public void run() {
        if (autoStart) {
            act.openAutoStart();
        } else {
            act.openAppSettings();
        }
    }
}

/** 建容器（后台线程）。 */
class ContainerMaker implements Runnable {

    private final MainActivity act;

    ContainerMaker(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.uiLog("容器：开始创建");
        String err = act.container().create(act);
        if (err == null || err.length() == 0) {
            act.uiLog("容器：创建完成");
        } else {
            act.uiLog("容器：" + err);
        }
        act.uiRefresh();
    }
}

/** 在容器里跑一条命令。 */
class ContainerRunner implements Runnable {

    private final MainActivity act;
    private final String cmdline;

    ContainerRunner(MainActivity a, String cmd) {
        this.act = a;
        this.cmdline = cmd == null ? "" : cmd.trim();
    }

    @Override
    public void run() {
        if (cmdline.length() == 0) {
            act.uiLog("容器：命令为空");
            return;
        }
        act.uiLog("容器$ " + cmdline);
        act.container().run(new String[]{"/bin/sh", "-c", cmdline}, 300, act);
        act.uiRefresh();
    }
}

/** 主线程打开文件选择器。 */
class DebPicker implements Runnable {

    private final MainActivity act;

    DebPicker(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.pickDeb();
    }
}

/** 后台线程：把选中的文件拷进容器并安装。 */
class DebImporter implements Runnable {

    private final MainActivity act;
    private final android.net.Uri uri;

    DebImporter(MainActivity a, android.net.Uri u) {
        this.act = a;
        this.uri = u;
    }

    @Override
    public void run() {
        try {
            String name = "package.deb";
            try {
                String seg = uri.getLastPathSegment();
                if (seg != null && seg.endsWith(".deb")) {
                    name = seg.substring(seg.lastIndexOf('/') + 1);
                }
            } catch (Exception ignored) {
            }
            act.uiLog("容器：导入 " + name);
            java.io.InputStream in = act.getContentResolver().openInputStream(uri);
            if (in == null) {
                act.uiLog("容器：读不到这个文件");
                return;
            }
            String guest = act.container().importFile(in, name, act);
            if (guest == null) {
                return;
            }
            act.uiLog("容器：开始安装（可能要一两分钟）");
            act.container().installDeb(guest, act);
            act.uiLog("容器：安装流程结束");
            act.uiRefresh();
        } catch (Exception e) {
            act.uiLog("容器：导入失败 " + e);
        }
    }
}

/** 主线程打开文件选择器（扩展包）。 */
class ExtPicker implements Runnable {

    private final MainActivity act;

    ExtPicker(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.extImport();
    }
}

/** 导入扩展包：把用户选的文件放进扩展目录。 */
class ExtImporter implements Runnable {

    private final MainActivity act;
    private final android.net.Uri uri;

    ExtImporter(MainActivity a, android.net.Uri u) {
        this.act = a;
        this.uri = u;
    }

    @Override
    public void run() {
        try {
            Extension e = act.qqExt();
            e.dir().mkdirs();
            e.writeScripts();
            String name = "payload.deb";
            try {
                String seg = uri.getLastPathSegment();
                if (seg != null) {
                    String tail = seg.substring(seg.lastIndexOf('/') + 1);
                    if (tail.length() > 0) {
                        name = tail;
                    }
                }
            } catch (Exception ignored) {
            }
            act.uiLog("扩展：导入 " + name);
            java.io.InputStream in = act.getContentResolver().openInputStream(uri);
            if (in == null) {
                act.uiLog("扩展：读不到文件");
                return;
            }
            java.io.File dst = new java.io.File(e.dir(), name);
            java.io.FileOutputStream out = new java.io.FileOutputStream(dst);
            byte[] b = new byte[1 << 16];
            int n;
            long got = 0;
            while ((n = in.read(b)) > 0) {
                out.write(b, 0, n);
                got += n;
            }
            in.close();
            out.close();
            act.uiLog("扩展：已放进扩展目录（" + (got / 1048576) + " MB）");
            act.uiRefresh();
        } catch (Exception ex) {
            act.uiLog("扩展：导入失败 " + ex);
        }
    }
}

/** 在容器里装扩展。 */
class ExtInstaller implements Runnable {

    private final MainActivity act;

    ExtInstaller(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        Extension e = act.qqExt();
        e.writeScripts();
        java.io.File p = e.payload();
        if (p == null) {
            act.uiLog("扩展：还没放安装包（点「导入安装包」）");
            return;
        }
        Container c = act.container();
        if (!c.ready()) {
            act.uiLog("扩展：先建容器");
            return;
        }
        act.uiLog("扩展：放入安装包…");
        c.push(p, "payload.deb", act);
        act.uiLog("扩展：开始安装（第一次会比较久）");
        c.run(new String[]{"/bin/sh", "-c",
                "mkdir -p /tmp/ext && cp -f "
                        + "/tmp/payload.deb /tmp/ext/payload.deb 2>/dev/null || true"}, 120, null);
        c.push(e.dir() != null ? new java.io.File(e.dir(), "install.sh") : null,
                "ext-install.sh", null);
        String out = c.run(new String[]{"/bin/sh", "/tmp/ext-install.sh"}, 1800, act);
        boolean ok = out != null && out.contains("QQ_DIR_OK");
        e.markInstalled(ok);
        act.uiLog(ok ? "扩展：安装完成" : "扩展：安装可能没成功，看上面日志");
        act.uiRefresh();
    }
}

/** 启动/停止/状态。 */
class ExtRunner implements Runnable {

    private final MainActivity act;
    private final String what;

    ExtRunner(MainActivity a, String what) {
        this.act = a;
        this.what = what;
    }

    @Override
    public void run() {
        Extension e = act.qqExt();
        Container c = act.container();
        if (!c.ready()) {
            act.uiLog("扩展：先建容器");
            return;
        }
        try {
            java.io.File script = new java.io.File(e.dir(), what + ".sh");
            c.push(script, "ext-" + what + ".sh", null);
            act.uiLog("扩展：" + what);
            c.run(new String[]{"/bin/sh", "/tmp/ext-" + what + ".sh"}, 300, act);
            act.uiRefresh();
        } catch (Exception ex) {
            act.uiLog("扩展：" + what + " 失败 " + ex);
        }
    }
}

/** 下载 NapCat 官方包（校验 sha256）装进容器。 */
class NapCatInstaller implements Runnable {

    private static String trimErr(String msg) {
        if (msg == null) {
            return "";
        }
        String one = msg.replace('\n', ' ');
        return one.length() > 90 ? one.substring(0, 90) : one;
    }

    private final MainActivity act;

    NapCatInstaller(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        try {
            Container c = act.container();
            if (!c.ready()) {
                act.uiLog("NapCat：先建容器（⑥）");
                return;
            }
            Extension e = act.qqExt();
            e.dir().mkdirs();
            e.writeScripts();

            java.io.File zip = new java.io.File(act.getCacheDir(), "napcat.zip");
            // ① 先用 App 里自带的官方包（离线可用，最快）
            if (!zip.exists() || zip.length() < 30 * 1024 * 1024
                    || !Extension.NAPCAT_SHA256.equalsIgnoreCase(sha256(zip))) {
                try {
                    act.uiLog("NapCat：使用 App 内置的官方包 " + Extension.NAPCAT_VER);
                    java.io.InputStream in = act.getAssets().open("napcat/NapCat.Shell.zip");
                    java.io.FileOutputStream out = new java.io.FileOutputStream(zip);
                    byte[] b = new byte[1 << 16];
                    int n;
                    long got = 0;
                    while ((n = in.read(b)) > 0) {
                        out.write(b, 0, n);
                        got += n;
                    }
                    in.close();
                    out.close();
                    act.uiLog("NapCat：内置包已解出 " + (got / 1048576) + " MB");
                } catch (Exception ex0) {
                    act.uiLog("NapCat：内置包不可用（" + ex0 + "）");
                }
            }
            boolean need = true;
            if (zip.exists() && zip.length() > 30 * 1024 * 1024) {
                String h = sha256(zip);
                if (Extension.NAPCAT_SHA256.equalsIgnoreCase(h)) {
                    need = false;
                    act.uiLog("NapCat：本地已有校验通过的包");
                }
            }
            if (need) {
                act.uiLog("NapCat：下载官方包 " + Extension.NAPCAT_VER + "（约 34 MB）");
                // 直连优先，失败再走加速镜像。无论哪条路，最后都按官方 sha256 校验。
                String[] tries = {
                        Extension.NAPCAT_URL,
                        "https://ghfast.top/" + Extension.NAPCAT_URL,
                        "https://gh-proxy.com/" + Extension.NAPCAT_URL,
                        "https://ghproxy.net/" + Extension.NAPCAT_URL,
                };
                boolean got = false;
                for (int i = 0; i < tries.length && !got; i++) {
                    String label = i == 0 ? "官方直连" : "镜像 " + i;
                    act.uiLog("NapCat：尝试" + label);
                    String err = download(tries[i], zip, act);
                    if (err != null) {
                        act.uiLog("NapCat：" + label + " 失败（" + trimErr(err) + "）");
                        zip.delete();
                        continue;
                    }
                    String h = sha256(zip);
                    if (!Extension.NAPCAT_SHA256.equalsIgnoreCase(h)) {
                        act.uiLog("NapCat：" + label + " 校验不通过，已丢弃");
                        zip.delete();
                        continue;
                    }
                    act.uiLog("NapCat：" + label + " 下载并校验通过");
                    got = true;
                }
                if (!got) {
                    act.uiLog("NapCat：所有下载方式都失败了。"
                            + "可以在电脑上下好 NapCat.Shell.zip，用「导入 NapCat 包」放进来。");
                    return;
                }
            }
            // 直接在 App 这边解压到容器目录（不依赖容器里的 unzip）
            java.io.File dest = new java.io.File(c.dir(), "opt/napcat");
            dest.mkdirs();
            int files = unzipTo(zip, dest);
            act.uiLog("NapCat：已解出 " + files + " 个文件到容器");

            c.push(new java.io.File(e.dir(), "napcat-install.sh"), "napcat-install.sh", null);
            act.uiLog("NapCat：开始装运行环境");
            String out = c.run(new String[]{"/bin/sh", "/tmp/napcat-install.sh"}, 900, act);
            // 判定不看日志文本（会被截断），直接查文件真的到位没有
            String chk = c.run(new String[]{"/bin/sh", "-c",
                    "test -d /opt/QQ/resources/app/napcat && "
                    + "test -f /opt/QQ/resources/app/loadNapCat.cjs && "
                    + "grep -q loadNapCat /opt/QQ/resources/app/package.json "
                    + "&& echo NAP_INSTALLED || echo NAP_MISSING"}, 60, act);
            boolean ok = chk != null && chk.contains("NAP_INSTALLED");
            act.uiLog(ok ? "NapCat：安装完成，可以点「启动协议端」" 
                         : "NapCat：没装好，看上面日志");
            act.uiRefresh();
        } catch (Throwable t) {
            act.uiLog("NapCat：出错 " + t);
        }
    }

    /** 把 zip 解到指定目录（Java 自带解压，容器里不需要 unzip）。 */
    private static int unzipTo(java.io.File zip, java.io.File dest) throws Exception {
        int n = 0;
        java.util.zip.ZipInputStream zis =
                new java.util.zip.ZipInputStream(
                        new java.io.BufferedInputStream(new java.io.FileInputStream(zip), 1 << 16));
        byte[] buf = new byte[1 << 16];
        String rootPath = dest.getCanonicalPath();
        java.util.zip.ZipEntry en;
        while ((en = zis.getNextEntry()) != null) {
            String name = en.getName();
            if (name == null || name.length() == 0 || name.endsWith("/")) {
                continue;
            }
            java.io.File f = new java.io.File(dest, name);
            if (!f.getCanonicalPath().startsWith(rootPath)) {
                continue;
            }
            java.io.File parent = f.getParentFile();
            if (parent != null) {
                parent.mkdirs();
            }
            java.io.FileOutputStream out = new java.io.FileOutputStream(f);
            int r;
            while ((r = zis.read(buf)) > 0) {
                out.write(buf, 0, r);
            }
            out.close();
            f.setExecutable(true, false);
            n++;
        }
        zis.close();
        return n;
    }

    private static String sha256(java.io.File f) {
        try {
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            java.io.FileInputStream in = new java.io.FileInputStream(f);
            byte[] b = new byte[1 << 16];
            int n;
            while ((n = in.read(b)) > 0) {
                md.update(b, 0, n);
            }
            in.close();
            StringBuilder sb = new StringBuilder();
            for (byte x : md.digest()) {
                sb.append(String.format("%02x", x));
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private String download(String url, java.io.File dst, MainActivity ui) {
        java.net.HttpURLConnection conn = null;
        try {
            conn = (java.net.HttpURLConnection) new java.net.URL(url).openConnection();
            conn.setConnectTimeout(20000);
            conn.setReadTimeout(60000);
            conn.setInstanceFollowRedirects(true);
            conn.setRequestProperty("User-Agent", "Botagent");
            int code = conn.getResponseCode();
            if (code != 200) {
                return "下载失败 HTTP " + code;
            }
            long total = conn.getContentLengthLong();
            java.io.InputStream in = conn.getInputStream();
            java.io.FileOutputStream out = new java.io.FileOutputStream(dst);
            byte[] b = new byte[1 << 16];
            int n;
            long got = 0;
            long last = 0;
            while ((n = in.read(b)) > 0) {
                out.write(b, 0, n);
                got += n;
                long now = System.currentTimeMillis();
                if (ui != null && now - last > 2000) {
                    last = now;
                    ui.uiLog("NapCat 下载 " + (got / 1048576) + " / " + (total / 1048576) + " MB");
                }
            }
            in.close();
            out.close();
            return null;
        } catch (Exception e) {
            return "下载失败：" + e;
        } finally {
            if (conn != null) {
                conn.disconnect();
            }
        }
    }
}

/** 跑扩展目录里的任意脚本（NapCat 用）。 */
class ExtRunner2 implements Runnable {

    private final MainActivity act;
    private final String script;

    private final int timeoutSec;

    ExtRunner2(MainActivity a, String script) {
        this(a, script, 600);
    }

    ExtRunner2(MainActivity a, String script, int timeout) {
        this.act = a;
        this.script = script;
        this.timeoutSec = timeout;
    }

    @Override
    public void run() {
        try {
            android.util.Log.i("botagent", "ExtRunner2 run script=" + script);
            Extension e = act.qqExt();
            e.writeScripts();
            android.util.Log.i("botagent", "writeScripts done, dir=" + e.dir());
            Container c = act.container();
            if (!c.ready()) {
                act.uiLog("先建容器");
                return;
            }
            c.push(new java.io.File(e.dir(), script + ".sh"), "run-" + script + ".sh", null);
            act.uiLog("执行 " + script);
            c.run(new String[]{"/bin/sh", "/tmp/run-" + script + ".sh"}, timeoutSec, act);
            act.uiRefresh();
        } catch (Exception ex) {
            act.uiLog(script + " 失败：" + ex);
        }
    }
}

/** 原生导航：上一步。 */
class NavPrev implements android.view.View.OnClickListener {

    private final MainActivity act;

    NavPrev(MainActivity a) {
        this.act = a;
    }

    @Override
    public void onClick(android.view.View v) {
        try {
            act.web.evaluateJavascript("window.wzPrev && window.wzPrev()", null);
        } catch (Throwable ignored) {
        }
    }
}

/** 原生导航：下一步。 */
class NavNext implements android.view.View.OnClickListener {

    private final MainActivity act;

    NavNext(MainActivity a) {
        this.act = a;
    }

    @Override
    public void onClick(android.view.View v) {
        try {
            act.web.evaluateJavascript("window.wzNext && window.wzNext()", null);
        } catch (Throwable ignored) {
        }
    }
}

/** 同步导航状态（在主线程）。 */
class NavSync implements Runnable {

    private final MainActivity act;
    private final int step;
    private final int total;

    NavSync(MainActivity a, int s, int t) {
        this.act = a;
        this.step = s;
        this.total = t;
    }

    @Override
    public void run() {
        if (act.navBar == null) {
            return;
        }
        boolean done = step > total;
        act.navBar.setVisibility(android.view.View.VISIBLE);
        act.prevBtn.setVisibility(step <= 1 ? android.view.View.GONE : android.view.View.VISIBLE);
        act.nextBtn.setText(done ? "进入控制台" : (step >= total ? "完成" : "下一步"));
    }
}

/** 显示/隐藏导航条（在主线程）。 */
class NavToggle implements Runnable {

    private final MainActivity act;
    private final boolean on;

    NavToggle(MainActivity a, boolean on) {
        this.act = a;
        this.on = on;
    }

    @Override
    public void run() {
        if (act.navBar != null) {
            act.navBar.setVisibility(on ? android.view.View.VISIBLE : android.view.View.GONE);
        }
    }
}

/** 从控制台回到向导页。 */
class SetupOpener implements Runnable {

    private final MainActivity act;

    SetupOpener(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        act.backToSetup();
    }
}

/** 一键启动：先起协议端，等 6099 起来，再起机器人，等控制台端口起来。 */
class StartAllTask implements Runnable {

    private final MainActivity act;

    StartAllTask(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        try {
            if (!act.container().ready()) {
                act.uiLog("一键启动：还没有容器，先去第 3 步创建");
                return;
            }
            if (!MainActivity.portOpen(6099, 300)) {
                act.uiLog("① 启动协议端（QQ + NapCat）…");
                new Thread(new ExtRunner2(act, "napcat-run", 86400)).start();
                for (int i = 0; i < 36; i++) {
                    Thread.sleep(2500);
                    if (MainActivity.portOpen(6099, 400)) {
                        act.uiLog("   协议端就绪（6099）");
                        break;
                    }
                }
                if (!MainActivity.portOpen(6099, 400)) {
                    act.uiLog("   协议端没起来：看第 3 步日志；可能是 QQ 包没导入");
                    return;
                }
            } else {
                act.uiLog("① 协议端已在运行");
            }

            if (!BotService.running) {
                act.uiLog("② 启动机器人…");
                act.startRuntime(false);
                for (int i = 0; i < 30; i++) {
                    Thread.sleep(2000);
                    int p = RuntimeManager.port > 0 ? RuntimeManager.port : 8080;
                    if (MainActivity.portOpen(p, 400)) {
                        act.uiLog("   控制台就绪（" + p + "）");
                        break;
                    }
                }
            } else {
                act.uiLog("② 机器人已在运行");
            }

            boolean ok = MainActivity.portOpen(RuntimeManager.port > 0
                    ? RuntimeManager.port : 8080, 500);
            act.runOnUiThread(new StartAllDone(act, ok));
        } catch (Throwable t) {
            act.uiLog("一键启动出错：" + t);
        }
    }
}

/** 一键启动结束后回到 UI 线程提示。 */
class StartAllDone implements Runnable {

    private final MainActivity act;
    private final boolean ok;

    StartAllDone(MainActivity a, boolean ok) {
        this.act = a;
        this.ok = ok;
    }

    @Override
    public void run() {
        android.widget.Toast.makeText(act,
                ok ? "都起来了，去「进入控制台」" : "有东西没起来，点「自检」看看",
                android.widget.Toast.LENGTH_LONG).show();
        try {
            act.web.evaluateJavascript(
                    "window.refreshAll && window.refreshAll()", null);
        } catch (Throwable ignored) {
        }
    }
}

/** 离线装依赖：/sdcard/botagent-deps → 容器 /tmp/deps → dpkg -i */
class OfflineDepsTask implements Runnable {

    private final MainActivity act;

    OfflineDepsTask(MainActivity a) {
        this.act = a;
    }

    @Override
    public void run() {
        try {
            java.io.File dir = new java.io.File("/sdcard/botagent-deps");
            if (!dir.isDirectory()) {
                act.uiLog("没找到 /sdcard/botagent-deps（先把这个文件夹拷进手机）");
                return;
            }
            java.io.File[] debs = dir.listFiles();
            int n = 0;
            if (debs != null) {
                for (java.io.File f : debs) {
                    if (f.isFile() && f.getName().endsWith(".deb")) {
                        n++;
                    }
                }
            }
            if (n == 0) {
                act.uiLog("/sdcard/botagent-deps 里没有 .deb");
                return;
            }
            act.uiLog("离线依赖：发现 " + n + " 个 deb，开始传进容器…");

            Container c = act.container();
            c.run(new String[]{"/bin/sh", "-c", "mkdir -p /tmp/deps"}, 60, null);

            int pushed = 0;
            for (java.io.File f : debs) {
                if (!f.isFile() || !f.getName().endsWith(".deb")) {
                    continue;
                }
                c.push(f, "deps/" + f.getName(), act);
                pushed++;
                if (pushed % 20 == 0) {
                    act.uiLog("  已传 " + pushed + "/" + n);
                }
            }
            act.uiLog("  传输完成：" + pushed + " 个");

            act.uiLog("开始 dpkg 安装（离线，不联网）…");
            c.run(new String[]{"/bin/sh", "/tmp/offline-deps.sh"}, 1800, act);
            act.uiLog("离线依赖安装结束，看上面结果");
        } catch (Throwable t) {
            act.uiLog("离线装依赖出错：" + t);
        }
    }
}
