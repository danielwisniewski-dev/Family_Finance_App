package com.familyfinance.app.state;

import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.GeneralSecurityException;
import java.util.Base64;
import javax.crypto.Cipher;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

/** Authenticated session encryption bound to the exact backend origin. */
public final class SessionCipher {
    private SessionCipher() { }

    public static String encrypt(SecretKey key, String token, String origin) throws GeneralSecurityException {
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.ENCRYPT_MODE, key);
        cipher.updateAAD(origin.getBytes(StandardCharsets.UTF_8));
        byte[] encrypted = cipher.doFinal(token.getBytes(StandardCharsets.UTF_8));
        return Base64.getEncoder().encodeToString(ByteBuffer.allocate(12 + encrypted.length)
                .put(cipher.getIV()).put(encrypted).array());
    }

    public static String decrypt(SecretKey key, String sealed, String origin) throws GeneralSecurityException {
        if (sealed.length() > 8192) throw new GeneralSecurityException("Invalid stored session");
        byte[] bytes;
        try { bytes = Base64.getDecoder().decode(sealed); }
        catch (IllegalArgumentException exception) { throw new GeneralSecurityException("Invalid stored session"); }
        if (bytes.length < 28) throw new GeneralSecurityException("Invalid stored session");
        Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(128, bytes, 0, 12));
        cipher.updateAAD(origin.getBytes(StandardCharsets.UTF_8));
        return new String(cipher.doFinal(bytes, 12, bytes.length - 12), StandardCharsets.UTF_8);
    }
}
