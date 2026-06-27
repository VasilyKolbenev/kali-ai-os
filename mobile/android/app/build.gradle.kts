import java.util.Properties
import java.io.FileInputStream

plugins {
    id("com.android.application")
    // The Flutter Gradle Plugin must be applied after the Android and Kotlin Gradle plugins.
    id("dev.flutter.flutter-gradle-plugin")
}

// Release signing is read from a gitignored `android/keystore.properties` (or
// the matching env vars in CI). The real upload keystore is provided out of
// band by the maintainer; see keystore.properties.example. When the file is
// absent we fall back to debug signing so `flutter run --release` and clean
// checkouts still build.
val keystorePropertiesFile = rootProject.file("keystore.properties")
val keystoreProperties = Properties().apply {
    if (keystorePropertiesFile.exists()) {
        load(FileInputStream(keystorePropertiesFile))
    }
}

fun signingProp(key: String, env: String): String? =
    keystoreProperties.getProperty(key) ?: System.getenv(env)

val hasReleaseSigning =
    signingProp("storeFile", "KALI_UPLOAD_STORE_FILE") != null

android {
    // namespace matches the store identity; MainActivity lives in this package
    // (android/app/src/main/kotlin/ai/kali/mobile/MainActivity.kt).
    namespace = "ai.kali.mobile"
    compileSdk = flutter.compileSdkVersion
    ndkVersion = flutter.ndkVersion

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    defaultConfig {
        // Real application ID for store distribution (was com.example placeholder).
        applicationId = "ai.kali.mobile"
        minSdk = 24
        targetSdk = flutter.targetSdkVersion
        versionCode = flutter.versionCode
        versionName = flutter.versionName
    }

    signingConfigs {
        create("release") {
            if (hasReleaseSigning) {
                storeFile = signingProp("storeFile", "KALI_UPLOAD_STORE_FILE")?.let { file(it) }
                storePassword = signingProp("storePassword", "KALI_UPLOAD_STORE_PASSWORD")
                keyAlias = signingProp("keyAlias", "KALI_UPLOAD_KEY_ALIAS")
                keyPassword = signingProp("keyPassword", "KALI_UPLOAD_KEY_PASSWORD")
            }
        }
    }

    buildTypes {
        release {
            // Use the real upload key when keystore.properties (or env) provides
            // one; otherwise fall back to debug so local/release builds still run.
            signingConfig = if (hasReleaseSigning) {
                signingConfigs.getByName("release")
            } else {
                signingConfigs.getByName("debug")
            }
        }
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

flutter {
    source = "../.."
}
