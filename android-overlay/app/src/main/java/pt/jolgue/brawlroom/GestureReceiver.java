package pt.jolgue.brawlroom;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class GestureReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        String expected = context.getSharedPreferences("gesture_bridge", Context.MODE_PRIVATE)
                .getString("token", "");
        String supplied = intent.getStringExtra("token");
        if (expected.isEmpty() || !expected.equals(supplied)) {
            setResultCode(3);
            return;
        }
        String kind = intent.getStringExtra("kind");
        if ("collapse".equals(kind)) {
            OverlayService.collapse();
            setResultCode(1);
            return;
        }
        GestureAccessibilityService service = GestureAccessibilityService.active();
        if (service == null) {
            setResultCode(2);
            return;
        }
        int[] values = new int[9];
        String[] names = {"mx1", "my1", "mx2", "my2", "moving", "ax1", "ay1", "ax2", "ay2"};
        for (int i = 0; i < values.length; i++) values[i] = intent.getIntExtra(names[i], 0);
        setResultCode(service.gesture(values, kind) ? 1 : 4);
    }
}
