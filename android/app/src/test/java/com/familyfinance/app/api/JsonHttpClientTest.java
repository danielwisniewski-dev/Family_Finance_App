package com.familyfinance.app.api;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Arrays;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.Assert.*;

public final class JsonHttpClientTest {
    private ServerSocket server;
    private ExecutorService worker;
    private String baseUrl;
    private final Map<String, Response> responses = new ConcurrentHashMap<>();
    private final Map<String, String> requestHeaders = new ConcurrentHashMap<>();
    private final AtomicReference<Exception> serverError = new AtomicReference<>();

    @Before
    public void startLocalServer() throws Exception {
        server = new ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"));
        baseUrl = "http://127.0.0.1:" + server.getLocalPort();
        worker = Executors.newSingleThreadExecutor();
        worker.execute(() -> {
            while (!server.isClosed()) {
                try (Socket socket = server.accept()) {
                    socket.setSoTimeout(2000);
                    BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.UTF_8));
                    String request = reader.readLine();
                    String path = request.split(" ")[1];
                    StringBuilder headers = new StringBuilder();
                    String line;
                    while ((line = reader.readLine()) != null && !line.isEmpty()) {
                        headers.append(line).append("\n");
                    }
                    requestHeaders.put(path, headers.toString());
                    Response response = responses.get(path);
                    if (response == null) {
                        response = new Response(404, "{}", null);
                    }
                    byte[] body = response.body.getBytes(StandardCharsets.UTF_8);
                    String header = "HTTP/1.1 " + response.status + " Test\r\nContent-Length: " + body.length
                            + "\r\nConnection: close\r\n"
                            + (response.location == null ? "" : "Location: " + response.location + "\r\n") + "\r\n";
                    socket.getOutputStream().write(header.getBytes(StandardCharsets.UTF_8));
                    socket.getOutputStream().write(body);
                    socket.getOutputStream().flush();
                } catch (Exception exception) {
                    if (!server.isClosed()) {
                        serverError.set(exception);
                    }
                }
            }
        });
    }

    @After
    public void stopLocalServer() throws Exception {
        server.close();
        worker.shutdownNow();
        worker.awaitTermination(2, TimeUnit.SECONDS);
        assertNull(serverError.get());
    }

    private void respond(String path, int status, String body) {
        responses.put(path, new Response(status, body, null));
    }

    @Test
    public void doesNotFollowRedirectsOrForwardSessionTokens() {
        responses.put("/redirect", new Response(302, "<html>Redirecting</html>", baseUrl + "/target"));
        respond("/target", 200, "{}");
        ApiException error = assertThrows(ApiException.class,
                () -> new JsonHttpClient(baseUrl, "synthetic-test-session").get("/redirect"));
        assertEquals(302, error.status);
        assertEquals("redirect_not_followed", error.code);
        assertTrue(requestHeaders.get("/redirect").contains("Bearer synthetic-test-session"));
        assertFalse(requestHeaders.containsKey("/target"));
    }

    @Test
    public void malformedUnauthorizedResponseStillRequiresLogin() {
        respond("/protected", 401, "<html>synthetic-private-detail</html>");
        ApiException error = assertThrows(ApiException.class, () -> new JsonHttpClient(baseUrl).get("/protected"));
        assertEquals(401, error.status);
        assertTrue(error.getMessage().contains("session expired"));
        assertFalse(error.getMessage().contains("synthetic-private-detail"));
    }

    @Test
    public void malformedSuccessDoesNotInventFinancialData() {
        respond("/summary", 200, "not json");
        ApiException error = assertThrows(ApiException.class, () -> new JsonHttpClient(baseUrl).get("/summary"));
        assertEquals("invalid_response", error.code);
    }

    @Test
    public void rejectsOversizedResponseBeforeParsing() {
        char[] oversized = new char[2 * 1024 * 1024 + 1];
        Arrays.fill(oversized, 'x');
        respond("/large", 200, new String(oversized));
        ApiException error = assertThrows(ApiException.class, () -> new JsonHttpClient(baseUrl).get("/large"));
        assertEquals("invalid_response", error.code);
    }

    @Test
    public void backendErrorCodesAndMessagesSurviveTransport() {
        respond("/split", 400, "{\"message\":\"Split total must equal the transaction amount.\",\"code\":\"validation_error\"}");
        ApiException error = assertThrows(ApiException.class, () -> new JsonHttpClient(baseUrl).get("/split"));
        assertEquals(400, error.status);
        assertEquals("validation_error", error.code);
        assertEquals("Split total must equal the transaction amount.", error.getMessage());
    }

    private static final class Response {
        final int status;
        final String body;
        final String location;
        Response(int status, String body, String location) {
            this.status = status;
            this.body = body;
            this.location = location;
        }
    }
}
