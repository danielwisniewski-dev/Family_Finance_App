package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class SetupStatusTest {
    @Test
    public void parsesEmptySetupState() throws Exception {
        SetupStatus status = SetupStatus.fromJson(new JSONObject(
                "{"
                        + "\"initialized\":false,"
                        + "\"household_exists\":false,"
                        + "\"users_exist\":false,"
                        + "\"can_initialize\":true"
                        + "}"
        ));

        assertFalse(status.initialized);
        assertFalse(status.householdExists);
        assertFalse(status.usersExist);
        assertTrue(status.canInitialize);
    }

    @Test
    public void parsesAuthenticatedSetupSummary() throws Exception {
        SetupStatus status = SetupStatus.fromJson(new JSONObject(
                "{"
                        + "\"initialized\":true,"
                        + "\"household_exists\":true,"
                        + "\"users_exist\":true,"
                        + "\"can_initialize\":false,"
                        + "\"current_user\":{\"name\":\"Daniel\"},"
                        + "\"current_household\":{\"name\":\"Daniel and Kara\"}"
                        + "}"
        ));

        assertTrue(status.initialized);
        assertEquals("Daniel", status.currentUserName);
        assertEquals("Daniel and Kara", status.currentHouseholdName);
    }
}
