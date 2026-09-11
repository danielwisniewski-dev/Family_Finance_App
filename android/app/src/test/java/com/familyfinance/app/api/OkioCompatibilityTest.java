package com.familyfinance.app.api;

import org.junit.Test;

import java.io.ByteArrayOutputStream;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.zip.GZIPOutputStream;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okio.Buffer;
import okio.BufferedSource;
import okio.GzipSource;
import okio.Okio;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;

public final class OkioCompatibilityTest {
    private static final String SYNTHETIC_JSON = "{\"synthetic\":true,\"amount_cents\":1573}";

    @Test
    public void normalGzipAndBufferRemainCompatible() throws IOException {
        try (BufferedSource source = Okio.buffer(new GzipSource(new Buffer().write(gzip(SYNTHETIC_JSON))))) {
            assertEquals(SYNTHETIC_JSON, source.readUtf8());
        }
    }

    @Test
    public void largeUnsignedGzipExtraLengthRemainsReadable() throws IOException {
        // CVE-2023-3635: XLEN is unsigned, including lengths with the high bit set.
        try (BufferedSource source = Okio.buffer(new GzipSource(new Buffer().write(gzipWithExtraField(32768))))) {
            assertEquals(SYNTHETIC_JSON, source.readUtf8());
        }
    }

    @Test(timeout = 5000)
    public void truncatedLargeExtraFieldFailsAsIoException() {
        Buffer truncated = new Buffer()
                .write(new byte[]{0x1f, (byte) 0x8b, 8, 4, 0, 0, 0, 0, 0, 0})
                .writeShortLe(32768);
        assertThrows(IOException.class, () -> {
            try (BufferedSource source = Okio.buffer(new GzipSource(truncated))) {
                source.readUtf8();
            }
        });
    }

    @Test(timeout = 10000)
    public void existingOkHttpTransparentlyDecodesLocalGzipResponse() throws Exception {
        byte[] compressed = gzipWithExtraField(32768);
        ServerSocket server = new ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"));
        ExecutorService worker = Executors.newSingleThreadExecutor();
        Future<?> serving = worker.submit(() -> {
            try (Socket socket = server.accept()) {
                socket.setSoTimeout(2000);
                BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
                String line;
                while ((line = reader.readLine()) != null && !line.isEmpty()) {
                    // Consume the synthetic request headers before responding.
                }
                String headers = "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        + "Content-Encoding: gzip\r\nContent-Length: " + compressed.length
                        + "\r\nConnection: close\r\n\r\n";
                socket.getOutputStream().write(headers.getBytes(StandardCharsets.US_ASCII));
                socket.getOutputStream().write(compressed);
                socket.getOutputStream().flush();
            }
            return null;
        });
        OkHttpClient client = new OkHttpClient.Builder().callTimeout(5, TimeUnit.SECONDS).build();
        try {
            String url = "http://127.0.0.1:" + server.getLocalPort() + "/synthetic";
            try (Response response = client.newCall(new Request.Builder().url(url).build()).execute()) {
                assertEquals(200, response.code());
                assertEquals(SYNTHETIC_JSON, response.body().string());
            }
            serving.get(5, TimeUnit.SECONDS);
        } finally {
            server.close();
            worker.shutdownNow();
            worker.awaitTermination(2, TimeUnit.SECONDS);
            client.connectionPool().evictAll();
            client.dispatcher().executorService().shutdownNow();
        }
    }

    private static byte[] gzip(String content) throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        try (GZIPOutputStream output = new GZIPOutputStream(bytes)) {
            output.write(content.getBytes(StandardCharsets.UTF_8));
        }
        return bytes.toByteArray();
    }

    private static byte[] gzipWithExtraField(int length) throws IOException {
        byte[] original = gzip(SYNTHETIC_JSON);
        original[3] |= 4;
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        bytes.write(original, 0, 10);
        bytes.write(length & 0xff);
        bytes.write((length >>> 8) & 0xff);
        bytes.write(new byte[length]);
        bytes.write(original, 10, original.length - 10);
        return bytes.toByteArray();
    }
}
