package com.familyfinance.app.model;

import org.json.JSONObject;

public final class SetupStatus {
    public final boolean initialized;
    public final boolean householdExists;
    public final boolean usersExist;
    public final boolean canInitialize;
    public final String currentUserName;
    public final String currentHouseholdName;

    public SetupStatus(
            boolean initialized,
            boolean householdExists,
            boolean usersExist,
            boolean canInitialize,
            String currentUserName,
            String currentHouseholdName
    ) {
        this.initialized = initialized;
        this.householdExists = householdExists;
        this.usersExist = usersExist;
        this.canInitialize = canInitialize;
        this.currentUserName = currentUserName;
        this.currentHouseholdName = currentHouseholdName;
    }

    public static SetupStatus fromJson(JSONObject json) {
        JSONObject user = json == null ? null : json.optJSONObject("current_user");
        JSONObject household = json == null ? null : json.optJSONObject("current_household");
        return new SetupStatus(
                json != null && json.optBoolean("initialized"),
                json != null && json.optBoolean("household_exists"),
                json != null && json.optBoolean("users_exist"),
                json != null && json.optBoolean("can_initialize"),
                user == null ? "" : user.optString("name", ""),
                household == null ? "" : household.optString("name", "")
        );
    }
}
