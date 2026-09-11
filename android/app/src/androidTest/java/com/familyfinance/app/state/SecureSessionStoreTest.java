package com.familyfinance.app.state;

import android.content.Context;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;

@RunWith(AndroidJUnit4.class)
public final class SecureSessionStoreTest {
    private Context getContext() { return InstrumentationRegistry.getInstrumentation().getTargetContext(); }
    @Test
    public void testKeystoreSessionSurvivesReopenAndRejectsDifferentBackend() {
        SecureSessionStore store = new SecureSessionStore(getContext());
        store.clear();
        assertTrue(store.save("synthetic-device-session", "https://household.example"));
        assertEquals("synthetic-device-session", new SecureSessionStore(getContext()).load("https://household.example"));
        assertFalse(getContext().getSharedPreferences("secure_session", 0).getString("token", "").contains("synthetic-device-session"));
        assertEquals("", store.load("https://different.example"));
        assertEquals("", store.load("https://household.example"));
        assertTrue(store.save("synthetic-device-session", "https://household.example"));
        store.clear();
        assertEquals("", store.load("https://household.example"));
    }
}
