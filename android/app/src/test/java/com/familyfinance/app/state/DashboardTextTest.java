package com.familyfinance.app.state;

import org.junit.Test;
import java.time.ZoneId;
import static org.junit.Assert.*;

public final class DashboardTextTest {
    private final ZoneId eastern = ZoneId.of("America/New_York");

    @Test
    public void sqliteSyncTimestampIsUtcAndCanLandOnPreviousLocalDate() {
        assertEquals("Last bank sync: Sept 16, 2026, 10:30 PM EDT",
                DashboardText.lastBankSync("2026-09-17 02:30:00", "2026-09-17 02:29:59", eastern));
        assertEquals("Sept 2026", DashboardText.budgetMonth("2026-09"));
    }

    @Test
    public void explicitOffsetsAndDaylightSavingAreRespected() {
        assertEquals("Last bank sync: Jan 3, 2026, 7:05 AM EST",
                DashboardText.lastBankSync("2026-01-03T12:05:00Z", "", eastern));
        assertEquals("Last bank sync: Sept 17, 2026, 9:45 AM EDT",
                DashboardText.lastBankSync("2026-09-17T15:45:00+02:00", "", eastern));
    }

    @Test
    public void missingTransactionSyncIsClearlyLabeledAsBalanceOnly() {
        assertEquals("Last balance sync: Sept 17, 2026, 9:45 AM EDT",
                DashboardText.lastBankSync(null, "2026-09-17 13:45:00", eastern));
    }

    @Test
    public void absentOrInvalidDatesDoNotInventASyncTime() {
        for (String missing : new String[]{null, "", "null", "bad date"}) {
            assertEquals("Bank sync: not available yet", DashboardText.lastBankSync(missing, missing, eastern));
        }
        assertEquals("Unknown month", DashboardText.budgetMonth(null));
        assertEquals("Unknown month", DashboardText.budgetMonth("Unknown month"));
    }
}
