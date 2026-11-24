package com.familyfinance.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

public final class DailyReminderReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        DailyReminder reminder = new DailyReminder(context);
        String action = intent.getAction();
        if (DailyReminder.ALARM.equals(action)) {
            reminder.onAlarm(intent);
        } else if (Intent.ACTION_BOOT_COMPLETED.equals(action)
                || Intent.ACTION_TIME_CHANGED.equals(action)
                || Intent.ACTION_TIMEZONE_CHANGED.equals(action)
                || Intent.ACTION_MY_PACKAGE_REPLACED.equals(action)) {
            reminder.refreshSchedule();
        }
    }
}
