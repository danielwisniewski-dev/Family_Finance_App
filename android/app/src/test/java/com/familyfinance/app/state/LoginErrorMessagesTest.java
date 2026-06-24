package com.familyfinance.app.state;

import org.junit.Test;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertTrue;

public final class LoginErrorMessagesTest {
    @Test
    public void explainsBackendUnreachable() {
        String message = LoginErrorMessages.fromException(
                new Exception("Could not reach backend API"),
                "http://10.0.2.2:8080"
        );

        assertTrue(message.contains("Backend is unreachable"));
        assertTrue(message.contains("http://10.0.2.2:8080"));
    }

    @Test
    public void explainsInvalidCredentialsWithoutDemoCredentialHint() {
        String message = LoginErrorMessages.fromException(
                new Exception("Invalid credentials"),
                "http://10.0.2.2:8080"
        );

        assertEquals("Wrong username/email or password for this local household setup.", message);
    }
}
