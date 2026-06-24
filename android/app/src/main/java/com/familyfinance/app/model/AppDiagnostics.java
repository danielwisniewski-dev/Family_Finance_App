package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.List;

public final class AppDiagnostics {
    public final boolean backendReachable;
    public final boolean databaseInitialized;
    public final String plaidMode;
    public final boolean plaidSandboxOnly;
    public final String userName;
    public final String householdName;
    public final int activeBudgetMonthId;
    public final boolean integrityOk;
    public final List<DiagnosticCheck> checks;

    public AppDiagnostics(
            boolean backendReachable,
            boolean databaseInitialized,
            String plaidMode,
            boolean plaidSandboxOnly,
            String userName,
            String householdName,
            int activeBudgetMonthId,
            boolean integrityOk,
            List<DiagnosticCheck> checks
    ) {
        this.backendReachable = backendReachable;
        this.databaseInitialized = databaseInitialized;
        this.plaidMode = plaidMode;
        this.plaidSandboxOnly = plaidSandboxOnly;
        this.userName = userName;
        this.householdName = householdName;
        this.activeBudgetMonthId = activeBudgetMonthId;
        this.integrityOk = integrityOk;
        this.checks = checks == null ? new ArrayList<>() : checks;
    }

    public static AppDiagnostics fromJson(JSONObject json) {
        JSONObject user = json == null ? null : json.optJSONObject("current_user");
        JSONObject household = json == null ? null : json.optJSONObject("current_household");
        JSONObject integrity = json == null ? null : json.optJSONObject("integrity");
        return new AppDiagnostics(
                json != null && json.optBoolean("backend_reachable"),
                json != null && json.optBoolean("database_initialized"),
                json == null ? "" : json.optString("plaid_mode", ""),
                json != null && json.optBoolean("plaid_sandbox_only"),
                user == null ? "" : user.optString("name", ""),
                household == null ? "" : household.optString("name", ""),
                json == null ? 0 : json.optInt("active_budget_month_id", 0),
                integrity != null && integrity.optBoolean("ok"),
                parseChecks(integrity == null ? null : integrity.optJSONArray("checks"))
        );
    }

    private static List<DiagnosticCheck> parseChecks(JSONArray array) {
        ArrayList<DiagnosticCheck> result = new ArrayList<>();
        if (array == null) {
            return result;
        }
        for (int i = 0; i < array.length(); i++) {
            result.add(DiagnosticCheck.fromJson(array.optJSONObject(i)));
        }
        return result;
    }

    public static final class DiagnosticCheck {
        public final String name;
        public final boolean ok;
        public final String severity;
        public final String message;
        public final int count;

        public DiagnosticCheck(String name, boolean ok, String severity, String message, int count) {
            this.name = name;
            this.ok = ok;
            this.severity = severity;
            this.message = message;
            this.count = count;
        }

        public static DiagnosticCheck fromJson(JSONObject json) {
            return new DiagnosticCheck(
                    json == null ? "" : json.optString("name", ""),
                    json != null && json.optBoolean("ok"),
                    json == null ? "" : json.optString("severity", ""),
                    json == null ? "" : json.optString("message", ""),
                    json == null ? 0 : json.optInt("count", 0)
            );
        }
    }
}
