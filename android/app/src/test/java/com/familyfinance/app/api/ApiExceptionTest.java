package com.familyfinance.app.api;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;

public final class ApiExceptionTest {
    @Test
    public void parsesStructuredSanitizedApiError() throws Exception {
        ApiException exception = ApiException.fromApiError(
                400,
                new JSONObject(
                        "{"
                                + "\"error\":\"amount_cents must be positive\","
                                + "\"message\":\"amount_cents must be positive\","
                                + "\"code\":\"validation_error\","
                                + "\"status\":400"
                                + "}"
                ),
                "/expected-bills"
        );

        assertEquals("amount_cents must be positive", exception.getMessage());
        assertEquals("validation_error", exception.code);
        assertEquals(400, exception.status);
    }

    @Test
    public void mapsUnauthorizedNonLoginRouteToSessionMessage() throws Exception {
        ApiException exception = ApiException.fromApiError(
                401,
                new JSONObject("{\"error\":\"Authentication required\",\"code\":\"unauthorized\",\"status\":401}"),
                "/app/diagnostics"
        );

        assertEquals("Login required or session expired. Please log in again.", exception.getMessage());
        assertEquals("unauthorized", exception.code);
        assertEquals(401, exception.status);
    }
}
