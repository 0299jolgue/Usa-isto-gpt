package pt.jolgue.brawlroom;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.view.accessibility.AccessibilityEvent;

public final class GestureAccessibilityService extends AccessibilityService {
    private static volatile GestureAccessibilityService active;

    static GestureAccessibilityService active() { return active; }

    @Override protected void onServiceConnected() {
        super.onServiceConnected();
        active = this;
    }

    @Override public boolean onUnbind(android.content.Intent intent) {
        active = null;
        return super.onUnbind(intent);
    }

    @Override public void onAccessibilityEvent(AccessibilityEvent event) { }
    @Override public void onInterrupt() { }

    boolean gesture(int[] values, String kind) {
        GestureDescription.Builder builder = new GestureDescription.Builder();
        boolean moving = values[4] != 0;
        if (moving) {
            Path path = new Path();
            path.moveTo(values[0], values[1]);
            path.lineTo(values[2], values[3]);
            builder.addStroke(new GestureDescription.StrokeDescription(path, 0, 900));
        }
        if (!"none".equals(kind)) {
            Path path = new Path();
            path.moveTo(values[5], values[6]);
            long start = moving ? 120 : 0;
            long duration;
            if ("attack".equals(kind)) {
                path.lineTo(values[7], values[8]);
                duration = 180;
            } else if ("auto_fire".equals(kind)) {
                duration = moving ? 650 : 450;
            } else if ("super".equals(kind) || "tap".equals(kind)) {
                duration = 80;
            } else {
                return false;
            }
            builder.addStroke(new GestureDescription.StrokeDescription(path, start, duration));
        }
        return (moving || !"none".equals(kind)) && dispatchGesture(builder.build(), null, null);
    }
}
