package com.familyfinance.app.state;

import org.junit.Test;

import static org.junit.Assert.*;

public final class ConnectionSettingsTest {
    @Test
    public void normalizesEquivalentServerAddresses() {
        assertEquals("http://localhost:8080", ConnectionSettings.normalizeBaseUrl(" HTTP://LOCALHOST:8080/// "));
        assertFalse(ConnectionSettings.requiresNewSession("http://localhost:80", "http://LOCALHOST/"));
        assertFalse(ConnectionSettings.requiresNewSession("https://localhost:443/", "https://localhost"));
    }

    @Test
    public void newAuthorityTransportOrPathRequiresAnotherLogin() {
        for (String next : new String[]{"http://other:8080", "https://localhost:8080", "http://localhost:8090", "http://localhost:8080/other"}) {
            assertTrue(ConnectionSettings.requiresNewSession("http://localhost:8080", next));
        }
    }

    @Test
    public void rejectsUnsafeOrMalformedConnectionValues() {
        for (String value : new String[]{"", "localhost:8080", "file:///tmp/test", "https://user:password@host", "http://host?token=test",
                "http://host/#fragment", "http://host:0", "http://host:65536", "http://host:abc", "http://host with spaces"}) {
            assertThrows(value, IllegalArgumentException.class, () -> ConnectionSettings.normalizeBaseUrl(value));
        }
        assertEquals(4, ConnectionSettings.parseBudgetMonthId(" 4 "));
        for (String value : new String[]{"0", "-1", "1.5", "", "2147483648"}) {
            assertThrows(IllegalArgumentException.class, () -> ConnectionSettings.parseBudgetMonthId(value));
        }
    }
}
