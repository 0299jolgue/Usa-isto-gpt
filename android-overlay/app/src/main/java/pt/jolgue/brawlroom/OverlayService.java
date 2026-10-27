package pt.jolgue.brawlroom;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.PixelFormat;
import android.graphics.drawable.GradientDrawable;
import android.os.IBinder;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.View;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class OverlayService extends Service {
    public final class MenuBridge {
        @JavascriptInterface public void collapse() { OverlayService.collapse(); }
    }
    private static volatile OverlayService active;
    private WindowManager manager;
    private WindowManager.LayoutParams params;
    private LinearLayout root;
    private WebView browser;
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
        if (root == null) makeWindow(site);
        else browser.loadUrl(site + "/overlay");
        return START_STICKY;
    }

    private int dp(int value) { return Math.round(getResources().getDisplayMetrics().density * value); }

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
        TextView toggle = text("✳", 28);
        bar.addView(toggle, new LinearLayout.LayoutParams(dp(56), dp(56)));
        toggle.setOnClickListener(view -> setExpanded(!expanded));
        TextView label = text("BRAWL ROOM", 14);
        bar.addView(label, new LinearLayout.LayoutParams(0, dp(56), 1));
        TextView close = text("✕", 22);
        bar.addView(close, new LinearLayout.LayoutParams(dp(48), dp(56)));
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
                manager.updateViewLayout(root, params);
                return true;
            }
            return true;
        });
        root.addView(bar);
        browser = new WebView(this);
        browser.getSettings().setJavaScriptEnabled(true);
        browser.getSettings().setDomStorageEnabled(true);
        browser.addJavascriptInterface(new MenuBridge(), "BrawlRoom");
        CookieManager.getInstance().setAcceptCookie(true);
        browser.setWebViewClient(new WebViewClient());
        browser.loadUrl(site + "/overlay");
        browser.setVisibility(View.GONE);
        root.addView(browser, new LinearLayout.LayoutParams(-1, 0, 1));
        manager.addView(root, params);
    }

    private void setExpanded(boolean value) {
        expanded = value;
        browser.setVisibility(value ? View.VISIBLE : View.GONE);
        params.width = value ? dp(300) : dp(56);
        params.height = value ? dp(360) : dp(56);
        params.flags = WindowManager.LayoutParams.FLAG_NOT_TOUCH_MODAL |
                (value ? 0 : WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE);
        manager.updateViewLayout(root, params);
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
