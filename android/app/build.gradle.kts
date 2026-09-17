plugins {
    id("com.android.application")
}

android {
    namespace = "com.familyfinance.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.familyfinance.app"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "0.6.1-interface"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }

    buildFeatures { buildConfig = true }

    val betaUrl = providers.gradleProperty("betaBackendUrl").orElse("https://configure-backend.invalid").get()
    require(betaUrl.matches(Regex("https://[A-Za-z0-9.-]+(:[0-9]+)?/?"))) { "betaBackendUrl must be an HTTPS server origin" }
    val signingPath = System.getenv("FF_ANDROID_KEYSTORE")
    if (!signingPath.isNullOrBlank()) {
        signingConfigs {
            create("privateBeta") {
                storeFile = file(signingPath)
                storePassword = System.getenv("FF_ANDROID_STORE_PASSWORD")
                keyAlias = "family-finance-beta"
                keyPassword = System.getenv("FF_ANDROID_KEY_PASSWORD")
            }
        }
    }
    buildTypes {
        getByName("debug") {
            buildConfigField("String", "DEFAULT_BACKEND_URL", "\"http://10.0.2.2:8080\"")
            buildConfigField("boolean", "BANK_LINKING_ENABLED", "true")
        }
        getByName("release") {
            isDebuggable = false
            buildConfigField("String", "DEFAULT_BACKEND_URL", "\"$betaUrl\"")
            buildConfigField("boolean", "BANK_LINKING_ENABLED", "true")
            if (!signingPath.isNullOrBlank()) signingConfig = signingConfigs.getByName("privateBeta")
        }
    }
}

dependencies {
    implementation("com.plaid.link:sdk-core:5.5.2")
    constraints {
        implementation("com.squareup.okio:okio:3.4.0") {
            because("Fix CVE-2023-3635 in Plaid's transitive Okio dependency")
        }
    }

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
    androidTestImplementation("androidx.test:runner:1.7.0")
    androidTestImplementation("androidx.test.ext:junit:1.3.0")
}
