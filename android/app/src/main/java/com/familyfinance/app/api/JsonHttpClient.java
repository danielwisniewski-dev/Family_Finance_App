package com.familyfinance.app.api;

import org.json.JSONObject;

import com.familyfinance.app.state.ConnectionSettings;

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
        this.baseUrl = ConnectionSettings.normalizeBaseUrl(baseUrl);
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
            connection.setInstanceFollowRedirects(false);
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
            if (status >= 300 && status < 400) {
                throw new ApiException("Backend redirected the request. Update the backend URL in settings.", "redirect_not_followed", status);
            }
            String body;
            try {
                body = readBody(status >= 400 ? connection.getErrorStream() : connection.getInputStream());
            } catch (IOException exception) {
                if (status >= 400) {
                    throw ApiException.fromApiError(status, null, path);
                }
                throw new ApiException("Backend response could not be read or exceeds the supported size.", "invalid_response", status);
            }
            JSONObject json;
            try {
                json = body.isEmpty() ? new JSONObject() : new JSONObject(body);
            } catch (Exception exception) {
                if (status >= 400) {
                    throw ApiException.fromApiError(status, null, path);
                }
                throw new ApiException("Backend returned an invalid response. Check the backend URL.", "invalid_response", status);
            }
            if (status >= 400) {
                throw ApiException.fromApiError(status, json, path);
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
            char[] buffer = new char[4096];
            int count;
            while ((count = reader.read(buffer)) != -1) {
                if (builder.length() + count > 2 * 1024 * 1024) {
                    throw new IOException("Backend response exceeds the supported size.");
                }
                builder.append(buffer, 0, count);
            }
        }
        return builder.toString();
    }

}
