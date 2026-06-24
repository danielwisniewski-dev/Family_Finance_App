package com.familyfinance.app.api;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

public final class JsonHttpClient {
    private final String baseUrl;
    private final String bearerToken;

    public JsonHttpClient(String baseUrl) {
        this(baseUrl, null);
    }

    public JsonHttpClient(String baseUrl, String bearerToken) {
        this.baseUrl = trimTrailingSlash(baseUrl);
        this.bearerToken = bearerToken == null ? "" : bearerToken.trim();
    }

    public JSONObject get(String path) throws ApiException {
        return request("GET", path, null);
    }

    public JSONObject post(String path, JSONObject payload) throws ApiException {
        return request("POST", path, payload);
    }

    public JSONObject patch(String path, JSONObject payload) throws ApiException {
        return request("PATCH", path, payload);
    }

    public JSONObject delete(String path) throws ApiException {
        return request("DELETE", path, null);
    }

    private JSONObject request(String method, String path, JSONObject payload) throws ApiException {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(baseUrl + path);
            connection = (HttpURLConnection) url.openConnection();
            connection.setRequestMethod(method);
            connection.setConnectTimeout(5_000);
            connection.setReadTimeout(5_000);
            connection.setRequestProperty("Accept", "application/json");
            if (!bearerToken.isEmpty()) {
                connection.setRequestProperty("Authorization", "Bearer " + bearerToken);
            }
            if (payload != null) {
                connection.setDoOutput(true);
                connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);
                connection.setRequestProperty("Content-Length", Integer.toString(body.length));
                try (OutputStream output = connection.getOutputStream()) {
                    output.write(body);
                }
            }

            int status = connection.getResponseCode();
            String body = readBody(status >= 400 ? connection.getErrorStream() : connection.getInputStream());
            JSONObject json = body.isEmpty() ? new JSONObject() : new JSONObject(body);
            if (status >= 400) {
                if (status == 401 && !"/auth/login".equals(path)) {
                    throw new ApiException("Login required or session expired. Please log in again.");
                }
                throw new ApiException(json.optString("error", "API error " + status));
            }
            return json;
        } catch (ApiException exception) {
            throw exception;
        } catch (Exception exception) {
            throw new ApiException("Could not reach backend API", exception);
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
        }
    }

    private static String readBody(InputStream stream) throws IOException {
        if (stream == null) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(stream, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line);
            }
        }
        return builder.toString();
    }

    private static String trimTrailingSlash(String value) {
        if (value == null || value.isEmpty()) {
            return "http://10.0.2.2:8080";
        }
        while (value.endsWith("/")) {
            value = value.substring(0, value.length() - 1);
        }
        return value;
    }
}
