package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
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
                        + "\"active_budget_month_id\":3,"
                        + "\"current_user\":{\"name\":\"Kara\"},"
                        + "\"current_household\":{\"name\":\"Daniel and Kara\"},"
                        + "\"integrity\":{\"ok\":false,\"checks\":["
                        + "{\"name\":\"split_totals_match\",\"ok\":false,\"severity\":\"important\","
                        + "\"message\":\"One or more transaction splits do not total the transaction amount.\",\"count\":1}"
                        + "]}"
                        + "}"
        ));

        assertTrue(diagnostics.backendReachable);
        assertTrue(diagnostics.databaseInitialized);
        assertEquals("sandbox", diagnostics.plaidMode);
        assertTrue(diagnostics.plaidSandboxOnly);
        assertEquals("Kara", diagnostics.userName);
        assertEquals("Daniel and Kara", diagnostics.householdName);
        assertEquals(3, diagnostics.activeBudgetMonthId);
        assertFalse(diagnostics.integrityOk);
        assertEquals(1, diagnostics.checks.size());
        assertEquals("split_totals_match", diagnostics.checks.get(0).name);
        assertFalse(diagnostics.checks.get(0).ok);
        assertEquals(1, diagnostics.checks.get(0).count);
    }
}
