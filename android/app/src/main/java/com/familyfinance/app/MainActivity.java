package com.familyfinance.app;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.widget.ArrayAdapter;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.familyfinance.app.api.FamilyFinanceApi;
import com.familyfinance.app.model.BudgetCategory;
import com.familyfinance.app.model.BudgetSummary;
import com.familyfinance.app.model.CashAccount;
import com.familyfinance.app.model.NotificationEvent;
import com.familyfinance.app.model.SafeToSpendResult;
import com.familyfinance.app.model.TransactionAssignment;
import com.familyfinance.app.model.TransactionDetail;
import com.familyfinance.app.state.BudgetScreenState;
import com.familyfinance.app.state.MoneyFormatter;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public final class MainActivity extends Activity {
    private static final String PREFS = "family_finance";
    private static final String DEFAULT_BASE_URL = "http://10.0.2.2:8080";
    private static final int DEFAULT_BUDGET_MONTH_ID = 1;
    private static final int DEFAULT_USER_ID = 1;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private LinearLayout root;
    private String baseUrl;
    private int budgetMonthId;
    private int userId;
    private FamilyFinanceApi api;
    private BudgetSummary summary;
    private List<TransactionDetail> transactions = new ArrayList<>();
    private List<TransactionDetail> reviewQueue = new ArrayList<>();
    private List<CashAccount> accounts = new ArrayList<>();
    private List<NotificationEvent> notifications = new ArrayList<>();
    private int unreadNotificationCount;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        loadPreferences();
        showLoading("Loading dashboard...");
        refreshData(this::showDashboard);
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    private void loadPreferences() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        baseUrl = prefs.getString("base_url", DEFAULT_BASE_URL);
        budgetMonthId = prefs.getInt("budget_month_id", DEFAULT_BUDGET_MONTH_ID);
        userId = prefs.getInt("user_id", DEFAULT_USER_ID);
        api = new FamilyFinanceApi(baseUrl);
    }

    private void savePreferences(String newBaseUrl, int newBudgetMonthId, int newUserId) {
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putString("base_url", newBaseUrl)
                .putInt("budget_month_id", newBudgetMonthId)
                .putInt("user_id", newUserId)
                .apply();
        loadPreferences();
    }

    private void refreshData(Runnable afterLoad) {
        executor.execute(() -> {
            try {
                BudgetSummary loadedSummary = api.getSummary(budgetMonthId);
                List<TransactionDetail> loadedTransactions = api.getTransactions(budgetMonthId);
                List<TransactionDetail> loadedReviewQueue = api.getReviewQueue(budgetMonthId);
                List<CashAccount> loadedAccounts = api.getAccounts(budgetMonthId);
                List<NotificationEvent> loadedNotifications = api.getNotifications(budgetMonthId, userId);
                int loadedUnreadNotificationCount = api.getUnreadNotificationCount(budgetMonthId, userId);
                mainHandler.post(() -> {
                    summary = loadedSummary;
                    transactions = loadedTransactions;
                    reviewQueue = loadedReviewQueue;
                    accounts = loadedAccounts;
                    notifications = loadedNotifications;
                    unreadNotificationCount = loadedUnreadNotificationCount;
                    afterLoad.run();
                });
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Could not load backend data", exception));
            }
        });
    }

    private void showDashboard() {
        beginScreen("Dashboard");
        addFact("Backend", baseUrl + "  |  Budget month ID " + budgetMonthId + "  |  User ID " + userId);
        if (summary == null) {
            addBody("No summary loaded.");
            addNav();
            return;
        }
        addMetric("Included account balance", MoneyFormatter.dollars(summary.includedAccountBalanceCents));
        addMetric("Bills before next payday", MoneyFormatter.dollars(summary.billsBeforePaydayCents));
        addMetric("Cash remaining after upcoming bills", MoneyFormatter.dollars(summary.cashAfterBillsCents));
        addMetric("Days until next payday", Integer.toString(summary.daysUntilPayday));
        if (summary.hasLowCushion()) {
            addWarning("Low cushion warning: cash remaining after bills is tight for the days until payday.");
        }
        addMetric("Uncategorized transactions", Integer.toString(reviewQueue.size()));
        addMetric("Unread notifications", Integer.toString(unreadNotificationCount));
        addFact("Notification viewer", "Unread state is scoped to user ID " + userId);
        addButton("Notifications / accountability", this::showNotifications);

        addSection("Categories needing attention");
        List<BudgetCategory> attention = summary.categoriesNeedingAttention();
        if (attention.isEmpty()) {
            addBody("No overspent or zero-remaining categories.");
        } else {
            for (BudgetCategory category : attention) {
                addButton(
                        category.name + "  " + MoneyFormatter.dollars(category.remainingCents),
                        () -> showCategoryDetail(category.id)
                );
            }
        }
        addNav();
    }

    private void showNotifications() {
        beginScreen("Notifications");
        addMetric("Unread", Integer.toString(unreadNotificationCount));
        addFact("Viewer user ID", Integer.toString(userId));
        addButton("Mark all read", () -> runMutation(
                "Marking notifications read...",
                () -> api.markAllNotificationsRead(budgetMonthId, userId),
                () -> refreshData(this::showNotifications)
        ));
        addSection("Accountability events");
        if (notifications.isEmpty()) {
            addBody("No notification events for this budget month.");
        } else {
            for (NotificationEvent notification : notifications) {
                addNotificationRow(notification);
            }
        }
        addNav();
    }

    private void showBudget() {
        beginScreen("Monthly Budget");
        if (summary == null) {
            addBody("No budget loaded.");
            addNav();
            return;
        }
        addMetric("Budget month", summary.month);
        addSection("Current budget");
        addBody("Budget group names are not exposed by the current backend summary route yet.");
        for (BudgetCategory category : summary.categories) {
            String marker = category.isOverspent() ? "OVERSPENT  " : "";
            addButton(
                    marker + category.name
                            + " | planned " + MoneyFormatter.dollars(category.plannedCents)
                            + " | spent " + MoneyFormatter.dollars(category.spentCents)
                            + " | remaining " + MoneyFormatter.dollars(category.remainingCents),
                    () -> showCategoryDetail(category.id)
            );
        }
        addNav();
    }

    private void showCategoryDetail(int categoryId) {
        beginScreen("Category Detail");
        BudgetCategory category = BudgetScreenState.findCategory(categoryId, summary == null ? null : summary.categories);
        if (category == null) {
            addBody("Category not found in loaded budget.");
            addNav();
            return;
        }
        addMetric("Category", category.name);
        addMetric("Planned", MoneyFormatter.dollars(category.plannedCents));
        addMetric("Spent", MoneyFormatter.dollars(category.spentCents));
        addMetric("Remaining", MoneyFormatter.dollars(category.remainingCents));
        addBody("Funding edits are intentionally placeholder-only until budget editing is explicitly scoped.");

        addSection("Assigned transactions");
        List<TransactionDetail> categoryTransactions = BudgetScreenState.transactionsForCategory(category.id, transactions);
        if (categoryTransactions.isEmpty()) {
            addBody("No transactions assigned to this category.");
        } else {
            for (TransactionDetail detail : categoryTransactions) {
                addTransactionButton(detail);
            }
        }
        addNav();
    }

    private void showTransactions(boolean reviewOnly) {
        beginScreen(reviewOnly ? "Uncategorized Review" : "Transactions");
        List<TransactionDetail> source = reviewOnly ? reviewQueue : transactions;
        if (source.isEmpty()) {
            addBody(reviewOnly ? "No transactions need categorization." : "No transactions returned by backend.");
        } else {
            for (TransactionDetail detail : source) {
                addTransactionButton(detail);
            }
        }
        addNav();
    }

    private void showTransactionDetail(int transactionId) {
        showLoading("Loading transaction...");
        executor.execute(() -> {
            try {
                TransactionDetail loaded = api.getTransaction(transactionId);
                mainHandler.post(() -> renderTransactionDetail(loaded));
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Could not load transaction", exception));
            }
        });
    }

    private void renderTransactionDetail(TransactionDetail detail) {
        beginScreen("Transaction Detail");
        addMetric("Name", detail.transaction.name);
        addMetric("Merchant", blankAsDash(detail.transaction.merchantName));
        addMetric("Amount", MoneyFormatter.dollars(detail.transaction.amountCents));
        addMetric("Date", detail.transaction.occurredOn);
        addMetric("Plaid hint", blankAsDash(detail.transaction.categoryHint));
        addMetric("Current assignment", describeCategory(detail.finalCategoryId));
        addMetric("Categorization status", detail.categorizationStatus);
        addMetric("Reviewed", detail.transaction.reviewed ? "Yes" : "No");
        addMetric("Ignored/excluded", detail.transaction.ignored ? "Yes" : "No");
        if (detail.isSplit()) {
            addSection("Split state");
            for (TransactionAssignment assignment : detail.assignments) {
                addBody(describeCategory(assignment.categoryId) + " | " + MoneyFormatter.dollars(assignment.amountCents));
            }
            addBody("Split editing is read-only in Milestone 4.");
        }

        addSection("Categorize");
        Spinner categorySpinner = categorySpinner();
        root.addView(categorySpinner);
        CheckBox reviewed = new CheckBox(this);
        reviewed.setText("Mark reviewed after assigning");
        reviewed.setChecked(true);
        root.addView(reviewed);
        addButton("Assign category", () -> {
            BudgetCategory category = selectedCategory(categorySpinner);
            if (category == null) {
                toast("No category selected.");
                return;
            }
            runMutation(
                    "Assigning category...",
                    () -> api.assignCategory(detail.transaction.id, category.id, reviewed.isChecked()),
                    () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
            );
        });
        addButton(detail.transaction.reviewed ? "Mark unreviewed" : "Mark reviewed", () -> runMutation(
                "Updating review state...",
                () -> api.markReviewed(detail.transaction.id, !detail.transaction.reviewed),
                () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
        ));
        addButton(detail.transaction.ignored ? "Unignore transaction" : "Ignore/exclude transaction", () -> runMutation(
                "Updating ignored state...",
                () -> api.setIgnored(detail.transaction.id, !detail.transaction.ignored, "Marked in Android MVP"),
                () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
        ));
        addNav();
    }

    private void showSafeToSpend() {
        beginScreen("Safe To Spend");
        EditText amount = new EditText(this);
        amount.setHint("Amount, e.g. 42.50");
        amount.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        root.addView(amount);

        Spinner categories = categorySpinner();
        root.addView(categories);

        EditText note = new EditText(this);
        note.setHint("Optional note or purpose");
        root.addView(note);

        addButton("Check safe to spend", () -> {
            BudgetCategory category = selectedCategory(categories);
            if (category == null) {
                toast("No category selected.");
                return;
            }
            int cents;
            try {
                cents = MoneyFormatter.parseDollarAmountToCents(amount.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Enter a valid amount.");
                return;
            }
            if (cents <= 0) {
                toast("Enter an amount greater than zero.");
                return;
            }
            showLoading("Checking safe to spend...");
            executor.execute(() -> {
                try {
                    SafeToSpendResult result = api.safeToSpend(budgetMonthId, category.id, cents);
                    mainHandler.post(() -> renderSafeToSpendResult(result, note.getText().toString()));
                } catch (Exception exception) {
                    mainHandler.post(() -> showError("Safe-to-spend check failed", exception));
                }
            });
        });
        addNav();
    }

    private void renderSafeToSpendResult(SafeToSpendResult result, String note) {
        beginScreen("Safe To Spend Result");
        addMetric("Result", result.warningLevel);
        addMetric("Budget line fits", result.budgetLineFits ? "Yes" : "No");
        addMetric("Category remaining after purchase", MoneyFormatter.dollars(result.categoryRemainingAfterCents));
        addMetric("Cash after purchase and upcoming bills", MoneyFormatter.dollars(result.cashAfterPurchaseAndBillsCents));
        addMetric("Days until payday", Integer.toString(result.daysUntilPayday));
        addMetric("Low cushion warning", result.lowCushion ? "Yes" : "No");
        addWarning(result.requiredPhrase);
        if (note != null && !note.trim().isEmpty()) {
            addBody("Purpose: " + note.trim());
        }
        addNav();
    }

    private void showSettings() {
        beginScreen("Accounts / Settings");
        addSection("Backend connection");
        EditText baseUrlInput = new EditText(this);
        baseUrlInput.setSingleLine(true);
        baseUrlInput.setText(baseUrl);
        root.addView(baseUrlInput);
        EditText budgetMonthInput = new EditText(this);
        budgetMonthInput.setHint("Budget month ID");
        budgetMonthInput.setSingleLine(true);
        budgetMonthInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        budgetMonthInput.setText(Integer.toString(budgetMonthId));
        root.addView(budgetMonthInput);
        EditText userIdInput = new EditText(this);
        userIdInput.setHint("Viewer user ID for notification read state");
        userIdInput.setSingleLine(true);
        userIdInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        userIdInput.setText(Integer.toString(userId));
        root.addView(userIdInput);
        addButton("Save and reload", () -> {
            int parsedId;
            int parsedUserId;
            try {
                parsedId = Integer.parseInt(budgetMonthInput.getText().toString());
                parsedUserId = Integer.parseInt(userIdInput.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Budget month ID and user ID must be numbers.");
                return;
            }
            savePreferences(baseUrlInput.getText().toString(), parsedId, parsedUserId);
            showLoading("Reloading...");
            refreshData(this::showDashboard);
        });
        addButton("Health check", () -> runMutation(
                "Checking health...",
                () -> api.health(),
                () -> toast("Backend health check passed.")
        ));

        addSection("Account inclusion");
        if (accounts.isEmpty()) {
            addBody("No account records returned. Plaid linking is intentionally not built in this milestone.");
        } else {
            for (CashAccount account : accounts) {
                addBody(account.name
                        + " | " + account.accountType
                        + " | " + MoneyFormatter.dollars(account.balanceCents)
                        + " | " + (account.includedInCashReality ? "included" : "excluded"));
            }
        }
        addNav();
    }

    private void addTransactionButton(TransactionDetail detail) {
        String status = detail.categorizationStatus
                + (detail.transaction.reviewed ? " | reviewed" : " | unreviewed")
                + (detail.transaction.ignored ? " | ignored" : "");
        addButton(
                detail.transaction.occurredOn
                        + "  " + detail.transaction.displayName()
                        + "  " + MoneyFormatter.dollars(detail.transaction.amountCents)
                        + "\n" + status,
                () -> showTransactionDetail(detail.transaction.id)
        );
    }

    private void addNotificationRow(NotificationEvent notification) {
        String status = notification.severityLabel()
                + " | " + notification.readStateLabel()
                + " | " + blankAsDash(notification.createdAt);
        addSection(notification.title);
        addBody(notification.message);
        addFact("Status", status);
        addFact("Type", notification.eventType);
        if (!notification.isRead()) {
            addButton("Mark read", () -> runMutation(
                    "Marking notification read...",
                    () -> api.markNotificationRead(notification.id, userId),
                    () -> refreshData(this::showNotifications)
            ));
        }
    }

    private void runMutation(String loadingMessage, ThrowingRunnable operation, Runnable onSuccess) {
        showLoading(loadingMessage);
        executor.execute(() -> {
            try {
                operation.run();
                mainHandler.post(onSuccess);
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Update failed", exception));
            }
        });
    }

    private void beginScreen(String title) {
        ScrollView scrollView = new ScrollView(this);
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(28, 28, 28, 28);
        scrollView.addView(root);
        setContentView(scrollView);
        TextView heading = new TextView(this);
        heading.setText(title);
        heading.setTextSize(26);
        heading.setGravity(Gravity.START);
        heading.setPadding(0, 0, 0, 20);
        root.addView(heading);
    }

    private void showLoading(String message) {
        beginScreen("Family Finance");
        addBody(message);
    }

    private void showError(String context, Exception exception) {
        beginScreen("Error");
        addWarning(context);
        addBody(exception.getMessage() == null ? exception.toString() : exception.getMessage());
        addButton("Retry dashboard", () -> refreshData(this::showDashboard));
        addButton("Settings", this::showSettings);
    }

    private void addNav() {
        addSection("Navigation");
        addButton("Dashboard", this::showDashboard);
        addButton("Monthly budget", this::showBudget);
        addButton("Transactions", () -> showTransactions(false));
        addButton("Uncategorized review", () -> showTransactions(true));
        addButton("Safe to spend", this::showSafeToSpend);
        addButton("Notifications", this::showNotifications);
        addButton("Accounts / settings", this::showSettings);
    }

    private void addMetric(String label, String value) {
        TextView textView = new TextView(this);
        textView.setText(label + ": " + value);
        textView.setTextSize(17);
        textView.setPadding(0, 6, 0, 6);
        root.addView(textView);
    }

    private void addFact(String label, String value) {
        TextView textView = new TextView(this);
        textView.setText(label + ": " + value);
        textView.setTextSize(13);
        textView.setPadding(0, 0, 0, 12);
        root.addView(textView);
    }

    private void addSection(String label) {
        TextView textView = new TextView(this);
        textView.setText(label);
        textView.setTextSize(20);
        textView.setPadding(0, 24, 0, 8);
        root.addView(textView);
    }

    private void addBody(String body) {
        TextView textView = new TextView(this);
        textView.setText(body);
        textView.setTextSize(15);
        textView.setPadding(0, 6, 0, 6);
        root.addView(textView);
    }

    private void addWarning(String body) {
        TextView textView = new TextView(this);
        textView.setText(body);
        textView.setTextSize(16);
        textView.setPadding(12, 12, 12, 12);
        textView.setBackgroundColor(0xFFFFF3CD);
        root.addView(textView);
    }

    private void addButton(String label, Runnable action) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText(label);
        button.setOnClickListener(view -> action.run());
        root.addView(button);
    }

    private Spinner categorySpinner() {
        Spinner spinner = new Spinner(this);
        ArrayList<String> labels = new ArrayList<>();
        if (summary != null) {
            for (BudgetCategory category : summary.categories) {
                labels.add(category.name + " (" + MoneyFormatter.dollars(category.remainingCents) + " left)");
            }
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        return spinner;
    }

    private BudgetCategory selectedCategory(Spinner spinner) {
        if (summary == null || summary.categories.isEmpty() || spinner.getSelectedItemPosition() < 0) {
            return null;
        }
        return summary.categories.get(spinner.getSelectedItemPosition());
    }

    private String describeCategory(Integer categoryId) {
        if (categoryId == null) {
            return "Uncategorized";
        }
        BudgetCategory category = BudgetScreenState.findCategory(categoryId, summary == null ? null : summary.categories);
        return category == null ? "Category #" + categoryId : category.name;
    }

    private String blankAsDash(String value) {
        return value == null || value.isEmpty() ? "-" : value;
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    private interface ThrowingRunnable {
        void run() throws Exception;
    }
}
