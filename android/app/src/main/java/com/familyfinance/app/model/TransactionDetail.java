package com.familyfinance.app.model;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class TransactionDetail {
    public final TransactionLine transaction;
    public final List<TransactionAssignment> assignments;
    public final Integer finalCategoryId;
    public final String categorizationStatus;
    public final boolean needsReview;

    public TransactionDetail(
            TransactionLine transaction,
            List<TransactionAssignment> assignments,
            Integer finalCategoryId,
            String categorizationStatus,
            boolean needsReview
    ) {
        this.transaction = transaction;
        this.assignments = Collections.unmodifiableList(new ArrayList<>(assignments));
        this.finalCategoryId = finalCategoryId;
        this.categorizationStatus = categorizationStatus;
        this.needsReview = needsReview;
    }

    public static TransactionDetail fromJson(JSONObject json) {
        JSONArray assignmentArray = json.optJSONArray("assignments");
        ArrayList<TransactionAssignment> assignments = new ArrayList<>();
        if (assignmentArray != null) {
            for (int i = 0; i < assignmentArray.length(); i++) {
                assignments.add(TransactionAssignment.fromJson(assignmentArray.optJSONObject(i)));
            }
        }
        Integer categoryId = json.isNull("final_category_id") ? null : json.optInt("final_category_id");
        return new TransactionDetail(
                TransactionLine.fromJson(json.optJSONObject("transaction")),
                assignments,
                categoryId,
                json.optString("categorization_status", "uncategorized"),
                json.optBoolean("needs_review")
        );
    }

    public boolean isSplit() {
        return "split".equals(categorizationStatus);
    }
}
