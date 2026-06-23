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
    username TEXT,
    email TEXT,
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'spouse',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TEXT
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

CREATE TABLE IF NOT EXISTS plaid_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    plaid_item_id TEXT NOT NULL UNIQUE,
    access_token_ref TEXT NOT NULL,
    institution_id TEXT,
    institution_name TEXT,
    sync_cursor TEXT,
    status TEXT NOT NULL DEFAULT 'connected' CHECK (status IN ('connected', 'error', 'disconnected')),
    last_error_code TEXT,
    last_error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cash_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_month_id INTEGER NOT NULL REFERENCES budget_months(id) ON DELETE CASCADE,
    plaid_item_id INTEGER REFERENCES plaid_items(id) ON DELETE SET NULL,
    plaid_account_id TEXT,
    name TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('checking', 'savings')),
    subtype TEXT,
    mask TEXT,
    official_name TEXT,
    balance_cents INTEGER NOT NULL DEFAULT 0,
    available_balance_cents INTEGER,
    current_balance_cents INTEGER,
    included_in_cash_reality INTEGER NOT NULL DEFAULT 1,
    last_balance_synced_at TEXT,
    UNIQUE(plaid_item_id, plaid_account_id)
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

CREATE TABLE IF NOT EXISTS account_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cash_account_id INTEGER NOT NULL REFERENCES cash_accounts(id) ON DELETE CASCADE,
    plaid_transaction_id TEXT,
    amount_cents INTEGER NOT NULL,
    occurred_on TEXT NOT NULL,
    name TEXT NOT NULL,
    merchant_name TEXT,
    pending INTEGER NOT NULL DEFAULT 0,
    category_hint TEXT,
    reviewed INTEGER NOT NULL DEFAULT 0,
    ignored INTEGER NOT NULL DEFAULT 0,
    ignored_reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS merchant_category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    budget_category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    merchant_match_text TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(household_id, merchant_match_text, budget_category_id)
);

CREATE TABLE IF NOT EXISTS transaction_category_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES account_transactions(id) ON DELETE CASCADE,
    budget_category_id INTEGER NOT NULL REFERENCES budget_categories(id) ON DELETE CASCADE,
    amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
    source TEXT NOT NULL CHECK (source IN ('manual', 'rule', 'plaid_hint', 'split')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    superseded_at TEXT
);

CREATE TABLE IF NOT EXISTS transaction_categorization_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES account_transactions(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT,
    budget_category_id INTEGER REFERENCES budget_categories(id) ON DELETE SET NULL,
    amount_cents INTEGER,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    household_id INTEGER NOT NULL REFERENCES households(id) ON DELETE CASCADE,
    budget_month_id INTEGER REFERENCES budget_months(id) ON DELETE SET NULL,
    event_type TEXT NOT NULL,
    actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    affected_entity_type TEXT NOT NULL,
    affected_entity_id INTEGER,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'caution', 'important')),
    metadata TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_event_reads (
    event_id INTEGER NOT NULL REFERENCES notification_events(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    read_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(event_id, user_id)
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

CREATE TABLE IF NOT EXISTS plaid_sync_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plaid_item_id INTEGER NOT NULL REFERENCES plaid_items(id) ON DELETE CASCADE,
    sync_type TEXT NOT NULL CHECK (sync_type IN ('balance', 'transaction', 'connection')),
    error_code TEXT,
    error_message TEXT NOT NULL,
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_plaid_items_household ON plaid_items(household_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username
    ON users(username)
    WHERE username IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email
    ON users(email)
    WHERE email IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_budget_categories_group ON budget_categories(budget_group_id);
CREATE INDEX IF NOT EXISTS idx_cash_accounts_budget_month ON cash_accounts(budget_month_id);
CREATE INDEX IF NOT EXISTS idx_cash_accounts_plaid_item ON cash_accounts(plaid_item_id);
CREATE INDEX IF NOT EXISTS idx_manual_spending_category ON manual_spending(budget_category_id);
CREATE INDEX IF NOT EXISTS idx_account_transactions_account ON account_transactions(cash_account_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_account_transactions_plaid_transaction
    ON account_transactions(plaid_transaction_id)
    WHERE plaid_transaction_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_merchant_rules_household ON merchant_category_rules(household_id, active, priority, id);
CREATE INDEX IF NOT EXISTS idx_transaction_assignments_transaction
    ON transaction_category_assignments(transaction_id, active);
CREATE INDEX IF NOT EXISTS idx_transaction_assignments_category
    ON transaction_category_assignments(budget_category_id, active);
CREATE INDEX IF NOT EXISTS idx_transaction_events_transaction
    ON transaction_categorization_events(transaction_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_notification_events_household
    ON notification_events(household_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_notification_events_budget_month
    ON notification_events(budget_month_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_notification_event_reads_user
    ON notification_event_reads(user_id, read_at);
CREATE INDEX IF NOT EXISTS idx_expected_bills_budget_month ON expected_bills(budget_month_id);
CREATE INDEX IF NOT EXISTS idx_paydays_household_date ON paydays(household_id, payday_date);
CREATE INDEX IF NOT EXISTS idx_plaid_sync_errors_item ON plaid_sync_errors(plaid_item_id);
