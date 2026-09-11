package com.familyfinance.app.state;

import org.junit.Test;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import java.security.GeneralSecurityException;
import java.util.Base64;
import static org.junit.Assert.*;

public final class SessionCipherTest {
    @Test public void encryptedSessionIsBoundToBackendAndKeyAndRejectsTampering() throws Exception {
        KeyGenerator generator = KeyGenerator.getInstance("AES");
        generator.init(256);
        SecretKey key = generator.generateKey();
        String origin = "https://household.example";
        String sealed = SessionCipher.encrypt(key, "synthetic-bearer", origin);
        assertFalse(sealed.contains("synthetic-bearer"));
        assertEquals("synthetic-bearer", SessionCipher.decrypt(key, sealed, origin));
        assertNotEquals(sealed, SessionCipher.encrypt(key, "synthetic-bearer", origin));
        assertThrows(GeneralSecurityException.class, () -> SessionCipher.decrypt(key, sealed, "https://other.example"));
        assertThrows(GeneralSecurityException.class, () -> SessionCipher.decrypt(generator.generateKey(), sealed, origin));
        byte[] bytes = Base64.getDecoder().decode(sealed);
        bytes[bytes.length - 1] ^= 1;
        assertThrows(GeneralSecurityException.class, () -> SessionCipher.decrypt(key, Base64.getEncoder().encodeToString(bytes), origin));
    }

    @Test public void releaseUrlValidationRequiresHttps() {
        assertThrows(IllegalArgumentException.class, () -> ConnectionSettings.normalizeBaseUrl("http://example.com", false));
        assertEquals("https://example.com", ConnectionSettings.normalizeBaseUrl("https://example.com/", false));
        assertEquals("http://localhost:8080", ConnectionSettings.normalizeBaseUrl("http://localhost:8080", true));
    }
}
