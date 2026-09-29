package com.familyfinance.app.model;

import org.json.JSONObject;

/** Request/import progress supplied by the backend; "checked" is not a completeness guarantee. */
public final class BankRefreshStatus {
    public final String state;
    public final String message;
    public final String requestedAt;
    public final String checkedAt;
    public final int retryAfterSeconds;
    public final boolean canRequest;

    private BankRefreshStatus(JSONObject json) {
        if (json == null) throw new IllegalArgumentException("The backend did not return bank-refresh progress.");
        state = json.optString("state");
        if (!state.equals("idle") && !state.equals("pending") && !state.equals("unknown")
                && !state.equals("checked") && !state.equals("failed")) {
            throw new IllegalArgumentException("The backend returned unrecognized bank-refresh progress.");
        }
        message = json.optString("message", "");
        requestedAt = json.isNull("requested_at") ? "" : json.optString("requested_at");
        checkedAt = json.isNull("checked_at") ? "" : json.optString("checked_at");
        retryAfterSeconds = Math.max(0, json.optInt("retry_after_seconds"));
        canRequest = json.optBoolean("can_request");
    }

    public static BankRefreshStatus fromResponse(JSONObject response) {
        return new BankRefreshStatus(response.optJSONObject("refresh"));
    }

    public boolean isChecked() { return "checked".equals(state); }
    public boolean isFailed() { return "failed".equals(state); }

    public static BankRefreshStatus combine(BankRefreshStatus first, BankRefreshStatus next) {
        if (first == null) return next;
        return priority(next.state) > priority(first.state) ? next : first;
    }

    private static int priority(String state) {
        switch (state) {
            case "failed": return 4;
            case "unknown": return 3;
            case "pending": return 2;
            case "idle": return 1;
            default: return 0;
        }
    }
}
