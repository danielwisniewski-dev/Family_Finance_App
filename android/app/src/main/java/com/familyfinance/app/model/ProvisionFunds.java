package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Backend-owned balances. Planning amounts never become saved money on the phone. */
public final class ProvisionFunds {
    public final int budgetMonthId;
    public final String month;
    public final int totalPlannedCents;
    public final int totalContributedCents;
    public final int totalSpentCents;
    public final int totalBalanceCents;
    public final int reservedIncludedCents;
    public final int totalShortfallCents;
    public final List<String> issues;
    public final List<Fund> funds;

    private ProvisionFunds(JSONObject json) {
        budgetMonthId = json.optInt("budget_month_id");
        month = json.optString("month");
        totalPlannedCents = JsonMoney.cents(json, "total_planned_cents");
        totalContributedCents = JsonMoney.cents(json, "total_contributed_cents");
        totalSpentCents = JsonMoney.cents(json, "total_spent_cents");
        totalBalanceCents = JsonMoney.cents(json, "total_balance_cents");
        reservedIncludedCents = JsonMoney.cents(json, "reserved_included_cents");
        totalShortfallCents = JsonMoney.cents(json, "total_shortfall_cents");
        ArrayList<String> warnings = new ArrayList<>();
        JSONArray warningArray = json.optJSONArray("issues");
        if (warningArray != null) {
            for (int i = 0; i < warningArray.length(); i++) warnings.add(warningArray.optString(i));
        }
        issues = Collections.unmodifiableList(warnings);
        ArrayList<Fund> values = new ArrayList<>();
        JSONArray array = json.optJSONArray("funds");
        if (array != null) {
            for (int i = 0; i < array.length(); i++) values.add(new Fund(array.optJSONObject(i)));
        }
        funds = Collections.unmodifiableList(values);
    }

    public static ProvisionFunds fromJson(JSONObject json) { return new ProvisionFunds(json); }

    public Fund find(int id) {
        for (Fund fund : funds) if (fund.id == id) return fund;
        return null;
    }

    public static final class Fund {
        public final int id;
        public final String name;
        public final Integer categoryId;
        public final int backingAccountId;
        public final String backingAccountName;
        public final int monthlyPlanCents;
        public final int annualTargetCents;
        public final String timingNote;
        public final int contributedThisMonthCents;
        public final int spentThisMonthCents;
        public final int balanceCents;
        public final int monthlyShortfallCents;
        public final boolean archived;
        public final List<Component> breakdown;
        public final List<Entry> entries;

        private Fund(JSONObject json) {
            id = json.optInt("id");
            name = json.optString("name");
            categoryId = json.isNull("category_id") ? null : json.optInt("category_id");
            backingAccountId = json.optInt("backing_account_id");
            backingAccountName = json.optString("backing_account_name");
            monthlyPlanCents = JsonMoney.cents(json, "monthly_plan_cents");
            annualTargetCents = JsonMoney.cents(json, "annual_target_cents");
            timingNote = json.optString("timing_note");
            contributedThisMonthCents = JsonMoney.cents(json, "contributed_this_month_cents");
            spentThisMonthCents = JsonMoney.cents(json, "spent_this_month_cents");
            balanceCents = JsonMoney.cents(json, "balance_cents");
            monthlyShortfallCents = JsonMoney.cents(json, "monthly_shortfall_cents");
            archived = json.optBoolean("archived");
            ArrayList<Component> components = new ArrayList<>();
            JSONArray items = json.optJSONArray("breakdown");
            if (items != null) {
                for (int i = 0; i < items.length(); i++) components.add(new Component(items.optJSONObject(i)));
            }
            breakdown = Collections.unmodifiableList(components);
            ArrayList<Entry> history = new ArrayList<>();
            JSONArray activity = json.optJSONArray("entries");
            if (activity != null) {
                for (int i = 0; i < activity.length(); i++) history.add(new Entry(activity.optJSONObject(i)));
            }
            entries = Collections.unmodifiableList(history);
        }
    }

    public static final class Component {
        public final String name;
        public final int annualCents;
        public final String timingNote;

        private Component(JSONObject json) {
            name = json.optString("name");
            annualCents = JsonMoney.cents(json, "annual_cents");
            timingNote = json.optString("timing_note");
        }
    }

    public static final class Entry {
        public final String kind;
        public final int amountCents;
        public final String occurredOn;
        public final String note;
        public final String actorName;
        public final String counterpartName;

        private Entry(JSONObject json) {
            kind = json.optString("kind");
            amountCents = JsonMoney.cents(json, "amount_cents");
            occurredOn = json.optString("occurred_on");
            note = json.optString("note");
            actorName = json.optString("actor_name");
            counterpartName = json.optString("counterpart_name");
        }
    }
}
