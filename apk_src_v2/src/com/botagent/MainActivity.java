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
        web.loadUrl(CONSOLE_URL);
    }

    void backToSetup() {
        onConsole = false;
        web.loadUrl(SETUP_URL);
    }

    void reloadPage() {
        if (onConsole) {
            web.loadUrl(CONSOLE_URL);
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
        return new File(getFilesDir(), "config.json");
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

    String saveConfig(String qq, String apiKey) {
        try {
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
            int uid = Integer.parseInt(owner);
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

    boolean astrbotInstalled() {
        try {
            getPackageManager().getPackageInfo("com.astrbot.astrbot_android", 0);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    boolean runtimeReady() {
        String[] paths = {
                getFilesDir() + "/rootfs/usr/bin/python3",
                getFilesDir() + "/runtime/bin/python3",
                getFilesDir() + "/python/bin/python3",
        };
        for (String p : paths) {
            if (new File(p).exists()) {
                return true;
            }
        }
        return false;
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
    public boolean runtimeReady() {
        return act.runtimeReady();
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
