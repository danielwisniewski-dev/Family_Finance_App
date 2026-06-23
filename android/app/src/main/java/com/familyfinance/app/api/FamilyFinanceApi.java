package com.familyfinance.app.api;

import com.familyfinance.app.model.BudgetSummary;
import com.familyfinance.app.model.CashAccount;
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

    FamilyFinanceApi(JsonHttpClient client) {
        this.client = client;
    }

    public JSONObject health() throws ApiException {
        return client.get("/health");
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

    public List<TransactionDetail> getTransactions(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transactions"));
    }

    public List<TransactionDetail> getReviewQueue(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transaction-review-queue"));
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
