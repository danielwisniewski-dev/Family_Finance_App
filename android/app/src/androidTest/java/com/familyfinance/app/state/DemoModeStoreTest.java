package com.familyfinance.app.state;

import android.content.Context;
import android.content.SharedPreferences;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public final class DemoModeStoreTest {
    private Context context() { return InstrumentationRegistry.getInstrumentation().getTargetContext(); }

    private JSONObject started(String token) throws Exception {
        return new JSONObject().put("demo", true).put("token", token).put("budget_month_id", 42)
                .put("user", new JSONObject().put("id", 7).put("name", "Fictional Alex"))
                .put("household", new JSONObject().put("id", 3).put("name", "Sample household"));
    }

    @Test
    public void coldLaunchAndExitPreserveRealCredentialsAndNeverReuseDemoEdits() throws Exception {
        Context context = context();
        context.getSharedPreferences("demo_mode", 0).edit().clear().commit();
        SharedPreferences real = context.getSharedPreferences("family_finance", 0);
        real.edit().putInt("budget_month_id", 99).putString("pending_fund_action:real", "unconfirmed").commit();
        SecureSessionStore realSession = new SecureSessionStore(context);
        assertTrue(realSession.save("synthetic-real", "https://household.example"));
        DemoModeStore demo = new DemoModeStore(context);
        assertTrue(demo.enter(started("synthetic-demo-one"), "https://household.example"));
        String abandonedScope = demo.scope();
        demo.preferences().edit().putInt("budget_month_id", 77).putString("pending_fund_action:demo", "unconfirmed").commit();
        DemoModeStore reopened = new DemoModeStore(context);
        assertTrue(reopened.isEnabled());
        assertEquals(77, reopened.preferences().getInt("budget_month_id", 0));
        assertEquals("synthetic-demo-one", reopened.session().load("https://household.example"));
        reopened.leave(); // Works without any network call.
        assertFalse(reopened.isEnabled());
        assertTrue(reopened.preferences().getAll().isEmpty());
        assertEquals("synthetic-real", realSession.load("https://household.example"));
        assertEquals(99, real.getInt("budget_month_id", 0));
        assertEquals("unconfirmed", real.getString("pending_fund_action:real", ""));
        assertEquals(1, reopened.pendingCleanup().size());
        assertEquals("synthetic-demo-one", reopened.pendingCleanup().get(0).token);
        assertTrue(reopened.enter(started("synthetic-demo-two"), "https://household.example"));
        assertNotEquals(abandonedScope, reopened.scope());
        assertEquals(42, reopened.preferences().getInt("budget_month_id", 0));
        assertFalse(reopened.preferences().contains("pending_fund_action:demo"));
        reopened.cleanupFinished(abandonedScope);
        assertEquals("synthetic-demo-two", reopened.session().load("https://household.example"));
        assertEquals("synthetic-real", realSession.load("https://household.example"));
        reopened.leave();
        for (DemoModeStore.Cleanup pending : reopened.pendingCleanup()) reopened.cleanupFinished(pending.scope);
        realSession.clear();
        real.edit().remove("pending_fund_action:real").commit();
    }

    @Test
    public void malformedStartCannotEnableDemo() throws Exception {
        context().getSharedPreferences("demo_mode", 0).edit().clear().commit();
        DemoModeStore demo = new DemoModeStore(context());
        assertFalse(demo.enter(new JSONObject().put("token", "synthetic-demo"), "https://household.example"));
        assertFalse(demo.isEnabled());
    }

    @Test
    public void encryptedDemoTokensCannotBeCopiedIntoAnotherSessionScope() {
        Context context = context();
        SecureSessionStore first = new SecureSessionStore(context, "demo_test_first");
        SecureSessionStore second = new SecureSessionStore(context, "demo_test_second");
        assertTrue(first.save("synthetic-demo", "https://household.example"));
        String sealed = context.getSharedPreferences("secure_session_demo_test_first", 0).getString("token", "");
        context.getSharedPreferences("secure_session_demo_test_second", 0).edit().putString("token", sealed).commit();
        assertEquals("", second.load("https://household.example"));
        assertEquals("synthetic-demo", first.load("https://household.example"));
        first.clear(); second.clear();
    }
}
