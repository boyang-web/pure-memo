package com.baiyang.purememo;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.pm.ApplicationInfo;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsetsController;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.HashMap;
import java.util.Map;

/**
 * 纯粹的 WebView 壳：把 APK 里的 assets/ 当作一个 https:// 站点来服务。
 *
 * <p>用 https://appassets.androidplatform.net/ 而不是 file:///android_asset/ 的原因：
 * localStorage、crypto.randomUUID 等能力在 file:// 下 origin 是 opaque 的，行为不稳定；
 * 虚拟域名给出的 origin 是稳定的 https，与浏览器里访问时一致。
 *
 * <p>Service Worker 在壳里没有意义（资源本来就随包分发，也不会更新），
 * 因此 /sw.js 直接回 404，页面里的注册会静默失败。
 */
public class MainActivity extends Activity {

    private static final String HOST = "appassets.androidplatform.net";
    private static final String BASE_URL = "https://" + HOST + "/";
    private static final String FALLBACK_URL = "file:///android_asset/index.html";

    /** 与页面默认主题（data-theme="dark"）的背景色一致，避免启动白闪。 */
    private static final int DEFAULT_BAR = 0xFF080B13;

    /** 页面把 meta[name=theme-color] 的变化同步到系统状态栏，切主题时不留色差。 */
    private static final String INJECT_SYNC_BARS =
            "(function(){"
            + "var m=document.querySelector('meta[name=theme-color]');"
            + "function sync(){if(!m||!m.content)return;"
            + "try{window.PureMemoShell.setBarColor(m.content)}catch(e){}}"
            + "sync();"
            + "if(window.MutationObserver&&m){"
            + "new MutationObserver(sync).observe(m,{attributes:true,attributeFilter:['content']});}"
            + "document.addEventListener('visibilitychange',sync);"
            + "})();";

    private WebView web;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);

        web = new WebView(this);
        web.setBackgroundColor(DEFAULT_BAR);
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);          // localStorage：卡片全靠它持久化
        s.setAllowFileAccess(true);            // 仅用于主文档加载失败时的兜底
        s.setAllowContentAccess(false);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setTextZoom(100);                    // 不跟随系统字体缩放，避免布局错位
        s.setUseWideViewPort(true);
        s.setLoadWithOverviewMode(false);
        s.setMediaPlaybackRequiresUserGesture(true);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            s.setForceDark(WebSettings.FORCE_DARK_OFF);   // 主题由页面自己管
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            s.setAlgorithmicDarkeningAllowed(false);
        }

        web.addJavascriptInterface(new ShellBridge(), "PureMemoShell");
        web.setWebViewClient(new AssetClient());
        // 只有调试包允许远程调试，正式包关闭
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }

        web.setLayoutParams(new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(web);

        applyBars(DEFAULT_BAR);

        if (state == null) {
            web.loadUrl(BASE_URL);
        } else {
            web.restoreState(state);
        }
    }

    /** 把虚拟域名下的请求映射到 assets/。 */
    private WebResourceResponse serveAsset(Uri url) {
        if (url == null || !HOST.equals(url.getHost())) return null;

        String path = url.getPath();
        if (path == null || path.isEmpty() || "/".equals(path)) path = "/index.html";
        String name = path.substring(1);

        if ("sw.js".equals(name)) return notFound();

        InputStream in;
        try {
            in = getAssets().open(name);
        } catch (IOException e) {
            return notFound();
        }

        Map<String, String> headers = new HashMap<>();
        headers.put("Cache-Control", "no-store");
        return new WebResourceResponse(mimeOf(name), encodingOf(name), 200, "OK", headers, in);
    }

    private static WebResourceResponse notFound() {
        return new WebResourceResponse("text/plain", "utf-8", 404, "Not Found",
                new HashMap<String, String>(), new ByteArrayInputStream(new byte[0]));
    }

    private static String mimeOf(String name) {
        String lower = name.toLowerCase(java.util.Locale.ROOT);
        if (lower.endsWith(".html") || lower.endsWith(".htm")) return "text/html";
        if (lower.endsWith(".js")) return "application/javascript";
        if (lower.endsWith(".css")) return "text/css";
        if (lower.endsWith(".json")) return "application/json";
        if (lower.endsWith(".webmanifest")) return "application/manifest+json";
        if (lower.endsWith(".svg")) return "image/svg+xml";
        if (lower.endsWith(".png")) return "image/png";
        if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
        if (lower.endsWith(".webp")) return "image/webp";
        if (lower.endsWith(".ico")) return "image/x-icon";
        return "application/octet-stream";
    }

    private static String encodingOf(String name) {
        String mime = mimeOf(name);
        boolean text = mime.startsWith("text/") || mime.endsWith("javascript")
                || mime.endsWith("json") || mime.endsWith("svg+xml");
        return text ? "utf-8" : null;
    }

    private void applyBars(int color) {
        getWindow().setStatusBarColor(color);
        getWindow().setNavigationBarColor(color);

        // 浅背景配深色图标，深背景配浅色图标
        boolean darkIcons = luminance(color) > 0.6;

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                int mask = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                        | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                c.setSystemBarsAppearance(darkIcons ? mask : 0, mask);
            }
        } else {
            int flags = getWindow().getDecorView().getSystemUiVisibility();
            if (darkIcons) {
                flags |= View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            } else {
                flags &= ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                if (darkIcons) {
                    flags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                } else {
                    flags &= ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
                }
            }
            getWindow().getDecorView().setSystemUiVisibility(flags);
        }
    }

    private static double luminance(int color) {
        return (0.2126 * Color.red(color) + 0.7152 * Color.green(color)
                + 0.0722 * Color.blue(color)) / 255.0;
    }

    private static int parseColor(String hex) {
        if (hex == null) return 0;
        try {
            return Color.parseColor(hex.trim());
        } catch (IllegalArgumentException e) {
            return 0;
        }
    }

    private class ShellBridge {
        @JavascriptInterface
        public void setBarColor(final String hex) {
            final int color = parseColor(hex);
            if (color == 0) return;
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    applyBars(color);
                }
            });
        }
    }

    private class AssetClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
            return serveAsset(request.getUrl());
        }

        @SuppressWarnings("deprecation")
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, String url) {
            return serveAsset(Uri.parse(url));
        }

        @Override
        public void onPageFinished(WebView view, String url) {
            view.evaluateJavascript(INJECT_SYNC_BARS, null);
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (request.isForMainFrame()) view.loadUrl(FALLBACK_URL);
        }

        @SuppressWarnings("deprecation")
        @Override
        public void onReceivedError(WebView view, int code, String description, String failingUrl) {
            if (failingUrl != null && !failingUrl.startsWith("file:")) {
                view.loadUrl(FALLBACK_URL);
            }
        }
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    @Override
    protected void onPause() {
        super.onPause();
        // 触发页面自己的 flushDraftToCard：切后台时可能来不及失焦
        web.evaluateJavascript("window.dispatchEvent(new Event('pagehide'));", null);
        web.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    public void onBackPressed() {
        finish();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }
}
