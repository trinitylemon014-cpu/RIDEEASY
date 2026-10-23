# Mobile Packaging Guide (Capacitor for Android & iOS)
**RideEasy — MOVE. TRAVEL. ARRIVE.**
**Emtrixz Technology Company**

## Overview
RideEasy is architected as a mobile-first Progressive Web Application (PWA). This guide describes how to bundle the responsive web interface into native **Android APK / AAB** and **iOS IPA** packages using **Capacitor**.

> **Note on App Store Readiness:** The web application is built to mobile-first responsive standards. However, official Google Play and Apple App Store distribution requires completion of the native signing certificates, camera/location permissions, and privacy policy filings detailed below before store readiness can be claimed.

---

## 1. Native App Identifiers
- **App Name**: RideEasy
- **Android Package ID**: `ug.rideeasy.app`
- **iOS Bundle ID**: `ug.rideeasy.app`
- **Developer Organization**: Emtrixz Technology Company Ltd

---

## 2. Capacitor Initialization

```bash
# In the project directory:
npm install @capacitor/core @capacitor/cli @capacitor/android @capacitor/ios
npm install @capacitor/geolocation @capacitor/push-notifications @capacitor/camera

# Initialize Capacitor configuration
npx cap init "RideEasy" "ug.rideeasy.app" --web-dir "app/static"
```

Configure `capacitor.config.json`:
```json
{
  "appId": "ug.rideeasy.app",
  "appName": "RideEasy",
  "webDir": "app/static",
  "server": {
    "url": "https://app.rideeasy.ug",
    "cleartext": false
  },
  "plugins": {
    "PushNotifications": {
      "presentationOptions": ["badge", "sound", "alert"]
    }
  }
}
```

---

## 3. Native Permissions Configuration

### Android (`android/app/src/main/AndroidManifest.xml`)
Add the following required permissions:
```xml
<!-- Precise GPS for Driver Location & Trip Tracking -->
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />

<!-- Camera & Storage for Driver Document Verification -->
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.READ_EXTERNAL_STORAGE" />

<!-- Push Notifications for 5-Stage Flight Reminders & Ride Status -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />
<uses-permission android:name="android.permission.INTERNET" />
```

### iOS (`ios/App/App/Info.plist`)
Add privacy usage description strings:
```xml
<key>NSLocationWhenInUseUsageDescription</key>
<string>RideEasy requires location access to match you with nearby drivers and provide accurate pickup navigation.</string>

<key>NSCameraUsageDescription</key>
<string>RideEasy uses your camera to capture driving permits and national ID documents for driver partner verification.</string>

<key>UIBackgroundModes</key>
<array>
  <string>remote-notification</string>
</array>
```

---

## 4. App Icons & Splash Screens
Use `@capacitor/assets` to automatically generate all required Android mipmap densities and iOS asset catalog scales:
```bash
npm install -g @capacitor/assets
capacitor-assets generate --iconBackgroundColor '#000000' --splashBackgroundColor '#FFFFFF'
```
- Source Icon: `assets/icon.png` (1024x1024 px, monochrome black on white)
- Source Splash: `assets/splash.png` (2732x2732 px, centered RideEasy brand)

---

## 5. Push Notifications Setup
1. **Firebase Cloud Messaging (FCM)**:
   - Download `google-services.json` from the Firebase console.
   - Place in `android/app/google-services.json`.
2. **Apple Push Notification Service (APNs)**:
   - Configure an APNs Auth Key (`.p8`) in your Apple Developer account.
   - Link the APNs key in Firebase or your backend push notification dispatcher.

---

## 6. Android Release Build & Signing
1. Generate release keystore:
   ```bash
   keytool -genkey -v -keystore rideeasy-release.keystore -alias rideeasy -keyalg RSA -keysize 2048 -validity 10000
   ```
2. Build Android App Bundle (`.aab`):
   ```bash
   npx cap copy android
   cd android
   ./gradlew bundleRelease
   ```
3. Upload `app-release.aab` to Google Play Console under Internal Testing track.

---

## 7. iOS Release Build & Archive
1. Open Xcode project:
   ```bash
   npx cap open ios
   ```
2. Select your Apple Developer Team under **Signing & Capabilities**.
3. Choose **Product > Archive**, validate assets, and distribute to **TestFlight**.
