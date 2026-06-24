package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class BudgetGroup {
    public final int id;
    public final String name;
    public final int displayOrder;
    public final boolean archived;
    public final List<BudgetCategory> categories;

    public BudgetGroup(int id, String name, int displayOrder, boolean archived, List<BudgetCategory> categories) {
        this.id = id;
        this.name = name;
        this.displayOrder = displayOrder;
        this.archived = archived;
        this.categories = Collections.unmodifiableList(new ArrayList<>(categories));
    }

    public static BudgetGroup fromJson(JSONObject json) {
        JSONArray array = json.optJSONArray("categories");
        ArrayList<BudgetCategory> categories = new ArrayList<>();
        if (array != null) {
            for (int i = 0; i < array.length(); i++) {
                categories.add(BudgetCategory.fromJson(array.optJSONObject(i)));
            }
        }
        return new BudgetGroup(
                json.optInt("id"),
                json.optString("name"),
                json.optInt("display_order"),
                json.optBoolean("archived"),
                categories
        );
    }
}
