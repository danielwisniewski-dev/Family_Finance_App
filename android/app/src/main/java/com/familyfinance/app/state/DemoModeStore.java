package com.familyfinance.app.state;

import android.content.Context;
import android.content.SharedPreferences;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;

/** Owns only disposable demo state. Real preferences and encrypted credentials are never edited. */
public final class DemoModeStore {
    private final Context context;
    private final SharedPreferences mode;

    public DemoModeStore(Context context) {
        this.context = context;
        mode = context.getSharedPreferences("demo_mode", Context.MODE_PRIVATE);
    }

    public boolean isEnabled() { return mode.getBoolean("enabled", false); }
    public SharedPreferences preferences() { return preferencesFor(scope()); }
    private SharedPreferences preferencesFor(String scope) {
        return context.getSharedPreferences("family_finance_" + scope, Context.MODE_PRIVATE);
    }
    public String scope() { return mode.getString("scope", "demo"); }
    public SecureSessionStore session() { return new SecureSessionStore(context, scope()); }

    public boolean enter(JSONObject response, String origin) {
        JSONObject user = response.optJSONObject("user");
        JSONObject household = response.optJSONObject("household");
        String token = response.optString("token");
        if (!response.optBoolean("demo") || token.isEmpty() || user == null || household == null
                || user.optInt("id") <= 0 || household.optInt("id") <= 0 || response.optInt("budget_month_id") <= 0) return false;
        String scope = "demo_" + UUID.randomUUID().toString();
        SecureSessionStore encrypted = new SecureSessionStore(context, scope);
        if (!encrypted.save(token, origin)) return false;
        if (!preferencesFor(scope).edit().clear().putString("base_url", origin)
                .putInt("budget_month_id", response.optInt("budget_month_id"))
                .putInt("current_user_id", user.optInt("id")).putString("current_user_name", user.optString("name"))
                .putInt("household_id", household.optInt("id")).putString("household_name", household.optString("name"))
                .commit()) { encrypted.clear(); return false; }
        if (!mode.edit().putBoolean("enabled", true).putString("scope", scope).commit()) {
            encrypted.clear(); return false;
        }
        return true;
    }

    /** Queue encrypted credentials for best-effort revocation, then stop using this session immediately. */
    public void leave() {
        if (!isEnabled()) return;
        SharedPreferences abandoned = preferences();
        String origin = abandoned.getString("base_url", "");
        Set<String> pending = new HashSet<>(mode.getStringSet("cleanup", new HashSet<>()));
        pending.add(scope());
        mode.edit().putStringSet("cleanup", pending).putString("cleanup_origin_" + scope(), origin)
                .putBoolean("enabled", false).remove("scope").commit();
        abandoned.edit().clear().commit();
    }

    public List<Cleanup> pendingCleanup() {
        List<Cleanup> result = new ArrayList<>();
        for (String scope : mode.getStringSet("cleanup", new HashSet<>())) {
            String origin = mode.getString("cleanup_origin_" + scope, "");
            result.add(new Cleanup(scope, origin, new SecureSessionStore(context, scope).load(origin)));
        }
        return result;
    }

    public synchronized void cleanupFinished(String scope) {
        new SecureSessionStore(context, scope).clear();
        preferencesFor(scope).edit().clear().commit();
        Set<String> pending = new HashSet<>(mode.getStringSet("cleanup", new HashSet<>()));
        pending.remove(scope);
        mode.edit().putStringSet("cleanup", pending).remove("cleanup_origin_" + scope).commit();
    }

    public static final class Cleanup {
        public final String scope, origin, token;
        Cleanup(String scope, String origin, String token) { this.scope = scope; this.origin = origin; this.token = token; }
    }
}
