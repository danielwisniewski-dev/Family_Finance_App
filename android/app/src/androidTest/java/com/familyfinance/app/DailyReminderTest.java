package com.familyfinance.app;

import android.Manifest;
import android.app.NotificationManager;
import android.content.Context;
import android.content.ContextWrapper;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.test.ext.junit.runners.AndroidJUnit4;
import androidx.test.platform.app.InstrumentationRegistry;

import com.familyfinance.app.state.DemoModeStore;
import com.familyfinance.app.state.SecureSessionStore;

import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;

import java.time.ZonedDateTime;
import java.time.temporal.ChronoUnit;
import java.util.UUID;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

@RunWith(AndroidJUnit4.class)
public final class DailyReminderTest {
    private static final String ORIGIN = "https://household.example";

    @Test
    public void postsOnceForAMissedCheckAndKeepsRealAndDemoAlarmsSeparate() throws Exception {
        var instrumentation = InstrumentationRegistry.getInstrumentation();
        Context target = instrumentation.getTargetContext();
        if (Build.VERSION.SDK_INT >= 33) {
            instrumentation.getUiAutomation().grantRuntimePermission(
                    target.getPackageName(), Manifest.permission.POST_NOTIFICATIONS);
        }
        String prefix = "reminder_test_" + UUID.randomUUID() + "_";
        Context context = new ContextWrapper(target) {
            @Override public Context getApplicationContext() { return this; }
            @Override public SharedPreferences getSharedPreferences(String name, int mode) {
                return super.getSharedPreferences(prefix + name, mode);
            }
        };
        NotificationManager manager = context.getSystemService(NotificationManager.class);
        DailyReminder reminder = new DailyReminder(context);
        SharedPreferences real = context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
        real.edit().putString("base_url", ORIGIN).putInt("current_user_id", 7).putInt("household_id", 3).commit();
        SecureSessionStore realSession = new SecureSessionStore(context);
        assertTrue(realSession.save("synthetic-real", ORIGIN));
        DemoModeStore demo = new DemoModeStore(context);
        ZonedDateTime due = ZonedDateTime.now().truncatedTo(ChronoUnit.MINUTES);
        try {
            DailyReminder.Scope realScope = reminder.activeScope();
            assertFalse(realScope.enabled());
            reminder.setEnabled(realScope, true);
            reminder.setTime(realScope, due.toLocalTime());
            broadcast(context, realScope, due);
            assertEquals("Ledger", title(manager));
            manager.cancel(1);
            broadcast(context, realScope, due);
            assertEquals("", title(manager));

            assertTrue(demo.enter(demoResponse(due), ORIGIN));
            reminder.sessionChanged(true);
            DailyReminder.Scope demoScope = reminder.activeScope();
            assertFalse(demoScope.enabled());
            reminder.setEnabled(demoScope, true);
            reminder.setTime(demoScope, due.toLocalTime());
            broadcast(context, realScope, due);
            assertEquals("", title(manager));
            broadcast(context, demoScope, due);
            assertEquals("Ledger demo reminder", title(manager));

            demo.leave();
            reminder.sessionChanged(true);
            assertEquals("", title(manager));
            assertTrue(reminder.activeScope().enabled());
            broadcast(context, demoScope, due);
            assertEquals("", title(manager));
            assertTrue(demo.enter(demoResponse(due), ORIGIN));
            assertFalse(reminder.activeScope().enabled());
            reminder.foregroundChanged(true, true);
            reminder.foregroundChanged(false, true);
            DailyReminder.Scope fresh = reminder.activeScope();
            reminder.setEnabled(fresh, true);
            reminder.setTime(fresh, due.toLocalTime());
            broadcast(context, fresh, due);
            assertEquals("", title(manager));
        } finally {
            demo.leave();
            for (DemoModeStore.Cleanup pending : demo.pendingCleanup()) demo.cleanupFinished(pending.scope);
            realSession.clear();
            real.edit().clear().commit();
            reminder.sessionChanged(false);
        }
    }

    private static JSONObject demoResponse(ZonedDateTime due) throws Exception {
        return new JSONObject().put("demo", true).put("token", "synthetic-demo")
                .put("budget_month_id", 1).put("expires_at", due.plusHours(8).toInstant().toString())
                .put("household", new JSONObject().put("id", 3)).put("user", new JSONObject().put("id", 7));
    }

    private static void broadcast(Context context, DailyReminder.Scope scope, ZonedDateTime due) {
        new DailyReminderReceiver().onReceive(context, new Intent(DailyReminder.ALARM)
                .putExtra("scope", scope.id()).putExtra("time", due.toInstant().toEpochMilli()));
    }

    private static String title(NotificationManager manager) {
        for (var notification : manager.getActiveNotifications()) {
            if (DailyReminder.CHANNEL.equals(notification.getNotification().getChannelId())) {
                return notification.getNotification().extras.getString(android.app.Notification.EXTRA_TITLE, "");
            }
        }
        return "";
    }
}
