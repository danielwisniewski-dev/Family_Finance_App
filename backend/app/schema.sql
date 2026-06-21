PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS households (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT,
    role TEXT NOT NULL DEFAULT 'spouse',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS budget_months (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    included_account_balance_cents INTEGER NOT NULL DEFAULT 0,
    low_cushion_daily_cents INTEGER NOT NULL DEFAULT 5000,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(household_id, month)
);

CREATE TABLE IF NOT EXISTS cash_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month_id INTEGER NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('checking', 'savings')),
    balance_cents INTEGER NOT NULL DEFAULT 0,
    included_in_cash_reality INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS income_plan (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month_id INTEGER NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('main', 'sporadic')),
    planned_cents INTEGER NOT NULL DEFAULT 0,
    received_cents INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS budget_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month_id INTEGER NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS budget_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_group_id INTEGER NOT NULL REFERENCES budget_groups(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    planned_cents INTEGER NOT NULL DEFAULT 0,
    archived INTEGER NOT NULL DEFAULT 0,
    display_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS manual_spending (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL,
    occurred_on TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS expected_bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month_id INTEGER NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    due_on TEXT NOT NULL,
    paid INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS paydays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    payday_date TEXT NOT NULL,
    UNIQUE(household_id, payday_date)
);

CREATE INDEX IF NOT EXISTS idx_budget_categories_group ON budget_categories(budget_group_id);
CREATE INDEX IF NOT EXISTS idx_cash_accounts_budget_month ON cash_accounts(budget_month_id);
CREATE INDEX IF NOT EXISTS idx_manual_spending_category ON manual_spending(budget_category_id);
CREATE INDEX IF NOT EXISTS idx_expected_bills_budget_month ON expected_bills(budget_month_id);
CREATE INDEX IF NOT EXISTS idx_paydays_household_date ON paydays(household_id, payday_date);
