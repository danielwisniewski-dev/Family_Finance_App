package com.familyfinance.app;

import android.Manifest;
import android.app.AlarmManager;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.os.Build;

import com.familyfinance.app.state.ConnectionSettings;
import com.familyfinance.app.state.DailyReminderSchedule;
import com.familyfinance.app.state.DemoModeStore;
import com.familyfinance.app.state.SecureSessionStore;

import java.time.Instant;
import java.time.LocalTime;
import java.time.ZonedDateTime;

final class DailyReminder {
    static final String CHANNEL = "daily_reminders";
    static final String ALARM = "com.familyfinance.app.DAILY_REMINDER";
    private static final String ALARM_SCOPE = "scope";
    private static final String ALARM_TIME = "time";
    private static final int NOTIFICATION_ID = 1;
    private static final int DEFAULT_MINUTE = 19 * 60;

    // MainActivity and the receiver run in the same process on the main thread.
    private static boolean foreground;
    private final Context context;
    private final AlarmManager alarms;
    private final NotificationManager notifications;

    DailyReminder(Context context) {
        this.context = context.getApplicationContext();
        alarms = this.context.getSystemService(AlarmManager.class);
        notifications = this.context.getSystemService(NotificationManager.class);
    }

    static final class Scope {
        final SharedPreferences prefs;
        final String origin;
        final String mode;
        final String key;
        final long expiresAt;

        Scope(SharedPreferences prefs, String origin, String mode, int household, int user, long expiresAt) {
            this.prefs = prefs;
            this.origin = origin;
            this.mode = mode;
            this.key = origin + ":" + household + ":" + user + ":daily_reminder_";
            this.expiresAt = expiresAt;
        }

        boolean enabled() { return prefs.getBoolean(key + "enabled", false); }
        boolean demo() { return !"real".equals(mode); }
        String id() { return mode + ":" + key; }
        LocalTime time() {
            int minute = prefs.getInt(key + "minute", DEFAULT_MINUTE);
            return LocalTime.of(minute / 60, minute % 60);
        }
        Instant lastCheck() {
            long time = prefs.getLong(key + "checked", 0);
            return time == 0 ? null : Instant.ofEpochMilli(time);
        }
        String lastReminderDay() { return prefs.getString(key + "sent_day", ""); }
    }

    Scope activeScope() {
        DemoModeStore demo = new DemoModeStore(context);
        boolean inDemo = demo.isEnabled();
        SharedPreferences prefs = inDemo ? demo.preferences()
                : context.getSharedPreferences(MainActivity.PREFS, Context.MODE_PRIVATE);
        int user = prefs.getInt("current_user_id", 0);
        int household = prefs.getInt("household_id", 0);
        long expiresAt = prefs.getLong("session_expires_at", inDemo ? 0 : Long.MAX_VALUE);
        if (user <= 0 || household <= 0 || Instant.now().getEpochSecond() >= expiresAt) return null;
        try {
            String origin = ConnectionSettings.normalizeBaseUrl(
                    prefs.getString("base_url", BuildConfig.DEFAULT_BACKEND_URL), BuildConfig.DEBUG);
            return new Scope(prefs, origin, inDemo ? demo.scope() : "real", household, user, expiresAt);
        } catch (IllegalArgumentException exception) {
            return null;
        }
    }

    boolean isCurrent(Scope scope) {
        Scope current = activeScope();
        return current != null && current.id().equals(scope.id());
    }

    void setEnabled(Scope scope, boolean enabled) {
        scope.prefs.edit().putBoolean(scope.key + "enabled", enabled).apply();
        schedule(scope, ZonedDateTime.now());
        if (!enabled) notifications.cancel(NOTIFICATION_ID);
    }

    void setTime(Scope scope, LocalTime time) {
        scope.prefs.edit().putInt(scope.key + "minute", time.getHour() * 60 + time.getMinute()).apply();
        schedule(scope, ZonedDateTime.now());
    }

    boolean notificationsAllowed() {
        NotificationChannel channel = notifications.getNotificationChannel(CHANNEL);
        return notifications.areNotificationsEnabled()
                && (channel == null || channel.getImportance() != NotificationManager.IMPORTANCE_NONE)
                && (Build.VERSION.SDK_INT < 33 || context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                        == PackageManager.PERMISSION_GRANTED);
    }

    void foregroundChanged(boolean isForeground, boolean signedIn) {
        foreground = isForeground;
        // Also count the day if Ledger was left in the foreground across midnight.
        sessionChanged(signedIn, true);
    }

    void sessionChanged(boolean signedIn) {
        sessionChanged(signedIn, foreground);
    }

    private void sessionChanged(boolean signedIn, boolean checked) {
        Scope scope = signedIn ? activeScope() : null;
        ZonedDateTime now = ZonedDateTime.now();
        if (scope != null && checked) recordCheck(scope, now);
        notifications.cancel(NOTIFICATION_ID);
        schedule(scope, now);
    }

    void refreshSchedule() {
        Scope scope = activeScope();
        if (scope != null && scope.enabled() && !hasSavedSession(scope)) scope = null;
        ZonedDateTime now = ZonedDateTime.now();
        if (scope != null && foreground) recordCheck(scope, now);
        schedule(scope, now);
    }

    void onAlarm(Intent intent) {
        Scope scope = activeScope();
        if (scope == null || !scope.id().equals(intent.getStringExtra(ALARM_SCOPE))
                || !scope.enabled() || !hasSavedSession(scope)) return;
        ZonedDateTime now = ZonedDateTime.now();
        if (foreground) recordCheck(scope, now);
        Instant planned = Instant.ofEpochMilli(intent.getLongExtra(ALARM_TIME, 0));
        if (notificationsAllowed() && DailyReminderSchedule.shouldRemind(
                now, scope.time(), planned, scope.lastCheck(), scope.lastReminderDay())) {
            scope.prefs.edit().putString(scope.key + "sent_day", now.toLocalDate().toString()).commit();
            post(scope, now);
        }
        schedule(scope, now);
    }

    private boolean hasSavedSession(Scope scope) {
        return !new SecureSessionStore(context, scope.mode).load(scope.origin).isEmpty();
    }

    private void recordCheck(Scope scope, ZonedDateTime now) {
        scope.prefs.edit().putLong(scope.key + "checked", now.toInstant().toEpochMilli()).apply();
    }

    private void schedule(Scope scope, ZonedDateTime now) {
        Intent intent = new Intent(context, DailyReminderReceiver.class).setAction(ALARM);
        if (scope == null || !scope.enabled() || !notificationsAllowed()) {
            cancelAlarm(intent);
            return;
        }
        Instant next = DailyReminderSchedule.nextAlarm(now, scope.time(), scope.lastCheck(), scope.lastReminderDay());
        if (next.getEpochSecond() >= scope.expiresAt) {
            cancelAlarm(intent);
            return;
        }
        intent.putExtra(ALARM_SCOPE, scope.id()).putExtra(ALARM_TIME, next.toEpochMilli());
        PendingIntent alarm = PendingIntent.getBroadcast(context, 0, intent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_CANCEL_CURRENT);
        alarms.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, next.toEpochMilli(), alarm);
    }

    private void cancelAlarm(Intent intent) {
        PendingIntent alarm = PendingIntent.getBroadcast(context, 0, intent,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_NO_CREATE);
        if (alarm != null) {
            alarms.cancel(alarm);
            alarm.cancel();
        }
    }

    void createChannel() {
        notifications.createNotificationChannel(new NotificationChannel(
                CHANNEL, "Daily reminders", NotificationManager.IMPORTANCE_DEFAULT));
    }

    private void post(Scope scope, ZonedDateTime now) {
        createChannel();
        Intent open = new Intent(context, MainActivity.class).setAction(Intent.ACTION_MAIN)
                .addCategory(Intent.CATEGORY_LAUNCHER)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);
        PendingIntent launch = PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_IMMUTABLE);
        long nextDay = now.toLocalDate().plusDays(1).atStartOfDay(now.getZone()).toEpochSecond();
        long timeout = Math.min(nextDay, scope.expiresAt) * 1000 - now.toInstant().toEpochMilli();
        notifications.notify(NOTIFICATION_ID, new Notification.Builder(context, CHANNEL)
                .setSmallIcon(R.drawable.ic_daily_reminder)
                .setContentTitle(scope.demo() ? "Ledger demo reminder" : context.getString(R.string.app_name))
                .setContentText("Take a moment to check Ledger.")
                .setContentIntent(launch)
                .setCategory(Notification.CATEGORY_REMINDER)
                .setVisibility(Notification.VISIBILITY_PRIVATE)
                .setTimeoutAfter(timeout)
                .setAutoCancel(true)
                .build());
    }
}
