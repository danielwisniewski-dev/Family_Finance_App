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
        versionCode = 1
        versionName = "0.4.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
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
}
