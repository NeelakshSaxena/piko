import java.util.Properties

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
}

// Firebase client settings are not secrets (they ship in every Firebase app) but they are specific to one
// Firebase project, so they come from android/local.properties (git-ignored) or -P properties, never from
// source. Unset means "push not configured on this build": the app builds, runs and falls back to polling.
val localProps = Properties().apply {
    val f = rootProject.file("local.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}
fun firebaseSetting(name: String): String =
    (providers.gradleProperty(name).orNull ?: localProps.getProperty(name) ?: "").replace("\"", "")

android {
    namespace = "app.piko.android"
    compileSdk = 36

    defaultConfig {
        applicationId = "app.piko.android"
        minSdk = 31
        targetSdk = 36
        versionCode = 1
        versionName = "0.4.0"
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        buildConfigField("String", "FIREBASE_PROJECT_ID", "\"${firebaseSetting("piko.firebase.projectId")}\"")
        buildConfigField("String", "FIREBASE_APP_ID", "\"${firebaseSetting("piko.firebase.appId")}\"")
        buildConfigField("String", "FIREBASE_API_KEY", "\"${firebaseSetting("piko.firebase.apiKey")}\"")
        buildConfigField("String", "FIREBASE_SENDER_ID", "\"${firebaseSetting("piko.firebase.senderId")}\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    testOptions {
        unitTests.isReturnDefaultValues = true
    }

    // Queue contract tests run on the JVM (in-memory store) and on a device (SQLite store).
    sourceSets {
        getByName("test").kotlin.directories.add("src/sharedTest/kotlin")
        getByName("androidTest").kotlin.directories.add("src/sharedTest/kotlin")
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.foundation)
    implementation(libs.androidx.compose.material3)
    implementation(libs.kotlinx.coroutines.android)
    implementation(platform(libs.firebase.bom))
    implementation(libs.firebase.messaging)

    testImplementation(libs.junit)
    testImplementation(libs.org.json)
    testImplementation(libs.kotlinx.coroutines.test)

    androidTestImplementation(libs.junit)
    androidTestImplementation(libs.androidx.test.ext.junit)
    androidTestImplementation(libs.androidx.test.runner)
    androidTestImplementation(libs.androidx.test.core)
    androidTestImplementation(libs.kotlinx.coroutines.test)
}
