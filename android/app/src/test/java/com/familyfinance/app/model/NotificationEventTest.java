package com.familyfinance.app.model;

import org.json.JSONObject;
import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

public final class NotificationEventTest {
    @Test
    public void parsesUnreadNotificationEvent() throws Exception {
        JSONObject json = new JSONObject();
        json.put("id", 7);
        json.put("household_id", 1);
        json.put("budget_month_id", 2);
        json.put("event_type", "transaction_recategorized");
        json.put("affected_entity_type", "transaction");
        json.put("affected_entity_id", 9);
        json.put("title", "Transaction recategorized");
        json.put("message", "Fresh Market moved to Groceries.");
        json.put("severity", "caution");
        json.put("read_at", JSONObject.NULL);
        json.put("created_at", "2026-06-23 12:00:00");

        NotificationEvent event = NotificationEvent.fromJson(json);

        assertEquals(7, event.id);
        assertEquals(Integer.valueOf(2), event.budgetMonthId);
        assertEquals("Caution", event.severityLabel());
        assertEquals("Unread", event.readStateLabel());
        assertFalse(event.isRead());
    }

    @Test
    public void parsesReadImportantNotificationEvent() throws Exception {
        JSONObject json = new JSONObject();
        json.put("id", 8);
        json.put("severity", "important");
        json.put("read_at", "2026-06-23 12:05:00");

        NotificationEvent event = NotificationEvent.fromJson(json);

        assertEquals("Important", event.severityLabel());
        assertEquals("Read", event.readStateLabel());
        assertTrue(event.isRead());
    }
}
