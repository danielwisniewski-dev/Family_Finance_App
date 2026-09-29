package com.familyfinance.app.api;

import org.junit.After;
import org.junit.Before;
import org.junit.Test;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.Arrays;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import java.util.Queue;
import java.util.concurrent.ConcurrentLinkedQueue;

import static org.junit.Assert.*;

public final class JsonHttpClientTest {
    private ServerSocket server;
    private ExecutorService worker;
    private String baseUrl;
    private final Map<String, Response> responses = new ConcurrentHashMap<>();
    private final Map<String, Queue<Response>> responseSequences = new ConcurrentHashMap<>();
    private final Map<String, String> requestHeaders = new ConcurrentHashMap<>();
    private final AtomicReference<Exception> serverError = new AtomicReference<>();
    private final List<String> requestOrder = Collections.synchronizedList(new ArrayList<>());

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
                    int length = 0;
                    while ((line = reader.readLine()) != null && !line.isEmpty()) {
                        headers.append(line).append("\n");
                        if (line.toLowerCase().startsWith("content-length:")) {
                            length = Integer.parseInt(line.substring(line.indexOf(':') + 1).trim());
                        }
                    }
                    char[] payload = new char[length];
                    int read = 0;
                    while (read < length) {
                        int count = reader.read(payload, read, length - read);
                        if (count < 0) throw new IllegalStateException("Incomplete request body");
                        read += count;
                    }
                    String key = path;
                    if ("/plaid/sync".equals(path)) {
                        JSONObject json = new JSONObject(new String(payload));
                        key += ":" + json.getInt("plaid_item_id") + ":" + json.getString("sync_type");
                    } else if ("/plaid/refresh".equals(path)) {
                        key += ":" + new JSONObject(new String(payload)).getInt("plaid_item_id");
                    }
                    requestOrder.add(key);
                    requestHeaders.put(path, headers.toString());
                    Response response = responses.getOrDefault(key, responses.get(path));
                    Queue<Response> sequence = responseSequences.get(key);
                    if (sequence != null && !sequence.isEmpty()) response = sequence.remove();
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
    public void ordinaryBillEditPreservesItsExistingFundButExplicitUnlinkSendsNull() throws Exception {
        JSONObject unchanged = FamilyFinanceApi.expectedBillUpdatePayload("Annual bill", 10000, "2026-10-01", true, 7, false);
        assertFalse(unchanged.has("reserve_fund_id"));
        JSONObject unlink = FamilyFinanceApi.expectedBillUpdatePayload("Annual bill", 10000, "2026-10-01", true, null, true);
        assertTrue(unlink.has("reserve_fund_id"));
        assertTrue(unlink.isNull("reserve_fund_id"));
    }

    private FamilyFinanceApi spendingApi() {
        respond("/budget-months/1/bank-status", 200,
                "{\"enabled\":true,\"connection_id\":7,\"accounts\":[{\"plaid_item_id\":7},{\"plaid_item_id\":7},{\"plaid_item_id\":8}]}");
        respond("/plaid/sync", 200, "{\"success\":true}");
        respond("/safe-to-spend", 200, "{\"warning_level\":\"caution\",\"category_name\":\"Food\",\"required_phrase\":\"Synthetic backend answer\","
                + "\"category_remaining_before_cents\":1000,\"category_remaining_after_cents\":500,"
                + "\"cash_after_bills_before_purchase_cents\":2000,\"cash_after_purchase_and_bills_cents\":1500}");
        return new FamilyFinanceApi(new JsonHttpClient(baseUrl, "synthetic-test-session"));
    }

    @Test
    public void safeToSpendSyncsEachConnectionOnceBeforeUsingBackendAnswer() throws Exception {
        assertEquals("Synthetic backend answer", spendingApi().syncAndCheckSafeToSpend(1, 3, 500).requiredPhrase);
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/sync:7:balance",
                "/plaid/sync:7:transaction", "/plaid/sync:8:balance", "/plaid/sync:8:transaction", "/safe-to-spend"), requestOrder);
    }

    @Test
    public void dashboardSyncOnlyImportsAvailableDataAndDeduplicatesConnections() throws Exception {
        spendingApi().syncAvailableBankData(1);
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/sync:7:balance",
                "/plaid/sync:7:transaction", "/plaid/sync:8:balance", "/plaid/sync:8:transaction",
                "/budget-months/1/bank-status"), requestOrder);
        assertFalse(requestOrder.stream().anyMatch(path -> path.startsWith("/plaid/refresh")));
    }

    private String refreshResponse(String state, int inserted) {
        return "{\"success\":true,\"request_sent\":true,\"inserted_transactions\":" + inserted
                + ",\"updated_transactions\":0,\"removed_transactions\":0,\"refresh\":{\"state\":\"" + state
                + "\",\"message\":\"Synthetic progress\",\"retry_after_seconds\":30,\"can_request\":false}}";
    }

    private FamilyFinanceApi refreshApi() {
        respond("/budget-months/1/bank-status", 200,
                "{\"enabled\":true,\"connection_id\":7,\"accounts\":[{\"plaid_item_id\":7},{\"plaid_item_id\":7}]}");
        respond("/plaid/refresh", 200, refreshResponse("pending", 0));
        respond("/plaid/sync:7:balance", 200, "{\"success\":true}");
        respond("/plaid/sync:7:transaction", 200, refreshResponse("pending", 0));
        return new FamilyFinanceApi(new JsonHttpClient(baseUrl, "synthetic-test-session"));
    }

    @Test
    public void freshRequestPollsImportsOnlyWithBoundedWaits() throws Exception {
        List<Long> waits = new ArrayList<>();
        List<String> states = new ArrayList<>();
        assertEquals("pending", refreshApi().requestFreshBankData(1, state -> states.add(state.state), waits::add).state);
        assertEquals(Arrays.asList(5000L, 10000L, 20000L), waits);
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/refresh:7"));
        assertEquals(4, Collections.frequency(requestOrder, "/plaid/sync:7:transaction"));
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/sync:7:balance"));
        assertFalse(states.contains("checked"));
    }

    @Test
    public void emptyCheckedImportStillWaitsForStreamToCatchUp() throws Exception {
        FamilyFinanceApi api = refreshApi();
        Queue<Response> sequence = new ConcurrentLinkedQueue<>();
        sequence.add(new Response(200, refreshResponse("checked", 0), null));
        sequence.add(new Response(200, refreshResponse("checked", 3), null));
        responseSequences.put("/plaid/sync:7:transaction", sequence);
        List<Long> waits = new ArrayList<>();
        assertTrue(api.requestFreshBankData(1, null, waits::add).isChecked());
        assertEquals(Arrays.asList(5000L), waits);
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/refresh:7"));
        assertEquals(2, Collections.frequency(requestOrder, "/plaid/sync:7:transaction"));
    }

    @Test
    public void checkedButEmptyImportsAreBoundedAndNeverRepeatBankRequest() throws Exception {
        FamilyFinanceApi api = refreshApi();
        respond("/plaid/sync:7:transaction", 200, refreshResponse("checked", 0));
        List<Long> waits = new ArrayList<>();
        assertTrue(api.requestFreshBankData(1, null, waits::add).isChecked());
        assertEquals(3, waits.size());
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/refresh:7"));
        assertEquals(4, Collections.frequency(requestOrder, "/plaid/sync:7:transaction"));
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/sync:7:balance"));
    }

    @Test
    public void ambiguousBankRequestImportsWithoutResendingRequest() throws Exception {
        FamilyFinanceApi api = refreshApi();
        respond("/plaid/refresh", 200, refreshResponse("unknown", 0).replace("\"success\":true", "\"success\":false"));
        respond("/plaid/sync:7:transaction", 200, refreshResponse("checked", 2));
        assertTrue(api.requestFreshBankData(1, null, delay -> fail("No wait needed after imported changes")).isChecked());
        assertEquals(1, Collections.frequency(requestOrder, "/plaid/refresh:7"));
    }

    @Test
    public void failedRefreshResponseIsNotRetriedOrCalledAnImportSuccess() throws Exception {
        FamilyFinanceApi api = refreshApi();
        respond("/plaid/refresh", 200, refreshResponse("failed", 0).replace("\"success\":true", "\"success\":false"));
        assertTrue(api.requestFreshBankData(1, null, delay -> fail("No wait after denial")).isFailed());
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/refresh:7"), requestOrder);
    }

    @Test
    public void malformedOrLostRefreshResponseNeverReplaysRefreshPost() {
        FamilyFinanceApi api = refreshApi();
        respond("/plaid/refresh", 200, "not-json");
        assertThrows(ApiException.class, () -> api.requestFreshBankData(1, null, delay -> fail("No replay after ambiguous response")));
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/refresh:7"), requestOrder);
    }

    @Test
    public void balanceFailureStopsSpendingCheck() {
        FamilyFinanceApi api = spendingApi();
        respond("/plaid/sync:7:balance", 200, "{\"success\":false,\"error_message\":\"Reconnect USAA\"}");
        assertEquals("Reconnect USAA", assertThrows(ApiException.class,
                () -> api.syncAndCheckSafeToSpend(1, 3, 500)).getMessage());
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/sync:7:balance"), requestOrder);
    }

    @Test
    public void transactionFailureNeverFallsBackToSavedSpendingResult() {
        FamilyFinanceApi api = spendingApi();
        respond("/plaid/sync:7:transaction", 200, "{\"success\":false}");
        assertThrows(ApiException.class, () -> api.syncAndCheckSafeToSpend(1, 3, 500));
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/plaid/sync:7:balance", "/plaid/sync:7:transaction"), requestOrder);
    }

    @Test
    public void successfulSyncDoesNotBypassTransactionReviewOrReconciliation() {
        FamilyFinanceApi api = spendingApi();
        respond("/safe-to-spend", 400, "{\"message\":\"Review imported spending first\",\"code\":\"validation_error\"}");
        assertEquals("Review imported spending first", assertThrows(ApiException.class,
                () -> api.syncAndCheckSafeToSpend(1, 3, 500)).getMessage());
        assertEquals("/safe-to-spend", requestOrder.get(requestOrder.size() - 1));
    }

    @Test
    public void manualBudgetsCheckWithoutBankCalls() throws Exception {
        FamilyFinanceApi api = spendingApi();
        respond("/budget-months/1/bank-status", 200, "{\"enabled\":false}");
        api.syncAndCheckSafeToSpend(1, 3, 500);
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/safe-to-spend"), requestOrder);
    }

    @Test
    public void missingConnectionOrFailedStatusDoesNotCheckSpending() {
        FamilyFinanceApi api = spendingApi();
        respond("/budget-months/1/bank-status", 200, "{\"enabled\":true,\"accounts\":[]}");
        assertThrows(ApiException.class, () -> api.syncAndCheckSafeToSpend(1, 3, 500));
        respond("/budget-months/1/bank-status", 401, "{}");
        assertEquals(401, assertThrows(ApiException.class, () -> api.syncAndCheckSafeToSpend(1, 3, 500)).status);
        respond("/budget-months/1/bank-status", 200, "{}");
        assertThrows(ApiException.class, () -> api.syncAndCheckSafeToSpend(1, 3, 500));
        assertEquals(Arrays.asList("/budget-months/1/bank-status", "/budget-months/1/bank-status", "/budget-months/1/bank-status"), requestOrder);
    }

    @Test
    public void bankSyncReportsFailureEvenWithSuccessfulHttpStatus() {
        respond("/plaid/sync", 200, "{\"success\":false,\"error_message\":\"Reconnect USAA in Settings\"}");
        ApiException error = assertThrows(ApiException.class,
                () -> new FamilyFinanceApi(new JsonHttpClient(baseUrl, "synthetic-test-session")).syncPlaid(1, "balance"));
        assertEquals("Reconnect USAA in Settings", error.getMessage());
    }

    @Test
    public void bankSyncRequiresExplicitSuccess() {
        respond("/plaid/sync", 200, "{}");
        assertThrows(ApiException.class,
                () -> new FamilyFinanceApi(new JsonHttpClient(baseUrl)).syncPlaid(1, "transaction"));
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
