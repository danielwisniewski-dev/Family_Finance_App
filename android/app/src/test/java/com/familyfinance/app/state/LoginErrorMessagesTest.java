package com.familyfinance.app.state;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;
import static org.junit.Assert.assertFalse;

public final class LoginErrorMessagesTest {
    @Test
    public void explainsBackendUnreachable() {
        String message = LoginErrorMessages.fromException(
                new Exception("Could not reach backend API at http://10.0.2.2:8080")
        );

        assertTrue(message.contains("Couldn't reach Ledger"));
        assertTrue(message.contains("First-time setup"));
        assertFalse(message.contains("http://10.0.2.2:8080"));
    }

    @Test
    public void explainsInvalidCredentialsWithoutDemoCredentialHint() {
        String message = LoginErrorMessages.fromException(
                new Exception("Invalid credentials")
        );

        assertEquals("Incorrect username/email or password. Please try again.", message);
    }

    @Test
    public void explainsExpiredSession() {
        String message = LoginErrorMessages.fromException(
                new Exception("Login required or session expired. Please log in again.")
        );

        assertEquals("Session expired. Please log in again.", message);
    }
}
