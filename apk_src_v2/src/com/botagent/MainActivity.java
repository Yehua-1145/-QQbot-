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

    static final String SETUP_URL = "file:///android_asset/setup.html";
    static final String CONSOLE_URL = "http://127.0.0.1:8080/app";

    WebView web;
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

        web.setBackgroundColor(0xFF0D1117);
        web.setWebViewClient(new PageClient(this));
        web.addJavascriptInterface(new Bridge(this), "Android");
        getWindow().setBackgroundDrawable(
                new android.graphics.drawable.ColorDrawable(0xFF0D1117));
        setContentView(web);
        web.loadUrl(SETUP_URL);
    }

    // ---------- 页面切换 ----------
    void openConsole() {
        onConsole = true;
        int p = RuntimeManager.port > 0 ? RuntimeManager.port : 8080;
        web.loadUrl("http://127.0.0.1:" + p + "/app");
    }

    void backToSetup() {
        onConsole = false;
        web.loadUrl(SETUP_URL);
    }

    void reloadPage() {
        if (onConsole) {
            int p = RuntimeManager.port > 0 ? RuntimeManager.port : 8080;
            web.loadUrl("http://127.0.0.1:" + p + "/app");
        } else {
            web.loadUrl(SETUP_URL);
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
