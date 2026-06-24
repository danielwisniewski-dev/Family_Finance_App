package com.familyfinance.app.api;

import com.familyfinance.app.model.BudgetSummary;
import com.familyfinance.app.model.CashAccount;
import com.familyfinance.app.model.NotificationEvent;
import com.familyfinance.app.model.SafeToSpendResult;
import com.familyfinance.app.model.TransactionDetail;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

public final class FamilyFinanceApi {
    private final JsonHttpClient client;

    public FamilyFinanceApi(String baseUrl) {
        this(new JsonHttpClient(baseUrl));
    }

    public FamilyFinanceApi(String baseUrl, String bearerToken) {
        this(new JsonHttpClient(baseUrl, bearerToken));
    }

    FamilyFinanceApi(JsonHttpClient client) {
        this.client = client;
    }

    public JSONObject health() throws ApiException {
        return client.get("/health");
    }

    public JSONObject login(String usernameOrEmail, String password) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("username", usernameOrEmail);
            payload.put("password", password);
            return client.post("/auth/login", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build login request", exception);
        }
    }

    public BudgetSummary getSummary(int budgetMonthId) throws ApiException {
        return BudgetSummary.fromJson(client.get("/budget-months/" + budgetMonthId + "/summary"));
    }

    public List<CashAccount> getAccounts(int budgetMonthId) throws ApiException {
        JSONArray json = client.get("/budget-months/" + budgetMonthId + "/accounts").optJSONArray("accounts");
        ArrayList<CashAccount> accounts = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                accounts.add(CashAccount.fromJson(json.optJSONObject(i)));
            }
        }
        return accounts;
    }

    public String createPlaidLinkToken() throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            return client.post("/plaid/link-token", payload).optString("link_token", "");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not request Plaid link token", exception);
        }
    }

    public JSONObject exchangePlaidPublicToken(int budgetMonthId, String publicToken) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_month_id", budgetMonthId);
            payload.put("public_token", publicToken);
            return client.post("/plaid/exchange-public-token", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not exchange Plaid public token", exception);
        }
    }

    public JSONObject syncPlaid(int plaidItemId, String syncType) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("plaid_item_id", plaidItemId);
            payload.put("sync_type", syncType);
            return client.post("/plaid/sync", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not sync Plaid item", exception);
        }
    }

    public void setAccountIncluded(int accountId, boolean included) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("included_in_cash_reality", included);
            client.patch("/accounts/" + accountId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update account inclusion", exception);
        }
    }

    public List<TransactionDetail> getTransactions(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transactions"));
    }

    public List<TransactionDetail> getReviewQueue(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transaction-review-queue"));
    }

    public List<NotificationEvent> getNotifications(int budgetMonthId) throws ApiException {
        JSONArray json = client.get(
                "/budget-months/" + budgetMonthId + "/notifications"
        ).optJSONArray("notifications");
        ArrayList<NotificationEvent> notifications = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                notifications.add(NotificationEvent.fromJson(json.optJSONObject(i)));
            }
        }
        return notifications;
    }

    public int getUnreadNotificationCount(int budgetMonthId) throws ApiException {
        return client.get(
                "/budget-months/" + budgetMonthId + "/notifications/unread-count"
        ).optInt("unread_count");
    }

    public TransactionDetail getTransaction(int transactionId) throws ApiException {
        return TransactionDetail.fromJson(client.get("/transactions/" + transactionId));
    }

    public void assignCategory(int transactionId, int categoryId, boolean reviewed) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("category_id", categoryId);
            payload.put("source", "manual");
            payload.put("reviewed", reviewed);
            client.patch("/transactions/" + transactionId + "/category", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build category assignment request", exception);
        }
    }

    public void markReviewed(int transactionId, boolean reviewed) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("reviewed", reviewed);
            client.patch("/transactions/" + transactionId + "/review", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build review request", exception);
        }
    }

    public void setIgnored(int transactionId, boolean ignored, String reason) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("ignored", ignored);
            if (reason != null && !reason.trim().isEmpty()) {
                payload.put("reason", reason.trim());
            }
            client.patch("/transactions/" + transactionId + "/ignore", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build ignore request", exception);
        }
    }

    public void markNotificationRead(int notificationId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            client.patch("/notifications/" + notificationId + "/read", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build notification read request", exception);
        }
    }

    public void markAllNotificationsRead(int budgetMonthId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            client.patch("/budget-months/" + budgetMonthId + "/notifications/read-all", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build mark all notifications request", exception);
        }
    }

    public SafeToSpendResult safeToSpend(
            int budgetMonthId,
            int categoryId,
            int purchaseAmountCents
    ) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_month_id", budgetMonthId);
            payload.put("category_id", categoryId);
            payload.put("purchase_amount_cents", purchaseAmountCents);
            payload.put("today", LocalDate.now().toString());
            payload.put("urgency", "planned_want");
            return SafeToSpendResult.fromJson(client.post("/safe-to-spend", payload));
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build safe-to-spend request", exception);
        }
    }

    private static List<TransactionDetail> parseTransactions(JSONObject payload) {
        JSONArray json = payload.optJSONArray("transactions");
        ArrayList<TransactionDetail> transactions = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                transactions.add(TransactionDetail.fromJson(json.optJSONObject(i)));
            }
        }
        return transactions;
    }
}
