package com.familyfinance.app.model;

import org.json.JSONObject;

public final class NotificationEvent {
    public final int id;
    public final int householdId;
    public final Integer budgetMonthId;
    public final String eventType;
    public final Integer actorUserId;
    public final String affectedEntityType;
    public final Integer affectedEntityId;
    public final String title;
    public final String message;
    public final String severity;
    public final String readAt;
    public final String createdAt;

    public NotificationEvent(
            int id,
            int householdId,
            Integer budgetMonthId,
            String eventType,
            Integer actorUserId,
            String affectedEntityType,
            Integer affectedEntityId,
            String title,
            String message,
            String severity,
            String readAt,
            String createdAt
    ) {
        this.id = id;
        this.householdId = householdId;
        this.budgetMonthId = budgetMonthId;
        this.eventType = eventType;
        this.actorUserId = actorUserId;
        this.affectedEntityType = affectedEntityType;
        this.affectedEntityId = affectedEntityId;
        this.title = title;
        this.message = message;
        this.severity = severity;
        this.readAt = readAt;
        this.createdAt = createdAt;
    }

    public static NotificationEvent fromJson(JSONObject json) {
        if (json == null) {
            json = new JSONObject();
        }
        return new NotificationEvent(
                json.optInt("id"),
                json.optInt("household_id"),
                json.isNull("budget_month_id") ? null : json.optInt("budget_month_id"),
                json.optString("event_type", ""),
                json.isNull("actor_user_id") ? null : json.optInt("actor_user_id"),
                json.optString("affected_entity_type", ""),
                json.isNull("affected_entity_id") ? null : json.optInt("affected_entity_id"),
                json.optString("title", "Notification"),
                json.optString("message", ""),
                json.optString("severity", "info"),
                nullableString(json, "read_at"),
                json.optString("created_at", "")
        );
    }

    public boolean isRead() {
        return readAt != null && !readAt.isEmpty();
    }

    public String readStateLabel() {
        return isRead() ? "Read" : "Unread";
    }

    public String severityLabel() {
        if ("important".equals(severity)) {
            return "Important";
        }
        if ("caution".equals(severity)) {
            return "Caution";
        }
        return "Info";
    }

    private static String nullableString(JSONObject json, String key) {
        return json.isNull(key) ? "" : json.optString(key, "");
    }
}
