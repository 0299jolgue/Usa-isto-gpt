package pt.jolgue.brawlroom;

import android.app.Activity;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.view.View;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;

public final class MainActivity extends Activity {
    private EditText site;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
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
        site = new EditText(this);
        site.setSingleLine(true);
        site.setTextColor(Color.WHITE);
        site.setHintTextColor(Color.LTGRAY);
        site.setHint("https://teu-site.shardweb.app");
        site.setText(getPreferences(0).getString("site", "https://brawl-stars-room-jo.shardweb.app"));
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
