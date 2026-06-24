package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public final class AppDiagnosticsTest {
    @Test
    public void parsesSanitizedDiagnostics() throws Exception {
        AppDiagnostics diagnostics = AppDiagnostics.fromJson(new JSONObject(
                "{"
                        + "\"backend_reachable\":true,"
                        + "\"database_initialized\":true,"
                        + "\"plaid_mode\":\"sandbox\","
                        + "\"plaid_sandbox_only\":true,"
                        + "\"current_user\":{\"name\":\"Kara\"},"
                        + "\"current_household\":{\"name\":\"Daniel and Kara\"}"
                        + "}"
        ));

        assertTrue(diagnostics.backendReachable);
        assertTrue(diagnostics.databaseInitialized);
        assertEquals("sandbox", diagnostics.plaidMode);
        assertTrue(diagnostics.plaidSandboxOnly);
        assertEquals("Kara", diagnostics.userName);
        assertEquals("Daniel and Kara", diagnostics.householdName);
    }
}
