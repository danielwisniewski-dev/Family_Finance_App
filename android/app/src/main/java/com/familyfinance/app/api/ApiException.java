package com.familyfinance.app.api;

import org.json.JSONObject;

public final class ApiException extends Exception {
    public final String code;
    public final int status;

    public ApiException(String message) {
        this(message, "", 0, null);
    }

    public ApiException(String message, String code, int status) {
        this(message, code, status, null);
    }

    public ApiException(String message, Throwable cause) {
        this(message, "", 0, cause);
    }

    private ApiException(String message, String code, int status, Throwable cause) {
        super(message, cause);
        this.code = code == null ? "" : code;
        this.status = status;
    }

    public static ApiException fromApiError(int status, JSONObject json, String path) {
        String message = json == null
                ? ""
                : json.optString("message", json.optString("error", ""));
        String code = json == null ? "" : json.optString("code", "");
        if (status == 401 && !"/auth/login".equals(path)) {
            message = "Login required or session expired. Please log in again.";
            code = code.isEmpty() ? "unauthorized" : code;
        }
        if (message == null || message.trim().isEmpty()) {
            message = "API error " + status;
        }
        return new ApiException(message, code, status);
    }
}
