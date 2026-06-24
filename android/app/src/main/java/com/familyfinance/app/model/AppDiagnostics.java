package com.familyfinance.app.model;

import org.json.JSONObject;

public final class AppDiagnostics {
    public final boolean backendReachable;
    public final boolean databaseInitialized;
    public final String plaidMode;
    public final boolean plaidSandboxOnly;
    public final String userName;
    public final String householdName;

    public AppDiagnostics(
            boolean backendReachable,
            boolean databaseInitialized,
            String plaidMode,
            boolean plaidSandboxOnly,
            String userName,
            String householdName
    ) {
        this.backendReachable = backendReachable;
        this.databaseInitialized = databaseInitialized;
        this.plaidMode = plaidMode;
        this.plaidSandboxOnly = plaidSandboxOnly;
        this.userName = userName;
        this.householdName = householdName;
    }

    public static AppDiagnostics fromJson(JSONObject json) {
        JSONObject user = json == null ? null : json.optJSONObject("current_user");
        JSONObject household = json == null ? null : json.optJSONObject("current_household");
        return new AppDiagnostics(
                json != null && json.optBoolean("backend_reachable"),
                json != null && json.optBoolean("database_initialized"),
                json == null ? "" : json.optString("plaid_mode", ""),
                json != null && json.optBoolean("plaid_sandbox_only"),
                user == null ? "" : user.optString("name", ""),
                household == null ? "" : household.optString("name", "")
        );
    }
}
