package com.familyfinance.app;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
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
import com.familyfinance.app.model.AppDiagnostics;
import com.familyfinance.app.model.BudgetDetail;
import com.familyfinance.app.model.BudgetGroup;
import com.familyfinance.app.model.BudgetMonth;
import com.familyfinance.app.model.BudgetCategory;
import com.familyfinance.app.model.BudgetSummary;
import com.familyfinance.app.model.CashAccount;
import com.familyfinance.app.model.ExpectedBill;
import com.familyfinance.app.model.MerchantRule;
import com.familyfinance.app.model.NotificationEvent;
import com.familyfinance.app.model.Payday;
import com.familyfinance.app.model.PlannedIncome;
import com.familyfinance.app.model.SafeToSpendResult;
import com.familyfinance.app.model.SetupStatus;
import com.familyfinance.app.model.TransactionAssignment;
import com.familyfinance.app.model.TransactionDetail;
import com.familyfinance.app.state.BudgetScreenState;
import com.familyfinance.app.state.LoginErrorMessages;
import com.familyfinance.app.state.MoneyFormatter;
import com.plaid.link.Plaid;
import com.plaid.link.PlaidHandler;
import com.plaid.link.configuration.LinkTokenConfiguration;
import com.plaid.link.result.LinkResultHandler;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.LinkedHashSet;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.time.LocalDate;
import java.time.YearMonth;

import kotlin.Unit;

public final class MainActivity extends Activity {
    private static final String PREFS = "family_finance";
    private static final String DEFAULT_BASE_URL = "http://10.0.2.2:8080";
    private static final int DEFAULT_BUDGET_MONTH_ID = 1;

    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final Handler mainHandler = new Handler(Looper.getMainLooper());

    private LinearLayout root;
    private String baseUrl;
    private int budgetMonthId;
    private int currentUserId;
    private int householdId;
    private String currentUserName;
    private String householdName;
    private String authToken;
    private FamilyFinanceApi api;
    private BudgetSummary summary;
    private BudgetDetail budgetDetail;
    private List<BudgetMonth> budgetMonths = new ArrayList<>();
    private List<TransactionDetail> transactions = new ArrayList<>();
    private List<TransactionDetail> reviewQueue = new ArrayList<>();
    private List<CashAccount> accounts = new ArrayList<>();
    private List<MerchantRule> merchantRules = new ArrayList<>();
    private List<NotificationEvent> notifications = new ArrayList<>();
    private int unreadNotificationCount;
    private PlaidHandler plaidHandler;
    private final LinkResultHandler plaidResultHandler = new LinkResultHandler(
            linkSuccess -> {
                String publicToken = linkSuccess.getPublicToken();
                if (publicToken == null || publicToken.trim().isEmpty()) {
                    toast("Plaid Link did not return a public token.");
                    return Unit.INSTANCE;
                }
                exchangePlaidPublicToken(publicToken);
                return Unit.INSTANCE;
            },
            linkExit -> {
                String message = "Plaid Link was cancelled.";
                if (linkExit.getError() != null) {
                    String display = linkExit.getError().getDisplayMessage();
                    String code = String.valueOf(linkExit.getError().getErrorCode());
                    message = (display == null || display.isEmpty() ? "Plaid Link failed" : display)
                            + (code == null || code.isEmpty() ? "" : " (" + code + ")");
                }
                toast(message);
                return Unit.INSTANCE;
            }
    );

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        loadPreferences();
        if (authToken == null || authToken.isEmpty()) {
            checkSetupThenShowLogin(null);
        } else {
            showLoading("Loading dashboard...");
            refreshData(this::showDashboard);
        }
    }

    @Override
    protected void onDestroy() {
        executor.shutdownNow();
        super.onDestroy();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        plaidResultHandler.onActivityResult(requestCode, resultCode, data);
    }

    private void loadPreferences() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        baseUrl = prefs.getString("base_url", DEFAULT_BASE_URL);
        budgetMonthId = prefs.getInt("budget_month_id", DEFAULT_BUDGET_MONTH_ID);
        authToken = prefs.getString("auth_token", "");
        currentUserId = prefs.getInt("current_user_id", 0);
        householdId = prefs.getInt("household_id", 0);
        currentUserName = prefs.getString("current_user_name", "");
        householdName = prefs.getString("household_name", "");
        api = new FamilyFinanceApi(baseUrl, authToken);
    }

    private void saveConnectionPreferences(String newBaseUrl, int newBudgetMonthId) {
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putString("base_url", newBaseUrl)
                .putInt("budget_month_id", newBudgetMonthId)
                .apply();
        loadPreferences();
    }

    private void saveAuthSession(String token, JSONObject user, JSONObject household) {
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putString("auth_token", token)
                .putInt("current_user_id", user.optInt("id"))
                .putString("current_user_name", user.optString("name"))
                .putInt("household_id", household.optInt("id"))
                .putString("household_name", household.optString("name"))
                .apply();
        loadPreferences();
    }

    private void logout() {
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .remove("auth_token")
                .remove("current_user_id")
                .remove("current_user_name")
                .remove("household_id")
                .remove("household_name")
                .apply();
        loadPreferences();
        summary = null;
        budgetDetail = null;
        budgetMonths = new ArrayList<>();
        transactions = new ArrayList<>();
        reviewQueue = new ArrayList<>();
        accounts = new ArrayList<>();
        merchantRules = new ArrayList<>();
        notifications = new ArrayList<>();
        unreadNotificationCount = 0;
        checkSetupThenShowLogin("Logged out.");
    }

    private void refreshData(Runnable afterLoad) {
        executor.execute(() -> {
            try {
                List<BudgetMonth> loadedBudgetMonths = api.getBudgetMonths();
                if (loadedBudgetMonths.isEmpty()) {
                    mainHandler.post(() -> {
                        budgetMonths = loadedBudgetMonths;
                        budgetDetail = null;
                        summary = null;
                        transactions = new ArrayList<>();
                        reviewQueue = new ArrayList<>();
                        accounts = new ArrayList<>();
                        merchantRules = new ArrayList<>();
                        notifications = new ArrayList<>();
                        unreadNotificationCount = 0;
                        afterLoad.run();
                    });
                    return;
                }
                int selectedBudgetMonthId = selectBudgetMonthId(loadedBudgetMonths);
                BudgetDetail loadedBudgetDetail = api.getBudgetDetail(selectedBudgetMonthId);
                List<TransactionDetail> loadedTransactions = api.getTransactions(selectedBudgetMonthId);
                List<TransactionDetail> loadedReviewQueue = api.getReviewQueue(selectedBudgetMonthId);
                List<CashAccount> loadedAccounts = api.getAccounts(selectedBudgetMonthId);
                List<MerchantRule> loadedMerchantRules = api.getMerchantRules();
                List<NotificationEvent> loadedNotifications = api.getNotifications(selectedBudgetMonthId);
                int loadedUnreadNotificationCount = api.getUnreadNotificationCount(selectedBudgetMonthId);
                mainHandler.post(() -> {
                    budgetDetail = loadedBudgetDetail;
                    summary = loadedBudgetDetail.summary;
                    budgetMonths = loadedBudgetMonths;
                    if (selectedBudgetMonthId != budgetMonthId) {
                        saveConnectionPreferences(baseUrl, selectedBudgetMonthId);
                    }
                    transactions = loadedTransactions;
                    reviewQueue = loadedReviewQueue;
                    accounts = loadedAccounts;
                    merchantRules = loadedMerchantRules;
                    notifications = loadedNotifications;
                    unreadNotificationCount = loadedUnreadNotificationCount;
                    afterLoad.run();
                });
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Could not load backend data", exception));
            }
        });
    }

    private int selectBudgetMonthId(List<BudgetMonth> months) {
        for (BudgetMonth month : months) {
            if (month.id == budgetMonthId) {
                return budgetMonthId;
            }
        }
        for (BudgetMonth month : months) {
            if (month.active) {
                return month.id;
            }
        }
        return months.get(0).id;
    }

    private void checkSetupThenShowLogin(String message) {
        showLoading("Checking setup status...");
        executor.execute(() -> {
            try {
                SetupStatus status = new FamilyFinanceApi(baseUrl).getSetupStatus();
                mainHandler.post(() -> {
                    if (status.canInitialize) {
                        showFirstRunSetup(message);
                    } else {
                        showLogin(message);
                    }
                });
            } catch (Exception exception) {
                mainHandler.post(() -> showLogin(
                        "Backend is unreachable at " + baseUrl + ". Check the server URL and try again."
                ));
            }
        });
    }

    private void showFirstRunSetup(String message) {
        beginScreen("First-Run Setup");
        if (message != null && !message.trim().isEmpty()) {
            addBody(message.trim());
        }
        addSection("Backend connection");
        EditText baseUrlInput = new EditText(this);
        baseUrlInput.setSingleLine(true);
        baseUrlInput.setText(baseUrl);
        root.addView(baseUrlInput);

        addSection("Private household");
        EditText householdInput = new EditText(this);
        householdInput.setHint("Household name");
        householdInput.setSingleLine(true);
        householdInput.setText("Daniel and Kara");
        root.addView(householdInput);

        addSection("Primary local user");
        EditText danielName = new EditText(this);
        danielName.setHint("Display name");
        danielName.setSingleLine(true);
        danielName.setText("Daniel");
        root.addView(danielName);
        EditText danielUsername = new EditText(this);
        danielUsername.setHint("Username");
        danielUsername.setSingleLine(true);
        root.addView(danielUsername);
        EditText danielEmail = new EditText(this);
        danielEmail.setHint("Email optional");
        danielEmail.setSingleLine(true);
        root.addView(danielEmail);
        EditText danielPassword = new EditText(this);
        danielPassword.setHint("Password");
        danielPassword.setSingleLine(true);
        danielPassword.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(danielPassword);

        addSection("Kara local user optional");
        EditText karaName = new EditText(this);
        karaName.setHint("Display name");
        karaName.setSingleLine(true);
        karaName.setText("Kara");
        root.addView(karaName);
        EditText karaUsername = new EditText(this);
        karaUsername.setHint("Username");
        karaUsername.setSingleLine(true);
        root.addView(karaUsername);
        EditText karaEmail = new EditText(this);
        karaEmail.setHint("Email optional");
        karaEmail.setSingleLine(true);
        root.addView(karaEmail);
        EditText karaPassword = new EditText(this);
        karaPassword.setHint("Password");
        karaPassword.setSingleLine(true);
        karaPassword.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(karaPassword);

        addButton("Create private household", () -> {
            String newBaseUrl = baseUrlInput.getText().toString().trim();
            String householdName = householdInput.getText().toString().trim();
            String primaryUsername = danielUsername.getText().toString().trim();
            String primaryPassword = danielPassword.getText().toString();
            String primaryName = danielName.getText().toString();
            String primaryEmail = danielEmail.getText().toString();
            String spouseName = karaName.getText().toString();
            String spouseUsername = karaUsername.getText().toString().trim();
            String spouseEmail = karaEmail.getText().toString();
            String spousePassword = karaPassword.getText().toString();
            if (householdName.isEmpty() || primaryUsername.isEmpty() || primaryPassword.isEmpty()) {
                toast("Household name, primary username, and primary password are required.");
                return;
            }
            showLoading("Creating private household...");
            executor.execute(() -> {
                try {
                    JSONArray users = new JSONArray();
                    users.put(setupUserJson(
                            primaryName,
                            primaryUsername,
                            primaryEmail,
                            primaryPassword
                    ));
                    if (!spouseUsername.isEmpty() || !spousePassword.isEmpty()) {
                        if (spouseUsername.isEmpty() || spousePassword.isEmpty()) {
                            throw new IllegalArgumentException("Kara username and password must both be filled or both left blank.");
                        }
                        users.put(setupUserJson(
                                spouseName,
                                spouseUsername,
                                spouseEmail,
                                spousePassword
                        ));
                    }
                    new FamilyFinanceApi(newBaseUrl).initializeHousehold(householdName, users);
                    mainHandler.post(() -> {
                        saveConnectionPreferences(newBaseUrl, budgetMonthId);
                        showLogin("Household created. Log in with the local credentials you just set.");
                    });
                } catch (Exception exception) {
                    mainHandler.post(() -> showFirstRunSetup(exception.getMessage()));
                }
            });
        });
        addButton("Back to login", () -> showLogin(null));
    }

    private JSONObject setupUserJson(String name, String username, String email, String password) throws Exception {
        JSONObject user = new JSONObject();
        user.put("name", name == null || name.trim().isEmpty() ? username.trim() : name.trim());
        user.put("username", username.trim());
        if (email != null && !email.trim().isEmpty()) {
            user.put("email", email.trim());
        }
        user.put("password", password);
        return user;
    }

    private void showLogin(String message) {
        beginScreen("Login");
        if (message != null && !message.trim().isEmpty()) {
            addBody(message.trim());
        }
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

        addSection("Private household login");
        EditText usernameInput = new EditText(this);
        usernameInput.setHint("Username or email");
        usernameInput.setSingleLine(true);
        root.addView(usernameInput);

        EditText passwordInput = new EditText(this);
        passwordInput.setHint("Password");
        passwordInput.setSingleLine(true);
        passwordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(passwordInput);

        addButton("Log in", () -> {
            int parsedBudgetMonthId;
            try {
                parsedBudgetMonthId = Integer.parseInt(budgetMonthInput.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Budget month ID must be a number.");
                return;
            }
            String newBaseUrl = baseUrlInput.getText().toString();
            String username = usernameInput.getText().toString().trim();
            String password = passwordInput.getText().toString();
            if (username.isEmpty() || password.isEmpty()) {
                toast("Enter username/email and password.");
                return;
            }
            showLoading("Logging in...");
            executor.execute(() -> {
                try {
                    FamilyFinanceApi loginApi = new FamilyFinanceApi(newBaseUrl);
                    JSONObject auth = loginApi.login(username, password);
                    mainHandler.post(() -> {
                        saveConnectionPreferences(newBaseUrl, parsedBudgetMonthId);
                        saveAuthSession(
                                auth.optString("token"),
                                auth.optJSONObject("user") == null ? new JSONObject() : auth.optJSONObject("user"),
                                auth.optJSONObject("household") == null ? new JSONObject() : auth.optJSONObject("household")
                        );
                        showLoading("Loading dashboard...");
                        refreshData(this::showDashboard);
                    });
                } catch (Exception exception) {
                    mainHandler.post(() -> showLogin(LoginErrorMessages.fromException(exception, newBaseUrl)));
                }
            });
        });
        addButton("Check first-run setup", () -> {
            saveConnectionPreferences(baseUrlInput.getText().toString(), budgetMonthId);
            checkSetupThenShowLogin(null);
        });
    }

    private void showDashboard() {
        beginScreen("Dashboard");
        addFact("Backend", baseUrl + "  |  Budget month ID " + budgetMonthId);
        addFact("Signed in", blankAsDash(currentUserName) + "  |  " + blankAsDash(householdName));
        if (summary == null) {
            if (budgetMonths.isEmpty()) {
                addBody("No budget month exists yet for this household.");
                addButton("Create starter budget month", this::showStarterBudget);
            } else {
                addBody("No summary loaded.");
            }
            addNav();
            return;
        }
        addMetric("Planned income", MoneyFormatter.dollars(summary.plannedIncomeTotalCents));
        addMetric("Assigned total", MoneyFormatter.dollars(summary.assignedTotalCents));
        addMetric("Remaining to assign", MoneyFormatter.dollars(summary.remainingToAssignCents));
        addMetric("Total spent", MoneyFormatter.dollars(summary.totalSpentCents));
        addMetric("Included account balance", MoneyFormatter.dollars(summary.includedAccountBalanceCents));
        addMetric("Bills before next payday", MoneyFormatter.dollars(summary.billsBeforePaydayCents));
        addMetric("Cash remaining after upcoming bills", MoneyFormatter.dollars(summary.cashAfterBillsCents));
        addMetric("Days until next payday", Integer.toString(summary.daysUntilPayday));
        if (summary.hasLowCushion()) {
            addWarning("Low cushion warning: cash remaining after bills is tight for the days until payday.");
        }
        addMetric("Uncategorized transactions", Integer.toString(reviewQueue.size()));
        addMetric("Unread notifications", Integer.toString(unreadNotificationCount));
        addFact("Notification viewer", "Unread state is scoped to the signed-in user.");
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

    private void showStarterBudget() {
        beginScreen("Starter Budget");
        addBody("Create the current budget month with starter categories. This will only work when this household has no budget months.");
        EditText nextPayday = new EditText(this);
        nextPayday.setHint("Next payday YYYY-MM-DD");
        nextPayday.setSingleLine(true);
        root.addView(nextPayday);
        addButton("Create current month", () -> {
            String payday = nextPayday.getText().toString().trim();
            if (payday.isEmpty()) {
                toast("Enter the next payday date.");
                return;
            }
            if (!isIsoDate(payday)) {
                toast("Next payday must use YYYY-MM-DD.");
                return;
            }
            runMutation(
                    "Creating starter budget...",
                    () -> {
                        int newMonthId = api.createStarterBudget(payday);
                        api.activateBudgetMonth(newMonthId);
                        saveConnectionPreferences(baseUrl, newMonthId);
                    },
                    () -> refreshData(this::showBudget)
            );
        });
        addNav();
    }

    private void showNotifications() {
        beginScreen("Notifications");
        addMetric("Unread", Integer.toString(unreadNotificationCount));
        addFact("Viewer", blankAsDash(currentUserName));
        addButton("Mark all read", () -> runMutation(
                "Marking notifications read...",
                () -> api.markAllNotificationsRead(budgetMonthId),
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
        if (summary == null || budgetDetail == null) {
            addBody("No budget month is loaded. Create a starter budget or reload after the backend is reachable.");
            if (budgetMonths.isEmpty()) {
                addButton("Create starter budget month", this::showStarterBudget);
            }
            addNav();
            return;
        }
        addMetric("Budget month", summary.month);
        addMetric("Planned income", MoneyFormatter.dollars(summary.plannedIncomeTotalCents));
        addMetric("Assigned", MoneyFormatter.dollars(summary.assignedTotalCents));
        addMetric("Remaining to assign", MoneyFormatter.dollars(summary.remainingToAssignCents));
        addMetric("Total spent", MoneyFormatter.dollars(summary.totalSpentCents));
        addButton("Switch / create budget month", this::showBudgetMonths);
        addButton("Income planning", this::showIncomePlanning);
        addButton("Bills and paydays", this::showBillsAndPaydays);

        addSection("Budget groups");
        if (budgetDetail.groups.isEmpty()) {
            addBody("No budget groups yet.");
        } else {
            for (BudgetGroup group : budgetDetail.groups) {
                addSection(group.name);
                addButton("Rename group", () -> showGroupEditor(group));
                addButton("Add category to " + group.name, () -> showCategoryEditor(null, group.id));
                if (group.categories.isEmpty()) {
                    addBody("No categories in this group.");
                } else {
                    for (BudgetCategory category : group.categories) {
                        String marker = category.isOverspent() ? "OVERSPENT  " : "";
                        addButton(
                                marker + category.name
                                        + " | planned " + MoneyFormatter.dollars(category.plannedCents)
                                        + " | spent " + MoneyFormatter.dollars(category.spentCents)
                                        + " | remaining " + MoneyFormatter.dollars(category.remainingCents),
                                () -> showCategoryDetail(category.id)
                        );
                    }
                }
            }
        }
        addButton("Add budget group", () -> showGroupEditor(null));
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
        addButton("Rename / fund category", () -> showCategoryEditor(category, category.budgetGroupId));
        addButton("Archive category", () -> runMutation(
                "Archiving category...",
                () -> api.updateCategory(category.id, category.name, category.plannedCents, true),
                () -> refreshData(this::showBudget)
        ));

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

    private void showBudgetMonths() {
        beginScreen("Budget Months");
        addMetric("Current month", summary == null ? "-" : summary.month);
        if (budgetMonths.isEmpty()) {
            addBody("No budget months returned by the backend.");
            addButton("Create starter budget month", this::showStarterBudget);
            addNav();
            return;
        }
        for (BudgetMonth month : budgetMonths) {
            addButton(
                    (month.active ? "Active  " : "") + month.month + " | ID " + month.id,
                    () -> runMutation(
                            "Switching budget month...",
                            () -> {
                                api.activateBudgetMonth(month.id);
                                saveConnectionPreferences(baseUrl, month.id);
                            },
                            () -> refreshData(this::showBudget)
                    )
            );
        }
        addButton("Create next month from current", () -> {
            if (summary == null || householdId == 0) {
                toast("No current budget month loaded.");
                return;
            }
            String nextMonth = YearMonth.parse(summary.month).plusMonths(1).toString();
            runMutation(
                    "Creating next month...",
                    () -> {
                        int newMonthId = api.createBudgetMonth(householdId, nextMonth, budgetMonthId);
                        api.activateBudgetMonth(newMonthId);
                        saveConnectionPreferences(baseUrl, newMonthId);
                    },
                    () -> refreshData(this::showBudget)
            );
        });
        addNav();
    }

    private void showGroupEditor(BudgetGroup group) {
        beginScreen(group == null ? "Add Budget Group" : "Edit Budget Group");
        EditText name = new EditText(this);
        name.setHint("Group name");
        name.setSingleLine(true);
        name.setText(group == null ? "" : group.name);
        root.addView(name);
        addButton(group == null ? "Add group" : "Save group", () -> {
            String cleaned = name.getText().toString().trim();
            if (cleaned.isEmpty()) {
                toast("Enter a group name.");
                return;
            }
            runMutation(
                    "Saving group...",
                    () -> {
                        if (group == null) {
                            api.createBudgetGroup(budgetMonthId, cleaned);
                        } else {
                            api.updateBudgetGroup(group.id, cleaned, false);
                        }
                    },
                    () -> refreshData(this::showBudget)
            );
        });
        addNav();
    }

    private void showCategoryEditor(BudgetCategory category, int groupId) {
        beginScreen(category == null ? "Add Category" : "Edit Category");
        EditText name = new EditText(this);
        name.setHint("Category name");
        name.setSingleLine(true);
        name.setText(category == null ? "" : category.name);
        root.addView(name);
        EditText planned = new EditText(this);
        planned.setHint("Planned amount, e.g. 250.00");
        planned.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        planned.setText(category == null ? "" : MoneyFormatter.dollarsWithoutSymbol(category.plannedCents));
        root.addView(planned);
        addButton(category == null ? "Add category" : "Save category", () -> {
            String cleaned = name.getText().toString().trim();
            if (cleaned.isEmpty()) {
                toast("Enter a category name.");
                return;
            }
            int plannedCents;
            try {
                plannedCents = MoneyFormatter.parseDollarAmountToCents(planned.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Enter a valid planned amount.");
                return;
            }
            runMutation(
                    "Saving category...",
                    () -> {
                        if (category == null) {
                            api.createCategory(groupId, cleaned, plannedCents);
                        } else {
                            api.updateCategory(category.id, cleaned, plannedCents, false);
                        }
                    },
                    () -> refreshData(this::showBudget)
            );
        });
        addNav();
    }

    private void showIncomePlanning() {
        beginScreen("Income Planning");
        if (summary != null) {
            addMetric("Planned income", MoneyFormatter.dollars(summary.plannedIncomeTotalCents));
            addMetric("Assigned", MoneyFormatter.dollars(summary.assignedTotalCents));
            addMetric("Remaining to assign", MoneyFormatter.dollars(summary.remainingToAssignCents));
        }
        if (budgetDetail == null || budgetDetail.income.isEmpty()) {
            addBody("No planned income yet.");
        } else {
            for (PlannedIncome income : budgetDetail.income) {
                addBody(income.name
                        + " | " + income.kind
                        + " | planned " + MoneyFormatter.dollars(income.plannedCents)
                        + " | received " + MoneyFormatter.dollars(income.receivedCents));
                addButton("Edit " + income.name, () -> showIncomeEditor(income));
                addButton("Remove " + income.name, () -> runMutation(
                        "Removing income...",
                        () -> api.deleteIncome(income.id),
                        () -> refreshData(this::showIncomePlanning)
                ));
            }
        }
        addButton("Add income", () -> showIncomeEditor(null));
        addNav();
    }

    private void showIncomeEditor(PlannedIncome income) {
        beginScreen(income == null ? "Add Income" : "Edit Income");
        EditText name = new EditText(this);
        name.setHint("Income name");
        name.setSingleLine(true);
        name.setText(income == null ? "" : income.name);
        root.addView(name);
        Spinner kind = new Spinner(this);
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, new String[]{"main", "sporadic"});
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        kind.setAdapter(adapter);
        if (income != null && "sporadic".equals(income.kind)) {
            kind.setSelection(1);
        }
        root.addView(kind);
        EditText planned = moneyInput("Planned amount", income == null ? 0 : income.plannedCents);
        EditText received = moneyInput("Received amount", income == null ? 0 : income.receivedCents);
        addButton(income == null ? "Add income" : "Save income", () -> {
            String cleaned = name.getText().toString().trim();
            if (cleaned.isEmpty()) {
                toast("Enter an income name.");
                return;
            }
            int plannedCents;
            int receivedCents;
            try {
                plannedCents = MoneyFormatter.parseDollarAmountToCents(planned.getText().toString());
                receivedCents = MoneyFormatter.parseDollarAmountToCents(received.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Enter valid amounts.");
                return;
            }
            String selectedKind = kind.getSelectedItem().toString();
            runMutation(
                    "Saving income...",
                    () -> {
                        if (income == null) {
                            api.createIncome(budgetMonthId, cleaned, selectedKind, plannedCents, receivedCents);
                        } else {
                            api.updateIncome(income.id, cleaned, selectedKind, plannedCents, receivedCents);
                        }
                    },
                    () -> refreshData(this::showIncomePlanning)
            );
        });
        addNav();
    }

    private void showBillsAndPaydays() {
        beginScreen("Bills and Paydays");
        if (summary != null) {
            addMetric("Bills before next payday", MoneyFormatter.dollars(summary.billsBeforePaydayCents));
            addMetric("Cash after bills", MoneyFormatter.dollars(summary.cashAfterBillsCents));
            addMetric("Next payday", summary.nextPayday);
            addMetric("Days until payday", Integer.toString(summary.daysUntilPayday));
        }
        addSection("Expected bills");
        if (budgetDetail == null || budgetDetail.expectedBills.isEmpty()) {
            addBody("No expected bills yet.");
        } else {
            for (ExpectedBill bill : budgetDetail.expectedBills) {
                addBody(bill.name + " | " + MoneyFormatter.dollars(bill.amountCents) + " | due " + bill.dueOn + (bill.paid ? " | paid" : ""));
                addButton("Edit " + bill.name, () -> showBillEditor(bill));
                addButton("Remove " + bill.name, () -> runMutation(
                        "Removing bill...",
                        () -> api.deleteExpectedBill(bill.id),
                        () -> refreshData(this::showBillsAndPaydays)
                ));
            }
        }
        addButton("Add bill", () -> showBillEditor(null));
        addSection("Paydays");
        if (budgetDetail == null || budgetDetail.paydays.isEmpty()) {
            addBody("No paydays configured.");
        } else {
            for (Payday payday : budgetDetail.paydays) {
                addBody(payday.paydayDate);
                addButton("Edit " + payday.paydayDate, () -> showPaydayEditor(payday));
                addButton("Remove " + payday.paydayDate, () -> runMutation(
                        "Removing payday...",
                        () -> api.deletePayday(payday.id),
                        () -> refreshData(this::showBillsAndPaydays)
                ));
            }
        }
        addButton("Add payday", () -> showPaydayEditor(null));
        addNav();
    }

    private void showBillEditor(ExpectedBill bill) {
        beginScreen(bill == null ? "Add Bill" : "Edit Bill");
        EditText name = new EditText(this);
        name.setHint("Bill name");
        name.setSingleLine(true);
        name.setText(bill == null ? "" : bill.name);
        root.addView(name);
        EditText amount = moneyInput("Amount", bill == null ? 0 : bill.amountCents);
        EditText dueOn = new EditText(this);
        dueOn.setHint("Due date YYYY-MM-DD");
        dueOn.setSingleLine(true);
        dueOn.setText(bill == null ? "" : bill.dueOn);
        root.addView(dueOn);
        CheckBox paid = new CheckBox(this);
        paid.setText("Paid");
        paid.setChecked(bill != null && bill.paid);
        root.addView(paid);
        addButton(bill == null ? "Add bill" : "Save bill", () -> {
            String cleaned = name.getText().toString().trim();
            String due = dueOn.getText().toString().trim();
            if (cleaned.isEmpty() || due.isEmpty()) {
                toast("Enter a bill name and due date.");
                return;
            }
            int amountCents;
            try {
                amountCents = MoneyFormatter.parseDollarAmountToCents(amount.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Enter a valid bill amount.");
                return;
            }
            runMutation(
                    "Saving bill...",
                    () -> {
                        if (bill == null) {
                            api.createExpectedBill(budgetMonthId, cleaned, amountCents, due, paid.isChecked());
                        } else {
                            api.updateExpectedBill(bill.id, cleaned, amountCents, due, paid.isChecked());
                        }
                    },
                    () -> refreshData(this::showBillsAndPaydays)
            );
        });
        addNav();
    }

    private void showPaydayEditor(Payday payday) {
        beginScreen(payday == null ? "Add Payday" : "Edit Payday");
        EditText paydayDate = new EditText(this);
        paydayDate.setHint("Payday YYYY-MM-DD");
        paydayDate.setSingleLine(true);
        paydayDate.setText(payday == null ? "" : payday.paydayDate);
        root.addView(paydayDate);
        addButton(payday == null ? "Add payday" : "Save payday", () -> {
            String cleaned = paydayDate.getText().toString().trim();
            if (cleaned.isEmpty()) {
                toast("Enter a payday date.");
                return;
            }
            runMutation(
                    "Saving payday...",
                    () -> {
                        if (payday == null) {
                            api.createPayday(householdId, cleaned);
                        } else {
                            api.updatePayday(payday.id, cleaned);
                        }
                    },
                    () -> refreshData(this::showBillsAndPaydays)
            );
        });
        addNav();
    }

    private void showTransactions(boolean reviewOnly) {
        beginScreen(reviewOnly ? "Uncategorized Review" : "Transactions");
        List<TransactionDetail> source = reviewOnly ? reviewQueue : transactions;
        if (source.isEmpty()) {
            addBody(reviewOnly
                    ? "No transactions need categorization right now."
                    : "No transactions returned by the backend for this budget month.");
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
        addMetric("Account", blankAsDash(detail.transaction.accountName));
        addMetric("Amount", MoneyFormatter.dollars(detail.transaction.amountCents));
        addMetric("Date", detail.transaction.occurredOn);
        addMetric("Plaid hint", blankAsDash(detail.transaction.categoryHint));
        addMetric("Suggestion", describeSuggestion(detail));
        addMetric("Current assignment", describeCategory(detail.finalCategoryId));
        addMetric("Categorization status", detail.categorizationStatus);
        addMetric("Reviewed", detail.transaction.reviewed ? "Yes" : "No");
        addMetric("Ignored/excluded", detail.transaction.ignored ? "Yes" : "No");
        addBudgetImpact(detail);
        if (detail.isSplit()) {
            addSection("Split state");
            for (TransactionAssignment assignment : detail.assignments) {
                addBody(describeCategory(assignment.categoryId) + " | " + MoneyFormatter.dollars(assignment.amountCents));
            }
            addButton("Edit split", () -> showSplitEditor(detail));
            addButton("Remove split", () -> runMutation(
                    "Removing split...",
                    () -> api.removeSplit(detail.transaction.id),
                    () -> afterTransactionSaved(detail.transaction.id)
            ));
        } else {
            addButton("Split transaction", () -> showSplitEditor(detail));
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
                    () -> afterTransactionSaved(detail.transaction.id)
            );
        });
        if (detail.finalCategoryId != null || detail.isSplit()) {
            addButton("Remove category assignment", () -> runMutation(
                    "Removing category...",
                    () -> api.removeCategory(detail.transaction.id),
                    () -> afterTransactionSaved(detail.transaction.id)
            ));
        }
        addButton(detail.transaction.reviewed ? "Mark unreviewed" : "Mark reviewed", () -> runMutation(
                "Updating review state...",
                () -> api.markReviewed(detail.transaction.id, !detail.transaction.reviewed),
                () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
        ));
        addButton(detail.transaction.ignored ? "Unignore transaction" : "Ignore/exclude transaction", () -> runMutation(
                "Updating ignored state...",
                () -> api.setIgnored(detail.transaction.id, !detail.transaction.ignored, "Marked in Android MVP"),
                () -> afterTransactionSaved(detail.transaction.id)
        ));
        addMerchantRuleControls(detail);
        addNav();
    }

    private void showSplitEditor(TransactionDetail detail) {
        beginScreen("Split Transaction");
        int totalCents = Math.abs(detail.transaction.amountCents);
        addMetric("Transaction", detail.transaction.displayName());
        addMetric("Amount to allocate", MoneyFormatter.dollars(totalCents));

        ArrayList<Spinner> categorySpinners = new ArrayList<>();
        ArrayList<EditText> amountInputs = new ArrayList<>();
        for (int i = 0; i < 3; i++) {
            addSection("Split line " + (i + 1));
            Spinner spinner = categorySpinner();
            categorySpinners.add(spinner);
            root.addView(spinner);
            int existingAmount = 0;
            if (i < detail.assignments.size()) {
                TransactionAssignment assignment = detail.assignments.get(i);
                setSpinnerToCategory(spinner, assignment.categoryId);
                existingAmount = assignment.amountCents;
            } else if (i == 0 && detail.assignments.isEmpty()) {
                existingAmount = totalCents;
            }
            amountInputs.add(moneyInput("Amount", existingAmount));
        }

        TextView remaining = new TextView(this);
        remaining.setTextSize(16);
        remaining.setPadding(0, 10, 0, 10);
        root.addView(remaining);
        Runnable updateRemaining = () -> updateSplitRemaining(amountInputs, remaining, totalCents);
        for (EditText input : amountInputs) {
            input.addTextChangedListener(new SimpleTextWatcher(updateRemaining));
        }
        updateRemaining.run();

        addButton("Save split", () -> {
            ArrayList<int[]> splits = new ArrayList<>();
            int total = 0;
            for (int i = 0; i < amountInputs.size(); i++) {
                String raw = amountInputs.get(i).getText().toString().trim();
                if (raw.isEmpty()) {
                    continue;
                }
                int cents;
                try {
                    cents = MoneyFormatter.parseDollarAmountToCents(raw);
                } catch (NumberFormatException exception) {
                    toast("Split amounts must be valid dollars.");
                    return;
                }
                if (cents <= 0) {
                    toast("Split amounts must be positive.");
                    return;
                }
                BudgetCategory category = selectedCategory(categorySpinners.get(i));
                if (category == null) {
                    toast("Choose a category for each split line.");
                    return;
                }
                splits.add(new int[]{category.id, cents});
                total += cents;
            }
            if (splits.size() < 2) {
                toast(BudgetScreenState.splitValidationMessage(totalCents, splitAmounts(splits)));
                return;
            }
            String validation = BudgetScreenState.splitValidationMessage(totalCents, splitAmounts(splits));
            if (!validation.isEmpty()) {
                toast(validation);
                return;
            }
            runMutation(
                    "Saving split...",
                    () -> api.splitTransaction(detail.transaction.id, splits, true),
                    () -> afterTransactionSaved(detail.transaction.id)
            );
        });
        addButton("Back to transaction", () -> showTransactionDetail(detail.transaction.id));
        addNav();
    }

    private void updateSplitRemaining(List<EditText> amountInputs, TextView remaining, int totalCents) {
        int allocated = 0;
        for (EditText input : amountInputs) {
            String raw = input.getText().toString().trim();
            if (raw.isEmpty()) {
                continue;
            }
            try {
                allocated += MoneyFormatter.parseDollarAmountToCents(raw);
            } catch (NumberFormatException ignored) {
                // Save validation gives the precise error; the preview just avoids crashing while typing.
            }
        }
        int left = totalCents - allocated;
        remaining.setText("Remaining to allocate: " + MoneyFormatter.dollars(left));
        remaining.setTextColor(left == 0 ? 0xFF155724 : 0xFF856404);
    }

    private void afterTransactionSaved(int transactionId) {
        refreshData(() -> {
            for (TransactionDetail next : reviewQueue) {
                if (next.transaction.id != transactionId) {
                    showTransactionDetail(next.transaction.id);
                    return;
                }
            }
            showTransactions(true);
        });
    }

    private void addBudgetImpact(TransactionDetail detail) {
        if (detail.transaction.ignored) {
            addMetric("Budget impact", "Ignored; not counted in spending");
            return;
        }
        if (detail.isSplit()) {
            addSection("Budget impact");
            for (TransactionAssignment assignment : detail.assignments) {
                BudgetCategory category = BudgetScreenState.findCategory(
                        assignment.categoryId,
                        summary == null ? null : summary.categories
                );
                if (category != null) {
                    addBody(category.name + " remaining now: " + MoneyFormatter.dollars(category.remainingCents));
                    if (category.isOverspent()) {
                        addWarning(category.name + " is overspent.");
                    }
                }
            }
            return;
        }
        Integer impactCategoryId = detail.finalCategoryId != null ? detail.finalCategoryId : detail.suggestedCategoryId;
        BudgetCategory category = impactCategoryId == null
                ? null
                : BudgetScreenState.findCategory(impactCategoryId, summary == null ? null : summary.categories);
        if (category == null) {
            addMetric("Budget impact", "No category impact yet");
            return;
        }
        if (detail.finalCategoryId != null) {
            addMetric("Budget impact", category.name + " remaining now: " + MoneyFormatter.dollars(category.remainingCents));
            if (category.isOverspent()) {
                addWarning(category.name + " is overspent.");
            }
        } else {
            int projected = category.remainingCents - Math.abs(detail.transaction.amountCents);
            addMetric("Projected impact", category.name + " would have " + MoneyFormatter.dollars(projected) + " left");
            if (projected < 0) {
                addWarning(category.name + " would be overspent.");
            }
        }
    }

    private void addMerchantRuleControls(TransactionDetail detail) {
        addSection("Merchant rule");
        MerchantRule matchingRule = findMatchingRule(detail);
        if (matchingRule != null) {
            addBody("Existing rule: " + matchingRule.merchantMatchText + " -> " + matchingRule.categoryName);
            addButton("Archive matching rule", () -> runMutation(
                    "Archiving merchant rule...",
                    () -> api.archiveMerchantRule(matchingRule.id),
                    () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
            ));
            addButton("Delete matching rule", () -> runMutation(
                    "Deleting merchant rule...",
                    () -> api.deleteMerchantRule(matchingRule.id),
                    () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
            ));
            return;
        }
        addBody("A new rule affects future matching transactions. Current unreviewed matches are optional.");
        Spinner ruleCategory = categorySpinner();
        if (detail.finalCategoryId != null) {
            setSpinnerToCategory(ruleCategory, detail.finalCategoryId);
        } else if (detail.suggestedCategoryId != null) {
            setSpinnerToCategory(ruleCategory, detail.suggestedCategoryId);
        }
        root.addView(ruleCategory);
        CheckBox applyExisting = new CheckBox(this);
        applyExisting.setText("Also apply to current unreviewed matches");
        applyExisting.setChecked(false);
        root.addView(applyExisting);
        addButton("Create merchant rule", () -> {
            BudgetCategory category = selectedCategory(ruleCategory);
            if (category == null) {
                toast("No category selected.");
                return;
            }
            runMutation(
                    "Creating merchant rule...",
                    () -> api.createMerchantRuleFromTransaction(detail.transaction.id, category.id, applyExisting.isChecked()),
                    () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
            );
        });
    }

    private String describeSuggestion(TransactionDetail detail) {
        if (detail.suggestionSource == null || detail.suggestionSource.isEmpty()) {
            return "None";
        }
        String category = detail.suggestedCategoryId == null ? "" : " -> " + describeCategory(detail.suggestedCategoryId);
        String reason = detail.suggestionReason == null || detail.suggestionReason.isEmpty()
                ? ""
                : " (" + detail.suggestionReason + ")";
        return detail.suggestionSource + category + reason;
    }

    private MerchantRule findMatchingRule(TransactionDetail detail) {
        if (detail.matchingRuleId != null) {
            for (MerchantRule rule : merchantRules) {
                if (rule.id == detail.matchingRuleId) {
                    return rule;
                }
            }
        }
        String haystack = ((detail.transaction.merchantName == null ? "" : detail.transaction.merchantName)
                + " "
                + (detail.transaction.name == null ? "" : detail.transaction.name)).toLowerCase();
        for (MerchantRule rule : merchantRules) {
            if (rule.active && !rule.merchantMatchText.isEmpty() && haystack.contains(rule.merchantMatchText)) {
                return rule;
            }
        }
        return null;
    }

    private void showSafeToSpend() {
        beginScreen("Safe To Spend");
        if (summary == null) {
            addBody("No budget month is loaded. Safe-to-spend needs backend budget and payday data.");
            addNav();
            return;
        }
        if (summary.categories.isEmpty()) {
            addBody("No active categories are available for safe-to-spend.");
            addNav();
            return;
        }
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
        if (authToken == null || authToken.isEmpty()) {
            showLogin("Log in to view settings.");
            return;
        }
        showLoading("Loading settings...");
        executor.execute(() -> {
            try {
                JSONObject accountSettings = api.getAccountSettings();
                AppDiagnostics diagnostics = api.getDiagnostics();
                mainHandler.post(() -> renderSettings(accountSettings, diagnostics, null));
            } catch (Exception exception) {
                mainHandler.post(() -> renderSettings(null, null, userFacingError(exception)));
            }
        });
    }

    private void renderSettings(JSONObject accountSettings, AppDiagnostics diagnostics, String errorMessage) {
        beginScreen("Accounts / Settings");
        if (errorMessage != null && !errorMessage.trim().isEmpty()) {
            addWarning("Could not load diagnostics: " + errorMessage);
        }
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
        addFact("Signed in", blankAsDash(currentUserName) + "  |  " + blankAsDash(householdName));
        addFact("Current user ID", currentUserId == 0 ? "-" : Integer.toString(currentUserId));
        addFact("Household ID", householdId == 0 ? "-" : Integer.toString(householdId));
        addFact("Plaid mode", "Sandbox");
        if (diagnostics != null) {
            addSection("Diagnostics");
            addFact("Backend reachable", diagnostics.backendReachable ? "Yes" : "No");
            addFact("Database initialized", diagnostics.databaseInitialized ? "Yes" : "No");
            addFact("Plaid sandbox only", diagnostics.plaidSandboxOnly ? "Yes" : "No");
            addFact("Active budget month ID", diagnostics.activeBudgetMonthId == 0 ? "-" : Integer.toString(diagnostics.activeBudgetMonthId));
            addFact("Integrity", diagnostics.integrityOk ? "OK" : "Needs attention");
            addFact("Diagnostic user", blankAsDash(diagnostics.userName));
            addFact("Diagnostic household", blankAsDash(diagnostics.householdName));
            if (!diagnostics.checks.isEmpty()) {
                addSection("Integrity checks");
                for (AppDiagnostics.DiagnosticCheck check : diagnostics.checks) {
                    String line = (check.ok ? "OK: " : "Needs attention: ") + check.message;
                    if (check.count > 0) {
                        line = line + " (" + check.count + ")";
                    }
                    if (check.ok) {
                        addBody(line);
                    } else {
                        addWarning(line);
                    }
                }
            }
        }
        addButton("Save and reload", () -> {
            int parsedId;
            try {
                parsedId = Integer.parseInt(budgetMonthInput.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Budget month ID must be a number.");
                return;
            }
            saveConnectionPreferences(baseUrlInput.getText().toString(), parsedId);
            showLoading("Reloading...");
            refreshData(this::showDashboard);
        });
        addButton("Refresh diagnostics", this::showSettings);

        addSection("Account");
        JSONObject user = accountSettings == null ? null : accountSettings.optJSONObject("user");
        JSONObject household = accountSettings == null ? null : accountSettings.optJSONObject("household");
        addFact("User", user == null ? blankAsDash(currentUserName) : blankAsDash(user.optString("name")));
        addFact("Username", user == null ? "-" : blankAsDash(user.optString("username")));
        addFact("Household", household == null ? blankAsDash(householdName) : blankAsDash(household.optString("name")));
        EditText displayNameInput = new EditText(this);
        displayNameInput.setHint("Display name");
        displayNameInput.setSingleLine(true);
        displayNameInput.setText(user == null ? currentUserName : user.optString("name"));
        root.addView(displayNameInput);
        addButton("Update display name", () -> {
            String displayName = displayNameInput.getText().toString().trim();
            if (displayName.isEmpty()) {
                toast("Enter a display name.");
                return;
            }
            runMutation(
                    "Updating display name...",
                    () -> api.updateDisplayName(displayName),
                    () -> {
                        currentUserName = displayName;
                        getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("current_user_name", displayName).apply();
                        showSettings();
                    }
            );
        });
        EditText currentPasswordInput = new EditText(this);
        currentPasswordInput.setHint("Current password");
        currentPasswordInput.setSingleLine(true);
        currentPasswordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(currentPasswordInput);
        EditText newPasswordInput = new EditText(this);
        newPasswordInput.setHint("New password");
        newPasswordInput.setSingleLine(true);
        newPasswordInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        root.addView(newPasswordInput);
        addButton("Change password", () -> {
            String currentPassword = currentPasswordInput.getText().toString();
            String newPassword = newPasswordInput.getText().toString();
            if (currentPassword.isEmpty() || newPassword.isEmpty()) {
                toast("Enter current and new passwords.");
                return;
            }
            if (newPassword.length() < 8) {
                toast("New password must be at least 8 characters.");
                return;
            }
            runMutation(
                    "Changing password...",
                    () -> api.changePassword(currentPassword, newPassword),
                    () -> {
                        toast("Password changed.");
                        showSettings();
                    }
            );
        });
        addButton("Log out", this::logout);

        addSection("Plaid Sandbox");
        addButton("Link bank with Plaid Sandbox", this::preparePlaidLink);
        addButton("Sync balances", () -> syncPlaidItems("balance"));
        addButton("Sync transactions", () -> syncPlaidItems("transaction"));

        addSection("Account inclusion");
        if (accounts.isEmpty()) {
            addBody("No linked checking or savings accounts returned. Link Plaid Sandbox or add demo accounts from the backend seed flow.");
        } else {
            for (CashAccount account : accounts) {
                addBody(account.name
                        + " | " + account.accountType
                        + " | " + MoneyFormatter.dollars(account.balanceCents)
                        + " | mask " + blankAsDash(account.mask)
                        + " | " + (account.includedInCashReality ? "included" : "excluded"));
                addButton(
                        account.includedInCashReality ? "Exclude " + account.name : "Include " + account.name,
                        () -> runMutation(
                                "Updating account inclusion...",
                                () -> api.setAccountIncluded(account.id, !account.includedInCashReality),
                                () -> refreshData(this::showSettings)
                        )
                );
            }
        }
        addNav();
    }

    private void preparePlaidLink() {
        showLoading("Preparing Plaid Sandbox Link...");
        executor.execute(() -> {
            try {
                String linkToken = api.createPlaidLinkToken();
                if (linkToken == null || linkToken.trim().isEmpty()) {
                    throw new IllegalStateException("Backend did not return a Plaid link token.");
                }
                mainHandler.post(() -> openPlaidLink(linkToken));
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Could not start Plaid Link", exception));
            }
        });
    }

    private void openPlaidLink(String linkToken) {
        try {
            plaidHandler = Plaid.create(
                    getApplication(),
                    new LinkTokenConfiguration.Builder()
                            .token(linkToken)
                            .build()
            );
            plaidHandler.open(this);
        } catch (Exception exception) {
            showError("Could not open Plaid Link", exception);
        }
    }

    private void exchangePlaidPublicToken(String publicToken) {
        showLoading("Connecting Plaid account...");
        executor.execute(() -> {
            try {
                api.exchangePlaidPublicToken(budgetMonthId, publicToken);
                mainHandler.post(() -> refreshData(this::showSettings));
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Plaid public token exchange failed", exception));
            }
        });
    }

    private void syncPlaidItems(String syncType) {
        Set<Integer> plaidItemIds = new LinkedHashSet<>();
        for (CashAccount account : accounts) {
            if (account.plaidItemId > 0) {
                plaidItemIds.add(account.plaidItemId);
            }
        }
        if (plaidItemIds.isEmpty()) {
            toast("No linked Plaid checking or savings accounts to sync.");
            return;
        }
        showLoading("Running Plaid " + syncType + " sync...");
        executor.execute(() -> {
            try {
                for (Integer plaidItemId : plaidItemIds) {
                    api.syncPlaid(plaidItemId, syncType);
                }
                mainHandler.post(() -> refreshData(this::showSettings));
            } catch (Exception exception) {
                mainHandler.post(() -> showError("Plaid sync failed", exception));
            }
        });
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
                    () -> api.markNotificationRead(notification.id),
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
        addBody(userFacingError(exception));
        addButton("Log in", () -> showLogin(null));
        addButton("Retry dashboard", () -> refreshData(this::showDashboard));
        addButton("Settings", this::showSettings);
    }

    private void addNav() {
        addSection("Navigation");
        addButton("Dashboard", this::showDashboard);
        addButton("Monthly budget", this::showBudget);
        addButton("Income planning", this::showIncomePlanning);
        addButton("Bills and paydays", this::showBillsAndPaydays);
        addButton("Transactions", () -> showTransactions(false));
        addButton("Uncategorized review", () -> showTransactions(true));
        addButton("Safe to spend", this::showSafeToSpend);
        addButton("Notifications", this::showNotifications);
        addButton("Accounts / settings", this::showSettings);
        addButton("Log out", this::logout);
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

    private EditText moneyInput(String hint, int cents) {
        EditText input = new EditText(this);
        input.setHint(hint);
        input.setSingleLine(true);
        input.setInputType(InputType.TYPE_CLASS_NUMBER | InputType.TYPE_NUMBER_FLAG_DECIMAL);
        if (cents != 0) {
            input.setText(MoneyFormatter.dollarsWithoutSymbol(cents));
        }
        root.addView(input);
        return input;
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

    private List<Integer> splitAmounts(List<int[]> splits) {
        ArrayList<Integer> amounts = new ArrayList<>();
        for (int[] split : splits) {
            amounts.add(split[1]);
        }
        return amounts;
    }

    private boolean isIsoDate(String value) {
        try {
            LocalDate.parse(value);
            return true;
        } catch (Exception exception) {
            return false;
        }
    }

    private String userFacingError(Exception exception) {
        if (exception == null) {
            return "Unknown error.";
        }
        String message = exception.getMessage() == null ? exception.toString() : exception.getMessage();
        if (message.contains("Login required") || message.contains("Authentication required")) {
            return "Session expired or login is required. Please log in again.";
        }
        if (message.contains("Plaid Sandbox is not configured")) {
            return "Plaid Sandbox is not configured on the backend.";
        }
        if (message.contains("No upcoming payday configured")) {
            return "Safe-to-spend needs an upcoming payday. Add a payday in Bills and paydays.";
        }
        if (message.contains("No active category") || message.contains("not part of budget month")) {
            return "Safe-to-spend needs an active budget category for this month.";
        }
        if (message.contains("Split amounts must equal") || message.contains("Split total must equal")) {
            return "Split total must equal the transaction amount.";
        }
        if (message.contains("Category must belong") && message.contains("active")) {
            return "That archived or unavailable category cannot be used for this action.";
        }
        return message;
    }

    private void setSpinnerToCategory(Spinner spinner, int categoryId) {
        if (summary == null) {
            return;
        }
        for (int i = 0; i < summary.categories.size(); i++) {
            if (summary.categories.get(i).id == categoryId) {
                spinner.setSelection(i);
                return;
            }
        }
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

    private static final class SimpleTextWatcher implements TextWatcher {
        private final Runnable afterChanged;

        private SimpleTextWatcher(Runnable afterChanged) {
            this.afterChanged = afterChanged;
        }

        @Override
        public void beforeTextChanged(CharSequence s, int start, int count, int after) {
        }

        @Override
        public void onTextChanged(CharSequence s, int start, int before, int count) {
        }

        @Override
        public void afterTextChanged(Editable s) {
            afterChanged.run();
        }
    }
}
