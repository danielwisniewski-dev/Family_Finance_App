package com.familyfinance.app.state;

public final class LoginErrorMessages {
    private LoginErrorMessages() {
    }

    public static String fromException(Exception exception, String attemptedBaseUrl) {
        String message = exception.getMessage() == null ? exception.toString() : exception.getMessage();
        if (message.contains("Could not reach backend API")) {
            return "Backend is unreachable at "
                    + attemptedBaseUrl
                    + ". Check the server URL and make sure the backend is running.";
        }
        if (message.contains("Invalid credentials")) {
            return "Wrong username/email or password for this local household setup.";
        }
        if (message.contains("Login required") || message.contains("Authentication required")) {
            return "Session expired. Please log in again.";
        }
        return message;
    }
}
