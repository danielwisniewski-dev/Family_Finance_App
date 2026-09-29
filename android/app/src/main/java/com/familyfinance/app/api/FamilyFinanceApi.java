package com.familyfinance.app.api;

import com.familyfinance.app.model.BudgetSummary;
import com.familyfinance.app.model.AppDiagnostics;
import com.familyfinance.app.model.BudgetDetail;
import com.familyfinance.app.model.BudgetMonth;
import com.familyfinance.app.model.CashAccount;
import com.familyfinance.app.model.MerchantRule;
import com.familyfinance.app.model.NotificationEvent;
import com.familyfinance.app.model.SafeToSpendResult;
import com.familyfinance.app.model.SetupStatus;
import com.familyfinance.app.model.TransactionDetail;
import com.familyfinance.app.model.ProvisionFunds;
import com.familyfinance.app.model.BankRefreshStatus;
import com.familyfinance.app.state.PendingFundAction;

import org.json.JSONArray;
import org.json.JSONObject;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.LinkedHashSet;
import java.util.Set;
import java.util.function.Consumer;

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

    public SetupStatus getSetupStatus() throws ApiException {
        return SetupStatus.fromJson(client.get("/setup/status"));
    }

    public JSONObject initializeHousehold(
            String householdName,
            JSONArray users,
            String setupCode
    ) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("household_name", householdName);
            payload.put("users", users);
            payload.put("setup_code", setupCode);
            return client.post("/setup/initialize", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not initialize household", exception);
        }
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

    public void logout() throws ApiException {
        client.post("/auth/logout", new JSONObject());
    }

    public JSONObject getAccountSettings() throws ApiException {
        return client.get("/settings/account");
    }

    public AppDiagnostics getDiagnostics() throws ApiException {
        return AppDiagnostics.fromJson(client.get("/app/diagnostics"));
    }

    public JSONObject updateDisplayName(String displayName) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("display_name", displayName);
            return client.patch("/settings/display-name", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update display name", exception);
        }
    }

    public void changePassword(String currentPassword, String newPassword) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("current_password", currentPassword);
            payload.put("new_password", newPassword);
            client.patch("/settings/password", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not change password", exception);
        }
    }

    public BudgetSummary getSummary(int budgetMonthId) throws ApiException {
        return BudgetSummary.fromJson(client.get("/budget-months/" + budgetMonthId + "/summary"));
    }

    public BudgetDetail getBudgetDetail(int budgetMonthId) throws ApiException {
        return BudgetDetail.fromJson(client.get("/budget-months/" + budgetMonthId + "/budget-detail"));
    }

    public ProvisionFunds getProvisionFunds(int budgetMonthId) throws ApiException {
        return ProvisionFunds.fromJson(client.get("/budget-months/" + budgetMonthId + "/funds"));
    }

    public void createProvisionFund(int budgetMonthId, JSONObject payload) throws ApiException {
        client.post("/budget-months/" + budgetMonthId + "/funds", payload);
    }

    public void updateProvisionFund(int fundId, JSONObject payload) throws ApiException {
        client.patch("/funds/" + fundId, payload);
    }

    public void applyFundAction(PendingFundAction action) throws Exception {
        client.post("/funds/" + action.fundId + (action.transfer ? "/transfer" : "/entries"), action.payload());
    }

    public List<BudgetMonth> getBudgetMonths() throws ApiException {
        JSONArray json = client.get("/budget-months").optJSONArray("budget_months");
        ArrayList<BudgetMonth> months = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                months.add(BudgetMonth.fromJson(json.optJSONObject(i)));
            }
        }
        return months;
    }

    public int createBudgetMonth(int householdId, String month, Integer copyFromBudgetMonthId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("household_id", householdId);
            payload.put("month", month);
            if (copyFromBudgetMonthId != null) {
                payload.put("copy_from_budget_month_id", copyFromBudgetMonthId);
            }
            return client.post("/budget-months", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create budget month", exception);
        }
    }

    public int createStarterBudget(String nextPayday) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("today", LocalDate.now().toString());
            if (nextPayday != null && !nextPayday.trim().isEmpty()) {
                payload.put("next_payday", nextPayday.trim());
            }
            return client.post("/starter-budget/current-month", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create starter budget", exception);
        }
    }

    public void activateBudgetMonth(int budgetMonthId) throws ApiException {
        try {
            client.patch("/budget-months/" + budgetMonthId + "/activate", new JSONObject());
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not activate budget month", exception);
        }
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

    public JSONObject getBankStatus(int monthId) throws ApiException {
        return client.get("/budget-months/" + monthId + "/bank-status");
    }

    public void reconcileBank(int monthId, String revision) throws Exception {
        client.post("/budget-months/" + monthId + "/bank-reconciliation", new JSONObject().put("revision", revision));
    }

    public void assignRefund(int transactionId, int categoryId) throws Exception {
        client.post("/transactions/" + transactionId + "/refund", new JSONObject().put("category_id", categoryId));
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
            JSONObject result = client.post("/plaid/sync", payload);
            if (!result.optBoolean("success", false)) {
                throw new ApiException(result.optString("error_message", "Bank sync failed. Retry or reconnect in Settings."));
            }
            return result;
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

    public int createIncome(int budgetMonthId, String name, String kind, int plannedCents, int receivedCents) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_month_id", budgetMonthId);
            payload.put("name", name);
            payload.put("kind", kind);
            payload.put("planned_cents", plannedCents);
            payload.put("received_cents", receivedCents);
            return client.post("/income", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create income", exception);
        }
    }

    public void updateIncome(int incomeId, String name, String kind, int plannedCents, int receivedCents) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("name", name);
            payload.put("kind", kind);
            payload.put("planned_cents", plannedCents);
            payload.put("received_cents", receivedCents);
            client.patch("/income/" + incomeId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update income", exception);
        }
    }

    public void deleteIncome(int incomeId) throws ApiException {
        client.delete("/income/" + incomeId);
    }

    public int createBudgetGroup(int budgetMonthId, String name) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_month_id", budgetMonthId);
            payload.put("name", name);
            return client.post("/budget-groups", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create budget group", exception);
        }
    }

    public void updateBudgetGroup(int groupId, String name, boolean archived) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("name", name);
            payload.put("archived", archived);
            client.patch("/budget-groups/" + groupId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update budget group", exception);
        }
    }

    public int createCategory(int budgetGroupId, String name, int plannedCents) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_group_id", budgetGroupId);
            payload.put("name", name);
            payload.put("planned_cents", plannedCents);
            return client.post("/categories", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create category", exception);
        }
    }

    public void updateCategory(int categoryId, String name, int plannedCents, boolean archived) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("name", name);
            payload.put("planned_cents", plannedCents);
            payload.put("archived", archived);
            client.patch("/categories/" + categoryId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update category", exception);
        }
    }

    public int createExpectedBill(int budgetMonthId, String name, int amountCents, String dueOn, boolean paid) throws ApiException {
        return createExpectedBill(budgetMonthId, name, amountCents, dueOn, paid, null);
    }

    public int createExpectedBill(int budgetMonthId, String name, int amountCents, String dueOn, boolean paid, Integer reserveFundId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("budget_month_id", budgetMonthId);
            payload.put("name", name);
            payload.put("amount_cents", amountCents);
            payload.put("due_on", dueOn);
            payload.put("paid", paid);
            if (reserveFundId != null) payload.put("reserve_fund_id", reserveFundId);
            return client.post("/expected-bills", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create expected bill", exception);
        }
    }

    public void updateExpectedBill(int billId, String name, int amountCents, String dueOn, boolean paid) throws ApiException {
        updateExpectedBill(billId, name, amountCents, dueOn, paid, null, false);
    }

    public void updateExpectedBill(int billId, String name, int amountCents, String dueOn, boolean paid,
            Integer reserveFundId, boolean updateFundLink) throws ApiException {
        try {
            JSONObject payload = expectedBillUpdatePayload(name, amountCents, dueOn, paid, reserveFundId, updateFundLink);
            client.patch("/expected-bills/" + billId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update expected bill", exception);
        }
    }

    /** Normal sync imports Plaid's available data; it never requests a bank refresh. */
    public JSONObject syncAvailableBankData(int budgetMonthId) throws ApiException {
        JSONObject status = getBankStatus(budgetMonthId);
        for (int itemId : bankConnectionIds(status)) {
            syncPlaid(itemId, "balance");
            syncPlaid(itemId, "transaction");
        }
        return getBankStatus(budgetMonthId);
    }

    private static Set<Integer> bankConnectionIds(JSONObject status) throws ApiException {
        if (!(status.opt("enabled") instanceof Boolean) || !status.optBoolean("enabled")) {
            throw new ApiException("Bank sync is unavailable on this backend.");
        }
        Set<Integer> itemIds = new LinkedHashSet<>();
        if (status.optInt("connection_id") > 0) itemIds.add(status.optInt("connection_id"));
        JSONArray accounts = status.optJSONArray("accounts");
        if (accounts != null) for (int i = 0; i < accounts.length(); i++) {
            JSONObject account = accounts.optJSONObject(i);
            if (account != null && account.optInt("plaid_item_id") > 0) itemIds.add(account.optInt("plaid_item_id"));
        }
        if (itemIds.isEmpty()) throw new ApiException("Connect USAA in Accounts / Settings before syncing bank data.");
        return itemIds;
    }

    public BankRefreshStatus requestFreshBankData(int budgetMonthId, Consumer<BankRefreshStatus> progress) throws ApiException {
        return requestFreshBankData(budgetMonthId, progress, Thread::sleep);
    }

    @FunctionalInterface
    interface RefreshPause { void waitFor(long milliseconds) throws InterruptedException; }

    BankRefreshStatus requestFreshBankData(int budgetMonthId, Consumer<BankRefreshStatus> progress,
            RefreshPause pause) throws ApiException {
        try {
            Set<Integer> itemIds = bankConnectionIds(getBankStatus(budgetMonthId));
            BankRefreshStatus status = null;
            for (int itemId : itemIds) {
                // This POST occurs once per explicit action. A timeout must never replay it.
                JSONObject response = client.post("/plaid/refresh", new JSONObject().put("plaid_item_id", itemId));
                if (!(response.opt("success") instanceof Boolean)) throw new ApiException("The bank-refresh request could not be confirmed.");
                BankRefreshStatus itemStatus = BankRefreshStatus.fromResponse(response);
                status = BankRefreshStatus.combine(status, itemStatus);
                if (itemStatus.isFailed()) return itemStatus;
                if (!response.optBoolean("success") && !"unknown".equals(itemStatus.state)) {
                    throw new ApiException(itemStatus.message.isEmpty() ? "USAA could not be asked for fresh data." : itemStatus.message);
                }
            }
            if (progress != null) progress.accept(status);
            // Balance fetches are separate live bank requests. Only refresh them once;
            // subsequent checks import the available transaction stream.
            for (int itemId : itemIds) syncPlaid(itemId, "balance");
            long[] delays = {0, 5_000, 10_000, 20_000};
            for (long delay : delays) {
                if (delay > 0) pause.waitFor(delay);
                status = null;
                boolean importedChanges = false;
                for (int itemId : itemIds) {
                    JSONObject imported = syncPlaid(itemId, "transaction");
                    status = BankRefreshStatus.combine(status, BankRefreshStatus.fromResponse(imported));
                    importedChanges |= imported.optLong("inserted_transactions") > 0
                            || imported.optLong("updated_transactions") > 0 || imported.optLong("removed_transactions") > 0;
                }
                if (progress != null) progress.accept(status);
                if (status.isFailed() || (status.isChecked() && importedChanges)) return status;
            }
            return status;
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new ApiException("The import check stopped. Use Dashboard Sync to check available data; do not repeat the fresh request yet.", exception);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("The fresh-data check could not finish. Use Dashboard Sync to check available data.", exception);
        }
    }

    static JSONObject expectedBillUpdatePayload(String name, int amountCents, String dueOn, boolean paid,
            Integer reserveFundId, boolean updateFundLink) throws org.json.JSONException {
        JSONObject payload = new JSONObject().put("name", name).put("amount_cents", amountCents)
                .put("due_on", dueOn).put("paid", paid);
        if (updateFundLink) payload.put("reserve_fund_id", reserveFundId == null ? JSONObject.NULL : reserveFundId);
        return payload;
    }

    public void deleteExpectedBill(int billId) throws ApiException {
        client.delete("/expected-bills/" + billId);
    }

    public int createPayday(int householdId, String paydayDate) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("household_id", householdId);
            payload.put("payday_date", paydayDate);
            return client.post("/paydays", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not create payday", exception);
        }
    }

    public void updatePayday(int paydayId, String paydayDate) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("payday_date", paydayDate);
            client.patch("/paydays/" + paydayId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not update payday", exception);
        }
    }

    public void deletePayday(int paydayId) throws ApiException {
        client.delete("/paydays/" + paydayId);
    }

    public List<TransactionDetail> getTransactions(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transactions"));
    }

    public List<TransactionDetail> getReviewQueue(int budgetMonthId) throws ApiException {
        return parseTransactions(client.get("/budget-months/" + budgetMonthId + "/transaction-review-queue"));
    }

    public List<MerchantRule> getMerchantRules() throws ApiException {
        JSONArray json = client.get("/merchant-category-rules?include_inactive=true").optJSONArray("rules");
        ArrayList<MerchantRule> rules = new ArrayList<>();
        if (json != null) {
            for (int i = 0; i < json.length(); i++) {
                rules.add(MerchantRule.fromJson(json.optJSONObject(i)));
            }
        }
        return rules;
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

    public void removeCategory(int transactionId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("category_id", JSONObject.NULL);
            payload.put("reviewed", false);
            client.patch("/transactions/" + transactionId + "/category", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build category removal request", exception);
        }
    }

    public void splitTransaction(int transactionId, List<int[]> splits, boolean reviewed) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            JSONArray splitArray = new JSONArray();
            for (int[] split : splits) {
                JSONObject row = new JSONObject();
                row.put("category_id", split[0]);
                row.put("amount_cents", split[1]);
                splitArray.put(row);
            }
            payload.put("splits", splitArray);
            payload.put("reviewed", reviewed);
            client.patch("/transactions/" + transactionId + "/split", payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build split request", exception);
        }
    }

    public void removeSplit(int transactionId) throws ApiException {
        client.delete("/transactions/" + transactionId + "/split");
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

    public int createMerchantRuleFromTransaction(
            int transactionId,
            int categoryId,
            boolean applyToExistingUnreviewed
    ) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("transaction_id", transactionId);
            payload.put("category_id", categoryId);
            payload.put("apply_to_existing_unreviewed", applyToExistingUnreviewed);
            return client.post("/merchant-category-rules", payload).optInt("id");
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build merchant rule request", exception);
        }
    }

    public void archiveMerchantRule(int ruleId) throws ApiException {
        client.delete("/merchant-category-rules/" + ruleId);
    }

    public void updateMerchantRule(int ruleId, String matchText, int categoryId) throws ApiException {
        try {
            JSONObject payload = new JSONObject();
            payload.put("merchant_match_text", matchText.trim());
            payload.put("category_id", categoryId);
            payload.put("apply_to_existing_unreviewed", false);
            client.patch("/merchant-category-rules/" + ruleId, payload);
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not build merchant rule update request", exception);
        }
    }

    public SafeToSpendResult syncAndCheckSafeToSpend(
            int budgetMonthId, int categoryId, int purchaseAmountCents
    ) throws ApiException {
        // Read current connection state instead of relying on the dashboard's cached snapshot.
        JSONObject status = getBankStatus(budgetMonthId);
        if (!(status.opt("enabled") instanceof Boolean)) {
            throw new ApiException("Bank connection status is unavailable. Please retry this check.");
        }
        if (status.optBoolean("enabled")) {
            Set<Integer> itemIds = new LinkedHashSet<>();
            if (status.optInt("connection_id") > 0) itemIds.add(status.optInt("connection_id"));
            JSONArray accounts = status.optJSONArray("accounts");
            if (accounts != null) {
                for (int i = 0; i < accounts.length(); i++) {
                    JSONObject account = accounts.optJSONObject(i);
                    if (account != null && account.optInt("plaid_item_id") > 0) {
                        itemIds.add(account.optInt("plaid_item_id"));
                    }
                }
            }
            if (itemIds.isEmpty()) throw new ApiException("Connect USAA in Accounts / Settings before checking safe to spend.");
            for (int itemId : itemIds) {
                syncPlaid(itemId, "balance");
                syncPlaid(itemId, "transaction");
            }
        }
        // The backend still enforces review, reconciliation, freshness, and all spending rules.
        return safeToSpend(budgetMonthId, categoryId, purchaseAmountCents);
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
