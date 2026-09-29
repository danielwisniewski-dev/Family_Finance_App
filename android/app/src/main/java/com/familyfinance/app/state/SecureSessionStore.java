package com.familyfinance.app.state;

import android.content.Context;
import android.content.SharedPreferences;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import java.security.KeyStore;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;

public final class SecureSessionStore {
    private static final String ALIAS = "family-finance-session-v1";
    private final SharedPreferences preferences;
    private final String scope;

    public SecureSessionStore(Context context) {
        this(context, "real");
    }

    public SecureSessionStore(Context context, String scope) {
        if (!scope.matches("[A-Za-z0-9_-]+")) throw new IllegalArgumentException("Invalid session scope");
        this.scope = scope;
        preferences = context.getSharedPreferences("real".equals(scope) ? "secure_session" : "secure_session_" + scope,
                Context.MODE_PRIVATE);
    }

    private SecretKey key() throws Exception {
        KeyStore store = KeyStore.getInstance("AndroidKeyStore");
        store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                    .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).setKeySize(256).build());
            generator.generateKey();
        }
        return (SecretKey) store.getKey(ALIAS, null);
    }

    public boolean save(String token, String origin) {
        try {
            return preferences.edit().putString("token", SessionCipher.encrypt(key(), token, boundOrigin(origin))).commit();
        } catch (Exception exception) {
            clear();
            return false;
        }
    }

    public String load(String origin) {
        String sealed = preferences.getString("token", "");
        if (sealed.isEmpty()) return "";
        try { return SessionCipher.decrypt(key(), sealed, boundOrigin(origin)); }
        catch (Exception exception) { clear(); return ""; }
    }

    public void clear() {
        preferences.edit().clear().commit();
    }

    private String boundOrigin(String origin) {
        // Preserve existing real sessions; demo ciphertext is additionally bound to its unique scope.
        return "real".equals(scope) ? origin : origin + "|" + scope;
    }
}
