package com.familyfinance.app.state;

import org.json.JSONException;
import org.json.JSONObject;

import java.util.UUID;

/** A fixed request survives a failed response so retrying cannot reserve money twice. */
public final class PendingFundAction {
    public final int fundId;
    public final boolean transfer;
    private final String request;

    private PendingFundAction(int fundId, boolean transfer, String request) {
        if (fundId <= 0) throw new IllegalArgumentException("Choose a fund.");
        this.fundId = fundId;
        this.transfer = transfer;
        this.request = request;
    }

    public static PendingFundAction create(int fundId, boolean transfer, JSONObject body) throws JSONException {
        JSONObject copy = new JSONObject(body.toString());
        copy.put("idempotency_key", UUID.randomUUID().toString());
        return new PendingFundAction(fundId, transfer, copy.toString());
    }

    public JSONObject payload() throws JSONException { return new JSONObject(request); }

    public String serialize() throws JSONException {
        return new JSONObject().put("fund_id", fundId).put("transfer", transfer)
                .put("request", payload()).toString();
    }

    public static PendingFundAction restore(String serialized) throws JSONException {
        JSONObject value = new JSONObject(serialized);
        JSONObject payload = value.getJSONObject("request");
        UUID.fromString(payload.getString("idempotency_key"));
        return new PendingFundAction(value.getInt("fund_id"), value.getBoolean("transfer"), payload.toString());
    }
}
