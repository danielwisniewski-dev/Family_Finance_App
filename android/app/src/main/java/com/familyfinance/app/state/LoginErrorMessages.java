package com.familyfinance.app.state;

public final class LoginErrorMessages {
    private LoginErrorMessages() {
    }

    public static String fromException(Exception exception) {
        String message = exception.getMessage() == null ? exception.toString() : exception.getMessage();
        if (message.contains("Could not reach backend API")) {
            return "Couldn't reach Ledger. Check your connection, or open First-time setup to review the server details.";
        }
        if (message.contains("Invalid credentials")) {
            return "Incorrect username/email or password. Please try again.";
        }
        if (message.contains("Login required") || message.contains("Authentication required")) {
            return "Session expired. Please log in again.";
        }
        return message;
    }
}
