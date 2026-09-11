package com.familyfinance.app.state;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

public final class ConnectionSettings {
    private ConnectionSettings() { }

    public static String normalizeBaseUrl(String value) {
        try {
            URI uri = new URI(value == null ? "" : value.trim());
            String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase(Locale.ROOT);
            if (!("http".equals(scheme) || "https".equals(scheme))
                    || uri.getHost() == null || uri.getUserInfo() != null
                    || uri.getQuery() != null || uri.getFragment() != null
                    || uri.getPort() > 65535 || uri.getPort() == 0) {
                throw new IllegalArgumentException("Enter an HTTP or HTTPS backend URL without credentials, a query, or a fragment.");
            }
            String path = uri.getPath() == null ? "" : uri.getPath();
            while (path.endsWith("/")) {
                path = path.substring(0, path.length() - 1);
            }
            int port = uri.getPort();
            if (("http".equals(scheme) && port == 80) || ("https".equals(scheme) && port == 443)) {
                port = -1;
            }
            return new URI(scheme, null, uri.getHost().toLowerCase(Locale.ROOT), port, path, null, null).toASCIIString();
        } catch (URISyntaxException exception) {
            throw new IllegalArgumentException("Enter a valid backend URL.");
        }
    }

    public static String normalizeBaseUrl(String value, boolean allowHttp) {
        String normalized = normalizeBaseUrl(value);
        if (!allowHttp && !normalized.startsWith("https://")) {
            throw new IllegalArgumentException("The private beta requires an HTTPS backend URL.");
        }
        return normalized;
    }

    public static boolean requiresNewSession(String previousUrl, String nextUrl) {
        return !normalizeBaseUrl(previousUrl).equals(normalizeBaseUrl(nextUrl));
    }

    public static int parseBudgetMonthId(String value) {
        try {
            int id = Integer.parseInt(value.trim());
            if (id > 0) {
                return id;
            }
        } catch (RuntimeException ignored) {
            // Give the same actionable message for missing, invalid, and overflowing IDs.
        }
        throw new IllegalArgumentException("Budget month ID must be a positive whole number.");
    }
}
