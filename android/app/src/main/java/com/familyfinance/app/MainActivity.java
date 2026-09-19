package com.familyfinance.app;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.res.ColorStateList;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.text.Editable;
import android.text.InputType;
import android.text.TextWatcher;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityNodeInfo;
import android.view.inputmethod.InputMethodManager;
import android.widget.ArrayAdapter;
import android.widget.AdapterView;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.ScrollView;
import android.widget.Spinner;
import android.widget.TextView;
import android.widget.Toast;

import com.familyfinance.app.api.FamilyFinanceApi;
import com.familyfinance.app.api.ApiException;
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
import com.familyfinance.app.state.CheckInStreak;
import com.familyfinance.app.state.CelebrationPolicy;
import com.familyfinance.app.state.ConnectionSettings;
import com.familyfinance.app.state.DashboardText;
import com.familyfinance.app.state.EncouragementMessages;
import com.familyfinance.app.state.LoginErrorMessages;
import com.familyfinance.app.state.MoneyFormatter;
import com.familyfinance.app.state.SecureSessionStore;
import com.familyfinance.app.state.SelectedCategoryAssigner;
import com.familyfinance.app.state.TransactionReviewState;
import com.familyfinance.app.ui.CelebrationOverlay;
import com.familyfinance.app.ui.HouseholdIllustrationView;
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
import java.time.ZoneId;

import kotlin.Unit;

public final class MainActivity extends Activity {
    private static final String PREFS = "family_finance";
    private static final String DEFAULT_BASE_URL = BuildConfig.DEFAULT_BACKEND_URL;
    private static final int DEFAULT_BUDGET_MONTH_ID = 1;
    private static final String PREF_LAST_BUDGET_CHECK_DATE = "last_budget_check_date";
    private static final String PREF_BUDGET_CHECK_STREAK = "budget_check_streak";
    private static final String PREF_BEST_BUDGET_CHECK_STREAK = "best_budget_check_streak";
    private static final String PREF_LAST_REVIEW_CLEAR_DATE = "last_review_clear_date";
    private static final String PREF_REVIEW_CLEAR_STREAK = "review_clear_streak";

    private static final String PREF_CELEBRATIONS = "celebration_animations";
    private Typeface headingFont;
    private static final Typeface LABEL_FONT = Typeface.create("sans-serif-medium", Typeface.NORMAL);
    private static final int COLOR_BACKGROUND = 0xFFE3EDE3;
    private static final int COLOR_SURFACE = 0xFFF8F7EE;
    private static final int COLOR_SURFACE_ALT = 0xFFD4E6D9;
    private static final int COLOR_TEXT = 0xFF203A2D;
    private static final int COLOR_MUTED = 0xFF506455;
    private static final int COLOR_BORDER = 0xFFB9CDBB;
    private static final int COLOR_PRIMARY = 0xFF246449;
    private static final int COLOR_PRIMARY_DARK = 0xFF194D3A;
    private static final int COLOR_GOLD_BG = 0xFFF8E7BF;
    private static final int COLOR_GOLD_TEXT = 0xFF6B4913;
    private static final int COLOR_WARNING_BG = 0xFFFFF4D7;
    private static final int COLOR_WARNING_TEXT = 0xFF76510A;
    private static final int COLOR_DANGER_BG = 0xFFFFECE8;
    private static final int COLOR_DANGER_TEXT = 0xFF9A3427;
    private static final int COLOR_SUCCESS_BG = 0xFFD7EBD9;
    private static final int COLOR_SUCCESS_TEXT = 0xFF155C35;

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
    private JSONObject bankStatus = new JSONObject();
    private boolean repairingBank;
    private boolean reviewingQueue;
    private String currentScreen = "";
    private volatile boolean destroyed;
    private boolean savedConnectionReset;
    private final LinkResultHandler plaidResultHandler = new LinkResultHandler(
            linkSuccess -> {
                if (repairingBank) {
                    repairingBank = false;
                    syncPlaidItems("all");
                    return Unit.INSTANCE;
                }
                String publicToken = linkSuccess.getPublicToken();
                if (publicToken == null || publicToken.trim().isEmpty()) {
                    toast("Plaid Link did not return a public token.");
                    return Unit.INSTANCE;
                }
                exchangePlaidPublicToken(publicToken);
                return Unit.INSTANCE;
            },
            linkExit -> {
                String message = linkExit.getError() == null ? "Plaid Link was cancelled."
                        : "Plaid Link could not finish. Retry or reconnect in Settings.";
                showSettings();
                toast(message);
                return Unit.INSTANCE;
            }
    );

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        headingFont = getResources().getFont(R.font.heading);
        repairingBank = savedInstanceState != null && savedInstanceState.getBoolean("repairingBank", false);
        if (!BuildConfig.DEBUG) getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        loadPreferences();
        if (savedConnectionReset) {
            showLogin("The saved backend URL was invalid and has been reset. Check the connection and log in again.");
        } else if (authToken == null || authToken.isEmpty()) {
            checkSetupThenShowLogin(null);
        } else {
            showLoading("Loading dashboard...");
            refreshData(this::showDashboard);
        }
    }

    @Override
    protected void onDestroy() {
        destroyed = true;
        mainHandler.removeCallbacksAndMessages(null);
        executor.shutdownNow();
        super.onDestroy();
    }

    private void postIfActive(Runnable action) {
        mainHandler.post(() -> {
            if (!destroyed && !isFinishing()) {
                action.run();
            }
        });
    }

    @Override
    public void onBackPressed() {
        if ("Family Finance".equals(currentScreen)) {
            return;
        }
        if ("Assignment stopped".equals(currentScreen)) {
            refreshData(() -> showTransactions(true));
            return;
        }
        if (authToken != null && !authToken.isEmpty() && !"Dashboard".equals(currentScreen)) {
            if ("Edit merchant rule".equals(currentScreen)) {
                showMerchantRules();
            } else if ("Merchant rules".equals(currentScreen)) {
                showTransactions(reviewingQueue);
            } else if ("Transaction Detail".equals(currentScreen) || "Select transactions".equals(currentScreen)) {
                showTransactions(reviewingQueue);
            } else {
                showDashboard();
            }
            return;
        }
        super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        outState.putBoolean("repairingBank", repairingBank);
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        plaidResultHandler.onActivityResult(requestCode, resultCode, data);
    }

    private void loadPreferences() {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        try {
            baseUrl = ConnectionSettings.normalizeBaseUrl(prefs.getString("base_url", DEFAULT_BASE_URL), BuildConfig.DEBUG);
        } catch (IllegalArgumentException exception) {
            baseUrl = DEFAULT_BASE_URL;
            savedConnectionReset = true;
            new SecureSessionStore(this).clear();
            prefs.edit().putString("base_url", DEFAULT_BASE_URL)
                    .remove("auth_token").remove("current_user_id").remove("current_user_name")
                    .remove("household_id").remove("household_name").apply();
        }
        budgetMonthId = prefs.getInt("budget_month_id", DEFAULT_BUDGET_MONTH_ID);
        // Legacy plaintext tokens are deliberately discarded; a fresh login encrypts the new session.
        if (prefs.contains("auth_token")) prefs.edit().remove("auth_token").commit();
        authToken = new SecureSessionStore(this).load(baseUrl);
        currentUserId = prefs.getInt("current_user_id", 0);
        householdId = prefs.getInt("household_id", 0);
        currentUserName = prefs.getString("current_user_name", "");
        householdName = prefs.getString("household_name", "");
        api = new FamilyFinanceApi(baseUrl, authToken);
    }

    private void saveConnectionPreferences(String newBaseUrl, int newBudgetMonthId) {
        newBaseUrl = ConnectionSettings.normalizeBaseUrl(newBaseUrl, BuildConfig.DEBUG);
        if (ConnectionSettings.requiresNewSession(baseUrl, newBaseUrl)) {
            clearSession();
        }
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .putString("base_url", newBaseUrl)
                .putInt("budget_month_id", newBudgetMonthId)
                .apply();
        loadPreferences();
    }

    private boolean saveAuthSession(String token, JSONObject user, JSONObject household) {
        if (!new SecureSessionStore(this).save(token, baseUrl)) {
            showLogin("The phone could not securely save your session. Please try logging in again.");
            return false;
        }
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .remove("auth_token")
                .putInt("current_user_id", user.optInt("id"))
                .putString("current_user_name", user.optString("name"))
                .putInt("household_id", household.optInt("id"))
                .putString("household_name", household.optString("name"))
                .apply();
        loadPreferences();
        return true;
    }

    private void logout() {
        FamilyFinanceApi previousApi = api;
        clearSession();
        showLoading("Signing out...");
        executor.execute(() -> {
            String message = "Logged out.";
            try { previousApi.logout(); }
            catch (ApiException exception) {
                if (exception.status != 401) message = "Signed out on this phone. The server could not be reached to revoke the session; it will expire automatically.";
            }
            String result = message;
            postIfActive(() -> showLogin(result));
        });
    }

    private void clearSession() {
        new SecureSessionStore(this).clear();
        getSharedPreferences(PREFS, MODE_PRIVATE)
                .edit()
                .remove("auth_token")
                .remove("current_user_id")
                .remove("current_user_name")
                .remove("household_id")
                .remove("household_name")
                .apply();
        loadPreferences();
        clearFinancialData();
    }

    private void clearFinancialData() {
        summary = null;
        budgetDetail = null;
        budgetMonths = new ArrayList<>();
        transactions = new ArrayList<>();
        reviewQueue = new ArrayList<>();
        accounts = new ArrayList<>();
        merchantRules = new ArrayList<>();
        notifications = new ArrayList<>();
        unreadNotificationCount = 0;
        reviewingQueue = false;
    }

    private void refreshData(Runnable afterLoad) {
        if (authToken == null || authToken.isEmpty()) {
            showLogin("Log in to load your household data.");
            return;
        }
        executor.execute(() -> {
            try {
                List<BudgetMonth> loadedBudgetMonths = api.getBudgetMonths();
                if (loadedBudgetMonths.isEmpty()) {
                    postIfActive(() -> {
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
                JSONObject loadedBankStatus = api.getBankStatus(selectedBudgetMonthId);
                List<MerchantRule> loadedMerchantRules = api.getMerchantRules();
                List<NotificationEvent> loadedNotifications = api.getNotifications(selectedBudgetMonthId);
                int loadedUnreadNotificationCount = api.getUnreadNotificationCount(selectedBudgetMonthId);
                postIfActive(() -> {
                    budgetDetail = loadedBudgetDetail;
                    summary = loadedBudgetDetail.summary;
                    budgetMonths = loadedBudgetMonths;
                    if (selectedBudgetMonthId != budgetMonthId) {
                        saveConnectionPreferences(baseUrl, selectedBudgetMonthId);
                    }
                    transactions = loadedTransactions;
                    reviewQueue = loadedReviewQueue;
                    accounts = loadedAccounts;
                    bankStatus = loadedBankStatus;
                    merchantRules = loadedMerchantRules;
                    notifications = loadedNotifications;
                    unreadNotificationCount = loadedUnreadNotificationCount;
                    afterLoad.run();
                });
            } catch (Exception exception) {
                postIfActive(() -> {
                    clearFinancialData();
                    showError("Could not load backend data", exception);
                });
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
                postIfActive(() -> {
                    if (status.canInitialize) {
                        showFirstRunSetup(message);
                    } else {
                        showLogin(message);
                    }
                });
            } catch (Exception exception) {
                postIfActive(() -> showLogin(
                        "Backend is unreachable at " + baseUrl + ". Check the server URL and try again."
                ));
            }
        });
    }

    private void showFirstRunSetup(String message) {
        beginScreen("First-Run Setup");
        if (message != null && !message.trim().isEmpty()) {
            addStatusCard("Setup note", message.trim(), COLOR_WARNING_BG, COLOR_WARNING_TEXT);
        }
        addSection("Backend connection");
        EditText baseUrlInput = new EditText(this);
        baseUrlInput.setHint("Backend URL");
        baseUrlInput.setSingleLine(true);
        baseUrlInput.setText(baseUrl);
        root.addView(baseUrlInput);

        addSection("Private household");
        EditText setupCodeInput = new EditText(this);
        setupCodeInput.setHint("Private setup code (provided with server setup)");
        setupCodeInput.setSingleLine(true);
        setupCodeInput.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_PASSWORD);
        setupCodeInput.setSaveEnabled(false);
        root.addView(setupCodeInput);
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

        addSection(BuildConfig.DEBUG ? "Kara local user optional" : "Kara");
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
            String newBaseUrl;
            try {
                newBaseUrl = ConnectionSettings.normalizeBaseUrl(baseUrlInput.getText().toString(), BuildConfig.DEBUG);
            } catch (IllegalArgumentException exception) {
                toast(exception.getMessage());
                return;
            }
            String householdName = householdInput.getText().toString().trim();
            String primaryUsername = danielUsername.getText().toString().trim();
            String primaryPassword = danielPassword.getText().toString();
            String primaryName = danielName.getText().toString();
            String primaryEmail = danielEmail.getText().toString();
            String spouseName = karaName.getText().toString();
            String spouseUsername = karaUsername.getText().toString().trim();
            String spouseEmail = karaEmail.getText().toString();
            String spousePassword = karaPassword.getText().toString();
            String setupCode = setupCodeInput.getText().toString().trim();
            if (!BuildConfig.DEBUG && (setupCode.isEmpty() || spouseUsername.isEmpty()
                    || primaryPassword.length() < 12 || spousePassword.length() < 12)) {
                toast("Enter the private setup code and both usernames. Each password needs at least 12 characters.");
                return;
            }
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
                    new FamilyFinanceApi(newBaseUrl).initializeHousehold(householdName, users, setupCode);
                    postIfActive(() -> {
                        saveConnectionPreferences(newBaseUrl, budgetMonthId);
                        showLogin("Household created. Log in with the credentials you just set.");
                    });
                } catch (Exception exception) {
                    postIfActive(() -> showFirstRunSetup(exception.getMessage()));
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
            addStatusCard("Connection note", message.trim(), COLOR_WARNING_BG, COLOR_WARNING_TEXT);
        }
        addSection("Backend connection");
        EditText baseUrlInput = new EditText(this);
        baseUrlInput.setHint("Backend URL");
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
            String newBaseUrl;
            try {
                parsedBudgetMonthId = ConnectionSettings.parseBudgetMonthId(budgetMonthInput.getText().toString());
                newBaseUrl = ConnectionSettings.normalizeBaseUrl(baseUrlInput.getText().toString(), BuildConfig.DEBUG);
            } catch (IllegalArgumentException exception) {
                toast(exception.getMessage());
                return;
            }
            String username = usernameInput.getText().toString().trim();
            String password = passwordInput.getText().toString();
            if (username.isEmpty() || password.isEmpty()) {
                toast("Enter username/email and password.");
                return;
            }
            saveConnectionPreferences(newBaseUrl, parsedBudgetMonthId);
            showLoading("Logging in...");
            executor.execute(() -> {
                try {
                    FamilyFinanceApi loginApi = new FamilyFinanceApi(newBaseUrl);
                    JSONObject auth = loginApi.login(username, password);
                    postIfActive(() -> {
                        saveConnectionPreferences(newBaseUrl, parsedBudgetMonthId);
                        if (!saveAuthSession(
                                auth.optString("token"),
                                auth.optJSONObject("user") == null ? new JSONObject() : auth.optJSONObject("user"),
                                auth.optJSONObject("household") == null ? new JSONObject() : auth.optJSONObject("household")
                        )) return;
                        showLoading("Loading dashboard...");
                        refreshData(this::showDashboard);
                    });
                } catch (Exception exception) {
                    postIfActive(() -> showLogin(LoginErrorMessages.fromException(exception, newBaseUrl)));
                }
            });
        });
        addButton("Check first-run setup", () -> {
            try {
                saveConnectionPreferences(baseUrlInput.getText().toString(), budgetMonthId);
            } catch (IllegalArgumentException exception) {
                toast(exception.getMessage());
                return;
            }
            checkSetupThenShowLogin(null);
        });
    }

    private void showDashboard() {
        beginScreen("Dashboard");
        if (summary != null) {
            LocalDate today = LocalDate.now();
            addCheckInStreakCard(recordBudgetCheckInStreak(today), today);
        }
        if (summary == null) {
            if (budgetMonths.isEmpty()) {
                addStatusCard(
                        "Ready for a starter plan",
                        "No budget month exists yet for this household. Create one, then the dashboard will fill in from backend data.",
                        COLOR_SURFACE_ALT,
                        COLOR_PRIMARY_DARK
                );
                addButton("Create starter budget month", this::showStarterBudget);
            } else {
                addWarning("No summary loaded.");
            }
            addNav();
            return;
        }
        recordReviewClearStreakIfCleared();
        addFact("Budget", DashboardText.budgetMonth(summary.month) + " · "
                + DashboardText.lastBankSync(bankStatus.optString("transactions_checked_at", ""),
                        bankStatus.optString("balance_checked_at", ""), ZoneId.systemDefault()));
        if (summary.forecastAvailable) {
            boolean lowCushion = summary.hasLowCushion();
            String cushionTitle = lowCushion ? "Cash cushion is tight"
                    : Boolean.FALSE.equals(summary.lowCushion) ? "Cushion looks steady" : "Cash after upcoming bills";
            addHeroCard(
                    cushionTitle,
                    MoneyFormatter.dollars(summary.cashAfterBillsCents),
                    "Left after upcoming bills. About " + summary.daysUntilPayday + " day"
                            + (summary.daysUntilPayday == 1 ? "" : "s")
                            + " until payday. Included balance is "
                            + MoneyFormatter.dollars(summary.includedAccountBalanceCents)
                            + ".",
                    lowCushion ? COLOR_WARNING_BG : COLOR_SURFACE_ALT,
                    lowCushion ? COLOR_WARNING_TEXT : COLOR_PRIMARY_DARK
            );
        } else {
            addHeroCard("Included account balance", MoneyFormatter.dollars(summary.includedAccountBalanceCents),
                    "Cash after bills is unavailable until you add an upcoming payday.");
            addButton("Add a payday", () -> showPaydayEditor(null));
        }
        addButton("Check safe to spend", this::showSafeToSpend);
        if (reviewQueue.isEmpty()) {
            addAllCaughtUpCard(() -> showTransactions(true));
        } else addProgressCard(
                "Transaction review",
                reviewProgressValue(),
                reviewProgressPercent(),
                reviewProgressDetail(),
                () -> showTransactions(true)
        );
        addSection("Month at a glance");
        addMetric("Planned income", MoneyFormatter.dollars(summary.plannedIncomeTotalCents));
        addMetric("Assigned total", MoneyFormatter.dollars(summary.assignedTotalCents));
        addMetric("Remaining to assign", MoneyFormatter.dollars(summary.remainingToAssignCents));
        addMetric("Total spent", MoneyFormatter.dollars(summary.totalSpentCents));
        addMetric("Bills before next payday", summary.forecastAvailable
                ? MoneyFormatter.dollars(summary.billsBeforePaydayCents) : "Add a payday to calculate");
        LinearLayout notificationsCard = addMetricCard("Unread notifications  \u203A",
                Integer.toString(unreadNotificationCount), null);
        makeCardAction(notificationsCard, "Unread notifications. " + unreadNotificationCount
                + ". Open notifications.", this::showNotifications);

        addSection("Categories needing attention");
        List<BudgetCategory> attention = summary.categoriesNeedingAttention();
        if (attention.isEmpty()) {
            addStatusCard(
                    "No red flags right now",
                    "No active categories are overspent this month.",
                    COLOR_SUCCESS_BG,
                    COLOR_SUCCESS_TEXT
            );
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
            addStatusCard(
                    "No budget month loaded",
                    "Create a starter budget or reload after the backend is reachable.",
                    COLOR_WARNING_BG,
                    COLOR_WARNING_TEXT
            );
            if (budgetMonths.isEmpty()) {
                addButton("Create starter budget month", this::showStarterBudget);
            }
            addNav();
            return;
        }
        int streak = recordBudgetCheckInStreak(LocalDate.now()).days;
        addHeroCard(
                summary.month,
                MoneyFormatter.dollars(summary.remainingToAssignCents),
                "Remaining to assign. Check-in streak: " + streak + " day"
                        + (streak == 1 ? "" : "s") + "."
        );
        addFact("Planned income", MoneyFormatter.dollars(summary.plannedIncomeTotalCents));
        addFact("Assigned / spent", MoneyFormatter.dollars(summary.assignedTotalCents)
                + " / " + MoneyFormatter.dollars(summary.totalSpentCents));
        addSecondaryButton("Switch / create budget month", this::showBudgetMonths);

        addSection("Budget groups");
        if (budgetDetail.groups.isEmpty()) {
            addStatusCard(
                    "No groups yet",
                    "Add a budget group to start organizing household spending.",
                    COLOR_SURFACE_ALT,
                    COLOR_PRIMARY_DARK
            );
        } else {
            for (BudgetGroup group : budgetDetail.groups) {
                addIconSection(group.name, categoryIcon(group.name));
                if (group.categories.isEmpty()) {
                    addBody("No categories in this group yet.");
                } else {
                    for (BudgetCategory category : group.categories) {
                        addCategoryCard(category);
                    }
                }
                addSecondaryButton("Rename " + group.name, () -> showGroupEditor(group));
                addSecondaryButton("Add category to " + group.name, () -> showCategoryEditor(null, group.id));
            }
        }
        addSecondaryButton("Add budget group", () -> showGroupEditor(null));
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
        addDangerButton("Archive category", () -> runMutation(
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
            if (plannedCents < 0) {
                toast("Planned amount cannot be negative.");
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
                addDangerButton("Remove " + income.name, () -> runMutation(
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
            if (plannedCents < 0 || receivedCents < 0) {
                toast("Income amounts cannot be negative.");
                return;
            }
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
        if (summary != null && summary.forecastAvailable) {
            addMetric("Bills before next payday", MoneyFormatter.dollars(summary.billsBeforePaydayCents));
            addMetric("Cash after bills", MoneyFormatter.dollars(summary.cashAfterBillsCents));
            addMetric("Next payday", summary.nextPayday);
            addMetric("Days until payday", Integer.toString(summary.daysUntilPayday));
        } else if (summary != null) {
            addWarning("Add an upcoming payday to calculate bills and cash remaining before payday.");
        }
        addSection("Expected bills");
        if (budgetDetail == null || budgetDetail.expectedBills.isEmpty()) {
            addBody("No expected bills yet.");
        } else {
            for (ExpectedBill bill : budgetDetail.expectedBills) {
                addBody(bill.name + " | " + MoneyFormatter.dollars(bill.amountCents) + " | due " + bill.dueOn + (bill.paid ? " | paid" : ""));
                addButton("Edit " + bill.name, () -> showBillEditor(bill));
                addDangerButton("Remove " + bill.name, () -> runMutation(
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
                addDangerButton("Remove " + payday.paydayDate, () -> runMutation(
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
            if (!isIsoDate(due)) {
                toast("Due date must use YYYY-MM-DD.");
                return;
            }
            int amountCents;
            try {
                amountCents = MoneyFormatter.parseDollarAmountToCents(amount.getText().toString());
            } catch (NumberFormatException exception) {
                toast("Enter a valid bill amount.");
                return;
            }
            if (amountCents < 0) {
                toast("Bill amount cannot be negative.");
                return;
            }
            final boolean isPaid = paid.isChecked();
            runMutation(
                    "Saving bill...",
                    () -> {
                        if (bill == null) {
                            api.createExpectedBill(budgetMonthId, cleaned, amountCents, due, isPaid);
                        } else {
                            api.updateExpectedBill(bill.id, cleaned, amountCents, due, isPaid);
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
            if (!isIsoDate(cleaned)) {
                toast("Payday must use YYYY-MM-DD.");
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
        reviewingQueue = reviewOnly;
        beginScreen(reviewOnly ? "Transaction Review" : "Transactions");
        addSecondaryButton("Merchant rules", this::showMerchantRules);
        List<TransactionDetail> source = reviewOnly ? reviewQueue : transactions;
        if (reviewOnly) {
            recordReviewClearStreakIfCleared();
            if (reviewQueue.isEmpty()) addAllCaughtUpCard(null);
            else addProgressCard(
                    "Review queue",
                    reviewProgressValue(),
                    reviewProgressPercent(),
                    reviewProgressDetail()
            );
        }
        if (source.isEmpty()) {
            if (!reviewOnly) addStatusCard(
                    "No transactions yet",
                    "Your transactions will appear here after they are added or synced.",
                    COLOR_SUCCESS_BG,
                    COLOR_SUCCESS_TEXT
            );
        } else {
            if (reviewOnly && source.stream().anyMatch(TransactionReviewState::canAssignTogether)) {
                addSecondaryButton("Select transactions", this::showTransactionSelection);
            }
            for (TransactionDetail detail : source) {
                addTransactionButton(detail);
            }
        }
        addNav();
    }

    private void showTransactionSelection() {
        reviewingQueue = true;
        beginScreen("Select transactions");
        addBody("Choose spending transactions for the same category. Refunds and splits are reviewed individually.");
        List<TransactionDetail> selected = new ArrayList<>();
        LinearLayout footer = new LinearLayout(this);
        footer.setOrientation(LinearLayout.HORIZONTAL);
        footer.setPadding(dp(14), dp(8), dp(14), dp(8));
        footer.setBackgroundColor(COLOR_BACKGROUND);
        Button cancel = selectionAction("Cancel", false);
        cancel.setOnClickListener(view -> showTransactions(true));
        footer.addView(cancel);
        Button choose = selectionAction("Assign selected (0)", true);
        choose.setEnabled(false);
        choose.setOnClickListener(view -> showSelectedCategoryDialog(new ArrayList<>(selected)));
        footer.addView(choose);
        for (TransactionDetail detail : reviewQueue) {
            if (!TransactionReviewState.canAssignTogether(detail)) continue;
            CheckBox row = new CheckBox(this);
            row.setText(detail.transaction.displayName() + "\n"
                    + MoneyFormatter.dollars(detail.transaction.amountCents) + " | " + detail.transaction.occurredOn
                    + "\n" + detail.transaction.accountName + " | " + transactionStatusLabel(detail));
            row.setPadding(dp(12), dp(12), dp(12), dp(12));
            row.setMinHeight(dp(80));
            row.setBackground(rounded(COLOR_SURFACE, COLOR_BORDER, 14));
            row.setOnCheckedChangeListener((button, checked) -> {
                if (checked) selected.add(detail); else selected.remove(detail);
                choose.setText("Assign selected (" + selected.size() + ")");
                choose.setEnabled(!selected.isEmpty());
                row.setBackground(rounded(checked ? COLOR_SURFACE_ALT : COLOR_SURFACE,
                        checked ? COLOR_PRIMARY : COLOR_BORDER, 14));
            });
            root.addView(row);
        }
        // Keep the action within reach while the list scrolls.
        ScrollView scroll = (ScrollView) root.getParent();
        ((ViewGroup) scroll.getParent()).removeView(scroll);
        scroll.setOnApplyWindowInsetsListener(null);
        scroll.setPadding(0, 0, 0, 0);
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(COLOR_BACKGROUND);
        screen.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        screen.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1));
        screen.addView(footer);
        setContentView(screen);
        screen.requestApplyInsets();
    }

    private Button selectionAction(String text, boolean primary) {
        Button button = new Button(this);
        button.setText(text);
        button.setAllCaps(false);
        button.setTextSize(15);
        button.setMinHeight(dp(52));
        button.setTextColor(primary ? COLOR_SURFACE : COLOR_PRIMARY_DARK);
        button.setBackgroundTintList(new ColorStateList(
                new int[][]{new int[]{-android.R.attr.state_enabled}, new int[]{}},
                new int[]{COLOR_BORDER, primary ? COLOR_PRIMARY : COLOR_SURFACE}));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT,
                primary ? 2 : 1);
        params.setMargins(dp(4), 0, dp(4), 0);
        button.setLayoutParams(params);
        return button;
    }

    private void showSelectedCategoryDialog(List<TransactionDetail> selected) {
        if (selected.isEmpty()) return;
        LinearLayout content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setPadding(dp(20), dp(8), dp(20), dp(8));
        long total = 0;
        for (TransactionDetail detail : selected) total -= (long) detail.transaction.amountCents;
        content.addView(mutedText(MoneyFormatter.dollars(total) + " in spending. Assigning also marks these transactions reviewed."));
        Spinner category = categorySpinner();
        category.setMinimumHeight(dp(54));
        content.addView(category);
        AlertDialog dialog = new AlertDialog.Builder(this)
                .setTitle("Assign " + selected.size() + " transaction" + (selected.size() == 1 ? "" : "s"))
                .setView(content)
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Assign selected", null)
                .create();
        dialog.setOnShowListener(ignored -> {
            Button assign = dialog.getButton(AlertDialog.BUTTON_POSITIVE);
            assign.setEnabled(false);
            category.setOnItemSelectedListener(new AdapterView.OnItemSelectedListener() {
                @Override
                public void onItemSelected(AdapterView<?> parent, View view, int position, long id) {
                    assign.setEnabled(selectedCategory(category) != null);
                }
                @Override
                public void onNothingSelected(AdapterView<?> parent) { assign.setEnabled(false); }
            });
            assign.setOnClickListener(view -> {
                BudgetCategory choice = selectedCategory(category);
                if (choice == null) return;
                dialog.dismiss();
                assignSelectedTransactions(selected, choice);
            });
        });
        dialog.show();
    }

    private void assignSelectedTransactions(List<TransactionDetail> selected, BudgetCategory category) {
        FamilyFinanceApi assignmentApi = api;
        boolean hadPending = selected.stream().anyMatch(chosen -> reviewQueue.stream()
                .anyMatch(pending -> pending.transaction.id == chosen.transaction.id));
        showLoading("Assigning " + selected.size() + " transactions...");
        executor.execute(() -> {
            SelectedCategoryAssigner.Result result = SelectedCategoryAssigner.assign(selected, category.id,
                    new SelectedCategoryAssigner.Gateway() {
                        private void ensureActive() throws ApiException {
                            if (destroyed || Thread.currentThread().isInterrupted()) {
                                throw new ApiException("Assignment interrupted. Reload to check the saved transactions.");
                            }
                        }
                        @Override
                        public TransactionDetail load(int id) throws Exception {
                            ensureActive();
                            return assignmentApi.getTransaction(id);
                        }
                        @Override
                        public void assignAndReview(int id, int categoryId) throws Exception {
                            ensureActive();
                            assignmentApi.assignCategory(id, categoryId, true);
                        }
                    });
            postIfActive(() -> {
                String saved = result.confirmed + " transaction" + (result.confirmed == 1 ? "" : "s")
                        + " assigned to " + category.name + " and reviewed.";
                if (result.error == null && !result.changed) {
                    refreshData(() -> {
                        showTransactions(true);
                        showReviewReward(CelebrationPolicy.reviewReward(
                                result.confirmed == selected.size(), hadPending, reviewQueue.isEmpty(), true), saved);
                    });
                } else if (result.error != null && handleExpiredSession(result.error)) {
                    toast(saved + " Log in again to check the remaining transactions.");
                } else {
                    beginScreen("Assignment stopped");
                    addBody(saved);
                    addBody(result.changed
                            ? "A selected transaction changed since you selected it. Reload the review queue before continuing."
                            : "The remaining saves could not be confirmed. Reload to see what was saved before trying again.");
                    addButton("Reload review queue", () -> refreshData(() -> showTransactions(true)));
                }
            });
        });
    }

    private void showTransactionDetail(int transactionId) {
        showTransactionDetail(transactionId, () -> {});
    }

    private void showTransactionDetail(int transactionId, Runnable afterRender) {
        showLoading("Loading transaction...");
        executor.execute(() -> {
            try {
                TransactionDetail loaded = api.getTransaction(transactionId);
                postIfActive(() -> {
                    renderTransactionDetail(loaded);
                    afterRender.run();
                });
            } catch (Exception exception) {
                postIfActive(() -> showError("Could not load transaction", exception));
            }
        });
    }

    private void renderTransactionDetail(TransactionDetail detail) {
        beginScreen("Transaction Detail");
        addHeroCard(detail.transaction.displayName(), MoneyFormatter.dollars(detail.transaction.amountCents),
                detail.transaction.occurredOn + " · " + blankAsDash(detail.transaction.accountName));
        addFact("Status", transactionStatusLabel(detail) + (detail.transaction.pending ? " · pending" : ""));
        addFact("Current category", detail.isSplit() ? "Split across categories" : describeCategory(detail.finalCategoryId));
        addFact("Suggestion", describeSuggestion(detail));
        if (!detail.transaction.name.equals(detail.transaction.displayName())) {
            addFact("Imported name", detail.transaction.name);
        }
        if (detail.transaction.categoryHint != null && !detail.transaction.categoryHint.isEmpty()) {
            addFact("Import hint", detail.transaction.categoryHint);
        }
        addBudgetImpact(detail);
        if (detail.transaction.ignored) {
            addBody("Unignore this transaction before assigning a category or splitting it.");
            addButton("Unignore transaction", () -> runMutation(
                    "Updating ignored state...",
                    () -> api.setIgnored(detail.transaction.id, false, "Unignored in Android"),
                    () -> afterTransactionSaved(detail.transaction.id)
            ));
            addNav();
            return;
        }
        if (TransactionReviewState.canConfirmExisting(detail)) {
            String confirmLabel = detail.isSplit() ? "Confirm existing split"
                    : detail.finalCategoryId != null ? "Confirm current category" : "Confirm incoming transaction";
            addButton(confirmLabel, () -> runMutation(
                    "Confirming transaction...",
                    () -> api.markReviewed(detail.transaction.id, true),
                    () -> afterTransactionSaved(detail.transaction.id, true)));
        }
        if (detail.isSplit()) {
            addSection("Split state");
            for (TransactionAssignment assignment : detail.assignments) {
                addBody(describeCategory(assignment.categoryId) + " | " + MoneyFormatter.dollars(assignment.amountCents));
            }
            addButton("Edit split", () -> showSplitEditor(detail));
            addDangerButton("Remove split", () -> runMutation(
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
        addButton(detail.transaction.amountCents > 0 ? "Apply posted refund to category" : "Assign category", () -> {
            BudgetCategory category = selectedCategory(categorySpinner);
            if (category == null) {
                toast("No category selected.");
                return;
            }
            runMutation(
                    "Assigning category...",
                    () -> {
                        if (detail.transaction.amountCents > 0) api.assignRefund(detail.transaction.id, category.id);
                        else api.assignCategory(detail.transaction.id, category.id, true);
                    },
                    () -> afterTransactionSaved(detail.transaction.id, true)
            );
        });
        if (detail.finalCategoryId != null || detail.isSplit()) {
            addDangerButton("Remove category assignment", () -> runMutation(
                    "Removing category...",
                    () -> api.removeCategory(detail.transaction.id),
                    () -> afterTransactionSaved(detail.transaction.id)
            ));
        }
        addDangerButton(detail.transaction.ignored ? "Unignore transaction" : "Ignore/exclude transaction", () -> runMutation(
                "Updating ignored state...",
                () -> api.setIgnored(detail.transaction.id, !detail.transaction.ignored, "Marked in Android MVP"),
                () -> afterTransactionSaved(detail.transaction.id)
        ));
        addButton("Mark as transfer (exclude from budget)", () -> runMutation(
                "Marking transfer...",
                () -> api.setIgnored(detail.transaction.id, true, "Transfer confirmed by household"),
                () -> afterTransactionSaved(detail.transaction.id)));
        addBody("A transfer affects the bank balance but is excluded from category spending. Apply incoming money as a refund only when it reverses spending; record pay in the income plan.");
        addMerchantRuleControls(detail);
        addNav();
    }

    private void showSplitEditor(TransactionDetail detail) {
        beginScreen("Split Transaction");
        long magnitude = Math.abs((long) detail.transaction.amountCents);
        if (magnitude > Integer.MAX_VALUE) {
            addWarning("This transaction exceeds the amount supported by the split editor.");
            addButton("Back to transaction", () -> showTransactionDetail(detail.transaction.id));
            addNav();
            return;
        }
        int totalCents = (int) magnitude;
        addMetric("Transaction", detail.transaction.displayName());
        addMetric("Amount to allocate", MoneyFormatter.dollars(totalCents));

        ArrayList<Spinner> categorySpinners = new ArrayList<>();
        ArrayList<EditText> amountInputs = new ArrayList<>();
        for (int i = 0; i < Math.max(3, detail.assignments.size()); i++) {
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
                    () -> afterTransactionSaved(detail.transaction.id, true)
            );
        });
        addButton("Back to transaction", () -> showTransactionDetail(detail.transaction.id));
        addNav();
    }

    private void updateSplitRemaining(List<EditText> amountInputs, TextView remaining, int totalCents) {
        long allocated = 0;
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
        long left = totalCents - allocated;
        remaining.setText("Remaining to allocate: " + MoneyFormatter.dollars(left));
        remaining.setTextColor(left == 0 ? 0xFF155724 : 0xFF856404);
    }

    private void afterTransactionSaved(int transactionId) {
        afterTransactionSaved(transactionId, false);
    }

    private void afterTransactionSaved(int transactionId, boolean rewardReview) {
        boolean hadPending = reviewQueue.stream().anyMatch(pending -> pending.transaction.id == transactionId);
        refreshData(() -> {
            boolean confirmedReviewed = transactions.stream().anyMatch(detail ->
                    detail.transaction.id == transactionId && !detail.needsReview && !detail.transaction.ignored);
            CelebrationPolicy.Reward reward = CelebrationPolicy.reviewReward(
                    rewardReview && confirmedReviewed, hadPending, reviewQueue.isEmpty(), true);
            Runnable afterRender = () -> showReviewReward(reward, "Saved and reviewed. One more handled!");
            if (!reviewingQueue) {
                showTransactionDetail(transactionId, afterRender);
                return;
            }
            for (TransactionDetail pending : reviewQueue) {
                if (pending.transaction.id == transactionId) {
                    showTransactionDetail(transactionId, afterRender);
                    return;
                }
            }
            for (TransactionDetail next : reviewQueue) {
                if (next.transaction.id != transactionId) {
                    showTransactionDetail(next.transaction.id, afterRender);
                    return;
                }
            }
            showTransactions(true);
            afterRender.run();
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
            addMetric("Suggested category remaining", category.name + ": " + MoneyFormatter.dollars(category.remainingCents));
            addBody("This suggestion has not been assigned. Save a category to update the budget.");
        }
    }

    private void addMerchantRuleControls(TransactionDetail detail) {
        addSection("Merchant rule");
        addSecondaryButton("Manage merchant rules", this::showMerchantRules);
        MerchantRule matchingRule = findMatchingRule(detail);
        if (matchingRule != null) {
            addBody("Existing rule: " + matchingRule.merchantMatchText + " -> " + matchingRule.categoryName);
            addDangerButton("Archive matching rule", () -> runMutation(
                    "Archiving merchant rule...",
                    () -> api.archiveMerchantRule(matchingRule.id),
                    () -> refreshData(() -> showTransactionDetail(detail.transaction.id))
            ));
            return;
        }
        addBody("A new rule affects future matching transactions. Current unreviewed matches are optional.");
        Spinner ruleCategory = categorySpinner();
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
            boolean includeExisting = applyExisting.isChecked();
            runMutation(
                    "Creating merchant rule...",
                    () -> api.createMerchantRuleFromTransaction(detail.transaction.id, category.id, includeExisting),
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

    private void showMerchantRules() {
        showLoading("Loading merchant rules...");
        executor.execute(() -> {
            try {
                List<MerchantRule> loaded = api.getMerchantRules();
                postIfActive(() -> {
                    merchantRules = loaded;
                    renderMerchantRules(false);
                });
            } catch (Exception exception) {
                postIfActive(() -> showError("Could not load merchant rules", exception));
            }
        });
    }

    private void renderMerchantRules(boolean includeDeleted) {
        beginScreen("Merchant rules");
        addBody("Rules assign categories to future matching transactions. You still review those transactions.");
        List<MerchantRule> sorted = new ArrayList<>(merchantRules);
        sorted.sort((left, right) -> {
            if (left.active != right.active) return left.active ? -1 : 1;
            return String.CASE_INSENSITIVE_ORDER.compare(left.merchantMatchText, right.merchantMatchText);
        });
        long activeCount = sorted.stream().filter(rule -> rule.active).count();
        addSection(activeCount + " active rule" + (activeCount == 1 ? "" : "s"));
        if (activeCount == 0) addBody("Create a rule from a transaction's detail screen.");
        if (activeCount < sorted.size()) {
            CheckBox deleted = new CheckBox(this);
            deleted.setText("Show deleted rules");
            deleted.setChecked(includeDeleted);
            deleted.setOnCheckedChangeListener((button, checked) -> renderMerchantRules(checked));
            root.addView(deleted);
        }
        for (MerchantRule rule : sorted) {
            if (!rule.active && !includeDeleted) continue;
            LinearLayout card = cardLayout(COLOR_SURFACE, COLOR_BORDER);
            TextView merchant = smallLabel(rule.merchantMatchText);
            merchant.setTextSize(17);
            card.addView(merchant);
            card.addView(mutedText(rule.categoryName + (rule.active ? "" : " · Deleted")));
            if (rule.active) {
                LinearLayout actions = new LinearLayout(this);
                for (String label : new String[]{"Edit", "Delete"}) {
                    Button button = new Button(this);
                    button.setText(label);
                    button.setAllCaps(false);
                    button.setContentDescription(label + " rule for " + rule.merchantMatchText);
                    button.setTextColor("Delete".equals(label) ? COLOR_DANGER_TEXT : COLOR_PRIMARY_DARK);
                    button.setOnClickListener(view -> {
                        if ("Edit".equals(label)) showMerchantRuleEditor(rule);
                        else confirmDeleteMerchantRule(rule);
                    });
                    actions.addView(button, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
                }
                card.addView(actions);
            }
            root.addView(card);
        }
        addSecondaryButton("Back to transactions", () -> showTransactions(reviewingQueue));
        addNav();
    }

    private void showMerchantRuleEditor(MerchantRule rule) {
        beginScreen("Edit merchant rule");
        addBody("Changes apply to future matches. Existing transaction categories stay as they are.");
        addSection("Merchant text to match");
        EditText match = new EditText(this);
        match.setSingleLine(true);
        match.setText(rule.merchantMatchText);
        root.addView(match);
        addSection("Category");
        addBody("Current category: " + rule.categoryName);
        Spinner category = categorySpinner();
        setSpinnerToCategory(category, rule.categoryId);
        root.addView(category);
        addButton("Save rule", () -> {
            String text = match.getText().toString().trim();
            BudgetCategory selected = selectedCategory(category);
            if (text.isEmpty()) {
                toast("Enter merchant text to match.");
                return;
            }
            if (selected == null) {
                toast("Choose an active category.");
                return;
            }
            runMutation("Saving merchant rule...",
                    () -> api.updateMerchantRule(rule.id, text, selected.id), this::showMerchantRules);
        });
        addSecondaryButton("Cancel", this::showMerchantRules);
    }

    private void confirmDeleteMerchantRule(MerchantRule rule) {
        new AlertDialog.Builder(this)
                .setTitle("Delete merchant rule?")
                .setMessage("Stop automatically categorizing matches for \"" + rule.merchantMatchText
                        + "\"? Past transactions and their categories will stay unchanged.")
                .setNegativeButton("Cancel", null)
                .setPositiveButton("Delete", (dialog, which) -> runMutation("Deleting merchant rule...",
                        () -> api.archiveMerchantRule(rule.id), this::showMerchantRules))
                .show();
    }

    private MerchantRule findMatchingRule(TransactionDetail detail) {
        if (detail.matchingRuleId != null) {
            for (MerchantRule rule : merchantRules) {
                if (rule.active && rule.id == detail.matchingRuleId) {
                    return rule;
                }
            }
        }
        return null;
    }

    private String safeToSpendTitle(String warningLevel) {
        if ("safe".equals(warningLevel)) {
            return "Looks safe";
        }
        if ("caution".equals(warningLevel)) {
            return "Use caution";
        }
        if ("no".equals(warningLevel)) {
            return "Not a good idea";
        }
        if ("discuss".equals(warningLevel)) {
            return "Talk it over first";
        }
        return "Backend result";
    }

    private int safeToSpendBackground(String warningLevel) {
        if ("safe".equals(warningLevel)) {
            return COLOR_SUCCESS_BG;
        }
        if ("no".equals(warningLevel) || "discuss".equals(warningLevel)) {
            return COLOR_DANGER_BG;
        }
        return COLOR_WARNING_BG;
    }

    private int safeToSpendTextColor(String warningLevel) {
        if ("safe".equals(warningLevel)) {
            return COLOR_SUCCESS_TEXT;
        }
        if ("no".equals(warningLevel) || "discuss".equals(warningLevel)) {
            return COLOR_DANGER_TEXT;
        }
        return COLOR_WARNING_TEXT;
    }

    private void showSafeToSpend() {
        beginScreen("Safe To Spend");
        if (summary == null) {
            addStatusCard(
                    "Budget data needed",
                    "Safe-to-spend needs backend budget and payday data before it can answer.",
                    COLOR_WARNING_BG,
                    COLOR_WARNING_TEXT
            );
            addNav();
            return;
        }
        if (BudgetScreenState.activeCategories(summary.categories).isEmpty()) {
            addStatusCard(
                    "No active categories",
                    "Safe-to-spend needs an active category for this month.",
                    COLOR_WARNING_BG,
                    COLOR_WARNING_TEXT
            );
            addNav();
            return;
        }
        if (!summary.forecastAvailable) {
            addWarning("Add an upcoming payday before checking safe to spend.");
            addButton("Add a payday", () -> showPaydayEditor(null));
            addNav();
            return;
        }
        addStatusCard(
                "Ask before spending",
                "Choose the category and amount. We'll sync your connected bank before checking your budget and upcoming bills.",
                COLOR_SURFACE_ALT,
                COLOR_PRIMARY_DARK
        );
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
            String purpose = note.getText().toString();
            checkSafeToSpend(category.id, cents, purpose);
        });
        addNav();
    }

    private void checkSafeToSpend(int categoryId, int cents, String purpose) {
        showLoading("Syncing bank data and checking safe to spend...");
        FamilyFinanceApi requestApi = api;
        int monthId = budgetMonthId;
        executor.execute(() -> {
            try {
                SafeToSpendResult result = requestApi.syncAndCheckSafeToSpend(monthId, categoryId, cents);
                postIfActive(() -> refreshData(() -> renderSafeToSpendResult(result, purpose)));
            } catch (Exception exception) {
                postIfActive(() -> {
                    if (handleExpiredSession(exception)) return;
                    beginScreen("Safe to spend needs attention");
                    addStatusCard("We couldn't finish this check", userFacingError(exception), COLOR_WARNING_BG, COLOR_WARNING_TEXT);
                    addButton("Retry this amount", () -> checkSafeToSpend(categoryId, cents, purpose));
                    addSecondaryButton("Review transactions", () -> refreshData(() -> showTransactions(true)));
                    addSecondaryButton("Accounts / settings", this::showSettings);
                    addSecondaryButton("Back to dashboard", () -> refreshData(this::showDashboard));
                });
            }
        });
    }

    private void renderSafeToSpendResult(SafeToSpendResult result, String note) {
        beginScreen("Safe To Spend Result");
        int background = safeToSpendBackground(result.warningLevel);
        int textColor = safeToSpendTextColor(result.warningLevel);
        addStatusCard(
                safeToSpendTitle(result.warningLevel),
                result.requiredPhrase,
                background,
                textColor
        );
        addFact("Category", result.categoryName);
        addBody("Good call checking before you spend.");
        addFact("Budget month", summary == null ? "" : summary.month);
        addMetric("Budget line fits", result.budgetLineFits ? "Yes" : "No");
        addMetric("Category remaining after purchase", MoneyFormatter.dollars(result.categoryRemainingAfterCents));
        addMetric("Cash after purchase and upcoming bills", MoneyFormatter.dollars(result.cashAfterPurchaseAndBillsCents));
        addMetric("Days until payday", Integer.toString(result.daysUntilPayday));
        addMetric("Low cushion warning", result.lowCushion ? "Yes" : "No");
        if (note != null && !note.trim().isEmpty()) {
            addBody("Purpose: " + note.trim());
        }
        addButton("Check another amount", this::showSafeToSpend);
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
                JSONObject loadedBankStatus = budgetMonthId > 0 ? api.getBankStatus(budgetMonthId) : new JSONObject();
                List<CashAccount> loadedBankAccounts = new ArrayList<>();
                JSONArray accountArray = loadedBankStatus.optJSONArray("accounts");
                if (accountArray != null) {
                    for (int i = 0; i < accountArray.length(); i++) {
                        loadedBankAccounts.add(CashAccount.fromJson(accountArray.getJSONObject(i)));
                    }
                }
                postIfActive(() -> {
                    bankStatus = loadedBankStatus;
                    accounts = loadedBankAccounts;
                    renderSettings(accountSettings, diagnostics, null);
                });
            } catch (Exception exception) {
                postIfActive(() -> {
                    if (!handleExpiredSession(exception)) {
                        renderSettings(null, null, userFacingError(exception));
                    }
                });
            }
        });
    }

    private void renderSettings(JSONObject accountSettings, AppDiagnostics diagnostics, String errorMessage) {
        beginScreen("Accounts / Settings");
        addCelebrationSetting();
        if (errorMessage != null && !errorMessage.trim().isEmpty()) {
            addWarning("Could not load diagnostics: " + errorMessage);
        }
        addSection("Backend connection");
        EditText baseUrlInput = new EditText(this);
        baseUrlInput.setHint("Backend URL");
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
        addFact("Bank mode", bankStatus.optString("mode", "unavailable"));
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
                parsedId = ConnectionSettings.parseBudgetMonthId(budgetMonthInput.getText().toString());
                saveConnectionPreferences(baseUrlInput.getText().toString(), parsedId);
            } catch (IllegalArgumentException exception) {
                toast(exception.getMessage());
                return;
            }
            if (authToken.isEmpty()) {
                showLogin("Backend changed. Log in to load this household.");
                return;
            }
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
        addDangerButton("Change password", () -> {
            String currentPassword = currentPasswordInput.getText().toString();
            String newPassword = newPasswordInput.getText().toString();
            if (currentPassword.isEmpty() || newPassword.isEmpty()) {
                toast("Enter current and new passwords.");
                return;
            }
            if (newPassword.length() < (BuildConfig.DEBUG ? 8 : 12)) {
                toast("New password must be at least " + (BuildConfig.DEBUG ? 8 : 12) + " characters.");
                return;
            }
            runMutation(
                    "Changing password...",
                    () -> api.changePassword(currentPassword, newPassword),
                    () -> {
                        clearSession();
                        showLogin("Password changed. Log in again with your new password.");
                    }
            );
        });
        addDangerButton("Log out", this::logout);

        addSection("USAA bank connection");
        if (BuildConfig.BANK_LINKING_ENABLED && bankStatus.optBoolean("enabled")) {
            addButton(bankStatus.optBoolean("connected") ? "Reconnect USAA" : "Connect USAA with Plaid", this::preparePlaidLink);
            addButton("Sync bank data", () -> syncPlaidItems("all"));
            addFact("Balances checked (UTC)", bankStatus.optString("balance_checked_at", "Not checked"));
            addFact("Transactions downloaded (UTC)", bankStatus.optString("transactions_checked_at", "Not downloaded"));
            addFact("Bank transaction update", bankStatus.optString("transactions_updated_at", "Unavailable"));
            addFact("History complete", bankStatus.optBoolean("history_complete") ? "Yes" : "Waiting for bank history");
            addBody("Refresh household data reads saved data. Sync bank data checks Plaid. Transactions can lag behind USAA.");
            JSONArray issues = bankStatus.optJSONArray("issues");
            if (issues != null) for (int i=0; i<issues.length(); i++) addWarning(issues.optString(i));
            addBody("Before confirming, compare each included account's available and current balances and recent posted/pending transactions with USAA. Review transfers, refunds, duplicate manual entries, and bills already paid. Bank data does not automatically mark bills paid or record income in your plan.");
            if (bankStatus.optBoolean("can_reconcile")) {
                addButton("I compared USAA and confirmed this month's data", () -> runMutation(
                        "Saving bank reconciliation...",
                        () -> api.reconcileBank(budgetMonthId, bankStatus.optString("revision")),
                        () -> refreshData(this::showSettings)));
            }
            addFact("Reconciled this month", bankStatus.optBoolean("reconciled") ? "Yes" : "No");
        } else {
            addBody("Bank linking is not enabled on this backend.");
        }

        addSection("Account inclusion");
        if (accounts.isEmpty()) {
            addBody("No checking or savings accounts connected yet.");
        } else {
            for (CashAccount account : accounts) {
                addBody(account.name
                        + " | " + account.accountType
                        + " | " + MoneyFormatter.dollars(account.balanceCents)
                        + " | mask " + blankAsDash(account.mask)
                        + " | " + (account.includedInCashReality ? "included" : "excluded"));
                addFact("Available", account.availableBalanceCents == null ? "Unavailable" : MoneyFormatter.dollars(account.availableBalanceCents));
                addFact("Current", account.currentBalanceCents == null ? "Unavailable" : MoneyFormatter.dollars(account.currentBalanceCents));
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
        repairingBank = bankStatus.optBoolean("connected");
        showLoading("Preparing USAA connection...");
        executor.execute(() -> {
            try {
                String linkToken = api.createPlaidLinkToken();
                if (linkToken == null || linkToken.trim().isEmpty()) {
                    throw new IllegalStateException("Backend did not return a Plaid link token.");
                }
                postIfActive(() -> openPlaidLink(linkToken));
            } catch (Exception exception) {
                postIfActive(() -> showError("Could not start Plaid Link", exception));
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
                postIfActive(() -> refreshData(this::showSettings));
            } catch (Exception exception) {
                postIfActive(() -> showError("Plaid public token exchange failed", exception));
            }
        });
    }

    private void syncPlaidItems(String syncType) {
        Set<Integer> plaidItemIds = new LinkedHashSet<>();
        if (bankStatus.optInt("connection_id") > 0) plaidItemIds.add(bankStatus.optInt("connection_id"));
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
                    if ("all".equals(syncType)) {
                        api.syncPlaid(plaidItemId, "balance");
                        api.syncPlaid(plaidItemId, "transaction");
                    } else api.syncPlaid(plaidItemId, syncType);
                }
                postIfActive(() -> refreshData(this::showSettings));
            } catch (Exception exception) {
                postIfActive(() -> showError("Plaid sync failed", exception));
            }
        });
    }

    private void addCategoryCard(BudgetCategory category) {
        int background = category.isOverspent() ? COLOR_DANGER_BG
                : category.remainingCents == 0 ? COLOR_WARNING_BG : COLOR_SURFACE;
        int textColor = category.isOverspent() ? COLOR_DANGER_TEXT
                : category.remainingCents == 0 ? COLOR_WARNING_TEXT : COLOR_PRIMARY_DARK;
        String status = category.isOverspent()
                ? "Overspent by " + MoneyFormatter.dollars(Math.abs((long) category.remainingCents))
                : category.remainingCents == 0 ? "Fully used" : MoneyFormatter.dollars(category.remainingCents) + " left";
        LinearLayout card = cardLayout(background, COLOR_BORDER);
        card.addView(rowTitle(category.name, categoryIcon(category.name)));
        TextView remaining = displayText(status, 21, textColor, LABEL_FONT);
        remaining.setPadding(0, dp(7), 0, dp(4));
        card.addView(remaining);
        card.addView(mutedText("Spent " + MoneyFormatter.dollars(category.spentCents)
                + " of " + MoneyFormatter.dollars(category.plannedCents)));
        makeCardAction(card, category.name + ". " + status + ". Spent "
                + MoneyFormatter.dollars(category.spentCents) + " of " + MoneyFormatter.dollars(category.plannedCents)
                + ". Open category.", () -> showCategoryDetail(category.id));
        root.addView(card);
    }

    private void addTransactionButton(TransactionDetail detail) {
        String status = transactionStatusLabel(detail);
        LinearLayout card = cardLayout(detail.needsReview ? COLOR_WARNING_BG : COLOR_SURFACE, COLOR_BORDER);
        TextView name = displayText(detail.transaction.displayName(), 17, COLOR_TEXT, LABEL_FONT);
        card.addView(name);
        TextView amount = displayText(MoneyFormatter.dollars(detail.transaction.amountCents), 23,
                detail.transaction.ignored ? COLOR_MUTED : COLOR_PRIMARY_DARK, LABEL_FONT);
        amount.setPadding(0, dp(4), 0, dp(3));
        card.addView(amount);
        card.addView(mutedText(detail.transaction.occurredOn));
        TextView badge = displayText(status, 13, detail.needsReview ? COLOR_WARNING_TEXT : COLOR_MUTED, LABEL_FONT);
        badge.setPadding(dp(9), dp(4), dp(9), dp(4));
        badge.setBackground(rounded(detail.needsReview ? COLOR_GOLD_BG : COLOR_SURFACE_ALT,
                detail.needsReview ? COLOR_GOLD_BG : COLOR_SURFACE_ALT, 8));
        LinearLayout.LayoutParams badgeParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        badgeParams.topMargin = dp(7);
        card.addView(badge, badgeParams);
        makeCardAction(card, detail.transaction.displayName() + ". "
                + MoneyFormatter.dollars(detail.transaction.amountCents) + ". "
                + detail.transaction.occurredOn + ". " + status + ". Open transaction.",
                () -> showTransactionDetail(detail.transaction.id));
        root.addView(card);
    }

    private String transactionStatusLabel(TransactionDetail detail) {
        if (detail.transaction.ignored) {
            return "ignored";
        }
        if (detail.transaction.reviewed) {
            return "reviewed";
        }
        if (detail.finalCategoryId != null || detail.isSplit()) {
            return "needs final review";
        }
        return "needs category";
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
                postIfActive(onSuccess);
            } catch (Exception exception) {
                postIfActive(() -> showError("Update failed", exception));
            }
        });
    }

    private void beginScreen(String title) {
        currentScreen = title;
        View focus = getCurrentFocus();
        if (focus != null) {
            InputMethodManager keyboard = (InputMethodManager) getSystemService(INPUT_METHOD_SERVICE);
            if (keyboard != null) {
                keyboard.hideSoftInputFromWindow(focus.getWindowToken(), 0);
            }
        }
        ScrollView scrollView = new ScrollView(this);
        scrollView.setFillViewport(true);
        scrollView.setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                    insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets;
        });
        scrollView.setBackgroundColor(COLOR_BACKGROUND);
        root = new StyledLinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(18), dp(22), dp(18), dp(24));
        scrollView.addView(root);
        setContentView(scrollView);
        TextView heading = new TextView(this);
        heading.setText(title);
        heading.setTextColor(COLOR_PRIMARY_DARK);
        heading.setTextSize(29);
        heading.setTypeface(headingFont);
        heading.setGravity(Gravity.START);
        heading.setPadding(0, 0, 0, dp(4));
        root.addView(heading);
    }

    private void showLoading(String message) {
        beginScreen("Family Finance");
        ProgressBar progress = new ProgressBar(this);
        progress.setIndeterminateTintList(ColorStateList.valueOf(COLOR_PRIMARY));
        progress.setContentDescription(message);
        root.addView(progress);
        addStatusCard("One moment", message, COLOR_SURFACE_ALT, COLOR_PRIMARY_DARK);
    }

    private void showError(String context, Exception exception) {
        if (handleExpiredSession(exception)) {
            return;
        }
        beginScreen("Something needs attention");
        addStatusCard(context, userFacingError(exception), COLOR_DANGER_BG, COLOR_DANGER_TEXT);
        if (authToken == null || authToken.isEmpty()) {
            addButton("Log in", () -> showLogin(null));
        }
        addButton("Retry dashboard", () -> refreshData(this::showDashboard));
        addButton("Settings", this::showSettings);
    }

    private void addNav() {
        addSection("Your household");
        addNavRow("Dashboard", this::showDashboard, "Monthly budget", this::showBudget);
        addNavRow("Transactions", () -> showTransactions(false), "Review queue", () -> showTransactions(true));
        addNavRow("Safe to spend", this::showSafeToSpend, "Bills / paydays", this::showBillsAndPaydays);
        addNavRow("Income planning", this::showIncomePlanning, "Notifications", this::showNotifications);
        addSecondaryButton("Accounts / settings", this::showSettings);
        addSecondaryButton("Refresh household data", () -> {
            showLoading("Refreshing household data...");
            refreshData(this::showDashboard);
        });
    }

    private String navigationIcon(String label) {
        switch (label) {
            case "Dashboard": return "\uD83C\uDFE0";
            case "Monthly budget": return "\uD83D\uDCD2";
            case "Transactions": return "\u21C4";
            case "Review queue": return "\u2713";
            case "Safe to spend": return "\uD83D\uDEE1";
            case "Bills / paydays": return "\uD83D\uDCC5";
            case "Income planning": return "\uD83C\uDF31";
            default: return "\uD83D\uDD14";
        }
    }

    private void addNavRow(String firstLabel, Runnable firstAction, String secondLabel, Runnable secondAction) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        String[] labels = {firstLabel, secondLabel};
        Runnable[] actions = {firstAction, secondAction};
        for (int i = 0; i < labels.length; i++) {
            Button button = new Button(this);
            button.setText(navigationIcon(labels[i]) + "  " + labels[i]);
            button.setContentDescription(labels[i]);
            button.setAllCaps(false);
            button.setTextSize(14);
            button.setTextColor(COLOR_PRIMARY_DARK);
            button.setBackgroundTintList(null);
            button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33246449),
                    rounded(COLOR_SURFACE_ALT, COLOR_BORDER, 14), null));
            button.setStateListAnimator(null);
            button.setPadding(dp(8), dp(10), dp(8), dp(10));
            button.setTypeface(LABEL_FONT);
            button.setMinHeight(dp(52));
            Runnable action = actions[i];
            button.setOnClickListener(view -> action.run());
            LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
            params.setMargins(i == 0 ? 0 : dp(4), dp(2), i == 0 ? dp(4) : 0, dp(4));
            row.addView(button, params);
        }
        root.addView(row);
    }

    private void addMetric(String label, String value) {
        addMetricCard(label, value, null);
    }

    private void addFact(String label, String value) {
        TextView textView = new TextView(this);
        textView.setText(label + ": " + value);
        textView.setTextColor(COLOR_MUTED);
        textView.setTextSize(13);
        textView.setPadding(0, dp(2), 0, dp(8));
        root.addView(textView);
    }

    private void addSection(String label) {
        TextView textView = new TextView(this);
        textView.setText(label);
        textView.setTextColor(COLOR_TEXT);
        textView.setTextSize(20);
        textView.setTypeface(headingFont);
        textView.setPadding(0, dp(22), 0, dp(8));
        root.addView(textView);
    }

    private void addBody(String body) {
        TextView textView = new TextView(this);
        textView.setText(body);
        textView.setTextColor(COLOR_TEXT);
        textView.setTextSize(15);
        textView.setLineSpacing(dp(2), 1.0f);
        textView.setPadding(0, dp(4), 0, dp(8));
        root.addView(textView);
    }

    private void addWarning(String body) {
        addStatusCard("Heads up", body, COLOR_WARNING_BG, COLOR_WARNING_TEXT);
    }

    private void addButton(String label, Runnable action) {
        addStyledButton(label, COLOR_PRIMARY, 0xFFFFFFFF, action);
    }

    private void addSecondaryButton(String label, Runnable action) {
        addStyledButton(label, COLOR_SURFACE_ALT, COLOR_PRIMARY_DARK, action);
    }

    private void addDangerButton(String label, Runnable action) {
        boolean needsConfirmation = label.startsWith("Remove") || label.startsWith("Archive")
                || label.startsWith("Ignore");
        addStyledButton(label, COLOR_DANGER_BG, COLOR_DANGER_TEXT, needsConfirmation ? () -> {
            String message = label.startsWith("Archive")
                    ? "History will be preserved. This entry will no longer be available for new assignments."
                    : label.startsWith("Ignore")
                    ? "This transaction will stay in history and stop counting toward budget spending."
                    : "This removes the saved entry or assignment from your household plan. Budget totals will refresh.";
            new AlertDialog.Builder(this).setTitle(label + "?").setMessage(message)
                    .setNegativeButton("Cancel", null)
                    .setPositiveButton("Confirm", (dialog, which) -> action.run()).show();
        } : action);
    }

    private void addStyledButton(String label, int backgroundColor, int textColor, Runnable action) {
        Button button = new Button(this);
        button.setAllCaps(false);
        button.setText(label);
        button.setTextColor(textColor);
        button.setTextSize(15);
        button.setTypeface(LABEL_FONT);
        button.setGravity(Gravity.CENTER);
        button.setPadding(dp(14), dp(10), dp(14), dp(10));
        button.setMinHeight(dp(52));
        button.setBackgroundTintList(null);
        button.setBackground(new RippleDrawable(ColorStateList.valueOf(0x33246449),
                rounded(backgroundColor, backgroundColor, 14), null));
        button.setStateListAnimator(null);
        button.setOnClickListener(view -> action.run());
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, dp(4), 0, dp(8));
        button.setLayoutParams(params);
        root.addView(button);
    }

    private void addCheckInStreakCard(CheckInStreak streak, LocalDate today) {
        LinearLayout card = cardLayout(COLOR_PRIMARY_DARK, COLOR_PRIMARY_DARK);
        LinearLayout top = new LinearLayout(this);
        top.setGravity(Gravity.CENTER_VERTICAL);
        LinearLayout words = new LinearLayout(this);
        words.setOrientation(LinearLayout.VERTICAL);
        TextView label = smallLabel("A little check-in. A stronger habit.");
        label.setTextColor(0xFFDAEADC);
        label.setAllCaps(false);
        words.addView(label);
        TextView current = displayText("\uD83D\uDD25 " + streak.days + "-day streak", 28, 0xFFFFF5DF, headingFont);
        current.setContentDescription("Budget check-in streak: " + streak.days + (streak.days == 1 ? " day" : " days"));
        current.setPadding(0, dp(4), 0, dp(6));
        words.addView(current);
        top.addView(words, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        // At large font sizes give the words the full width; the art is decorative.
        if (getResources().getConfiguration().fontScale <= 1.3f) {
            top.addView(new HouseholdIllustrationView(this, false), new LinearLayout.LayoutParams(dp(76), dp(82)));
        }
        card.addView(top);
        TextView best = displayText("\uD83C\uDFC6 Personal best: " + streak.bestDays
                + (streak.bestDays == 1 ? " day" : " days"), 14, COLOR_GOLD_TEXT, LABEL_FONT);
        best.setContentDescription("Personal best: " + streak.bestDays + (streak.bestDays == 1 ? " day" : " days"));
        best.setPadding(dp(10), dp(7), dp(10), dp(7));
        best.setBackground(rounded(COLOR_GOLD_BG, COLOR_GOLD_BG, 10));
        card.addView(best, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT));
        TextView encouragement = mutedText(EncouragementMessages.forDate(today));
        encouragement.setTextColor(0xFFEBF3E9);
        encouragement.setTextSize(15);
        encouragement.setPadding(0, dp(12), 0, 0);
        card.addView(encouragement);
        root.addView(card);
    }

    private void addAllCaughtUpCard(Runnable action) {
        LinearLayout card = cardLayout(COLOR_GOLD_BG, 0xFFE0C890);
        card.addView(new HouseholdIllustrationView(this, true),
                new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(82)));
        TextView title = displayText("All caught up!", 25, COLOR_PRIMARY_DARK, headingFont);
        title.setGravity(Gravity.CENTER);
        card.addView(title);
        TextView body = mutedText("No transactions waiting for review. Enjoy that clear-queue feeling.");
        body.setTextColor(COLOR_GOLD_TEXT);
        body.setGravity(Gravity.CENTER);
        body.setPadding(0, dp(6), 0, 0);
        card.addView(body);
        if (action != null) makeCardAction(card,
                "Transaction review. All caught up. No transactions waiting for review. Open transaction review.", action);
        root.addView(card);
    }

    private TextView displayText(String value, int size, int color, Typeface font) {
        TextView text = new TextView(this);
        text.setText(value);
        text.setTextSize(size);
        text.setTextColor(color);
        text.setTypeface(font);
        return text;
    }

    private String categoryIcon(String name) {
        String text = name.toLowerCase(java.util.Locale.ROOT);
        if (text.matches(".*(eating|dining|restaurant).*")) return "\uD83C\uDF7D\uFE0F";
        if (text.matches(".*(food|grocer).*")) return "\uD83D\uDED2";
        if (text.matches(".*(transport|gas|fuel|auto|car ).*")) return "\uD83D\uDE97";
        if (text.matches(".*(home|hous|rent|mortgage|utilit).*")) return "\uD83C\uDFE0";
        if (text.matches(".*(saving|emergency).*")) return "\uD83C\uDF31";
        if (text.matches(".*(giving|gift|charit|donat).*")) return "\uD83C\uDF81";
        if (text.matches(".*(child|school|educat).*")) return "\uD83D\uDCDA";
        if (text.matches(".*(health|medical|insur).*")) return "\uD83D\uDEE1";
        if (text.matches(".*(fun|music|entertain).*")) return "\uD83C\uDFB5";
        return "\uD83D\uDD16";
    }

    private LinearLayout rowTitle(String label, String icon) {
        LinearLayout row = new LinearLayout(this);
        row.setGravity(Gravity.CENTER_VERTICAL);
        TextView graphic = displayText(icon, 20, COLOR_PRIMARY_DARK, Typeface.DEFAULT);
        graphic.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO);
        graphic.setGravity(Gravity.CENTER);
        graphic.setBackground(rounded(COLOR_SURFACE_ALT, COLOR_SURFACE_ALT, 12));
        row.addView(graphic, new LinearLayout.LayoutParams(dp(40), dp(40)));
        TextView text = displayText(label, 17, COLOR_TEXT, LABEL_FONT);
        text.setPadding(dp(10), 0, 0, 0);
        row.addView(text, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1));
        return row;
    }

    private void addIconSection(String label, String icon) {
        LinearLayout row = rowTitle(label, icon);
        row.setPadding(0, dp(18), 0, dp(8));
        root.addView(row);
    }

    private void makeCardAction(LinearLayout card, String description, Runnable action) {
        card.setOnClickListener(view -> action.run());
        card.setFocusable(true);
        card.setForeground(new RippleDrawable(ColorStateList.valueOf(0x24236B4E),
                null, rounded(0xFFFFFFFF, 0xFFFFFFFF, 18)));
        card.setContentDescription(description);
        card.setAccessibilityDelegate(new View.AccessibilityDelegate() {
            @Override
            public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                super.onInitializeAccessibilityNodeInfo(host, info);
                info.setClassName(Button.class.getName());
            }
        });
        for (int i = 0; i < card.getChildCount(); i++) {
            card.getChildAt(i).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
        }
    }

    private LinearLayout addMetricCard(String label, String value, String detail) {
        LinearLayout card = cardLayout(COLOR_SURFACE, COLOR_BORDER);
        TextView labelView = smallLabel(label);
        card.addView(labelView);
        TextView valueView = new TextView(this);
        valueView.setText(value);
        valueView.setTextColor(COLOR_TEXT);
        valueView.setTextSize(22);
        valueView.setTypeface(LABEL_FONT);
        valueView.setPadding(0, dp(2), 0, detail == null ? 0 : dp(4));
        card.addView(valueView);
        if (detail != null && !detail.trim().isEmpty()) {
            TextView detailView = mutedText(detail);
            card.addView(detailView);
        }
        root.addView(card);
        return card;
    }

    private void addHeroCard(String label, String value, String detail) {
        addHeroCard(label, value, detail, COLOR_SURFACE_ALT, COLOR_PRIMARY_DARK);
    }

    private void addHeroCard(String label, String value, String detail, int backgroundColor, int textColor) {
        LinearLayout card = cardLayout(backgroundColor,
                backgroundColor == COLOR_SURFACE_ALT ? 0xFFBFD5C8 : backgroundColor);
        TextView labelView = smallLabel(label);
        labelView.setTextColor(textColor);
        card.addView(labelView);
        TextView valueView = new TextView(this);
        valueView.setText(value);
        valueView.setTextColor(textColor);
        valueView.setTextSize(34);
        valueView.setTypeface(LABEL_FONT);
        valueView.setPadding(0, dp(2), 0, dp(8));
        card.addView(valueView);
        if (detail != null && !detail.trim().isEmpty()) {
            TextView detailView = mutedText(detail);
            card.addView(detailView);
        }
        root.addView(card);
    }

    private void addStatusCard(String title, String body, int backgroundColor, int textColor) {
        LinearLayout card = cardLayout(backgroundColor, backgroundColor);
        TextView titleView = new TextView(this);
        titleView.setText(title);
        titleView.setTextColor(textColor);
        titleView.setTextSize(16);
        titleView.setTypeface(headingFont);
        card.addView(titleView);
        TextView bodyView = new TextView(this);
        bodyView.setText(body);
        bodyView.setTextColor(textColor);
        bodyView.setTextSize(15);
        bodyView.setLineSpacing(dp(2), 1.0f);
        bodyView.setPadding(0, dp(4), 0, 0);
        card.addView(bodyView);
        root.addView(card);
    }

    private void addProgressCard(String title, String value, int progressPercent, String detail) {
        addProgressCard(title, value, progressPercent, detail, null);
    }

    private void addProgressCard(String title, String value, int progressPercent, String detail, Runnable action) {
        LinearLayout card = cardLayout(COLOR_SURFACE, COLOR_BORDER);
        TextView titleView = smallLabel(action == null ? title : title + "  \u203A");
        card.addView(titleView);
        TextView valueView = new TextView(this);
        valueView.setText(value);
        valueView.setTextColor(COLOR_TEXT);
        valueView.setTextSize(20);
        valueView.setTypeface(LABEL_FONT);
        valueView.setPadding(0, dp(2), 0, dp(8));
        card.addView(valueView);
        ProgressBar progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        progressBar.setMax(100);
        progressBar.setProgress(Math.max(0, Math.min(100, progressPercent)));
        progressBar.setProgressTintList(ColorStateList.valueOf(COLOR_PRIMARY));
        progressBar.setProgressBackgroundTintList(ColorStateList.valueOf(0xFFE1E8E3));
        LinearLayout.LayoutParams progressParams = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                dp(10)
        );
        progressParams.setMargins(0, 0, 0, dp(8));
        progressBar.setLayoutParams(progressParams);
        card.addView(progressBar);
        if (detail != null && !detail.trim().isEmpty()) {
            card.addView(mutedText(detail));
        }
        if (action != null) {
            card.setOnClickListener(view -> action.run());
            card.setFocusable(true);
            card.setForeground(new RippleDrawable(ColorStateList.valueOf(0x24236B4E),
                    null, rounded(0xFFFFFFFF, 0xFFFFFFFF, 14)));
            card.setContentDescription(title + ". " + value + ". "
                    + (detail == null ? "" : detail + " ") + "Open transaction review.");
            card.setAccessibilityDelegate(new View.AccessibilityDelegate() {
                @Override
                public void onInitializeAccessibilityNodeInfo(View host, AccessibilityNodeInfo info) {
                    super.onInitializeAccessibilityNodeInfo(host, info);
                    info.setClassName(Button.class.getName());
                }
            });
            for (int i = 0; i < card.getChildCount(); i++) {
                card.getChildAt(i).setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);
            }
        }
        root.addView(card);
    }

    private LinearLayout cardLayout(int backgroundColor, int strokeColor) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.VERTICAL);
        card.setPadding(dp(16), dp(14), dp(16), dp(14));
        card.setBackground(rounded(backgroundColor, strokeColor, 18));
        LinearLayout.LayoutParams params = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.WRAP_CONTENT
        );
        params.setMargins(0, dp(6), 0, dp(10));
        card.setLayoutParams(params);
        return card;
    }

    private TextView smallLabel(String label) {
        TextView textView = new TextView(this);
        textView.setText(label);
        textView.setTextColor(COLOR_MUTED);
        textView.setTextSize(12);
        textView.setTypeface(LABEL_FONT);
        textView.setLetterSpacing(0.03f);
        textView.setAllCaps(false);
        return textView;
    }

    private TextView mutedText(String body) {
        TextView textView = new TextView(this);
        textView.setText(body);
        textView.setTextColor(COLOR_MUTED);
        textView.setTextSize(14);
        textView.setLineSpacing(dp(2), 1.0f);
        return textView;
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
        List<BudgetCategory> available = BudgetScreenState.sortedCategoryChoices(summary == null ? null : summary.categories);
        spinner.setTag(available);
        spinner.setContentDescription("Budget category");
        ArrayList<String> labels = new ArrayList<>();
        labels.add("Choose a category...");
        for (BudgetCategory category : available) {
            labels.add(category.name + " (" + MoneyFormatter.dollars(category.remainingCents) + " left)");
        }
        ArrayAdapter<String> adapter = new ArrayAdapter<>(this, android.R.layout.simple_spinner_item, labels);
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item);
        spinner.setAdapter(adapter);
        spinner.setSelection(0);
        return spinner;
    }

    private BudgetCategory selectedCategory(Spinner spinner) {
        return BudgetScreenState.categoryChoice(spinnerCategories(spinner), spinner.getSelectedItemPosition());
    }

    @SuppressWarnings("unchecked")
    private List<BudgetCategory> spinnerCategories(Spinner spinner) {
        return (List<BudgetCategory>) spinner.getTag();
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

    private boolean handleExpiredSession(Exception exception) {
        if (exception instanceof ApiException && ((ApiException) exception).status == 401) {
            clearSession();
            showLogin("Your session expired. Log in again to load your household data.");
            return true;
        }
        return false;
    }

    private void setSpinnerToCategory(Spinner spinner, int categoryId) {
        List<BudgetCategory> choices = spinnerCategories(spinner);
        for (int i = 0; i < choices.size(); i++) {
            if (choices.get(i).id == categoryId) {
                spinner.setSelection(i + 1);
                return;
            }
        }
        spinner.setSelection(0);
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

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable rounded(int backgroundColor, int strokeColor, int radiusDp) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(backgroundColor);
        drawable.setCornerRadius(dp(radiusDp));
        drawable.setStroke(dp(1), strokeColor);
        return drawable;
    }

    private int recordDailyStreak(String lastDateKey, String streakKey) {
        String scope = baseUrl + ":" + householdId + ":" + currentUserId + ":";
        lastDateKey = scope + lastDateKey;
        streakKey = scope + streakKey;
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String today = LocalDate.now().toString();
        String lastDate = prefs.getString(lastDateKey, "");
        int currentStreak = prefs.getInt(streakKey, 0);
        if (today.equals(lastDate)) {
            return currentStreak;
        }
        int nextStreak;
        try {
            LocalDate last = LocalDate.parse(lastDate);
            nextStreak = last.plusDays(1).equals(LocalDate.parse(today)) ? currentStreak + 1 : 1;
        } catch (Exception exception) {
            nextStreak = 1;
        }
        prefs.edit()
                .putString(lastDateKey, today)
                .putInt(streakKey, nextStreak)
                .apply();
        return nextStreak;
    }

    private CheckInStreak recordBudgetCheckInStreak(LocalDate today) {
        // Keep the existing scope and keys so an app update preserves each person's streak.
        String scope = baseUrl + ":" + householdId + ":" + currentUserId + ":";
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String previousDate = prefs.getString(scope + PREF_LAST_BUDGET_CHECK_DATE, "");
        int previousDays = prefs.getInt(scope + PREF_BUDGET_CHECK_STREAK, 0);
        int previousBest = prefs.getInt(scope + PREF_BEST_BUDGET_CHECK_STREAK, 0);
        CheckInStreak streak = CheckInStreak.record(today, previousDate, previousDays, previousBest);
        prefs.edit()
                .putString(scope + PREF_LAST_BUDGET_CHECK_DATE, today.toString())
                .putInt(scope + PREF_BUDGET_CHECK_STREAK, streak.days)
                .putInt(scope + PREF_BEST_BUDGET_CHECK_STREAK, streak.bestDays)
                .apply();
        String achievement = CelebrationPolicy.streakMessage(today, previousDate, previousDays, previousBest, streak);
        if (achievement != null) {
            LinearLayout achievementScreen = root;
            achievementScreen.post(() -> {
                if (!destroyed && root == achievementScreen) celebrate(achievement, true);
            });
        }
        return streak;
    }

    private String celebrationPreferenceKey() {
        return baseUrl + ":" + householdId + ":" + currentUserId + ":" + PREF_CELEBRATIONS;
    }

    private void celebrate(String message, boolean milestone) {
        toast(message);
        if (getSharedPreferences(PREFS, MODE_PRIVATE).getBoolean(celebrationPreferenceKey(), true)) {
            CelebrationOverlay.show(this, milestone);
        }
    }

    private void showReviewReward(CelebrationPolicy.Reward reward, String savedMessage) {
        if (reward == CelebrationPolicy.Reward.QUEUE_CLEARED) {
            celebrate("All caught up! Every waiting transaction is reviewed.", true);
        } else if (reward == CelebrationPolicy.Reward.SMALL) {
            celebrate(savedMessage, false);
        }
    }

    private void addCelebrationSetting() {
        addSection("Make it yours");
        CheckBox animations = new CheckBox(this);
        animations.setText("Celebrate my progress");
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        String key = celebrationPreferenceKey();
        animations.setChecked(prefs.getBoolean(key, true));
        animations.setOnCheckedChangeListener((button, enabled) -> prefs.edit().putBoolean(key, enabled).apply());
        root.addView(animations);
        addBody("Checkmarks, sparkles, and fireworks for your wins. Turn off for quiet celebrations. "
                + "Also follows your phone's animation setting. Saved for you on this device.");
    }

    private int recordReviewClearStreakIfCleared() {
        if (!reviewQueue.isEmpty()) {
            return 0;
        }
        return recordDailyStreak(PREF_LAST_REVIEW_CLEAR_DATE, PREF_REVIEW_CLEAR_STREAK);
    }

    private int reviewProgressPercent() {
        if (transactions.isEmpty()) {
            return reviewQueue.isEmpty() ? 100 : 0;
        }
        int reviewedOrCategorized = Math.max(0, transactions.size() - reviewQueue.size());
        return Math.round((reviewedOrCategorized * 100f) / Math.max(1, transactions.size()));
    }

    private String reviewProgressValue() {
        if (transactions.isEmpty()) {
            return reviewQueue.isEmpty() ? "Nothing waiting" : reviewQueue.size() + " to review";
        }
        int reviewedOrCategorized = Math.max(0, transactions.size() - reviewQueue.size());
        return reviewedOrCategorized + " of " + transactions.size() + " handled";
    }

    private String reviewProgressDetail() {
        if (reviewQueue.isEmpty()) {
            return "Everything waiting for review is handled. Nicely done!";
        }
        return reviewQueue.size() + " quick decision" + (reviewQueue.size() == 1 ? "" : "s")
                + " left before the queue is clear.";
    }

    private void toast(String message) {
        Toast.makeText(this, message, Toast.LENGTH_SHORT).show();
    }

    private final class StyledLinearLayout extends LinearLayout {
        private StyledLinearLayout(Activity context) {
            super(context);
        }

        @Override
        public void addView(View child) {
            styleLooseChild(child);
            super.addView(child);
        }

        @Override
        public void addView(View child, int index) {
            styleLooseChild(child);
            super.addView(child, index);
        }

        @Override
        public void addView(View child, ViewGroup.LayoutParams params) {
            styleLooseChild(child);
            super.addView(child, params);
        }
    }

    private void styleLooseChild(View child) {
        if (child instanceof EditText) {
            EditText editText = (EditText) child;
            if (editText.getId() == View.NO_ID && editText.getHint() != null) {
                editText.setId(View.generateViewId());
                TextView label = smallLabel(editText.getHint().toString());
                label.setLabelFor(editText.getId());
                label.setPadding(0, dp(8), 0, dp(2));
                root.addView(label);
            }
            editText.setTextColor(COLOR_TEXT);
            editText.setHintTextColor(COLOR_MUTED);
            editText.setTextSize(15);
            editText.setPadding(dp(14), 0, dp(14), 0);
            editText.setMinHeight(dp(54));
            editText.setBackground(rounded(COLOR_SURFACE, COLOR_BORDER, 12));
            ensureBlockMargins(editText, dp(4), dp(8));
            return;
        }
        if (child instanceof Spinner) {
            child.setBackground(rounded(COLOR_SURFACE, COLOR_BORDER, 12));
            child.setPadding(dp(10), 0, dp(10), 0);
            child.setMinimumHeight(dp(54));
            ensureBlockMargins(child, dp(4), dp(8));
            return;
        }
        if (child instanceof CheckBox) {
            CheckBox checkBox = (CheckBox) child;
            checkBox.setTextColor(COLOR_TEXT);
            checkBox.setTextSize(15);
            checkBox.setButtonTintList(ColorStateList.valueOf(COLOR_PRIMARY));
            ensureBlockMargins(checkBox, dp(4), dp(8));
        }
    }

    private void ensureBlockMargins(View view, int top, int bottom) {
        ViewGroup.LayoutParams rawParams = view.getLayoutParams();
        LinearLayout.LayoutParams params;
        if (rawParams instanceof LinearLayout.LayoutParams) {
            params = (LinearLayout.LayoutParams) rawParams;
        } else {
            params = new LinearLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.WRAP_CONTENT
            );
        }
        params.setMargins(params.leftMargin, top, params.rightMargin, bottom);
        view.setLayoutParams(params);
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
