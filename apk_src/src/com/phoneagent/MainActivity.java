package com.phoneagent;

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
import java.io.InputStreamReader;

/**
 * PhoneAgent 手机端 App：全屏 WebView 加载本机 8080 的 /app 页面。
 * 服务没起来时显示离线兜底页，可一键用 root 拉起服务。
 *
 * 注意：这里刻意不用匿名内部类（javac 21 + 老版本 d8 会在 $1.class 上报 NPE），
 * 全部改用顶层命名类。
 */
public class MainActivity extends Activity {

    static final String DEFAULT_URL = "http://127.0.0.1:8080/app";

    WebView web;
    boolean offlineShown = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        try {
            s.setMixedContentMode(WebSettings.MIXED_CONTENT_ALWAYS_ALLOW);
        } catch (Throwable ignored) {
        }

        // 深色底，避免滚动回弹/加载时露出白边
        web.setBackgroundColor(0xFF0D1117);
        web.setLayerType(android.view.View.LAYER_TYPE_HARDWARE, null);
        web.setWebViewClient(new PageClient(this));
        web.addJavascriptInterface(new Bridge(this), "Android");
        getWindow().setBackgroundDrawable(
                new android.graphics.drawable.ColorDrawable(0xFF0D1117));
        setContentView(web);
        web.loadUrl(DEFAULT_URL);
    }

    void showOffline() {
        if (offlineShown) {
            return;
        }
        offlineShown = true;
        String html = "<!doctype html><html><head><meta charset=utf-8>"
                + "<meta name=viewport content='width=device-width,initial-scale=1'>"
                + "<style>"
                + "body{background:#0d1117;color:#e6edf3;font-family:system-ui,sans-serif;"
                + "padding:26px;text-align:center;margin:0}"
                + "h3{color:#f85149;margin:18px 0 8px}"
                + "p{color:#8b949e;font-size:14px;line-height:1.6}"
                + ".b{display:block;width:100%;padding:17px;margin:12px 0;border:0;border-radius:13px;"
                + "background:#238636;color:#fff;font-size:16px;font-weight:600}"
                + ".g{background:#1f6feb}"
                + "#o{color:#8b949e;font-size:12px;white-space:pre-wrap;text-align:left;margin-top:18px}"
                + "</style></head><body>"
                + "<h3>本地服务未响应</h3>"
                + "<p>PhoneAgent 的 WebUI（8080 端口）没有运行。<br>"
                + "点下面的按钮，App 会用 root 帮你把它拉起来。</p>"
                + "<button class=b onclick=\"Android.startServices()\">启动本地服务</button>"
                + "<button class='b g' onclick=\"Android.reload()\">重新连接</button>"
                + "<div id=o></div>"
                + "</body></html>";
        web.loadDataWithBaseURL("http://127.0.0.1/", html, "text/html", "UTF-8", null);
    }

    void reloadPage() {
        offlineShown = false;
        web.loadUrl(DEFAULT_URL);
    }

    void startServices() {
        new Thread(new RootTask(
                "sh /data/local/tmp/start_webui.sh; sleep 5; sh /data/local/tmp/start_bot.sh")).start();
        new Handler(Looper.getMainLooper()).postDelayed(new DelayReload(this), 11000);
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK && web != null && web.canGoBack()) {
            web.goBack();
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }
}

/** WebView 客户端：主框架加载失败时切到离线页。 */
class PageClient extends WebViewClient {

    private final MainActivity act;

    PageClient(MainActivity a) {
        this.act = a;
    }

    /** 统一处理外链：站内留在 WebView，B 站直接跳 App，其它交给系统。 */
    private boolean handleUrl(String url) {
        if (url == null) return false;
        if (url.startsWith("http://127.0.0.1") || url.startsWith("http://localhost")) {
            return false;   // 控制台页面本身
        }

        // 其它外链：交给系统（可能是浏览器）
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
    public boolean shouldOverrideUrlLoading(WebView view, android.webkit.WebResourceRequest request) {
        try {
            return handleUrl(request.getUrl().toString());
        } catch (Exception e) {
            return false;
        }
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        act.offlineShown = false;
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        if (request == null || request.isForMainFrame()) {
            act.showOffline();
        }
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onReceivedError(WebView view, int errorCode, String description, String failingUrl) {
        act.showOffline();
    }
}

/** 暴露给网页的 JS 接口（window.Android.xxx）。 */
class Bridge {

    private final MainActivity act;

    Bridge(MainActivity a) {
        this.act = a;
    }

    @JavascriptInterface
    public void startServices() {
        act.startServices();
    }

    @JavascriptInterface
    public void reload() {
        act.reloadPage();
    }

    @JavascriptInterface
    public void toast(String text) {
        act.runOnUiThread(new UiToast(act, text));
    }

    /**
     * 打开外部链接：优先用 App scheme（bilibili://space/123），
     * 没装对应 App 就退回网页。
     */
    @JavascriptInterface
    public void openApp(String appUrl, String webUrl) {
        act.runOnUiThread(new AppOpener(act, appUrl, webUrl));
    }
}

/** 以 root 执行一条命令（丢弃输出，避免管道阻塞）。 */
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

class RootTask implements Runnable {

    // Magisk 的 su 常见位置（/system/bin/su 在部分机型/版本上不存在）
    private static final String[] SU_PATHS = {
            "/debug_ramdisk/su",
            "/system/bin/su",
            "/sbin/su",
            "/system/xbin/su",
            "su"
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
                    // drain stdout
                }
                while ((line = e.readLine()) != null) {
                    // drain stderr
                }
                int rc = p.waitFor();
                if (rc == 0) {
                    return;
                }
            } catch (Throwable ignored) {
                // 试下一个路径
            }
        }
    }
}

/** 延迟后重新加载页面。 */
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

/** 主线程弹 Toast。 */
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
