package pt.jolgue.brawlroom;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.IBinder;
import android.os.Handler;
import android.os.Looper;
import android.net.Uri;
import android.util.DisplayMetrics;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class OverlayService extends Service {
    public final class MenuBridge {
        @JavascriptInterface public void collapse() { OverlayService.collapse(); }
        @JavascriptInterface public void openDashboard() { OverlayService.this.openDashboard(); }
        @JavascriptInterface public void copyText(String value) {
            if (value == null || value.length() > 4096) return;
            ClipboardManager clipboard = (ClipboardManager) getSystemService(CLIPBOARD_SERVICE);
            clipboard.setPrimaryClip(ClipData.newPlainText("Comando Termux", value));
        }
    }
    private static volatile OverlayService active;
    private WindowManager manager;
    private WindowManager.LayoutParams params;
    private LinearLayout root;
    private WebView browser;
    private TextView statusLabel;
    private String siteAddress;
    private int retries = 0;
    private boolean pageFailed = false;
    private boolean expanded = false;
    private float dragX, dragY;
    private int originX, originY;

    @Override public void onCreate() {
        super.onCreate();
        active = this;
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel("menu", "Menu Brawl Room", NotificationManager.IMPORTANCE_LOW));
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class),
                PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
        Notification notification = new Notification.Builder(this, "menu")
                .setSmallIcon(android.R.drawable.ic_menu_view).setContentTitle("Menu Brawl Room")
                .setContentText("Toca para abrir as opções do menu").setContentIntent(open).build();
        startForeground(7, notification);
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        String site = intent != null ? intent.getStringExtra("site") : null;
        if (site == null || !site.startsWith("https://")) return START_NOT_STICKY;
        siteAddress = site;
        if (root == null) makeWindow(site);
        else {
            retries = 0;
            loadMenu();
        }
        return START_STICKY;
    }

    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }

    private int[] screenSize() {
        DisplayMetrics metrics = new DisplayMetrics();
        manager.getDefaultDisplay().getRealMetrics(metrics);
        return new int[]{metrics.widthPixels, metrics.heightPixels};
    }

    private void clampPosition() {
        int[] size = screenSize();
        params.x = Math.max(0, Math.min(params.x, size[0] - params.width));
        params.y = Math.max(0, Math.min(params.y, size[1] - params.height));
    }

    private void openDashboard() {
        if (siteAddress == null) return;
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(siteAddress + "/bridge"));
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startActivity(intent);
        collapse();
    }

    private void loadMenu() {
        if (browser != null && siteAddress != null) {
            browser.loadUrl(siteAddress + "/overlay?refresh=" + System.currentTimeMillis());
        }
    }

    private void retryMenu(int errorCode) {
        if (pageFailed) return;
        pageFailed = true;
        statusLabel.setText("ERRO " + errorCode + " · ⟳");
        if (retries >= 3) return;
        long delay = 1200L << retries;
        retries++;
        final int attempt = retries;
        new Handler(Looper.getMainLooper()).postDelayed(() -> {
            if (browser != null && retries == attempt) loadMenu();
        }, delay);
    }

    private TextView text(String content, int size) {
        TextView view = new TextView(this);
        view.setText(content);
        view.setTextColor(Color.WHITE);
        view.setTextSize(size);
        view.setGravity(Gravity.CENTER);
        return view;
    }

    private void makeWindow(String site) {
        manager = (WindowManager) getSystemService(WINDOW_SERVICE);
        params = new WindowManager.LayoutParams(dp(56), dp(56),
                WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
                WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL,
                PixelFormat.TRANSLUCENT);
        params.gravity = Gravity.TOP | Gravity.START;
        params.x = dp(18);
        params.y = dp(24);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        GradientDrawable background = new GradientDrawable();
        background.setColor(Color.rgb(21, 29, 49));
        background.setCornerRadius(dp(16));
        background.setStroke(dp(1), Color.rgb(93, 115, 150));
        root.setBackground(background);
        LinearLayout bar = new LinearLayout(this);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        TextView toggle = text("✳", 26);
        bar.addView(toggle, new LinearLayout.LayoutParams(dp(56), dp(52)));
        toggle.setOnClickListener(view -> setExpanded(!expanded));
        statusLabel = text("BRAWL ROOM", 12);
        bar.addView(statusLabel, new LinearLayout.LayoutParams(0, dp(52), 1));
        TextView refresh = text("⟳", 23);
        bar.addView(refresh, new LinearLayout.LayoutParams(dp(38), dp(52)));
        refresh.setContentDescription("Atualizar menu");
        refresh.setOnClickListener(view -> {
            retries = 0;
            browser.clearCache(true);
            loadMenu();
        });
        TextView minimise = text("—", 23);
        bar.addView(minimise, new LinearLayout.LayoutParams(dp(38), dp(52)));
        minimise.setContentDescription("Recolher menu");
        minimise.setOnClickListener(view -> setExpanded(false));
        TextView close = text("✕", 20);
        bar.addView(close, new LinearLayout.LayoutParams(dp(38), dp(52)));
        close.setContentDescription("Fechar menu");
        close.setOnClickListener(view -> stopSelf());
        bar.setOnTouchListener((view, event) -> {
            if (event.getAction() == MotionEvent.ACTION_DOWN) {
                dragX = event.getRawX(); dragY = event.getRawY();
                originX = params.x; originY = params.y;
                return true;
            }
            if (event.getAction() == MotionEvent.ACTION_MOVE) {
                params.x = originX + Math.round(event.getRawX() - dragX);
                params.y = originY + Math.round(event.getRawY() - dragY);
                clampPosition();
                manager.updateViewLayout(root, params);
                return true;
            }
            return true;
        });
        root.addView(bar);
        browser = new WebView(this);
        browser.getSettings().setJavaScriptEnabled(true);
        browser.getSettings().setDomStorageEnabled(true);
        browser.getSettings().setAllowFileAccess(false);
        browser.getSettings().setCacheMode(WebSettings.LOAD_NO_CACHE);
        browser.addJavascriptInterface(new MenuBridge(), "BrawlRoom");
        CookieManager.getInstance().setAcceptCookie(true);
        browser.setWebViewClient(new WebViewClient() {
            @Override public void onPageStarted(WebView view, String url, android.graphics.Bitmap icon) {
                pageFailed = false;
                statusLabel.setText("A LIGAR...");
            }
            @Override public void onReceivedHttpError(WebView view, WebResourceRequest request,
                                                       WebResourceResponse response) {
                if (request.isForMainFrame() && response.getStatusCode() >= 500)
                    retryMenu(response.getStatusCode());
            }
            @Override public void onReceivedError(WebView view, WebResourceRequest request,
                                                   android.webkit.WebResourceError error) {
                if (request.isForMainFrame()) retryMenu(error.getErrorCode());
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!pageFailed) {
                    retries = 0;
                    statusLabel.setText("BRAWL ROOM");
                }
            }
        });
        loadMenu();
        browser.setVisibility(View.GONE);
        root.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1));
        manager.addView(root, params);
    }

    private void setExpanded(boolean value) {
        expanded = value;
        browser.setVisibility(value ? View.VISIBLE : View.GONE);
        int[] size = screenSize();
        params.width = value ? Math.min(dp(320), Math.max(dp(56), size[0] - dp(24))) : dp(56);
        params.height = value ? Math.min(dp(430), Math.max(dp(56), size[1] - dp(48))) : dp(56);
        params.flags = WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL |
                (value ? 0 : WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        clampPosition();
        manager.updateViewLayout(root, params);
    }

    @Override public void onConfigurationChanged(Configuration configuration) {
        super.onConfigurationChanged(configuration);
        if (root != null) setExpanded(expanded);
    }

    static void collapse() {
        OverlayService service = active;
        if (service != null) new Handler(Looper.getMainLooper()).post(() -> {
            if (service.root != null && service.expanded) service.setExpanded(false);
        });
    }

    @Override public void onDestroy() {
        active = null;
        if (manager != null && root != null) {
            manager.removeView(root);
            root = null;
        }
        if (browser != null) { browser.destroy(); browser = null; }
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) { return null; }
}
