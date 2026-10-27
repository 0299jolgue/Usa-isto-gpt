package pt.jolgue.brawlroom;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.Base64;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

import java.security.SecureRandom;

public final class MainActivity extends Activity {
    private static final String DEFAULT_SITE = "https://joinbrawl.shardweb.app";
    private EditText site;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        if (!getSharedPreferences("gesture_bridge", MODE_PRIVATE).contains("token")) {
            byte[] secret = new byte[24];
            new SecureRandom().nextBytes(secret);
            getSharedPreferences("gesture_bridge", MODE_PRIVATE).edit().putString(
                    "token", Base64.encodeToString(secret, Base64.NO_WRAP | Base64.URL_SAFE)).apply();
        }
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(32, 48, 32, 32);
        root.setBackgroundColor(Color.rgb(16, 20, 36));
        TextView title = new TextView(this);
        title.setText("Brawl Room · menu flutuante");
        title.setTextSize(23);
        title.setTextColor(Color.WHITE);
        root.addView(title);
        TextView help = new TextView(this);
        help.setText("O menu fica por cima do jogo. Toca em ✕ para o fechar.");
        help.setTextColor(Color.LTGRAY);
        root.addView(help);
        Button accessibility = new Button(this);
        accessibility.setText("Ativar controlo por Acessibilidade");
        root.addView(accessibility);
        accessibility.setOnClickListener(view -> startActivity(
                new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)));
        site = new EditText(this);
        site.setSingleLine(true);
        site.setTextColor(Color.WHITE);
        site.setHintTextColor(Color.LTGRAY);
        site.setHint(DEFAULT_SITE);
        String savedSite = getPreferences(0).getString("site", DEFAULT_SITE);
        if ("https://brawl-stars-room-jo.shardweb.app".equals(savedSite)
                || "https://brawl-stars-room-join.shardweb.app".equals(savedSite)) {
            savedSite = DEFAULT_SITE;
            getPreferences(0).edit().putString("site", savedSite).apply();
        }
        site.setText(savedSite);
        root.addView(site);
        Button open = new Button(this);
        open.setText("Abrir menu");
        root.addView(open);
        open.setOnClickListener(view -> openOverlay());
        Button close = new Button(this);
        close.setText("Fechar menu");
        root.addView(close);
        close.setOnClickListener(view -> stopService(new Intent(this, OverlayService.class)));
        setContentView(root);
    }

    private void openOverlay() {
        String address = site.getText().toString().trim();
        Uri uri = Uri.parse(address);
        if (!"https".equals(uri.getScheme()) || uri.getHost() == null || uri.getHost().isEmpty()) {
            site.setError("Indica um endereço HTTPS válido");
            return;
        }
        if (!Settings.canDrawOverlays(this)) {
            Intent permission = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
            startActivity(permission);
            return;
        }
        getPreferences(0).edit().putString("site", address.replaceAll("/+$", "")).apply();
        Intent service = new Intent(this, OverlayService.class);
        service.putExtra("site", address.replaceAll("/+$", ""));
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(service); else startService(service);
        moveTaskToBack(true);
    }
}
