package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public final class PaydaySchedule {
    public enum Frequency {
        WEEKLY("weekly", "Weekly"),
        EVERY_TWO_WEEKS("every_two_weeks", "Every two weeks"),
        TWICE_MONTHLY("twice_monthly", "Twice a month"),
        MONTHLY("monthly", "Monthly");

        public final String key;
        public final String label;

        Frequency(String key, String label) {
            this.key = key;
            this.label = label;
        }

        @Override public String toString() { return label; }
    }

    public final int id;
    public final String name;
    public final String startsOn;
    public final Frequency frequency;
    public final int dayOne;
    public final int dayTwo;

    public PaydaySchedule(JSONObject json) {
        id = json.optInt("id");
        name = json.optString("name");
        startsOn = json.optString("starts_on");
        frequency = Frequency.valueOf(json.optString("frequency").toUpperCase(java.util.Locale.ROOT));
        dayOne = json.optInt("day_one", 15);
        dayTwo = json.optInt("day_two", 0);
    }

    public String description() {
        if (frequency == Frequency.MONTHLY) return frequency.label + " · " + dayLabel(dayOne);
        if (frequency == Frequency.TWICE_MONTHLY) {
            return frequency.label + " · " + dayLabel(dayOne) + " and " + dayLabel(dayTwo);
        }
        return frequency.label + " · first payday " + startsOn;
    }

    public static String dayLabel(int day) {
        return day == 0 ? "Last day of the month" : Integer.toString(day);
    }

    public static final class Occurrence {
        public final int scheduleId;
        public final String name;
        public final String date;
        public final String original;

        private Occurrence(JSONObject json) {
            scheduleId = json.optInt("schedule_id");
            name = json.optString("name");
            date = json.optString("payday_date");
            original = json.optString("original_date");
        }

        public String description() {
            return date + " · " + name + (date.equals(original) ? "" : " · moved from " + original);
        }
    }

    public static List<Occurrence> occurrences(JSONArray json) {
        List<Occurrence> result = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                JSONObject entry = json.optJSONObject(i);
                if (entry != null) result.add(new Occurrence(entry));
            }
        }
        return result;
    }
}
