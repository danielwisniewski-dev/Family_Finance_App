package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class BudgetDetail {
    public final BudgetSummary summary;
    public final List<PlannedIncome> income;
    public final List<BudgetGroup> groups;
    public final List<ExpectedBill> expectedBills;
    public final List<Payday> paydays;

    public BudgetDetail(
            BudgetSummary summary,
            List<PlannedIncome> income,
            List<BudgetGroup> groups,
            List<ExpectedBill> expectedBills,
            List<Payday> paydays
    ) {
        this.summary = summary;
        this.income = Collections.unmodifiableList(new ArrayList<>(income));
        this.groups = Collections.unmodifiableList(new ArrayList<>(groups));
        this.expectedBills = Collections.unmodifiableList(new ArrayList<>(expectedBills));
        this.paydays = Collections.unmodifiableList(new ArrayList<>(paydays));
    }

    public static BudgetDetail fromJson(JSONObject json) {
        ArrayList<PlannedIncome> income = new ArrayList<>();
        JSONArray incomeArray = json.optJSONArray("income");
        if (incomeArray != null) {
            for (int i = 0; i < incomeArray.length(); i++) {
                income.add(PlannedIncome.fromJson(incomeArray.optJSONObject(i)));
            }
        }

        ArrayList<BudgetGroup> groups = new ArrayList<>();
        JSONArray groupArray = json.optJSONArray("groups");
        if (groupArray != null) {
            for (int i = 0; i < groupArray.length(); i++) {
                groups.add(BudgetGroup.fromJson(groupArray.optJSONObject(i)));
            }
        }

        ArrayList<ExpectedBill> bills = new ArrayList<>();
        JSONArray billArray = json.optJSONArray("expected_bills");
        if (billArray != null) {
            for (int i = 0; i < billArray.length(); i++) {
                bills.add(ExpectedBill.fromJson(billArray.optJSONObject(i)));
            }
        }

        ArrayList<Payday> paydays = new ArrayList<>();
        JSONArray paydayArray = json.optJSONArray("paydays");
        if (paydayArray != null) {
            for (int i = 0; i < paydayArray.length(); i++) {
                paydays.add(Payday.fromJson(paydayArray.optJSONObject(i)));
            }
        }

        return new BudgetDetail(BudgetSummary.fromJson(json), income, groups, bills, paydays);
    }
}
